"""Encapsulamento de uma conexão WebRTC com um único participante remoto."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from aiortc import (
    RTCConfiguration,
    RTCDataChannel,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.mediastreams import MediaStreamTrack
from aiortc.sdp import candidate_from_sdp

from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

TipoRetornoChamada = Any | Awaitable[Any]
TipoChamada = Callable[..., TipoRetornoChamada]


def montar_configuracao_ice(
    servidores_stun: list[str],
    turn_url: str = "",
    turn_usuario: str = "",
    turn_senha: str = "",
    forcar_relay: bool = False,
) -> RTCConfiguration:
    """Monta a configuração ICE com STUN e TURN opcionais."""
    servidores: list[RTCIceServer] = []
    if servidores_stun:
        servidores.append(RTCIceServer(urls=servidores_stun))
    if turn_url:
        servidores.append(
            RTCIceServer(
                urls=turn_url,
                username=turn_usuario or None,
                credential=turn_senha or None,
            )
        )
    configuracao = RTCConfiguration(iceServers=servidores)
    # aiortc 1.15 ainda não aplica esta política internamente, porém preservar o
    # valor no objeto permite que camadas superiores exibam a intenção do usuário.
    configuracao.iceTransportPolicy = "relay" if forcar_relay else "all"
    return configuracao


class ParRemoto:
    """Gerencia sinalização, mídia e dados de um único par WebRTC."""

    def __init__(
        self,
        id_par: str,
        apelido: str,
        configuracao_ice: RTCConfiguration,
        iniciador: bool,
        ao_sinal: TipoChamada,
        ao_faixa_video: TipoChamada,
        ao_faixa_audio: TipoChamada,
        ao_estado: TipoChamada,
        ao_mensagem_dados: TipoChamada,
        ao_encerrar: TipoChamada,
    ) -> None:
        """Inicializa o par e registra os eventos da conexão."""
        self.id_par = id_par
        self.apelido = apelido
        self.iniciador = iniciador
        self._ao_sinal = ao_sinal
        self._ao_faixa_video = ao_faixa_video
        self._ao_faixa_audio = ao_faixa_audio
        self._ao_estado = ao_estado
        self._ao_mensagem_dados = ao_mensagem_dados
        self._ao_encerrar = ao_encerrar
        self._pc = RTCPeerConnection(configuracao_ice)
        self._canal_dados: RTCDataChannel | None = None
        # Transceptores criados antes da oferta. Reservar as duas trilhas desde
        # o inicio permite comecar (ou trocar) a transmissao depois, apenas com
        # replaceTrack, sem uma nova negociacao - e o que evita "a chamada cai
        # quando alguem compartilha a tela".
        self._transceptores: dict[str, Any] = {}
        self._faixas_pendentes: dict[str, MediaStreamTrack] = {}
        self._fila_candidatos: list[dict[str, Any]] = []
        self._trava_sinal = asyncio.Lock()
        self._encerrado = False
        self._encerramento_notificado = False
        self._estatisticas_anteriores: dict[str, tuple[int, datetime]] = {}
        self._registrar_eventos()

    @property
    def conectado(self) -> bool:
        """Informa se a conexão alcançou o estado conectado."""
        return self._pc.connectionState == "connected"

    @property
    def estado(self) -> str:
        """Devolve o estado atual da conexão WebRTC."""
        return self._pc.connectionState

    async def iniciar(self) -> None:
        """Cria e envia a oferta inicial quando este par for o iniciador."""
        if self._encerrado:
            raise RuntimeError("Não é possível iniciar um par já encerrado.")
        if not self.iniciador:
            return
        if self._canal_dados is None:
            self._configurar_canal_dados(self._pc.createDataChannel("controle"))
        self._criar_transceptores()
        oferta = await self._pc.createOffer()
        await self._pc.setLocalDescription(oferta)
        await self._emitir_descricao_local("oferta")

    async def receber_sinal(self, dados: dict[str, Any]) -> None:
        """Aplica oferta, resposta ou candidato recebido pela sinalização."""
        if self._encerrado:
            return
        if not isinstance(dados, dict):
            raise ValueError("O sinal WebRTC deve ser um objeto.")

        async with self._trava_sinal:
            tipo = dados.get("tipo")
            if tipo == "oferta":
                await self._receber_oferta(dados)
            elif tipo == "resposta":
                await self._receber_resposta(dados)
            elif tipo == "candidato":
                await self._receber_candidato(dados)
            else:
                raise ValueError("O tipo de sinal WebRTC não é reconhecido.")

    async def definir_faixas(
        self,
        video: MediaStreamTrack | None = None,
        audio: MediaStreamTrack | None = None,
    ) -> None:
        """Define as faixas locais sem exigir uma nova negociação."""
        if video is not None:
            self._aplicar_faixa("video", video)
        if audio is not None:
            self._aplicar_faixa("audio", audio)

    async def remover_faixa_video(self) -> None:
        """Remove a fonte de vídeo preservando o transceptor existente."""
        self._faixas_pendentes.pop("video", None)
        transceptor = self._transceptores.get("video")
        if transceptor is not None:
            transceptor.sender.replaceTrack(None)

    def enviar_dados(self, objeto: dict[str, Any]) -> bool:
        """Envia um objeto JSON pelo canal de controle quando ele estiver aberto."""
        if self._canal_dados is None or self._canal_dados.readyState != "open":
            return False
        try:
            self._canal_dados.send(json.dumps(objeto, ensure_ascii=False))
        except (TypeError, ValueError) as erro:
            _registrador.warning("Não foi possível serializar dado para %s: %s", self.id_par, erro)
            return False
        return True

    async def estatisticas(self) -> dict[str, float | int | tuple[int, int] | None]:
        """Extrai bitrate, perdas, RTT e resolução das estatísticas WebRTC."""
        relatorio = await self._pc.getStats()
        bitrate = 0.0
        perdas = 0
        rtt: float | None = None
        resolucao: tuple[int, int] | None = None

        for identificador, item in relatorio.items():
            tipo = getattr(item, "type", "")
            if tipo in {"outbound-rtp", "inbound-rtp"}:
                perdas += int(getattr(item, "packetsLost", 0) or 0)
                largura = getattr(item, "frameWidth", None)
                altura = getattr(item, "frameHeight", None)
                if isinstance(largura, int) and isinstance(altura, int):
                    resolucao = (largura, altura)
                bitrate += self._calcular_bitrate(identificador, item)
            if tipo == "remote-inbound-rtp":
                valor_rtt = getattr(item, "roundTripTime", None)
                if isinstance(valor_rtt, (int, float)):
                    rtt = float(valor_rtt)

        return {
            "bitrate_estimado": bitrate,
            "pacotes_perdidos": perdas,
            "rtt": rtt,
            "resolucao": resolucao,
        }

    async def encerrar(self) -> None:
        """Fecha a conexão e notifica o chamador uma única vez."""
        if not self._encerrado:
            self._encerrado = True
            await self._pc.close()
        await self._avisar_encerramento()

    def _registrar_eventos(self) -> None:
        """Registra todos os callbacks expostos pelo RTCPeerConnection."""
        @self._pc.on("track")
        def ao_receber_faixa(faixa: MediaStreamTrack) -> None:
            if faixa.kind == "video":
                self._agendar_chamada(self._ao_faixa_video, faixa)
            elif faixa.kind == "audio":
                self._agendar_chamada(self._ao_faixa_audio, faixa)

        @self._pc.on("datachannel")
        def ao_receber_canal(canal: RTCDataChannel) -> None:
            self._configurar_canal_dados(canal)

        @self._pc.on("connectionstatechange")
        def ao_mudar_estado() -> None:
            self._agendar_chamada(self._ao_estado, self.estado)
            if self.estado == "failed":
                self._agendar_corrotina(self._avisar_encerramento())

    def _configurar_canal_dados(self, canal: RTCDataChannel) -> None:
        """Configura o canal de dados local ou recebido do outro participante."""
        self._canal_dados = canal

        @canal.on("message")
        def ao_receber_mensagem(mensagem: str | bytes) -> None:
            if isinstance(mensagem, bytes):
                try:
                    mensagem = mensagem.decode("utf-8")
                except UnicodeDecodeError:
                    _registrador.warning("Mensagem binária inválida recebida de %s", self.id_par)
                    return
            try:
                objeto = json.loads(mensagem)
            except (TypeError, ValueError):
                _registrador.warning("Mensagem JSON inválida recebida de %s", self.id_par)
                return
            if not isinstance(objeto, dict):
                _registrador.warning("Mensagem de %s não é um objeto JSON", self.id_par)
                return
            self._agendar_chamada(self._ao_mensagem_dados, objeto)

    async def _receber_oferta(self, dados: dict[str, Any]) -> None:
        """Define uma oferta remota e devolve uma resposta."""
        descricao = self._criar_descricao(dados, "offer")
        await self._pc.setRemoteDescription(descricao)
        self._registrar_transceptores()
        await self._aplicar_candidatos_em_fila()
        resposta = await self._pc.createAnswer()
        await self._pc.setLocalDescription(resposta)
        await self._emitir_descricao_local("resposta")

    async def _receber_resposta(self, dados: dict[str, Any]) -> None:
        """Define a resposta recebida pelo iniciador."""
        descricao = self._criar_descricao(dados, "answer")
        await self._pc.setRemoteDescription(descricao)
        await self._aplicar_candidatos_em_fila()

    async def _receber_candidato(self, dados: dict[str, Any]) -> None:
        """Aplica ou enfileira um candidato ICE que chegou antecipadamente."""
        if self._pc.remoteDescription is None:
            self._fila_candidatos.append(dados.copy())
            return
        await self._adicionar_candidato(dados)

    async def _aplicar_candidatos_em_fila(self) -> None:
        """Aplica candidatos recebidos antes da descrição remota."""
        candidatos = self._fila_candidatos
        self._fila_candidatos = []
        for candidato in candidatos:
            await self._adicionar_candidato(candidato)

    async def _adicionar_candidato(self, dados: dict[str, Any]) -> None:
        """Converte o candidato serializado para o formato aceito pelo aiortc."""
        sdp = dados.get("sdp")
        if sdp is None:
            await self._pc.addIceCandidate(None)
            return
        if not isinstance(sdp, str):
            raise ValueError("O candidato ICE não contém SDP válido.")
        texto_candidato = sdp.removeprefix("candidate:")
        candidato = candidate_from_sdp(texto_candidato)
        candidato.sdpMid = dados.get("sdpMid")
        candidato.sdpMLineIndex = dados.get("sdpMLineIndex")
        await self._pc.addIceCandidate(candidato)

    async def _emitir_descricao_local(self, tipo: str) -> None:
        """Envia descrição local e todos os candidatos reunidos por ela."""
        descricao = self._pc.localDescription
        if descricao is None:
            raise RuntimeError("A descrição local WebRTC não foi criada.")
        await self._chamar(self._ao_sinal, {"tipo": tipo, "sdp": descricao.sdp})
        for candidato in self._extrair_candidatos_locais(descricao.sdp):
            await self._chamar(self._ao_sinal, candidato)

    def _extrair_candidatos_locais(self, sdp: str) -> list[dict[str, Any]]:
        """Serializa os candidatos ICE presentes na descrição SDP local."""
        candidatos: list[dict[str, Any]] = []
        indice_linha_midia = -1
        identificador_midia: str | None = None
        for linha in sdp.splitlines():
            if linha.startswith("m="):
                indice_linha_midia += 1
                identificador_midia = None
            elif linha.startswith("a=mid:"):
                identificador_midia = linha[6:]
            elif linha.startswith("a=candidate:"):
                candidatos.append(
                    {
                        "tipo": "candidato",
                        "sdp": linha[2:],
                        "sdpMid": identificador_midia,
                        "sdpMLineIndex": indice_linha_midia,
                    }
                )
        candidatos.append(
            {
                "tipo": "candidato",
                "sdp": None,
                "sdpMid": None,
                "sdpMLineIndex": None,
            }
        )
        return candidatos

    def _criar_transceptores(self) -> None:
        """Reserva as trilhas de vídeo e áudio antes de criar a oferta."""
        for tipo in ("video", "audio"):
            if tipo in self._transceptores:
                continue
            self._transceptores[tipo] = self._pc.addTransceiver(tipo, direction="sendrecv")
        self._aplicar_faixas_pendentes()

    def _registrar_transceptores(self) -> None:
        """Localiza os transceptores criados pela oferta remota.

        Quem apenas responde a oferta recebe transceptores em "recvonly"; sem
        forcar "sendrecv" este lado nunca conseguiria transmitir a propria tela.
        """
        for transceptor in self._pc.getTransceivers():
            tipo = getattr(transceptor, "kind", "")
            if tipo not in {"video", "audio"}:
                continue
            if transceptor.direction != "sendrecv":
                transceptor.direction = "sendrecv"
            self._transceptores.setdefault(tipo, transceptor)
        self._aplicar_faixas_pendentes()

    def _aplicar_faixas_pendentes(self) -> None:
        """Publica as faixas que chegaram antes dos transceptores existirem."""
        for tipo in list(self._faixas_pendentes):
            faixa = self._faixas_pendentes.pop(tipo)
            self._aplicar_faixa(tipo, faixa)

    def _aplicar_faixa(self, tipo: str, faixa: MediaStreamTrack) -> None:
        """Troca a fonte de um transceptor, guardando a faixa se ele não existir."""
        if faixa.kind != tipo:
            raise ValueError(f"A faixa informada não é do tipo {tipo}.")
        transceptor = self._transceptores.get(tipo)
        if transceptor is None:
            self._faixas_pendentes[tipo] = faixa
            return
        transceptor.sender.replaceTrack(faixa)

    def _criar_descricao(
        self, dados: dict[str, Any], tipo_esperado: str
    ) -> RTCSessionDescription:
        """Valida e cria uma descrição de sessão recebida."""
        sdp = dados.get("sdp")
        if not isinstance(sdp, str) or not sdp:
            raise ValueError(f"A {tipo_esperado} WebRTC não contém SDP válido.")
        return RTCSessionDescription(sdp=sdp, type=tipo_esperado)

    def _calcular_bitrate(self, identificador: str, item: Any) -> float:
        """Calcula bitrate em bits por segundo desde a consulta anterior."""
        bytes_transferidos = getattr(item, "bytesSent", getattr(item, "bytesReceived", None))
        instante = getattr(item, "timestamp", None)
        if not isinstance(bytes_transferidos, int) or not isinstance(instante, datetime):
            return 0.0
        anterior = self._estatisticas_anteriores.get(identificador)
        self._estatisticas_anteriores[identificador] = (bytes_transferidos, instante)
        if anterior is None:
            return 0.0
        bytes_anteriores, instante_anterior = anterior
        intervalo = (instante - instante_anterior).total_seconds()
        if intervalo <= 0:
            return 0.0
        return max(0.0, (bytes_transferidos - bytes_anteriores) * 8 / intervalo)

    async def _avisar_encerramento(self) -> None:
        """Notifica o encerramento sem duplicar o callback."""
        if self._encerramento_notificado:
            return
        self._encerramento_notificado = True
        await self._chamar(self._ao_encerrar)

    async def _chamar(self, chamada: TipoChamada, *argumentos: Any) -> Any:
        """Executa callback síncrono ou assíncrono."""
        resultado = chamada(*argumentos)
        if inspect.isawaitable(resultado):
            return await resultado
        return resultado

    def _agendar_chamada(self, chamada: TipoChamada, *argumentos: Any) -> None:
        """Agenda callback de evento sem bloquear o emissor do aiortc."""
        self._agendar_corrotina(self._chamar(chamada, *argumentos))

    def _agendar_corrotina(self, corrotina: Awaitable[Any]) -> None:
        """Agenda corrotina de evento quando houver laço assíncrono em execução."""
        try:
            laco = asyncio.get_running_loop()
        except RuntimeError:
            return
        tarefa = laco.create_task(corrotina)
        tarefa.add_done_callback(self._registrar_erro_tarefa)

    def _registrar_erro_tarefa(self, tarefa: asyncio.Task[Any]) -> None:
        """Registra falha de callback sem interromper a conexão WebRTC."""
        if tarefa.cancelled():
            return
        erro = tarefa.exception()
        if erro is not None:
            _registrador.exception("Falha em callback do par %s", self.id_par, exc_info=erro)
