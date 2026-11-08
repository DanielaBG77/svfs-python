"""
pruebas.py - Lista de chequeo automatica del SVFS (seccion 5 del taller).
Cada prueba imprime LOGRADO o NO LOGRADO para que lo uses como evidencia.

Cambio frente a la version base: con el RETO 1 (puntero indirecto) un archivo
de mas de 4096 bytes ya SI se puede crear, asi que ese test ahora comprueba
el nuevo comportamiento y el limite teorico nuevo.
"""

import os
from svfs import SVFS, DATA_START, NUM_BLOCKS, MAX_BYTES_ARCHIVO, NO_PTR

RUTA = 'disco_pruebas.svfs'


def check(descripcion, condicion):
    """Imprime el resultado de una verificacion."""
    print(('[LOGRADO]    ' if condicion else '[NO LOGRADO] ') + descripcion)


def debe_fallar(descripcion, funcion, tipo_error):
    """Comprueba que 'funcion' lance el error esperado."""
    # Si funcion() NO lanza error, la prueba falla. Si lanza el tipo esperado,
    # pasa; un error de otro tipo se propaga y detiene el script.
    try:
        funcion()
        check(descripcion, False)
    except tipo_error as e:
        check('%s (error: %s)' % (descripcion, e), True)


# Partimos de un disco limpio
if os.path.exists(RUTA):
    os.remove(RUTA)

fs = SVFS(RUTA)

print('--- Asignacion de bloques ---')
check('Formateo marca bloques 0 a %d como ocupados' % (DATA_START - 1),
      all(fs.is_used(b) for b in range(DATA_START)))
libres_inicio = fs.free_blocks()
check('Bloques libres iniciales = %d' % (NUM_BLOCKS - DATA_START),
      libres_inicio == NUM_BLOCKS - DATA_START)

fs.create('a.txt', b'A' * 1900)   # techo(1900 / 512) = 4 bloques
check('1900 bytes ocupan 4 bloques',
      len(fs.blocks_of(fs.read_inode(fs.lookup('a.txt')))) == 4)

print('--- Inodos y directorio ---')
fs.create('b.txt', b'B' * 600)
fs.create('c.txt', b'C' * 10)
check('ls muestra 3 archivos con su tamano',
      fs.ls() == [('a.txt', 1900), ('b.txt', 600), ('c.txt', 10)])
check('read devuelve el contenido exacto', fs.read('b.txt') == b'B' * 600)
debe_fallar('Rechaza nombre repetido', lambda: fs.create('a.txt', b'x'),
            FileExistsError)
debe_fallar('Rechaza nombre de mas de 30 bytes',
            lambda: fs.create('n' * 31, b'x'), ValueError)

fs.delete('a.txt')
fs.delete('b.txt')
fs.delete('c.txt')
check('Borrado libera inodos y entradas del directorio', fs.ls() == [])
check('free_block devuelve los bloques (conteo vuelve al inicial)',
      fs.free_blocks() == libres_inicio)
check('verificar() devuelve OK', fs.verificar() == 'OK')

print('--- Manejo de errores ---')
debe_fallar('Archivo inexistente', lambda: fs.read('nada.txt'),
            FileNotFoundError)

# RETO 1: ya no hay limite de 4096 bytes; se usa el bloque indirecto.
fs.create('g.bin', b'x' * 5000)
ino_g = fs.read_inode(fs.lookup('g.bin'))
check('Archivo de 5000 bytes (supera 4096) se guarda y se lee completo',
      fs.read('g.bin') == b'x' * 5000)
check('El archivo de 5000 bytes usa el bloque indirecto',
      ino_g['indirecto'] != NO_PTR)
fs.delete('g.bin')
debe_fallar('Archivo mayor al maximo teorico (%d bytes)' % MAX_BYTES_ARCHIVO,
            lambda: fs.create('g', b'x' * (MAX_BYTES_ARCHIVO + 1)), OSError)


# Hay 32 inodos y el 0 es la raiz: al crear 40 archivos, a partir del
# archivo 32 debe lanzarse OSError('No quedan inodos libres').
def llenar_inodos():
    for i in range(40):
        fs.create('f%d' % i, b'x')


debe_fallar('Sin inodos libres', llenar_inodos, OSError)
for nombre, _ in fs.ls():
    fs.delete(nombre)


# 30 archivos de 4096 bytes = 30 x 8 = 240 bloques, pero solo hay 124 libres:
# en algun momento debe lanzarse OSError('Disco lleno').
def llenar_disco():
    for i in range(30):
        fs.create('d%d' % i, b'x' * 4096)


debe_fallar('Disco lleno', llenar_disco, OSError)
for nombre, _ in fs.ls():
    fs.delete(nombre)
check('verificar() OK tras errores', fs.verificar() == 'OK')
check('Los bloques libres vuelven al valor inicial tras los errores',
      fs.free_blocks() == libres_inicio)

print('--- Persistencia ---')
fs.create('persistente.txt', b'Sigo aqui' * 50)
fs.close()
fs = SVFS(RUTA)   # Reabrimos SIN formatear
check('Al reabrir, ls recupera el archivo',
      fs.ls() == [('persistente.txt', 450)])
check('Al reabrir, read recupera el contenido',
      fs.read('persistente.txt') == b'Sigo aqui' * 50)
fs.close()

with open('no_es_svfs.bin', 'wb') as f:
    f.write(b'basura' * 100)
debe_fallar('Valida el identificador SVFS', lambda: SVFS('no_es_svfs.bin'),
            ValueError)
os.remove('no_es_svfs.bin')
