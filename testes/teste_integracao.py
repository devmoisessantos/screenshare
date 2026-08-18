"""Teste de integração servidor↔cliente sobre localhost.

A captura de tela e o áudio são substituídos por dublês, permitindo validar
handshake, autenticação por senha e chat bidirecional em qualquer ambiente
(inclusive servidores sem monitor ou placa de som).
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from aplicacao.cliente import ClienteVisualizador, ErroCliente
from aplicacao.servidor import ServidorCompartilhamento
from configuracao.configuracoes import Configuracoes
from nucleo.protocolo import TipoMensagem
from nucleo.sessao import Retornos, Sessao
from utilitarios.rede import porta_disponivel


def configuracoes_de_teste(porta: int, senha: str = "") -> Configuracoes:
    """Cria configurações isoladas, sem áudio, para os testes."""
    configuracoes = Configuracoes()
    configuracoes.rede.porta = porta
    configuracoes.rede.senha = senha
    configuracoes.rede.endereco_escuta = "127.0.0.1"
    configuracoes.rede.intervalo_ping = 1.0
    configuracoes.rede.tentativas_reconexao = 0
    configuracoes.audio.ativo = False
    configuracoes.interface.apelido = "TesteAutomatizado"
    return configuracoes


def porta_livre(inicio: int = 45000) -> int:
    """Procura uma porta TCP livre para o teste."""
    for porta in range(inicio, inicio + 200):
        if porta_disponivel(porta, "127.0.0.1"):
            return porta
    raise RuntimeError("Nenhuma porta livre encontrada")


class TesteIntegracao(unittest.TestCase):
    """Valida o fluxo completo de conexão entre host e espectador."""

    def setUp(self) -> None:
        # Substitui o envio de vídeo por um laço inerte e desativa o áudio.
        self._patches = [
            mock.patch.object(Sessao, "_laco_video", lambda self: None),
            mock.patch.object(Sessao, "_laco_audio", lambda self: None),
            mock.patch.object(Sessao, "_iniciar_reproducao_audio", lambda self: None),
        ]
        for patch in self._patches:
            patch.start()
        self.porta = porta_livre()
        self.servidor: ServidorCompartilhamento | None = None
        self.cliente: ClienteVisualizador | None = None

    def tearDown(self) -> None:
        if self.cliente is not None:
            self.cliente.desconectar()
        if self.servidor is not None:
            self.servidor.parar()
        for patch in self._patches:
            patch.stop()
        time.sleep(0.1)

    # -- Casos de teste -----------------------------------------------------

    def teste_conexao_e_chat_bidirecional(self) -> None:
        recebidas_host: list[dict] = []
        recebidas_cliente: list[dict] = []
        evento_host = threading.Event()
        evento_cliente = threading.Event()

        configuracoes_servidor = configuracoes_de_teste(self.porta)
        self.servidor = ServidorCompartilhamento(
            configuracoes=configuracoes_servidor,
            retornos=Retornos(
                ao_chat=lambda dados: (recebidas_host.append(dados), evento_host.set())
            ),
        )
        self.servidor.iniciar()

        configuracoes_cliente = configuracoes_de_teste(self.porta)
        configuracoes_cliente.interface.apelido = "Espectador"
        self.cliente = ClienteVisualizador(
            configuracoes=configuracoes_cliente,
            retornos=Retornos(
                ao_chat=lambda dados: (
                    recebidas_cliente.append(dados),
                    evento_cliente.set(),
                )
            ),
        )
        self.cliente.conectar("127.0.0.1", self.porta)

        self.assertTrue(self.cliente.conectado)
        self.assertEqual(
            self.cliente.informacoes_host.get("apelido"), "TesteAutomatizado"
        )

        # Espectador -> host
        self.assertTrue(self.cliente.sessao.enviar_chat("Olá, host!"))
        self.assertTrue(evento_host.wait(timeout=5))
        self.assertEqual(recebidas_host[0]["conteudo"], "Olá, host!")
        self.assertEqual(recebidas_host[0]["autor"], "Espectador")

        # Host -> espectador
        self.assertIsNotNone(self.servidor.sessao)
        self.assertTrue(self.servidor.sessao.enviar_chat("Consegue ver?"))
        self.assertTrue(evento_cliente.wait(timeout=5))
        self.assertEqual(recebidas_cliente[0]["conteudo"], "Consegue ver?")

    def teste_senha_incorreta_e_recusada(self) -> None:
        self.servidor = ServidorCompartilhamento(
            configuracoes=configuracoes_de_teste(self.porta, senha="correta")
        )
        self.servidor.iniciar()

        self.cliente = ClienteVisualizador(
            configuracoes=configuracoes_de_teste(self.porta, senha="errada")
        )
        with self.assertRaises(ErroCliente):
            self.cliente.conectar("127.0.0.1", self.porta)

    def teste_senha_correta_e_aceita(self) -> None:
        self.servidor = ServidorCompartilhamento(
            configuracoes=configuracoes_de_teste(self.porta, senha="segredo")
        )
        self.servidor.iniciar()

        self.cliente = ClienteVisualizador(
            configuracoes=configuracoes_de_teste(self.porta, senha="segredo")
        )
        self.cliente.conectar("127.0.0.1", self.porta)
        self.assertTrue(self.cliente.conectado)

    def teste_transmissao_de_video_simulada(self) -> None:
        quadros: list[bytes] = []
        evento = threading.Event()

        self.servidor = ServidorCompartilhamento(
            configuracoes=configuracoes_de_teste(self.porta)
        )
        self.servidor.iniciar()

        self.cliente = ClienteVisualizador(
            configuracoes=configuracoes_de_teste(self.porta),
            retornos=Retornos(
                ao_video=lambda dados: (quadros.append(dados), evento.set())
            ),
        )
        self.cliente.conectar("127.0.0.1", self.porta)

        self.servidor.sessao.conexao.enviar(TipoMensagem.VIDEO, b"quadro-falso")
        self.assertTrue(evento.wait(timeout=5))
        self.assertEqual(quadros[0], b"quadro-falso")

    def teste_segundo_espectador_e_recusado(self) -> None:
        self.servidor = ServidorCompartilhamento(
            configuracoes=configuracoes_de_teste(self.porta)
        )
        self.servidor.iniciar()

        self.cliente = ClienteVisualizador(
            configuracoes=configuracoes_de_teste(self.porta)
        )
        self.cliente.conectar("127.0.0.1", self.porta)

        segundo = ClienteVisualizador(configuracoes=configuracoes_de_teste(self.porta))
        with self.assertRaises(ErroCliente):
            segundo.conectar("127.0.0.1", self.porta)

    def teste_desconexao_encerra_sessao_no_host(self) -> None:
        self.servidor = ServidorCompartilhamento(
            configuracoes=configuracoes_de_teste(self.porta)
        )
        self.servidor.iniciar()

        self.cliente = ClienteVisualizador(
            configuracoes=configuracoes_de_teste(self.porta)
        )
        self.cliente.conectar("127.0.0.1", self.porta)
        self.cliente.desconectar()
        self.cliente = None

        for _ in range(50):
            if self.servidor.sessao is None:
                break
            time.sleep(0.1)
        self.assertIsNone(self.servidor.sessao)


if __name__ == "__main__":
    unittest.main()
