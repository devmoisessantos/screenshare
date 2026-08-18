"""Janela do servidor (host) - quem compartilha a tela."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from aplicacao.servidor import ErroServidor, ServidorCompartilhamento
from configuracao.configuracoes import (
    NOME_APLICACAO,
    RESOLUCOES,
    TAXAS_QUADROS,
    VERSAO_APLICACAO,
    Configuracoes,
)
from interface.componentes import PainelChat, PainelEstatisticas, PonteInterface
from interface.tema import aplicar_tema
from midia.captura_audio import AUDIO_DISPONIVEL
from midia.captura_tela import descrever_monitores
from nucleo.sessao import Retornos
from utilitarios.recursos import aplicar_icone
from utilitarios.rede import obter_ip_local, validar_porta
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)


class JanelaServidor(tk.Toplevel):
    """Interface de configuração e monitoramento do compartilhamento."""

    def __init__(self, mestre: tk.Misc, configuracoes: Configuracoes) -> None:
        super().__init__(mestre)
        self.configuracoes = configuracoes
        self.title(f"{NOME_APLICACAO} {VERSAO_APLICACAO} - Compartilhando")
        self.geometry("620x680")
        self.minsize(560, 620)

        self._paleta = aplicar_tema(self, configuracoes.interface.tema)
        aplicar_icone(self)
        self._ponte = PonteInterface(self)
        self._servidor: ServidorCompartilhamento | None = None

        self._construir_interface()
        self._registrar_atalhos()
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    # -- Construção da interface -------------------------------------------

    def _construir_interface(self) -> None:
        """Monta todos os widgets da janela."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        # Cabeçalho -------------------------------------------------------
        cabecalho = ttk.Frame(self, padding=(16, 14, 16, 6))
        cabecalho.grid(row=0, column=0, sticky="ew")
        cabecalho.columnconfigure(0, weight=1)
        ttk.Label(cabecalho, text="Compartilhar minha tela", style="Titulo.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self._var_status = tk.StringVar(value="Pronto para iniciar")
        ttk.Label(
            cabecalho, textvariable=self._var_status, style="Secundario.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        # Configurações ---------------------------------------------------
        opcoes = ttk.Labelframe(self, text=" Configurações ", padding=12)
        opcoes.grid(row=1, column=0, sticky="ew", padx=16, pady=6)
        for coluna in (1, 3):
            opcoes.columnconfigure(coluna, weight=1)

        self._var_apelido = tk.StringVar(value=self.configuracoes.interface.apelido)
        self._var_porta = tk.StringVar(value=str(self.configuracoes.rede.porta))
        self._var_senha = tk.StringVar(value=self.configuracoes.rede.senha)
        self._var_resolucao = tk.StringVar(value=self.configuracoes.video.resolucao)
        self._var_fps = tk.StringVar(value=str(self.configuracoes.video.fps))
        self._var_qualidade = tk.IntVar(value=self.configuracoes.video.qualidade_jpeg)
        self._var_audio = tk.BooleanVar(
            value=self.configuracoes.audio.ativo and AUDIO_DISPONIVEL
        )
        self._var_adaptativa = tk.BooleanVar(
            value=self.configuracoes.video.compressao_adaptativa
        )
        self._monitores = descrever_monitores()
        indice_monitor = min(
            self.configuracoes.video.monitor, max(0, len(self._monitores) - 1)
        )
        self._var_monitor = tk.StringVar(value=self._monitores[indice_monitor])

        ttk.Label(opcoes, text="Seu apelido").grid(row=0, column=0, sticky="w", pady=4)
        self._campo_apelido = ttk.Entry(opcoes, textvariable=self._var_apelido)
        self._campo_apelido.grid(row=0, column=1, sticky="ew", padx=(8, 16), pady=4)

        ttk.Label(opcoes, text="Porta TCP").grid(row=0, column=2, sticky="w", pady=4)
        self._campo_porta = ttk.Entry(opcoes, textvariable=self._var_porta, width=10)
        self._campo_porta.grid(row=0, column=3, sticky="ew", padx=(8, 0), pady=4)

        ttk.Label(opcoes, text="Senha (opcional)").grid(row=1, column=0, sticky="w", pady=4)
        self._campo_senha = ttk.Entry(opcoes, textvariable=self._var_senha, show="*")
        self._campo_senha.grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=4)

        ttk.Label(opcoes, text="Monitor").grid(row=1, column=2, sticky="w", pady=4)
        self._campo_monitor = ttk.Combobox(
            opcoes,
            textvariable=self._var_monitor,
            values=self._monitores,
            state="readonly",
        )
        self._campo_monitor.grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=4)

        ttk.Label(opcoes, text="Resolução").grid(row=2, column=0, sticky="w", pady=4)
        self._campo_resolucao = ttk.Combobox(
            opcoes,
            textvariable=self._var_resolucao,
            values=list(RESOLUCOES),
            state="readonly",
            width=10,
        )
        self._campo_resolucao.grid(row=2, column=1, sticky="ew", padx=(8, 16), pady=4)

        ttk.Label(opcoes, text="Quadros por segundo").grid(
            row=2, column=2, sticky="w", pady=4
        )
        self._campo_fps = ttk.Combobox(
            opcoes,
            textvariable=self._var_fps,
            values=[str(valor) for valor in TAXAS_QUADROS],
            state="readonly",
            width=10,
        )
        self._campo_fps.grid(row=2, column=3, sticky="ew", padx=(8, 0), pady=4)

        ttk.Label(opcoes, text="Qualidade JPEG").grid(row=3, column=0, sticky="w", pady=4)
        moldura_qualidade = ttk.Frame(opcoes)
        moldura_qualidade.grid(row=3, column=1, sticky="ew", padx=(8, 16), pady=4)
        moldura_qualidade.columnconfigure(0, weight=1)
        self._escala_qualidade = ttk.Scale(
            moldura_qualidade,
            from_=20,
            to=95,
            variable=self._var_qualidade,
            command=lambda _valor: self._var_rotulo_qualidade.set(
                str(self._var_qualidade.get())
            ),
        )
        self._escala_qualidade.grid(row=0, column=0, sticky="ew")
        self._var_rotulo_qualidade = tk.StringVar(value=str(self._var_qualidade.get()))
        ttk.Label(
            moldura_qualidade,
            textvariable=self._var_rotulo_qualidade,
            style="Secundario.TLabel",
            width=4,
        ).grid(row=0, column=1, padx=(6, 0))

        self._caixa_audio = ttk.Checkbutton(
            opcoes,
            text="Transmitir microfone" if AUDIO_DISPONIVEL else "Áudio indisponível",
            variable=self._var_audio,
            state="normal" if AUDIO_DISPONIVEL else "disabled",
        )
        self._caixa_audio.grid(row=3, column=2, columnspan=2, sticky="w", padx=(8, 0))

        self._caixa_adaptativa = ttk.Checkbutton(
            opcoes,
            text="Ajustar qualidade automaticamente conforme a latência",
            variable=self._var_adaptativa,
        )
        self._caixa_adaptativa.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # Endereço e ações ------------------------------------------------
        acoes = ttk.Frame(self, padding=(16, 6))
        acoes.grid(row=2, column=0, sticky="ew")
        acoes.columnconfigure(1, weight=1)

        self._var_endereco = tk.StringVar(
            value=f"{obter_ip_local()}:{self.configuracoes.rede.porta}"
        )
        ttk.Label(acoes, text="Endereço:").grid(row=0, column=0, sticky="w")
        ttk.Label(
            acoes, textvariable=self._var_endereco, style="Secundario.TLabel"
        ).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Button(acoes, text="Copiar", command=self._copiar_endereco).grid(
            row=0, column=2, padx=(8, 0)
        )

        self._botao_iniciar = ttk.Button(
            acoes,
            text="Iniciar compartilhamento",
            style="Destaque.TButton",
            command=self._alternar_compartilhamento,
        )
        self._botao_iniciar.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self._botao_microfone = ttk.Button(
            acoes, text="Mutar microfone", command=self._alternar_microfone, state="disabled"
        )
        self._botao_microfone.grid(row=1, column=2, sticky="e", pady=(10, 0))

        # Chat -------------------------------------------------------------
        area_chat = ttk.Frame(self, padding=(16, 10))
        area_chat.grid(row=3, column=0, sticky="nsew")
        area_chat.columnconfigure(0, weight=1)
        area_chat.rowconfigure(0, weight=1)
        self._chat = PainelChat(area_chat, self._paleta, self._enviar_chat)
        self._chat.grid(row=0, column=0, sticky="nsew")
        self._chat.definir_habilitado(False)

        # Estatísticas -----------------------------------------------------
        self._estatisticas = PainelEstatisticas(self, self._paleta)
        self._estatisticas.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 14))
        self._estatisticas.definir_texto("Compartilhamento inativo")

    def _registrar_atalhos(self) -> None:
        """Vincula os atalhos de teclado da janela."""
        self.bind("<Control-q>", lambda _e: self._ao_fechar())
        self.bind("<Control-m>", lambda _e: self._alternar_microfone())
        self.bind("<Control-s>", lambda _e: self._alternar_compartilhamento())

    # -- Ações da interface -------------------------------------------------

    def _copiar_endereco(self) -> None:
        """Copia o endereço de conexão para a área de transferência."""
        self.clipboard_clear()
        self.clipboard_append(self._var_endereco.get())
        self._chat.adicionar_sistema("Endereço copiado para a área de transferência.")

    def _alternar_compartilhamento(self) -> None:
        """Inicia ou para o compartilhamento conforme o estado atual."""
        if self._servidor is not None and self._servidor.em_execucao:
            self._parar_compartilhamento()
        else:
            self._iniciar_compartilhamento()

    def _coletar_configuracoes(self) -> bool:
        """Aplica os valores da interface nas configurações. ``False`` se inválido."""
        try:
            porta = validar_porta(self._var_porta.get())
        except ValueError as erro:
            messagebox.showerror("Porta inválida", str(erro), parent=self)
            return False

        interface = self.configuracoes.interface
        interface.apelido = self._var_apelido.get().strip() or "Host"

        rede = self.configuracoes.rede
        rede.porta = porta
        rede.senha = self._var_senha.get()

        video = self.configuracoes.video
        video.resolucao = self._var_resolucao.get()
        video.fps = int(self._var_fps.get())
        video.qualidade_jpeg = int(self._var_qualidade.get())
        video.compressao_adaptativa = bool(self._var_adaptativa.get())
        try:
            video.monitor = int(self._var_monitor.get().split(" - ")[0])
        except (ValueError, IndexError):
            video.monitor = 1

        self.configuracoes.audio.ativo = bool(self._var_audio.get()) and AUDIO_DISPONIVEL

        try:
            self.configuracoes.salvar()
        except OSError as erro:  # pragma: no cover
            _registrador.warning("Não foi possível salvar configurações: %s", erro)
        return True

    def _iniciar_compartilhamento(self) -> None:
        """Cria o servidor e começa a aguardar o espectador."""
        if not self._coletar_configuracoes():
            return

        retornos = Retornos(
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
        self._servidor = ServidorCompartilhamento(
            configuracoes=self.configuracoes,
            retornos=retornos,
            ao_status=lambda texto: self._ponte.agendar(self._var_status.set, texto),
            ao_conectar=lambda info: self._ponte.agendar(self._ao_conectar, info),
        )

        try:
            self._servidor.iniciar()
        except ErroServidor as erro:
            self._servidor = None
            messagebox.showerror("Falha ao iniciar", str(erro), parent=self)
            return

        self._var_endereco.set(self._servidor.endereco_publicado)
        self._botao_iniciar.configure(text="Parar compartilhamento", style="Perigo.TButton")
        self._definir_estado_configuracoes("disabled")
        self._chat.adicionar_sistema(
            "Compartilhamento iniciado. Informe o endereço "
            f"{self._servidor.endereco_publicado} ao espectador."
        )
        self._estatisticas.definir_texto("Aguardando espectador...")

    def _parar_compartilhamento(self) -> None:
        """Encerra o servidor e volta a interface ao estado inicial."""
        if self._servidor is not None:
            self._servidor.parar()
            self._servidor = None
        self._botao_iniciar.configure(
            text="Iniciar compartilhamento", style="Destaque.TButton"
        )
        self._botao_microfone.configure(state="disabled", text="Mutar microfone")
        self._definir_estado_configuracoes("normal")
        self._chat.definir_habilitado(False)
        self._var_status.set("Compartilhamento parado")
        self._estatisticas.definir_texto("Compartilhamento inativo")

    def _definir_estado_configuracoes(self, estado: str) -> None:
        """Habilita/desabilita os campos de configuração."""
        somente_leitura = "readonly" if estado == "normal" else "disabled"
        for campo in (self._campo_apelido, self._campo_porta, self._campo_senha):
            campo.configure(state=estado)
        for campo in (self._campo_monitor, self._campo_resolucao, self._campo_fps):
            campo.configure(state=somente_leitura)
        self._escala_qualidade.configure(state=estado)
        self._caixa_adaptativa.configure(state=estado)
        if AUDIO_DISPONIVEL:
            self._caixa_audio.configure(state=estado)

    def _alternar_microfone(self) -> None:
        """Ativa/desativa o envio do microfone durante a sessão."""
        if self._servidor is None or self._servidor.sessao is None:
            return
        ativo = self._servidor.sessao.alternar_microfone()
        self._botao_microfone.configure(
            text="Mutar microfone" if ativo else "Ativar microfone"
        )
        self._chat.adicionar_sistema(
            "Microfone ativado." if ativo else "Microfone silenciado."
        )

    def _enviar_chat(self, texto: str) -> None:
        """Envia uma mensagem de chat ao espectador."""
        if self._servidor is None or self._servidor.sessao is None:
            self._chat.adicionar_sistema("Nenhum espectador conectado.")
            return
        if self._servidor.sessao.enviar_chat(texto):
            self._chat.adicionar_mensagem(
                self.configuracoes.interface.apelido, texto, proprio=True
            )

    # -- Retornos das threads ----------------------------------------------

    def _ao_conectar(self, informacoes: dict) -> None:
        """Atualiza a interface quando um espectador entra."""
        self._chat.definir_habilitado(True)
        if AUDIO_DISPONIVEL and self.configuracoes.audio.ativo:
            self._botao_microfone.configure(state="normal")
        self._chat.adicionar_sistema(
            f"{informacoes.get('apelido', 'Espectador')} "
            f"({informacoes.get('ip', '?')}) entrou na sessão."
        )

    def _exibir_chat(self, dados: dict) -> None:
        """Exibe uma mensagem recebida do espectador."""
        self._chat.adicionar_mensagem(
            dados.get("autor", "Espectador"),
            dados.get("conteudo", ""),
            dados.get("horario", ""),
        )

    def _exibir_estado(self, dados: dict) -> None:
        """Exibe mudanças de estado informadas pelo espectador."""
        if "microfone" in dados:
            estado = "ativou" if dados["microfone"] else "silenciou"
            self._chat.adicionar_sistema(
                f"{dados.get('apelido', 'Espectador')} {estado} o microfone."
            )

    def _ao_encerrar(self, motivo: str) -> None:
        """Reage ao encerramento da sessão de mídia."""
        self._chat.definir_habilitado(False)
        self._botao_microfone.configure(state="disabled")
        self._chat.adicionar_sistema(motivo)
        self._estatisticas.definir_texto("Aguardando espectador...")

    # -- Encerramento -------------------------------------------------------

    def _ao_fechar(self) -> None:
        """Encerra tudo e fecha a janela."""
        if self._servidor is not None:
            self._servidor.parar()
            self._servidor = None
        self._ponte.encerrar()
        self.destroy()
