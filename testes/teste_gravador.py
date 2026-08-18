"""Testes locais de gravação e clipes sem monitor ou placa de som."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from midia.gravador import (
    AV_DISPONIVEL,
    BufferClipes,
    ConfiguracaoGravacao,
    GerenciadorGravacao,
    Gravador,
    av,
)


def quadro_sintetico(indice: int, largura: int = 320, altura: int = 240) -> np.ndarray:
    """Cria um quadro BGR determinístico sem depender de captura de tela."""
    quadro = np.zeros((altura, largura, 3), dtype=np.uint8)
    quadro[:, :, 0] = (indice * 17) % 255
    quadro[:, :, 1] = (indice * 29) % 255
    quadro[:, :, 2] = (indice * 43) % 255
    return quadro


def bloco_silencio(amostras: int = 1600) -> bytes:
    """Cria PCM mono int16 sem acessar qualquer dispositivo de áudio."""
    return np.zeros(amostras, dtype=np.int16).tobytes()


@unittest.skipUnless(AV_DISPONIVEL, "PyAV não está disponível neste ambiente")
class TesteGravador(unittest.TestCase):
    """Verifica a escrita e leitura de um MP4 real em diretório temporário."""

    def teste_gravacao_pode_ser_reaberta(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            configuracao = ConfiguracaoGravacao(pasta=Path(diretorio), fps=30)
            gravador = Gravador(configuracao)
            caminho_inicial = gravador.iniciar(320, 240)
            for indice in range(15):
                gravador.escrever_video(quadro_sintetico(indice))
                gravador.escrever_audio(bloco_silencio())

            self.assertTrue(gravador.gravando)
            self.assertGreaterEqual(gravador.duracao, 0.45)
            caminho = gravador.parar()

            self.assertEqual(caminho, caminho_inicial)
            self.assertIsNotNone(caminho)
            self.assertTrue(caminho.exists())
            self.assertGreater(caminho.stat().st_size, 0)
            self.assertEqual(caminho.name[:9], "gravacao_")

            with av.open(str(caminho)) as entrada:
                fluxo_video = next(fluxo for fluxo in entrada.streams if fluxo.type == "video")
                self.assertEqual((fluxo_video.width, fluxo_video.height), (320, 240))
                self.assertIsNotNone(entrada.duration)
                self.assertGreaterEqual(entrada.duration / av.time_base, 0.35)


@unittest.skipUnless(AV_DISPONIVEL, "PyAV não está disponível neste ambiente")
class TesteBufferClipes(unittest.TestCase):
    """Verifica o limite circular e a exportação não bloqueante de um clipe."""

    def teste_limite_circular_e_clipe_legivel(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            configuracao = ConfiguracaoGravacao(
                pasta=Path(diretorio), fps=5, segundos_buffer=2
            )
            buffer = BufferClipes(configuracao)
            for indice in range(15):
                buffer.alimentar_video(quadro_sintetico(indice))
                buffer.alimentar_audio(bloco_silencio())

            self.assertEqual(buffer.segundos_disponiveis, 2.0)
            self.assertGreater(buffer.memoria_estimada_bytes, 0)
            caminho = buffer.salvar_clipe(1)

            self.assertIsNotNone(caminho)
            self.assertTrue(caminho.exists())
            self.assertGreater(caminho.stat().st_size, 0)
            self.assertGreater(buffer.segundos_disponiveis, 0.0)
            with av.open(str(caminho)) as entrada:
                fluxo_video = next(fluxo for fluxo in entrada.streams if fluxo.type == "video")
                self.assertEqual((fluxo_video.width, fluxo_video.height), (320, 240))

    def teste_clipe_sem_dados_devolve_nada(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            buffer = BufferClipes(ConfiguracaoGravacao(pasta=Path(diretorio)))
            self.assertIsNone(buffer.salvar_clipe(30))


@unittest.skipUnless(AV_DISPONIVEL, "PyAV não está disponível neste ambiente")
class TesteGerenciadorGravacao(unittest.TestCase):
    """Verifica callbacks de falha e o estado seguro para a interface."""

    def teste_erros_viram_callback_e_estado_acompanha_gravacao(self) -> None:
        eventos: list[str] = []
        erros: list[str] = []
        with tempfile.TemporaryDirectory() as diretorio:
            configuracao = ConfiguracaoGravacao(
                pasta=Path(diretorio), fps=10, segundos_buffer=3
            )
            gerenciador = GerenciadorGravacao(configuracao, eventos.append, erros.append)

            self.assertIsNone(gerenciador.iniciar_gravacao())
            self.assertTrue(erros)
            self.assertFalse(gerenciador.estado()["gravando"])

            gerenciador.ativar_buffer(320, 240)
            caminho = gerenciador.iniciar_gravacao()
            self.assertIsNotNone(caminho)
            for indice in range(6):
                gerenciador.alimentar_video(quadro_sintetico(indice))
                gerenciador.alimentar_audio(bloco_silencio())

            estado = gerenciador.estado()
            self.assertTrue(estado["gravando"])
            self.assertTrue(estado["buffer_ativo"])
            self.assertGreater(estado["segundos_no_buffer"], 0.0)
            self.assertGreater(estado["memoria"], 0)

            gerenciador.alimentar_video("quadro inválido")  # type: ignore[arg-type]
            self.assertGreaterEqual(len(erros), 2)
            salvo = gerenciador.parar_gravacao()

            self.assertEqual(salvo, caminho)
            self.assertTrue(salvo.exists())
            self.assertTrue(eventos)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
