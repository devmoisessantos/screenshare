"""Painel de chat com suporte a emojis, atalhos de texto e mensagens do sistema.

Diferenca em relacao ao `PainelChat` do modo local: aqui os emojis do catalogo
sao desenhados como imagens (o Tk 8.6 do Windows nao aceita emojis fora do
plano basico como texto), existe um botao que abre o seletor e os atalhos
digitados (`:)`, `<3`, `:fogo:`) sao convertidos no envio.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from tkinter import ttk

from interface.emojis import (
    RenderizadorEmojis,
    SeletorEmojis,
    aplicar_atalhos,
    inserir_texto_com_emojis,
)
from interface.tema import FONTE_MONO, FONTE_PADRAO


class ChatRico(ttk.Frame):
    """Historico de mensagens com campo de envio e seletor de emojis."""

    def __init__(
        self,
        mestre: tk.Misc,
        paleta: dict[str, str],
        ao_enviar: Callable[[str], None],
        renderizador: RenderizadorEmojis | None = None,
    ) -> None:
        super().__init__(mestre, style="Barra.TFrame", padding=(8, 8))
        self._paleta = paleta
        self._ao_enviar = ao_enviar
        self._renderizador = renderizador or RenderizadorEmojis()
        self._seletor: SeletorEmojis | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ttk.Label(self, text="Chat da sala", style="Painel.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )

        moldura = tk.Frame(self, background=paleta["fundo_campo"], bd=0)
        moldura.grid(row=1, column=0, columnspan=2, sticky="nsew")
        moldura.columnconfigure(0, weight=1)
        moldura.rowconfigure(0, weight=1)

        self._historico = tk.Text(
            moldura,
            width=30,
            height=12,
            wrap="word",
            state="disabled",
            background=paleta["fundo_campo"],
            foreground=paleta["texto"],
            insertbackground=paleta["texto"],
            relief="flat",
            highlightthickness=0,
            bd=0,
            padx=8,
            pady=8,
            font=FONTE_PADRAO,
            spacing1=2,
            spacing3=4,
        )
        self._historico.grid(row=0, column=0, sticky="nsew")
        barra = ttk.Scrollbar(moldura, orient=tk.VERTICAL, command=self._historico.yview)
        barra.grid(row=0, column=1, sticky="ns")
        self._historico.configure(yscrollcommand=barra.set)

        self._historico.tag_configure("autor_proprio", foreground=paleta["destaque"])
        self._historico.tag_configure("autor_remoto", foreground=paleta["sucesso"])
        self._historico.tag_configure(
            "sistema", foreground=paleta["texto_secundario"], font=FONTE_MONO
        )
        self._historico.tag_configure("horario", foreground=paleta["texto_secundario"])
        self._historico.tag_configure("erro", foreground=paleta["erro"], font=FONTE_MONO)

        linha_envio = ttk.Frame(self, style="Barra.TFrame")
        linha_envio.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        linha_envio.columnconfigure(0, weight=1)

        self._entrada = ttk.Entry(linha_envio)
        self._entrada.grid(row=0, column=0, sticky="ew")
        self._entrada.bind("<Return>", self._enviar)

        self._botao_emoji = ttk.Button(
            linha_envio, text=":)", width=4, command=self.abrir_seletor
        )
        self._botao_emoji.grid(row=0, column=1, padx=(6, 0))
        ttk.Button(linha_envio, text="Enviar", command=self._enviar).grid(
            row=0, column=2, padx=(6, 0)
        )

        ttk.Label(
            self,
            text="Atalhos: :) :( <3 :fogo: :ok: :festa:",
            style="Status.TLabel",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

    # -- Envio --------------------------------------------------------------

    def _enviar(self, _evento: tk.Event | None = None) -> None:
        """Converte atalhos e dispara o callback de envio."""
        texto = aplicar_atalhos(self._entrada.get().strip())
        if not texto:
            return
        self._entrada.delete(0, "end")
        self._ao_enviar(texto)

    def abrir_seletor(self) -> None:
        """Abre (ou fecha) o seletor de emojis junto ao campo de mensagem."""
        if self._seletor is not None and self._seletor.winfo_exists():
            self._seletor.destroy()
            self._seletor = None
            return
        self._seletor = SeletorEmojis(
            self, self._paleta, self._inserir_emoji, self._renderizador
        )
        self._seletor.posicionar_perto(self._botao_emoji)

    def _inserir_emoji(self, emoji: str) -> None:
        """Acrescenta um emoji ao campo de mensagem."""
        self._entrada.insert("end", emoji)
        self._entrada.focus_set()

    # -- Historico ----------------------------------------------------------

    def adicionar_mensagem(self, autor: str, conteudo: str, proprio: bool = False) -> None:
        """Acrescenta uma mensagem de chat, com emojis renderizados."""
        etiqueta = "autor_proprio" if proprio else "autor_remoto"
        self._historico.configure(state="normal")
        self._historico.insert("end", f"[{datetime.now():%H:%M}] ", ("horario",))
        self._historico.insert("end", f"{autor}: ", (etiqueta,))
        inserir_texto_com_emojis(self._historico, conteudo, self._renderizador)
        self._historico.insert("end", "\n")
        self._historico.configure(state="disabled")
        self._historico.see("end")

    def adicionar_sistema(self, texto: str) -> None:
        """Acrescenta um aviso informativo."""
        self._historico.configure(state="normal")
        self._historico.insert("end", f"- {texto}\n", ("sistema",))
        self._historico.configure(state="disabled")
        self._historico.see("end")

    def adicionar_erro(self, texto: str) -> None:
        """Acrescenta um aviso de erro em destaque."""
        self._historico.configure(state="normal")
        self._historico.insert("end", f"! {texto}\n", ("erro",))
        self._historico.configure(state="disabled")
        self._historico.see("end")

    def definir_habilitado(self, habilitado: bool) -> None:
        """Habilita ou bloqueia o envio de mensagens."""
        estado = "normal" if habilitado else "disabled"
        self._entrada.configure(state=estado)
        self._botao_emoji.configure(state=estado)
