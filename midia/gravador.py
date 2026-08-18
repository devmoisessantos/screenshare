"""Gravação local e buffer circular de clipes usando PyAV.

O :class:`BufferClipes` mantém os quadros como JPEGs, em vez de ``ndarray``
BGR descomprimidos. Em 720p, um quadro BGR ocuparia cerca de 2,64 MiB; 5
minutos a 30 fps consumiriam aproximadamente 23,2 GiB só de vídeo. Com JPEG
(qualidade 80), uma estimativa conservadora de 250 KiB por quadro reduz o
vídeo para cerca de 2,15 GiB, mais aproximadamente 27,5 MiB de áudio PCM mono
48 kHz. O consumo real pode ser consultado em ``memoria_estimada_bytes`` e
varia conforme o conteúdo da tela.
"""

from __future__ import annotations

import os
import threading
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np

from midia.compressao import comprimir_jpeg, descomprimir_jpeg
from utilitarios.registro import obter_registrador

try:
    import av
except Exception as erro_importacao:  # pragma: no cover - depende do ambiente
    av: Any = None
    AV_DISPONIVEL = False
    MOTIVO_AV_INDISPONIVEL = str(erro_importacao)
else:
    AV_DISPONIVEL = True
    MOTIVO_AV_INDISPONIVEL = ""

_registrador = obter_registrador(__name__)

_LAYOUTS_AUDIO = {1: "mono", 2: "stereo"}
_BYTES_POR_AMOSTRA = 2


class ErroGravacao(Exception):
    """Falha ao preparar ou escrever uma gravação local."""


def _pasta_padrao() -> Path:
    """Calcula a pasta padrão sem criá-la antecipadamente."""
    if os.name == "nt":
        return Path.home() / "Videos" / "ScreenShare"
    return Path.home() / "Videos" / "ScreenShare"


@dataclass
class ConfiguracaoGravacao:
    """Parâmetros da gravação local e do buffer de clipes."""

    pasta: Path = field(default_factory=_pasta_padrao)
    fps: int = 30
    #: FPS e qualidade JPEG usados somente no buffer de clipes, reduzidos de
    #: proposito para manter o consumo de RAM em poucas centenas de MiB.
    fps_buffer: int = 15
    qualidade_buffer: int = 55
    taxa_bits: int = 4_000_000
    codec: str = "libx264"
    taxa_audio: int = 48000
    canais_audio: int = 1
    segundos_buffer: int = 120


