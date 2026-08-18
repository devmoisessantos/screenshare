"""Testes da pré-visualização local da transmissão."""

from __future__ import annotations

import threading
import unittest
from unittest import mock

import numpy as np

from configuracao.configuracoes import ConfiguracaoVideo
from midia.previa import LARGURA_PREVIA, PreVisualizadorTela


class CapturadorFalso:
    """Substitui o :class:`CapturadorTela` real, sem depender de tela."""

    def __init__(self, configuracao: ConfiguracaoVideo, dimensoes=None) -> None:
        self.configuracao = configuracao
        self.dimensoes = dimensoes
        self.aberto = False
        self.fechado = False

    def abrir(self) -> None:
        self.aberto = True

    def fechar(self) -> None:
        self.fechado = True

    def capturar(self) -> np.ndarray:
        largura, altura = self.dimensoes or (16, 9)
        return np.zeros((altura, largura, 3), dtype=np.uint8)


class TestePreVisualizador(unittest.TestCase):
    """Valida as dimensões reduzidas e o ciclo de vida da thread."""

    def test_dimensoes_reduzidas_preservam_proporcao(self) -> None:
        configuracao = ConfiguracaoVideo(resolucao="1080p")
        largura, altura = PreVisualizadorTela._calcular_dimensoes(configuracao)
        self.assertEqual(largura, LARGURA_PREVIA)
        self.assertAlmostEqual(largura / altura, 1920 / 1080, places=2)

    def test_nao_amplia_resolucoes_menores_que_a_previa(self) -> None:
        configuracao = ConfiguracaoVideo(resolucao="480p")
        largura_original = configuracao.dimensoes[0]
        largura, _ = PreVisualizadorTela._calcular_dimensoes(configuracao)
        self.assertLessEqual(largura, largura_original)

    def test_entrega_quadros_e_encerra(self) -> None:
        recebidos: list[np.ndarray] = []
        pronto = threading.Event()

        def ao_quadro(quadro: np.ndarray) -> None:
            recebidos.append(quadro)
            pronto.set()

        previa = PreVisualizadorTela(
            ConfiguracaoVideo(resolucao="720p"), ao_quadro=ao_quadro, fps=60
        )
        with mock.patch("midia.previa.CapturadorTela", CapturadorFalso):
            previa.iniciar()
            self.assertTrue(pronto.wait(timeout=3.0), "nenhum quadro foi entregue")
            self.assertTrue(previa.ativa)
            previa.parar()

        self.assertFalse(previa.ativa)
        self.assertTrue(recebidos)
        # A prévia deve entregar RGB com 3 canais, pronto para a interface.
        self.assertEqual(recebidos[0].shape[2], 3)

    def test_erro_de_captura_e_reportado(self) -> None:
        from midia.captura_tela import ErroCapturaTela

        mensagens: list[str] = []
        aviso = threading.Event()

        class CapturadorQueFalha(CapturadorFalso):
            def abrir(self) -> None:
                raise ErroCapturaTela("monitor indisponível")

        def ao_erro(mensagem: str) -> None:
            mensagens.append(mensagem)
            aviso.set()

        previa = PreVisualizadorTela(
            ConfiguracaoVideo(),
            ao_quadro=lambda _q: None,
            fps=30,
            ao_erro=ao_erro,
        )
        with mock.patch("midia.previa.CapturadorTela", CapturadorQueFalha):
            previa.iniciar()
            self.assertTrue(aviso.wait(timeout=3.0))
            previa.parar()

        self.assertIn("Prévia indisponível", mensagens[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
