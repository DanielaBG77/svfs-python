"""
retos.py - Demostracion de los 4 RETOS DE AMPLIACION del SVFS
=============================================================
Ejecuta:  python retos.py

Cada reto imprime lo que pasa en pantalla para que tomes capturas como
evidencia. Todos usan discos temporales (reto1.svfs, reto2.svfs, ...) que se
borran al final; no tocan tu disco.svfs.

    RETO 1  Puntero indirecto (archivos de mas de 4096 bytes)
    RETO 2  Subdirectorios
    RETO 3  Primer ajuste vs mejor ajuste (fragmentacion)
    RETO 4  Corte de energia entre las escrituras y analisis con verificar()
"""

import glob
import os

from svfs import (SVFS, CorteDeEnergia, POLITICAS, BLOCK_SIZE, NUM_BLOCKS,
                  NUM_INODES, DATA_START, N_DIRECT, NO_PTR, PTRS_POR_BLOQUE,
                  MAX_BYTES_ARCHIVO)


# ----------------------------------------------------------------------
# Utilidades de impresion
# ----------------------------------------------------------------------
def titulo(texto):
    """Imprime un encabezado grande para separar las secciones."""
    print()
    print('=' * 72)
    print(texto)
    print('=' * 72)


def disco_nuevo(ruta, politica='primer'):
    """Crea un disco desde cero (borra el archivo si ya existia)."""
    if os.path.exists(ruta):
        os.remove(ruta)
    return SVFS(ruta, politica)


def intentar(descripcion, funcion):
    """Ejecuta 'funcion' y muestra si funciono o que error lanzo."""
    # Exception atrapa cualquier error para mostrarlo sin detener la demo.
    try:
        funcion()
        print('  [FUNCIONA] %s' % descripcion)
    except Exception as e:
        print('  [ERROR]    %s -> %s: %s' % (descripcion, type(e).__name__, e))


def mostrar_mapa(fs, sangria='    '):
    """Dibuja el disco: '#' metadatos, '.' libre, letra/numero = inodo dueno,
    '?' = bloque ocupado que nadie reclama."""
    for linea in fs.mapa():
        print(sangria + linea)


# ----------------------------------------------------------------------
# RETO 1 - Puntero indirecto
# ----------------------------------------------------------------------
def reto1():
    titulo('RETO 1 - Puntero indirecto: archivos de mas de 4096 bytes')
    fs = disco_nuevo('reto1.svfs')

    # Contenido reconocible: byte i = i mod 251 (asi detectamos cualquier error)
    datos = bytes(i % 251 for i in range(10000))
    fs.create('grande.bin', datos)

    ino = fs.read_inode(fs.lookup('grande.bin'))
    bloques_datos = fs.blocks_of(ino)
    print('Archivo grande.bin de %d bytes' % ino['tam'])
    print('  Bloques de datos             : %d' % len(bloques_datos))
    print('  Punteros directos del inodo  :', [p for p in ino['directos'] if p != NO_PTR])
    print('  Bloque indirecto (en el inodo): %d' % ino['indirecto'])
    print('  Punteros dentro del indirecto:', bloques_datos[N_DIRECT:])
    print('  Bloques totales que ocupa    : %d (datos + 1 indirecto)'
          % len(fs.all_blocks_of(ino)))
    print('  Contenido leido == original  :', fs.read('grande.bin') == datos)
    print('  verificar()                  :', fs.verificar())
    fs.delete('grande.bin')

    print()
    print('Limites:')
    print('  Teorico = (%d directos + %d indirectos) x %d = %d bytes'
          % (N_DIRECT, PTRS_POR_BLOQUE, BLOCK_SIZE, MAX_BYTES_ARCHIVO))
    # El disco solo tiene 124 bloques de datos. Un archivo de n bloques gasta
    # n + 1 (indirecto) y el directorio raiz necesita 1 mas -> n maximo = 122.
    cabe = (NUM_BLOCKS - DATA_START - 2) * BLOCK_SIZE
    print('  Practico en este disco = (%d - 2) x %d = %d bytes (el disco es chico)'
          % (NUM_BLOCKS - DATA_START, BLOCK_SIZE, cabe))
    intentar('crear archivo de %d bytes (el mas grande que cabe)' % cabe,
             lambda: fs.create('max.bin', bytes(cabe)))
    fs.delete('max.bin')
    intentar('crear archivo de %d bytes (1 byte de mas)' % (cabe + 1),
             lambda: fs.create('pasado.bin', bytes(cabe + 1)))
    intentar('crear archivo de %d bytes (supera el maximo teorico)'
             % (MAX_BYTES_ARCHIVO + 1),
             lambda: fs.create('enorme.bin', bytes(MAX_BYTES_ARCHIVO + 1)))
    print('  verificar() tras los errores :', fs.verificar())
    fs.close()