class _CodificadorMp4:
    """Encapsula o muxador PyAV, usado sob o bloqueio de quem o possui."""

    def __init__(
        self,
        caminho: Path,
        configuracao: ConfiguracaoGravacao,
        largura: int,
        altura: int,
    ) -> None:
        if not AV_DISPONIVEL:
            raise ErroGravacao(f"PyAV indisponível: {MOTIVO_AV_INDISPONIVEL}")
        if largura <= 0 or altura <= 0:
            raise ErroGravacao("A resolução da gravação deve ser positiva")
        if configuracao.fps <= 0 or configuracao.taxa_audio <= 0:
            raise ErroGravacao("FPS e taxa de áudio devem ser positivos")
        if configuracao.canais_audio not in _LAYOUTS_AUDIO:
            raise ErroGravacao("A gravação aceita áudio mono ou estéreo")

        self.caminho = caminho
        self.configuracao = configuracao
        self.largura = largura
        self.altura = altura
        self._codec_video = _escolher_codec(configuracao.codec)
        self._saida = av.open(str(caminho), mode="w", format="mp4")
        try:
            self._video = self._saida.add_stream(self._codec_video, rate=configuracao.fps)
            self._video.width = largura
            self._video.height = altura
            self._video.pix_fmt = "yuv420p"
            self._video.bit_rate = configuracao.taxa_bits
            if self._codec_video == "libx264":
                self._video.options = {"preset": "veryfast", "crf": "23"}

            self._audio = self._saida.add_stream("aac", rate=configuracao.taxa_audio)
            self._audio.layout = _LAYOUTS_AUDIO[configuracao.canais_audio]
            self._audio.bit_rate = 128_000
        except Exception as erro:
            self._saida.close()
            raise ErroGravacao(f"Não foi possível configurar os codecs: {erro}") from erro

        self._quadros_video = 0
        self._amostras_audio = 0
        self._fechado = False

    @property
    def duracao(self) -> float:
        """Duração estimada a partir das amostras entregues ao codificador."""
        duracao_video = self._quadros_video / self.configuracao.fps
        duracao_audio = self._amostras_audio / self.configuracao.taxa_audio
        return max(duracao_video, duracao_audio)

    def escrever_video(self, quadro_bgr: np.ndarray) -> None:
        """Codifica um quadro BGR e o envia ao fluxo de vídeo."""
        if self._fechado:
            return
        _validar_quadro(quadro_bgr, self.largura, self.altura)
        quadro = av.VideoFrame.from_ndarray(quadro_bgr, format="bgr24")
        quadro.pts = self._quadros_video
        for pacote in self._video.encode(quadro):
            self._saida.mux(pacote)
        self._quadros_video += 1

    def escrever_audio(self, bloco_int16: bytes | np.ndarray) -> None:
        """Codifica PCM int16 intercalado e o envia ao fluxo de áudio."""
        if self._fechado:
            return
        amostras = _normalizar_audio(bloco_int16, self.configuracao.canais_audio)
        if not amostras.size:
            return
        plano = np.ascontiguousarray(amostras.T)
        quadro = av.AudioFrame.from_ndarray(
            plano,
            format="s16p",
            layout=_LAYOUTS_AUDIO[self.configuracao.canais_audio],
        )
        quadro.sample_rate = self.configuracao.taxa_audio
        quadro.pts = self._amostras_audio
        for pacote in self._audio.encode(quadro):
            self._saida.mux(pacote)
        self._amostras_audio += quadro.samples

    def fechar(self) -> None:
        """Drena os codificadores e fecha o contêiner MP4."""
        if self._fechado:
            return
        try:
            for pacote in self._video.encode():
                self._saida.mux(pacote)
            for pacote in self._audio.encode():
                self._saida.mux(pacote)
        finally:
            self._fechado = True
            self._saida.close()


def _escolher_codec(codec_solicitado: str) -> str:
    """Escolhe libx264 quando existente, com alternativa mpeg4 automática."""
    if not AV_DISPONIVEL:
        raise ErroGravacao(f"PyAV indisponível: {MOTIVO_AV_INDISPONIVEL}")
    codecs = av.codecs_available
    if codec_solicitado == "libx264" and "libx264" not in codecs:
        _registrador.warning("libx264 ausente no PyAV; usando mpeg4")
        return "mpeg4"
    if codec_solicitado in codecs:
        return codec_solicitado
    if "mpeg4" in codecs:
        _registrador.warning("Codec %s indisponível; usando mpeg4", codec_solicitado)
        return "mpeg4"
    raise ErroGravacao("Nenhum codec de vídeo compatível está disponível")


def _validar_quadro(quadro: np.ndarray, largura: int, altura: int) -> None:
    """Confere que um quadro é BGR uint8 na resolução aberta."""
    if not isinstance(quadro, np.ndarray):
        raise ErroGravacao("O quadro de vídeo deve ser um numpy.ndarray")
    if quadro.dtype != np.uint8 or quadro.ndim != 3 or quadro.shape[2] != 3:
        raise ErroGravacao("O quadro de vídeo deve ser BGR uint8 com três canais")
    if quadro.shape[:2] != (altura, largura):
        raise ErroGravacao("A resolução do quadro mudou durante a gravação")


