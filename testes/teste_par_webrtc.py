"""Teste de negociação WebRTC em memória entre dois pares."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from nucleo.par_webrtc import ParRemoto, montar_configuracao_ice


class TesteParWebRTC(unittest.IsolatedAsyncioTestCase):
    """Valida uma conexão real sem STUN, TURN ou rede externa."""

    async def test_negociacao_mensagem_e_encerramento(self) -> None:
        """Dois pares negociam, trocam dados e encerram sem falhas."""
        mensagens: list[dict[str, Any]] = []
        estados_a: list[str] = []
        estados_b: list[str] = []
        encerrados: list[str] = []
        mensagem_recebida = asyncio.Event()
        configuracao = montar_configuracao_ice([])

        async def enviar_para_b(dados: dict[str, Any]) -> None:
            await par_b.receber_sinal(dados)

        async def enviar_para_a(dados: dict[str, Any]) -> None:
            await par_a.receber_sinal(dados)

        def ao_receber_mensagem(dados: dict[str, Any]) -> None:
            mensagens.append(dados)
            mensagem_recebida.set()

        par_a = ParRemoto(
            "par-b",
            "Bia",
            configuracao,
            True,
            enviar_para_b,
            lambda faixa: None,
            lambda faixa: None,
            estados_a.append,
            lambda dados: None,
            lambda: encerrados.append("a"),
        )
        par_b = ParRemoto(
            "par-a",
            "Ana",
            configuracao,
            False,
            enviar_para_a,
            lambda faixa: None,
            lambda faixa: None,
            estados_b.append,
            ao_receber_mensagem,
            lambda: encerrados.append("b"),
        )

        try:
            await par_a.iniciar()
            await self._esperar_conexao(par_a, par_b)

            self.assertTrue(par_a.enviar_dados({"tipo": "controle", "acao": "ping"}))
            await asyncio.wait_for(mensagem_recebida.wait(), timeout=5)
            self.assertEqual(mensagens, [{"tipo": "controle", "acao": "ping"}])
            self.assertIn("connected", estados_a)
            self.assertIn("connected", estados_b)

            estatisticas = await par_a.estatisticas()
            self.assertEqual(
                set(estatisticas),
                {"bitrate_estimado", "pacotes_perdidos", "rtt", "resolucao"},
            )
        finally:
            await par_a.encerrar()
            await par_b.encerrar()

        self.assertEqual(par_a.estado, "closed")
        self.assertEqual(par_b.estado, "closed")
        self.assertFalse(par_a.conectado)
        self.assertCountEqual(encerrados, ["a", "b"])

    async def _esperar_conexao(self, par_a: ParRemoto, par_b: ParRemoto) -> None:
        """Aguarda os dois lados terminarem o handshake local."""
        for _ in range(100):
            if par_a.conectado and par_b.conectado:
                return
            await asyncio.sleep(0.05)
        self.fail(f"Conexão não estabelecida: {par_a.estado}, {par_b.estado}")
