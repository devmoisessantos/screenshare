"""Componentes reutilizáveis da interface gráfica.

Contém o painel de chat, o painel de estatísticas, o visualizador de vídeo e
uma ponte thread-safe entre as threads de rede e a thread da interface.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageTk

from interface.tema import FONTE_MONO, FONTE_PADRAO
from utilitarios.rede import formatar_taxa


class PonteInterface:
    """Executa callbacks das threads de rede dentro da thread da interface.

    As threads de trabalho chamam :meth:`agendar`, que enfileira a função; a
    interface consome a fila periodicamente com ``after``, evitando o uso
    concorrente (e inseguro) dos widgets tkinter.
    """

    def __init__(self, widget: tk.Misc, intervalo_ms: int = 30) -> None:
        self._widget = widget
        self._intervalo_ms = intervalo_ms
        self._fila: queue.Queue[tuple[Callable[..., Any], tuple]] = queue.Queue()
        self._ativa = True
        self._widget.after(self._intervalo_ms, self._processar)

    def agendar(self, funcao: Callable[..., Any], *argumentos: Any) -> None:
        """Enfileira uma função para execução na thread da interface."""
        if self._ativa:
            self._fila.put((funcao, argumentos))

    def _processar(self) -> None:
        """Consome a fila e reagenda a próxima verificação."""
        while True:
            try:
                funcao, argumentos = self._fila.get_nowait()
            except queue.Empty:
                break
            try:
                funcao(*argumentos)
            except tk.TclError:
                self._ativa = False
                return
        if self._ativa:
            try:
                self._widget.after(self._intervalo_ms, self._processar)
            except tk.TclError:  # pragma: no cover - janela destruída
                self._ativa = False

    def encerrar(self) -> None:
        """Interrompe o processamento da fila."""
        self._ativa = False


class PainelChat(ttk.Frame):
    """Área de histórico de mensagens com campo de envio."""

    def __init__(
        self,
        mestre: tk.Misc,
        paleta: dict[str, str],
        ao_enviar: Callable[[str], None],
    ) -> None:
        super().__init__(mestre, style="TFrame")
        self._paleta = paleta
        self._ao_enviar = ao_enviar

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ttk.Label(self, text="Chat", style="Secundario.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )

        moldura = tk.Frame(self, background=paleta["fundo_campo"], bd=0)
        moldura.grid(row=1, column=0, columnspan=2, sticky="nsew")
        moldura.columnconfigure(0, weight=1)
        moldura.rowconfigure(0, weight=1)

        self._historico = tk.Text(
            moldura,
            height=10,
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
        )
        self._historico.grid(row=0, column=0, sticky="nsew")

        barra = ttk.Scrollbar(moldura, orient="vertical", command=self._historico.yview)
        barra.grid(row=0, column=1, sticky="ns")
        self._historico.configure(yscrollcommand=barra.set)

        self._historico.tag_configure("autor_proprio", foreground=paleta["destaque"])
        self._historico.tag_configure("autor_remoto", foreground=paleta["sucesso"])
        self._historico.tag_configure(
            "sistema", foreground=paleta["texto_secundario"], font=FONTE_MONO
        )
        self._historico.tag_configure("horario", foreground=paleta["texto_secundario"])

        self._entrada = ttk.Entry(self)
        self._entrada.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self._entrada.bind("<Return>", self._enviar)

        ttk.Button(self, text="Enviar", command=self._enviar).grid(
            row=2, column=1, sticky="e", padx=(8, 0), pady=(8, 0)
        )

    # -- Ações --------------------------------------------------------------

    def _enviar(self, _evento: tk.Event | None = None) -> None:
        """Lê o campo de texto e dispara o callback de envio."""
        texto = self._entrada.get().strip()
        if not texto:
            return
        self._entrada.delete(0, "end")
        self._ao_enviar(texto)

    def adicionar_mensagem(
        self, autor: str, conteudo: str, horario: str = "", proprio: bool = False
    ) -> None:
        """Acrescenta uma mensagem de chat ao histórico."""
        etiqueta = "autor_proprio" if proprio else "autor_remoto"
        self._historico.configure(state="normal")
        if horario:
            self._historico.insert("end", f"[{horario}] ", "horario")
        self._historico.insert("end", f"{autor}: ", etiqueta)
        self._historico.insert("end", f"{conteudo}\n")
        self._historico.configure(state="disabled")
        self._historico.see("end")

    def adicionar_sistema(self, texto: str) -> None:
        """Acrescenta uma mensagem informativa do sistema."""
        self._historico.configure(state="normal")
        self._historico.insert("end", f"- {texto}\n", "sistema")
        self._historico.configure(state="disabled")
        self._historico.see("end")

    def definir_habilitado(self, habilitado: bool) -> None:
        """Habilita ou desabilita o campo de envio."""
        self._entrada.configure(state="normal" if habilitado else "disabled")


class PainelEstatisticas(ttk.Frame):
    """Exibe FPS, latência, qualidade e taxa de transferência."""

    def __init__(self, mestre: tk.Misc, paleta: dict[str, str]) -> None:
        super().__init__(mestre, style="Painel.TFrame", padding=8)
        self._paleta = paleta
        self._variavel = tk.StringVar(value="Aguardando dados...")
        ttk.Label(
            self, textvariable=self._variavel, style="Status.TLabel", anchor="w"
        ).pack(fill="x")

    def atualizar(self, estatisticas: Any) -> None:
        """Atualiza o texto do painel com as métricas da sessão."""
        self._variavel.set(
            f"FPS envio: {estatisticas.fps_envio:.0f}  |  FPS recepção: {estatisticas.fps_recepcao:.0f}  |  Latência: {estatisticas.latencia_ms:.0f} ms  |  "
            f"Qualidade: {estatisticas.qualidade}  |  Subida: {formatar_taxa(estatisticas.taxa_envio)}  |  Descida: {formatar_taxa(estatisticas.taxa_recepcao)}  |  Descartados: {estatisticas.quadros_descartados}"
        )

    def definir_texto(self, texto: str) -> None:
        """Define um texto livre no painel."""
        self._variavel.set(texto)


class VisualizadorVideo(ttk.Frame):
    """Exibe os quadros recebidos preservando a proporção da tela original."""

    def __init__(self, mestre: tk.Misc, paleta: dict[str, str]) -> None:
        super().__init__(mestre, style="TFrame")
        self._paleta = paleta
        self._trava = threading.Lock()
        self._quadro_pendente: np.ndarray | None = None
        self._imagem: ImageTk.PhotoImage | None = None

        self.canvas = tk.Canvas(
            self,
            background="#000000",
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.canvas.pack(fill="both", expand=True)
        self._texto_id = self.canvas.create_text(
            10, 10, text="Aguardando vídeo...", fill=paleta["texto_secundario"], anchor="nw"
        )

    # -- Atualização --------------------------------------------------------

    def definir_quadro(self, quadro_rgb: np.ndarray) -> None:
        """Registra o quadro mais recente (pode ser chamado de outra thread)."""
        with self._trava:
            self._quadro_pendente = quadro_rgb

    def renderizar(self) -> None:
        """Desenha o quadro pendente no canvas (thread da interface)."""
        with self._trava:
            quadro = self._quadro_pendente
            self._quadro_pendente = None
        if quadro is None:
            return

        largura_canvas = max(1, self.canvas.winfo_width())
        altura_canvas = max(1, self.canvas.winfo_height())
        altura, largura = quadro.shape[:2]
        escala = min(largura_canvas / largura, altura_canvas / altura)
        nova_largura = max(1, int(largura * escala))
        nova_altura = max(1, int(altura * escala))

        imagem = Image.fromarray(quadro)
        if (nova_largura, nova_altura) != (largura, altura):
            imagem = imagem.resize((nova_largura, nova_altura), Image.BILINEAR)

        self._imagem = ImageTk.PhotoImage(imagem)
        self.canvas.delete("quadro")
        self.canvas.itemconfigure(self._texto_id, state="hidden")
        self.canvas.create_image(
            largura_canvas // 2,
            altura_canvas // 2,
            image=self._imagem,
            anchor="center",
            tags="quadro",
        )

    def limpar(self, mensagem: str = "Sem vídeo") -> None:
        """Remove a imagem exibida e mostra uma mensagem."""
        self.canvas.delete("quadro")
        self._imagem = None
        self.canvas.itemconfigure(self._texto_id, state="normal", text=mensagem)
