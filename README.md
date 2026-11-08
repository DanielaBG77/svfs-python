# SVFS - Simple Virtual File System

Taller de la **Semana 10: Sistemas de Archivos y Estructuras de Almacenamiento**
Asignatura: Sistemas Operativos - UNINTEP Roldanillo - Docente: Oscar Pulgarín
Autora: Daniela Blandón

SVFS es un sistema de archivos en miniatura escrito en Python. Todo el "disco" vive dentro de **un solo archivo binario** de 64 KB, y sobre él se construyen las mismas piezas que tiene un sistema de archivos real: superbloque, mapa de bits, inodos y directorios.

Además del taller base, este proyecto resuelve los **4 retos de ampliación**: puntero indirecto, subdirectorios, política de asignación (primer ajuste vs mejor ajuste) y simulación de corte de energía con verificador y reparador.

---

## Contenido del proyecto

| Archivo | Para qué sirve |
|---|---|
| `svfs.py` | La librería: clase `SVFS` con todo el sistema de archivos. También se puede ejecutar para probar la persistencia. |
| `pruebas.py` | Lista de chequeo automática (sección 5 del taller). Imprime `[LOGRADO]` o `[NO LOGRADO]` por cada ítem. |
| `retos.py` | Demostración en pantalla de los 4 retos de ampliación (útil para tomar capturas de evidencia). |

No se necesita instalar nada: solo **Python 3** y los módulos estándar `os` y `struct`.

---

## Cómo ejecutarlo

```bash
python svfs.py      # ejecútalo DOS veces: la 1.ª crea hola.txt, la 2.ª lo recupera
python pruebas.py   # lista de chequeo (crea y borra disco_pruebas.svfs)
python retos.py     # demo de los 4 retos (usa discos temporales reto*.svfs y los borra al final)
```

La primera vez que se ejecuta `svfs.py`, el disco `disco.svfs` se crea y se formatea. Las siguientes veces se **reabre sin formatear** y se valida el identificador `SVFS`; eso es lo que demuestra la persistencia.

---

## Diseño del disco

Decisiones de diseño (pedidas en el punto 3.3 del taller):

| Parámetro | Valor |
|---|---|
| Tamaño de bloque | 512 bytes |
| Número de bloques | 128 (disco de 64 KB) |
| Número de inodos | 32 (el inodo 0 es siempre el directorio raíz) |
| Tamaño de inodo | 32 bytes |
| Tamaño de entrada de directorio | 32 bytes (2 de inodo + 30 de nombre) |
| Límite de nombres | 30 bytes por componente de la ruta |
| Punteros directos por inodo | 8 |
| Punteros en el bloque indirecto | 256 (punteros de 2 bytes) |

### Distribución de los bloques

| Bloque | Contenido |
|---|---|
| 0 | Superbloque (identificador `SVFS` y parámetros del disco) |
| 1 | Mapa de bits (1 bit por bloque: 0 = libre, 1 = ocupado) |
| 2 a 3 | Tabla de inodos (32 inodos de 32 bytes) |
| 4 a 127 | Bloques de datos (124 bloques) |

### Estructura de un inodo (32 bytes)

```
usado (1) | tipo (1) | tamaño (4) | 8 punteros directos (16) | indirecto (2) | relleno (8)
```

- `tipo`: `1` = archivo, `2` = directorio.
- Un puntero con valor `0xFFFF` (`NO_PTR`) significa "no apunta a nada".
- El **nombre no está en el inodo**: vive en la entrada del directorio que apunta a él, igual que en UNIX.

### Cómo se guarda un archivo

1. `create` reserva un inodo libre.
2. `write_data` reserva los bloques (más uno extra si hay bloque indirecto), escribe los datos y luego el inodo.
3. Se agrega la entrada `(inodo, nombre)` al directorio padre.

Por ejemplo, un archivo de 1900 bytes ocupa `techo(1900 / 512) = 4` bloques.

---

## Uso como librería

```python
from svfs import SVFS

fs = SVFS('disco.svfs')            # crea y formatea, o reabre si ya existe
fs.mkdir('docs')                   # subdirectorio
fs.create('docs/nota.txt', b'Hola')
print(fs.read('docs/nota.txt'))    # b'Hola'
print(fs.ls('docs'))               # [('nota.txt', 4)]
print('\n'.join(fs.arbol()))       # vista de árbol
print(fs.verificar())              # 'OK' o 'ERROR: ...'
fs.delete('docs/nota.txt')
fs.rmdir('docs')
fs.close()
```

### Operaciones principales

| Método | Qué hace |
|---|---|
| `create(ruta, datos)` | Crea un archivo con los bytes dados |
| `read(ruta)` | Devuelve el contenido del archivo |
| `delete(ruta)` | Borra un archivo y libera su inodo y sus bloques |
| `mkdir(ruta)` / `rmdir(ruta)` | Crea / borra un subdirectorio (debe estar vacío) |
| `ls(ruta='/')` | Lista `(nombre, tamaño)`; los directorios llevan `/` al final |
| `arbol()` | Devuelve el contenido del disco como líneas de un árbol |
| `free_blocks()` | Cuenta los bloques libres |
| `verificar()` | Devuelve `'OK'` o el detalle de cada inconsistencia |
| `reparar()` | Mini `fsck`: corrige lo que se puede y lista las acciones |
| `fragmentacion()` / `fragmentos_de(ruta)` / `mapa()` | Métricas y dibujo del disco |