# ----------------------------------------------------------------------
# RETO 2 - Subdirectorios
# ----------------------------------------------------------------------
def reto2():
    titulo('RETO 2 - Subdirectorios')
    fs = disco_nuevo('reto2.svfs')

    fs.mkdir('docs')
    fs.mkdir('docs/tareas')
    fs.create('docs/tareas/so.txt', b'Taller de Sistemas Operativos')
    fs.create('docs/leeme.txt', b'Hola')
    fs.create('raiz.txt', b'Archivo en la raiz')

    print('Arbol del disco:')
    for linea in fs.arbol():
        print('  ' + linea)
    print()
    print("ls('/')            :", fs.ls('/'))
    print("ls('docs')         :", fs.ls('docs'))
    print("ls('docs/tareas')  :", fs.ls('docs/tareas'))
    print("read('docs/tareas/so.txt') :", fs.read('docs/tareas/so.txt'))
    print('verificar()        :', fs.verificar())

    print()
    print('Casos de error:')
    intentar("mismo nombre en otro directorio: create('docs/raiz.txt')",
             lambda: fs.create('docs/raiz.txt', b'x'))
    intentar("create('noexiste/x.txt') (el directorio padre no existe)",
             lambda: fs.create('noexiste/x.txt', b'x'))
    intentar("create('raiz.txt/x') (un archivo no es directorio)",
             lambda: fs.create('raiz.txt/x', b'x'))
    intentar("read('docs') (es un directorio)", lambda: fs.read('docs'))
    intentar("delete('docs') (usa rmdir)", lambda: fs.delete('docs'))
    intentar("rmdir('docs') con contenido", lambda: fs.rmdir('docs'))

    print()
    print('Limpieza (de adentro hacia afuera):')
    for ruta in ('docs/raiz.txt', 'docs/tareas/so.txt'):
        fs.delete(ruta)
    fs.rmdir('docs/tareas')
    fs.delete('docs/leeme.txt')
    fs.rmdir('docs')
    fs.delete('raiz.txt')
    print('  Arbol final:', fs.arbol())
    print('  Bloques libres: %d de %d | verificar(): %s'
          % (fs.free_blocks(), NUM_BLOCKS - DATA_START, fs.verificar()))
    fs.close()


# ----------------------------------------------------------------------
# RETO 3 - Primer ajuste vs mejor ajuste
# ----------------------------------------------------------------------
def preparar_reto3(politica):
    """Arma un disco con dos huecos de distinto tamano:

        a (10 bloques + 1 indirecto = hueco de 11)   s1 (separador)
        b (4 bloques = hueco de 4)                    s2 (separador)
        relleno: ocupa TODO el resto del disco (105 bloques + 1 indirecto)

    y luego borra 'b' y 'a'. Resultado: el disco solo tiene 2 huecos libres,
    uno de 11 bloques (el primero) y otro de 4 bloques (el segundo)."""
    fs = disco_nuevo('reto3_%s.svfs' % politica, politica)
    fs.create('a', bytes(10 * BLOCK_SIZE))
    fs.create('s1', bytes(BLOCK_SIZE))
    fs.create('b', bytes(4 * BLOCK_SIZE))
    fs.create('s2', bytes(BLOCK_SIZE))
    fs.create('relleno', bytes(105 * BLOCK_SIZE))
    fs.delete('b')
    fs.delete('a')
    return fs


def reto3():
    titulo('RETO 3 - Primer ajuste vs mejor ajuste')
    print('Leyenda del mapa: # metadatos | . libre | letra/numero = n. de inodo')
    print('(0 = directorio raiz, 2 = s1, 4 = s2, 5 = relleno; n1 y n2 toman los')
    print('numeros de inodo que quedaron libres)')
    print('Pasos: se borran a y b (quedan 2 huecos: 11 y 4 bloques); despues se')
    print('crea n1 (4 bloques) y luego n2 (10 bloques + 1 indirecto = 11).')

    resumen = []
    for politica in POLITICAS:
        print()
        print('--- Politica: %s ajuste ---' % politica)
        fs = preparar_reto3(politica)
        antes = fs.fragmentacion()
        print('  Tras borrar a y b: %s' % antes)
        mostrar_mapa(fs)

        fs.create('n1', bytes(4 * BLOCK_SIZE))
        tras_n1 = fs.fragmentacion()
        print('  Tras crear n1 (4 bloques): %s' % tras_n1)
        mostrar_mapa(fs)

        fs.create('n2', bytes(10 * BLOCK_SIZE))
        print('  Tras crear n2 (10 bloques + indirecto):')
        mostrar_mapa(fs)

        resumen.append((politica, tras_n1, fs.fragmentos_de('n1'),
                        fs.fragmentos_de('n2'), fs.verificar()))
        fs.close()

    print()
    print('RESUMEN')
    print('%-8s | huecos tras n1 | mayor hueco | frag. externa | trozos n1 | trozos n2 | verificar'
          % 'politica')
    print('-' * 100)
    for pol, f, fn1, fn2, ver in resumen:
        print('%-8s | %14d | %11d | %12.1f%% | %9d | %9d | %s'
              % (pol, f['huecos'], f['mayor_hueco'], f['externa_pct'], fn1, fn2, ver))
    print('(trozos = en cuantos tramos contiguos quedo guardado el archivo; 1 = entero)')


