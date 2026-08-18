"""Gerenciamento de conexão TCP.

A classe :class:`Conexao` encapsula um socket já conectado e oferece envio
thread-safe e recepção de quadros completos do protocolo.
"""

from __future__ import annotations

import socket
import threading

from configuracao.configuracoes import TAMANHO_MAXIMO_CARGA
from nucleo.protocolo import (
    TAMANHO_CABECALHO,
    ErroProtocolo,
    TipoMensagem,
    codificar_json,
    desempacotar_cabecalho,
    empacotar,
)
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)


class ConexaoEncerrada(Exception):
    """Sinaliza que a conexão foi fechada pelo outro lado ou localmente."""


class Conexao:
    """Envolve um socket TCP conectado com a semântica do protocolo."""

    def __init__(
        self,
        soquete: socket.socket,
        endereco: tuple[str, int],
        tamanho_maximo_carga: int = TAMANHO_MAXIMO_CARGA,
    ) -> None:
        self._soquete = soquete
        self._endereco = endereco
        self._tamanho_maximo_carga = tamanho_maximo_carga
        self._trava_envio = threading.Lock()
        self._aberta = True
        self.bytes_enviados = 0
        self.bytes_recebidos = 0
        try:
            self._soquete.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:  # pragma: no cover - dependente do sistema
            pass

    # -- Propriedades -------------------------------------------------------

    @property
    def endereco(self) -> tuple[str, int]:
        """Endereço (IP, porta) do outro lado da conexão."""
        return self._endereco

    @property
    def aberta(self) -> bool:
        """``True`` enquanto a conexão não foi encerrada."""
        return self._aberta

    # -- Envio --------------------------------------------------------------

    def enviar(self, tipo: TipoMensagem, carga: bytes = b"") -> None:
        """Envia um quadro. Seguro para uso por múltiplas threads.

        Raises:
            ConexaoEncerrada: se o socket já estiver fechado ou falhar.
        """
        if not self._aberta:
            raise ConexaoEncerrada("Conexão já encerrada")
        quadro = empacotar(tipo, carga)
        with self._trava_envio:
            try:
                self._soquete.sendall(quadro)
                self.bytes_enviados += len(quadro)
            except (OSError, AttributeError) as erro:
                self._aberta = False
                raise ConexaoEncerrada(f"Falha ao enviar dados: {erro}") from erro

    def enviar_json(self, tipo: TipoMensagem, objeto: object) -> None:
        """Envia um quadro cuja carga é um objeto serializado em JSON."""
        self.enviar(tipo, codificar_json(objeto))

    # -- Recepção -----------------------------------------------------------

    def receber(self) -> tuple[TipoMensagem, bytes]:
        """Bloqueia até receber um quadro completo.

        Raises:
            ConexaoEncerrada: se a conexão for fechada durante a leitura.
            ErroProtocolo: se o quadro violar o protocolo.
        """
        cabecalho = self._receber_exato(TAMANHO_CABECALHO)
        tipo, tamanho = desempacotar_cabecalho(cabecalho)
        if tamanho > self._tamanho_maximo_carga:
            self.fechar()
            raise ErroProtocolo(
                f"Carga de {tamanho} bytes excede o limite permitido"
            )
        carga = self._receber_exato(tamanho) if tamanho else b""
        return tipo, carga

    def _receber_exato(self, quantidade: int) -> bytes:
        """Lê exatamente ``quantidade`` bytes do socket."""
        partes: list[bytes] = []
        restante = quantidade
        while restante > 0:
            try:
                pedaco = self._soquete.recv(min(restante, 65536))
            except socket.timeout as erro:
                raise ConexaoEncerrada("Tempo limite de leitura excedido") from erro
            except OSError as erro:
                raise ConexaoEncerrada(f"Falha na leitura: {erro}") from erro
            if not pedaco:
                self._aberta = False
                raise ConexaoEncerrada("O outro lado encerrou a conexão")
            partes.append(pedaco)
            restante -= len(pedaco)
        dados = b"".join(partes)
        self.bytes_recebidos += len(dados)
        return dados

    # -- Encerramento -------------------------------------------------------

    def fechar(self) -> None:
        """Encerra a conexão de forma idempotente e silenciosa."""
        if not self._aberta:
            return
        self._aberta = False
        try:
            self._soquete.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._soquete.close()
        except OSError:
            pass
        _registrador.info("Conexão com %s encerrada", self._endereco)

    def __enter__(self) -> Conexao:
        return self

    def __exit__(self, *_excecao: object) -> None:
        self.fechar()


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------


def criar_socket_escuta(endereco: str, porta: int, fila: int = 1) -> socket.socket:
    """Cria e prepara um socket TCP em modo de escuta."""
    soquete = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soquete.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    soquete.bind((endereco, porta))
    soquete.listen(fila)
    _registrador.info("Escutando em %s:%s", endereco, porta)
    return soquete


def conectar(ip: str, porta: int, tempo_limite: float = 15.0) -> Conexao:
    """Conecta-se a um servidor e devolve a :class:`Conexao` resultante.

    Raises:
        ConexaoEncerrada: se a conexão não puder ser estabelecida.
    """
    try:
        soquete = socket.create_connection((ip, porta), timeout=tempo_limite)
    except OSError as erro:
        raise ConexaoEncerrada(f"Não foi possível conectar a {ip}:{porta} ({erro})") from erro
    soquete.settimeout(None)
    _registrador.info("Conectado a %s:%s", ip, porta)
    return Conexao(soquete, (ip, porta))
