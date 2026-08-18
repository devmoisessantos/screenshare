"""Testes de compressão de vídeo e do controlador adaptativo de qualidade."""

from __future__ import annotations

import unittest

import numpy as np

from midia.compressao import (
    ControladorQualidade,
    ErroCompressao,
    bgr_para_rgb,
    comprimir_jpeg,
    descomprimir_jpeg,
    redimensionar,
)


def quadro_exemplo(largura: int = 320, altura: int = 240) -> np.ndarray:
    """Gera um quadro sintético determinístico para os testes."""
    gerador = np.random.default_rng(42)
    return gerador.integers(0, 256, size=(altura, largura, 3), dtype=np.uint8)


class TesteCompressao(unittest.TestCase):
    """Verifica o ciclo de compressão/descompressão JPEG."""

    def teste_ida_e_volta(self) -> None:
        quadro = quadro_exemplo()
        dados = comprimir_jpeg(quadro, 80)
        self.assertIsInstance(dados, bytes)
        self.assertGreater(len(dados), 0)
        recuperado = descomprimir_jpeg(dados)
        self.assertEqual(recuperado.shape, quadro.shape)

    def teste_qualidade_afeta_tamanho(self) -> None:
        quadro = quadro_exemplo()
        pequeno = comprimir_jpeg(quadro, 20)
        grande = comprimir_jpeg(quadro, 95)
        self.assertLess(len(pequeno), len(grande))

    def teste_qualidade_fora_da_faixa(self) -> None:
        quadro = quadro_exemplo(64, 64)
        self.assertGreater(len(comprimir_jpeg(quadro, 500)), 0)
        self.assertGreater(len(comprimir_jpeg(quadro, -10)), 0)

    def teste_dados_corrompidos(self) -> None:
        with self.assertRaises(ErroCompressao):
            descomprimir_jpeg(b"nao e uma imagem")

    def teste_conversao_de_cores(self) -> None:
        quadro = np.zeros((2, 2, 3), dtype=np.uint8)
        quadro[:, :, 0] = 255  # canal azul em BGR
        convertido = bgr_para_rgb(quadro)
        self.assertEqual(convertido[0, 0, 2], 255)

    def teste_redimensionamento(self) -> None:
        quadro = quadro_exemplo(640, 480)
        reduzido = redimensionar(quadro, 320, 240)
        self.assertEqual(reduzido.shape[:2], (240, 320))
        igual = redimensionar(reduzido, 320, 240)
        self.assertIs(igual, reduzido)


class TesteControladorQualidade(unittest.TestCase):
    """Verifica o ajuste dinâmico de qualidade conforme a latência."""

    def teste_reduz_com_latencia_alta(self) -> None:
        controlador = ControladorQualidade(70, 35, 90, limite_latencia_ms=200)
        controlador.registrar_latencia(250)
        self.assertLess(controlador.qualidade, 70)

    def teste_respeita_minimo(self) -> None:
        controlador = ControladorQualidade(40, 35, 90, limite_latencia_ms=200)
        for _ in range(20):
            controlador.registrar_latencia(900)
        self.assertEqual(controlador.qualidade, 35)

    def teste_recupera_com_latencia_baixa(self) -> None:
        controlador = ControladorQualidade(50, 35, 90, limite_latencia_ms=200)
        for _ in range(10):
            controlador.registrar_latencia(20)
        self.assertGreater(controlador.qualidade, 50)
        self.assertLessEqual(controlador.qualidade, 90)

    def teste_descarte_de_quadros(self) -> None:
        controlador = ControladorQualidade(70, 35, 90, limite_latencia_ms=200)
        controlador.registrar_latencia(100)
        self.assertFalse(controlador.deve_descartar_quadro())
        controlador.registrar_latencia(600)
        self.assertTrue(controlador.deve_descartar_quadro())

    def teste_desabilitado_nao_altera(self) -> None:
        controlador = ControladorQualidade(70, 35, 90, habilitado=False)
        controlador.registrar_latencia(2000)
        self.assertEqual(controlador.qualidade, 70)
        self.assertFalse(controlador.deve_descartar_quadro())


if __name__ == "__main__":
    unittest.main()