# ----------------------------------------------------------------------
# RETO 4 - Corte de energia
# ----------------------------------------------------------------------
def verificar_original(fs):
    """El verificar() del taller base: solo comprueba inodo -> bloques
    (bloque repetido o bloque usado pero libre en el mapa de bits)."""
    vistos = set()
    for i in range(NUM_INODES):
        ino = fs.read_inode(i)
        if not ino['usado']:
            continue
        for b in fs.blocks_of(ino):
            if b in vistos or not fs.is_used(b):
                return 'ERROR'
            vistos.add(b)
    return 'OK'


# Cada tupla: (punto de corte definido en svfs.py, operacion, explicacion).
# El punto de corte le dice a SVFS en que instante exacto "se va la luz".
ESCENARIOS = [
    ('antes_del_inodo', 'create',
     'create(nuevo.txt): bloques reservados y escritos, pero el inodo NO se actualizo'),
    ('tras_datos', 'create',
     'create(nuevo.txt): datos e inodo listos, pero NO se agrego la entrada al directorio'),
    ('mitad_directorio', 'create',
     'create(nuevo.txt): el directorio ya se vacio para reescribirlo y se fue la luz'),
    ('tras_liberar', 'delete',
     'delete(antes.txt): el inodo ya se libero, pero la entrada sigue en el directorio'),
]


def escenario(num, punto, operacion, descripcion):
    """Prepara un disco sano, arma el corte de luz en 'punto', ejecuta la
    operacion, 'reinicia' el disco y analiza que quedo inconsistente."""
    print()
    print('-' * 72)
    print('Escenario %d - %s' % (num, descripcion))
    print("Punto de corte: '%s'" % punto)
    print('-' * 72)

    ruta = 'reto4_%d.svfs' % num
    fs = disco_nuevo(ruta)
    fs.create('antes.txt', b'dato previo ' * 40)      # 480 bytes = 1 bloque
    libres_antes = fs.free_blocks()
    print('Disco sano: ls = %s | libres = %d | verificar = %s'
          % (fs.ls(), libres_antes, fs.verificar()))

    fs.corte = punto                                  # armamos el corte
    try:
        if operacion == 'create':
            fs.create('nuevo.txt', b'N' * 1500)       # 3 bloques
        else:
            fs.delete('antes.txt')
    except CorteDeEnergia:
        print('*** SE FUE LA LUZ ***')
    fs.close()

    fs = SVFS(ruta)                                   # "reinicio" del equipo
    print()
    print('Despues de reiniciar:')
    print('  ls()                     :', fs.ls())
    print('  bloques libres           : %d (antes eran %d)' % (fs.free_blocks(), libres_antes))
    if operacion == 'delete':
        print("  read('antes.txt')        : %r  <- devuelve vacio sin avisar" % fs.read('antes.txt'))
    print('  verificar() ORIGINAL     :', verificar_original(fs), ' <- no ve el problema')
    problemas = fs.problemas()
    print('  verificar() AMPLIADO     : %s' % ('OK' if not problemas else 'ERROR'))
    for p in problemas:
        print('      - ' + p)
    print('  Mapa del disco:')
    mostrar_mapa(fs, '      ')

    acciones = fs.reparar()
    print('  reparar():')
    for a in acciones:
        print('      * ' + a)
    print('  Tras reparar: ls = %s | libres = %d | verificar = %s'
          % (fs.ls(), fs.free_blocks(), fs.verificar()))
    fs.close()


def reto4():
    titulo('RETO 4 - Corte de energia entre write_data y save_entries')
    print("Leyenda del mapa: '?' = bloque ocupado que ningun inodo reclama.")
    for num, (punto, operacion, descripcion) in enumerate(ESCENARIOS, start=1):
        escenario(num, punto, operacion, descripcion)


# ----------------------------------------------------------------------
# Programa principal
# ----------------------------------------------------------------------
if __name__ == '__main__':
    reto1()
    reto2()
    reto3()
    reto4()
    for archivo in glob.glob('reto*.svfs'):           # limpiamos los discos temporales
        os.remove(archivo)
    print()
    print('Listo: se borraron los discos temporales reto*.svfs')
