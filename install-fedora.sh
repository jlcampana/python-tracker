#!/usr/bin/env bash
# Instalación en Fedora.
set -euo pipefail

echo "==> Instalando paquetes del sistema (dnf)"
sudo dnf install -y python3 openmpt123

exec "$(dirname "$(readlink -f "$0")")/install-common.sh"
