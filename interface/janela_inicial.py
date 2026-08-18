"""Janela inicial: cria ou entra em uma sala pela internet (ou usa o modo local).

O modo internet e o padrao. Ele nao exige liberar portas, nao depende de estar
na mesma rede e funciona entre cidades ou paises: um servidor de sinalizacao
apenas aproxima os participantes, e o audio/video vai direto de um computador ao
outro (WebRTC). O modo local antigo (TCP direto) fica disponivel para uso na
mesma rede, sem qualquer servidor.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from configuracao.configuracoes import (
    NOME_APLICACAO,
    VERSAO_APLICACAO,
    Configuracoes,
)
from interface.janela_chamada import JanelaChamada
from interface.janela_cliente import JanelaCliente
from interface.janela_servidor import JanelaServidor
from interface.tema import aplicar_tema
from midia.captura_audio import descrever_motor_audio
from nucleo.convite import ErroConvite, gerar_codigo_sala, interpretar
from utilitarios.recursos import aplicar_icone
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)


class JanelaInicial(tk.Tk):
    """Menu principal da aplicacao."""

    def __init__(self, configuracoes: Configuracoes | None = None) -> None:
        super().__init__()
        self.configuracoes = configuracoes or Configuracoes.carregar()
        self.title(f"{NOME_APLICACAO} {VERSAO_APLICACAO}")
        self.geometry("660x700")
        self.minsize(620, 640)

        self._paleta = aplicar_tema(self, self.configuracoes.interface.tema)
        aplicar_icone(self)
        self._janelas: list[tk.Toplevel] = []

        self._construir()
        self.bind("<Control-q>", lambda _e: self._ao_fechar())
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    # -- Montagem -----------------------------------------------------------

    def _construir(self) -> None:
        """Monta cabecalho, abas de modo e rodape."""
        cabecalho = ttk.Frame(self, padding=(24, 20, 24, 8))
        cabecalho.pack(fill=tk.X)
        ttk.Label(cabecalho, text=NOME_APLICACAO, style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(
            cabecalho,
            text="Chamadas de voz, video e tela entre qualquer lugar do mundo",
            style="Secundario.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        identidade = ttk.Frame(self, padding=(24, 4))
        identidade.pack(fill=tk.X)
        identidade.columnconfigure(1, weight=1)
        ttk.Label(identidade, text="Seu apelido").grid(row=0, column=0, sticky="w")
        self._apelido = tk.StringVar(value=self.configuracoes.interface.apelido or "Usuario")
        ttk.Entry(identidade, textvariable=self._apelido).grid(
            row=0, column=1, sticky="ew", padx=(10, 0)
        )

        abas = ttk.Notebook(self)
        abas.pack(fill=tk.BOTH, expand=True, padx=24, pady=(12, 8))
        self._aba_internet(abas)
        self._aba_local(abas)
        self._aba_ajustes(abas)

        rodape = ttk.Frame(self, style="Barra.TFrame", padding=(24, 10))
        rodape.pack(fill=tk.X)
        ttk.Label(
            rodape,
            text=f"Audio: {descrever_motor_audio()}",
            style="Status.TLabel",
        ).pack(side=tk.LEFT)
        ttk.Button(rodape, text="Sair", command=self._ao_fechar).pack(side=tk.RIGHT)

    def _aba_internet(self, abas: ttk.Notebook) -> None:
        """Aba principal: criar sala ou entrar por codigo/convite."""
        aba = ttk.Frame(abas, padding=16)
        abas.add(aba, text="  Chamada pela internet  ")
        aba.columnconfigure(0, weight=1)

        ttk.Label(
            aba,
            text=(
                "Crie uma sala e envie o convite. Quem receber entra pelo codigo,\n"
                "de qualquer rede, sem abrir portas no firewall."
            ),
            style="Secundario.TLabel",
            justify="left",
        ).grid(row=0, column=0, sticky="w")

        servidor = ttk.LabelFrame(aba, text="Servidor de sinalizacao", padding=12)
        servidor.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        servidor.columnconfigure(0, weight=1)
        self._servidor = tk.StringVar(value=self.configuracoes.internet.servidor_sinalizacao)
        ttk.Entry(servidor, textvariable=self._servidor).grid(row=0, column=0, sticky="ew")
        ttk.Label(
            servidor,
            text=(
                "Exemplo: wss://minha-sala.onrender.com/ws\n"
                "O servidor acompanha o projeto (pasta servidor_sinalizacao) e pode ser\n"
                "publicado de graca. Ele so troca mensagens de encontro: o video nunca passa por ele."
            ),
            style="Status.TLabel",
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        sala = ttk.LabelFrame(aba, text="Sala", padding=12)
        sala.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        sala.columnconfigure(1, weight=1)

        ttk.Label(sala, text="Codigo").grid(row=0, column=0, sticky="w")
        self._codigo = tk.StringVar(value=self.configuracoes.internet.ultima_sala)
        ttk.Entry(sala, textvariable=self._codigo, width=14).grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )
        ttk.Button(sala, text="Gerar codigo", command=self._gerar_codigo).grid(
            row=0, column=2, padx=(10, 0)
        )

        ttk.Label(sala, text="Senha (opcional)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._senha = tk.StringVar()
        ttk.Entry(sala, textvariable=self._senha, show="*", width=14).grid(
            row=1, column=1, sticky="w", padx=(10, 0), pady=(8, 0)
        )

        ttk.Label(sala, text="Ou cole um convite").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self._convite = tk.StringVar()
        ttk.Entry(sala, textvariable=self._convite).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=(8, 0)
        )
        ttk.Button(sala, text="Usar convite", command=self._aplicar_convite).grid(
            row=3, column=1, sticky="w", padx=(10, 0), pady=(8, 0)
        )

        acoes = ttk.Frame(aba)
        acoes.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        ttk.Button(
            acoes,
            text="Criar sala e entrar",
            style="Destaque.TButton",
            command=self._criar_sala,
        ).pack(side=tk.LEFT)
        ttk.Button(acoes, text="Entrar na sala", style="Sucesso.TButton", command=self._entrar).pack(
            side=tk.LEFT, padx=(10, 0)
        )

    def _aba_local(self, abas: ttk.Notebook) -> None:
        """Aba do modo antigo, direto por IP na mesma rede."""
        aba = ttk.Frame(abas, padding=16)
        abas.add(aba, text="  Rede local (avancado)  ")
        ttk.Label(
            aba,
            text=(
                "Modo direto por IP, sem servidor nenhum. Funciona quando os dois\n"
                "computadores estao na mesma rede (casa, escritorio, LAN house).\n"
                "Para conexoes entre cidades, use a aba de chamada pela internet."
            ),
            style="Secundario.TLabel",
            justify="left",
        ).pack(anchor="w")
        botoes = ttk.Frame(aba)
        botoes.pack(anchor="w", pady=(16, 0))
        ttk.Button(botoes, text="Transmitir (host)", command=self._abrir_servidor).pack(side=tk.LEFT)
        ttk.Button(botoes, text="Assistir (cliente)", command=self._abrir_cliente).pack(
            side=tk.LEFT, padx=(10, 0)
        )

    def _aba_ajustes(self, abas: ttk.Notebook) -> None:
        """Aba com tema, TURN e preferencias de gravacao."""
        aba = ttk.Frame(abas, padding=16)
        abas.add(aba, text="  Ajustes  ")
        aba.columnconfigure(1, weight=1)

        ttk.Label(aba, text="Tema").grid(row=0, column=0, sticky="w")
        self._tema = tk.StringVar(value=self.configuracoes.interface.tema)
        combo = ttk.Combobox(
            aba, textvariable=self._tema, values=["escuro", "claro"], state="readonly", width=12
        )
        combo.grid(row=0, column=1, sticky="w", padx=(10, 0))
        combo.bind("<<ComboboxSelected>>", self._trocar_tema)

        turn = ttk.LabelFrame(aba, text="Servidor TURN (para redes muito restritivas)", padding=12)
        turn.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        turn.columnconfigure(1, weight=1)
        self._turn_url = tk.StringVar(value=self.configuracoes.internet.turn_url)
        self._turn_usuario = tk.StringVar(value=self.configuracoes.internet.turn_usuario)
        self._turn_senha = tk.StringVar(value=self.configuracoes.internet.turn_senha)
        for indice, (rotulo, variavel, oculto) in enumerate(
            (
                ("Endereco", self._turn_url, False),
                ("Usuario", self._turn_usuario, False),
                ("Senha", self._turn_senha, True),
            )
        ):
            ttk.Label(turn, text=rotulo).grid(row=indice, column=0, sticky="w", pady=2)
            ttk.Entry(
                turn, textvariable=variavel, show="*" if oculto else ""
            ).grid(row=indice, column=1, sticky="ew", padx=(10, 0), pady=2)
        ttk.Label(
            turn,
            text=(
                "Deixe em branco na maioria dos casos. Preencha se a operadora usar\n"
                "CGNAT e a conexao direta falhar (exemplo: turn:servidor:3478)."
            ),
            style="Status.TLabel",
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        gravacao = ttk.LabelFrame(aba, text="Gravacao e clipes", padding=12)
        gravacao.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        gravacao.columnconfigure(1, weight=1)
        ttk.Label(gravacao, text="Pasta").grid(row=0, column=0, sticky="w")
        self._pasta = tk.StringVar(value=self.configuracoes.gravacao.pasta)
        ttk.Entry(gravacao, textvariable=self._pasta).grid(
            row=0, column=1, sticky="ew", padx=(10, 0)
        )
        self._buffer_automatico = tk.BooleanVar(
            value=self.configuracoes.gravacao.buffer_automatico
        )
        ttk.Checkbutton(
            gravacao,
            text="Manter buffer de clipes ligado ao transmitir (usa mais memoria)",
            variable=self._buffer_automatico,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Button(aba, text="Salvar ajustes", style="Destaque.TButton", command=self._salvar).grid(
            row=3, column=0, sticky="w", pady=(18, 0)
        )

    # -- Acoes --------------------------------------------------------------

    def _gerar_codigo(self) -> None:
        """Sorteia um codigo de sala novo."""
        self._codigo.set(gerar_codigo_sala())

    def _aplicar_convite(self) -> None:
        """Le um convite colado e preenche os campos."""
        texto = self._convite.get().strip()
        if not texto:
            return
        try:
            convite = interpretar(texto)
        except ErroConvite as erro:
            messagebox.showerror("Convite invalido", str(erro), parent=self)
            return
        self._codigo.set(convite.codigo)
        if convite.senha:
            self._senha.set(convite.senha)
        if convite.modo == "internet" and convite.servidor:
            self._servidor.set(convite.servidor)
        messagebox.showinfo(
            "Convite aplicado",
            f"Sala {convite.codigo} pronta. Clique em Entrar na sala.",
            parent=self,
        )

    def _criar_sala(self) -> None:
        """Gera um codigo (se preciso) e entra na sala."""
        if not self._codigo.get().strip():
            self._gerar_codigo()
        self._entrar()

    def _entrar(self) -> None:
        """Valida os campos e abre a janela de chamada."""
        codigo = "".join(self._codigo.get().upper().split())
        apelido = self._apelido.get().strip() or "Usuario"
        servidor = self._servidor.get().strip()
        if not codigo:
            messagebox.showwarning(
                "Sala", "Informe ou gere um codigo de sala.", parent=self
            )
            return
        if not servidor:
            messagebox.showwarning(
                "Servidor de sinalizacao",
                "Informe o endereco do servidor de sinalizacao.\n\n"
                "Publique a pasta servidor_sinalizacao (veja o README) ou use o modo"
                " de rede local se os dois computadores estiverem na mesma rede.",
                parent=self,
            )
            return

        self.configuracoes.internet.servidor_sinalizacao = servidor
        self.configuracoes.internet.ultima_sala = codigo
        self.configuracoes.interface.apelido = apelido
        self._salvar_preferencias()

        janela = JanelaChamada(
            self,
            self.configuracoes,
            codigo,
            apelido,
            self._senha.get(),
        )
        self._registrar(janela)

    def _abrir_servidor(self) -> None:
        """Abre a janela do modo local em papel de host."""
        self._sincronizar_apelido()
        self._registrar(JanelaServidor(self, self.configuracoes))

    def _abrir_cliente(self) -> None:
        """Abre a janela do modo local em papel de espectador."""
        self._sincronizar_apelido()
        self._registrar(JanelaCliente(self, self.configuracoes))

    def _sincronizar_apelido(self) -> None:
        """Guarda o apelido digitado nas configuracoes."""
        self.configuracoes.interface.apelido = self._apelido.get().strip() or "Usuario"
        self._salvar_preferencias()

    def _trocar_tema(self, _evento: tk.Event | None = None) -> None:
        """Aplica o tema escolhido imediatamente."""
        self.configuracoes.interface.tema = self._tema.get()
        self._paleta = aplicar_tema(self, self._tema.get())
        self._salvar_preferencias()

    def _salvar(self) -> None:
        """Persiste os ajustes da aba de configuracoes."""
        internet = self.configuracoes.internet
        internet.servidor_sinalizacao = self._servidor.get().strip()
        internet.turn_url = self._turn_url.get().strip()
        internet.turn_usuario = self._turn_usuario.get().strip()
        internet.turn_senha = self._turn_senha.get().strip()
        self.configuracoes.gravacao.pasta = self._pasta.get().strip()
        self.configuracoes.gravacao.buffer_automatico = bool(self._buffer_automatico.get())
        self.configuracoes.interface.apelido = self._apelido.get().strip() or "Usuario"
        self.configuracoes.interface.tema = self._tema.get()
        self._salvar_preferencias()
        messagebox.showinfo("Ajustes", "Preferencias salvas.", parent=self)

    def _salvar_preferencias(self) -> None:
        """Grava as configuracoes em disco sem interromper a interface."""
        try:
            self.configuracoes.salvar()
        except OSError as erro:  # pragma: no cover - disco cheio ou sem permissao
            _registrador.warning("Nao foi possivel salvar as preferencias: %s", erro)

    def _registrar(self, janela: tk.Toplevel) -> None:
        """Guarda a janela aberta para fechar tudo no final."""
        self._janelas.append(janela)
        janela.focus_set()

    def _ao_fechar(self) -> None:
        """Fecha as janelas filhas e encerra a aplicacao."""
        self._sincronizar_apelido()
        for janela in list(self._janelas):
            try:
                if janela.winfo_exists():
                    encerrar = getattr(janela, "encerrar", None)
                    if callable(encerrar):
                        encerrar()
                    else:
                        janela.destroy()
            except tk.TclError:  # pragma: no cover - janela ja destruida
                pass
        self.destroy()
