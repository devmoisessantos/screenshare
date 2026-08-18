"""Janela do servidor (host) - quem compartilha a tela.

Organizada em duas colunas para acomodar a pré-visualização local:

* **Esquerda** - configurações, endereço de conexão, ações e estatísticas.
* **Direita** - prévia do que está sendo transmitido, controles de áudio
  (microfone e som) e o chat.
"""

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
from interface.componentes import (
    BarraControleAudio,
    PainelChat,
    PainelEstatisticas,
    PonteInterface,
    VisualizadorVideo,
)
from interface.janela_diagnostico import JanelaDiagnostico
from interface.tema import aplicar_tema
from midia.captura_audio import AUDIO_DISPONIVEL, descrever_motor_audio
from midia.captura_tela import descrever_monitores
from midia.previa import PreVisualizadorTela
from nucleo.sessao import Retornos
from utilitarios.recursos import aplicar_icone
from utilitarios.rede import ip_local_recomendado, validar_porta
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

#: Intervalo de redesenho da prévia (aproximadamente 60 Hz).
INTERVALO_RENDERIZACAO_MS = 16


class JanelaServidor(tk.Toplevel):
    """Interface de configuração e monitoramento do compartilhamento."""

    def __init__(self, mestre: tk.Misc, configuracoes: Configuracoes) -> None:
        super().__init__(mestre)
        self.configuracoes = configuracoes
        self.title(f"{NOME_APLICACAO} {VERSAO_APLICACAO} - Compartilhando")
        self.geometry("1120x760")
        self.minsize(980, 700)

        self._paleta = aplicar_tema(self, configuracoes.interface.tema)
        aplicar_icone(self)
        self._ponte = PonteInterface(self)
        self._servidor: ServidorCompartilhamento | None = None
        self._previa: PreVisualizadorTela | None = None
        self._renderizacao_agendada: str | None = None

        self._construir_interface()
        self._registrar_atalhos()
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    # -- Construção da interface -------------------------------------------

    def _construir_interface(self) -> None:
        """Monta as duas colunas da janela."""
        self.columnconfigure(0, weight=0, minsize=520)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        coluna_esquerda = ttk.Frame(self)
        coluna_esquerda.grid(row=0, column=0, sticky="nsew")
        coluna_esquerda.columnconfigure(0, weight=1)
        coluna_esquerda.rowconfigure(3, weight=1)

        coluna_direita = ttk.Frame(self)
        coluna_direita.grid(row=0, column=1, sticky="nsew")
        coluna_direita.columnconfigure(0, weight=1)
        coluna_direita.rowconfigure(1, weight=3)
        coluna_direita.rowconfigure(3, weight=2)

        self._construir_cabecalho(coluna_esquerda)
        self._construir_opcoes(coluna_esquerda)
        self._construir_acoes(coluna_esquerda)
        self._construir_ajuda(coluna_esquerda)
        self._construir_estatisticas(coluna_esquerda)
        self._construir_previa(coluna_direita)
        self._construir_chat(coluna_direita)

    def _construir_cabecalho(self, mestre: ttk.Frame) -> None:
        """Título e linha de status."""
        cabecalho = ttk.Frame(mestre, padding=(16, 14, 16, 6))
        cabecalho.grid(row=0, column=0, sticky="ew")
        cabecalho.columnconfigure(0, weight=1)
        ttk.Label(cabecalho, text="Compartilhar minha tela", style="Titulo.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self._var_status = tk.StringVar(value="Pronto para iniciar")
        ttk.Label(
            cabecalho,
            textvariable=self._var_status,
            style="Secundario.TLabel",
            wraplength=470,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

    def _construir_opcoes(self, mestre: ttk.Frame) -> None:
        """Painel de configurações da transmissão."""
        opcoes = ttk.Labelframe(mestre, text=" Configurações ", padding=12)
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

        ttk.Label(
            opcoes,
            text=descrever_motor_audio(),
            style="Secundario.TLabel",
            wraplength=460,
            justify="left",
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _construir_acoes(self, mestre: ttk.Frame) -> None:
        """Endereço publicado, botões de iniciar/parar e diagnóstico."""
        acoes = ttk.Frame(mestre, padding=(16, 6))
        acoes.grid(row=2, column=0, sticky="ew")
        acoes.columnconfigure(1, weight=1)

        self._var_endereco = tk.StringVar(
            value=f"{ip_local_recomendado()}:{self.configuracoes.rede.porta}"
        )
        ttk.Label(acoes, text="Endereço:").grid(row=0, column=0, sticky="w")
        ttk.Label(
            acoes, textvariable=self._var_endereco, style="Secundario.TLabel"
        ).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Button(acoes, text="Copiar", command=self._copiar_endereco).grid(
            row=0, column=2, padx=(8, 0)
        )

        ttk.Label(
            acoes,
            text=(
                "Se o espectador receber tempo esgotado, abra o diagnóstico "
                "e libere a porta no firewall."
            ),
            style="Secundario.TLabel",
            wraplength=470,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        self._botao_iniciar = ttk.Button(
            acoes,
            text="Iniciar compartilhamento",
            style="Destaque.TButton",
            command=self._alternar_compartilhamento,
        )
        self._botao_iniciar.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

        ttk.Button(acoes, text="Diagnóstico", command=self._abrir_diagnostico).grid(
            row=2, column=2, sticky="e", pady=(10, 0)
        )

    def _construir_ajuda(self, mestre: ttk.Frame) -> None:
        """Passo a passo e atalhos, para dispensar consulta à documentação."""
        ajuda = ttk.Labelframe(mestre, text=" Como o espectador se conecta ", padding=12)
        ajuda.grid(row=3, column=0, sticky="new", padx=16, pady=6)
        ajuda.columnconfigure(0, weight=1)

        passos = (
            "REDE LOCAL\n"
            '1. Clique em "Iniciar compartilhamento".\n'
            "2. Copie o endereço e envie ao espectador.\n"
            '3. Na 1ª vez abra "Diagnóstico" e libere a porta no firewall.\n'
            "4. O espectador cola o endereço e conecta.\n\n"
            "ENTRE CIDADES / ESTADOS / PAÍSES (recomendado)\n"
            "Use Tailscale ou ZeroTier nos dois PCs (mesma conta):\n"
            "  → https://tailscale.com   ou   https://zerotier.com\n"
            "Depois use o IP da VPN (ex.: 100.x.x.x) no lugar do IP local.\n"
            "Assim não precisa abrir porta no roteador e o timed out some.\n\n"
            "WebRTC (modo internet nativo) está em desenvolvimento.\n\n"
            "Atalhos: Ctrl+S inicia/para · Ctrl+M microfone · "
            "Ctrl+D som · Ctrl+Q sair"
        )
        ttk.Label(
            ajuda,
            text=passos,
            style="Secundario.TLabel",
            justify="left",
            wraplength=460,
        ).grid(row=0, column=0, sticky="w")

    def _construir_estatisticas(self, mestre: ttk.Frame) -> None:
        """Painel inferior com as métricas da sessão."""
        self._estatisticas = PainelEstatisticas(mestre, self._paleta)
        self._estatisticas.grid(row=4, column=0, sticky="ew", padx=16, pady=(6, 14))
        self._estatisticas.definir_texto("Compartilhamento inativo")

    def _construir_previa(self, mestre: ttk.Frame) -> None:
        """Prévia local da transmissão e controles de áudio."""
        ttk.Label(
            mestre,
            text="Prévia da minha transmissão",
            style="Titulo.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))

        self._visualizador = VisualizadorVideo(mestre, self._paleta)
        self._visualizador.grid(row=1, column=0, sticky="nsew", padx=16)
        self._visualizador.limpar("A prévia aparece ao iniciar o compartilhamento.")

        self._controles_audio = BarraControleAudio(
            mestre,
            self._paleta,
            ao_alternar_microfone=self._alternar_microfone,
            ao_alternar_som=self._alternar_som,
            disponivel=AUDIO_DISPONIVEL,
            motivo_indisponivel=descrever_motor_audio(),
        )
        self._controles_audio.grid(row=2, column=0, sticky="ew", padx=16, pady=(10, 4))
        if AUDIO_DISPONIVEL:
            self._controles_audio.definir_habilitado(False)

    def _construir_chat(self, mestre: ttk.Frame) -> None:
        """Painel de chat com o espectador."""
        area_chat = ttk.Frame(mestre, padding=(16, 6, 16, 14))
        area_chat.grid(row=3, column=0, sticky="nsew")
        area_chat.columnconfigure(0, weight=1)
        area_chat.rowconfigure(0, weight=1)
        self._chat = PainelChat(area_chat, self._paleta, self._enviar_chat)
        self._chat.grid(row=0, column=0, sticky="nsew")
        self._chat.definir_habilitado(False)

    def _registrar_atalhos(self) -> None:
        """Vincula os atalhos de teclado da janela."""
        self.bind("<Control-q>", lambda _e: self._ao_fechar())
        self.bind("<Control-m>", lambda _e: self._controles_audio.alternar_microfone())
        self.bind("<Control-d>", lambda _e: self._controles_audio.alternar_som())
        self.bind("<Control-s>", lambda _e: self._alternar_compartilhamento())

    # -- Ações da interface -------------------------------------------------

    def _copiar_endereco(self) -> None:
        """Copia o convite completo (endereço + instruções) para a área de transferência."""
        from utilitarios.convite import criar_convite

        texto = self._var_endereco.get().strip()
        endereco, _, porta_txt = texto.partition(":")
        try:
            porta = int(porta_txt) if porta_txt.isdigit() else self.configuracoes.rede.porta
        except ValueError:
            porta = self.configuracoes.rede.porta
        convite = criar_convite(
            endereco=endereco or texto,
            porta=porta,
            senha=self.configuracoes.rede.senha,
        )
        mensagem = convite.para_mensagem()
        self.clipboard_clear()
        self.clipboard_append(mensagem)
        self._chat.adicionar_sistema(
            "Convite completo copiado (endereço + instruções). "
            "Cole no WhatsApp/Discord e envie."
        )

    def _abrir_diagnostico(self) -> None:
        """Abre a janela de diagnóstico de rede."""
        JanelaDiagnostico(self, self.configuracoes, self._var_endereco.get())

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
        """Cria o servidor, inicia a prévia e começa a aguardar o espectador."""
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
        self._iniciar_previa()

    def _parar_compartilhamento(self) -> None:
        """Encerra o servidor, para a prévia e restaura o estado inicial."""
        if self._servidor is not None:
            self._servidor.parar()
            self._servidor = None
        self._parar_previa()
        self._botao_iniciar.configure(
            text="Iniciar compartilhamento", style="Destaque.TButton"
        )
        if AUDIO_DISPONIVEL:
            self._controles_audio.definir_habilitado(False)
            self._controles_audio.definir_estado_remoto("")
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

    # -- Pré-visualização ---------------------------------------------------

    def _iniciar_previa(self) -> None:
        """Liga a captura da prévia e o laço de redesenho."""
        if self._previa is not None:
            return
        self._previa = PreVisualizadorTela(
            self.configuracoes.video,
            ao_quadro=self._visualizador.definir_quadro,
            fps=self.configuracoes.video.fps_previa,
            ao_erro=lambda mensagem: self._ponte.agendar(
                self._chat.adicionar_sistema, mensagem
            ),
        )
        self._previa.iniciar()
        self._agendar_renderizacao()

    def _parar_previa(self) -> None:
        """Desliga a captura da prévia e limpa o visualizador."""
        if self._renderizacao_agendada is not None:
            try:
                self.after_cancel(self._renderizacao_agendada)
            except tk.TclError:  # pragma: no cover - janela em destruição
                pass
            self._renderizacao_agendada = None
        if self._previa is not None:
            self._previa.parar()
            self._previa = None
        self._visualizador.limpar("A prévia aparece ao iniciar o compartilhamento.")

    def _agendar_renderizacao(self) -> None:
        """Redesenha a prévia periodicamente na thread da interface."""
        if self._previa is None:
            return
        self._visualizador.renderizar()
        self._renderizacao_agendada = self.after(
            INTERVALO_RENDERIZACAO_MS, self._agendar_renderizacao
        )

    # -- Controles de áudio -------------------------------------------------

    def _alternar_microfone(self) -> bool:
        """Ativa/desativa o envio do microfone. Devolve o novo estado."""
        if self._servidor is None or self._servidor.sessao is None:
            return True
        ativo = self._servidor.sessao.alternar_microfone()
        self._chat.adicionar_sistema(
            "Microfone ativado." if ativo else "Microfone silenciado."
        )
        return ativo

    def _alternar_som(self) -> bool:
        """Ativa/desativa a reprodução do áudio recebido."""
        if self._servidor is None or self._servidor.sessao is None:
            return True
        ativo = self._servidor.sessao.alternar_som()
        self._chat.adicionar_sistema(
            "Som ativado." if ativo else "Som desativado (nada será reproduzido)."
        )
        return ativo

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
        if AUDIO_DISPONIVEL:
            self._controles_audio.definir_habilitado(True)
            sessao = self._servidor.sessao if self._servidor else None
            if sessao is not None:
                self._controles_audio.sincronizar(
                    sessao.microfone_ativo, sessao.som_ativo
                )
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
            apelido = dados.get("apelido", "Espectador")
            ativo = bool(dados["microfone"])
            self._chat.adicionar_sistema(
                f"{apelido} {'ativou' if ativo else 'silenciou'} o microfone."
            )
            self._controles_audio.definir_estado_remoto(
                f"{apelido}: microfone {'ligado' if ativo else 'mudo'}"
            )

    def _ao_encerrar(self, motivo: str) -> None:
        """Reage ao encerramento da sessão de mídia."""
        self._chat.definir_habilitado(False)
        if AUDIO_DISPONIVEL:
            self._controles_audio.definir_habilitado(False)
            self._controles_audio.definir_estado_remoto("")
        self._chat.adicionar_sistema(motivo)
        self._estatisticas.definir_texto("Aguardando espectador...")

    # -- Encerramento -------------------------------------------------------

    def _ao_fechar(self) -> None:
        """Encerra tudo e fecha a janela."""
        self._parar_previa()
        if self._servidor is not None:
            self._servidor.parar()
            self._servidor = None
        self._ponte.encerrar()
        self.destroy()
