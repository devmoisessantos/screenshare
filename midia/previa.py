"""Pré-visualização local da própria transmissão.

Assim como o Discord e ferramentas similares, o host deve conseguir ver o que
está sendo transmitido - é a única forma de confirmar que o monitor correto foi
escolhido e que a qualidade está aceitável, sem depender do espectador.

A prévia roda em uma thread própria, independente da sessão de rede, para que
funcione desde o momento em que o compartilhamento é iniciado, antes de
qualquer espectador conectar. Para não competir com a transmissão, ela captura
em taxa e resolução reduzidas (padrão: 10 quadros por segundo).
"""

from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np

from configuracao.configuracoes import ConfiguracaoVideo
from midia.captura_tela import CapturadorTela, ErroCapturaTela
from midia.compressao import bgr_para_rgb
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

#: Largura máxima da prévia, em pixels. Suficiente para conferir o conteúdo
#: sem consumir CPU desnecessária com redimensionamentos grandes.
LARGURA_PREVIA = 640


class PreVisualizadorTela:
    """Captura a tela periodicamente e entrega os quadros para a interface.

    Args:
        configuracao: configuração de vídeo usada para saber qual monitor e
            qual proporção capturar.
        ao_quadro: função chamada, na thread da prévia, com cada quadro RGB.
        fps: quantos quadros por segundo capturar.
    """

    def __init__(
        self,
        configuracao: ConfiguracaoVideo,
        ao_quadro: Callable[[np.ndarray], None],
        fps: int = 10,
        ao_erro: Callable[[str], None] | None = None,
    ) -> None:
        self._configuracao = configuracao
        self._dimensoes = self._calcular_dimensoes(configuracao)
        self._ao_quadro = ao_quadro
        self._ao_erro = ao_erro
        self._fps = max(1, fps)
        self._parando = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _calcular_dimensoes(configuracao: ConfiguracaoVideo) -> tuple[int, int]:
        """Calcula as dimensões da prévia preservando a proporção da tela."""
        largura, altura = configuracao.dimensoes
        proporcao = altura / largura if largura else 9 / 16
        nova_largura = min(LARGURA_PREVIA, largura)
        return nova_largura, max(1, int(nova_largura * proporcao))

    @property
    def ativa(self) -> bool:
        """``True`` enquanto a thread de prévia está em execução."""
        return self._thread is not None and self._thread.is_alive()

    def iniciar(self) -> None:
        """Inicia a captura da prévia."""
        if self.ativa:
            return
        self._parando.clear()
        self._thread = threading.Thread(
            target=self._laco, name="previa-local", daemon=True
        )
        self._thread.start()
        _registrador.info("Pré-visualização local iniciada (%s fps)", self._fps)

    def parar(self) -> None:
        """Interrompe a captura da prévia."""
        self._parando.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

    def _laco(self) -> None:
        """Captura quadros no intervalo configurado até ser interrompida."""
        capturador = CapturadorTela(self._configuracao, dimensoes=self._dimensoes)
        try:
            capturador.abrir()
        except ErroCapturaTela as erro:
            _registrador.warning("Prévia indisponível: %s", erro)
            if self._ao_erro:
                self._ao_erro(f"Prévia indisponível: {erro}")
            return

        intervalo = 1.0 / self._fps
        try:
            while not self._parando.is_set():
                inicio = time.perf_counter()
                try:
                    quadro = capturador.capturar()
                    self._ao_quadro(bgr_para_rgb(quadro))
                except ErroCapturaTela as erro:
                    _registrador.debug("Quadro de prévia perdido: %s", erro)
                    self._parando.wait(0.25)
                except Exception as erro:  # nunca deixar a thread morrer calada
                    _registrador.warning("Falha na prévia: %s", erro)
                    self._parando.wait(0.5)

                espera = intervalo - (time.perf_counter() - inicio)
                if espera > 0:
                    self._parando.wait(espera)
        finally:
            capturador.fechar()
            _registrador.info("Pré-visualização local encerrada")
