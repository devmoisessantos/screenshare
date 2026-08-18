"""Testes das configurações, persistência e utilidades de rede."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from configuracao.configuracoes import RESOLUCOES, Configuracoes, obter_tema
from utilitarios.rede import (
    formatar_taxa,
    obter_ip_local,
    validar_endereco,
    validar_porta,
)


class TesteConfiguracoes(unittest.TestCase):
    """Verifica padrões, serialização e leitura tolerante a falhas."""

    def teste_valores_padrao(self) -> None:
        configuracoes = Configuracoes()
        self.assertEqual(configuracoes.video.resolucao, "720p")
        self.assertEqual(configuracoes.video.dimensoes, RESOLUCOES["720p"])
        self.assertEqual(configuracoes.rede.porta, 9999)
        self.assertAlmostEqual(configuracoes.video.intervalo_quadro, 1 / 30, places=5)
        self.assertTrue(configuracoes.interface.apelido)

    def teste_persistencia(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            caminho = Path(diretorio) / "configuracoes.json"
            original = Configuracoes()
            original.video.resolucao = "1080p"
            original.rede.porta = 12345
            original.interface.apelido = "Moises"
            original.salvar(caminho)

            recuperada = Configuracoes.carregar(caminho)
            self.assertEqual(recuperada.video.resolucao, "1080p")
            self.assertEqual(recuperada.rede.porta, 12345)
            self.assertEqual(recuperada.interface.apelido, "Moises")

    def teste_arquivo_inexistente_usa_padroes(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            caminho = Path(diretorio) / "ausente.json"
            self.assertEqual(Configuracoes.carregar(caminho).rede.porta, 9999)

    def teste_arquivo_corrompido_usa_padroes(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            caminho = Path(diretorio) / "ruim.json"
            caminho.write_text("{{{ invalido", encoding="utf-8")
            self.assertEqual(Configuracoes.carregar(caminho).rede.porta, 9999)

    def teste_dicionario_parcial(self) -> None:
        configuracoes = Configuracoes.de_dicionario({"video": {"fps": 15}})
        self.assertEqual(configuracoes.video.fps, 15)
        self.assertEqual(configuracoes.rede.porta, 9999)

    def teste_temas(self) -> None:
        self.assertIn("destaque", obter_tema("escuro"))
        self.assertEqual(obter_tema("inexistente"), obter_tema("escuro"))


class TesteRede(unittest.TestCase):
    """Verifica as validações e formatações de rede."""

    def teste_porta_valida(self) -> None:
        self.assertEqual(validar_porta("9999"), 9999)
        self.assertEqual(validar_porta(80), 80)

    def teste_porta_invalida(self) -> None:
        for valor in ("0", "70000", "abc", None):
            with self.assertRaises(ValueError):
                validar_porta(valor)  # type: ignore[arg-type]

    def teste_endereco_valido(self) -> None:
        self.assertEqual(validar_endereco(" 192.168.0.10 "), "192.168.0.10")

    def teste_endereco_vazio(self) -> None:
        with self.assertRaises(ValueError):
            validar_endereco("   ")

    def teste_ip_local(self) -> None:
        self.assertTrue(obter_ip_local())

    def teste_formatar_taxa(self) -> None:
        self.assertIn("Mbps", formatar_taxa(1_000_000))
        self.assertIn("kbps", formatar_taxa(1_000))
        self.assertIn("bps", formatar_taxa(10))


if __name__ == "__main__":
    unittest.main()
