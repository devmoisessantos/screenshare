"""Faixas WebRTC que fazem a ponte entre fontes locais e aiortc."""

from __future__ import annotations

import asyncio
import fractions
import queue
import threading
import time
from typing import Any, Callable

import av
import mss
import numpy as np
from aiortc import AudioStreamTrack, VideoStreamTrack
from aiortc.mediastreams import MediaStreamError

from midia import captura_audio
from midia.fontes import FonteCaptura, regiao_da_janela
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

TAXA_AUDIO = 48000
AMOSTRAS_POR_BLOCO = 960
DURACAO_BLOCO_AUDIO = AMOSTRAS_POR_BLOCO / TAXA_AUDIO
RELOGIO_VIDEO = 90000


def _redimensionar_com_barras(
    quadro: np.ndarray, largura_destino: int, altura_destino: int
) -> np.ndarray:
    """Redimensiona um quadro BGR por vizinho próximo e adiciona barras pretas."""
    resultado = np.zeros((altura_destino, largura_destino, 3), dtype=np.uint8)
    if quadro.ndim != 3 or quadro.shape[0] <= 0 or quadro.shape[1] <= 0:
        return resultado
    altura_origem, largura_origem = quadro.shape[:2]
    escala = min(largura_destino / largura_origem, altura_destino / altura_origem)
    largura = max(1, round(largura_origem * escala))
    altura = max(1, round(altura_origem * escala))
    indices_y = np.linspace(0, altura_origem - 1, altura).astype(np.intp)
    indices_x = np.linspace(0, largura_origem - 1, largura).astype(np.intp)
    redimensionado = quadro[indices_y][:, indices_x, :3]
    topo = (altura_destino - altura) // 2
    esquerda = (largura_destino - largura) // 2
    resultado[topo : topo + altura, esquerda : esquerda + largura] = redimensionado
    return resultado


class FaixaTela(VideoStreamTrack):
    """Faixa de vídeo que captura uma tela, monitor ou janela em uma thread."""

    def __init__(
        self,
        fonte: FonteCaptura,
        largura: int,
        altura: int,
        fps: int,
        seguir_janela: bool = True,
    ) -> None:
        super().__init__()
        self.fonte = fonte
        self.largura = largura
        self.altura = altura
        self.fps = max(1, fps)
        self.seguir_janela = seguir_janela
        self._local = threading.local()
        self._parada = False
        self._aviso_emitido = False
        self._inicio: float | None = None
        self._timestamp_video: int | None = None

    async def next_timestamp(self) -> tuple[int, fractions.Fraction]:
        """Entrega timestamps no ritmo configurado para esta faixa."""
        if self.readyState != "live" or self._parada:
            raise MediaStreamError
        incremento = max(1, round(RELOGIO_VIDEO / self.fps))
        if self._timestamp_video is None:
            self._inicio = time.monotonic()
            self._timestamp_video = 0
        else:
            self._timestamp_video += incremento
            assert self._inicio is not None
            espera = self._inicio + self._timestamp_video / RELOGIO_VIDEO - time.monotonic()
            if espera > 0:
                await asyncio.sleep(espera)
        return self._timestamp_video, fractions.Fraction(1, RELOGIO_VIDEO)

    def _capturar_sincrono(self) -> np.ndarray:
        """Captura e converte um quadro no contexto da thread de trabalho."""
        regiao = self.fonte.regiao
        if self.fonte.tipo == "janela" and self.seguir_janela:
            regiao = regiao_da_janela(self.fonte.identificador_janela or self.fonte.identificador)
        if regiao is None:
            raise RuntimeError("Fonte de captura não possui região disponível")
        captura = getattr(self._local, "captura", None)
        if captura is None:
            captura = mss.mss()
            self._local.captura = captura
        bruto = captura.grab(regiao)
        quadro = np.asarray(bruto, dtype=np.uint8)
        if quadro.ndim != 3 or quadro.shape[2] < 3:
            raise RuntimeError("Captura de tela retornou um quadro inválido")
        return quadro[:, :, :3]

    async def recv(self) -> av.VideoFrame:
        """Captura um quadro sem bloquear o laço assíncrono."""
        pts, base_tempo = await self.next_timestamp()
        try:
            quadro = await asyncio.to_thread(self._capturar_sincrono)
            quadro = _redimensionar_com_barras(quadro, self.largura, self.altura)
        except Exception as erro:
            if not self._aviso_emitido:
                _registrador.warning("Falha na captura de tela; enviando quadro preto: %s", erro)
                self._aviso_emitido = True
            quadro = np.zeros((self.altura, self.largura, 3), dtype=np.uint8)
        quadro_av = av.VideoFrame.from_ndarray(quadro, format="bgr24")
        quadro_av.pts = pts
        quadro_av.time_base = base_tempo
        return quadro_av

    def trocar_fonte(self, fonte: FonteCaptura) -> None:
        """Passa a capturar outra fonte a partir do próximo quadro."""
        self.fonte = fonte
        self._aviso_emitido = False

    def parar(self) -> None:
        """Interrompe a faixa e libera seu estado WebRTC."""
        self._parada = True
        self.stop()


