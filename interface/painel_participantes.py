"""Lista lateral de participantes, no estilo do painel de voz do Discord.

Cada participante aparece com um avatar circular (as iniciais do apelido), o
apelido, o estado da conexao e dois indicadores: microfone mudo e
compartilhamento de tela ativo.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from interface.tema import FONTE_PADRAO
from nucleo.chamada import Participante

#: Cores usadas para gerar avatares deterministicos a partir do apelido.
CORES_AVATAR: tuple[str, ...] = (
    "#5865f2",
    "#3ba55d",
    "#faa61a",
    "#ed4245",
    "#9b59b6",
    "#1abc9c",
)


def cor_do_apelido(apelido: str) -> str:
    """Escolhe sempre a mesma cor para o mesmo apelido."""
    if not apelido:
        return CORES_AVATAR[0]
    return CORES_AVATAR[sum(apelido.encode("utf-8")) % len(CORES_AVATAR)]


def iniciais(apelido: str) -> str:
    """Extrai ate duas letras para o avatar."""
    partes = [parte for parte in apelido.split() if parte]
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[1][0]).upper()


class LinhaParticipante(ttk.Frame):
    """Uma linha da lista de participantes."""

    def __init__(self, mestre: tk.Misc, paleta: dict[str, str], participante: Participante) -> None:
        super().__init__(mestre, style="Barra.TFrame", padding=(8, 5))
        self._paleta = paleta
        self.participante = participante

        self._avatar = tk.Canvas(
            self,
            width=32,
            height=32,
            background=paleta["fundo_painel"],
            highlightthickness=0,
            bd=0,
        )
        self._avatar.pack(side=tk.LEFT)

        textos = ttk.Frame(self, style="Barra.TFrame")
        textos.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        self._apelido = ttk.Label(textos, style="Painel.TLabel", font=FONTE_PADRAO)
        self._apelido.pack(anchor="w")
        self._estado = ttk.Label(textos, style="Status.TLabel")
        self._estado.pack(anchor="w")

        self._indicadores = ttk.Label(self, style="Painel.TLabel")
        self._indicadores.pack(side=tk.RIGHT)

        self.atualizar(participante)

    def atualizar(self, participante: Participante) -> None:
        """Redesenha a linha com os dados mais recentes."""
        self.participante = participante
        self._apelido.configure(text=participante.apelido[:24])
        self._estado.configure(text=participante.descricao_estado)
        marcas = []
        if not participante.microfone_ativo:
            marcas.append("mudo")
        if participante.compartilhando:
            marcas.append("tela")
        self._indicadores.configure(text=" / ".join(marcas))
        self._desenhar_avatar(participante)

    def _desenhar_avatar(self, participante: Participante) -> None:
        """Desenha o circulo com as iniciais e a borda de estado."""
        self._avatar.delete("all")
        cor = cor_do_apelido(participante.apelido)
        borda = self._paleta["sucesso"] if participante.estado == "connected" else self._paleta[
            "texto_secundario"
        ]
        if participante.estado == "failed":
            borda = self._paleta["erro"]
        self._avatar.create_oval(1, 1, 31, 31, fill=cor, outline=borda, width=2)
        self._avatar.create_text(
            16, 16, text=iniciais(participante.apelido), fill="#ffffff", font=("Segoe UI", 9, "bold")
        )


class PainelParticipantes(ttk.Frame):
    """Painel com o cabecalho da sala e a lista de participantes."""

    def __init__(self, mestre: tk.Misc, paleta: dict[str, str]) -> None:
        super().__init__(mestre, style="Barra.TFrame", padding=(6, 8))
        self._paleta = paleta
        self._linhas: dict[str, LinhaParticipante] = {}

        self._titulo = ttk.Label(self, text="Participantes", style="Painel.TLabel")
        self._titulo.pack(anchor="w", padx=6)
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)
        self._lista = ttk.Frame(self, style="Barra.TFrame")
        self._lista.pack(fill=tk.BOTH, expand=True)

    def atualizar(self, participantes: list[Participante]) -> None:
        """Sincroniza as linhas com a lista recebida da chamada."""
        self._titulo.configure(text=f"Participantes ({len(participantes)})")
        vistos = set()
        for participante in participantes:
            vistos.add(participante.identificador)
            linha = self._linhas.get(participante.identificador)
            if linha is None:
                linha = LinhaParticipante(self._lista, self._paleta, participante)
                linha.pack(fill=tk.X, pady=1)
                self._linhas[participante.identificador] = linha
            else:
                linha.atualizar(participante)
        for identificador in list(self._linhas):
            if identificador not in vistos:
                self._linhas.pop(identificador).destroy()
