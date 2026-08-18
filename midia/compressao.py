"""Compressão e descompressão de quadros de vídeo.

Utiliza codificação JPEG do OpenCV, que oferece um bom equilíbrio entre
velocidade (compressão em poucos milissegundos) e tamanho do quadro.
"""

from __future__ import annotations

import cv2
import numpy as np

from configuracao.configuracoes import LIMITE_LATENCIA_MS


class ErroCompressao(Exception):
    """Falha ao comprimir ou decodificar um quadro."""


def comprimir_jpeg(quadro: np.ndarray, qualidade: int = 70) -> bytes:
    """Comprime um quadro BGR em JPEG.

    Args:
        quadro: imagem no formato BGR (``numpy.ndarray``).
        qualidade: 0 a 100; valores maiores geram imagens melhores e maiores.

    Returns:
        Bytes do JPEG resultante.

    Raises:
        ErroCompressao: se o OpenCV não conseguir codificar o quadro.
    """
    qualidade = int(max(1, min(100, qualidade)))
    sucesso, buffer = cv2.imencode(
        ".jpg", quadro, [int(cv2.IMWRITE_JPEG_QUALITY), qualidade]
    )
    if not sucesso:
        raise ErroCompressao("Falha ao codificar o quadro em JPEG")
    return buffer.tobytes()


def descomprimir_jpeg(dados: bytes) -> np.ndarray:
    """Decodifica bytes JPEG em um quadro BGR.

    Raises:
        ErroCompressao: se os dados não representarem uma imagem válida.
    """
    vetor = np.frombuffer(dados, dtype=np.uint8)
    quadro = cv2.imdecode(vetor, cv2.IMREAD_COLOR)
    if quadro is None:
        raise ErroCompressao("Quadro JPEG corrompido ou incompleto")
    return quadro


def bgr_para_rgb(quadro: np.ndarray) -> np.ndarray:
    """Converte um quadro BGR (OpenCV) para RGB (usado pela GUI)."""
    return cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB)


def redimensionar(quadro: np.ndarray, largura: int, altura: int) -> np.ndarray:
    """Redimensiona o quadro preservando a área útil solicitada."""
    altura_atual, largura_atual = quadro.shape[:2]
    if (largura_atual, altura_atual) == (largura, altura):
        return quadro
    interpolacao = cv2.INTER_AREA if largura_atual > largura else cv2.INTER_LINEAR
    return cv2.resize(quadro, (largura, altura), interpolation=interpolacao)


class ControladorQualidade:
    """Ajusta dinamicamente a qualidade JPEG conforme a latência medida.

    A cada medição de latência (ida e volta), a qualidade é reduzida quando a
    rede está congestionada e recuperada gradualmente quando a latência volta
    a níveis saudáveis. Também indica quando quadros devem ser descartados.
    """

    def __init__(
        self,
        qualidade_inicial: int = 70,
        qualidade_minima: int = 35,
        qualidade_maxima: int = 90,
        limite_latencia_ms: int = LIMITE_LATENCIA_MS,
        habilitado: bool = True,
    ) -> None:
        self.qualidade_minima = int(qualidade_minima)
        self.qualidade_maxima = int(qualidade_maxima)
        self.limite_latencia_ms = int(limite_latencia_ms)
        self.habilitado = bool(habilitado)
        self._qualidade = int(
            max(self.qualidade_minima, min(self.qualidade_maxima, qualidade_inicial))
        )
        self._latencia_ms = 0.0

    @property
    def qualidade(self) -> int:
        """Qualidade JPEG atual."""
        return self._qualidade

    @property
    def latencia_ms(self) -> float:
        """Última latência medida, em milissegundos."""
        return self._latencia_ms

    def registrar_latencia(self, latencia_ms: float) -> int:
        """Informa uma nova medição de latência e devolve a qualidade ajustada."""
        self._latencia_ms = float(latencia_ms)
        if not self.habilitado:
            return self._qualidade
        if latencia_ms > self.limite_latencia_ms * 1.5:
            self._qualidade = max(self.qualidade_minima, self._qualidade - 10)
        elif latencia_ms > self.limite_latencia_ms:
            self._qualidade = max(self.qualidade_minima, self._qualidade - 5)
        elif latencia_ms < self.limite_latencia_ms * 0.5:
            self._qualidade = min(self.qualidade_maxima, self._qualidade + 2)
        return self._qualidade

    def deve_descartar_quadro(self) -> bool:
        """Indica se o próximo quadro deve ser descartado por excesso de lag."""
        return self.habilitado and self._latencia_ms > self.limite_latencia_ms * 2
