"""Janela principal do modo internet: a chamada em si.

Layout inspirado no Discord:

    +-------------------------------------------------------------+
    | cabecalho: sala, convite, estado da conexao                 |
    +-----------------------------+-------------------------------+
    | grade de video              | participantes                 |
    | (quem compartilha aparece   +-------------------------------+
    |  em destaque)               | chat com emojis               |
    +-----------------------------+-------------------------------+
    | barra: microfone, som, transmitir, gravar, clipar, sair     |
    +-------------------------------------------------------------+

Tudo que chega da rede passa pela `PonteInterface`, porque os callbacks da
`Chamada` sao executados na thread de rede e o tkinter so aceita chamadas na
thread que criou a janela.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

import numpy as np

from configuracao.configuracoes import Configuracoes
from interface.chat_rico import ChatRico
from interface.componentes import PonteInterface, VisualizadorVideo
from interface.emojis import RenderizadorEmojis
from interface.painel_participantes import PainelParticipantes
from interface.seletor_fonte import SeletorFonte
from interface.tema import FONTE_MONO, aplicar_tema
from midia import dispositivos
from midia.gravador import ConfiguracaoGravacao, GerenciadorGravacao
from nucleo.chamada import Chamada, Participante, RetornosChamada
from nucleo.convite import Convite
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

#: Intervalo de redesenho dos quadros de video, em milissegundos (~30 FPS).
INTERVALO_RENDERIZACAO = 33


def _rotulo_dispositivo(dispositivo: Any) -> str:
    """Monta um rotulo curto e legivel para um dispositivo de audio."""
    nome = " ".join(str(dispositivo.nome).split())[:34]
    return f"{nome} (padrao)" if dispositivo.padrao else nome


class CelulaVideo(ttk.Frame):
    """Um quadro de video com o nome de quem esta transmitindo."""

    def __init__(self, mestre: tk.Misc, paleta: dict[str, str], titulo: str) -> None:
        super().__init__(mestre, style="Cartao.TFrame", padding=4)
        self.visualizador = VisualizadorVideo(self, paleta)
        self.visualizador.pack(fill=tk.BOTH, expand=True)
        self._rotulo = ttk.Label(self, text=titulo, style="Cartao.TLabel")
        self._rotulo.pack(anchor="w", pady=(4, 0))

    def definir_titulo(self, titulo: str) -> None:
        """Atualiza a legenda da celula."""
        self._rotulo.configure(text=titulo)


class JanelaChamada(tk.Toplevel):
    """Janela de uma chamada em andamento."""

    def __init__(
        self,
        mestre: tk.Misc,
        configuracoes: Configuracoes,
        sala: str,
        apelido: str,
        senha: str = "",
        ao_fechar: Any = None,
    ) -> None:
        super().__init__(mestre)
        self._configuracoes = configuracoes
        self._sala = sala
        self._apelido = apelido
        self._ao_fechar = ao_fechar

        self.title(f"ScreenShare - sala {sala}")
        self.geometry("1280x780")
        self.minsize(1024, 660)
        self.paleta = aplicar_tema(self, configuracoes.interface.tema)
        self._renderizador = RenderizadorEmojis()
        self.ponte = PonteInterface(self)

        self._celulas: dict[str, CelulaVideo] = {}
        self._janela_destacada: tk.Toplevel | None = None
        self._visualizador_destacado: VisualizadorVideo | None = None
        self._id_destacado = ""
        self._tela_cheia = False
        self._encerrando = False
        self._ultimo_quadro_local: np.ndarray | None = None

        self._gravacao = GerenciadorGravacao(
            ConfiguracaoGravacao(
                pasta=Path(configuracoes.gravacao.pasta)
                if configuracoes.gravacao.pasta
                else Path.home() / "Videos" / "ScreenShare",
                taxa_bits=configuracoes.gravacao.taxa_bits,
                segundos_buffer=configuracoes.gravacao.segundos_buffer,
                fps=configuracoes.video.fps,
                fps_buffer=configuracoes.gravacao.fps_buffer,
                qualidade_buffer=configuracoes.gravacao.qualidade_buffer,
            ),
            ao_evento=lambda texto: self.ponte.agendar(self._chat.adicionar_sistema, texto),
            ao_erro=lambda texto: self.ponte.agendar(self._chat.adicionar_erro, texto),
        )

        self._montar()
        self._registrar_atalhos()

        self.chamada = Chamada(
            configuracoes,
            RetornosChamada(
                ao_entrar=lambda sala, identificador: self.ponte.agendar(
                    self._ao_entrar, sala, identificador
                ),
                ao_participantes=lambda lista: self.ponte.agendar(self._ao_participantes, lista),
                ao_chat=lambda autor, texto: self.ponte.agendar(
                    self._chat.adicionar_mensagem, autor, texto, False
                ),
                ao_sistema=lambda texto: self.ponte.agendar(self._chat.adicionar_sistema, texto),
                ao_erro=lambda texto: self.ponte.agendar(self._ao_erro, texto),
                ao_quadro_remoto=lambda origem, quadro: self.ponte.agendar(
                    self._ao_quadro_remoto, origem, quadro
                ),
                ao_quadro_local=lambda quadro: self.ponte.agendar(self._ao_quadro_local, quadro),
                ao_estatisticas=lambda dados: self.ponte.agendar(self._ao_estatisticas, dados),
                ao_encerrar=lambda motivo: self.ponte.agendar(self._ao_encerrar, motivo),
            ),
        )

        self.protocol("WM_DELETE_WINDOW", self.encerrar)
        self._renderizar()
        self.chamada.entrar(sala, apelido, senha)

    # -- Montagem -----------------------------------------------------------

    def _montar(self) -> None:
        """Cria cabecalho, area central, painel lateral e barra de controles."""
        self._montar_cabecalho()

        corpo = ttk.Frame(self, padding=(10, 6))
        corpo.pack(fill=tk.BOTH, expand=True)
        corpo.columnconfigure(0, weight=3)
        corpo.columnconfigure(1, weight=1, minsize=300)
        corpo.rowconfigure(0, weight=1)

        self._grade = ttk.Frame(corpo)
        self._grade.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        lateral = ttk.Frame(corpo)
        lateral.grid(row=0, column=1, sticky="nsew")
        lateral.rowconfigure(0, weight=0)
        lateral.rowconfigure(1, weight=1)
        lateral.columnconfigure(0, weight=1)

        self._painel_participantes = PainelParticipantes(lateral, self.paleta)
        self._painel_participantes.grid(row=0, column=0, sticky="ew")

        self._chat = ChatRico(lateral, self.paleta, self._enviar_chat, self._renderizador)
        self._chat.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        self._montar_barra()
        self._montar_celula_local()

    def _montar_cabecalho(self) -> None:
        """Cabecalho com o codigo da sala, convite e estado."""
        cabecalho = ttk.Frame(self, style="Barra.TFrame", padding=(14, 10))
        cabecalho.pack(fill=tk.X)

        esquerda = ttk.Frame(cabecalho, style="Barra.TFrame")
        esquerda.pack(side=tk.LEFT)
        ttk.Label(esquerda, text=f"Sala {self._sala}", style="Painel.TLabel").pack(anchor="w")
        self._rotulo_estado = ttk.Label(
            esquerda, text="Conectando ao servidor de sinalizacao...", style="Status.TLabel"
        )
        self._rotulo_estado.pack(anchor="w")

        direita = ttk.Frame(cabecalho, style="Barra.TFrame")
        direita.pack(side=tk.RIGHT)
        ttk.Button(direita, text="Copiar convite", command=self.copiar_convite).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(direita, text="Ver convite", command=self.mostrar_convite).pack(side=tk.LEFT)

    def _montar_barra(self) -> None:
        """Barra inferior com os controles da chamada."""
        barra = ttk.Frame(self, style="Barra.TFrame", padding=(14, 10))
        barra.pack(fill=tk.X)

        self._botao_microfone = ttk.Button(
            barra, text="Mutar microfone", style="Barra.TButton", command=self.alternar_microfone
        )
        self._botao_microfone.pack(side=tk.LEFT)

        self._botao_som = ttk.Button(
            barra, text="Desligar som", style="Barra.TButton", command=self.alternar_som
        )
        self._botao_som.pack(side=tk.LEFT, padx=(8, 0))

        self._botao_transmitir = ttk.Button(
            barra, text="Transmitir tela", style="Destaque.TButton", command=self.escolher_fonte
        )
        self._botao_transmitir.pack(side=tk.LEFT, padx=(16, 0))

        self._botao_gravar = ttk.Button(
            barra, text="Gravar (Ctrl+R)", style="Barra.TButton", command=self.alternar_gravacao
        )
        self._botao_gravar.pack(side=tk.LEFT, padx=(8, 0))

        self._botao_clipe = ttk.Button(
            barra, text="Clipar (Ctrl+G)", style="Barra.TButton", command=self.salvar_clipe
        )
        self._botao_clipe.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(
            barra, text="Tela cheia (F11)", style="Barra.TButton", command=self.alternar_tela_cheia
        ).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(barra, text="Sair da chamada", style="Perigo.TButton", command=self.encerrar).pack(
            side=tk.RIGHT
        )

        self._rotulo_metricas = ttk.Label(barra, text="", style="Status.TLabel", font=FONTE_MONO)
        self._rotulo_metricas.pack(side=tk.RIGHT, padx=(0, 16))

        self._montar_audio(barra)

    def _montar_audio(self, mestre: tk.Misc) -> None:
        """Seletores de dispositivo de entrada e saida, com volume."""
        painel = ttk.Frame(mestre, style="Barra.TFrame")
        painel.pack(side=tk.RIGHT, padx=(0, 16))

        entradas = dispositivos.listar_entradas()
        saidas = dispositivos.listar_saidas()

        if not entradas and not saidas:
            ttk.Label(
                painel,
                text="Sem audio: instale o PortAudio",
                style="Status.TLabel",
                wraplength=150,
                justify="left",
            ).pack()
            return

        self._mapa_entradas = {_rotulo_dispositivo(item): item.indice for item in entradas}
        self._mapa_saidas = {_rotulo_dispositivo(item): item.indice for item in saidas}

        linha = ttk.Frame(painel, style="Barra.TFrame")
        linha.pack(anchor="e")
        ttk.Label(linha, text="Microfone", style="Status.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        self._combo_entrada = ttk.Combobox(
            linha, values=list(self._mapa_entradas), state="readonly", width=22
        )
        self._combo_entrada.pack(side=tk.LEFT)
        if entradas:
            self._combo_entrada.current(0)
        self._combo_entrada.bind("<<ComboboxSelected>>", self._trocar_entrada)

        linha2 = ttk.Frame(painel, style="Barra.TFrame")
        linha2.pack(anchor="e", pady=(2, 0))
        ttk.Label(linha2, text="Volume", style="Status.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        self._volume = tk.DoubleVar(value=self._configuracoes.interface.volume_saida * 100)
        ttk.Scale(
            linha2,
            from_=0,
            to=100,
            variable=self._volume,
            command=self._trocar_volume,
            length=140,
            style="Painel.TScale",
        ).pack(side=tk.LEFT)

    def _montar_celula_local(self) -> None:
        """Cria a celula que mostra a propria transmissao."""
        celula = CelulaVideo(self._grade, self.paleta, f"{self._apelido} (voce)")
        celula.visualizador.limpar("Voce ainda nao esta transmitindo")
        self._celulas["local"] = celula
        self._reorganizar_grade()

    def _registrar_atalhos(self) -> None:
        """Liga os atalhos de teclado configurados."""
        self.bind("<Control-r>", lambda _e: self.alternar_gravacao())
        self.bind("<Control-g>", lambda _e: self.salvar_clipe())
        self.bind("<F11>", lambda _e: self.alternar_tela_cheia())
        self.bind("<Escape>", lambda _e: self._sair_tela_cheia())
        self.bind("<Control-m>", lambda _e: self.alternar_microfone())
        self.bind("<Control-d>", lambda _e: self.alternar_som())
        self.bind("<Control-s>", lambda _e: self.escolher_fonte())

    # -- Grade de video -----------------------------------------------------

    def _obter_celula(self, identificador: str, titulo: str) -> CelulaVideo:
        """Devolve (criando se preciso) a celula de um participante."""
        celula = self._celulas.get(identificador)
        if celula is None:
            celula = CelulaVideo(self._grade, self.paleta, titulo)
            self._celulas[identificador] = celula
            self._reorganizar_grade()
        else:
            celula.definir_titulo(titulo)
        return celula

    def _reorganizar_grade(self) -> None:
        """Recalcula a grade para caber todas as celulas ativas."""
        celulas = list(self._celulas.values())
        for celula in celulas:
            celula.grid_forget()
        colunas = 1 if len(celulas) == 1 else 2
        for indice, celula in enumerate(celulas):
            celula.grid(
                row=indice // colunas, column=indice % colunas, sticky="nsew", padx=4, pady=4
            )
        linhas = (len(celulas) + colunas - 1) // colunas
        for coluna in range(colunas):
            self._grade.columnconfigure(coluna, weight=1)
        for linha in range(max(1, linhas)):
            self._grade.rowconfigure(linha, weight=1)

    def _renderizar(self) -> None:
        """Desenha os quadros pendentes de todas as celulas."""
        if self._encerrando:
            return
        for celula in self._celulas.values():
            celula.visualizador.renderizar()
        if self._visualizador_destacado is not None:
            self._visualizador_destacado.renderizar()
        self.after(INTERVALO_RENDERIZACAO, self._renderizar)

    # -- Eventos da chamada -------------------------------------------------

    def _ao_entrar(self, sala: str, _identificador: str) -> None:
        """Confirma a entrada na sala."""
        self._sala = sala
        self._rotulo_estado.configure(text=f"Na sala {sala}. Aguardando participantes.")
        self._configuracoes.internet.ultima_sala = sala
        self._salvar_preferencias()

    def _salvar_preferencias(self) -> None:
        """Grava as configuracoes em disco sem interromper a chamada."""
        try:
            self._configuracoes.salvar()
        except OSError as erro:  # pragma: no cover - disco cheio ou sem permissao
            _registrador.warning("Nao foi possivel salvar as preferencias: %s", erro)

    def _ao_participantes(self, participantes: list[Participante]) -> None:
        """Atualiza a lista lateral e as legendas das celulas."""
        self._painel_participantes.atualizar(participantes)
        conectados = sum(1 for item in participantes if item.estado == "connected" and not item.eu)
        total = max(0, len(participantes) - 1)
        if total == 0:
            self._rotulo_estado.configure(
                text=f"Na sala {self._sala}. Envie o convite para alguem entrar."
            )
        else:
            self._rotulo_estado.configure(
                text=f"Na sala {self._sala}. {conectados} de {total} conectados diretamente."
            )
        for participante in participantes:
            if participante.eu:
                continue
            celula = self._celulas.get(participante.identificador)
            if celula is not None:
                celula.definir_titulo(participante.apelido)

    def _ao_quadro_remoto(self, origem: str, quadro: np.ndarray) -> None:
        """Entrega um quadro recebido a celula correspondente."""
        participante = next(
            (item for item in self.chamada.participantes if item.identificador == origem), None
        )
        titulo = participante.apelido if participante else "Participante"
        celula = self._obter_celula(origem, titulo)
        celula.visualizador.definir_quadro(quadro)
        if self._id_destacado == origem and self._visualizador_destacado is not None:
            self._visualizador_destacado.definir_quadro(quadro)

    def _ao_quadro_local(self, quadro: np.ndarray) -> None:
        """Mostra a propria transmissao e alimenta a gravacao."""
        self._ultimo_quadro_local = quadro
        celula = self._celulas.get("local")
        if celula is not None:
            celula.visualizador.definir_quadro(quadro)
        if self._id_destacado == "local" and self._visualizador_destacado is not None:
            self._visualizador_destacado.definir_quadro(quadro)
        self._gravacao.alimentar_video(quadro[:, :, ::-1])

    def _ao_estatisticas(self, dados: dict[str, Any]) -> None:
        """Mostra um resumo curto das metricas de rede."""
        pares = dados.get("pares", {})
        if not pares:
            self._rotulo_metricas.configure(text="")
            return
        taxas = [
            float(item.get("taxa_bits", 0) or 0)
            for item in pares.values()
            if isinstance(item, dict)
        ]
        perdas = [
            int(item.get("pacotes_perdidos", 0) or 0)
            for item in pares.values()
            if isinstance(item, dict)
        ]
        total_mbps = sum(taxas) / 1_000_000
        self._rotulo_metricas.configure(
            text=f"{dados.get('conectados', 0)} conectados | {total_mbps:.1f} Mbps"
            f" | perdas {sum(perdas)}"
        )

    def _ao_erro(self, texto: str) -> None:
        """Mostra um erro no chat e no cabecalho."""
        self._chat.adicionar_erro(texto)
        self._rotulo_estado.configure(text=texto[:90])

    def _ao_encerrar(self, motivo: str) -> None:
        """Registra o encerramento da chamada."""
        self._chat.adicionar_sistema(motivo)

    # -- Acoes --------------------------------------------------------------

    def _enviar_chat(self, texto: str) -> None:
        """Envia a mensagem digitada e a exibe localmente."""
        if self.chamada.enviar_chat(texto):
            self._chat.adicionar_mensagem(self._apelido, texto, proprio=True)
        else:
            self._chat.adicionar_erro("Ninguem conectado para receber a mensagem.")

    def escolher_fonte(self) -> None:
        """Abre o seletor de fonte ou encerra a transmissao em andamento."""
        if self.chamada.compartilhando:
            self.chamada.parar_compartilhamento()
            self._botao_transmitir.configure(text="Transmitir tela")
            celula = self._celulas.get("local")
            if celula is not None:
                celula.visualizador.limpar("Voce ainda nao esta transmitindo")
            return
        SeletorFonte(self, self.paleta, self._iniciar_transmissao)

    def _iniciar_transmissao(self, fonte: Any) -> None:
        """Comeca a transmitir a fonte escolhida."""
        self.chamada.iniciar_compartilhamento(fonte)
        self._botao_transmitir.configure(text="Parar transmissao")
        largura = int(fonte.regiao.get("width", 1280))
        altura = int(fonte.regiao.get("height", 720))
        if self._configuracoes.gravacao.buffer_automatico:
            self._gravacao.ativar_buffer(min(largura, 1280), min(altura, 720))

    def alternar_microfone(self) -> None:
        """Muta ou desmuta o proprio microfone."""
        ativo = self.chamada.alternar_microfone()
        self._botao_microfone.configure(
            text="Mutar microfone" if ativo else "Desmutar microfone",
            style="Barra.TButton" if ativo else "Perigo.TButton",
        )

    def alternar_som(self) -> None:
        """Liga ou desliga o audio recebido dos outros."""
        ativo = self.chamada.alternar_som()
        self._botao_som.configure(
            text="Desligar som" if ativo else "Ligar som",
            style="Barra.TButton" if ativo else "Perigo.TButton",
        )

    def _trocar_entrada(self, _evento: tk.Event | None = None) -> None:
        """Aplica o microfone escolhido no combobox."""
        rotulo = self._combo_entrada.get()
        self.chamada.trocar_microfone(self._mapa_entradas.get(rotulo))
        self._chat.adicionar_sistema(f"Microfone alterado para {rotulo}.")

    def _trocar_volume(self, _valor: str) -> None:
        """Aplica o volume do controle deslizante."""
        self.chamada.definir_volume(self._volume.get() / 100)

    def alternar_gravacao(self) -> None:
        """Inicia ou encerra a gravacao local em MP4."""
        estado = self._gravacao.estado()
        if estado.get("gravando"):
            caminho = self._gravacao.parar_gravacao()
            self._botao_gravar.configure(text="Gravar (Ctrl+R)", style="Barra.TButton")
            if caminho:
                self._chat.adicionar_sistema(f"Gravacao salva em {caminho}")
            return
        if self._ultimo_quadro_local is None:
            self._chat.adicionar_erro(
                "Comece a transmitir uma tela antes de gravar: a gravacao usa a sua imagem."
            )
            return
        altura, largura = self._ultimo_quadro_local.shape[:2]
        self._gravacao.ativar_buffer(largura, altura)
        if self._gravacao.iniciar_gravacao():
            self._botao_gravar.configure(text="Parar gravacao", style="Perigo.TButton")

    def salvar_clipe(self) -> None:
        """Salva os ultimos segundos do buffer, como no Medal."""
        segundos = self._configuracoes.gravacao.segundos_clipe
        caminho = self._gravacao.clipar(segundos)
        if caminho:
            self._chat.adicionar_sistema(f"Clipe de {segundos}s salvo em {caminho}")

    def alternar_tela_cheia(self) -> None:
        """Alterna a janela entre tela cheia e janela normal."""
        self._tela_cheia = not self._tela_cheia
        try:
            self.attributes("-fullscreen", self._tela_cheia)
        except tk.TclError:  # pragma: no cover - gerenciador de janelas simples
            self._tela_cheia = False

    def _sair_tela_cheia(self) -> None:
        """Sai da tela cheia sem alternar de volta."""
        if self._tela_cheia:
            self.alternar_tela_cheia()

    def destacar(self, identificador: str) -> None:
        """Abre a transmissao escolhida em uma janela separada."""
        if self._janela_destacada is not None and self._janela_destacada.winfo_exists():
            self._janela_destacada.destroy()
        janela = tk.Toplevel(self)
        janela.title("ScreenShare - transmissao")
        janela.geometry("960x540")
        aplicar_tema(janela, self._configuracoes.interface.tema)
        visualizador = VisualizadorVideo(janela, self.paleta)
        visualizador.pack(fill=tk.BOTH, expand=True)
        janela.bind("<F11>", lambda _e: janela.attributes("-fullscreen", True))
        janela.bind("<Escape>", lambda _e: janela.attributes("-fullscreen", False))
        self._janela_destacada = janela
        self._visualizador_destacado = visualizador
        self._id_destacado = identificador

    # -- Convite ------------------------------------------------------------

    def _montar_convite(self) -> Convite:
        """Monta o convite correspondente a sala atual."""
        return Convite(
            codigo=self._sala,
            servidor=self._configuracoes.internet.servidor_sinalizacao,
            modo="internet",
        )

    def copiar_convite(self) -> None:
        """Copia o texto do convite para a area de transferencia."""
        try:
            convite = self._montar_convite()
        except Exception as erro:
            self._chat.adicionar_erro(f"Nao foi possivel montar o convite: {erro}")
            return
        self.clipboard_clear()
        self.clipboard_append(convite.texto_amigavel)
        self._chat.adicionar_sistema("Convite copiado. Cole no WhatsApp, Telegram ou e-mail.")

    def mostrar_convite(self) -> None:
        """Mostra o convite completo em uma janela para copiar manualmente."""
        try:
            convite = self._montar_convite()
        except Exception as erro:
            messagebox.showerror("Convite", f"Nao foi possivel montar o convite: {erro}", parent=self)
            return
        janela = tk.Toplevel(self)
        janela.title("Convite da sala")
        janela.geometry("560x300")
        aplicar_tema(janela, self._configuracoes.interface.tema)
        ttk.Label(janela, text="Convite da sala", style="Titulo.TLabel").pack(
            anchor="w", padx=16, pady=(16, 4)
        )
        caixa = tk.Text(
            janela,
            height=8,
            wrap="word",
            background=self.paleta["fundo_campo"],
            foreground=self.paleta["texto"],
            relief="flat",
            padx=10,
            pady=10,
        )
        caixa.pack(fill=tk.BOTH, expand=True, padx=16)
        caixa.insert("end", convite.texto_amigavel)
        caixa.configure(state="disabled")
        rodape = ttk.Frame(janela, padding=(16, 10))
        rodape.pack(fill=tk.X)
        ttk.Button(rodape, text="Copiar", style="Destaque.TButton", command=self.copiar_convite).pack(
            side=tk.RIGHT
        )
        ttk.Button(rodape, text="Fechar", command=janela.destroy).pack(side=tk.RIGHT, padx=(0, 8))

    # -- Encerramento -------------------------------------------------------

    def encerrar(self) -> None:
        """Fecha a chamada, a gravacao e a janela."""
        if self._encerrando:
            return
        self._encerrando = True
        try:
            self._gravacao.parar_gravacao()
            self._gravacao.desativar_buffer()
        except Exception as erro:  # pragma: no cover - protecao de encerramento
            _registrador.warning("Falha ao encerrar gravacao: %s", erro)
        self.chamada.sair()
        self.ponte.encerrar()
        if self._janela_destacada is not None and self._janela_destacada.winfo_exists():
            self._janela_destacada.destroy()
        if self._ao_fechar is not None:
            self._ao_fechar()
        self.destroy()