class FaixaMicrofone(AudioStreamTrack):
    """Faixa Opus de microfone em PCM mono de 48 kHz e blocos de 20 ms."""

    def __init__(self, indice_dispositivo: int | None = None, limite_fila: int = 12) -> None:
        super().__init__()
        self.indice_dispositivo = indice_dispositivo
        self.mudo = False
        self._fila: queue.Queue[bytes] = queue.Queue(maxsize=max(1, limite_fila))
        self._fluxo: Any = None
        self._instancia_pyaudio: Any = None
        self._parada = False
        self._inicio: float | None = None
        self._timestamp_audio: int | None = None
        self._abrir_entrada()

    def _inserir_bloco(self, dados: bytes) -> None:
        """Enfileira um bloco, descartando o mais antigo quando necessário."""
        try:
            self._fila.put_nowait(bytes(dados))
        except queue.Full:
            try:
                self._fila.get_nowait()
                self._fila.put_nowait(bytes(dados))
            except (queue.Empty, queue.Full):  # pragma: no cover - disputa de threads
                pass

    def _abrir_entrada(self) -> None:
        """Abre a entrada nativa em modo callback, quando houver motor de áudio."""
        if not captura_audio.AUDIO_DISPONIVEL:
            return
        try:
            if captura_audio.MOTOR_AUDIO == captura_audio.MOTOR_SOUNDDEVICE:
                self._fluxo = captura_audio._sounddevice.RawInputStream(
                    samplerate=TAXA_AUDIO,
                    blocksize=AMOSTRAS_POR_BLOCO,
                    device=self.indice_dispositivo,
                    channels=1,
                    dtype="int16",
                    callback=self._ao_audio_sounddevice,
                )
                self._fluxo.start()
            elif captura_audio.MOTOR_AUDIO == captura_audio.MOTOR_PYAUDIO:
                self._instancia_pyaudio = captura_audio._pyaudio.PyAudio()
                self._fluxo = self._instancia_pyaudio.open(
                    format=captura_audio._pyaudio.paInt16,
                    channels=1,
                    rate=TAXA_AUDIO,
                    input=True,
                    input_device_index=self.indice_dispositivo,
                    frames_per_buffer=AMOSTRAS_POR_BLOCO,
                    stream_callback=self._ao_audio_pyaudio,
                )
                self._fluxo.start_stream()
        except Exception as erro:
            _registrador.warning("Microfone indisponível; enviando silêncio: %s", erro)
            self._fechar_entrada()

    def _ao_audio_sounddevice(
        self, dados: Any, _quadros: int, _tempo: Any, estado: Any
    ) -> None:
        """Recebe um bloco do callback do sounddevice."""
        if estado:
            _registrador.debug("Estado da captura de áudio: %s", estado)
        self._inserir_bloco(bytes(dados))

    def _ao_audio_pyaudio(
        self, dados: bytes, _quadros: int, _tempo: Any, _estado: int
    ) -> tuple[None, int]:
        """Recebe um bloco do callback do PyAudio."""
        self._inserir_bloco(dados)
        return None, captura_audio._pyaudio.paContinue

    def _fechar_entrada(self) -> None:
        """Fecha a entrada de microfone e sua instância auxiliar."""
        if self._fluxo is not None:
            try:
                if hasattr(self._fluxo, "stop"):
                    self._fluxo.stop()
                elif hasattr(self._fluxo, "stop_stream"):
                    self._fluxo.stop_stream()
                self._fluxo.close()
            except Exception:  # pragma: no cover - adaptador externo
                pass
            self._fluxo = None
        if self._instancia_pyaudio is not None:
            try:
                self._instancia_pyaudio.terminate()
            except Exception:  # pragma: no cover - adaptador externo
                pass
            self._instancia_pyaudio = None

    async def _proximo_timestamp(self) -> tuple[int, fractions.Fraction]:
        """Mantém a cadência de 20 ms exigida pelo Opus."""
        if self.readyState != "live" or self._parada:
            raise MediaStreamError
        if self._timestamp_audio is None:
            self._inicio = time.monotonic()
            self._timestamp_audio = 0
        else:
            self._timestamp_audio += AMOSTRAS_POR_BLOCO
            assert self._inicio is not None
            espera = self._inicio + self._timestamp_audio / TAXA_AUDIO - time.monotonic()
            if espera > 0:
                await asyncio.sleep(espera)
        return self._timestamp_audio, fractions.Fraction(1, TAXA_AUDIO)

    async def recv(self) -> av.AudioFrame:
        """Devolve o próximo bloco de microfone ou silêncio no mesmo formato."""
        pts, base_tempo = await self._proximo_timestamp()
        dados = bytes(AMOSTRAS_POR_BLOCO * 2)
        if not self.mudo:
            try:
                recebido = self._fila.get_nowait()
                dados = recebido[: AMOSTRAS_POR_BLOCO * 2].ljust(AMOSTRAS_POR_BLOCO * 2, b"\0")
            except queue.Empty:
                pass
        quadro = av.AudioFrame(format="s16", layout="mono", samples=AMOSTRAS_POR_BLOCO)
        quadro.planes[0].update(dados)
        quadro.pts = pts
        quadro.sample_rate = TAXA_AUDIO
        quadro.time_base = base_tempo
        return quadro

    def trocar_dispositivo(self, indice: int | None) -> None:
        """Reabre a captura usando outro microfone."""
        self._fechar_entrada()
        while not self._fila.empty():
            try:
                self._fila.get_nowait()
            except queue.Empty:  # pragma: no cover - disputa de threads
                break
        self.indice_dispositivo = indice
        if not self._parada:
            self._abrir_entrada()

    def parar(self) -> None:
        """Interrompe a faixa e fecha o microfone."""
        self._parada = True
        self._fechar_entrada()
        self.stop()


