"""Ponto de entrada do ScreenShare.

Uso típico (interface gráfica)::

    python principal.py

Modos diretos::

    python principal.py --host                    # abre já como host
    python principal.py --assistir 192.168.0.10   # abre já como espectador
    python principal.py --host --console          # host sem interface gráfica
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from configuracao.configuracoes import (
    NOME_APLICACAO,
    RESOLUCOES,
    VERSAO_APLICACAO,
    Configuracoes,
)
from utilitarios.registro import configurar_registro, obter_registrador

_registrador = obter_registrador(__name__)


def construir_analisador() -> argparse.ArgumentParser:
    """Cria o analisador de argumentos da linha de comando."""
    analisador = argparse.ArgumentParser(
        prog="screenshare",
        description=f"{NOME_APLICACAO} {VERSAO_APLICACAO} - compartilhamento de tela 1:1",
    )
    analisador.add_argument(
        "--host", action="store_true", help="inicia diretamente no modo host"
    )
    analisador.add_argument(
        "--assistir", metavar="IP", help="conecta diretamente ao host informado"
    )
    analisador.add_argument("--porta", type=int, help="porta TCP (padrão: 9999)")
    analisador.add_argument("--senha", help="senha da sessão (opcional)")
    analisador.add_argument(
        "--resolucao", choices=list(RESOLUCOES), help="resolução do compartilhamento"
    )
    analisador.add_argument("--fps", type=int, help="quadros por segundo")
    analisador.add_argument(
        "--sem-audio", action="store_true", help="desativa captura e reprodução de áudio"
    )
    analisador.add_argument(
        "--console",
        action="store_true",
        help="executa o host sem interface gráfica (útil em servidores)",
    )
    analisador.add_argument(
        "--depurar", action="store_true", help="ativa log detalhado (nível DEBUG)"
    )
    analisador.add_argument(
        "--versao", action="version", version=f"{NOME_APLICACAO} {VERSAO_APLICACAO}"
    )
    return analisador


def aplicar_argumentos(configuracoes: Configuracoes, argumentos: argparse.Namespace) -> None:
    """Sobrescreve as configurações com os valores da linha de comando."""
    if argumentos.porta:
        configuracoes.rede.porta = argumentos.porta
    if argumentos.senha is not None:
        configuracoes.rede.senha = argumentos.senha
    if argumentos.resolucao:
        configuracoes.video.resolucao = argumentos.resolucao
    if argumentos.fps:
        configuracoes.video.fps = argumentos.fps
    if argumentos.sem_audio:
        configuracoes.audio.ativo = False


def executar_console(configuracoes: Configuracoes) -> int:
    """Executa o host em modo texto, sem interface gráfica."""
    from aplicacao.servidor import ErroServidor, ServidorCompartilhamento

    servidor = ServidorCompartilhamento(
        configuracoes=configuracoes, ao_status=lambda texto: print(f"[status] {texto}")
    )
    try:
        servidor.iniciar()
    except ErroServidor as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1

    print(f"Compartilhando em {servidor.endereco_publicado}. Pressione Ctrl+C para sair.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        servidor.parar()
    return 0


def executar_interface(configuracoes: Configuracoes, argumentos: argparse.Namespace) -> int:
    """Abre a interface gráfica, opcionalmente já em um dos modos."""
    try:
        import tkinter  # noqa: F401  (validação de disponibilidade)
    except ImportError:
        print(
            "Tkinter não está disponível nesta instalação do Python.\n"
            "No Ubuntu/Debian instale com: sudo apt install python3-tk",
            file=sys.stderr,
        )
        return 1

    from interface.janela_inicial import JanelaInicial

    janela = JanelaInicial(configuracoes)
    if argumentos.host:
        janela._abrir_servidor()
    elif argumentos.assistir:
        from interface.janela_cliente import JanelaCliente

        cliente = JanelaCliente(janela, configuracoes)
        cliente._var_endereco.set(argumentos.assistir)
        janela._registrar(cliente)
    janela.mainloop()
    return 0


def principal(lista_argumentos: list[str] | None = None) -> int:
    """Função principal da aplicação; devolve o código de saída."""
    argumentos = construir_analisador().parse_args(lista_argumentos)
    configurar_registro(logging.DEBUG if argumentos.depurar else logging.INFO)
    _registrador.info("Iniciando %s %s", NOME_APLICACAO, VERSAO_APLICACAO)

    configuracoes = Configuracoes.carregar()
    aplicar_argumentos(configuracoes, argumentos)

    if argumentos.console:
        return executar_console(configuracoes)
    return executar_interface(configuracoes, argumentos)


if __name__ == "__main__":
    sys.exit(principal())
