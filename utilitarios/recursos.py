"""Localização de arquivos de recursos (ícones), inclusive dentro do executável."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)


def diretorio_base() -> Path:
    """Diretório raiz dos arquivos do projeto ou do executável PyInstaller."""
    base_pyinstaller = getattr(sys, "_MEIPASS", None)
    if base_pyinstaller:
        return Path(base_pyinstaller)
    return Path(__file__).resolve().parent.parent


def caminho_recurso(nome_relativo: str) -> Path:
    """Devolve o caminho absoluto de um recurso empacotado."""
    return diretorio_base() / nome_relativo


def aplicar_icone(janela: tk.Misc) -> None:
    """Aplica o ícone da aplicação na janela, ignorando falhas silenciosamente."""
    try:
        if sys.platform.startswith("win"):
            caminho_ico = caminho_recurso("recursos/icone.ico")
            if caminho_ico.exists():
                janela.iconbitmap(str(caminho_ico))  # type: ignore[attr-defined]
                return
        caminho_png = caminho_recurso("recursos/icone.png")
        if caminho_png.exists():
            imagem = tk.PhotoImage(master=janela, file=str(caminho_png))
            janela.iconphoto(True, imagem)  # type: ignore[attr-defined]
            # Mantém a referência para o coletor de lixo não descartar a imagem.
            janela._icone_referencia = imagem
    except tk.TclError as erro:  # pragma: no cover - dependente do sistema
        _registrador.debug("Não foi possível aplicar o ícone: %s", erro)
