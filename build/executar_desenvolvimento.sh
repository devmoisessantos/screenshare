#!/usr/bin/env bash
# Instala as dependências (se necessário) e executa o ScreenShare a partir do código.
set -euo pipefail

cd "$(dirname "$0")/.."

[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

exec python principal.py "$@"
