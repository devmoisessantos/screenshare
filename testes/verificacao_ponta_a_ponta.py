"""Verificacao manual de uma chamada real entre dois participantes.

Este script nao faz parte da suite automatizada (o descobridor procura apenas
``teste_*.py``), porque ele sobe processos, abre sockets e depende de captura de
tela. Ele existe para comprovar, de ponta a ponta, que a pilha WebRTC funciona:

1. sobe o servidor de sinalizacao incluido no projeto em uma porta livre;
2. cria dois participantes que entram na mesma sala;
3. um deles compartilha a area de trabalho;
4. o outro envia uma mensagem de chat;
5. imprime quantos quadros de video atravessaram a conexao.

Uso, a partir da raiz do projeto:

    python testes/verificacao_ponta_a_ponta.py

Em servidores sem monitor, use um X virtual:

    xvfb-run -a -s "-screen 0 1024x768x24" python testes/verificacao_ponta_a_ponta.py

Sucesso significa: "Conexao direta estabelecida" nos dois lados, o chat
entregue e uma contagem de quadros maior que zero.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from configuracao.configuracoes import Configuracoes  # noqa: E402
from midia.fontes import listar_fontes  # noqa: E402
from nucleo.chamada import Chamada, RetornosChamada  # noqa: E402

PORTA = 8391
SALA = "TESTE1"


def _montar_participante(apelido: str) -> tuple[Chamada, list[tuple]]:
    """Cria uma chamada apontada ao servidor local e coleta seus eventos."""
    configuracoes = Configuracoes.carregar()
    configuracoes.internet.servidor_sinalizacao = f"ws://127.0.0.1:{PORTA}/ws"
    configuracoes.audio.ativo = False
    eventos: list[tuple] = []
    retornos = RetornosChamada(
        ao_sistema=lambda texto: eventos.append(("sistema", texto)),
        ao_erro=lambda texto: eventos.append(("erro", texto)),
        ao_chat=lambda autor, texto: eventos.append(("chat", autor, texto)),
        ao_quadro_remoto=lambda origem, quadro: eventos.append(("video", origem)),
    )
    return Chamada(configuracoes, retornos), eventos


def _resumir(nome: str, eventos: list[tuple]) -> int:
    """Imprime os eventos relevantes e devolve a contagem de quadros."""
    quadros = sum(1 for evento in eventos if evento[0] == "video")
    print(f"--- {nome} ---")
    for evento in eventos:
        if evento[0] != "video":
            print(" ", evento)
    print(f"  quadros de video recebidos: {quadros}")
    return quadros


def main() -> int:
    """Executa o roteiro completo e devolve o codigo de saida do processo."""
    servidor = subprocess.Popen(
        [sys.executable, "servidor_sinalizacao/servidor.py", "--porta", str(PORTA)],
        cwd=str(RAIZ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    primeiro, eventos_primeiro = _montar_participante("Ana")
    segundo, eventos_segundo = _montar_participante("Bruno")
    try:
        time.sleep(2.5)
        primeiro.entrar(SALA, "Ana")
        time.sleep(2.0)
        segundo.entrar(SALA, "Bruno")
        time.sleep(3.0)

        fontes = listar_fontes()
        print("Fontes de captura encontradas:", [fonte.titulo for fonte in fontes])
        if fontes:
            primeiro.iniciar_compartilhamento(fontes[0])
        time.sleep(8.0)

        segundo.enviar_chat("teste de chat")
        time.sleep(2.0)

        _resumir("Ana (transmitindo)", eventos_primeiro)
        quadros = _resumir("Bruno (assistindo)", eventos_segundo)
    finally:
        primeiro.sair()
        segundo.sair()
        servidor.terminate()
        servidor.wait(timeout=5)

    if quadros:
        print("\nRESULTADO: video e chat atravessaram a conexao WebRTC.")
        return 0
    print("\nRESULTADO: nenhum quadro chegou. Confira o log do servidor.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