def _normalizar_audio(bloco: bytes | np.ndarray, canais: int) -> np.ndarray:
    """Converte PCM int16 intercalado em matriz de amostras por canal."""
    if isinstance(bloco, bytes):
        if len(bloco) % (_BYTES_POR_AMOSTRA * canais):
            raise ErroGravacao("O bloco de áudio não termina em uma amostra completa")
        dados = np.frombuffer(bloco, dtype=np.int16)
    elif isinstance(bloco, np.ndarray):
        if bloco.dtype != np.int16:
            raise ErroGravacao("O bloco de áudio deve usar amostras int16")
        dados = bloco
    else:
        raise ErroGravacao("O bloco de áudio deve ser bytes ou numpy.ndarray")

    if dados.ndim == 1:
        if dados.size % canais:
            raise ErroGravacao("O bloco de áudio não contém todos os canais")
        return np.ascontiguousarray(dados.reshape(-1, canais))
    if dados.ndim == 2 and dados.shape[1] == canais:
        return np.ascontiguousarray(dados)
    if dados.ndim == 2 and dados.shape[0] == canais:
        return np.ascontiguousarray(dados.T)
    raise ErroGravacao("O formato do bloco de áudio não corresponde aos canais configurados")


def _nome_arquivo(prefixo: str) -> str:
    """Gera o nome padronizado de uma gravação ou clipe."""
    instante = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{prefixo}_{instante}.mp4"


class Gravador:
    """Grava continuamente vídeo BGR e áudio PCM int16 em um arquivo MP4."""

    def __init__(self, configuracao: ConfiguracaoGravacao | None = None) -> None:
        self.configuracao = configuracao or ConfiguracaoGravacao()
        self._bloqueio = threading.RLock()
        self._codificador: _CodificadorMp4 | None = None
        self._caminho: Path | None = None
        self._duracao_final = 0.0

    @property
    def gravando(self) -> bool:
        """Indica se o arquivo de gravação está aberto."""
        with self._bloqueio:
            return self._codificador is not None

    @property
    def duracao(self) -> float:
        """Duração estimada da mídia já entregue ao gravador, em segundos."""
        with self._bloqueio:
            return self._codificador.duracao if self._codificador else self._duracao_final

    @property
    def caminho(self) -> Path | None:
        """Caminho do arquivo atual ou do último arquivo criado."""
        with self._bloqueio:
            return self._caminho

    @property
    def tamanho_bytes(self) -> int:
        """Tamanho atual do arquivo no disco, quando ele já existe."""
        with self._bloqueio:
            if self._caminho is None:
                return 0
            try:
                return self._caminho.stat().st_size
            except OSError:
                return 0

    def iniciar(self, largura: int, altura: int) -> Path:
        """Abre uma nova gravação e devolve seu caminho."""
        with self._bloqueio:
            if self._codificador is not None and self._caminho is not None:
                return self._caminho
            self.configuracao.pasta.mkdir(parents=True, exist_ok=True)
            caminho = self.configuracao.pasta / _nome_arquivo("gravacao")
            self._codificador = _CodificadorMp4(caminho, self.configuracao, largura, altura)
            self._caminho = caminho
            self._duracao_final = 0.0
            _registrador.info("Gravação iniciada em %s", caminho)
            return caminho

    def escrever_video(self, quadro_bgr: np.ndarray) -> None:
        """Adiciona um quadro de vídeo, de forma segura entre threads."""
        with self._bloqueio:
            if self._codificador is not None:
                self._codificador.escrever_video(quadro_bgr)

    def escrever_audio(self, bloco_int16: bytes | np.ndarray) -> None:
        """Adiciona um bloco de áudio, de forma segura entre threads."""
        with self._bloqueio:
            if self._codificador is not None:
                self._codificador.escrever_audio(bloco_int16)

    def parar(self) -> Path | None:
        """Fecha a gravação atual e devolve o caminho finalizado."""
        with self._bloqueio:
            if self._codificador is None:
                return None
            codificador, caminho = self._codificador, self._caminho
            try:
                codificador.fechar()
            finally:
                self._duracao_final = codificador.duracao
                self._codificador = None
            _registrador.info("Gravação finalizada em %s", caminho)
            return caminho


