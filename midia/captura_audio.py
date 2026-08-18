"""Captura e reprodução de áudio com suporte a múltiplos motores.

O motor preferencial é o **sounddevice**, que fornece rodas (*wheels*)
compatíveis com as versões mais recentes do Python (inclusive 3.13/3.14) e
depende apenas da biblioteca PortAudio do sistema. O **PyAudio** permanece
como alternativa automática, garantindo compatibilidade com instalações
antigas do projeto.

O módulo é tolerante à ausência de qualquer biblioteca ou dispositivo: nesse
caso ``AUDIO_DISPONIVEL`` fica ``False``, o motivo é registrado em
``MOTIVO_AUDIO_INDISPONIVEL`` e a aplicação segue funcionando apenas com
vídeo e chat.

Para adicionar um novo motor basta criar um par de adaptadores com a mesma
interface de ``_EntradaSounddevice``/``_SaidaSounddevice`` e registrá-lo em
``_detectar_motor``.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

from configuracao.configuracoes import ConfiguracaoAudio
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

MOTOR_SOUNDDEVICE = "sounddevice"
MOTOR_PYAUDIO = "pyaudio"

_sounddevice: Any = None
_pyaudio: Any = None


class ErroAudio(Exception):
    """Falha ao abrir dispositivo de entrada ou saída de áudio."""


# ---------------------------------------------------------------------------
# Detecção do motor disponível
# ---------------------------------------------------------------------------


def _detectar_motor() -> tuple[str | None, str]:
    """Descobre qual biblioteca de áudio pode ser usada.

    Returns:
        Uma tupla ``(motor, motivo)``. Quando nenhum motor está disponível,
        ``motor`` é ``None`` e ``motivo`` explica o problema para o usuário.
    """
    global _sounddevice, _pyaudio

    erros: list[str] = []

    try:
        import sounddevice  # noqa: PLC0415 - importação intencionalmente tardia

        _sounddevice = sounddevice
        return MOTOR_SOUNDDEVICE, ""
    except Exception as erro:  # ImportError ou OSError (PortAudio ausente)
        erros.append(f"sounddevice: {erro}")

    try:
        import pyaudio  # noqa: PLC0415 - importação intencionalmente tardia

        _pyaudio = pyaudio
        return MOTOR_PYAUDIO, ""
    except Exception as erro:
        erros.append(f"PyAudio: {erro}")

    return None, "; ".join(erros)


MOTOR_AUDIO, MOTIVO_AUDIO_INDISPONIVEL = _detectar_motor()
AUDIO_DISPONIVEL = MOTOR_AUDIO is not None

if AUDIO_DISPONIVEL:
    _registrador.info("Motor de áudio em uso: %s", MOTOR_AUDIO)
else:  # pragma: no cover - depende do ambiente
    _registrador.warning(
        "Nenhum motor de áudio disponível (%s); o áudio será desativado",
        MOTIVO_AUDIO_INDISPONIVEL,
    )


def descrever_motor_audio() -> str:
    """Texto curto sobre o estado do áudio, para exibir na interface."""
    if MOTOR_AUDIO == MOTOR_SOUNDDEVICE:
        return "Áudio disponível (sounddevice)"
    if MOTOR_AUDIO == MOTOR_PYAUDIO:
        return "Áudio disponível (PyAudio)"
    return "Áudio indisponível - instale o sounddevice e o PortAudio"


def listar_dispositivos(entrada: bool = True) -> list[str]:
    """Lista os dispositivos de áudio de entrada ou de saída."""
    if MOTOR_AUDIO == MOTOR_SOUNDDEVICE:
        return _listar_dispositivos_sounddevice(entrada)
    if MOTOR_AUDIO == MOTOR_PYAUDIO:
        return _listar_dispositivos_pyaudio(entrada)
    return []


def _listar_dispositivos_sounddevice(entrada: bool) -> list[str]:
    """Lista os dispositivos conhecidos pelo sounddevice."""
    chave = "max_input_channels" if entrada else "max_output_channels"
    descricoes: list[str] = []
    try:
        for indice, info in enumerate(_sounddevice.query_devices()):
            if int(info.get(chave, 0)) > 0:
                descricoes.append(f"{indice} - {info.get('name')}")
    except Exception as erro:  # pragma: no cover - depende do sistema
        _registrador.warning("Falha ao listar dispositivos de áudio: %s", erro)
    return descricoes


def _listar_dispositivos_pyaudio(entrada: bool) -> list[str]:
    """Lista os dispositivos conhecidos pelo PyAudio."""
    chave = "maxInputChannels" if entrada else "maxOutputChannels"
    descricoes: list[str] = []
    instancia = None
    try:
        instancia = _pyaudio.PyAudio()
        for indice in range(instancia.get_device_count()):
            info = instancia.get_device_info_by_index(indice)
            if int(info.get(chave, 0) or 0) > 0:
                descricoes.append(f"{indice} - {info.get('name')}")
    except Exception as erro:  # pragma: no cover - depende do sistema
        _registrador.warning("Falha ao listar dispositivos de áudio: %s", erro)
    finally:
        if instancia is not None:
            instancia.terminate()
    return descricoes


# ---------------------------------------------------------------------------
# Adaptadores de entrada (microfone)
# ---------------------------------------------------------------------------


class _EntradaSounddevice:
    """Fluxo de entrada PCM de 16 bits usando o sounddevice."""

    def __init__(self, configuracao: ConfiguracaoAudio) -> None:
        self._configuracao = configuracao
        self._fluxo: Any = None

    def abrir(self) -> None:
        """Abre o fluxo de captura do microfone."""
        self._fluxo = _sounddevice.RawInputStream(
            samplerate=self._configuracao.taxa_amostragem,
            blocksize=self._configuracao.tamanho_bloco,
            device=self._configuracao.dispositivo_entrada,
            channels=self._configuracao.canais,
            dtype="int16",
        )
        self._fluxo.start()

    def ler(self) -> bytes:
        """Lê um bloco de amostras, devolvendo bytes PCM."""
        dados, estourou = self._fluxo.read(self._configuracao.tamanho_bloco)
        if estourou:
            _registrador.debug("Estouro na captura de áudio (bloco atrasado)")
        return bytes(dados)

    def fechar(self) -> None:
        """Encerra o fluxo de captura."""
        if self._fluxo is not None:
            try:
                self._fluxo.stop()
                self._fluxo.close()
            except Exception:  # pragma: no cover
                pass
            self._fluxo = None


class _EntradaPyAudio:
    """Fluxo de entrada PCM de 16 bits usando o PyAudio."""

    def __init__(self, configuracao: ConfiguracaoAudio) -> None:
        self._configuracao = configuracao
        self._instancia: Any = None
        self._fluxo: Any = None

    def abrir(self) -> None:
        """Abre o fluxo de captura do microfone."""
        self._instancia = _pyaudio.PyAudio()
        self._fluxo = self._instancia.open(
            format=_pyaudio.paInt16,
            channels=self._configuracao.canais,
            rate=self._configuracao.taxa_amostragem,
            input=True,
            input_device_index=self._configuracao.dispositivo_entrada,
            frames_per_buffer=self._configuracao.tamanho_bloco,
        )

    def ler(self) -> bytes:
        """Lê um bloco de amostras, devolvendo bytes PCM."""
        return self._fluxo.read(
            self._configuracao.tamanho_bloco, exception_on_overflow=False
        )

    def fechar(self) -> None:
        """Encerra o fluxo e a instância do PyAudio."""
        if self._fluxo is not None:
            try:
                self._fluxo.stop_stream()
                self._fluxo.close()
            except Exception:  # pragma: no cover
                pass
            self._fluxo = None
        if self._instancia is not None:
            try:
                self._instancia.terminate()
            except Exception:  # pragma: no cover
                pass
            self._instancia = None


# ---------------------------------------------------------------------------
# Adaptadores de saída (alto-falante)
# ---------------------------------------------------------------------------


class _SaidaSounddevice:
    """Fluxo de saída PCM de 16 bits usando o sounddevice."""

    def __init__(self, configuracao: ConfiguracaoAudio) -> None:
        self._configuracao = configuracao
        self._fluxo: Any = None

    def abrir(self) -> None:
        """Abre o fluxo de reprodução."""
        self._fluxo = _sounddevice.RawOutputStream(
            samplerate=self._configuracao.taxa_amostragem,
            blocksize=self._configuracao.tamanho_bloco,
            device=self._configuracao.dispositivo_saida,
            channels=self._configuracao.canais,
            dtype="int16",
        )
        self._fluxo.start()

    def escrever(self, dados: bytes) -> None:
        """Envia um bloco PCM para a placa de som."""
        self._fluxo.write(dados)

    def fechar(self) -> None:
        """Encerra o fluxo de reprodução."""
        if self._fluxo is not None:
            try:
                self._fluxo.stop()
                self._fluxo.close()
            except Exception:  # pragma: no cover
                pass
            self._fluxo = None


class _SaidaPyAudio:
    """Fluxo de saída PCM de 16 bits usando o PyAudio."""

    def __init__(self, configuracao: ConfiguracaoAudio) -> None:
        self._configuracao = configuracao
        self._instancia: Any = None
        self._fluxo: Any = None

    def abrir(self) -> None:
        """Abre o fluxo de reprodução."""
        self._instancia = _pyaudio.PyAudio()
        self._fluxo = self._instancia.open(
            format=_pyaudio.paInt16,
            channels=self._configuracao.canais,
            rate=self._configuracao.taxa_amostragem,
            output=True,
            output_device_index=self._configuracao.dispositivo_saida,
            frames_per_buffer=self._configuracao.tamanho_bloco,
        )

    def escrever(self, dados: bytes) -> None:
        """Envia um bloco PCM para a placa de som."""
        self._fluxo.write(dados, exception_on_underflow=False)

    def fechar(self) -> None:
        """Encerra o fluxo e a instância do PyAudio."""
        if self._fluxo is not None:
            try:
                self._fluxo.stop_stream()
                self._fluxo.close()
            except Exception:  # pragma: no cover
                pass
            self._fluxo = None
        if self._instancia is not None:
            try:
                self._instancia.terminate()
            except Exception:  # pragma: no cover
                pass
            self._instancia = None


def _criar_entrada(configuracao: ConfiguracaoAudio) -> Any:
    """Cria o adaptador de entrada do motor ativo."""
    if MOTOR_AUDIO == MOTOR_SOUNDDEVICE:
        return _EntradaSounddevice(configuracao)
    if MOTOR_AUDIO == MOTOR_PYAUDIO:
        return _EntradaPyAudio(configuracao)
    raise ErroAudio(f"Nenhum motor de áudio disponível ({MOTIVO_AUDIO_INDISPONIVEL})")


def _criar_saida(configuracao: ConfiguracaoAudio) -> Any:
    """Cria o adaptador de saída do motor ativo."""
    if MOTOR_AUDIO == MOTOR_SOUNDDEVICE:
        return _SaidaSounddevice(configuracao)
    if MOTOR_AUDIO == MOTOR_PYAUDIO:
        return _SaidaPyAudio(configuracao)
    raise ErroAudio(f"Nenhum motor de áudio disponível ({MOTIVO_AUDIO_INDISPONIVEL})")


# ---------------------------------------------------------------------------
# Classes públicas
# ---------------------------------------------------------------------------


class CapturadorAudio:
    """Captura blocos PCM do microfone, independente do motor de áudio."""

    def __init__(self, configuracao: ConfiguracaoAudio) -> None:
        self.configuracao = configuracao
        self._entrada: Any = None

    @property
    def disponivel(self) -> bool:
        """Indica se a captura de áudio pode ser utilizada."""
        return AUDIO_DISPONIVEL and self.configuracao.ativo

    def abrir(self) -> None:
        """Abre o fluxo de entrada de áudio.

        Raises:
            ErroAudio: se o microfone não estiver acessível.
        """
        if not self.disponivel:
            raise ErroAudio("Captura de áudio desativada ou indisponível")
        try:
            self._entrada = _criar_entrada(self.configuracao)
            self._entrada.abrir()
        except Exception as erro:
            self.fechar()
            raise ErroAudio(f"Microfone indisponível: {erro}") from erro
        _registrador.info("Microfone aberto com sucesso (%s)", MOTOR_AUDIO)

    def ler(self) -> bytes:
        """Lê um bloco de áudio do microfone.

        Raises:
            ErroAudio: se o fluxo não estiver aberto ou a leitura falhar.
        """
        if self._entrada is None:
            raise ErroAudio("Fluxo de entrada não inicializado")
        try:
            return self._entrada.ler()
        except Exception as erro:
            raise ErroAudio(f"Falha na leitura do microfone: {erro}") from erro

    def fechar(self) -> None:
        """Libera o fluxo de entrada."""
        if self._entrada is not None:
            self._entrada.fechar()
            self._entrada = None


class ReprodutorAudio:
    """Reproduz blocos PCM recebidos pela rede.

    Os blocos são enfileirados e consumidos por uma thread dedicada, evitando
    que a rede fique bloqueada pela placa de som. Blocos antigos são
    descartados quando a fila enche, o que mantém a latência sob controle.
    """

    def __init__(self, configuracao: ConfiguracaoAudio, limite_fila: int = 24) -> None:
        self.configuracao = configuracao
        self._fila: queue.Queue[bytes] = queue.Queue(maxsize=limite_fila)
        self._saida: Any = None
        self._thread: threading.Thread | None = None
        self._ativo = False
        self.blocos_descartados = 0

    @property
    def disponivel(self) -> bool:
        """Indica se a reprodução de áudio pode ser utilizada."""
        return AUDIO_DISPONIVEL

    def iniciar(self) -> None:
        """Abre a saída de áudio e inicia a thread de reprodução.

        Raises:
            ErroAudio: se a saída de áudio não puder ser aberta.
        """
        if not self.disponivel:
            raise ErroAudio(
                f"Reprodução de áudio indisponível ({MOTIVO_AUDIO_INDISPONIVEL})"
            )
        if self._ativo:
            return
        try:
            self._saida = _criar_saida(self.configuracao)
            self._saida.abrir()
        except Exception as erro:
            self.parar()
            raise ErroAudio(f"Saída de áudio indisponível: {erro}") from erro

        self._ativo = True
        self._thread = threading.Thread(
            target=self._laco_reproducao, name="reproducao-audio", daemon=True
        )
        self._thread.start()
        _registrador.info("Reprodução de áudio iniciada (%s)", MOTOR_AUDIO)

    def escrever(self, dados: bytes) -> None:
        """Enfileira um bloco para reprodução, descartando o mais antigo se cheio."""
        if not self._ativo:
            return
        try:
            self._fila.put_nowait(dados)
        except queue.Full:
            self.blocos_descartados += 1
            try:
                self._fila.get_nowait()
                self._fila.put_nowait(dados)
            except (queue.Empty, queue.Full):  # pragma: no cover
                pass

    def _laco_reproducao(self) -> None:
        """Consome a fila e envia os blocos para a placa de som."""
        while self._ativo:
            try:
                bloco = self._fila.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if self._saida is not None:
                    self._saida.escrever(bloco)
            except Exception as erro:  # pragma: no cover
                _registrador.warning("Falha ao reproduzir áudio: %s", erro)
                break

    def parar(self) -> None:
        """Interrompe a reprodução e libera os recursos."""
        self._ativo = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        if self._saida is not None:
            self._saida.fechar()
            self._saida = None
