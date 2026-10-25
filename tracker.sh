#!/usr/bin/env bash
# Explorador de modarchive.org y reproductor de música tracker para la terminal.
# Las canciones se guardan en ~/Música/Tracker y la base de datos en ~/.local/share/trackerplay.
set -euo pipefail

APP_DIR="$(dirname "$(readlink -f "$0")")"
VENV="$HOME/.local/share/trackerplay-venv"

if ! command -v openmpt123 >/dev/null; then
    echo "Falta openmpt123. Ejecuta install.sh" >&2
    exit 1
fi

# Instalar Textual si no está
if [[ ! -x $VENV/bin/python ]] || ! "$VENV/bin/python" -c "import textual" 2>/dev/null; then
    echo "Instalando dependencias de Python..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"
fi

exec "$VENV/bin/python" "$APP_DIR/tracker.py" "$@"
