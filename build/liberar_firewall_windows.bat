@echo off
REM ===================================================================
REM  ScreenShare 1.0 - Liberacao da porta no Firewall do Windows
REM
REM  Este e o passo que resolve o erro "tempo esgotado / timed out"
REM  no espectador: sem a regra, o Windows descarta silenciosamente a
REM  conexao antes que ela chegue ao aplicativo.
REM
REM  COMO USAR: clique com o botao direito neste arquivo e escolha
REM             "Executar como administrador".
REM ===================================================================
setlocal

set PORTA=%1
if "%PORTA%"=="" set PORTA=9999

net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERRO: este script precisa de privilegios de administrador.
    echo Feche esta janela, clique com o botao direito no arquivo e
    echo escolha "Executar como administrador".
    echo.
    pause
    exit /b 1
)

echo Removendo regra anterior (se existir)...
netsh advfirewall firewall delete rule name="ScreenShare %PORTA%" >nul 2>&1

echo Criando regra de entrada TCP para a porta %PORTA%...
netsh advfirewall firewall add rule name="ScreenShare %PORTA%" dir=in action=allow protocol=TCP localport=%PORTA%
if errorlevel 1 (
    echo.
    echo ERRO ao criar a regra. Verifique as mensagens acima.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo  Porta %PORTA%/TCP liberada no Firewall do Windows.
echo  Agora inicie o compartilhamento e peca ao espectador
echo  para conectar novamente.
echo ==========================================================
echo.
echo Para remover a regra depois, execute como administrador:
echo   netsh advfirewall firewall delete rule name="ScreenShare %PORTA%"
echo.
pause
