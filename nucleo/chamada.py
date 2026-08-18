"""Orquestrador de uma chamada pela internet (WebRTC em malha).

Este modulo e o coracao do modo internet. Ele:

1. entra em uma sala pelo servidor de sinalizacao (`nucleo.sinalizacao`);
2. abre uma conexao WebRTC direta com cada participante (`nucleo.par_webrtc`),
   formando uma malha - cada um fala com todos, sem servidor de midia;
3. publica a tela e o microfone locais como faixas, usando um `MediaRelay` para
   que a MESMA captura alimente todos os pares, a previa local e a gravacao;
4. recebe video, audio e chat dos outros e entrega tudo por callbacks.

Por que malha e nao servidor de midia: para tres ou quatro pessoas a malha
dispensa infraestrutura (nenhum byte de video passa por um servidor nosso), o
que era o requisito principal. Acima de seis participantes o custo de subida
cresce demais, e por isso `LIMITE_PARTICIPANTES` existe.

Toda a rede roda em um laco asyncio proprio, dentro de uma thread dedicada. A
interface (tkinter) e sincrona e nunca toca nesse laco diretamente: os metodos
publicos desta classe agendam corrotinas com `run_coroutine_threadsafe`, e os
eventos voltam por callbacks que a janela redireciona para a `PonteInterface`.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aiortc.contrib.media import MediaRelay

from configuracao.configuracoes import RESOLUCOES, Configuracoes
from midia.faixas_webrtc import (
    ConsumidorFaixaVideo,
    FaixaMicrofone,
    FaixaTela,
    ReprodutorFaixaRemota,
)
from midia.fontes import FonteCaptura
from nucleo.par_webrtc import ParRemoto, montar_configuracao_ice
from nucleo.sinalizacao import ClienteSinalizacao
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

#: Intervalo entre coletas de estatisticas das conexoes.
INTERVALO_ESTATISTICAS = 2.0


@dataclass
class Participante:
    """Estado conhecido de uma pessoa na sala."""

    identificador: str
    apelido: str
    microfone_ativo: bool = True
    compartilhando: bool = False
    estado: str = "conectando"
    eu: bool = False

    @property
    def descricao_estado(self) -> str:
        """Texto curto para a lista de participantes."""
        if self.eu:
            return "voce"
        mapa = {
            "connected": "conectado",
            "connecting": "conectando",
            "new": "conectando",
            "checking": "negociando",
            "failed": "falhou",
            "closed": "saiu",
            "disconnected": "instavel",
        }
        return mapa.get(self.estado, self.estado)


@dataclass
class RetornosChamada:
    """Callbacks que a interface registra para acompanhar a chamada.

    Todos sao opcionais e chamados a partir da thread de rede: a janela deve
    redirecionar cada um para a thread da interface.
    """

    ao_entrar: Callable[[str, str], None] | None = None
    ao_participantes: Callable[[list[Participante]], None] | None = None
    ao_chat: Callable[[str, str], None] | None = None
    ao_sistema: Callable[[str], None] | None = None
    ao_erro: Callable[[str], None] | None = None
    ao_quadro_remoto: Callable[[str, Any], None] | None = None
    ao_quadro_local: Callable[[Any], None] | None = None
    ao_estatisticas: Callable[[dict[str, Any]], None] | None = None
    ao_encerrar: Callable[[str], None] | None = None


class Chamada:
    """Uma chamada de voz, video e chat em uma sala."""

    def __init__(
        self,
        configuracoes: Configuracoes,
        retornos: RetornosChamada | None = None,
    ) -> None:
        self._configuracoes = configuracoes
        self._retornos = retornos or RetornosChamada()

        self._laco: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._pronto = threading.Event()

        self._sinalizacao: ClienteSinalizacao | None = None
        self._pares: dict[str, ParRemoto] = {}
        self._participantes: dict[str, Participante] = {}
        self._id_local = ""
        self._sala = ""
        self._apelido = ""
        self._senha = ""

        self._distribuidor = MediaRelay()
        self._faixa_tela: FaixaTela | None = None
        self._faixa_microfone: FaixaMicrofone | None = None
        self._previa: ConsumidorFaixaVideo | None = None
        self._consumidores_video: dict[str, ConsumidorFaixaVideo] = {}
        self._reprodutores: dict[str, ReprodutorFaixaRemota] = {}
        self._tarefa_estatisticas: asyncio.Task[None] | None = None

        self._microfone_ativo = True
        self._som_ativo = True
        self._compartilhando = False
        self._fonte_atual: FonteCaptura | None = None
        self._encerrada = False

    # -- Propriedades -------------------------------------------------------

    @property
    def sala(self) -> str:
        """Codigo da sala atual."""
        return self._sala

    @property
    def id_local(self) -> str:
        """Identificador do proprio participante na sala."""
        return self._id_local

    @property
    def microfone_ativo(self) -> bool:
        """``False`` quando o microfone esta mudo."""
        return self._microfone_ativo

    @property
    def som_ativo(self) -> bool:
        """``False`` quando o audio recebido esta desligado."""
        return self._som_ativo

    @property
    def compartilhando(self) -> bool:
        """``True`` enquanto uma tela ou janela esta sendo transmitida."""
        return self._compartilhando

    @property
    def fonte_atual(self) -> FonteCaptura | None:
        """Fonte de captura em uso, se houver."""
        return self._fonte_atual

    @property
    def participantes(self) -> list[Participante]:
        """Lista ordenada de participantes, com o usuario local primeiro."""
        return sorted(self._participantes.values(), key=lambda item: (not item.eu, item.apelido))

    # -- Ciclo de vida ------------------------------------------------------

    def entrar(self, sala: str, apelido: str, senha: str = "") -> None:
        """Sobe a thread de rede e entra na sala informada."""
        if self._thread is not None:
            raise RuntimeError("Esta chamada ja foi iniciada.")
        self._sala = "".join(sala.upper().split())
        self._apelido = apelido.strip() or "Usuario"
        self._senha = senha
        self._thread = threading.Thread(target=self._executar_laco, name="chamada", daemon=True)
        self._thread.start()
        self._pronto.wait(timeout=5.0)
        self._agendar(self._entrar_na_sala())

    def sair(self, motivo: str = "Chamada encerrada") -> None:
        """Encerra a chamada, as conexoes e a thread de rede."""
        if self._encerrada:
            return
        self._encerrada = True
        laco = self._laco
        if laco is not None and laco.is_running():
            futuro = asyncio.run_coroutine_threadsafe(self._encerrar_tudo(), laco)
            with contextlib.suppress(Exception):
                futuro.result(timeout=6.0)
            laco.call_soon_threadsafe(laco.stop)
        if self._thread is not None:
            self._thread.join(timeout=4.0)
        self._notificar(self._retornos.ao_encerrar, motivo)

    def _executar_laco(self) -> None:
        """Corpo da thread de rede: um laco asyncio dedicado."""
        laco = asyncio.new_event_loop()
        asyncio.set_event_loop(laco)
        self._laco = laco
        self._pronto.set()
        try:
            laco.run_forever()
        finally:
            self._cancelar_tarefas_restantes(laco)
            with contextlib.suppress(Exception):
                laco.run_until_complete(laco.shutdown_asyncgens())
            laco.close()
            _registrador.info("Laco da chamada encerrado")

    @staticmethod
    def _cancelar_tarefas_restantes(laco: asyncio.AbstractEventLoop) -> None:
        """Cancela tarefas internas do aiortc antes de fechar o laco.

        Sem isso, o encerramento imprime avisos do tipo "Task was destroyed but
        it is pending" para as tarefas do distribuidor de midia.
        """
        pendentes = [tarefa for tarefa in asyncio.all_tasks(laco) if not tarefa.done()]
        if not pendentes:
            return
        for tarefa in pendentes:
            tarefa.cancel()
        with contextlib.suppress(Exception):
            laco.run_until_complete(
                asyncio.gather(*pendentes, return_exceptions=True)
            )

    def _agendar(self, corrotina) -> None:
        """Agenda uma corrotina no laco de rede, vindo de qualquer thread."""
        laco = self._laco
        if laco is None or not laco.is_running():
            corrotina.close()
            return
        futuro = asyncio.run_coroutine_threadsafe(corrotina, laco)
        futuro.add_done_callback(self._registrar_falha)

    def _registrar_falha(self, futuro) -> None:
        """Converte excecoes de tarefas em log e aviso na interface."""
        try:
            futuro.result()
        except asyncio.CancelledError:  # pragma: no cover - encerramento normal
            pass
        except Exception as erro:
            _registrador.exception("Falha em tarefa da chamada: %s", erro)
            self._notificar(self._retornos.ao_erro, f"Falha interna: {erro}")

    # -- Sinalizacao --------------------------------------------------------

    async def _entrar_na_sala(self) -> None:
        """Conecta ao servidor de sinalizacao e pede entrada na sala."""
        internet = self._configuracoes.internet
        if not internet.servidor_sinalizacao:
            self._notificar(
                self._retornos.ao_erro,
                "Nenhum servidor de sinalizacao configurado. Abra Configuracoes e informe"
                " o endereco, ou use o modo de convite manual.",
            )
            return
        self._sinalizacao = ClienteSinalizacao(
            internet.servidor_sinalizacao,
            ao_bem_vindo=self._ao_bem_vindo,
            ao_entrou=self._ao_entrou,
            ao_saiu=self._ao_saiu,
            ao_sinal=self._ao_sinal,
            ao_erro=self._ao_erro_sinalizacao,
            ao_desconectar=self._ao_desconectar,
        )
        if not await self._sinalizacao.conectar():
            self._notificar(
                self._retornos.ao_erro,
                "Nao foi possivel falar com o servidor de sinalizacao."
                " Verifique o endereco e a sua conexao com a internet.",
            )
            return
        await self._sinalizacao.entrar(self._sala, self._apelido, self._senha)

    def _ao_bem_vindo(self, identificador: str, sala: str, participantes: list) -> None:
        """Entrada aceita: cria um par para cada pessoa que ja estava na sala."""
        self._id_local = identificador
        self._sala = sala
        self._participantes = {
            identificador: Participante(identificador, self._apelido, eu=True, estado="connected")
        }
        self._notificar(self._retornos.ao_entrar, sala, identificador)
        self._notificar(
            self._retornos.ao_sistema,
            f"Voce entrou na sala {sala}. Compartilhe o codigo com quem for participar.",
        )
        for dados in participantes:
            outro = dados.get("id", "")
            apelido = dados.get("apelido", "Participante")
            if not outro or outro == identificador:
                continue
            self._participantes[outro] = Participante(outro, apelido)
            # Quem entra depois inicia a oferta: evita ofertas simultaneas.
            self._agendar(self._criar_par(outro, apelido, iniciador=True))
        self._publicar_participantes()
        self._agendar(self._iniciar_estatisticas())

    def _ao_entrou(self, identificador: str, apelido: str) -> None:
        """Alguem novo entrou: prepara o par que vai receber a oferta dele."""
        self._participantes[identificador] = Participante(identificador, apelido)
        self._notificar(self._retornos.ao_sistema, f"{apelido} entrou na chamada.")
        self._publicar_participantes()
        self._agendar(self._criar_par(identificador, apelido, iniciador=False))

    def _ao_saiu(self, identificador: str) -> None:
        """Alguem saiu: limpa par, consumidores e reprodutores."""
        participante = self._participantes.pop(identificador, None)
        if participante is not None:
            self._notificar(self._retornos.ao_sistema, f"{participante.apelido} saiu da chamada.")
        self._publicar_participantes()
        self._agendar(self._remover_par(identificador))

    def _ao_sinal(self, origem: str, dados: dict) -> None:
        """Repassa um sinal recebido ao par correspondente."""
        self._agendar(self._entregar_sinal(origem, dados))

    def _ao_erro_sinalizacao(self, codigo: str, mensagem: str) -> None:
        """Traduz erros da sinalizacao para linguagem de usuario."""
        traducoes = {
            "SALA_CHEIA": "A sala esta cheia. O limite e de seis participantes.",
            "SENHA_INCORRETA": "Senha da sala incorreta.",
            "SALA_INEXISTENTE": "Essa sala nao existe mais.",
            "DADOS_INVALIDOS": "Informe um codigo de sala e um apelido validos.",
        }
        self._notificar(self._retornos.ao_erro, traducoes.get(codigo, mensagem))

    def _ao_desconectar(self) -> None:
        """Aviso de queda da sinalizacao (a midia em curso continua)."""
        self._notificar(
            self._retornos.ao_sistema,
            "Conexao com o servidor de sinalizacao caiu. Tentando reconectar.",
        )

    async def _entregar_sinal(self, origem: str, dados: dict) -> None:
        """Garante que existe um par para a origem e entrega o sinal."""
        par = self._pares.get(origem)
        if par is None:
            apelido = self._participantes.get(origem, Participante(origem, "Participante")).apelido
            par = await self._criar_par(origem, apelido, iniciador=False)
        if par is not None:
            await par.receber_sinal(dados)

    # -- Pares WebRTC -------------------------------------------------------

    async def _criar_par(self, identificador: str, apelido: str, iniciador: bool) -> ParRemoto | None:
        """Cria a conexao WebRTC com um participante e publica as faixas locais."""
        if identificador in self._pares:
            return self._pares[identificador]
        internet = self._configuracoes.internet
        configuracao_ice = montar_configuracao_ice(
            list(internet.servidores_stun),
            internet.turn_url,
            internet.turn_usuario,
            internet.turn_senha,
            internet.forcar_relay,
        )
        par = ParRemoto(
            identificador,
            apelido,
            configuracao_ice,
            iniciador,
            ao_sinal=lambda dados, destino=identificador: self._enviar_sinal(destino, dados),
            ao_faixa_video=lambda faixa, origem=identificador: self._receber_video(origem, faixa),
            ao_faixa_audio=lambda faixa, origem=identificador: self._receber_audio(origem, faixa),
            ao_estado=lambda estado, origem=identificador: self._atualizar_estado(origem, estado),
            ao_mensagem_dados=lambda objeto, origem=identificador: self._receber_dados(
                origem, objeto
            ),
            ao_encerrar=lambda origem=identificador: self._ao_saiu(origem),
        )
        self._pares[identificador] = par
        await self._publicar_faixas_locais(par)
        await par.iniciar()
        # Informa o estado atual (mudo, compartilhando) assim que possivel.
        self._agendar(self._anunciar_estado_ao_par(par))
        return par

    async def _anunciar_estado_ao_par(self, par: ParRemoto) -> None:
        """Espera o canal de dados e envia o estado local uma vez."""
        for _ in range(40):
            if par.enviar_dados(
                {
                    "tipo": "estado",
                    "apelido": self._apelido,
                    "microfone": self._microfone_ativo,
                    "compartilhando": self._compartilhando,
                }
            ):
                return
            await asyncio.sleep(0.25)

    async def _publicar_faixas_locais(self, par: ParRemoto) -> None:
        """Assina as faixas locais para este par por meio do distribuidor."""
        video = None
        audio = None
        if self._faixa_tela is not None:
            video = self._distribuidor.subscribe(self._faixa_tela, buffered=False)
        if self._faixa_microfone is None:
            self._faixa_microfone = self._criar_faixa_microfone()
        if self._faixa_microfone is not None:
            audio = self._distribuidor.subscribe(self._faixa_microfone, buffered=False)
        if video is not None or audio is not None:
            await par.definir_faixas(video=video, audio=audio)

    async def _remover_par(self, identificador: str) -> None:
        """Encerra e descarta tudo relacionado a um participante."""
        par = self._pares.pop(identificador, None)
        if par is not None:
            await par.encerrar()
        consumidor = self._consumidores_video.pop(identificador, None)
        if consumidor is not None:
            consumidor.parar()
        reprodutor = self._reprodutores.pop(identificador, None)
        if reprodutor is not None:
            reprodutor.parar()

    def _enviar_sinal(self, destino: str, dados: dict) -> None:
        """Encaminha um sinal do par para o servidor de sinalizacao."""
        if self._sinalizacao is None:
            return
        self._agendar(self._sinalizacao.enviar_sinal(destino, dados))

    def _atualizar_estado(self, identificador: str, estado: str) -> None:
        """Atualiza o estado da conexao de um participante."""
        participante = self._participantes.get(identificador)
        if participante is None:
            return
        participante.estado = estado
        if estado == "connected":
            self._notificar(
                self._retornos.ao_sistema,
                f"Conexao direta estabelecida com {participante.apelido}.",
            )
        elif estado == "failed":
            self._notificar(
                self._retornos.ao_erro,
                f"Nao foi possivel abrir a conexao direta com {participante.apelido}."
                " Se a sua rede for restritiva, configure um servidor TURN.",
            )
        self._publicar_participantes()

    # -- Midia recebida -----------------------------------------------------

    def _receber_video(self, origem: str, faixa) -> None:
        """Consome a faixa de video de um participante e repassa os quadros."""
        anterior = self._consumidores_video.pop(origem, None)
        if anterior is not None:
            anterior.parar()
        consumidor = ConsumidorFaixaVideo(
            faixa, lambda quadro, quem=origem: self._entregar_quadro(quem, quadro)
        )
        self._consumidores_video[origem] = consumidor
        consumidor.iniciar()
        participante = self._participantes.get(origem)
        if participante is not None:
            participante.compartilhando = True
            self._publicar_participantes()

    def _receber_audio(self, origem: str, faixa) -> None:
        """Reproduz a faixa de audio de um participante."""
        anterior = self._reprodutores.pop(origem, None)
        if anterior is not None:
            anterior.parar()
        reprodutor = ReprodutorFaixaRemota(faixa, self._configuracoes.audio.dispositivo_saida)
        reprodutor.surdo = not self._som_ativo
        reprodutor.volume = self._configuracoes.interface.volume_saida
        self._reprodutores[origem] = reprodutor
        reprodutor.iniciar()

    def _entregar_quadro(self, origem: str, quadro) -> None:
        """Entrega um quadro remoto para a interface."""
        self._notificar(self._retornos.ao_quadro_remoto, origem, quadro)

    def _receber_dados(self, origem: str, objeto: Any) -> None:
        """Trata mensagens do canal de controle (chat e estado)."""
        if not isinstance(objeto, dict):
            return
        participante = self._participantes.get(origem)
        apelido = participante.apelido if participante else "Participante"
        tipo = objeto.get("tipo")
        if tipo == "chat":
            texto = str(objeto.get("texto", ""))[:2000]
            if texto:
                self._notificar(self._retornos.ao_chat, apelido, texto)
        elif tipo == "estado" and participante is not None:
            participante.apelido = str(objeto.get("apelido", apelido))[:40] or apelido
            participante.microfone_ativo = bool(objeto.get("microfone", True))
            participante.compartilhando = bool(objeto.get("compartilhando", False))
            self._publicar_participantes()
        elif tipo == "saindo":
            self._ao_saiu(origem)

    # -- Acoes do usuario ---------------------------------------------------

    def iniciar_compartilhamento(self, fonte: FonteCaptura) -> None:
        """Comeca (ou troca) a transmissao da tela, monitor ou janela."""
        self._fonte_atual = fonte
        self._agendar(self._iniciar_compartilhamento(fonte))

    async def _iniciar_compartilhamento(self, fonte: FonteCaptura) -> None:
        """Cria ou reaproveita a faixa de tela e a publica para todos os pares."""
        video = self._configuracoes.video
        largura, altura = RESOLUCOES.get(video.resolucao, (1280, 720))
        if self._faixa_tela is None:
            self._faixa_tela = FaixaTela(fonte, largura, altura, video.fps)
            self._previa = ConsumidorFaixaVideo(
                self._distribuidor.subscribe(self._faixa_tela, buffered=False),
                lambda quadro: self._notificar(self._retornos.ao_quadro_local, quadro),
            )
            self._previa.iniciar()
            for par in list(self._pares.values()):
                await par.definir_faixas(
                    video=self._distribuidor.subscribe(self._faixa_tela, buffered=False)
                )
        else:
            self._faixa_tela.trocar_fonte(fonte)
        self._compartilhando = True
        self._anunciar_estado()
        self._notificar(self._retornos.ao_sistema, f"Compartilhando: {fonte.titulo}")

    def parar_compartilhamento(self) -> None:
        """Interrompe a transmissao de tela, mantendo a chamada de voz."""
        self._agendar(self._parar_compartilhamento())

    async def _parar_compartilhamento(self) -> None:
        """Remove a faixa de video de todos os pares e libera a captura."""
        for par in list(self._pares.values()):
            await par.remover_faixa_video()
        if self._previa is not None:
            self._previa.parar()
            self._previa = None
        if self._faixa_tela is not None:
            self._faixa_tela.parar()
            self._faixa_tela = None
        self._compartilhando = False
        self._fonte_atual = None
        self._anunciar_estado()
        self._notificar(self._retornos.ao_sistema, "Compartilhamento encerrado.")

    def alternar_microfone(self) -> bool:
        """Liga/desliga o envio do microfone e devolve o novo estado."""
        self._microfone_ativo = not self._microfone_ativo
        if self._faixa_microfone is not None:
            self._faixa_microfone.mudo = not self._microfone_ativo
        self._anunciar_estado()
        participante = self._participantes.get(self._id_local)
        if participante is not None:
            participante.microfone_ativo = self._microfone_ativo
            self._publicar_participantes()
        return self._microfone_ativo

    def alternar_som(self) -> bool:
        """Liga/desliga o audio recebido (apenas local) e devolve o estado."""
        self._som_ativo = not self._som_ativo
        for reprodutor in self._reprodutores.values():
            reprodutor.surdo = not self._som_ativo
        return self._som_ativo

    def definir_volume(self, volume: float) -> None:
        """Ajusta o volume de reproducao (0.0 a 1.0)."""
        volume = max(0.0, min(1.0, volume))
        self._configuracoes.interface.volume_saida = volume
        for reprodutor in self._reprodutores.values():
            reprodutor.volume = volume

    def trocar_microfone(self, indice: int | None) -> None:
        """Troca o dispositivo de entrada sem derrubar a chamada."""
        self._configuracoes.audio.dispositivo_entrada = indice
        if self._faixa_microfone is not None:
            self._faixa_microfone.trocar_dispositivo(indice)

    def enviar_chat(self, texto: str) -> bool:
        """Envia uma mensagem de chat a todos os participantes."""
        texto = texto.strip()[:2000]
        if not texto:
            return False
        mensagem = {"tipo": "chat", "texto": texto, "apelido": self._apelido}
        # O envio precisa ocorrer na thread do laco asyncio: o canal de dados do
        # aiortc agenda tarefas internas e falha se chamado pela interface.
        self._agendar(self._enviar_a_todos(mensagem))
        return any(par.conectado for par in self._pares.values())

    def _anunciar_estado(self) -> None:
        """Informa a todos o estado do microfone e do compartilhamento."""
        mensagem = {
            "tipo": "estado",
            "apelido": self._apelido,
            "microfone": self._microfone_ativo,
            "compartilhando": self._compartilhando,
        }
        self._agendar(self._enviar_a_todos(mensagem))

    async def _enviar_a_todos(self, mensagem: dict[str, Any]) -> None:
        """Envia uma mensagem de controle a todos os pares, dentro do laco."""
        for par in list(self._pares.values()):
            par.enviar_dados(mensagem)

    def _criar_faixa_microfone(self) -> FaixaMicrofone | None:
        """Cria a faixa do microfone, respeitando a configuracao de audio."""
        if not self._configuracoes.audio.ativo:
            return None
        faixa = FaixaMicrofone(self._configuracoes.audio.dispositivo_entrada)
        faixa.mudo = not self._microfone_ativo
        return faixa

    # -- Estatisticas -------------------------------------------------------

    async def _iniciar_estatisticas(self) -> None:
        """Liga a coleta periodica de estatisticas das conexoes."""
        if self._tarefa_estatisticas is not None:
            return
        self._tarefa_estatisticas = asyncio.create_task(self._laco_estatisticas())

    async def _laco_estatisticas(self) -> None:
        """Coleta e publica metricas agregadas da chamada."""
        while not self._encerrada:
            await asyncio.sleep(INTERVALO_ESTATISTICAS)
            if self._retornos.ao_estatisticas is None:
                continue
            agregado: dict[str, Any] = {
                "participantes": len(self._participantes),
                "conectados": sum(1 for par in self._pares.values() if par.conectado),
                "pares": {},
            }
            for identificador, par in list(self._pares.items()):
                with contextlib.suppress(Exception):
                    agregado["pares"][identificador] = await par.estatisticas()
            self._notificar(self._retornos.ao_estatisticas, agregado)

    # -- Encerramento -------------------------------------------------------

    async def _encerrar_tudo(self) -> None:
        """Fecha faixas, pares e sinalizacao na ordem segura."""
        if self._tarefa_estatisticas is not None:
            self._tarefa_estatisticas.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tarefa_estatisticas
            self._tarefa_estatisticas = None
        for par in list(self._pares.values()):
            par.enviar_dados({"tipo": "saindo"})
        if self._previa is not None:
            self._previa.parar()
            self._previa = None
        for consumidor in self._consumidores_video.values():
            consumidor.parar()
        self._consumidores_video.clear()
        for reprodutor in self._reprodutores.values():
            reprodutor.parar()
        self._reprodutores.clear()
        for identificador in list(self._pares):
            await self._remover_par(identificador)
        if self._faixa_tela is not None:
            self._faixa_tela.parar()
            self._faixa_tela = None
        if self._faixa_microfone is not None:
            self._faixa_microfone.parar()
            self._faixa_microfone = None
        if self._sinalizacao is not None:
            await self._sinalizacao.fechar()
            self._sinalizacao = None

    # -- Utilidades ---------------------------------------------------------

    def _publicar_participantes(self) -> None:
        """Envia a lista atual de participantes para a interface."""
        self._notificar(self._retornos.ao_participantes, self.participantes)

    @staticmethod
    def _notificar(retorno: Callable[..., None] | None, *argumentos: Any) -> None:
        """Chama um callback da interface protegendo contra excecoes."""
        if retorno is None:
            return
        try:
            retorno(*argumentos)
        except Exception as erro:  # pragma: no cover - protecao de callback
            _registrador.warning("Callback da chamada falhou: %s", erro)


@dataclass
class ResumoChamada:
    """Resumo textual usado pela interface e pelos testes."""

    sala: str
    participantes: list[Participante] = field(default_factory=list)
    compartilhando: bool = False

    def __str__(self) -> str:
        nomes = ", ".join(item.apelido for item in self.participantes)
        return f"Sala {self.sala} com {len(self.participantes)} participantes: {nomes}"
