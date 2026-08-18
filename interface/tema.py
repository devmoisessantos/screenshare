"""Aplicação de temas visuais nos widgets tkinter/ttk."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from configuracao.configuracoes import obter_tema

FONTE_PADRAO = ("Segoe UI", 10)
FONTE_TITULO = ("Segoe UI", 14, "bold")
FONTE_MONO = ("Consolas", 9)


def aplicar_tema(janela: tk.Misc, nome_tema: str = "escuro") -> dict[str, str]:
    """Configura os estilos ttk da janela e devolve a paleta utilizada.

    Args:
        janela: janela (``Tk`` ou ``Toplevel``) que receberá o tema.
        nome_tema: ``"escuro"`` ou ``"claro"``.

    Returns:
        Dicionário com as cores do tema, para uso em widgets clássicos.
    """
    paleta = obter_tema(nome_tema)
    estilo = ttk.Style(janela)
    try:
        estilo.theme_use("clam")
    except tk.TclError:  # pragma: no cover - tema indisponível
        pass

    janela.configure(background=paleta["fundo"])

    estilo.configure(
        ".",
        background=paleta["fundo"],
        foreground=paleta["texto"],
        fieldbackground=paleta["fundo_campo"],
        font=FONTE_PADRAO,
    )
    estilo.configure("TFrame", background=paleta["fundo"])
    estilo.configure("Painel.TFrame", background=paleta["fundo_painel"])
    estilo.configure(
        "TLabel", background=paleta["fundo"], foreground=paleta["texto"]
    )
    estilo.configure(
        "Painel.TLabel",
        background=paleta["fundo_painel"],
        foreground=paleta["texto"],
    )
    estilo.configure(
        "Secundario.TLabel",
        background=paleta["fundo"],
        foreground=paleta["texto_secundario"],
    )
    estilo.configure("Titulo.TLabel", font=FONTE_TITULO)
    estilo.configure(
        "Status.TLabel",
        background=paleta["fundo_painel"],
        foreground=paleta["texto_secundario"],
        font=FONTE_MONO,
    )
    estilo.configure(
        "TLabelframe",
        background=paleta["fundo"],
        foreground=paleta["texto_secundario"],
        bordercolor=paleta["fundo_campo"],
    )
    estilo.configure(
        "TLabelframe.Label",
        background=paleta["fundo"],
        foreground=paleta["texto_secundario"],
    )
    estilo.configure(
        "TButton",
        background=paleta["fundo_campo"],
        foreground=paleta["texto"],
        borderwidth=0,
        focusthickness=0,
        padding=(12, 7),
    )
    estilo.map(
        "TButton",
        background=[("active", paleta["destaque"]), ("disabled", paleta["fundo_campo"])],
        foreground=[("disabled", paleta["texto_secundario"])],
    )
    estilo.configure(
        "Destaque.TButton",
        background=paleta["destaque"],
        foreground="#ffffff",
    )
    estilo.map("Destaque.TButton", background=[("active", paleta["destaque"])])
    estilo.configure(
        "Perigo.TButton", background=paleta["erro"], foreground="#ffffff"
    )
    estilo.map("Perigo.TButton", background=[("active", paleta["erro"])])
    estilo.configure(
        "TEntry",
        fieldbackground=paleta["fundo_campo"],
        foreground=paleta["texto"],
        insertcolor=paleta["texto"],
        borderwidth=0,
        padding=6,
    )
    estilo.map(
        "TEntry",
        fieldbackground=[("disabled", paleta["fundo_painel"])],
        foreground=[("disabled", paleta["texto_secundario"])],
    )
    estilo.configure(
        "TCombobox",
        fieldbackground=paleta["fundo_campo"],
        background=paleta["fundo_campo"],
        foreground=paleta["texto"],
        arrowcolor=paleta["texto"],
        selectbackground=paleta["fundo_campo"],
        selectforeground=paleta["texto"],
        padding=4,
    )
    # Comboboxes em modo "readonly" precisam de mapeamento explícito para não
    # herdarem as cores claras padrão do tema clam.
    estilo.map(
        "TCombobox",
        fieldbackground=[
            ("readonly", paleta["fundo_campo"]),
            ("disabled", paleta["fundo_painel"]),
        ],
        foreground=[
            ("readonly", paleta["texto"]),
            ("disabled", paleta["texto_secundario"]),
        ],
        selectbackground=[("readonly", paleta["fundo_campo"])],
        selectforeground=[("readonly", paleta["texto"])],
        arrowcolor=[("disabled", paleta["texto_secundario"])],
    )
    # Lista suspensa do combobox (widget clássico interno).
    janela.option_add("*TCombobox*Listbox.background", paleta["fundo_campo"])
    janela.option_add("*TCombobox*Listbox.foreground", paleta["texto"])
    janela.option_add("*TCombobox*Listbox.selectBackground", paleta["destaque"])
    janela.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    estilo.configure(
        "TCheckbutton",
        background=paleta["fundo"],
        foreground=paleta["texto"],
        focuscolor=paleta["fundo"],
    )
    estilo.configure(
        "TScale", background=paleta["fundo"], troughcolor=paleta["fundo_campo"]
    )
    estilo.configure("TSeparator", background=paleta["fundo_campo"])

    # Abas: o tema clam usa cinza claro com texto escuro, ilegivel no escuro.
    estilo.configure("TNotebook", background=paleta["fundo"], borderwidth=0)
    estilo.configure(
        "TNotebook.Tab",
        background=paleta["fundo_painel"],
        foreground=paleta["texto_secundario"],
        padding=(14, 8),
        borderwidth=0,
    )
    estilo.map(
        "TNotebook.Tab",
        background=[("selected", paleta["fundo_campo"]), ("active", paleta["fundo_campo"])],
        foreground=[("selected", paleta["texto"]), ("active", paleta["texto"])],
    )

    # Estilos usados pela interface de chamada (modo internet).
    estilo.configure("Barra.TFrame", background=paleta["fundo_painel"])
    estilo.configure("Cartao.TFrame", background=paleta["fundo_campo"])
    estilo.configure(
        "Cartao.TLabel",
        background=paleta["fundo_campo"],
        foreground=paleta["texto"],
    )
    estilo.configure(
        "CartaoSecundario.TLabel",
        background=paleta["fundo_campo"],
        foreground=paleta["texto_secundario"],
    )
    estilo.configure(
        "Sucesso.TButton", background=paleta["sucesso"], foreground="#ffffff"
    )
    estilo.map("Sucesso.TButton", background=[("active", paleta["sucesso"])])
    estilo.configure(
        "Barra.TButton",
        background=paleta["fundo_campo"],
        foreground=paleta["texto"],
        padding=(10, 8),
    )
    estilo.map("Barra.TButton", background=[("active", paleta["destaque"])])
    estilo.configure(
        "Painel.TCheckbutton",
        background=paleta["fundo_painel"],
        foreground=paleta["texto"],
        focuscolor=paleta["fundo_painel"],
    )
    estilo.configure(
        "Painel.TScale",
        background=paleta["fundo_painel"],
        troughcolor=paleta["fundo_campo"],
    )
    return paleta
