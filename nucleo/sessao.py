"""Sessão de mídia: orquestra as threads de vídeo, áudio, chat e keep-alive.

A mesma classe é usada pelo servidor (host) e pelo cliente (espectador). A
diferença é o parâmetro ``transmitir_video``: apenas o host captura e envia a
tela. O áudio é bidirecional, permitindo conversa nos dois sentidos.

Todos os retornos para a camada de interface acontecem por *callbacks*, que
são executados nas threads de trabalho - a interface é responsável por
enfileirar as atualizações na thread principal.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from configuracao.configuracoes import Configuracoes
from midia.captura_audio import (
    MOTIVO_AUDIO_INDISPONIVEL,
    CapturadorAudio,
    ErroAudio,
    ReprodutorAudio,
)
from midia.captura_tela import CapturadorTela, ErroCapturaTela
from midia.compressao import ControladorQualidade, ErroCompressao, comprimir_jpeg
from nucleo.conexao import Conexao, ConexaoEncerrada
from nucleo.protocolo import (
    ErroProtocolo,
    TipoMensagem,
    agora_ms,
    codificar_json,
    decodificar_json,
    mensagem_chat,
)
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)


@dataclass
class Estatisticas:
    """Métricas em tempo real da sessão."""

    fps_envio: float = 0.0
    fps_recepcao: float = 0.0
    latencia_ms: float = 0.0
    qualidade: int = 0
    taxa_envio: float = 0.0  # bytes por segundo
    taxa_recepcao: float = 0.0  # bytes por segundo
    quadros_enviados: int = 0
    quadros_recebidos: int = 0
    quadros_descartados: int = 0
    audio_ativo: bool = False


@dataclass
class Retornos:
    """Conjunto de callbacks opcionais consumidos pela interface."""

    ao_video: Callable[[bytes], None] | None = None
    ao_chat: Callable[[dict], None] | None = None
    ao_estado: Callable[[dict], None] | None = None
    ao_estatisticas: Callable[[Estatisticas], None] | None = None
    ao_encerrar: Callable[[str], None] | None = None
    ao_erro: Callable[[str], None] | None = None


class Sessao:
    """Gerencia o fluxo de dados de uma conexão já estabelecida."""

    def __init__(
        self,
        conexao: Conexao,
        configuracoes: Configuracoes,
        transmitir_video: bool,
        apelido: str,
        retornos: Retornos | None = None,
    ) -> None:
        self.conexao = conexao
        self.configuracoes = configuracoes
        self.transmitir_video = transmitir_video
        self.apelido = apelido
        self.retornos = retornos or Retornos()

        self.estatisticas = Estatisticas(qualidade=configuracoes.video.qualidade_jpeg)
        #: Controla o envio do próprio microfone (botão "mudo").
        self.microfone_ativo = configuracoes.audio.ativo
        #: Controla a reprodução do áudio recebido (botão "desativar som").
        #: Como no Discord, silenciar a saída é independente de silenciar o
        #: microfone; os pacotes continuam chegando, apenas são descartados.
        self.som_ativo = True

        self._ativa = False
        self._encerrando = threading.Event()
        self._threads: list[threading.Thread] = []
        self._reprodutor: ReprodutorAudio | None = None
        self._controlador = ControladorQualidade(
            qualidade_inicial=configuracoes.video.qualidade_jpeg,
            qualidade_minima=configuracoes.video.qualidade_minima,
            qualidade_maxima=configuracoes.video.qualidade_maxima,
            habilitado=configuracoes.video.compressao_adaptativa,
        )
        self._contador_envio = 0
        self._contador_recepcao = 0
        self._motivo_encerramento = ""

    # -- Propriedades -------------------------------------------------------

    @property
    def ativa(self) -> bool:
        """``True`` enquanto a sessão está transmitindo/recebendo."""
        return self._ativa

    # -- Ciclo de vida ------------------------------------------------------

    def iniciar(self) -> None:
        """Inicia todas as threads de trabalho da sessão."""
        if self._ativa:
            return
        self._ativa = True
        self._encerrando.clear()

        self._iniciar_reproducao_audio()

        self._criar_thread(self._laco_recepcao, "recepcao")
        self._criar_thread(self._laco_ping, "ping")
        self._criar_thread(self._laco_estatisticas, "estatisticas")
        if self.transmitir_video:
            self._criar_thread(self._laco_video, "envio-video")
        if self.configuracoes.audio.ativo:
            self._criar_thread(self._laco_audio, "envio-audio")

        _registrador.info(
            "Sessão iniciada (vídeo=%s, áudio=%s)",
            self.transmitir_video,
            self.configuracoes.audio.ativo,
        )

    def _criar_thread(self, alvo: Callable[[], None], nome: str) -> None:
        thread = threading.Thread(target=alvo, name=nome, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _iniciar_reproducao_audio(self) -> None:
        """Tenta abrir a saída de áudio; falhas não interrompem a sessão."""
        if not self.configuracoes.audio.ativo:
            return
        reprodutor = ReprodutorAudio(self.configuracoes.audio)
        if not reprodutor.disponivel:
            self._notificar_erro(f"Áudio indisponível: {MOTIVO_AUDIO_INDISPONIVEL}")
            return
        try:
            reprodutor.iniciar()
            self._reprodutor = reprodutor
            self.estatisticas.audio_ativo = True
        except ErroAudio as erro:
            self._notificar_erro(f"Saída de áudio indisponível: {erro}")

    def encerrar(self, motivo: str = "Sessão encerrada", notificar: bool = True) -> None:
        """Encerra a sessão, avisando o outro lado quando possível."""
        if self._encerrando.is_set():
            return
        self._encerrando.set()
        self._ativa = False
        self._motivo_encerramento = motivo

        if notificar and self.conexao.aberta:
            try:
                self.conexao.enviar_json(TipoMensagem.ENCERRAR, {"motivo": motivo})
            except ConexaoEncerrada:
                pass

        self.conexao.fechar()

        if self._reprodutor is not None:
            self._reprodutor.parar()
            self._reprodutor = None

        if self.retornos.ao_encerrar:
            self.retornos.ao_encerrar(motivo)
        _registrador.info("Sessão encerrada: %s", motivo)

    def aguardar_encerramento(self, tempo_limite: float | None = None) -> None:
        """Bloqueia até que a sessão seja encerrada."""
        self._encerrando.wait(tempo_limite)

    # -- Envio de dados -----------------------------------------------------

    def enviar_chat(self, texto: str) -> bool:
        """Envia uma mensagem de chat. Devolve ``False`` em caso de falha."""
        texto = (texto or "").strip()
        if not texto:
            return False
        try:
            self.conexao.enviar(TipoMensagem.CHAT, mensagem_chat(self.apelido, texto))
            return True
        except ConexaoEncerrada as erro:
            self.encerrar(f"Conexão perdida ao enviar mensagem: {erro}", notificar=False)
            return False

    def alternar_microfone(self) -> bool:
        """Ativa/desativa o envio de áudio e devolve o novo estado."""
        self.microfone_ativo = not self.microfone_ativo
        self._enviar_estado({"microfone": self.microfone_ativo})
        return self.microfone_ativo

    def alternar_som(self) -> bool:
        """Ativa/desativa a reprodução do áudio recebido e devolve o estado."""
        self.som_ativo = not self.som_ativo
        self.estatisticas.audio_ativo = self.som_ativo and self._reprodutor is not None
        return self.som_ativo

    def _enviar_estado(self, dados: dict) -> None:
        """Informa o outro lado sobre mudanças de estado (mudo, resolução...)."""
        try:
            self.conexao.enviar(
                TipoMensagem.ESTADO, codificar_json({"apelido": self.apelido, **dados})
            )
        except ConexaoEncerrada:
            pass

    # -- Laços de trabalho --------------------------------------------------

    def _laco_recepcao(self) -> None:
        """Recebe e despacha todas as mensagens vindas do outro lado."""
        while not self._encerrando.is_set():
            try:
                tipo, carga = self.conexao.receber()
            except ConexaoEncerrada as erro:
                self.encerrar(f"Conexão encerrada: {erro}", notificar=False)
                return
            except ErroProtocolo as erro:
                self.encerrar(f"Erro de protocolo: {erro}", notificar=False)
                return

            try:
                self._despachar(tipo, carga)
            except Exception as erro:  # nunca deixar a thread morrer silenciosa
                _registrador.exception("Falha ao processar mensagem %s: %s", tipo, erro)

    def _despachar(self, tipo: TipoMensagem, carga: bytes) -> None:
        """Encaminha uma mensagem recebida para o tratamento adequado."""
        if tipo is TipoMensagem.VIDEO:
            self._contador_recepcao += 1
            self.estatisticas.quadros_recebidos += 1
            if self.retornos.ao_video:
                self.retornos.ao_video(carga)

        elif tipo is TipoMensagem.AUDIO:
            # Quando o som está desativado o bloco é simplesmente descartado:
            # é mais barato que renegociar a transmissão e mantém a reativação
            # instantânea.
            if self._reprodutor is not None and self.som_ativo:
                self._reprodutor.escrever(carga)

        elif tipo is TipoMensagem.CHAT:
            if self.retornos.ao_chat:
                self.retornos.ao_chat(decodificar_json(carga))

        elif tipo is TipoMensagem.PING:
            try:
                self.conexao.enviar(TipoMensagem.PONG, carga)
            except ConexaoEncerrada:
                pass

        elif tipo is TipoMensagem.PONG:
            dados = decodificar_json(carga)
            enviado_em = float(dados.get("t", 0))
            latencia = max(0.0, agora_ms() - enviado_em)
            self.estatisticas.latencia_ms = latencia
            self.estatisticas.qualidade = self._controlador.registrar_latencia(latencia)

        elif tipo is TipoMensagem.ESTADO:
            if self.retornos.ao_estado:
                self.retornos.ao_estado(decodificar_json(carga))

        elif tipo is TipoMensagem.ENCERRAR:
            dados = decodificar_json(carga)
            self.encerrar(
                dados.get("motivo", "O outro participante encerrou a sessão"),
                notificar=False,
            )

    def _laco_video(self) -> None:
        """Captura, comprime e envia quadros respeitando o FPS configurado."""
        capturador = CapturadorTela(self.configuracoes.video)
        try:
            capturador.abrir()
        except ErroCapturaTela as erro:
            self._notificar_erro(str(erro))
            self.encerrar(f"Captura de tela indisponível: {erro}")
            return

        try:
            while not self._encerrando.is_set():
                inicio = time.perf_counter()
                try:
                    quadro = capturador.capturar()
                    if self._controlador.deve_descartar_quadro():
                        self.estatisticas.quadros_descartados += 1
                    else:
                        dados = comprimir_jpeg(quadro, self._controlador.qualidade)
                        self.conexao.enviar(TipoMensagem.VIDEO, dados)
                        self._contador_envio += 1
                        self.estatisticas.quadros_enviados += 1
                except ConexaoEncerrada as erro:
                    self.encerrar(f"Conexão perdida no envio de vídeo: {erro}", notificar=False)
                    return
                except (ErroCapturaTela, ErroCompressao) as erro:
                    _registrador.warning("Quadro perdido: %s", erro)
                    time.sleep(0.05)

                espera = self.configuracoes.video.intervalo_quadro - (
                    time.perf_counter() - inicio
                )
                if espera > 0:
                    self._encerrando.wait(espera)
        finally:
            capturador.fechar()

    def _laco_audio(self) -> None:
        """Captura o microfone e transmite blocos PCM continuamente."""
        capturador = CapturadorAudio(self.configuracoes.audio)
        if not capturador.disponivel:
            return
        try:
            capturador.abrir()
        except ErroAudio as erro:
            self._notificar_erro(f"Microfone indisponível: {erro}")
            return

        try:
            while not self._encerrando.is_set():
                try:
                    bloco = capturador.ler()
                except ErroAudio as erro:
                    self._notificar_erro(f"Erro no microfone: {erro}")
                    return
                if not self.microfone_ativo:
                    continue
                try:
                    self.conexao.enviar(TipoMensagem.AUDIO, bloco)
                except ConexaoEncerrada:
                    return
        finally:
            capturador.fechar()

    def _laco_ping(self) -> None:
        """Envia PING periódico para medir latência e detectar quedas."""
        intervalo = max(1.0, self.configuracoes.rede.intervalo_ping)
        while not self._encerrando.is_set():
            try:
                self.conexao.enviar(TipoMensagem.PING, codificar_json({"t": agora_ms()}))
            except ConexaoEncerrada:
                return
            self._encerrando.wait(intervalo)

    def _laco_estatisticas(self) -> None:
        """Calcula FPS e taxas de transferência uma vez por segundo."""
        ultimo_enviados = self.conexao.bytes_enviados
        ultimo_recebidos = self.conexao.bytes_recebidos
        while not self._encerrando.is_set():
            self._encerrando.wait(1.0)
            if self._encerrando.is_set():
                return
            self.estatisticas.fps_envio = float(self._contador_envio)
            self.estatisticas.fps_recepcao = float(self._contador_recepcao)
            self._contador_envio = 0
            self._contador_recepcao = 0
            self.estatisticas.taxa_envio = float(
                self.conexao.bytes_enviados - ultimo_enviados
            )
            self.estatisticas.taxa_recepcao = float(
                self.conexao.bytes_recebidos - ultimo_recebidos
            )
            ultimo_enviados = self.conexao.bytes_enviados
            ultimo_recebidos = self.conexao.bytes_recebidos
            self.estatisticas.qualidade = self._controlador.qualidade
            if self.retornos.ao_estatisticas:
                self.retornos.ao_estatisticas(self.estatisticas)

    # -- Auxiliares ---------------------------------------------------------

    def _notificar_erro(self, mensagem: str) -> None:
        """Repassa um aviso não fatal para a interface e para o log."""
        _registrador.warning(mensagem)
        if self.retornos.ao_erro:
            self.retornos.ao_erro(mensagem)
