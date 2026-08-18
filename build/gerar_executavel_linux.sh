#!/usr/bin/env bash
# ===================================================================
#  ScreenShare 1.0 - Geração do executável para Linux
#  Uso: bash build/gerar_executavel_linux.sh
#  Resultado: dist/ScreenShare
# ===================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/5] Verificando o Python..."
command -v python3 >/dev/null || { echo "ERRO: python3 não encontrado."; exit 1; }
python3 --version

echo "[2/5] Criando o ambiente virtual (.venv)..."
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[3/5] Instalando dependências..."
python -m pip install --upgrade pip >/dev/null
if ! python -m pip install -r requirements.txt; then
    echo "AVISO: falha ao instalar alguma dependência (provavelmente PyAudio)."
    echo "       Instale as bibliotecas do sistema com:"
    echo "       sudo apt install portaudio19-dev python3-tk"
    python -m pip install mss opencv-python numpy pillow
fi
python -m pip install pyinstaller

echo "[4/5] Executando os testes automatizados..."
python -m unittest discover -s testes -p "teste_*.py" || echo "AVISO: testes com falha; build continuará."

echo "[5/5] Gerando o executável..."
pyinstaller build/screenshare.spec --noconfirm --clean

echo
echo "=========================================================="
echo " Concluído! Executável gerado em: dist/ScreenShare"
echo " Execute com: ./dist/ScreenShare"
echo "=========================================================="
