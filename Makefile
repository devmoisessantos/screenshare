# Atalhos de desenvolvimento do ScreenShare
PYTHON ?= python3

.PHONY: ajuda instalar executar testes sinalizacao verificar executavel limpar

ajuda:  ## Lista os alvos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

instalar:  ## Cria o ambiente virtual e instala as dependências
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements-dev.txt

executar:  ## Executa a aplicação
	$(PYTHON) principal.py

testes:  ## Roda os 110 testes automatizados
	$(PYTHON) -m unittest discover -s testes -p "teste_*.py" -v

sinalizacao:  ## Inicia o servidor local de sinalização WebRTC
	$(PYTHON) servidor_sinalizacao/servidor.py

verificar:  ## Analisa o código com o ruff (se instalado)
	ruff check .

executavel:  ## Gera o executável com PyInstaller
	pyinstaller build/screenshare.spec --noconfirm --clean

limpar:  ## Remove artefatos de build e caches
	rm -rf build/ScreenShare build/screenshare dist __pycache__ */__pycache__ .ruff_cache
