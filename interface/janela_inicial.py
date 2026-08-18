"""Janela inicial: escolha entre compartilhar a tela ou assistir."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from configuracao.configuracoes import (
    ATALHOS,
    NOME_APLICACAO,
    VERSAO_APLICACAO,
    Configuracoes,
    diretorio_dados,
)
from interface.janela_cliente import JanelaCliente
from interface.janela_servidor import JanelaServidor
from interface.tema import aplicar_tema
from midia.captura_audio import descrever_motor_audio
from utilitarios.recursos import aplicar_icone
from utilitarios.rede import ip_local_recomendado


class JanelaInicial(tk.Tk):
    """Menu principal da aplicação."""

    def __init__(self, configuracoes: Configuracoes | None = None) -> None:
        super().__init__()
        self.configuracoes = configuracoes or Configuracoes.carregar()
        self.title(f"{NOME_APLICACAO} {VERSAO_APLICACAO}")
        self.geometry("520x430")
        self.minsize(480, 400)
        self.resizable(True, True)

        self._paleta = aplicar_tema(self, self.configuracoes.interface.tema)
        aplicar_icone(self)
        self._janelas: list[tk.Toplevel] = []
        self._construir_interface()
        self.bind("<Control-q>", lambda _e: self._ao_fechar())
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    # -- Interface ----------------------------------------------------------

    def _construir_interface(self) -> None:
        """Monta os widgets do menu principal."""
        self.columnconfigure(0, weight=1)

        cabecalho = ttk.Frame(self, padding=(24, 24, 24, 8))
        cabecalho.grid(row=0, column=0, sticky="ew")
        cabecalho.columnconfigure(0, weight=1)
        ttk.Label(cabecalho, text=NOME_APLICACAO, style="Titulo.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            cabecalho,
            text="Compartilhamento de tela ponto a ponto com áudio e chat",
            style="Secundario.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        corpo = ttk.Frame(self, padding=(24, 8))
        corpo.grid(row=1, column=0, sticky="ew")
        corpo.columnconfigure(0, weight=1)

        self._var_apelido = tk.StringVar(value=self.configuracoes.interface.apelido)
        linha_apelido = ttk.Frame(corpo)
        linha_apelido.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        linha_apelido.columnconfigure(1, weight=1)
        ttk.Label(linha_apelido, text="Seu apelido").grid(row=0, column=0, sticky="w")
        ttk.Entry(linha_apelido, textvariable=self._var_apelido).grid(
            row=0, column=1, sticky="ew", padx=(10, 0)
        )

        ttk.Button(
            corpo,
            text="Compartilhar minha tela  (ser host)",
            style="Destaque.TButton",
            command=self._abrir_servidor,
        ).grid(row=1, column=0, sticky="ew", pady=(0, 10))

        ttk.Button(
            corpo,
            text="Assistir a uma tela  (ser espectador)",
            command=self._abrir_cliente,
        ).grid(row=2, column=0, sticky="ew")

        ttk.Separator(corpo, orient="horizontal").grid(
            row=3, column=0, sticky="ew", pady=16
        )

        self._var_tema = tk.StringVar(value=self.configuracoes.interface.tema)
        linha_tema = ttk.Frame(corpo)
        linha_tema.grid(row=4, column=0, sticky="ew")
        ttk.Label(linha_tema, text="Tema").grid(row=0, column=0, sticky="w")
        seletor = ttk.Combobox(
            linha_tema,
            textvariable=self._var_tema,
            values=["escuro", "claro"],
            state="readonly",
            width=12,
        )
        seletor.grid(row=0, column=1, padx=(10, 0))
        seletor.bind("<<ComboboxSelected>>", self._trocar_tema)

        informacoes = ttk.Frame(self, padding=(24, 8, 24, 20))
        informacoes.grid(row=2, column=0, sticky="ew")
        informacoes.columnconfigure(0, weight=1)
        texto = (
            f"IP local: {ip_local_recomendado()}\n"
            f"{descrever_motor_audio()}\n"
            f"Dados e logs: {diretorio_dados()}\n"
            "Atalhos: " + ", ".join(f"{tecla} = {acao}" for tecla, acao in ATALHOS.items())
        )
        ttk.Label(
            informacoes, text=texto, style="Secundario.TLabel", justify="left", wraplength=460
        ).grid(row=0, column=0, sticky="w")

    # -- Ações --------------------------------------------------------------

    def _sincronizar_apelido(self) -> None:
        """Aplica o apelido digitado nas configurações e salva."""
        self.configuracoes.interface.apelido = (
            self._var_apelido.get().strip() or self.configuracoes.interface.apelido
        )
        try:
            self.configuracoes.salvar()
        except OSError:  # pragma: no cover
            pass

    def _trocar_tema(self, _evento: tk.Event | None = None) -> None:
        """Troca o tema visual do menu (janelas novas herdam a escolha)."""
        self.configuracoes.interface.tema = self._var_tema.get()
        self._paleta = aplicar_tema(self, self.configuracoes.interface.tema)
        try:
            self.configuracoes.salvar()
        except OSError:  # pragma: no cover
            pass

    def _abrir_servidor(self) -> None:
        """Abre a janela do host."""
        self._sincronizar_apelido()
        self._registrar(JanelaServidor(self, self.configuracoes))

    def _abrir_cliente(self) -> None:
        """Abre a janela do espectador."""
        self._sincronizar_apelido()
        self._registrar(JanelaCliente(self, self.configuracoes))

    def _registrar(self, janela: tk.Toplevel) -> None:
        """Guarda a referência da janela e a coloca em foco."""
        self._janelas.append(janela)
        janela.focus_set()

    def _ao_fechar(self) -> None:
        """Fecha as janelas filhas e encerra a aplicação."""
        self._sincronizar_apelido()
        for janela in list(self._janelas):
            try:
                janela.destroy()
            except tk.TclError:  # pragma: no cover
                pass
        self.destroy()
