"""Testes headless-tolerantes dos componentes visuais da chamada."""

from __future__ import annotations

import tkinter as tk
import unittest
from unittest import mock

from configuracao.configuracoes import obter_tema
from interface.chat_rico import ChatRico
from interface.emojis import RenderizadorEmojis
from interface.painel_participantes import PainelParticipantes, cor_do_apelido, iniciais
from interface.seletor_fonte import CartaoFonte, SeletorFonte, _imagem_vazia
from interface.tema import aplicar_tema
from midia.fontes import FonteCaptura
from nucleo.chamada import Participante


class TesteInterfaceChamada(unittest.TestCase):
    """Valida widgets somente quando o Tk consegue abrir uma janela."""

    def setUp(self) -> None:
        """Cria a janela de teste ou pula em um ambiente sem servidor gráfico."""
        try:
            self.raiz = tk.Tk()
        except tk.TclError as erro:
            self.skipTest(f"Tk indisponível: {erro}")
        self.raiz.withdraw()
        self.paleta = aplicar_tema(self.raiz)
        self.addCleanup(self.raiz.destroy)

    @staticmethod
    def fonte(titulo: str = "Monitor de teste") -> FonteCaptura:
        """Devolve uma fonte de captura simples para os cartões de teste."""
        return FonteCaptura(
            identificador="monitor:1",
            titulo=titulo,
            tipo="monitor",
            regiao={"left": 0, "top": 0, "width": 800, "height": 600},
            indice_monitor=1,
            identificador_janela=None,
        )

    def test_painel_calcula_avatares_e_sincroniza_linhas(self) -> None:
        """Mantém cor estável, iniciais corretas e remove linhas ausentes."""
        self.assertEqual(cor_do_apelido("Ana"), cor_do_apelido("Ana"))
        self.assertIn(cor_do_apelido(""), ("#5865f2",))
        self.assertEqual(iniciais("ana"), "AN")
        self.assertEqual(iniciais("Ana Maria"), "AM")
        self.assertEqual(iniciais("  "), "?")

        painel = PainelParticipantes(self.raiz, self.paleta)
        painel.pack()
        participantes = [
            Participante("eu", "Eu", eu=True),
            Participante("ana", "Ana", microfone_ativo=False),
        ]
        painel.atualizar(participantes)
        self.raiz.update_idletasks()
        linha_ana = painel._linhas["ana"]

        self.assertEqual(len(painel._linhas), 2)
        self.assertEqual(painel._titulo.cget("text"), "Participantes (2)")
        painel.atualizar([participantes[0]])
        self.assertEqual(list(painel._linhas), ["eu"])
        self.assertFalse(linha_ana.winfo_exists())

    def test_chat_adiciona_mensagens_envia_atalho_e_alterna_estado(self) -> None:
        """Registra mensagens e converte atalhos digitados antes de chamar o callback."""
        enviados: list[str] = []
        chat = ChatRico(
            self.raiz,
            self.paleta,
            enviados.append,
            renderizador=RenderizadorEmojis(arquivo_fonte=None),
        )
        chat.pack()
        chat.adicionar_mensagem("Ana", "Olá", proprio=False)
        chat.adicionar_sistema("Ana entrou")
        chat.adicionar_erro("Falha de teste")
        chat._entrada.insert(0, ":ok:")
        chat._enviar()

        historico = chat._historico.get("1.0", "end-1c")
        self.assertIn("Ana: Olá", historico)
        self.assertIn("- Ana entrou", historico)
        self.assertIn("! Falha de teste", historico)
        self.assertEqual(enviados, ["👍"])
        self.assertEqual(chat._entrada.get(), "")
        chat.definir_habilitado(False)
        self.assertEqual(str(chat._entrada.cget("state")), "disabled")
        chat.definir_habilitado(True)
        self.assertEqual(str(chat._entrada.cget("state")), "normal")

    def test_seletor_monta_fontes_vazias_e_permite_selecao(self) -> None:
        """Cria cartões sem captura real e atualiza a seleção da fonte."""
        imagem = _imagem_vazia(obter_tema("escuro"))
        self.assertEqual(imagem.size, (208, 117))
        self.assertEqual(CartaoFonte._encurtar("a" * 60), "a" * 43 + "...")

        fonte = self.fonte("Monitor com um título bastante longo para validar a descrição")
        with (
            mock.patch("interface.seletor_fonte.listar_fontes", return_value=[fonte]),
            mock.patch.object(SeletorFonte, "_carregar_miniaturas"),
        ):
            seletor = SeletorFonte(self.raiz, self.paleta)
            self.addCleanup(lambda: seletor.winfo_exists() and seletor.fechar())
            self.assertEqual(len(seletor._cartoes), 1)
            self.assertEqual(seletor._cartoes[0]._descricao(), "Monitor - 800x600")
            self.assertIs(seletor._fonte_escolhida, fonte)
            seletor.atualizar_fontes()
            seletor._selecionar(fonte)

        self.assertIs(seletor._fonte_escolhida, fonte)
        self.assertEqual(str(seletor._botao_confirmar.cget("state")), "normal")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
