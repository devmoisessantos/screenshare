"""Captura e reprodução de áudio com sounddevice.

O módulo é tolerante à ausência da biblioteca ou de dispositivos de áudio:
nesse caso a aplicação continua funcionando apenas com vídeo e chat.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

import numpy as np

from configuracao.configuracoes import ConfiguracaoAudio
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

try:  # pragma: no cover - depende do ambiente
    import sounddevice as sd

    AUDIO_DISPONIVEL = True
except Exception as _erro_importacao:  # pragma: no cover
    sd = None  # type: ignore[assignment]
    AUDIO_DISPONIVEL = False
    _registrador.warning(
        "sounddevice indisponível (%s); o áudio será desativado", _erro_importacao
    )


class ErroAudio(Exception):
    """Falha ao abrir dispositivo de entrada ou saída de áudio."""


def _formato_amostra() -> str:
    """Formato de amostragem usado (16 bits inteiros com sinal)."""
    if not AUDIO_DISPONIVEL:
        raise ErroAudio("sounddevice não está disponível")
    return "int16"


def listar_dispositivos(entrada: bool = True) -> list[str]:
    """Lista dispositivos de áudio de entrada ou de saída."""
    if not AUDIO_DISPONIVEL:
        return []
    descricoes: list[str] = []
    try:
        dispositivos = sd.query_devices()
        for indice, info in enumerate(dispositivos):
            canais = info.get("max_input_channels" if entrada else "max_output_channels", 0)
            if canais and int(canais) > 0:
                descricoes.append(f"{indice} - {info.get('name')}")
    except Exception as erro:
        _registrador.warning("Falha ao listar dispositivos: %s", erro)
    return descricoes


class CapturadorAudio:
    """Captura blocos PCM do microfone."""

    def __init__(self, configuracao: ConfiguracaoAudio) -> None:
        self.configuracao = configuracao
        self._fluxo: Any = None

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
            self._fluxo = sd.InputStream(
                samplerate=self.configuracao.taxa_amostragem,
                channels=self.configuracao.canais,
                dtype=_formato_amostra(),
                blocksize=self.configuracao.tamanho_bloco,
                device=self.configuracao.dispositivo_entrada,
            )
            self._fluxo.start()
        except Exception as erro:
            self.fechar()
            raise ErroAudio(f"Microfone indisponível: {erro}") from erro
        _registrador.info("Microfone aberto com sucesso")

    def ler(self) -> bytes:
        """Lê um bloco de áudio do microfone.

        Raises:
            ErroAudio: se a leitura falhar.
        """
        if self._fluxo is None:
            raise ErroAudio("Fluxo de entrada não inicializado")
        try:
            dados, _ = self._fluxo.read(self.configuracao.tamanho_bloco)
            return dados.tobytes()
        except Exception as erro:
            raise ErroAudio(f"Falha na leitura do microfone: {erro}") from erro

    def fechar(self) -> None:
        """Libera o fluxo de áudio."""
        if self._fluxo is not None:
            try:
                self._fluxo.stop()
                self._fluxo.close()
            except Exception:  # pragma: no cover
                pass
            self._fluxo = None


class ReprodutorAudio:
    """Reproduz blocos PCM recebidos pela rede.

    Os blocos são enfileirados e consumidos por uma thread dedicada, evitando
    que a rede fique bloqueada pela placa de som. Blocos antigos são
    descartados quando a fila enche, o que mantém a latência sob controle.
    """

    def __init__(self, configuracao: ConfiguracaoAudio, limite_fila: int = 24) -> None:
        self.configuracao = configuracao
        self._fila: queue.Queue[bytes] = queue.Queue(maxsize=limite_fila)
        self._fluxo: Any = None
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
            raise ErroAudio("Reprodução de áudio indisponível")
        if self._ativo:
            return
        try:
            self._fluxo = sd.OutputStream(
                samplerate=self.configuracao.taxa_amostragem,
                channels=self.configuracao.canais,
                dtype=_formato_amostra(),
                blocksize=self.configuracao.tamanho_bloco,
                device=self.configuracao.dispositivo_saida,
            )
            self._fluxo.start()
        except Exception as erro:
            self.parar()
            raise ErroAudio(f"Saída de áudio indisponível: {erro}") from erro

        self._ativo = True
        self._thread = threading.Thread(
            target=self._laco_reproducao, name="reproducao-audio", daemon=True
        )
        self._thread.start()
        _registrador.info("Reprodução de áudio iniciada")

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
                if self._fluxo is not None:
                    dados = np.frombuffer(bloco, dtype=np.int16)
                    self._fluxo.write(dados)
            except Exception as erro:  # pragma: no cover
                _registrador.warning("Falha ao reproduzir áudio: %s", erro)
                break

    def parar(self) -> None:
        """Interrompe a reprodução e libera os recursos."""
        self._ativo = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        if self._fluxo is not None:
            try:
                self._fluxo.stop()
                self._fluxo.close()
            except Exception:  # pragma: no cover
                pass
            self._fluxo = None
