"""Catalogo de emojis, renderizacao em imagem e seletor visual para o chat.

Emojis em Tkinter tem um problema conhecido: o Tcl/Tk 8.6 usa UCS-2
internamente e recusa caracteres acima de U+FFFF, que e justamente onde vive a
maior parte dos emojis. Escrever ``"\U0001f600"`` em um widget resulta em
``TclError`` ou em um retangulo vazio.

A solucao adotada aqui e a mesma dos aplicativos de mensagem: nao desenhar o
caractere, e sim uma **imagem**. O Pillow renderiza o glifo colorido a partir da
fonte de emoji do proprio sistema (Segoe UI Emoji no Windows, Apple Color Emoji
no macOS, Noto Color Emoji no Linux) e o resultado entra no Tk como
``PhotoImage``. Se nenhuma fonte de emoji existir, o modulo degrada em duas
etapas: tenta desenhar o caractere como texto e, em ultimo caso, mantem os
atalhos digitados (``:)``, ``:coracao:``), que funcionam em qualquer ambiente.
"""

from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

from interface.tema import FONTE_PADRAO
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

#: Tamanho, em pixels, dos emojis desenhados dentro do chat.
TAMANHO_EMOJI_CHAT = 18

#: Tamanho dos emojis nos botoes do seletor.
TAMANHO_EMOJI_SELETOR = 26

#: Arquivos de fonte de emoji procurados em cada sistema, na ordem de
#: preferencia. Sao fontes que ja acompanham o sistema operacional: nada e
#: baixado nem embutido no executavel.
CAMINHOS_FONTE_EMOJI: dict[str, tuple[str, ...]] = {
    "win32": (
        r"C:\Windows\Fonts\seguiemj.ttf",
        r"C:\Windows\Fonts\seguisym.ttf",
    ),
    "darwin": (
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "/Library/Fonts/Apple Color Emoji.ttc",
    ),
    "linux": (
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
        "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
    ),
}

#: Fontes de emoji por nome, usadas quando o desenho vai para o proprio Tk.
FONTES_EMOJI: tuple[str, ...] = (
    "Segoe UI Emoji",
    "Apple Color Emoji",
    "Noto Color Emoji",
    "Segoe UI Symbol",
)


@dataclass(frozen=True)
class Emoji:
    """Um emoji do catalogo, com nome e atalhos de digitacao."""

    caractere: str
    nome: str
    atalhos: tuple[str, ...] = ()


#: Catalogo por categoria. Mantido enxuto de proposito: um painel gigante
#: atrapalha mais do que ajuda em uma conversa de trabalho.
CATALOGO: dict[str, tuple[Emoji, ...]] = {
    "Rostos": (
        Emoji("\U0001f600", "sorriso", (":)", ":sorriso:")),
        Emoji("\U0001f602", "chorando de rir", (":rindo:",)),
        Emoji("\U0001f609", "piscada", (";)", ":piscada:")),
        Emoji("\U0001f60e", "estiloso", (":oculos:",)),
        Emoji("\U0001f914", "pensativo", (":pensando:",)),
        Emoji("\U0001f610", "neutro", (":|",)),
        Emoji("\U0001f62c", "sem palavras", (":ops:",)),
        Emoji("\U0001f622", "triste", (":(", ":triste:")),
        Emoji("\U0001f621", "irritado", (":raiva:",)),
        Emoji("\U0001f634", "com sono", (":sono:",)),
        Emoji("\U0001f973", "festa", (":festa:",)),
        Emoji("\U0001f92f", "mente explodindo", (":explodiu:",)),
    ),
    "Gestos": (
        Emoji("\U0001f44d", "positivo", (":+1:", ":ok:")),
        Emoji("\U0001f44e", "negativo", (":-1:",)),
        Emoji("\U0001f44f", "palmas", (":palmas:",)),
        Emoji("\U0001f64f", "por favor", (":favor:",)),
        Emoji("\U0001f4aa", "forca", (":forca:",)),
        Emoji("\U0001f91d", "aperto de mao", (":acordo:",)),
        Emoji("\U0001f44b", "tchau", (":tchau:",)),
        Emoji("\U0001f440", "olhando", (":olhos:",)),
    ),
    "Reacoes": (
        Emoji("\u2764", "coracao", (":coracao:", "<3")),
        Emoji("\U0001f525", "fogo", (":fogo:",)),
        Emoji("\U0001f389", "comemoracao", (":comemorar:",)),
        Emoji("\u2705", "certo", (":certo:",)),
        Emoji("\u274c", "errado", (":errado:",)),
        Emoji("\u26a0", "atencao", (":atencao:",)),
        Emoji("\u2b50", "estrela", (":estrela:",)),
        Emoji("\U0001f4a1", "ideia", (":ideia:",)),
    ),
    "Trabalho": (
        Emoji("\U0001f4bb", "computador", (":pc:",)),
        Emoji("\U0001f5a5", "monitor", (":monitor:",)),
        Emoji("\U0001f3a4", "microfone", (":mic:",)),
        Emoji("\U0001f50a", "som", (":som:",)),
        Emoji("\U0001f507", "sem som", (":mudo:",)),
        Emoji("\U0001f4f9", "gravando", (":gravar:",)),
        Emoji("\U0001f41b", "erro", (":bug:",)),
        Emoji("\U0001f680", "subiu", (":foguete:",)),
        Emoji("\u2615", "cafe", (":cafe:",)),
        Emoji("\U0001f552", "aguardando", (":relogio:",)),
    ),
}

