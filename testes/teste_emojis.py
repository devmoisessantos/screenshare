"""Testes do catálogo, atalhos e renderização de emojis."""

from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from interface import emojis


class TesteAtalhosEFontes(unittest.TestCase):
    """Valida componentes que não exigem uma janela Tk."""

    def test_aplicar_atalhos_converte_varios_e_prioriza_o_mais_longo(self) -> None:
        """Substitui todos os atalhos, sem consumir primeiro os menores."""
        texto = emojis.aplicar_atalhos(
            "xxx xx x :) <3 :fogo:",
            {"x": "curto", "xx": "medio", "xxx": "longo"},
        )

        self.assertEqual(texto, "longo medio curto :) <3 :fogo:")
        self.assertEqual(
            emojis.aplicar_atalhos(":) <3 :fogo:"),
            f"{emojis.ATALHOS_EMOJI[':)']} {emojis.ATALHOS_EMOJI['<3']} "
            f"{emojis.ATALHOS_EMOJI[':fogo:']}",
        )

    def test_catalogo_tem_caracteres(self) -> None:
        """Mantém ao menos um emoji conhecido para a varredura do chat."""
        self.assertTrue(emojis.CARACTERES_CATALOGO)
        self.assertIn(emojis.ATALHOS_EMOJI[":)"], emojis.CARACTERES_CATALOGO)

    def test_localizar_fonte_emoji_encontra_arquivo_configurado(self) -> None:
        """Procura a primeira fonte existente da plataforma atual."""
        with tempfile.TemporaryDirectory() as diretorio:
            fonte = Path(diretorio) / "emoji.ttf"
            fonte.touch()
            caminhos = {"linux": (str(fonte),)}
            with (
                mock.patch.object(emojis, "CAMINHOS_FONTE_EMOJI", caminhos),
                mock.patch.object(emojis.sys, "platform", "linux"),
            ):
                self.assertEqual(emojis.localizar_fonte_emoji(), fonte)

    def test_localizar_fonte_emoji_devolve_none_sem_arquivos(self) -> None:
        """Não inventa uma fonte quando os caminhos configurados não existem."""
        caminhos = {"linux": ("/nao/existe/fonte-emoji.ttf",)}
        with (
            mock.patch.object(emojis, "CAMINHOS_FONTE_EMOJI", caminhos),
            mock.patch.object(emojis.sys, "platform", "linux"),
        ):
            self.assertIsNone(emojis.localizar_fonte_emoji())


class TesteEmojisComTk(unittest.TestCase):
    """Valida integrações que precisam de um servidor gráfico Tk."""

    def setUp(self) -> None:
        """Cria uma raiz Tk ou pula o teste em ambiente sem tela."""
        try:
            self.raiz = tk.Tk()
        except tk.TclError as erro:
            self.skipTest(f"Tk indisponível: {erro}")
        self.raiz.withdraw()
        self.addCleanup(self.raiz.destroy)

    def test_texto_suportado_pelo_tk_mede_caractere_basico(self) -> None:
        """Confirma que a medição de texto disponível no Tk é aceita."""
        self.assertTrue(emojis.texto_suportado_pelo_tk(self.raiz, "A"))

    def test_renderizador_cria_e_reutiliza_imagem(self) -> None:
        """Renderiza uma imagem Tk e a conserva no cache por tamanho."""
        candidatas = (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        )
        fonte = next((item for item in candidatas if item.exists()), None)
        if fonte is None:
            self.skipTest("Nenhuma fonte TrueType de teste está disponível.")

        renderizador = emojis.RenderizadorEmojis(fonte)
        imagem = renderizador.imagem("A")

        self.assertIsNotNone(imagem)
        self.assertIs(imagem, renderizador.imagem("A"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
