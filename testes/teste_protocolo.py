"""Testes do protocolo binário e da conexão TCP."""

from __future__ import annotations

import socket
import threading
import unittest

from nucleo import protocolo
from nucleo.conexao import Conexao, ConexaoEncerrada
from nucleo.protocolo import (
    TAMANHO_CABECALHO,
    ErroProtocolo,
    TipoMensagem,
    decodificar_json,
    desempacotar_cabecalho,
    empacotar,
    gerar_token,
    mensagem_chat,
    tokens_equivalentes,
)


class TesteEmpacotamento(unittest.TestCase):
    """Verifica a montagem e leitura dos quadros do protocolo."""

    def teste_ida_e_volta(self) -> None:
        carga = b"conteudo binario"
        quadro = empacotar(TipoMensagem.VIDEO, carga)
        tipo, tamanho = desempacotar_cabecalho(quadro[:TAMANHO_CABECALHO])
        self.assertIs(tipo, TipoMensagem.VIDEO)
        self.assertEqual(tamanho, len(carga))
        self.assertEqual(quadro[TAMANHO_CABECALHO:], carga)

    def teste_carga_vazia(self) -> None:
        quadro = empacotar(TipoMensagem.PRONTO)
        tipo, tamanho = desempacotar_cabecalho(quadro)
        self.assertIs(tipo, TipoMensagem.PRONTO)
        self.assertEqual(tamanho, 0)

    def teste_prefixo_invalido(self) -> None:
        quadro = bytearray(empacotar(TipoMensagem.CHAT, b"oi"))
        quadro[0:2] = b"XX"
        with self.assertRaises(ErroProtocolo):
            desempacotar_cabecalho(bytes(quadro[:TAMANHO_CABECALHO]))

    def teste_tipo_desconhecido(self) -> None:
        quadro = bytearray(empacotar(TipoMensagem.CHAT, b""))
        quadro[2] = 199
        with self.assertRaises(ErroProtocolo):
            desempacotar_cabecalho(bytes(quadro))


class TesteCargasJson(unittest.TestCase):
    """Verifica a serialização das mensagens de alto nível."""

    def teste_mensagem_chat(self) -> None:
        dados = decodificar_json(mensagem_chat("João", "Olá, mundo!"))
        self.assertEqual(dados["autor"], "João")
        self.assertEqual(dados["conteudo"], "Olá, mundo!")
        self.assertIn("horario", dados)

    def teste_json_invalido(self) -> None:
        with self.assertRaises(ErroProtocolo):
            decodificar_json(b"nao e json")

    def teste_json_nao_objeto(self) -> None:
        with self.assertRaises(ErroProtocolo):
            decodificar_json(b"[1, 2, 3]")

    def teste_handshake(self) -> None:
        dados = decodificar_json(protocolo.mensagem_handshake("Maria", "abc"))
        self.assertEqual(dados["versao"], protocolo.VERSAO_PROTOCOLO)
        self.assertEqual(dados["apelido"], "Maria")


class TesteToken(unittest.TestCase):
    """Verifica a geração e comparação de tokens de autenticação."""

    def teste_senha_vazia(self) -> None:
        self.assertEqual(gerar_token(""), "")
        self.assertTrue(tokens_equivalentes(gerar_token(""), gerar_token("")))

    def teste_senhas_diferentes(self) -> None:
        self.assertFalse(tokens_equivalentes(gerar_token("a"), gerar_token("b")))

    def teste_senhas_iguais(self) -> None:
        self.assertTrue(tokens_equivalentes(gerar_token("segredo"), gerar_token("segredo")))


class TesteConexao(unittest.TestCase):
    """Testa o envio e a recepção usando um par de sockets reais."""

    def setUp(self) -> None:
        self._escuta = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._escuta.bind(("127.0.0.1", 0))
        self._escuta.listen(1)
        porta = self._escuta.getsockname()[1]

        aceito: list[socket.socket] = []

        def aceitar() -> None:
            soquete, _ = self._escuta.accept()
            aceito.append(soquete)

        thread = threading.Thread(target=aceitar)
        thread.start()
        cliente = socket.create_connection(("127.0.0.1", porta), timeout=5)
        thread.join(timeout=5)

        self.conexao_cliente = Conexao(cliente, ("127.0.0.1", porta))
        self.conexao_servidor = Conexao(aceito[0], ("127.0.0.1", porta))

    def tearDown(self) -> None:
        self.conexao_cliente.fechar()
        self.conexao_servidor.fechar()
        self._escuta.close()

    def teste_envio_e_recepcao(self) -> None:
        self.conexao_cliente.enviar(TipoMensagem.VIDEO, b"\x00\x01\x02")
        tipo, carga = self.conexao_servidor.receber()
        self.assertIs(tipo, TipoMensagem.VIDEO)
        self.assertEqual(carga, b"\x00\x01\x02")

    def teste_envio_json(self) -> None:
        self.conexao_cliente.enviar_json(TipoMensagem.ESTADO, {"microfone": False})
        tipo, carga = self.conexao_servidor.receber()
        self.assertIs(tipo, TipoMensagem.ESTADO)
        self.assertFalse(decodificar_json(carga)["microfone"])

    def teste_carga_grande_recusada(self) -> None:
        self.conexao_servidor._tamanho_maximo_carga = 8  # limite artificial
        self.conexao_cliente.enviar(TipoMensagem.VIDEO, b"0123456789")
        with self.assertRaises(ErroProtocolo):
            self.conexao_servidor.receber()

    def teste_fechamento_detectado(self) -> None:
        self.conexao_cliente.fechar()
        with self.assertRaises(ConexaoEncerrada):
            self.conexao_servidor.receber()

    def teste_contadores_de_bytes(self) -> None:
        self.conexao_cliente.enviar(TipoMensagem.CHAT, b"abc")
        self.conexao_servidor.receber()
        self.assertEqual(self.conexao_cliente.bytes_enviados, TAMANHO_CABECALHO + 3)
        self.assertEqual(self.conexao_servidor.bytes_recebidos, TAMANHO_CABECALHO + 3)


if __name__ == "__main__":
    unittest.main()
