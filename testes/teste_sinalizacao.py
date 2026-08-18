"""Testes de integração do protocolo WebSocket de sinalização."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable
from typing import Any

from aiohttp import web

from nucleo.sinalizacao import ClienteSinalizacao
from servidor_sinalizacao.servidor import LIMITE_PARTICIPANTES, ServidorSinalizacao


class TesteSinalizacaoIntegrada(unittest.IsolatedAsyncioTestCase):
    """Sobe um servidor real em porta livre e conecta clientes reais."""

    async def asyncSetUp(self) -> None:
        self.servidor = ServidorSinalizacao()
        self.aplicacao = self.servidor.criar_aplicacao()
        self.executor = web.AppRunner(self.aplicacao)
        await self.executor.setup()
        self.site = web.TCPSite(self.executor, "127.0.0.1", 0)
        await self.site.start()
        soquete = self.site._server.sockets[0]  # type: ignore[union-attr]
        porta = soquete.getsockname()[1]
        self.url = f"ws://127.0.0.1:{porta}/ws"
        self.clientes: list[ClienteSinalizacao] = []

    async def asyncTearDown(self) -> None:
        for cliente in self.clientes:
            await cliente.fechar()
        await self.executor.cleanup()

    def criar_cliente(self, **argumentos: Any) -> ClienteSinalizacao:
        """Instancia um cliente ligado ao servidor temporário."""
        cliente = ClienteSinalizacao(self.url, **argumentos)
        self.clientes.append(cliente)
        return cliente

    async def aguardar(self, condicao: Callable[[], bool], mensagem: str = "") -> None:
        """Espera uma condição assíncrona sem depender de tempos fixos."""
        for _ in range(100):
            if condicao():
                return
            await asyncio.sleep(0.01)
        self.fail(mensagem or "A condição esperada não foi atingida.")

    async def teste_entrada_participantes_sinais_e_saida(self) -> None:
        """Dois clientes entram, trocam sinais nos dois sentidos e um sai."""
        entradas_alice: list[tuple[str, str]] = []
        saidas_alice: list[str] = []
        sinais_alice: list[tuple[str, dict[str, Any]]] = []
        sinais_bruno: list[tuple[str, dict[str, Any]]] = []

        alice = self.criar_cliente(
            ao_entrou=lambda identificador, apelido: entradas_alice.append(
                (identificador, apelido)
            ),
            ao_saiu=saidas_alice.append,
            ao_sinal=lambda origem, dados: sinais_alice.append((origem, dados)),
        )
        bruno = self.criar_cliente(
            ao_sinal=lambda origem, dados: sinais_bruno.append((origem, dados))
        )

        self.assertTrue(await alice.conectar())
        self.assertTrue(await alice.entrar(" sala 01 ", "Alice"))
        await self.aguardar(lambda: alice.id_local is not None)
        id_alice = alice.id_local

        self.assertTrue(await bruno.conectar())
        self.assertTrue(await bruno.entrar("sAlA01", "Bruno"))
        await self.aguardar(lambda: bruno.id_local is not None)
        id_bruno = bruno.id_local
        await self.aguardar(lambda: len(entradas_alice) == 1)

        self.assertEqual(entradas_alice[0][1], "Bruno")
        self.assertEqual(bruno.participantes, [{"id": id_alice, "apelido": "Alice"}])
        self.assertEqual(alice.participantes, [{"id": id_bruno, "apelido": "Bruno"}])

        oferta = {"tipo": "oferta", "sdp": "oferta-de-alice"}
        resposta = {"tipo": "resposta", "sdp": "resposta-de-bruno"}
        self.assertTrue(await alice.enviar_sinal(id_bruno or "", oferta))
        self.assertTrue(await bruno.enviar_sinal(id_alice or "", resposta))
        await self.aguardar(lambda: sinais_alice == [(id_bruno, resposta)])
        await self.aguardar(lambda: sinais_bruno == [(id_alice, oferta)])

        self.assertTrue(await bruno.sair())
        await self.aguardar(lambda: saidas_alice == [id_bruno])
        self.assertEqual(alice.participantes, [])
        self.assertEqual(len(self.servidor.salas), 1)

    async def teste_senha_incorreta(self) -> None:
        """Uma sala protegida rejeita cliente que informa senha diferente."""
        erros: list[tuple[str, str]] = []
        criador = self.criar_cliente()
        invasor = self.criar_cliente(ao_erro=lambda codigo, mensagem: erros.append((codigo, mensagem)))

        self.assertTrue(await criador.entrar("senha1", "Criador", "correta"))
        await self.aguardar(lambda: criador.id_local is not None)
        self.assertTrue(await invasor.entrar("senha1", "Invasor", "incorreta"))
        await self.aguardar(lambda: bool(erros))

        self.assertEqual(erros[0][0], "SENHA_INCORRETA")
        self.assertIsNone(invasor.id_local)
        self.assertEqual(len(criador.participantes), 0)

    async def teste_sala_cheia(self) -> None:
        """A sétima conexão recebe o erro previsto para sala de seis pessoas."""
        participantes: list[ClienteSinalizacao] = []
        for numero in range(LIMITE_PARTICIPANTES):
            cliente = self.criar_cliente()
            participantes.append(cliente)
            self.assertTrue(await cliente.entrar("lotada", f"Pessoa {numero}"))
            await self.aguardar(lambda cliente=cliente: cliente.id_local is not None)

        erros: list[tuple[str, str]] = []
        excedente = self.criar_cliente(ao_erro=lambda codigo, mensagem: erros.append((codigo, mensagem)))
        self.assertTrue(await excedente.entrar("lotada", "Excedente"))
        await self.aguardar(lambda: bool(erros))

        self.assertEqual(erros[0][0], "SALA_CHEIA")
        self.assertIsNone(excedente.id_local)
        self.assertEqual(len(participantes[-1].participantes), LIMITE_PARTICIPANTES - 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
