#!/usr/bin/env bash
# Instalación en Ubuntu / Debian. openmpt123 está en el repositorio "universe".
set -euo pipefail

echo "==> Instalando paquetes del sistema (apt)"
if ! grep -rqs '^[^#].* universe' /etc/apt/sources.list /etc/apt/sources.list.d/ \
     && ! grep -rqs '^Components:.*universe' /etc/apt/sources.list.d/; then
    sudo add-apt-repository -y universe
fi
sudo apt-get update
sudo apt-get install -y python3 python3-venv openmpt123

exec "$(dirname "$(readlink -f "$0")")/install-common.sh"
