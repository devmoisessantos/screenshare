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
        self._ultimo_quadro: np.ndarray | None = None
        self._tamanho_desenhado: tuple[int, int] = (0, 0)
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
        # Redesenha ao redimensionar: sem isso um quadro desenhado antes de a
        # janela ter tamanho final ficaria minúsculo até chegar o próximo.
        self.canvas.bind("<Configure>", self._ao_redimensionar)

    def _ao_redimensionar(self, _evento: tk.Event) -> None:
        """Reaproveita o último quadro quando o tamanho do canvas muda."""
        if self._ultimo_quadro is None:
            return
        with self._trava:
            self._quadro_pendente = self._ultimo_quadro

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
        self._ultimo_quadro = quadro

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
        self._ultimo_quadro = None
        with self._trava:
            self._quadro_pendente = None
        self.canvas.itemconfigure(self._texto_id, state="normal", text=mensagem)


class BarraControleAudio(ttk.Frame):
    """Barra com os botões de microfone e de som, no estilo do Discord.

    Os dois controles são independentes e possuem estado visual explícito:

    * **Microfone** - deixa de enviar o próprio áudio (mudo).
    * **Som** - deixa de reproduzir o áudio recebido (desativar som).

    Quando o áudio não está disponível na máquina, os botões aparecem
    desabilitados com o motivo em um rótulo ao lado, em vez de simplesmente
    não funcionarem.

    Args:
        mestre: widget pai.
        paleta: cores do tema em uso.
        ao_alternar_microfone: função chamada ao clicar no microfone; deve
            devolver o novo estado (``True`` = ativo).
        ao_alternar_som: idem para o som.
        disponivel: se o áudio existe nesta máquina.
        motivo_indisponivel: texto exibido quando ``disponivel`` é ``False``.
    """

    #: Rótulos dos botões. Apenas caracteres com boa renderização no tkinter.
    ROTULO_MICROFONE_ATIVO = "Microfone: ligado"
    ROTULO_MICROFONE_MUDO = "Microfone: MUDO"
    ROTULO_SOM_ATIVO = "Som: ligado"
    ROTULO_SOM_MUDO = "Som: DESLIGADO"

    def __init__(
        self,
        mestre: tk.Misc,
        paleta: dict[str, str],
        ao_alternar_microfone: Callable[[], bool],
        ao_alternar_som: Callable[[], bool],
        disponivel: bool = True,
        motivo_indisponivel: str = "",
    ) -> None:
        super().__init__(mestre, style="TFrame")
        self._paleta = paleta
        self._ao_alternar_microfone = ao_alternar_microfone
        self._ao_alternar_som = ao_alternar_som
        self._microfone_ativo = True
        self._som_ativo = True

        self.botao_microfone = ttk.Button(
            self, text=self.ROTULO_MICROFONE_ATIVO, command=self.alternar_microfone
        )
        self.botao_microfone.grid(row=0, column=0, sticky="w")

        self.botao_som = ttk.Button(
            self, text=self.ROTULO_SOM_ATIVO, command=self.alternar_som
        )
        self.botao_som.grid(row=0, column=1, sticky="w", padx=(8, 0))

        self._var_estado_remoto = tk.StringVar(value="")
        self.rotulo_estado = ttk.Label(
            self, textvariable=self._var_estado_remoto, style="Secundario.TLabel"
        )
        self.rotulo_estado.grid(row=0, column=2, sticky="w", padx=(12, 0))

        self.columnconfigure(2, weight=1)

        if not disponivel:
            self.definir_indisponivel(motivo_indisponivel or "áudio indisponível")

    # -- Estado -------------------------------------------------------------

    def definir_indisponivel(self, motivo: str) -> None:
        """Desabilita os controles e explica o motivo ao usuário."""
        self.botao_microfone.configure(state="disabled")
        self.botao_som.configure(state="disabled")
        self._var_estado_remoto.set(motivo)

    def definir_habilitado(self, habilitado: bool) -> None:
        """Habilita ou desabilita os dois botões."""
        estado = "normal" if habilitado else "disabled"
        self.botao_microfone.configure(state=estado)
        self.botao_som.configure(state=estado)

    def definir_estado_remoto(self, texto: str) -> None:
        """Mostra o estado de áudio do outro participante."""
        self._var_estado_remoto.set(texto)

    def alternar_microfone(self) -> None:
        """Aciona o callback do microfone e atualiza o rótulo."""
        self._microfone_ativo = bool(self._ao_alternar_microfone())
        self.botao_microfone.configure(
            text=(
                self.ROTULO_MICROFONE_ATIVO
                if self._microfone_ativo
                else self.ROTULO_MICROFONE_MUDO
            ),
            style="TButton" if self._microfone_ativo else "Perigo.TButton",
        )

    def alternar_som(self) -> None:
        """Aciona o callback do som e atualiza o rótulo."""
        self._som_ativo = bool(self._ao_alternar_som())
        self.botao_som.configure(
            text=self.ROTULO_SOM_ATIVO if self._som_ativo else self.ROTULO_SOM_MUDO,
            style="TButton" if self._som_ativo else "Perigo.TButton",
        )

    def sincronizar(self, microfone_ativo: bool, som_ativo: bool) -> None:
        """Ajusta os rótulos a um estado conhecido, sem acionar callbacks."""
        self._microfone_ativo = microfone_ativo
        self._som_ativo = som_ativo
        self.botao_microfone.configure(
            text=(
                self.ROTULO_MICROFONE_ATIVO
                if microfone_ativo
                else self.ROTULO_MICROFONE_MUDO
            ),
            style="TButton" if microfone_ativo else "Perigo.TButton",
        )
        self.botao_som.configure(
            text=self.ROTULO_SOM_ATIVO if som_ativo else self.ROTULO_SOM_MUDO,
            style="TButton" if som_ativo else "Perigo.TButton",
        )
