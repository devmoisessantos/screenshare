"""Janela de escolha do que sera transmitido (tela, monitor ou janela).

Reproduz a ideia do seletor do Discord: as fontes aparecem em cartoes com
miniatura ao vivo, agrupadas em duas abas ("Telas" e "Janelas"). O usuario
clica em um cartao e confirma.

As miniaturas sao capturadas sob demanda com `mss` em uma thread, para que a
janela nunca congele quando houver muitos monitores ou janelas abertas.
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import numpy as np
from PIL import Image, ImageTk

from interface.tema import aplicar_tema
from midia.fontes import MOTIVO_JANELAS_INDISPONIVEIS, FonteCaptura, listar_fontes
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

#: Tamanho dos cartoes de miniatura, em pixels.
LARGURA_MINIATURA = 208
ALTURA_MINIATURA = 117


def _capturar_miniatura(fonte: FonteCaptura) -> Image.Image | None:
    """Captura uma imagem reduzida da fonte, ou ``None`` em caso de falha."""
    try:
        import mss

        with mss.mss() as captura:
            bruto = captura.grab(fonte.regiao)
            imagem = Image.frombytes("RGB", bruto.size, bruto.rgb)
    except Exception as erro:  # pragma: no cover - depende do ambiente grafico
        _registrador.debug("Miniatura indisponivel para %s: %s", fonte.titulo, erro)
        return None
    imagem.thumbnail((LARGURA_MINIATURA, ALTURA_MINIATURA))
    return imagem


def _imagem_vazia(paleta: dict[str, str]) -> Image.Image:
    """Cria um retangulo neutro para fontes sem miniatura disponivel."""
    cor = paleta["fundo_painel"].lstrip("#")
    rgb = tuple(int(cor[indice : indice + 2], 16) for indice in (0, 2, 4))
    matriz = np.full((ALTURA_MINIATURA, LARGURA_MINIATURA, 3), rgb, dtype=np.uint8)
    return Image.fromarray(matriz)


class CartaoFonte(ttk.Frame):
    """Cartao clicavel que representa uma fonte de captura."""

    def __init__(
        self,
        mestre: tk.Misc,
        paleta: dict[str, str],
        fonte: FonteCaptura,
        ao_selecionar: Callable[[FonteCaptura], None],
        ao_confirmar: Callable[[FonteCaptura], None],
    ) -> None:
        super().__init__(mestre, style="Cartao.TFrame", padding=6)
        self.paleta = paleta
        self.fonte = fonte
        self._ao_selecionar = ao_selecionar
        self._ao_confirmar = ao_confirmar
        self._selecionado = False

        self._imagem: ImageTk.PhotoImage | None = None
        self._rotulo_imagem = tk.Label(
            self,
            background=paleta["fundo_painel"],
            width=LARGURA_MINIATURA,
            height=ALTURA_MINIATURA,
            borderwidth=0,
            highlightthickness=0,
        )
        self._rotulo_imagem.pack()
        self._titulo = ttk.Label(
            self,
            text=self._encurtar(fonte.titulo),
            style="Cartao.TLabel",
            wraplength=LARGURA_MINIATURA,
            justify="center",
        )
        self._titulo.pack(fill=tk.X, pady=(6, 0))
        self._subtitulo = ttk.Label(
            self,
            text=self._descricao(),
            style="CartaoSecundario.TLabel",
            wraplength=LARGURA_MINIATURA,
            justify="center",
        )
        self._subtitulo.pack(fill=tk.X)

        for widget in (self, self._rotulo_imagem, self._titulo, self._subtitulo):
            widget.bind("<Button-1>", self._clicar)
            widget.bind("<Double-Button-1>", self._duplo_clique)

    def _descricao(self) -> str:
        """Texto auxiliar com tipo e tamanho da fonte."""
        regiao = self.fonte.regiao
        tipos = {"tela": "Tela inteira", "monitor": "Monitor", "janela": "Janela"}
        tipo = tipos.get(self.fonte.tipo, self.fonte.tipo)
        return f"{tipo} - {regiao.get('width', 0)}x{regiao.get('height', 0)}"

    @staticmethod
    def _encurtar(titulo: str, limite: int = 46) -> str:
        """Evita titulos longos quebrando o layout do cartao."""
        titulo = " ".join(titulo.split())
        if len(titulo) <= limite:
            return titulo
        return titulo[: limite - 3] + "..."

    def definir_miniatura(self, imagem: Image.Image) -> None:
        """Troca a imagem exibida no cartao."""
        self._imagem = ImageTk.PhotoImage(imagem)
        self._rotulo_imagem.configure(image=self._imagem)

    def definir_selecionado(self, selecionado: bool) -> None:
        """Realca visualmente o cartao escolhido."""
        self._selecionado = selecionado
        cor = self.paleta["destaque"] if selecionado else self.paleta["fundo_campo"]
        self.configure(relief="solid" if selecionado else "flat")
        self._rotulo_imagem.configure(
            highlightthickness=3 if selecionado else 0, highlightbackground=cor
        )

    def _clicar(self, _evento: tk.Event) -> None:
        """Marca o cartao como selecionado."""
        self._ao_selecionar(self.fonte)

    def _duplo_clique(self, _evento: tk.Event) -> None:
        """Seleciona e confirma de uma vez."""
        self._ao_selecionar(self.fonte)
        self._ao_confirmar(self.fonte)


class SeletorFonte(tk.Toplevel):
    """Janela modal de escolha da fonte de transmissao."""

    def __init__(
        self,
        mestre: tk.Misc,
        paleta: dict[str, str] | None = None,
        ao_escolher: Callable[[FonteCaptura], None] | None = None,
        incluir_audio: bool = True,
    ) -> None:
        super().__init__(mestre)
        self.title("Escolher o que transmitir")
        self.geometry("760x560")
        self.minsize(640, 480)
        self.paleta = paleta or aplicar_tema(self)
        self._ao_escolher = ao_escolher
        self._fonte_escolhida: FonteCaptura | None = None
        self._cartoes: list[CartaoFonte] = []
        self._encerrado = False
        self.compartilhar_audio = tk.BooleanVar(value=incluir_audio)

        self._montar()
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        self.bind("<Escape>", lambda _evento: self.fechar())
        self.bind("<Return>", lambda _evento: self._confirmar())
        self.atualizar_fontes()

    # -- Montagem -----------------------------------------------------------

    def _montar(self) -> None:
        """Cria abas, area de cartoes e barra inferior."""
        topo = ttk.Frame(self, padding=(16, 14, 16, 6))
        topo.pack(fill=tk.X)
        ttk.Label(topo, text="O que voce quer transmitir?", style="Titulo.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            topo,
            text="Clique em uma opcao e confirme. Um clique duplo transmite direto.",
            style="Secundario.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        self._abas = ttk.Notebook(self)
        self._abas.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        self._aba_telas = ttk.Frame(self._abas, padding=8)
        self._aba_janelas = ttk.Frame(self._abas, padding=8)
        self._abas.add(self._aba_telas, text="  Telas  ")
        self._abas.add(self._aba_janelas, text="  Janelas  ")

        self._area_telas = self._criar_area_rolavel(self._aba_telas)
        self._area_janelas = self._criar_area_rolavel(self._aba_janelas)

        rodape = ttk.Frame(self, style="Barra.TFrame", padding=(16, 12))
        rodape.pack(fill=tk.X)
        ttk.Checkbutton(
            rodape,
            text="Enviar tambem o meu microfone",
            variable=self.compartilhar_audio,
            style="Painel.TCheckbutton",
        ).pack(side=tk.LEFT)
        ttk.Button(rodape, text="Cancelar", command=self.fechar).pack(
            side=tk.RIGHT, padx=(8, 0)
        )
        self._botao_confirmar = ttk.Button(
            rodape,
            text="Transmitir",
            style="Destaque.TButton",
            command=self._confirmar,
            state=tk.DISABLED,
        )
        self._botao_confirmar.pack(side=tk.RIGHT)
        ttk.Button(rodape, text="Atualizar lista", command=self.atualizar_fontes).pack(
            side=tk.RIGHT, padx=(8, 8)
        )

    def _criar_area_rolavel(self, mestre: tk.Misc) -> tk.Frame:
        """Cria um canvas com barra de rolagem e devolve o frame interno."""
        canvas = tk.Canvas(
            mestre,
            background=self.paleta["fundo"],
            highlightthickness=0,
            borderwidth=0,
        )
        barra = ttk.Scrollbar(mestre, orient=tk.VERTICAL, command=canvas.yview)
        interno = tk.Frame(canvas, background=self.paleta["fundo"])
        canvas.create_window((0, 0), window=interno, anchor="nw")
        canvas.configure(yscrollcommand=barra.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        barra.pack(side=tk.RIGHT, fill=tk.Y)
        interno.bind(
            "<Configure>",
            lambda _evento: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<MouseWheel>",
            lambda evento: canvas.yview_scroll(-1 * (evento.delta // 120), "units"),
        )
        return interno

    # -- Fontes -------------------------------------------------------------

    def atualizar_fontes(self) -> None:
        """Recarrega a lista de fontes e recria os cartoes."""
        for cartao in self._cartoes:
            cartao.destroy()
        self._cartoes.clear()
        for area in (self._area_telas, self._area_janelas):
            for filho in area.winfo_children():
                filho.destroy()

        fontes = listar_fontes()
        telas = [item for item in fontes if item.tipo in {"tela", "monitor"}]
        janelas = [item for item in fontes if item.tipo == "janela"]

        self._preencher(self._area_telas, telas, colunas=3)
        if janelas:
            self._preencher(self._area_janelas, janelas, colunas=3)
        else:
            ttk.Label(
                self._area_janelas,
                text=(
                    "Nenhuma janela detectada.\n"
                    f"{MOTIVO_JANELAS_INDISPONIVEIS or 'Use a aba Telas para transmitir.'}"
                ),
                style="Secundario.TLabel",
                justify="left",
            ).grid(row=0, column=0, padx=12, pady=12, sticky="w")

        if telas:
            self._selecionar(telas[0])
        self._carregar_miniaturas()

    def _preencher(self, area: tk.Misc, fontes: list[FonteCaptura], colunas: int) -> None:
        """Distribui os cartoes em uma grade."""
        for indice, fonte in enumerate(fontes):
            cartao = CartaoFonte(
                area, self.paleta, fonte, self._selecionar, self._confirmar_fonte
            )
            cartao.definir_miniatura(_imagem_vazia(self.paleta))
            cartao.grid(
                row=indice // colunas,
                column=indice % colunas,
                padx=8,
                pady=8,
                sticky="nsew",
            )
            self._cartoes.append(cartao)

    def _carregar_miniaturas(self) -> None:
        """Captura as miniaturas em uma thread e aplica na interface."""
        cartoes = list(self._cartoes)

        def trabalho() -> None:
            for cartao in cartoes:
                imagem = _capturar_miniatura(cartao.fonte)
                if imagem is None:
                    continue
                self._aplicar_miniatura(cartao, imagem)

        threading.Thread(target=trabalho, name="miniaturas", daemon=True).start()

    def _aplicar_miniatura(self, cartao: CartaoFonte, imagem: Image.Image) -> None:
        """Agenda a troca da miniatura na thread da interface."""
        if self._encerrado:
            return
        try:
            self.after(0, lambda: self._trocar_miniatura(cartao, imagem))
        except tk.TclError:  # pragma: no cover - janela fechada durante a captura
            pass

    def _trocar_miniatura(self, cartao: CartaoFonte, imagem: Image.Image) -> None:
        """Aplica a miniatura se o cartao ainda existir."""
        if self._encerrado or not cartao.winfo_exists():
            return
        cartao.definir_miniatura(imagem)

    # -- Selecao ------------------------------------------------------------

    def _selecionar(self, fonte: FonteCaptura) -> None:
        """Guarda a fonte escolhida e realca o cartao correspondente."""
        self._fonte_escolhida = fonte
        for cartao in self._cartoes:
            cartao.definir_selecionado(cartao.fonte is fonte)
        self._botao_confirmar.configure(state=tk.NORMAL)

    def _confirmar(self) -> None:
        """Confirma a fonte atualmente selecionada."""
        if self._fonte_escolhida is not None:
            self._confirmar_fonte(self._fonte_escolhida)

    def _confirmar_fonte(self, fonte: FonteCaptura) -> None:
        """Entrega a fonte ao chamador e fecha a janela."""
        if self._ao_escolher is not None:
            self._ao_escolher(fonte)
        self.fechar()

    def fechar(self) -> None:
        """Fecha a janela liberando as miniaturas."""
        if self._encerrado:
            return
        self._encerrado = True
        self.destroy()
