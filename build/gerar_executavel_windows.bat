@echo off
REM ===================================================================
REM  ScreenShare 1.0 - Geracao do executavel para Windows 10/11
REM  Uso: dar duplo clique neste arquivo ou executar no Prompt:
REM       build\gerar_executavel_windows.bat
REM  Resultado: dist\ScreenShare.exe
REM ===================================================================
setlocal
cd /d "%~dp0.."

echo.
echo [1/5] Verificando o Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado no PATH.
    echo Instale em https://www.python.org/downloads/ marcando "Add Python to PATH".
    pause
    exit /b 1
)

echo [2/5] Criando o ambiente virtual (.venv)...
if not exist ".venv" (
    python -m venv .venv || goto :erro
)
call .venv\Scripts\activate.bat || goto :erro

echo [3/5] Instalando dependencias...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo AVISO: alguma dependencia falhou. Tentando sem o audio...
    python -m pip install mss opencv-python numpy pillow || goto :erro
    echo O aplicativo funcionara sem audio ate o sounddevice ser instalado.
)
python -m pip install pyinstaller || goto :erro

echo [4/5] Executando os testes automatizados...
python -m unittest discover -s testes -p "teste_*.py"
if errorlevel 1 (
    echo AVISO: existem testes falhando. O build continuara.
)

echo [5/5] Gerando o executavel...
pyinstaller build\screenshare.spec --noconfirm --clean || goto :erro

echo.
echo ==========================================================
echo  Concluido! Executavel gerado em: dist\ScreenShare.exe
echo ==========================================================
pause
exit /b 0

:erro
echo.
echo ERRO durante o processo. Verifique as mensagens acima.
pause
exit /b 1
