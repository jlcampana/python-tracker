# trackerplay

Explorador de [The Mod Archive](https://modarchive.org) y reproductor de música tracker
(MOD, XM, S3M, IT y [muchos más formatos](https://lib.openmpt.org/libopenmpt/)) para la terminal.

Navegas por modarchive de forma interactiva y, al elegir una canción, se descarga sola en
`~/Música/Tracker` y empieza a sonar. Lo descargado (y cualquier módulo que copies en esa carpeta)
queda en una biblioteca local que puedes escuchar sin conexión.

## Funciones

**Explorar modarchive**
- Buscar canciones (por nombre de archivo o título) y artistas
- Rankings: más descargadas, mejor puntuadas, favoritas de la gente y destacadas
- Navegar por géneros, por orden alfabético (A-Z) o sacar canciones aleatorias
- Páginas de resultados, volver atrás y ordenar la página por título o popularidad
- Las canciones que ya tienes salen marcadas con ✓

**Biblioteca local**
- Ordenar alfabéticamente, agrupar por artista, por popularidad en modarchive, por más
  escuchadas, por añadidas recientemente o ver solo tus favoritas
- Filtrar por título, artista, archivo o género
- Contador de escuchas y marcado de favoritas
- Comprobar actualizaciones: vuelve a consultar modarchive, refresca los datos (artista,
  descargas, favoritos, género) y, si el MD5 del archivo publicado ya no coincide con el tuyo,
  lo vuelve a bajar

**Reproductor**
- Pausa, parar, siguiente/anterior, saltar ±10 s y volumen
- Al acabar una canción pasa a la siguiente de la lista desde la que la elegiste

## Dependencias

| Dependencia | Para qué | Fedora | Ubuntu |
|---|---|---|---|
| Python ≥ 3.10 | La aplicación | `python3` | `python3`, `python3-venv` |
| [openmpt123](https://lib.openmpt.org/libopenmpt/) | Reproducir los módulos (libopenmpt) | `openmpt123` | `openmpt123` (universe) |
| [Textual](https://textual.textualize.io) | Interfaz de terminal | pip (`requirements.txt`) | pip (`requirements.txt`) |

Textual se instala en un entorno virtual propio (`~/.local/share/trackerplay-venv`), sin tocar el
Python del sistema. El resto (descargas, base de datos SQLite) usa solo la biblioteca estándar.

## Instalación

```bash
git clone git@github.com:jlcampana/trackerplay.git
cd trackerplay
./install-fedora.sh     # en Fedora
./install-ubuntu.sh     # en Ubuntu / Debian
```

Los scripts instalan los paquetes del sistema (piden `sudo`), crean el entorno de Python y enlazan
el comando `tracker` en `~/.local/bin`.

## Uso

```bash
tracker
```

| Tecla | Acción |
|---|---|
| `1` / `2` | Pestaña Explorar / Biblioteca |
| `Enter` | Abrir sección, descargar y reproducir |
| `/` | Ir al buscador o al filtro |
| `[` / `]` | Página anterior / siguiente (explorar) |
| `Re Pág` / `Av Pág` | Desplazarse; en la primera o última fila cambia de página (explorar) |
| `Retroceso` / `Esc` | Volver al listado anterior (explorar) |
| `d` | Descargar sin reproducir (explorar) |
| `o` | Cambiar el orden |
| `f` | Marcar o desmarcar favorita (biblioteca) |
| `r` | Volver a escanear la carpeta (biblioteca) |
| `u` | Comprobar actualizaciones (biblioteca) |
| `Espacio` | Pausa |
| `s` | Parar |
| `n` / `b` | Siguiente / anterior |
| `,` / `.` | Retroceder / avanzar 10 s |
| `-` / `+` | Bajar / subir volumen |
| `q` | Salir |

## Dónde guarda las cosas

- Canciones: `~/Música/Tracker` (se puede cambiar con la variable de entorno `TRACKER_DIR`)
- Base de datos: `~/.local/share/trackerplay/biblioteca.db` (SQLite)

La tabla `tracks` guarda por canción: ruta, ID y URL de descarga de modarchive, MD5, título,
artista, formato, género, canales, duración, descargas y favoritos en modarchive, fecha de alta,
número de escuchas, última escucha, favorita y fecha de la última comprobación de actualizaciones.

## Notas

- modarchive no tiene API pública sin clave, así que la app lee las páginas HTML de la web. Si
  cambian el diseño, puede que haya que ajustar los parsers de `tracker.py`.
- La web limita las peticiones simultáneas; la comprobación de actualizaciones va de una en una
  con una pequeña pausa entre canciones.
