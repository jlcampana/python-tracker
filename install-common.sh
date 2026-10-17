#!/usr/bin/env bash
# Pasos comunes de instalación (los llaman install-fedora.sh e install-ubuntu.sh).
set -euo pipefail

APP_DIR="$(dirname "$(readlink -f "$0")")"
VENV="$HOME/.local/share/trackerplay-venv"
BIN_DIR="$HOME/.local/bin"

echo "==> Creando entorno de Python en $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> Creando la carpeta de música"
mkdir -p "${TRACKER_DIR:-$HOME/Música/Tracker}"

echo "==> Enlazando el comando 'tracker' en $BIN_DIR"
mkdir -p "$BIN_DIR"
chmod +x "$APP_DIR/tracker.sh" "$APP_DIR/tracker.py"
ln -sf "$APP_DIR/tracker.sh" "$BIN_DIR/tracker"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "Aviso: $BIN_DIR no está en tu PATH. Añade esto a ~/.bashrc:"
       echo "  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

echo "==> Listo. Ejecuta: tracker"