class BufferClipes:
    """Mantém JPEGs e PCM recentes em memória para exportar os últimos segundos.

    Os quadros são JPEG comprimidos com qualidade 80, decisão que reduz muito a
    RAM frente aos BGR crus. Consulte a documentação do módulo para uma
    estimativa de 5 minutos em 720p e ``memoria_estimada_bytes`` para o valor
    efetivamente ocupado pelos dados armazenados.
    """

    def __init__(self, configuracao: ConfiguracaoGravacao | None = None) -> None:
        self.configuracao = configuracao or ConfiguracaoGravacao()
        if self.fps_efetivo <= 0 or self.configuracao.segundos_buffer <= 0:
            raise ErroGravacao("FPS e duração do buffer devem ser positivos")
        self._bloqueio = threading.RLock()
        self._quadros: deque[bytes] = deque(
            maxlen=self.fps_efetivo * self.configuracao.segundos_buffer
        )
        self._blocos_audio: deque[bytes] = deque()
        self._bytes_video = 0
        self._bytes_audio = 0
        self._largura: int | None = None
        self._altura: int | None = None
        # Contador de decimacao: a captura entrega no FPS cheio, mas o buffer
        # guarda apenas 1 de cada N quadros para respeitar o fps_buffer.
        self._passo = max(1, round(self.configuracao.fps / self.fps_efetivo))
        self._contador_quadros = 0

    @property
    def fps_efetivo(self) -> int:
        """FPS realmente aplicado ao buffer, sem passar do FPS da captura."""
        return max(1, min(self.configuracao.fps_buffer, self.configuracao.fps))

    @property
    def segundos_disponiveis(self) -> float:
        """Quantidade de vídeo armazenada, limitada ao tamanho circular."""
        with self._bloqueio:
            return len(self._quadros) / self.fps_efetivo

    @property
    def memoria_estimada_bytes(self) -> int:
        """Total dos JPEGs e PCM armazenados, sem a sobrecarga dos objetos Python."""
        with self._bloqueio:
            return self._bytes_video + self._bytes_audio

    def configurar(self, largura: int, altura: int) -> None:
        """Define a resolução esperada antes da chegada do primeiro quadro."""
        if largura <= 0 or altura <= 0:
            raise ErroGravacao("A resolução do buffer deve ser positiva")
        with self._bloqueio:
            self._largura = largura
            self._altura = altura

    def alimentar_video(self, quadro_bgr: np.ndarray) -> None:
        """Comprime e guarda um quadro BGR no buffer circular."""
        if not isinstance(quadro_bgr, np.ndarray):
            raise ErroGravacao("O quadro de vídeo deve ser um numpy.ndarray")
        if quadro_bgr.dtype != np.uint8 or quadro_bgr.ndim != 3 or quadro_bgr.shape[2] != 3:
            raise ErroGravacao("O quadro de vídeo deve ser BGR uint8 com três canais")
        with self._bloqueio:
            indice = self._contador_quadros
            self._contador_quadros += 1
        if indice % self._passo:
            return
        altura, largura = quadro_bgr.shape[:2]
        jpeg = comprimir_jpeg(quadro_bgr, self.configuracao.qualidade_buffer)
        with self._bloqueio:
            if self._largura is None:
                self._largura, self._altura = largura, altura
            elif (largura, altura) != (self._largura, self._altura):
                raise ErroGravacao("A resolução do quadro mudou durante o buffer")
            if len(self._quadros) == self._quadros.maxlen:
                self._bytes_video -= len(self._quadros[0])
            self._quadros.append(jpeg)
            self._bytes_video += len(jpeg)

    def alimentar_audio(self, bloco: bytes | np.ndarray) -> None:
        """Guarda PCM int16 recente, respeitando a janela temporal do buffer."""
        amostras = _normalizar_audio(bloco, self.configuracao.canais_audio)
        if not amostras.size:
            return
        dados = np.ascontiguousarray(amostras).tobytes()
        limite = (
            self.configuracao.segundos_buffer
            * self.configuracao.taxa_audio
            * self.configuracao.canais_audio
            * _BYTES_POR_AMOSTRA
        )
        with self._bloqueio:
            self._blocos_audio.append(dados)
            self._bytes_audio += len(dados)
            while (
                self._blocos_audio
                and self._bytes_audio > limite
                and self._bytes_audio - len(self._blocos_audio[0]) >= limite
            ):
                removido = self._blocos_audio.popleft()
                self._bytes_audio -= len(removido)
            if self._blocos_audio and self._bytes_audio > limite:
                excesso = self._bytes_audio - limite
                primeiro = self._blocos_audio.popleft()
                restante = primeiro[excesso:]
                self._blocos_audio.appendleft(restante)
                self._bytes_audio -= excesso

    def salvar_clipe(self, segundos: int) -> Path | None:
        """Escreve os últimos ``segundos`` em MP4 sem pausar o buffer."""
        if segundos <= 0:
            return None
        with self._bloqueio:
            quantidade = min(len(self._quadros), segundos * self.fps_efetivo)
            if not quantidade or self._largura is None or self._altura is None:
                return None
            quadros = list(self._quadros)[-quantidade:]
            audio = _ultimos_bytes_audio(
                self._blocos_audio,
                segundos,
                self.configuracao.taxa_audio,
                self.configuracao.canais_audio,
            )
            largura, altura = self._largura, self._altura

        if not AV_DISPONIVEL:
            _registrador.warning("Não foi possível salvar clipe: %s", MOTIVO_AV_INDISPONIVEL)
            return None
        self.configuracao.pasta.mkdir(parents=True, exist_ok=True)
        caminho = self.configuracao.pasta / _nome_arquivo("clipe")
        configuracao_clipe = replace(self.configuracao, fps=self.fps_efetivo)
        codificador = _CodificadorMp4(caminho, configuracao_clipe, largura, altura)
        try:
            for jpeg in quadros:
                codificador.escrever_video(descomprimir_jpeg(jpeg))
            if audio:
                codificador.escrever_audio(audio)
        finally:
            codificador.fechar()
        _registrador.info("Clipe salvo em %s", caminho)
        return caminho

    def limpar(self) -> None:
        """Remove todos os dados mantidos no buffer circular."""
        with self._bloqueio:
            self._quadros.clear()
            self._blocos_audio.clear()
            self._bytes_video = 0
            self._bytes_audio = 0
            self._largura = None
            self._altura = None
            self._contador_quadros = 0


