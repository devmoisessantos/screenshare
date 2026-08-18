#!/usr/bin/env bash
# ===================================================================
#  ScreenShare 2.0 - Geração do executável para Linux
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
    echo "ERRO: não foi possível instalar as dependências do ScreenShare 2.0."
    echo "      No Ubuntu/Debian, verifique: sudo apt install libportaudio2 python3-tk"
    exit 1
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