class ReprodutorFaixaRemota:
    """Consome uma faixa remota e a encaminha à saída local de áudio."""

    def __init__(self, faixa: AudioStreamTrack, indice_dispositivo: int | None = None) -> None:
        self.faixa = faixa
        self.indice_dispositivo = indice_dispositivo
        self.volume = 1.0
        self.surdo = False
        self._saida: Any = None
        self._instancia_pyaudio: Any = None
        self._parada = False
        self._reamostrador = av.AudioResampler(format="s16", layout="mono", rate=TAXA_AUDIO)
        self._tarefa: asyncio.Task[None] | None = None
        self.iniciar()

    def iniciar(self) -> None:
        """Inicia a tarefa de consumo quando existe um laço assíncrono em execução."""
        if self._tarefa is not None or self._parada:
            return
        try:
            self._tarefa = asyncio.get_running_loop().create_task(self._consumir())
        except RuntimeError:
            _registrador.warning("Reprodutor remoto criado sem laço assíncrono")

    def _abrir_saida(self) -> None:
        """Abre a saída de áudio preguiçosamente."""
        if self._saida is not None or not captura_audio.AUDIO_DISPONIVEL:
            return
        try:
            if captura_audio.MOTOR_AUDIO == captura_audio.MOTOR_SOUNDDEVICE:
                self._saida = captura_audio._sounddevice.RawOutputStream(
                    samplerate=TAXA_AUDIO,
                    blocksize=AMOSTRAS_POR_BLOCO,
                    device=self.indice_dispositivo,
                    channels=1,
                    dtype="int16",
                )
                self._saida.start()
            elif captura_audio.MOTOR_AUDIO == captura_audio.MOTOR_PYAUDIO:
                self._instancia_pyaudio = captura_audio._pyaudio.PyAudio()
                self._saida = self._instancia_pyaudio.open(
                    format=captura_audio._pyaudio.paInt16,
                    channels=1,
                    rate=TAXA_AUDIO,
                    output=True,
                    output_device_index=self.indice_dispositivo,
                    frames_per_buffer=AMOSTRAS_POR_BLOCO,
                )
        except Exception as erro:
            _registrador.warning("Saída de áudio indisponível: %s", erro)
            self._fechar_saida()

    def _fechar_saida(self) -> None:
        """Libera a saída de áudio local."""
        if self._saida is not None:
            try:
                if hasattr(self._saida, "stop"):
                    self._saida.stop()
                elif hasattr(self._saida, "stop_stream"):
                    self._saida.stop_stream()
                self._saida.close()
            except Exception:  # pragma: no cover - adaptador externo
                pass
            self._saida = None
        if self._instancia_pyaudio is not None:
            try:
                self._instancia_pyaudio.terminate()
            except Exception:  # pragma: no cover - adaptador externo
                pass
            self._instancia_pyaudio = None

    def _ajustar_volume(self, dados: bytes) -> bytes:
        """Aplica volume limitado ao PCM s16."""
        if self.surdo:
            return bytes(len(dados))
        volume = min(1.0, max(0.0, float(self.volume)))
        if volume == 1.0:
            return dados
        amostras = np.frombuffer(dados, dtype=np.int16).astype(np.float32)
        return np.clip(amostras * volume, -32768, 32767).astype(np.int16).tobytes()

    async def _consumir(self) -> None:
        """Lê, reamostra e reproduz todos os quadros da faixa remota."""
        try:
            while not self._parada:
                quadro = await self.faixa.recv()
                for convertido in self._reamostrador.resample(quadro):
                    dados = self._ajustar_volume(bytes(convertido.planes[0]))
                    self._abrir_saida()
                    if self._saida is not None and hasattr(self._saida, "write"):
                        self._saida.write(dados)
        except (asyncio.CancelledError, MediaStreamError):
            raise
        except Exception as erro:
            if not self._parada:
                _registrador.warning("Falha ao reproduzir faixa remota: %s", erro)
        finally:
            self._fechar_saida()

    def parar(self) -> None:
        """Cancela a tarefa de reprodução e fecha a saída local."""
        self._parada = True
        if self._tarefa is not None:
            self._tarefa.cancel()
        self._fechar_saida()


