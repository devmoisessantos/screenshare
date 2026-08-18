"""Testes das faixas WebRTC com fontes e dispositivos dublês."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import av
import numpy as np
from aiortc import VideoStreamTrack

from midia import captura_audio
from midia.faixas_webrtc import ConsumidorFaixaVideo, FaixaMicrofone, FaixaTela
from midia.fontes import FonteCaptura


class _CapturaMssFalsa:
    """Dublê do mss que devolve uma imagem BGRA pequena."""

    def grab(self, _regiao: dict[str, int]) -> np.ndarray:
        quadro = np.zeros((10, 20, 4), dtype=np.uint8)
        quadro[:, :, 1] = 127
        quadro[:, :, 3] = 255
        return quadro


class _FaixaVideoFalsa(VideoStreamTrack):
    """Faixa remota que entrega um quadro e espera no seguinte."""

    def __init__(self) -> None:
        super().__init__()
        self._entregou = False
        self._espera = asyncio.Event()

    async def recv(self) -> av.VideoFrame:
        if self._entregou:
            await self._espera.wait()
        self._entregou = True
        return av.VideoFrame.from_ndarray(np.zeros((4, 6, 3), dtype=np.uint8), format="bgr24")


class TesteFaixas(unittest.IsolatedAsyncioTestCase):
    """Garante que as faixas preservam contrato sem recursos nativos."""

    async def test_faixa_tela_tem_dimensoes_e_timestamps_crescentes(self) -> None:
        fonte = FonteCaptura(
            identificador="monitor:1",
            titulo="Monitor 1",
            tipo="monitor",
            regiao={"left": 0, "top": 0, "width": 20, "height": 10},
            indice_monitor=1,
            identificador_janela=None,
        )
        faixa = FaixaTela(fonte, largura=64, altura=36, fps=20)
        with patch("midia.faixas_webrtc.mss.mss", return_value=_CapturaMssFalsa()):
            primeiro = await faixa.recv()
            segundo = await faixa.recv()
        faixa.parar()

        self.assertEqual((primeiro.width, primeiro.height), (64, 36))
        self.assertEqual(primeiro.format.name, "bgr24")
        self.assertLess(primeiro.pts, segundo.pts)
        self.assertEqual(primeiro.time_base, segundo.time_base)

    async def test_faixa_microfone_muda_entrega_silencio(self) -> None:
        with patch.object(captura_audio, "AUDIO_DISPONIVEL", False):
            faixa = FaixaMicrofone()
            faixa.mudo = True
            quadro = await faixa.recv()
        faixa.parar()

        amostras = quadro.to_ndarray()
        self.assertEqual(quadro.samples, 960)
        self.assertEqual(quadro.sample_rate, 48000)
        self.assertTrue(np.all(amostras == 0))

    async def test_consumidor_video_entrega_quadros_convertidos(self) -> None:
        quadros: list[np.ndarray] = []
        consumidor = ConsumidorFaixaVideo(_FaixaVideoFalsa(), quadros.append)

        for _ in range(10):
            if quadros:
                break
            await asyncio.sleep(0.01)
        consumidor.parar()
        await asyncio.sleep(0)

        self.assertEqual(len(quadros), 1)
        self.assertEqual(quadros[0].shape, (4, 6, 3))
