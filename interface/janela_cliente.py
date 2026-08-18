"""Janela do cliente (espectador) - quem assiste à tela compartilhada."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from aplicacao.cliente import ClienteVisualizador, ErroCliente
from configuracao.configuracoes import (
    NOME_APLICACAO,
    VERSAO_APLICACAO,
    Configuracoes,
)
from interface.componentes import (
    PainelChat,
    PainelEstatisticas,
    PonteInterface,
    VisualizadorVideo,
)
from interface.tema import aplicar_tema
from midia.captura_audio import AUDIO_DISPONIVEL
from midia.compressao import ErroCompressao, bgr_para_rgb, descomprimir_jpeg
from nucleo.sessao import Retornos
from utilitarios.recursos import aplicar_icone
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

INTERVALO_RENDERIZACAO_MS = 16  # ~60 quadros por segundo na tela


class JanelaCliente(tk.Toplevel):
    """Interface de conexão, visualização de vídeo e chat do espectador."""

    def __init__(self, mestre: tk.Misc, configuracoes: Configuracoes) -> None:
        super().__init__(mestre)
        self.configuracoes = configuracoes
        self.title(f"{NOME_APLICACAO} {VERSAO_APLICACAO} - Assistindo")
        self.geometry("1180x720")
        self.minsize(900, 600)

        self._paleta = aplicar_tema(self, configuracoes.interface.tema)
        aplicar_icone(self)
        self._ponte = PonteInterface(self)
        self._cliente: ClienteVisualizador | None = None

        self._construir_interface()
        self._registrar_atalhos()
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self.after(INTERVALO_RENDERIZACAO_MS, self._laco_renderizacao)

    # -- Construção da interface -------------------------------------------

    def _construir_interface(self) -> None:
        """Monta todos os widgets da janela."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Barra de conexão --------------------------------------------------
        barra = ttk.Frame(self, padding=(16, 12, 16, 6))
        barra.grid(row=0, column=0, sticky="ew")
        barra.columnconfigure(7, weight=1)

        self._var_endereco = tk.StringVar()
        self._var_porta = tk.StringVar(value=str(self.configuracoes.rede.porta))
        self._var_senha = tk.StringVar(value=self.configuracoes.rede.senha)
        self._var_apelido = tk.StringVar(value=self.configuracoes.interface.apelido)

        ttk.Label(barra, text="IP do host").grid(row=0, column=0, sticky="w")
        self._campo_endereco = ttk.Entry(barra, textvariable=self._var_endereco, width=18)
        self._campo_endereco.grid(row=0, column=1, padx=(6, 14))

        ttk.Label(barra, text="Porta").grid(row=0, column=2, sticky="w")
        self._campo_porta = ttk.Entry(barra, textvariable=self._var_porta, width=8)
        self._campo_porta.grid(row=0, column=3, padx=(6, 14))

        ttk.Label(barra, text="Senha").grid(row=0, column=4, sticky="w")
        self._campo_senha = ttk.Entry(barra, textvariable=self._var_senha, show="*", width=14)
        self._campo_senha.grid(row=0, column=5, padx=(6, 14))

        ttk.Label(barra, text="Apelido").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._campo_apelido = ttk.Entry(barra, textvariable=self._var_apelido, width=18)
        self._campo_apelido.grid(row=1, column=1, padx=(6, 14), pady=(8, 0))

        self._botao_conectar = ttk.Button(
            barra, text="Conectar", style="Destaque.TButton", command=self._alternar_conexao
        )
        self._botao_conectar.grid(row=0, column=6, rowspan=1, padx=(0, 8))

        self._botao_microfone = ttk.Button(
            barra, text="Mutar microfone", command=self._alternar_microfone, state="disabled"
        )
        self._botao_microfone.grid(row=1, column=6, pady=(8, 0))

        self._var_status = tk.StringVar(value="Desconectado")
        ttk.Label(barra, textvariable=self._var_status, style="Secundario.TLabel").grid(
            row=0, column=7, rowspan=2, sticky="e"
        )

        ttk.Separator(self, orient="horizontal").grid(row=1, column=0, sticky="ew", padx=16)

        # Vídeo + chat ------------------------------------------------------
        corpo = ttk.Frame(self, padding=(16, 10))
        corpo.grid(row=2, column=0, sticky="nsew")
        corpo.rowconfigure(0, weight=1)
        corpo.columnconfigure(0, weight=1)
        corpo.columnconfigure(1, minsize=340)

        self._visualizador = VisualizadorVideo(corpo, self._paleta)
        self._visualizador.grid(row=0, column=0, sticky="nsew")
        self._visualizador.limpar("Conecte-se a um host para ver a tela compartilhada.")

        self._chat = PainelChat(corpo, self._paleta, self._enviar_chat)
        self._chat.grid(row=0, column=1, sticky="nsew", padx=(14, 0))
        self._chat.definir_habilitado(False)

        # Estatísticas ------------------------------------------------------
        self._estatisticas = PainelEstatisticas(self, self._paleta)
        self._estatisticas.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))
        self._estatisticas.definir_texto("Sem conexão")

    def _registrar_atalhos(self) -> None:
        """Vincula os atalhos de teclado da janela."""
        self.bind("<Control-q>", lambda _e: self._ao_fechar())
        self.bind("<Control-m>", lambda _e: self._alternar_microfone())
        self.bind("<Control-s>", lambda _e: self._alternar_conexao())

    # -- Conexão ------------------------------------------------------------

    def _alternar_conexao(self) -> None:
        """Conecta ou desconecta conforme o estado atual."""
        if self._cliente is not None and self._cliente.conectado:
            self._desconectar()
        else:
            self._conectar()

    def _conectar(self) -> None:
        """Coleta os dados do formulário e conecta em uma thread separada."""
        endereco = self._var_endereco.get().strip()
        if not endereco:
            messagebox.showwarning(
                "Endereço obrigatório", "Informe o IP do host.", parent=self
            )
            return

        # Aceita o formato "ip:porta" colado diretamente do host.
        if ":" in endereco:
            endereco, _, porta_colada = endereco.partition(":")
            if porta_colada.strip().isdigit():
                self._var_porta.set(porta_colada.strip())

        self.configuracoes.interface.apelido = self._var_apelido.get().strip() or "Espectador"
        self.configuracoes.rede.senha = self._var_senha.get()
        try:
            self.configuracoes.salvar()
        except OSError:  # pragma: no cover
            pass

        retornos = Retornos(
            ao_video=self._processar_video,
            ao_chat=lambda dados: self._ponte.agendar(self._exibir_chat, dados),
            ao_estado=lambda dados: self._ponte.agendar(self._exibir_estado, dados),
            ao_estatisticas=lambda estatisticas: self._ponte.agendar(
                self._estatisticas.atualizar, estatisticas
            ),
            ao_encerrar=lambda motivo: self._ponte.agendar(self._ao_encerrar, motivo),
            ao_erro=lambda mensagem: self._ponte.agendar(
                self._chat.adicionar_sistema, mensagem
            ),
        )
        self._cliente = ClienteVisualizador(
            configuracoes=self.configuracoes,
            retornos=retornos,
            ao_status=lambda texto: self._ponte.agendar(self._var_status.set, texto),
            ao_conectar=lambda info: self._ponte.agendar(self._ao_conectar, info),
        )

        self._botao_conectar.configure(state="disabled", text="Conectando...")
        threading.Thread(
            target=self._conectar_em_segundo_plano,
            args=(endereco, self._var_porta.get()),
            name="conexao-cliente",
            daemon=True,
        ).start()

    def _conectar_em_segundo_plano(self, endereco: str, porta: str) -> None:
        """Executa a conexão fora da thread da interface."""
        assert self._cliente is not None
        try:
            self._cliente.conectar(endereco, porta)
        except ErroCliente as erro:
            self._cliente = None
            self._ponte.agendar(self._falha_conexao, str(erro))

    def _falha_conexao(self, mensagem: str) -> None:
        """Mostra o erro de conexão e restaura os botões."""
        self._botao_conectar.configure(state="normal", text="Conectar")
        self._var_status.set("Falha na conexão")
        self._chat.adicionar_sistema(mensagem)
        messagebox.showerror("Não foi possível conectar", mensagem, parent=self)

    def _desconectar(self) -> None:
        """Encerra a sessão com o host."""
        if self._cliente is not None:
            self._cliente.desconectar()
            self._cliente = None
        self._restaurar_estado_desconectado()

    def _restaurar_estado_desconectado(self) -> None:
        """Devolve a interface ao estado inicial."""
        self._botao_conectar.configure(state="normal", text="Conectar", style="Destaque.TButton")
        self._botao_microfone.configure(state="disabled", text="Mutar microfone")
        self._chat.definir_habilitado(False)
        self._visualizador.limpar("Sessão encerrada.")
        self._estatisticas.definir_texto("Sem conexão")

    # -- Vídeo --------------------------------------------------------------

    def _processar_video(self, dados: bytes) -> None:
        """Decodifica o quadro recebido (thread de rede) e guarda para exibição."""
        try:
            quadro = descomprimir_jpeg(dados)
        except ErroCompressao as erro:
            _registrador.debug("Quadro descartado: %s", erro)
            return
        self._visualizador.definir_quadro(bgr_para_rgb(quadro))

    def _laco_renderizacao(self) -> None:
        """Desenha periodicamente o quadro mais recente disponível."""
        try:
            self._visualizador.renderizar()
        except tk.TclError:  # pragma: no cover - janela destruída
            return
        self.after(INTERVALO_RENDERIZACAO_MS, self._laco_renderizacao)

    # -- Chat e estado ------------------------------------------------------

    def _enviar_chat(self, texto: str) -> None:
        """Envia uma mensagem de chat ao host."""
        if self._cliente is None or self._cliente.sessao is None:
            self._chat.adicionar_sistema("Você não está conectado.")
            return
        if self._cliente.sessao.enviar_chat(texto):
            self._chat.adicionar_mensagem(
                self.configuracoes.interface.apelido, texto, proprio=True
            )

    def _alternar_microfone(self) -> None:
        """Ativa/desativa o envio do microfone durante a sessão."""
        if self._cliente is None or self._cliente.sessao is None:
            return
        ativo = self._cliente.sessao.alternar_microfone()
        self._botao_microfone.configure(
            text="Mutar microfone" if ativo else "Ativar microfone"
        )
        self._chat.adicionar_sistema(
            "Microfone ativado." if ativo else "Microfone silenciado."
        )

    def _exibir_chat(self, dados: dict) -> None:
        """Exibe uma mensagem recebida do host."""
        self._chat.adicionar_mensagem(
            dados.get("autor", "Host"),
            dados.get("conteudo", ""),
            dados.get("horario", ""),
        )

    def _exibir_estado(self, dados: dict) -> None:
        """Exibe mudanças de estado informadas pelo host."""
        if "microfone" in dados:
            estado = "ativou" if dados["microfone"] else "silenciou"
            self._chat.adicionar_sistema(
                f"{dados.get('apelido', 'Host')} {estado} o microfone."
            )

    # -- Retornos das threads ----------------------------------------------

    def _ao_conectar(self, informacoes: dict) -> None:
        """Atualiza a interface após um handshake bem-sucedido."""
        self._botao_conectar.configure(
            state="normal", text="Desconectar", style="Perigo.TButton"
        )
        if AUDIO_DISPONIVEL and self.configuracoes.audio.ativo:
            self._botao_microfone.configure(state="normal")
        self._chat.definir_habilitado(True)
        self._chat.adicionar_sistema(
            f"Conectado a {informacoes.get('apelido', 'host')} - "
            f"{informacoes.get('resolucao', '?')} @ {informacoes.get('fps', '?')} fps."
        )
        self._visualizador.limpar("Aguardando o primeiro quadro...")

    def _ao_encerrar(self, motivo: str) -> None:
        """Reage ao encerramento da sessão."""
        self._chat.adicionar_sistema(motivo)
        if self._cliente is None or not self._cliente.conectado:
            self._restaurar_estado_desconectado()
            self._var_status.set(motivo)

    # -- Encerramento -------------------------------------------------------

    def _ao_fechar(self) -> None:
        """Encerra a sessão e fecha a janela."""
        if self._cliente is not None:
            self._cliente.desconectar()
            self._cliente = None
        self._ponte.encerrar()
        self.destroy()