class ConsumidorFaixaVideo:
    """Converte os quadros de uma faixa remota e os entrega por callback."""

    def __init__(
        self, faixa: VideoStreamTrack, ao_quadro: Callable[[np.ndarray], None]
    ) -> None:
        self.faixa = faixa
        self.ao_quadro = ao_quadro
        self._parada = False
        self._tarefa: asyncio.Task[None] | None = None
        self.iniciar()

    def iniciar(self) -> None:
        """Inicia o consumo ao ser usado dentro de um laço assíncrono."""
        if self._tarefa is not None or self._parada:
            return
        try:
            self._tarefa = asyncio.get_running_loop().create_task(self._consumir())
        except RuntimeError:
            _registrador.warning("Consumidor de vídeo criado sem laço assíncrono")

    async def _consumir(self) -> None:
        """Recebe vídeo remoto, converte-o para BGR e dispara o callback."""
        try:
            while not self._parada:
                quadro = await self.faixa.recv()
                self.ao_quadro(quadro.to_ndarray(format="bgr24"))
        except (asyncio.CancelledError, MediaStreamError):
            raise
        except Exception as erro:
            if not self._parada:
                _registrador.warning("Falha ao consumir faixa de vídeo: %s", erro)

    def parar(self) -> None:
        """Cancela o consumo da faixa remota."""
        self._parada = True
        if self._tarefa is not None:
            self._tarefa.cancel()