#: Mapa atalho digitado -> caractere, montado uma unica vez.
ATALHOS_EMOJI: dict[str, str] = {
    atalho: emoji.caractere
    for grupo in CATALOGO.values()
    for emoji in grupo
    for atalho in emoji.atalhos
}

#: Conjunto de todos os caracteres do catalogo, para varredura de texto.
CARACTERES_CATALOGO: frozenset[str] = frozenset(
    emoji.caractere for grupo in CATALOGO.values() for emoji in grupo
)


def aplicar_atalhos(texto: str, atalhos: dict[str, str] | None = None) -> str:
    """Troca atalhos digitados pelos emojis correspondentes.

    A substituicao vai do atalho mais longo para o mais curto, para que
    ``:-1:`` nao seja parcialmente consumido por um atalho menor.
    """
    mapa = ATALHOS_EMOJI if atalhos is None else atalhos
    for atalho in sorted(mapa, key=len, reverse=True):
        if atalho in texto:
            texto = texto.replace(atalho, mapa[atalho])
    return texto


def localizar_fonte_emoji() -> Path | None:
    """Devolve o arquivo de fonte de emoji do sistema, se existir."""
    plataforma = "win32" if sys.platform.startswith("win") else sys.platform
    if plataforma not in CAMINHOS_FONTE_EMOJI:
        plataforma = "linux"
    for caminho in CAMINHOS_FONTE_EMOJI[plataforma]:
        arquivo = Path(caminho)
        if arquivo.exists():
            return arquivo
    return None


def nome_fonte_emoji_tk(widget: tk.Misc) -> str:
    """Nome da primeira fonte de emoji instalada, para uso direto no Tk."""
    try:
        from tkinter import font as tkfont

        instaladas = {nome.lower() for nome in tkfont.families(widget)}
    except tk.TclError:  # pragma: no cover - ambiente sem Tk
        return FONTE_PADRAO[0]
    for candidata in FONTES_EMOJI:
        if candidata.lower() in instaladas:
            return candidata
    return FONTE_PADRAO[0]


def texto_suportado_pelo_tk(widget: tk.Misc, caractere: str) -> bool:
    """Informa se o Tk consegue medir (e portanto desenhar) o caractere."""
    try:
        widget.tk.call("font", "measure", FONTE_PADRAO, caractere)
    except tk.TclError:
        return False
    return True