def _ultimos_bytes_audio(
    blocos: deque[bytes], segundos: int, taxa_audio: int, canais_audio: int
) -> bytes:
    """Extrai do fim dos blocos somente a quantidade de PCM solicitada."""
    desejado = segundos * taxa_audio * canais_audio * _BYTES_POR_AMOSTRA
    if not desejado or not blocos:
        return b""
    selecionados: list[bytes] = []
    restante = desejado
    for bloco in reversed(blocos):
        if restante <= 0:
            break
        selecionados.append(bloco[-restante:])
        restante -= len(bloco)
    return b"".join(reversed(selecionados))


def _ignorar_mensagem(_: str) -> None:
    """Callback padrão para uma fachada usada sem interface conectada."""


class GerenciadorGravacao:
    """Fachada tolerante a falhas para a interface controlar gravações e clipes."""

    def __init__(
        self,
        configuracao: ConfiguracaoGravacao | None = None,
        ao_evento: Callable[[str], None] | None = None,
        ao_erro: Callable[[str], None] | None = None,
    ) -> None:
        self.configuracao = configuracao or ConfiguracaoGravacao()
        self.ao_evento = ao_evento or _ignorar_mensagem
        self.ao_erro = ao_erro or _ignorar_mensagem
        self._gravador = Gravador(self.configuracao)
        self._buffer: BufferClipes | None = None
        self._largura: int | None = None
        self._altura: int | None = None
        self._bloqueio = threading.RLock()

    def ativar_buffer(self, largura: int, altura: int) -> None:
        """Ativa um novo buffer circular na resolução informada."""
        try:
            buffer = BufferClipes(self.configuracao)
            buffer.configurar(largura, altura)
            with self._bloqueio:
                self._buffer = buffer
                self._largura, self._altura = largura, altura
            self._emitir_evento("Buffer de clipes ativado")
        except Exception as erro:
            self._emitir_erro(f"Não foi possível ativar o buffer: {erro}")

    def desativar_buffer(self) -> None:
        """Desativa e limpa o buffer de clipes atual."""
        try:
            with self._bloqueio:
                buffer, self._buffer = self._buffer, None
            if buffer is not None:
                buffer.limpar()
            self._emitir_evento("Buffer de clipes desativado")
        except Exception as erro:
            self._emitir_erro(f"Não foi possível desativar o buffer: {erro}")

    def iniciar_gravacao(self) -> Path | None:
        """Inicia a gravação contínua sem propagar erros para a interface."""
        try:
            with self._bloqueio:
                largura, altura = self._largura, self._altura
            if largura is None or altura is None:
                raise ErroGravacao("Ative o buffer ou entregue um quadro antes de gravar")
            caminho = self._gravador.iniciar(largura, altura)
            self._emitir_evento(f"Gravação iniciada: {caminho}")
            return caminho
        except Exception as erro:
            self._emitir_erro(f"Não foi possível iniciar a gravação: {erro}")
            return None

    def parar_gravacao(self) -> Path | None:
        """Finaliza a gravação contínua sem propagar erros para a interface."""
        try:
            caminho = self._gravador.parar()
            if caminho is not None:
                self._emitir_evento(f"Gravação salva: {caminho}")
            return caminho
        except Exception as erro:
            self._emitir_erro(f"Não foi possível finalizar a gravação: {erro}")
            return None

    def clipar(self, segundos: int = 30) -> Path | None:
        """Salva um clipe recente, quando houver um buffer ativo com vídeo."""
        try:
            with self._bloqueio:
                buffer = self._buffer
            if buffer is None:
                raise ErroGravacao("O buffer de clipes não está ativo")
            caminho = buffer.salvar_clipe(segundos)
            if caminho is not None:
                self._emitir_evento(f"Clipe salvo: {caminho}")
            return caminho
        except Exception as erro:
            self._emitir_erro(f"Não foi possível salvar o clipe: {erro}")
            return None

    def alimentar_video(self, quadro: np.ndarray) -> None:
        """Entrega um quadro ao buffer e à gravação em andamento."""
        try:
            altura, largura = quadro.shape[:2]
            with self._bloqueio:
                self._largura, self._altura = largura, altura
                buffer = self._buffer
            if buffer is not None:
                buffer.alimentar_video(quadro)
            self._gravador.escrever_video(quadro)
        except Exception as erro:
            self._emitir_erro(f"Não foi possível gravar o quadro: {erro}")

    def alimentar_audio(self, bloco: bytes | np.ndarray) -> None:
        """Entrega PCM ao buffer e à gravação em andamento."""
        try:
            with self._bloqueio:
                buffer = self._buffer
            if buffer is not None:
                buffer.alimentar_audio(bloco)
            self._gravador.escrever_audio(bloco)
        except Exception as erro:
            self._emitir_erro(f"Não foi possível gravar o áudio: {erro}")

    def estado(self) -> dict[str, bool | float | int]:
        """Devolve um retrato simples do estado que a interface pode consultar."""
        try:
            with self._bloqueio:
                buffer = self._buffer
            return {
                "gravando": self._gravador.gravando,
                "duracao": self._gravador.duracao,
                "buffer_ativo": buffer is not None,
                "segundos_no_buffer": buffer.segundos_disponiveis if buffer else 0.0,
                "memoria": buffer.memoria_estimada_bytes if buffer else 0,
            }
        except Exception as erro:  # pragma: no cover - proteção da interface
            self._emitir_erro(f"Não foi possível consultar o estado: {erro}")
            return {
                "gravando": False,
                "duracao": 0.0,
                "buffer_ativo": False,
                "segundos_no_buffer": 0.0,
                "memoria": 0,
            }

    def _emitir_evento(self, mensagem: str) -> None:
        """Chama o callback de eventos sem deixar a interface falhar."""
        try:
            self.ao_evento(mensagem)
        except Exception:  # pragma: no cover - callback de terceiros
            _registrador.exception("O callback de eventos falhou")

    def _emitir_erro(self, mensagem: str) -> None:
        """Registra e chama o callback de erros de forma segura."""
        _registrador.warning("%s", mensagem)
        try:
            self.ao_erro(mensagem)
        except Exception:  # pragma: no cover - callback de terceiros
            _registrador.exception("O callback de erros falhou")
