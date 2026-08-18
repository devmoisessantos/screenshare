"""Ponto de entrada do ScreenShare.

Uso típico (interface gráfica)::

    python principal.py

Modos diretos::

    python principal.py --sala ABC123             # entra na sala pela internet
    python principal.py --convite "screenshare://sala/ABC123?s=wss://..."
    python principal.py --host                    # modo local: abre como host
    python principal.py --assistir 192.168.0.10   # modo local: espectador
    python principal.py --host --console          # host local sem interface
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
        description=f"{NOME_APLICACAO} {VERSAO_APLICACAO} - chamadas de tela, voz e chat",
    )
    analisador.add_argument(
        "--sala", metavar="CODIGO", help="entra diretamente nesta sala (modo internet)"
    )
    analisador.add_argument(
        "--convite", metavar="TEXTO", help="entra usando um link ou codigo de convite"
    )
    analisador.add_argument(
        "--servidor-sinalizacao",
        metavar="URL",
        help="endereco do servidor de sinalizacao (exemplo: wss://exemplo/ws)",
    )
    analisador.add_argument("--apelido", help="nome exibido aos outros participantes")
    analisador.add_argument(
        "--host", action="store_true", help="modo local: inicia diretamente como host"
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
    if argumentos.servidor_sinalizacao:
        configuracoes.internet.servidor_sinalizacao = argumentos.servidor_sinalizacao
    if argumentos.apelido:
        configuracoes.interface.apelido = argumentos.apelido
    if argumentos.convite:
        _aplicar_convite(configuracoes, argumentos)


def _aplicar_convite(configuracoes: Configuracoes, argumentos: argparse.Namespace) -> None:
    """Interpreta o convite recebido na linha de comando."""
    from nucleo.convite import ErroConvite, interpretar

    try:
        convite = interpretar(argumentos.convite)
    except ErroConvite as erro:
        print(f"Convite invalido: {erro}", file=sys.stderr)
        return
    argumentos.sala = convite.codigo
    if convite.senha:
        configuracoes.rede.senha = convite.senha
        argumentos.senha = convite.senha
    if convite.modo == "internet" and convite.servidor:
        configuracoes.internet.servidor_sinalizacao = convite.servidor
    elif convite.modo == "local" and convite.endereco:
        argumentos.assistir = convite.endereco


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
    if argumentos.sala:
        from interface.janela_chamada import JanelaChamada

        chamada = JanelaChamada(
            janela,
            configuracoes,
            "".join(argumentos.sala.upper().split()),
            configuracoes.interface.apelido,
            argumentos.senha or "",
        )
        janela._registrar(chamada)
    elif argumentos.host:
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