class RenderizadorEmojis:
    """Converte caracteres de emoji em imagens Tk, com cache por tamanho.

    Manter uma referencia viva das imagens e obrigatorio: o Tkinter nao segura
    o objeto ``PhotoImage``, e sem o cache os emojis desapareceriam do chat
    assim que o coletor de lixo passasse.
    """

    def __init__(self, arquivo_fonte: Path | None = None) -> None:
        self._arquivo = arquivo_fonte if arquivo_fonte is not None else localizar_fonte_emoji()
        self._cache: dict[tuple[str, int], ImageTk.PhotoImage] = {}
        self._fontes: dict[int, ImageFont.FreeTypeFont] = {}
        self._avisou = False

    @property
    def disponivel(self) -> bool:
        """``True`` quando existe uma fonte de emoji utilizavel."""
        return self._arquivo is not None

    @property
    def arquivo_fonte(self) -> Path | None:
        """Arquivo de fonte em uso, util para diagnostico."""
        return self._arquivo

    def _fonte(self, tamanho: int) -> ImageFont.FreeTypeFont | None:
        """Carrega (e memoriza) a fonte no tamanho pedido."""
        if self._arquivo is None:
            return None
        if tamanho in self._fontes:
            return self._fontes[tamanho]
        try:
            fonte = ImageFont.truetype(str(self._arquivo), tamanho)
        except OSError:
            # A Noto Color Emoji so aceita 109 px; nesse caso desenhamos grande
            # e reduzimos depois.
            try:
                fonte = ImageFont.truetype(str(self._arquivo), 109)
            except OSError as erro:
                self._registrar_falha(erro)
                self._arquivo = None
                return None
        self._fontes[tamanho] = fonte
        return fonte

    def _registrar_falha(self, erro: Exception) -> None:
        if not self._avisou:
            _registrador.warning("Fonte de emoji indisponivel (%s); usando texto", erro)
            self._avisou = True

    def imagem(self, caractere: str, tamanho: int = TAMANHO_EMOJI_CHAT):
        """Devolve o emoji como imagem Tk, ou ``None`` se nao for possivel."""
        chave = (caractere, tamanho)
        if chave in self._cache:
            return self._cache[chave]
        fonte = self._fonte(tamanho)
        if fonte is None:
            return None
        try:
            lado = max(tamanho, fonte.size)
            tela = Image.new("RGBA", (lado * 2, lado * 2), (0, 0, 0, 0))
            pincel = ImageDraw.Draw(tela)
            pincel.text((lado // 2, lado // 2), caractere, font=fonte, embedded_color=True)
            recorte = tela.getbbox()
            if recorte is None:
                return None
            desenho = tela.crop(recorte).resize((tamanho, tamanho), Image.LANCZOS)
            imagem = ImageTk.PhotoImage(desenho)
        except (OSError, ValueError, tk.TclError) as erro:
            self._registrar_falha(erro)
            return None
        self._cache[chave] = imagem
        return imagem

    def limpar(self) -> None:
        """Descarta o cache (usado ao trocar de tema ou fechar a janela)."""
        self._cache.clear()
        self._fontes.clear()


def inserir_texto_com_emojis(
    widget: tk.Text,
    texto: str,
    renderizador: RenderizadorEmojis | None,
    etiquetas: tuple[str, ...] = (),
) -> None:
    """Insere ``texto`` em um ``Text``, trocando emojis conhecidos por imagens.

    Quando nao ha renderizador (ou ele falhou), o caractere e inserido como
    texto comum, o que ainda funciona nas plataformas com Tk mais novo.
    """
    if renderizador is None or not renderizador.disponivel:
        widget.insert("end", texto, etiquetas)
        return

    acumulado: list[str] = []
    for caractere in texto:
        if caractere in CARACTERES_CATALOGO:
            imagem = renderizador.imagem(caractere)
            if imagem is not None:
                if acumulado:
                    widget.insert("end", "".join(acumulado), etiquetas)
                    acumulado.clear()
                widget.image_create("end", image=imagem)
                continue
        acumulado.append(caractere)
    if acumulado:
        widget.insert("end", "".join(acumulado), etiquetas)


class SeletorEmojis(tk.Toplevel):
    """Janela flutuante com o catalogo, aberta ao lado do campo de mensagem."""

    COLUNAS = 6

    def __init__(
        self,
        mestre: tk.Misc,
        paleta: dict[str, str],
        ao_escolher,
        renderizador: RenderizadorEmojis | None = None,
    ) -> None:
        super().__init__(mestre)
        self._paleta = paleta
        self._ao_escolher = ao_escolher
        self._renderizador = renderizador or RenderizadorEmojis()
        self._imagens: list[ImageTk.PhotoImage] = []

        self.title("Emojis")
        self.transient(mestre.winfo_toplevel())
        self.resizable(False, False)
        self.configure(background=paleta["fundo_painel"])
        try:
            self.attributes("-topmost", True)
        except tk.TclError:  # pragma: no cover - gerenciador de janelas simples
            pass

        self._fonte_tk = (nome_fonte_emoji_tk(self), 16)
        self._construir()
        self.bind("<Escape>", lambda _evento: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # -- Construcao ---------------------------------------------------------

    def _construir(self) -> None:
        abas = ttk.Notebook(self)
        abas.grid(row=0, column=0, padx=8, pady=(8, 4))
        vazio = True
        for categoria, grupo in CATALOGO.items():
            aba, desenhou = self._montar_aba(abas, grupo)
            abas.add(aba, text=categoria)
            vazio = vazio and not desenhou

        rodape = (
            "Clique para inserir. Atalhos de texto tambem funcionam: :) <3 :fogo:"
            if not vazio
            else "Este sistema nao desenha emojis. Use os atalhos: :) <3 :fogo:"
        )
        ttk.Label(self, text=rodape, style="Painel.TLabel").grid(
            row=1, column=0, padx=10, pady=(0, 8), sticky="w"
        )

    def _montar_aba(
        self, mestre: ttk.Notebook, grupo: Iterable[Emoji]
    ) -> tuple[ttk.Frame, bool]:
        quadro = ttk.Frame(mestre, style="Painel.TFrame", padding=6)
        desenhou = False
        for indice, item in enumerate(grupo):
            imagem = self._renderizador.imagem(item.caractere, TAMANHO_EMOJI_SELETOR)
            botao = tk.Button(
                quadro,
                relief="flat",
                background=self._paleta["fundo_painel"],
                activebackground=self._paleta["destaque"],
                foreground=self._paleta["texto"],
                highlightthickness=0,
                borderwidth=0,
                cursor="hand2",
                command=lambda escolhido=item: self._escolher(escolhido),
            )
            if imagem is not None:
                self._imagens.append(imagem)
                botao.configure(image=imagem, width=TAMANHO_EMOJI_SELETOR + 8)
                desenhou = True
            elif texto_suportado_pelo_tk(self, item.caractere):
                botao.configure(text=item.caractere, font=self._fonte_tk, width=2)
                desenhou = True
            else:
                # Sem imagem e sem suporte no Tk: mostra o atalho digitavel.
                atalho = item.atalhos[0] if item.atalhos else item.nome
                botao.configure(text=atalho, width=6)
            botao.grid(
                row=indice // self.COLUNAS,
                column=indice % self.COLUNAS,
                padx=2,
                pady=2,
            )
            self._descrever(botao, item.nome)
        return quadro, desenhou

    def _descrever(self, widget: tk.Widget, nome: str) -> None:
        """Mostra o nome do emoji na barra de titulo ao passar o mouse."""
        widget.bind("<Enter>", lambda _evento: self.title(f"Emojis - {nome}"))
        widget.bind("<Leave>", lambda _evento: self.title("Emojis"))

    # -- Acoes --------------------------------------------------------------

    def _escolher(self, item: Emoji) -> None:
        try:
            self._ao_escolher(item.caractere)
        except Exception as erro:  # pragma: no cover - protecao da interface
            _registrador.warning("Falha ao inserir emoji: %s", erro)
        self.destroy()

    def posicionar_perto(self, widget: tk.Misc) -> None:
        """Coloca a janela logo acima do widget informado, dentro da tela."""
        self.update_idletasks()
        x = widget.winfo_rootx()
        y = widget.winfo_rooty() - self.winfo_height() - 6
        if y < 0:
            y = widget.winfo_rooty() + widget.winfo_height() + 6
        largura_tela = self.winfo_screenwidth()
        x = max(0, min(x, largura_tela - self.winfo_width()))
        self.geometry(f"+{x}+{y}")
