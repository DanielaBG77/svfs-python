"""
svfs.py - SVFS (Simple Virtual File System) + RETOS DE AMPLIACION
=================================================================
Sistemas Operativos - UNINTEP Roldanillo - Semana 10

Un sistema de archivos miniatura que vive dentro de UN solo archivo binario
(el "disco virtual").

Analogia: el archivo 'disco.svfs' es un edificio de 128 apartamentos
(bloques) de 512 bytes cada uno. Hay un plano en el apartamento 0
(superbloque), una pizarra que marca cuales estan ocupados (mapa de bits),
un libro de registros con la ficha de cada archivo (tabla de inodos) y una
agenda que relaciona nombre -> ficha (directorios).

Distribucion del disco (128 bloques x 512 bytes = 64 KB):

    Bloque 0        Superbloque (identificador 'SVFS' y parametros)
    Bloque 1        Mapa de bits (1 bit por bloque: 0 = libre, 1 = ocupado)
    Bloques 2 a 3   Tabla de inodos (32 inodos de 32 bytes)
    Bloques 4 a 127 Bloques de datos

El inodo 0 es SIEMPRE el directorio raiz.

RETOS DE AMPLIACION IMPLEMENTADOS (marcados en el codigo como "RETO n"):

    RETO 1  Puntero indirecto: la ficha (inodo) ya no tiene solo 8 punteros
            directos; el campo 'indirecto' apunta a un bloque que contiene
            256 punteros mas. Archivo maximo teorico: (8 + 256) x 512 bytes.
    RETO 2  Subdirectorios: rutas como 'docs/tareas/so.txt', mkdir y rmdir.
    RETO 3  Politica de asignacion: 'primer' ajuste vs 'mejor' ajuste, con
            metricas de fragmentacion y un mapa visual del disco.
    RETO 4  Corte de energia: puntos de fallo simulados + verificador
            ampliado (mini fsck) que detecta inodos huerfanos, bloques
            perdidos y entradas colgantes, y una funcion reparar().
"""

import os
import struct

# ----------------------------------------------------------------------
# 1. CONSTANTES DE DISENO
# ----------------------------------------------------------------------
BLOCK_SIZE = 512       # Tamano de cada bloque en bytes
NUM_BLOCKS = 128       # Total de bloques del disco (128 * 512 = 64 KB)
NUM_INODES = 32        # Cantidad de inodos disponibles
N_DIRECT = 8           # Punteros directos por inodo
NO_PTR = 0xFFFF        # Valor especial: "este puntero no apunta a nada"
                       # (65535 nunca es un bloque real: el disco solo tiene 128)
MAX_NAME = 30          # Longitud maxima del nombre (cada componente de la ruta)

# Formatos de struct (empaquetado binario). '<' = little-endian, sin relleno.
#   B = 1 byte, H = 2 bytes, I = 4 bytes, s = cadena de bytes, x = relleno
SB_FMT = '<4sHHHHH'       # magia, tam. bloque, n. bloques, n. inodos,
                          # inicio de inodos, inicio de datos
INODE_FMT = '<BBI8HH8x'   # usado, tipo, tamano, 8 directos, 1 indirecto,
                          # 8 bytes de relleno  -> 32 bytes
                          # Suma: 1 + 1 + 4 + (8 x 2) + 2 + 8 = 32 bytes exactos.
                          # El '<' evita que Python agregue relleno de alineacion.
DIRENT_FMT = '<H30s'      # n. de inodo (2 bytes), nombre (30 bytes) -> 32 bytes
                          # En un bloque de 512 bytes caben 512 / 32 = 16 entradas.

INODE_SIZE = struct.calcsize(INODE_FMT)    # = 32
DIRENT_SIZE = struct.calcsize(DIRENT_FMT)  # = 32

# Posiciones calculadas del disco
BITMAP_BLOCK = 1                    # El mapa de bits esta en el bloque 1
INODE_START = 2                     # La tabla de inodos empieza en el bloque 2
INODE_BLOCKS = (NUM_INODES * INODE_SIZE + BLOCK_SIZE - 1) // BLOCK_SIZE  # = 2
DATA_START = INODE_START + INODE_BLOCKS  # Primer bloque de datos (= 4)

# RETO 1: el bloque indirecto es un arreglo de punteros de 2 bytes (H).
PTRS_POR_BLOQUE = BLOCK_SIZE // struct.calcsize('<H')   # = 256 punteros
IND_FMT = '<%dH' % PTRS_POR_BLOQUE                      # formato del bloque
MAX_BLOQUES_ARCHIVO = N_DIRECT + PTRS_POR_BLOQUE        # = 264 bloques
MAX_BYTES_ARCHIVO = MAX_BLOQUES_ARCHIVO * BLOCK_SIZE    # = 135168 bytes

