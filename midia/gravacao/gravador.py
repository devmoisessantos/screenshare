"""Gravador local de vídeo + áudio da sessão.

Usa OpenCV (VideoWriter) para o vídeo e, quando possível, grava o áudio
em paralelo. O arquivo final é um .avi/.mp4 no diretório de gravações do
usuário.

Recursos planejados (incrementais):
* Gravação contínua da sessão
* Clip dos últimos N minutos (buffer circular)
* Botão de “salvar clipe” estilo Medal
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from configuracao.configuracoes import diretorio_dados
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)


class EstadoGravacao(str, Enum):
    PARADO = "parado"
    GRAVANDO = "gravando"
    PAUSADO = "pausado"


@dataclass
class InfoGravacao:
    """Estado e estatísticas da gravação atual."""

    estado: EstadoGravacao = EstadoGravacao.PARADO
    caminho: Path | None = None
    frames_gravados: int = 0
    segundos: float = 0.0
    inicio: float = 0.0


class GravadorSessao:
    """Grava quadros BGR (e futuramente áudio) em arquivo de vídeo.

    Uso típico:
        gravador = GravadorSessao(fps=30, dimensoes=(1280, 720))
        gravador.iniciar()
        ...
        gravador.adicionar_quadro(frame_bgr)
        ...
        caminho = gravador.parar()
    """

    def __init__(
        self,
        fps: int = 30,
        dimensoes: tuple[int, int] = (1280, 720),
        pasta: Path | None = None,
        ao_estado: Callable[[InfoGravacao], None] | None = None,
    ) -> None:
        self.fps = max(1, fps)
        self.dimensoes = dimensoes
        self.pasta = pasta or (diretorio_dados() / "gravacoes")
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.ao_estado = ao_estado

        self._info = InfoGravacao()
        self._writer: cv2.VideoWriter | None = None
        self._trava = threading.Lock()
        self._ultimo_frame_ts = 0.0

    @property
    def info(self) -> InfoGravacao:
        return self._info

    @property
    def gravando(self) -> bool:
        return self._info.estado is EstadoGravacao.GRAVANDO

    def iniciar(self, nome: str | None = None) -> Path:
        """Abre um novo arquivo de gravação e começa a aceitar quadros."""
        with self._trava:
            if self._info.estado is EstadoGravacao.GRAVANDO:
                return self._info.caminho  # type: ignore[return-value]

            carimbo = time.strftime("%Y%m%d_%H%M%S")
            nome_arquivo = nome or f"screenshare_{carimbo}.avi"
            caminho = self.pasta / nome_arquivo

            quatrocc = cv2.VideoWriter_fourcc(*"XVID")
            largura, altura = self.dimensoes
            writer = cv2.VideoWriter(
                str(caminho), quatrocc, float(self.fps), (largura, altura)
            )
            if not writer.isOpened():
                raise RuntimeError(f"Não foi possível criar o arquivo de gravação: {caminho}")

            self._writer = writer
            self._info = InfoGravacao(
                estado=EstadoGravacao.GRAVANDO,
                caminho=caminho,
                inicio=time.monotonic(),
            )
            self._ultimo_frame_ts = 0.0
            _registrador.info("Gravação iniciada: %s", caminho)
            self._notificar()
            return caminho

    def adicionar_quadro(self, frame_bgr: np.ndarray) -> None:
        """Adiciona um quadro BGR à gravação (redimensiona se necessário)."""
        with self._trava:
            if self._info.estado is not EstadoGravacao.GRAVANDO or self._writer is None:
                return

            h, w = frame_bgr.shape[:2]
            alvo_w, alvo_h = self.dimensoes
            if (w, h) != (alvo_w, alvo_h):
                frame_bgr = cv2.resize(frame_bgr, (alvo_w, alvo_h), interpolation=cv2.INTER_AREA)

            self._writer.write(frame_bgr)
            self._info.frames_gravados += 1
            self._info.segundos = time.monotonic() - self._info.inicio

    def parar(self) -> Path | None:
        """Finaliza a gravação e devolve o caminho do arquivo (ou None)."""
        with self._trava:
            if self._writer is None:
                return None
            caminho = self._info.caminho
            try:
                self._writer.release()
            except Exception as erro:  # pragma: no cover
                _registrador.warning("Erro ao finalizar gravação: %s", erro)
            self._writer = None
            self._info.estado = EstadoGravacao.PARADO
            self._info.segundos = time.monotonic() - self._info.inicio if self._info.inicio else 0
            _registrador.info(
                "Gravação finalizada: %s (%d frames, %.1fs)",
                caminho,
                self._info.frames_gravados,
                self._info.segundos,
            )
            self._notificar()
            return caminho

    def _notificar(self) -> None:
        if self.ao_estado:
            try:
                self.ao_estado(self._info)
            except Exception:  # pragma: no cover
                pass
