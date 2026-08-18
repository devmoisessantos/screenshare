"""Testes do orquestrador de chamadas sem abrir conexões de rede."""

from __future__ import annotations

import unittest

from configuracao.configuracoes import Configuracoes
from nucleo.chamada import Chamada, Participante, ResumoChamada, RetornosChamada


class TesteChamada(unittest.TestCase):
    """Valida os eventos e as ações síncronas da chamada."""

    def criar_chamada(self, retornos: RetornosChamada | None = None) -> Chamada:
        """Cria uma chamada sem iniciar sua thread nem conectar ao servidor."""
        return Chamada(Configuracoes(), retornos)

    @staticmethod
    def agendador_falso(destino: list[str]):
        """Fecha corrotinas recebidas para os testes não deixarem avisos."""

        def agendar(corrotina) -> None:
            destino.append(corrotina.cr_code.co_name)
            corrotina.close()

        return agendar

    def test_participante_descreve_estados_e_prioriza_o_usuario_local(self) -> None:
        """Traduz os estados de conexão e mostra ``voce`` para o participante local."""
        esperados = {
            "connected": "conectado",
            "checking": "negociando",
            "failed": "falhou",
            "closed": "saiu",
            "disconnected": "instavel",
            "desconhecido": "desconhecido",
        }

        for estado, descricao in esperados.items():
            with self.subTest(estado=estado):
                participante = Participante("p", "Pessoa", estado=estado)
                self.assertEqual(participante.descricao_estado, descricao)

        self.assertEqual(Participante("eu", "Eu", estado="failed", eu=True).descricao_estado, "voce")

    def test_retornos_chamada_sao_opcionais_por_padrao(self) -> None:
        """Não exige callbacks para instanciar uma chamada."""
        retornos = RetornosChamada()

        self.assertTrue(all(valor is None for valor in vars(retornos).values()))

    def test_bem_vindo_popula_participantes_notifica_e_fecha_corrotinas(self) -> None:
        """Aceita a entrada, cria a lista local e agenda somente os pares necessários."""
        entradas: list[tuple[str, str]] = []
        sistemas: list[str] = []
        listas: list[list[Participante]] = []
        chamada = self.criar_chamada(
            RetornosChamada(
                ao_entrar=lambda sala, identificador: entradas.append((sala, identificador)),
                ao_sistema=sistemas.append,
                ao_participantes=lambda itens: listas.append(list(itens)),
            )
        )
        chamada._apelido = "Eu"
        agendadas: list[str] = []
        chamada._agendar = self.agendador_falso(agendadas)

        chamada._ao_bem_vindo(
            "local",
            "SALA",
            [
                {"id": "local", "apelido": "Duplicado"},
                {"id": "ana", "apelido": "Ana"},
                {"id": "", "apelido": "Ignorado"},
            ],
        )

        self.assertEqual(chamada.id_local, "local")
        self.assertEqual(chamada.sala, "SALA")
        self.assertEqual([item.apelido for item in chamada.participantes], ["Eu", "Ana"])
        self.assertTrue(chamada.participantes[0].eu)
        self.assertEqual(entradas, [("SALA", "local")])
        self.assertIn("Voce entrou na sala SALA.", sistemas[0])
        self.assertEqual([item.identificador for item in listas[-1]], ["local", "ana"])
        self.assertEqual(agendadas.count("_criar_par"), 1)
        self.assertEqual(agendadas.count("_iniciar_estatisticas"), 1)

    def test_entrada_e_saida_atualizam_lista_e_agendam_limpeza(self) -> None:
        """Inclui uma pessoa nova e remove seus recursos ao sair."""
        sistemas: list[str] = []
        listas: list[list[str]] = []
        chamada = self.criar_chamada(
            RetornosChamada(
                ao_sistema=sistemas.append,
                ao_participantes=lambda itens: listas.append([item.identificador for item in itens]),
            )
        )
        agendadas: list[str] = []
        chamada._agendar = self.agendador_falso(agendadas)

        chamada._ao_entrou("bia", "Bia")
        chamada._ao_saiu("bia")

        self.assertNotIn("bia", chamada._participantes)
        self.assertEqual(listas, [["bia"], []])
        self.assertEqual(sistemas, ["Bia entrou na chamada.", "Bia saiu da chamada."])
        self.assertEqual(agendadas, ["_criar_par", "_remover_par"])

    def test_receber_dados_trata_chat_estado_saida_e_objeto_invalido(self) -> None:
        """Interpreta cada mensagem válida sem alterar estado para objetos inválidos."""
        chats: list[tuple[str, str]] = []
        listas: list[list[Participante]] = []
        sistemas: list[str] = []
        chamada = self.criar_chamada(
            RetornosChamada(
                ao_chat=lambda apelido, texto: chats.append((apelido, texto)),
                ao_participantes=lambda itens: listas.append(list(itens)),
                ao_sistema=sistemas.append,
            )
        )
        chamada._participantes["ana"] = Participante("ana", "Ana")
        agendadas: list[str] = []
        chamada._agendar = self.agendador_falso(agendadas)

        chamada._receber_dados("ana", {"tipo": "chat", "texto": "Olá"})
        chamada._receber_dados(
            "ana",
            {
                "tipo": "estado",
                "apelido": "Ana Maria",
                "microfone": False,
                "compartilhando": True,
            },
        )
        chamada._receber_dados("ana", {"tipo": "saindo"})
        chamada._receber_dados("outra", ["não é um dicionário"])

        self.assertEqual(chats, [("Ana", "Olá")])
        self.assertEqual(sistemas, ["Ana Maria saiu da chamada."])
        self.assertNotIn("ana", chamada._participantes)
        self.assertEqual(len(listas), 2)
        self.assertEqual(agendadas, ["_remover_par"])

    def test_acoes_de_audio_sem_faixas_alteram_apenas_estado_local(self) -> None:
        """Alterna microfone, som e volume mesmo antes de uma faixa existir."""
        chamada = self.criar_chamada()

        self.assertTrue(chamada.alternar_microfone() is False)
        self.assertTrue(chamada.alternar_som() is False)
        chamada.definir_volume(2.0)
        self.assertEqual(chamada._configuracoes.interface.volume_saida, 1.0)
        chamada.definir_volume(-0.5)
        self.assertEqual(chamada._configuracoes.interface.volume_saida, 0.0)
        self.assertIsNone(chamada._faixa_microfone)
        self.assertFalse(chamada.microfone_ativo)
        self.assertFalse(chamada.som_ativo)

    def test_enviar_chat_sem_pares_e_resumo_textual(self) -> None:
        """Aceita um chat local e conserva a representação legível do resumo."""
        chamada = self.criar_chamada()

        self.assertFalse(chamada.enviar_chat(" mensagem "))
        self.assertFalse(chamada.enviar_chat("   "))
        resumo = ResumoChamada(
            "ABCD",
            [Participante("a", "Ana"), Participante("b", "Bia")],
            compartilhando=True,
        )
        self.assertEqual(str(resumo), "Sala ABCD com 2 participantes: Ana, Bia")

    def test_erro_de_sinalizacao_traduz_codigos_conhecidos(self) -> None:
        """Expõe mensagens amigáveis para todos os códigos do protocolo."""
        erros: list[str] = []
        chamada = self.criar_chamada(RetornosChamada(ao_erro=erros.append))
        traducoes = {
            "SALA_CHEIA": "A sala esta cheia. O limite e de seis participantes.",
            "SENHA_INCORRETA": "Senha da sala incorreta.",
            "SALA_INEXISTENTE": "Essa sala nao existe mais.",
            "DADOS_INVALIDOS": "Informe um codigo de sala e um apelido validos.",
        }

        for codigo, mensagem in traducoes.items():
            chamada._ao_erro_sinalizacao(codigo, "mensagem original")
            self.assertEqual(erros[-1], mensagem)
        chamada._ao_erro_sinalizacao("OUTRO", "Detalhe do servidor")
        self.assertEqual(erros[-1], "Detalhe do servidor")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
