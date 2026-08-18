"""Testes da criação e interpretação de convites."""

from __future__ import annotations

import unittest

from nucleo.convite import (
    CODIGO_TAMANHO,
    Convite,
    ErroConvite,
    codificar_sdp,
    decodificar_sdp,
    gerar_codigo_sala,
    interpretar,
)


class TesteConvite(unittest.TestCase):
    """Garante os formatos públicos de convite."""

    def test_gerar_codigo_sala(self) -> None:
        """O código tem tamanho fixo e não contém caracteres ambíguos."""
        codigo = gerar_codigo_sala()

        self.assertEqual(len(codigo), CODIGO_TAMANHO)
        self.assertNotRegex(codigo, r"[O0I1L]")

    def test_link_faz_ida_e_volta(self) -> None:
        """Link da sala preserva os dados de internet."""
        convite = Convite(
            codigo="ABC234",
            servidor="wss://exemplo.com/ws",
            senha="segredo 2",
        )

        interpretado = interpretar(convite.link)

        self.assertEqual(interpretado, convite)
        self.assertIn("Codigo da sala: ABC234", convite.texto_amigavel)
        self.assertTrue(convite.texto_amigavel.isascii())

    def test_codigo_puro_e_endereco_local(self) -> None:
        """Código puro e os formatos IP locais são aceitos."""
        por_codigo = interpretar("abc234")
        por_ip_porta = interpretar("192.168.10.2:5000")
        por_ip = interpretar("10.0.0.5")

        self.assertEqual(por_codigo.codigo, "ABC234")
        self.assertEqual(por_codigo.modo, "internet")
        self.assertEqual(por_ip_porta.modo, "local")
        self.assertEqual(por_ip_porta.endereco, "192.168.10.2:5000")
        self.assertEqual(por_ip.endereco, "10.0.0.5")
        self.assertEqual(interpretar(por_ip_porta.link), por_ip_porta)

    def test_formatos_invalidos_levantam_erro_em_portugues(self) -> None:
        """Entradas desconhecidas e códigos ambíguos são recusados."""
        for valor in ("", "ABC01L", "999.999.1.1", "192.168.1.2:70000"):
            with self.subTest(valor=valor), self.assertRaisesRegex(
                ErroConvite, "convite|Informe|reconhecido"
            ):
                interpretar(valor)

    def test_sdp_manual_faz_ida_e_volta(self) -> None:
        """Oferta e resposta manuais mantêm o tipo e o conteúdo SDP."""
        sdp = "v=0\r\no=teste 1 1 IN IP4 127.0.0.1\r\ns=-\r\n"

        blob = codificar_sdp(sdp, "oferta")

        self.assertTrue(blob.startswith("SS1-"))
        self.assertEqual(decodificar_sdp(blob), (sdp, "oferta"))
        with self.assertRaises(ErroConvite):
            decodificar_sdp("SS1-invalido")