# Tipos de inodo
TIPO_ARCHIVO, TIPO_DIR = 1, 2

# RETO 3: politicas de asignacion disponibles
POLITICAS = ('primer', 'mejor')

# Una letra por inodo, para dibujar el mapa del disco (32 simbolos)
ETIQUETAS = '0123456789ABCDEFGHIJKLMNOPQRSTUV'


class CorteDeEnergia(Exception):
    """RETO 4: simula que se fue la luz en medio de una operacion.

    A proposito NO hereda de OSError: create() deshace sus cambios cuando
    captura un OSError, pero con un corte de luz real no habria ninguna
    oportunidad de deshacer nada. Asi el disco queda a medias, como en la
    vida real."""


class SVFS:
    """Sistema de archivos virtual sobre un archivo binario."""

    # ------------------------------------------------------------------
    # CONSTRUCTOR: abre el disco (o lo crea y formatea si no existe)
    # ------------------------------------------------------------------
    def __init__(self, ruta, politica='primer'):
        """
        Abre el disco virtual en 'ruta'.
        - Si el archivo NO existe: lo crea y lo formatea.
        - Si existe: valida que tenga el identificador 'SVFS' (persistencia).
        - politica: 'primer' (primer ajuste) o 'mejor' (mejor ajuste), RETO 3.
        """
        if politica not in POLITICAS:
            raise ValueError("politica debe ser 'primer' o 'mejor'")
        self.politica = politica
        self.corte = None   # RETO 4: nombre del punto donde "se va la luz"

        nuevo = not os.path.exists(ruta)
        # 'w+b' crea el archivo; 'r+b' abre uno existente para leer y escribir
        self.f = open(ruta, 'w+b' if nuevo else 'r+b')
        if nuevo:
            self.formatear()
        else:
            # Leemos el superbloque y comprobamos el "numero magico"
            tam_sb = struct.calcsize(SB_FMT)
            magia = struct.unpack(SB_FMT, self.read_block(0)[:tam_sb])[0]
            if magia != b'SVFS':
                self.f.close()
                raise ValueError('El archivo no es un disco SVFS')
            # Cargamos el mapa de bits a memoria para trabajar rapido
            self.bitmap = bytearray(self.read_block(BITMAP_BLOCK))

    # ------------------------------------------------------------------
    # 2. ACCESO A DISCO (lectura/escritura de bloques completos)
    # ------------------------------------------------------------------
    def read_block(self, n):
        """Lee y devuelve los 512 bytes del bloque numero 'n'."""
        # El bloque n empieza en el byte n * 512. Ej.: el bloque 3 empieza en
        # el byte 1536. Asi un archivo plano se comporta como un disco.
        self.f.seek(n * BLOCK_SIZE)   # Saltamos a la posicion del bloque
        return self.f.read(BLOCK_SIZE)

    def write_block(self, n, datos):
        """Escribe 'datos' en el bloque 'n', rellenando con ceros hasta 512."""
        self.f.seek(n * BLOCK_SIZE)
        # ljust completa con bytes 0 a la derecha hasta llegar a 512, porque
        # siempre se escribe un bloque completo (nunca medio bloque).
        self.f.write(datos.ljust(BLOCK_SIZE, b'\0'))
        self.f.flush()                # Forzamos que se guarde en el archivo

    def formatear(self):
        """Crea un disco vacio: superbloque, mapa de bits y directorio raiz."""
        # Disco lleno de ceros (64 KB)
        self.f.write(b'\0' * (BLOCK_SIZE * NUM_BLOCKS))

        # Bloque 0: superbloque con el identificador y los parametros
        self.write_block(0, struct.pack(
            SB_FMT, b'SVFS', BLOCK_SIZE, NUM_BLOCKS,
            NUM_INODES, INODE_START, DATA_START))

        # Mapa de bits: marcamos como ocupados los bloques de metadatos (0..3)
        self.bitmap = bytearray(BLOCK_SIZE)
        for b in range(DATA_START):
            self.bitmap[b // 8] |= 1 << (b % 8)
        self.save_bitmap()

        # Inodo 0 = directorio raiz (vacio al inicio)
        raiz = {'usado': 1, 'tipo': TIPO_DIR, 'tam': 0,
                'directos': [NO_PTR] * N_DIRECT, 'indirecto': NO_PTR}
        self.write_inode(0, raiz)

    # ------------------------------------------------------------------
    # 3. MAPA DE BITS (gestion del espacio libre)
    # ------------------------------------------------------------------
    def save_bitmap(self):
        """Guarda el mapa de bits (de memoria) en el bloque 1 del disco."""
        self.write_block(BITMAP_BLOCK, bytes(self.bitmap))

    def is_used(self, b):
        """Devuelve 1 si el bloque 'b' esta ocupado, 0 si esta libre.
        Byte = b // 8 ; bit dentro del byte = b % 8."""
        # Ejemplo con b = 10: byte = 10 // 8 = 1 y bit = 10 % 8 = 2.
        # '>> 2' mueve ese bit a la posicion 0 y '& 1' descarta los demas.
        return (self.bitmap[b // 8] >> (b % 8)) & 1

    def _huecos(self):
        """RETO 3: devuelve la lista [(inicio, longitud), ...] de cada HUECO,
        es decir, cada tramo de bloques libres consecutivos del area de datos.

        Analogia: en el edificio, un hueco es una fila de apartamentos
        vacios uno junto al otro."""
        huecos = []
        inicio = None
        for b in range(DATA_START, NUM_BLOCKS):
            if not self.is_used(b):
                if inicio is None:
                    inicio = b                       # empieza un hueco
            elif inicio is not None:
                huecos.append((inicio, b - inicio))  # termina un hueco
                inicio = None
        if inicio is not None:                       # hueco que llega al final
            huecos.append((inicio, NUM_BLOCKS - inicio))
        return huecos

    def alloc_blocks(self, n, politica=None):
        """Reserva 'n' bloques libres, los marca ocupados y devuelve la lista.

        RETO 3 - Politicas (se busca un hueco donde quepan los n bloques JUNTOS):
          'primer': el PRIMER hueco (el de menor direccion) donde quepan.
          'mejor' : el hueco MAS PEQUENO donde quepan (el que mejor ajusta).
        Si ningun hueco alcanza, los bloques se reparten en los primeros
        libres (el archivo queda fragmentado). Si no hay n libres: OSError.
        Todo se decide ANTES de tocar el mapa de bits, asi un fallo no deja
        bloques reservados a medias."""
        if n == 0:
            return []
        politica = politica or self.politica
        huecos = self._huecos()
        if sum(largo for _, largo in huecos) < n:
            raise OSError('Disco lleno')

        candidatos = [h for h in huecos if h[1] >= n]   # huecos donde cabe todo
        if candidatos:
            if politica == 'mejor':
                inicio = min(candidatos, key=lambda h: h[1])[0]
            else:
                inicio = candidatos[0][0]
            bloques = list(range(inicio, inicio + n))
        else:
            bloques = []                    # ningun hueco alcanza: se reparte
            for inicio, largo in huecos:
                bloques.extend(range(inicio, inicio + largo))
                if len(bloques) >= n:
                    break
            bloques = bloques[:n]

        # '1 << (b % 8)' crea una mascara con UN solo bit encendido y '|='
        # (OR) lo enciende sin alterar los otros 7 bits del byte.
        for b in bloques:                   # marcar ocupados (bit a 1)
            self.bitmap[b // 8] |= 1 << (b % 8)
        self.save_bitmap()
        return bloques

    def alloc_block(self):
        """Reserva UN bloque (caso particular de alloc_blocks) y lo devuelve.
        Lanza OSError si el disco esta lleno."""
        return self.alloc_blocks(1)[0]

    def free_block(self, b):
        """Marca el bloque 'b' como libre (bit a 0)."""
        # '~mascara' deja ese bit en 0 y los demas en 1; '&=' (AND) apaga solo
        # ese bit. El '& 0xFF' es porque ~ en Python da numeros negativos y
        # un byte del bitmap debe quedar entre 0 y 255.
        self.bitmap[b // 8] &= ~(1 << (b % 8)) & 0xFF
        self.save_bitmap()

    def free_blocks(self):
        """Cuenta cuantos bloques libres quedan en el disco."""
        return sum(1 for b in range(NUM_BLOCKS) if not self.is_used(b))

    # ------------------------------------------------------------------
    # 4. INODOS (la "ficha" de cada archivo)
    # ------------------------------------------------------------------
    def read_inode(self, i):
        """Lee el inodo numero 'i' y lo devuelve como diccionario."""
        # Posicion = inicio de la tabla (bloque 2 = byte 1024) + i * 32.
        # Ej.: el inodo 5 esta en el byte 1024 + 160 = 1184.
        self.f.seek(INODE_START * BLOCK_SIZE + i * INODE_SIZE)
        # 'u' es una tupla con los 12 campos: u[0] usado, u[1] tipo, u[2] tam,
        # u[3..10] los 8 punteros directos y u[11] el puntero indirecto.
        u = struct.unpack(INODE_FMT, self.f.read(INODE_SIZE))
        return {'usado': u[0], 'tipo': u[1], 'tam': u[2],
                'directos': list(u[3:11]), 'indirecto': u[11]}

    def write_inode(self, i, ino):
        """Escribe el diccionario 'ino' como inodo numero 'i'."""
        self.f.seek(INODE_START * BLOCK_SIZE + i * INODE_SIZE)
        self.f.write(struct.pack(
            INODE_FMT, ino['usado'], ino['tipo'], ino['tam'],
            *ino['directos'], ino['indirecto']))
        self.f.flush()

    def alloc_inode(self, tipo):
        """Reserva el primer inodo libre y lo devuelve. OSError si no hay."""
        for i in range(NUM_INODES):
            if not self.read_inode(i)['usado']:
                ino = {'usado': 1, 'tipo': tipo, 'tam': 0,
                       'directos': [NO_PTR] * N_DIRECT, 'indirecto': NO_PTR}
                self.write_inode(i, ino)
                return i
        raise OSError('No quedan inodos libres')

    def blocks_of(self, ino):
        """Lista de bloques de DATOS de un inodo, en orden.
        RETO 1: primero los directos y luego los que enumera el bloque
        indirecto (si el inodo tiene uno)."""
        bloques = [p for p in ino['directos'] if p != NO_PTR]
        if ino['indirecto'] != NO_PTR:
            crudo = self.read_block(ino['indirecto'])
            # El bloque indirecto son 512 bytes = 256 numeros de 2 bytes;
            # unpack los convierte en una tupla de 256 enteros.
            punteros = struct.unpack(IND_FMT, crudo)
            bloques += [p for p in punteros if p != NO_PTR]
        return bloques

    def all_blocks_of(self, ino):
        """Todos los bloques que ocupa un inodo: los de datos MAS el propio
        bloque indirecto (que es metadato, pero tambien ocupa espacio)."""
        bloques = self.blocks_of(ino)
        if ino['indirecto'] != NO_PTR:
            bloques.append(ino['indirecto'])
        return bloques

    # ------------------------------------------------------------------
    # 5. DATOS DE UN INODO
    # ------------------------------------------------------------------
    def _corte(self, punto):
        """RETO 4: si self.corte == punto, 'se va la luz' en este instante."""
        if self.corte == punto:
            raise CorteDeEnergia(punto)

    def write_data(self, inum, datos):
        """Guarda 'datos' (bytes) en los bloques del inodo 'inum'.
        Bloques necesarios = techo(len(datos) / 512). Si son mas de 8, se usa
        ademas UN bloque indirecto (RETO 1)."""
        # Division hacia arriba (techo) usando solo enteros.
        # Ej.: 1900 bytes -> (1900 + 511) // 512 = 4 bloques.
        n = (len(datos) + BLOCK_SIZE - 1) // BLOCK_SIZE
        if n > MAX_BLOQUES_ARCHIVO:
            raise OSError('Archivo mayor que %d bytes' % MAX_BYTES_ARCHIVO)
        usa_indirecto = n > N_DIRECT

        ino = self.read_inode(inum)
        # RETO 3: la politica elegida aplica a los datos de ARCHIVOS. Los
        # directorios usan siempre primer ajuste, para que la comparacion entre
        # politicas sea justa (ambas tratan igual a los metadatos).
        politica = self.politica if ino['tipo'] == TIPO_ARCHIVO else 'primer'

        # Reservamos TODO de una vez (datos + bloque indirecto). Si no hay
        # espacio, alloc_blocks falla sin dejar nada reservado.
        reservados = self.alloc_blocks(n + (1 if usa_indirecto else 0), politica)
        # Los primeros n bloques son de datos; si hay indirecto, el ultimo
        # bloque reservado es el que guardara la lista de punteros.
        bloques = reservados[:n]
        bloque_ind = reservados[n] if usa_indirecto else NO_PTR

        # Escribimos cada trozo de 512 bytes en su bloque
        for i, b in enumerate(bloques):
            self.write_block(b, datos[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE])

        # RETO 1: el bloque indirecto guarda los punteros de los bloques 9, 10...
        if usa_indirecto:
            # 'extra' = bloques del 9 en adelante. Se rellena con NO_PTR hasta
            # tener 256 punteros, o sea un bloque indirecto completo.
            extra = bloques[N_DIRECT:]
            punteros = extra + [NO_PTR] * (PTRS_POR_BLOQUE - len(extra))
            self.write_block(bloque_ind, struct.pack(IND_FMT, *punteros))

        self._corte('antes_del_inodo')   # RETO 4: datos escritos, inodo NO

        # Orden de escritura: 1) datos, 2) inodo, 3) directorio (en create).
        # Si la luz se va entre dos pasos, el disco queda inconsistente (RETO 4).
        # Actualizamos el inodo: punteros y tamano real en bytes
        # (los 8 primeros bloques van a los directos; si sobran huecos se
        # rellenan con NO_PTR para que el inodo siempre guarde 8 punteros)
        ino['directos'] = bloques[:N_DIRECT] + [NO_PTR] * (N_DIRECT - min(n, N_DIRECT))
        ino['indirecto'] = bloque_ind
        ino['tam'] = len(datos)
        self.write_inode(inum, ino)

    def read_data(self, inum):
        """Lee todo el contenido del inodo 'inum' y lo devuelve (bytes)."""
        ino = self.read_inode(inum)
        # Leemos cada bloque completo (512 bytes) y los pegamos en orden. El
        # ultimo trae ceros de relleno, que se recortan con el tamano real.
        crudo = b''.join(self.read_block(b) for b in self.blocks_of(ino))
        return crudo[:ino['tam']]   # Quitamos el relleno de ceros final

    def free_data(self, inum):
        """Libera los bloques del inodo (datos + indirecto); el inodo sigue
        en uso."""
        ino = self.read_inode(inum)
        for b in self.all_blocks_of(ino):
            self.free_block(b)
        ino['directos'] = [NO_PTR] * N_DIRECT
        ino['indirecto'] = NO_PTR
        ino['tam'] = 0
        self.write_inode(inum, ino)

    def delete_inode(self, inum):
        """Libera los datos y marca el inodo como no usado."""
        self.free_data(inum)
        ino = self.read_inode(inum)
        ino['usado'] = 0
        self.write_inode(inum, ino)

    # ------------------------------------------------------------------
    # 6. DIRECTORIOS (RETO 2: el raiz y cualquier subdirectorio)
    #    Un directorio es un inodo de tipo TIPO_DIR cuyo contenido es una
    #    tabla de entradas (n. de inodo, nombre) de 32 bytes cada una.
    # ------------------------------------------------------------------
    def entries(self, dir_inum=0):
        """Devuelve [(n_inodo, nombre), ...] del directorio 'dir_inum'
        (por defecto el raiz)."""
        crudo = self.read_data(dir_inum)
        salida = []
        # Avanzamos de 32 en 32 bytes: cada salto es una entrada del directorio.
        for i in range(0, len(crudo), DIRENT_SIZE):
            inum, nombre = struct.unpack(DIRENT_FMT, crudo[i:i + DIRENT_SIZE])
            # rstrip quita los ceros de relleno y decode pasa bytes -> texto
            salida.append((inum, nombre.rstrip(b'\0').decode()))
        return salida

    def save_entries(self, dir_inum, entradas):
        """Reescribe por completo el directorio 'dir_inum' con 'entradas'."""
        # Cada (inodo, nombre) se empaqueta en 32 bytes; struct completa el
        # nombre con ceros hasta los 30 bytes del formato.
        datos = b''.join(struct.pack(DIRENT_FMT, inum, nombre.encode())
                         for inum, nombre in entradas)
        # Estrategia simple: vaciamos el directorio y lo reescribimos entero.
        # No es atomico: si la luz se va entre ambos pasos, se pierden las
        # entradas (justo lo que muestra el escenario 3 del RETO 4).
        self.free_data(dir_inum)
        self._corte('mitad_directorio')   # RETO 4: directorio ya vaciado
        self.write_data(dir_inum, datos)

    def _partes(self, ruta):
        """Divide 'docs/tareas/so.txt' en ['docs', 'tareas', 'so.txt'] y valida
        cada nombre (maximo 30 bytes, sin '.' ni '..')."""
        partes = [p for p in ruta.split('/') if p]
        for p in partes:
            if len(p.encode()) > MAX_NAME:
                raise ValueError('Nombre de mas de %d bytes' % MAX_NAME)
            if p in ('.', '..'):
                raise ValueError('Nombre no permitido: %s' % p)
        return partes

    def _buscar_en(self, dir_inum, nombre):
        """Busca 'nombre' dentro de UN directorio; devuelve su inodo o None."""
        for inum, n in self.entries(dir_inum):
            if n == nombre:
                return inum
        return None

    def lookup(self, ruta):
        """Recorre la ruta desde la raiz y devuelve el n. de inodo del final,
        o None si algo no existe. lookup('') devuelve 0 (la raiz)."""
        inum = 0
        for parte in self._partes(ruta):
            if self.read_inode(inum)['tipo'] != TIPO_DIR:
                return None            # un archivo no puede contener cosas
            inum = self._buscar_en(inum, parte)
            if inum is None:
                return None
        return inum

    def _padre(self, ruta):
        """Devuelve (inodo del directorio padre, nombre final) de una ruta.
        Ej.: 'docs/so.txt' -> (inodo de 'docs', 'so.txt')."""
        partes = self._partes(ruta)
        if not partes:
            raise ValueError('Ruta vacia')
        ruta_padre = '/'.join(partes[:-1])
        padre = self.lookup(ruta_padre)
        if padre is None:
            raise FileNotFoundError(ruta_padre)
        if self.read_inode(padre)['tipo'] != TIPO_DIR:
            raise NotADirectoryError(ruta_padre)
        return padre, partes[-1]

    # ------------------------------------------------------------------
    # 7. OPERACIONES PUBLICAS (lo que "ve" el usuario)
    # ------------------------------------------------------------------
    def create(self, ruta, datos):
        """Crea el archivo 'ruta' (ej. 'a.txt' o 'docs/a.txt') con 'datos'."""
        padre, nombre = self._padre(ruta)
        if self._buscar_en(padre, nombre) is not None:
            raise FileExistsError(ruta)
        entradas = self.entries(padre)
        # Orden de create: 1) reservar inodo, 2) escribir datos, 3) anotar el
        # nombre en el directorio. Si algo falla con OSError se deshace todo;
        # con CorteDeEnergia NO, porque una luz que se va no deshace nada.
        inum = self.alloc_inode(TIPO_ARCHIVO)
        try:
            self.write_data(inum, datos)
            self._corte('tras_datos')   # RETO 4: datos listos, falta el directorio
            self.save_entries(padre, entradas + [(inum, nombre)])
        except OSError:
            self.delete_inode(inum)     # Deshacemos si algo fallo
            raise

    def read(self, ruta):
        """Devuelve el contenido (bytes) del archivo 'ruta'."""
        inum = self.lookup(ruta)
        if inum is None:
            raise FileNotFoundError(ruta)
        if self.read_inode(inum)['tipo'] == TIPO_DIR:
            raise IsADirectoryError(ruta)
        return self.read_data(inum)

    def delete(self, ruta):
        """Borra el archivo: libera inodo, bloques y quita su entrada."""
        padre, nombre = self._padre(ruta)
        inum = self._buscar_en(padre, nombre)
        if inum is None:
            raise FileNotFoundError(ruta)
        if self.read_inode(inum)['tipo'] == TIPO_DIR:
            raise IsADirectoryError('%s es un directorio, usa rmdir' % ruta)
        self.delete_inode(inum)
        self._corte('tras_liberar')     # RETO 4: inodo libre, entrada sigue
        self.save_entries(padre, [e for e in self.entries(padre) if e[0] != inum])

    def mkdir(self, ruta):
        """RETO 2: crea un subdirectorio vacio en 'ruta'."""
        padre, nombre = self._padre(ruta)
        if self._buscar_en(padre, nombre) is not None:
            raise FileExistsError(ruta)
        entradas = self.entries(padre)
        inum = self.alloc_inode(TIPO_DIR)
        try:
            self.save_entries(padre, entradas + [(inum, nombre)])
        except OSError:
            self.delete_inode(inum)
            raise

    def rmdir(self, ruta):
        """RETO 2: borra un subdirectorio, que debe estar VACIO."""
        padre, nombre = self._padre(ruta)
        inum = self._buscar_en(padre, nombre)
        if inum is None:
            raise FileNotFoundError(ruta)
        if self.read_inode(inum)['tipo'] != TIPO_DIR:
            raise NotADirectoryError(ruta)
        if self.entries(inum):
            raise OSError('Directorio no vacio: %s' % ruta)
        self.delete_inode(inum)
        self.save_entries(padre, [e for e in self.entries(padre) if e[0] != inum])

    def ls(self, ruta='/'):
        """Lista [(nombre, tamano_en_bytes), ...] del directorio 'ruta'.
        Los subdirectorios aparecen con una '/' al final del nombre."""
        inum = self.lookup(ruta)
        if inum is None:
            raise FileNotFoundError(ruta)
        if self.read_inode(inum)['tipo'] != TIPO_DIR:
            raise NotADirectoryError(ruta)
        salida = []
        for i, n in self.entries(inum):
            ino = self.read_inode(i)
            salida.append((n + '/' if ino['tipo'] == TIPO_DIR else n, ino['tam']))
        return salida

    def arbol(self, dir_inum=0, nivel=0):
        """RETO 2: devuelve el contenido del disco como lineas de un arbol."""
        lineas = ['/'] if nivel == 0 else []
        sangria = '  ' * (nivel + 1)
        for inum, nombre in self.entries(dir_inum):
            ino = self.read_inode(inum)
            if ino['tipo'] == TIPO_DIR:
                lineas.append('%s%s/' % (sangria, nombre))
                # Recursion: el mismo metodo recorre el subdirectorio con un
                # nivel mas de sangria.
                lineas += self.arbol(inum, nivel + 1)
            else:
                lineas.append('%s%s (%d bytes)' % (sangria, nombre, ino['tam']))
        return lineas

    # ------------------------------------------------------------------
    # 8. FRAGMENTACION Y MAPA DEL DISCO (RETO 3)
    # ------------------------------------------------------------------
    def fragmentacion(self):
        """Metricas de fragmentacion EXTERNA del espacio libre:
          libres      : bloques de datos libres
          huecos      : en cuantos tramos esta partido ese espacio libre
          mayor_hueco : el tramo libre mas grande
          externa_pct : 100 x (1 - mayor_hueco / libres). 0 % = todo el espacio
                        libre esta junto; cerca de 100 % = muy desperdigado."""
        huecos = self._huecos()
        libres = sum(largo for _, largo in huecos)
        mayor = max((largo for _, largo in huecos), default=0)
        externa = 0.0 if libres == 0 else round(100.0 * (1 - mayor / libres), 1)
        return {'libres': libres, 'huecos': len(huecos),
                'mayor_hueco': mayor, 'externa_pct': externa}

    def fragmentos_de(self, ruta):
        """En cuantos tramos CONTIGUOS esta guardado un archivo.
        1 = todo seguido (ideal); mayor = fragmentado."""
        inum = self.lookup(ruta)
        if inum is None:
            raise FileNotFoundError(ruta)
        bloques = self.blocks_of(self.read_inode(inum))
        if not bloques:
            return 0
        # Contamos los "saltos": cada vez que un bloque NO es el siguiente del
        # anterior empieza un tramo nuevo. Ej.: [5,6,7,20,21] -> 2 tramos.
        return 1 + sum(1 for a, b in zip(bloques, bloques[1:]) if b != a + 1)

    def mapa(self, ancho=64):
        """Dibuja el disco, un caracter por bloque: '#' metadatos del sistema,
        '.' libre, una letra/numero = bloque del inodo con esa etiqueta
        (ver ETIQUETAS) y '?' = bloque ocupado que NINGUN inodo reclama."""
        duenio = {}
        for i in range(NUM_INODES):
            ino = self.read_inode(i)
            if ino['usado']:
                for b in self.all_blocks_of(ino):
                    duenio[b] = ETIQUETAS[i]
        celdas = []
        for b in range(NUM_BLOCKS):
            if b < DATA_START:
                celdas.append('#')
            elif self.is_used(b):
                celdas.append(duenio.get(b, '?'))
            else:
                celdas.append('.')
        texto = ''.join(celdas)   # una sola cadena de 128 caracteres...
        # ...que se corta en lineas de 'ancho' caracteres (64 -> 2 lineas)
        return [texto[i:i + ancho] for i in range(0, len(texto), ancho)]

    # ------------------------------------------------------------------
    # 9. VERIFICADOR DE CONSISTENCIA Y REPARADOR (RETO 4, como un mini fsck)
    # ------------------------------------------------------------------
    def _alcanzables(self, problemas):
        """Recorre el arbol desde la raiz y devuelve el conjunto de inodos a
        los que se puede llegar por algun nombre. Las entradas que apuntan a un
        inodo NO usado se anotan en 'problemas' (entradas colgantes)."""
        # Recorrido en profundidad con una pila: partimos de la raiz (inodo 0)
        # y entramos a cada subdirectorio. 'vistos' evita repetir inodos.
        vistos = {0}
        pila = [0]
        while pila:
            d = pila.pop()
            for inum, nombre in self.entries(d):
                ino = self.read_inode(inum)
                if not ino['usado']:
                    problemas.append(
                        "la entrada '%s' apunta al inodo %d, que no esta en "
                        "uso (entrada colgante)" % (nombre, inum))
                    continue
                if inum in vistos:
                    continue
                vistos.add(inum)
                if ino['tipo'] == TIPO_DIR:
                    pila.append(inum)
        return vistos

    def problemas(self):
        """Devuelve la lista de TODAS las inconsistencias encontradas:
          - bloque asignado a dos inodos
          - bloque usado por un inodo pero libre en el mapa de bits
          - bloque ocupado en el mapa de bits que ningun inodo usa (perdido)
          - inodo en uso sin ninguna entrada de directorio (huerfano)
          - entrada de directorio que apunta a un inodo libre (colgante)"""
        problemas = []
        duenio = {}                     # bloque -> inodo que lo usa
        usados = []
        for i in range(NUM_INODES):
            ino = self.read_inode(i)
            if not ino['usado']:
                continue
            usados.append(i)
            for b in self.all_blocks_of(ino):
                if b in duenio:
                    problemas.append('bloque %d asignado a dos inodos (%d y %d)'
                                     % (b, duenio[b], i))
                else:
                    duenio[b] = i
                if not self.is_used(b):
                    problemas.append('bloque %d en uso por el inodo %d pero '
                                     'libre en el mapa de bits' % (b, i))
        for b in range(DATA_START, NUM_BLOCKS):
            if self.is_used(b) and b not in duenio:
                problemas.append('bloque %d ocupado en el mapa de bits pero '
                                 'ningun inodo lo usa (bloque perdido)' % b)
        alcanzables = self._alcanzables(problemas)
        for i in usados:
            if i not in alcanzables:
                problemas.append('inodo %d en uso pero sin entrada en ningun '
                                 'directorio (inodo huerfano)' % i)
        return problemas

    def verificar(self):
        """Devuelve 'OK' si el disco es consistente, o 'ERROR: ...' con el
        detalle de cada problema."""
        problemas = self.problemas()
        if not problemas:
            return 'OK'
        return 'ERROR: ' + '; '.join(problemas)

    def reparar(self):
        """Mini fsck: arregla lo que se puede SIN conocer los nombres perdidos.
        Quita entradas colgantes, libera inodos huerfanos (con sus bloques) y
        libera bloques perdidos. Devuelve la lista de acciones realizadas.
        OJO: sin journaling, los datos de un huerfano se pierden."""
        acciones = []

        # 1. Entradas colgantes: se borran de su directorio
        for d in sorted(self._alcanzables([])):
            if self.read_inode(d)['tipo'] != TIPO_DIR:
                continue
            entradas = self.entries(d)
            buenas = [e for e in entradas if self.read_inode(e[0])['usado']]
            if len(buenas) != len(entradas):
                for inum, nombre in entradas:
                    if not self.read_inode(inum)['usado']:
                        acciones.append("quitada la entrada colgante '%s' "
                                        "(inodo %d)" % (nombre, inum))
                self.save_entries(d, buenas)

        # 2. Inodos huerfanos: se liberan junto con sus bloques
        alcanzables = self._alcanzables([])
        for i in range(NUM_INODES):
            if self.read_inode(i)['usado'] and i not in alcanzables:
                self.delete_inode(i)
                acciones.append('liberado el inodo huerfano %d y sus bloques' % i)

        # 3. Bloques perdidos: ocupados en el mapa pero sin duenio
        con_duenio = set()
        for i in range(NUM_INODES):
            ino = self.read_inode(i)
            if ino['usado']:
                con_duenio.update(self.all_blocks_of(ino))
        for b in range(DATA_START, NUM_BLOCKS):
            if self.is_used(b) and b not in con_duenio:
                self.free_block(b)
                acciones.append('liberado el bloque perdido %d' % b)
        return acciones

    def close(self):
        """Cierra el archivo del disco."""
        self.f.close()


# ----------------------------------------------------------------------
# PROGRAMA DE PRUEBA DE PERSISTENCIA
# Ejecutalo DOS veces: la 1.a crea el archivo, la 2.a lo recupera.
# ----------------------------------------------------------------------
if __name__ == '__main__':
    fs = SVFS('disco.svfs')
    if fs.lookup('hola.txt') is None:
        fs.create('hola.txt', b'Hola desde el SVFS ' * 100)   # 1900 bytes
        print('Archivo creado. Ejecuta el programa otra vez para '
              'comprobar la persistencia.')
    else:
        print('Contenido recuperado:', fs.read('hola.txt')[:19])
    print('Directorio:', fs.ls())
    print('Bloques libres:', fs.free_blocks())
    print('Verificacion:', fs.verificar())
    fs.close()
