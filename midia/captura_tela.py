"""Captura de tela multiplataforma usando a biblioteca ``mss``."""

from __future__ import annotations

from typing import Any

import mss
import numpy as np

from configuracao.configuracoes import ConfiguracaoVideo
from midia.compressao import redimensionar
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)


class ErroCapturaTela(Exception):
    """Falha ao capturar a tela (monitor indisponível, permissão negada...)."""


def listar_monitores() -> list[dict[str, Any]]:
    """Lista os monitores disponíveis.

    O índice 0 da lista ``mss`` representa a área total (todos os monitores);
    os índices seguintes representam monitores individuais.
    """
    try:
        with mss.mss() as captura:
            return [dict(monitor) for monitor in captura.monitors]
    except Exception as erro:  # mss lança exceções variadas por plataforma
        raise ErroCapturaTela(f"Não foi possível listar monitores: {erro}") from erro


def descrever_monitores() -> list[str]:
    """Devolve descrições legíveis dos monitores para exibição na interface."""
    descricoes: list[str] = []
    try:
        monitores = listar_monitores()
    except ErroCapturaTela:
        return ["1 - Monitor principal"]
    for indice, monitor in enumerate(monitores):
        rotulo = "Todos os monitores" if indice == 0 else f"Monitor {indice}"
        descricoes.append(
            f"{indice} - {rotulo} ({monitor.get('width')}x{monitor.get('height')})"
        )
    return descricoes


class CapturadorTela:
    """Captura quadros da tela já redimensionados e no formato BGR.

    A instância de ``mss`` é criada de forma preguiçosa e por thread, pois o
    objeto não é seguro para uso concorrente.

    Args:
        configuracao: parâmetros de vídeo (monitor e resolução).
        dimensoes: largura e altura de saída que substituem a resolução da
            configuração. Usado pela pré-visualização local, que precisa de uma
            imagem menor sem alterar a configuração da transmissão.
    """

    def __init__(
        self,
        configuracao: ConfiguracaoVideo,
        dimensoes: tuple[int, int] | None = None,
    ) -> None:
        self.configuracao = configuracao
        self.dimensoes = dimensoes
        self._captura: mss.base.MSSBase | None = None
        self._regiao: dict[str, int] | None = None

    # -- Ciclo de vida ------------------------------------------------------

    def abrir(self) -> None:
        """Inicializa o contexto de captura e seleciona o monitor configurado."""
        try:
            self._captura = mss.mss()
            monitores = self._captura.monitors
        except Exception as erro:
            raise ErroCapturaTela(f"Não foi possível iniciar a captura: {erro}") from erro

        indice = self.configuracao.monitor
        if indice < 0 or indice >= len(monitores):
            _registrador.warning(
                "Monitor %s indisponível; usando o monitor principal", indice
            )
            indice = 1 if len(monitores) > 1 else 0
        self._regiao = monitores[indice]
        _registrador.info("Capturando região %s", self._regiao)

    def fechar(self) -> None:
        """Libera os recursos de captura."""
        if self._captura is not None:
            try:
                self._captura.close()
            except Exception:  # pragma: no cover
                pass
            self._captura = None

    # -- Captura ------------------------------------------------------------

    def capturar(self) -> np.ndarray:
        """Captura um quadro e devolve a imagem BGR redimensionada.

        Raises:
            ErroCapturaTela: se a captura falhar.
        """
        if self._captura is None or self._regiao is None:
            self.abrir()
        assert self._captura is not None and self._regiao is not None

        try:
            bruto = self._captura.grab(self._regiao)
        except Exception as erro:
            raise ErroCapturaTela(f"Falha ao capturar a tela: {erro}") from erro

        # mss entrega BGRA; descartamos o canal alfa para reduzir dados.
        quadro = np.asarray(bruto, dtype=np.uint8)[:, :, :3]
        largura, altura = self.dimensoes or self.configuracao.dimensoes
        return redimensionar(quadro, largura, altura)

    def __enter__(self) -> CapturadorTela:
        self.abrir()
        return self

    def __exit__(self, *_excecao: object) -> None:
        self.fechar()
