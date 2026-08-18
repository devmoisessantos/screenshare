"""Testes dos utilitários de rede e do diagnóstico de conectividade."""

from __future__ import annotations

import socket
import threading
import unittest
from unittest import mock

from utilitarios import rede


class TesteClassificacaoEnderecos(unittest.TestCase):
    """Valida a classificação usada para orientar o usuário."""

    def test_loopback(self) -> None:
        categoria, _ = rede._classificar("127.0.0.1")
        self.assertEqual(categoria, "loopback")

    def test_rede_local(self) -> None:
        categoria, descricao = rede._classificar("192.168.0.15")
        self.assertEqual(categoria, "local")
        self.assertIn("recomendado", descricao)

    def test_faixa_de_vpn(self) -> None:
        categoria, _ = rede._classificar("100.64.10.2")
        self.assertEqual(categoria, "vpn")

    def test_adaptador_virtual(self) -> None:
        categoria, _ = rede._classificar("172.17.0.5")
        self.assertEqual(categoria, "virtual")

    def test_listagem_ordena_locais_primeiro(self) -> None:
        enderecos = rede.listar_ips_locais()
        self.assertTrue(enderecos)
        categorias = [endereco.categoria for endereco in enderecos]
        self.assertEqual(categorias, sorted(categorias, key=lambda c: {
            "local": 0, "vpn": 1, "virtual": 2, "loopback": 3}[c]))

    def test_endereco_recomendado_nao_e_vazio(self) -> None:
        self.assertTrue(rede.ip_local_recomendado())


class TesteDiagnostico(unittest.TestCase):
    """Valida as mensagens produzidas para cada tipo de falha."""

    def test_porta_aberta(self) -> None:
        servidor = socket.socket()
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        porta = servidor.getsockname()[1]
        aceitador = threading.Thread(target=servidor.accept, daemon=True)
        aceitador.start()
        try:
            resultado = rede.testar_alcance("127.0.0.1", porta, tempo_limite=2.0)
        finally:
            servidor.close()
        self.assertTrue(resultado.alcancavel)
        self.assertEqual(resultado.situacao, "aberta")

    def test_porta_recusada_orienta_iniciar_compartilhamento(self) -> None:
        # Porta reservada e fechada: o sistema local recusa de imediato.
        soquete = socket.socket()
        soquete.bind(("127.0.0.1", 0))
        porta = soquete.getsockname()[1]
        soquete.close()

        resultado = rede.testar_alcance("127.0.0.1", porta, tempo_limite=2.0)
        self.assertFalse(resultado.alcancavel)
        self.assertEqual(resultado.situacao, "recusada")
        self.assertIn("Iniciar compartilhamento", resultado.texto_completo)

    def test_tempo_esgotado_orienta_firewall(self) -> None:
        with mock.patch("socket.socket") as fabrica:
            fabrica.return_value.connect.side_effect = TimeoutError()
            resultado = rede.testar_alcance("10.255.255.1", 9999, tempo_limite=0.1)
        self.assertEqual(resultado.situacao, "tempo_esgotado")
        self.assertIn("firewall", resultado.texto_completo.lower())

    def test_firewall_fora_do_windows_devolve_indefinido(self) -> None:
        with mock.patch("sys.platform", "linux"):
            self.assertIsNone(rede.firewall_liberado(9999))
            sucesso, mensagem = rede.liberar_firewall(9999)
        self.assertFalse(sucesso)
        self.assertIn("ufw", mensagem)


class TesteValidacoes(unittest.TestCase):
    """Valida a separação de endereço/porta usada ao colar o endereço."""

    def test_endereco_com_porta(self) -> None:
        self.assertEqual(
            rede.separar_endereco_porta("192.168.0.5:1234", 9999), ("192.168.0.5", 1234)
        )

    def test_endereco_sem_porta_usa_padrao(self) -> None:
        self.assertEqual(
            rede.separar_endereco_porta(" 192.168.0.5 ", 9999), ("192.168.0.5", 9999)
        )

    def test_porta_nao_numerica_cai_no_padrao(self) -> None:
        self.assertEqual(
            rede.separar_endereco_porta("192.168.0.5:abc", 9999), ("192.168.0.5", 9999)
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TesteEnderecoSemRede(unittest.TestCase):
    """Endereços APIPA (169.254.x.x) nunca devem ser recomendados."""

    def teste_apipa_nao_e_recomendado(self) -> None:
        endereco = rede.EnderecoLocal("169.254.0.21", *rede._classificar("169.254.0.21"))
        self.assertEqual(endereco.categoria, "virtual")
        self.assertFalse(endereco.recomendado)
        self.assertIn("169.254", endereco.descricao)
