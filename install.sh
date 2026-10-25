#!/usr/bin/env bash
# Instalación de terminal-tracker en Fedora o Ubuntu / Debian.
#
# Desde una copia del repositorio:  ./install.sh
# Sin clonar nada:
#   curl -fsSL https://raw.githubusercontent.com/jlcampana/terminal-tracker/main/install.sh | bash
#
# Instala openmpt123 y Python (pide sudo), descarga la aplicación en
# ~/.local/share/terminal-tracker si no se ejecuta desde una copia, crea el entorno de Python
# y enlaza el comando 'tracker' en ~/.local/bin. Volver a ejecutarlo actualiza la aplicación.
set -euo pipefail

REPO="https://github.com/jlcampana/terminal-tracker"
VENV="$HOME/.local/share/trackerplay-venv"
BIN_DIR="$HOME/.local/bin"

# Todo va dentro de main() para que bash lea el script entero antes de ejecutarlo: con
# 'curl | bash' el script llega por la entrada estándar y dnf/apt podrían comerse el resto.
main() {

# ------------------------------------------------------------ paquetes del sistema

. /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
    *" fedora "*)
        echo "==> Instalando paquetes del sistema (dnf)"
        sudo dnf install -y python3 git openmpt123
        ;;
    *" debian "*|*" ubuntu "*)
        echo "==> Instalando paquetes del sistema (apt)"
        # openmpt123 está en el repositorio "universe" de Ubuntu
        if [[ ${ID:-} == ubuntu ]] \
           && ! grep -rqs '^[^#].* universe' /etc/apt/sources.list /etc/apt/sources.list.d/ \
           && ! grep -rqs '^Components:.*universe' /etc/apt/sources.list.d/; then
            sudo add-apt-repository -y universe
        fi
        sudo apt-get update
        sudo apt-get install -y python3 python3-venv git openmpt123
        ;;
    *)
        echo "Distribución no soportada (${PRETTY_NAME:-desconocida})." >&2
        echo "Instala a mano python3, python3-venv, git y openmpt123 y vuelve a ejecutarlo." >&2
        exit 1
        ;;
esac

# ------------------------------------------------------------ código de la aplicación

# Con 'curl | bash' no hay archivo de script: BASH_SOURCE está vacío o apunta a la entrada estándar.
SRC="${BASH_SOURCE[0]:-}"
if [[ -n $SRC && -f $SRC && -f "$(dirname "$(readlink -f "$SRC")")/tracker.py" ]]; then
    APP_DIR="$(dirname "$(readlink -f "$SRC")")"
else
    APP_DIR="$HOME/.local/share/terminal-tracker"
    if [[ -d $APP_DIR/.git ]]; then
        echo "==> Actualizando la aplicación en $APP_DIR"
        git -C "$APP_DIR" pull --ff-only -q
    else
        echo "==> Descargando la aplicación en $APP_DIR"
        rm -rf "$APP_DIR"
        git clone -q --depth 1 "$REPO.git" "$APP_DIR"
    fi
fi

# ------------------------------------------------------------ entorno de Python y comando

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
}

main "$@"
