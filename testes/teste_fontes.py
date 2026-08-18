"""Testes da enumeração de fontes de captura."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from midia import fontes


class _CapturaFalsa:
    """Dublê do contexto mss que informa dois monitores."""

    monitors = [
        {"left": -100, "top": 0, "width": 2020, "height": 1080},
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": -100, "top": 0, "width": 100, "height": 1080},
    ]

    def __enter__(self) -> _CapturaFalsa:
        return self

    def __exit__(self, *_argumentos: object) -> None:
        return None


class TesteFontes(unittest.TestCase):
    """Cobre fontes que não dependem de um monitor físico."""

    def test_lista_area_de_trabalho_e_monitores(self) -> None:
        with (
            patch.object(fontes.mss, "mss", return_value=_CapturaFalsa()),
            patch.object(fontes, "JANELAS_DISPONIVEIS", False),
        ):
            fontes_encontradas = fontes.listar_fontes()

        self.assertEqual(len(fontes_encontradas), 3)
        self.assertEqual(fontes_encontradas[0].titulo, "Toda a área de trabalho")
        self.assertEqual(fontes_encontradas[0].tipo, "tela_inteira")
        self.assertEqual(fontes_encontradas[1].indice_monitor, 1)
        self.assertEqual(fontes_encontradas[2].regiao["left"], -100)

    def test_sem_suporte_a_janelas_nao_lanca_erro(self) -> None:
        with (
            patch.object(fontes, "_listar_monitores", return_value=[]),
            patch.object(fontes, "JANELAS_DISPONIVEIS", False),
        ):
            fontes_encontradas = fontes.listar_fontes()

        self.assertEqual(len(fontes_encontradas), 1)
        self.assertEqual(fontes_encontradas[0].tipo, "tela_inteira")
        self.assertIsNone(fontes_encontradas[0].regiao)