Errores claros: `FileExistsError` (nombre repetido), `FileNotFoundError`, `NotADirectoryError`, `IsADirectoryError`, `ValueError` (nombre de más de 30 bytes o disco que no es SVFS) y `OSError` (disco lleno, sin inodos, archivo demasiado grande, directorio no vacío).

---

## Retos de ampliación

### Reto 1 - Puntero indirecto

Con solo 8 punteros directos un archivo no pasaba de 4096 bytes. Ahora el campo `indirecto` del inodo apunta a un **bloque de punteros** (256 punteros de 2 bytes) que enumera los bloques 9 en adelante.

- Máximo teórico: `(8 + 256) x 512 = 135168` bytes.
- Máximo práctico en este disco: `(124 - 2) x 512 = 62464` bytes, porque el disco solo tiene 124 bloques de datos y hay que dejar uno para el bloque indirecto y otro para el directorio raíz.
- Un archivo de 10000 bytes usa 20 bloques de datos + 1 indirecto.

### Reto 2 - Subdirectorios

Se aceptan rutas como `docs/tareas/so.txt`. Un directorio es un inodo de tipo `2` cuyo contenido es una tabla de entradas, y la búsqueda de una ruta recorre el árbol desde la raíz. Se agregaron `mkdir`, `rmdir`, `ls(ruta)` y `arbol()`. Un mismo nombre puede repetirse en directorios distintos. No se aceptan `.` ni `..` como nombres.

### Reto 3 - Primer ajuste vs mejor ajuste

`SVFS(ruta, politica='primer' | 'mejor')` cambia cómo se elige el hueco de bloques libres para un archivo:

- **Primer ajuste:** el primer hueco donde quepa el archivo.
- **Mejor ajuste:** el hueco más pequeño donde quepa.

Resultado de la demo de `retos.py` (dos huecos libres, de 11 y 4 bloques, y se crean `n1` de 4 bloques y luego `n2` de 11):

| Política | Huecos tras crear n1 | Mayor hueco | Fragmentación externa | Tramos de n1 | Tramos de n2 |
|---|---|---|---|---|---|
| primer | 2 | 7 | 36.4 % | 1 | 2 |
| mejor | 1 | 11 | 0.0 % | 1 | 1 |

Con primer ajuste, `n1` se come el inicio del hueco grande y `n2` ya no cabe entero, así que queda partido en 2 tramos. Con mejor ajuste, `n1` usa el hueco de 4 y el hueco de 11 queda intacto para `n2`. (Esto vale para este escenario; en otros, mejor ajuste puede dejar huecos diminutos.)

### Reto 4 - Corte de energía

`fs.corte = '<punto>'` hace que la ejecución se interrumpa con `CorteDeEnergia` en un punto exacto de una operación. Esa excepción **no** hereda de `OSError` a propósito: `create` deshace sus cambios cuando atrapa un `OSError`, pero con una luz que se va de verdad no habría oportunidad de deshacer nada.

| Escenario | Punto de corte | Qué queda inconsistente |
|---|---|---|
| 1 | `antes_del_inodo` | 3 bloques ocupados que ningún inodo usa (bloques perdidos) y un inodo huérfano |
| 2 | `tras_datos` | Inodo huérfano: datos listos pero sin entrada en el directorio |
| 3 | `mitad_directorio` | El directorio quedó vacío: `ls()` no muestra nada y los inodos de `antes.txt` y `nuevo.txt` quedan huérfanos (se pierde un archivo que ya existía) |
| 4 | `tras_liberar` | Entrada colgante: `antes.txt` sigue en el directorio pero su inodo está libre; `read` devuelve vacío sin avisar |

El `verificar()` del taller base solo revisa inodo -> bloques, y en los 4 escenarios responde `OK`. El `verificar()` ampliado detecta además bloques perdidos, inodos huérfanos y entradas colgantes, y `reparar()` los limpia. Limitación importante: sin journaling, `reparar()` **no puede recuperar los datos** de un huérfano, solo devolver el disco a un estado consistente. Esto conecta con el cierre de la clase sobre journaling.

---

## Lista de chequeo (sección 5 del taller)

`python pruebas.py` verifica automáticamente, y en la última ejecución todos los ítems dieron `[LOGRADO]`:

| Criterio | Ítems cubiertos |
|---|---|
| Asignación de bloques | El formateo marca los bloques 0 a 3 como ocupados; los bloques libres vuelven al valor inicial tras borrar; 1900 bytes = 4 bloques |
| Inodos y directorio | `ls` y `read` correctos; se rechazan nombres repetidos y de más de 30 bytes; el borrado libera inodo y entrada |
| Consistencia | `verificar()` devuelve `OK` tras crear y borrar archivos y tras los errores |
| Persistencia | Al reabrir, `ls` y `read` recuperan los archivos; se valida el identificador `SVFS` |
| Manejo de errores | Disco lleno, sin inodos, archivo inexistente y archivo mayor al máximo generan un error claro |

---

## Limitaciones conocidas

- Los directorios se reescriben completos en cada cambio (vaciar y volver a escribir), por eso no son atómicos.
- No hay journaling: ante un corte de energía solo se puede detectar y reparar, no recuperar datos.
- El disco es pequeño (64 KB) y los inodos son 32, así que el sistema soporta como máximo 31 archivos o directorios además de la raíz.
- `create` no sobrescribe: para cambiar un archivo hay que borrarlo y crearlo de nuevo.
- No guarda permisos, propietario ni fechas, solo tipo y tamaño.
