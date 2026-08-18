"""Protocolo binário de comunicação do ScreenShare.

Formato do quadro transmitido no socket TCP::

    +----------+--------+-------------+-----------------+
    | 2 bytes  | 1 byte |   4 bytes   |    N bytes      |
    |  "SS"    |  tipo  |  tamanho N  |   carga útil    |
    +----------+--------+-------------+-----------------+

O prefixo mágico ``SS`` permite detectar rapidamente dessincronização do
fluxo; o campo *tipo* identifica a natureza da mensagem (vídeo, áudio,
chat, controle) e *tamanho* informa quantos bytes de carga seguem.

Cargas úteis:
    * ``VIDEO``  -> quadro JPEG comprimido (bytes).
    * ``AUDIO``  -> bloco PCM 16 bits (bytes).
    * demais     -> JSON codificado em UTF-8.
"""

from __future__ import annotations

import hashlib
import json
import struct
import time
from enum import IntEnum
from typing import Any

#: Versão do protocolo; usada no handshake para impedir versões incompatíveis.
VERSAO_PROTOCOLO = "1.0"

#: Prefixo mágico de cada quadro.
MAGICO = b"SS"

_CABECALHO = struct.Struct("!2sBI")

#: Tamanho fixo do cabeçalho, em bytes.
TAMANHO_CABECALHO = _CABECALHO.size  # 7 bytes


class TipoMensagem(IntEnum):
    """Tipos de mensagem suportados pelo protocolo."""

    HANDSHAKE_PEDIDO = 1
    HANDSHAKE_ACEITO = 2
    HANDSHAKE_RECUSADO = 3
    PRONTO = 4
    VIDEO = 10
    AUDIO = 11
    CHAT = 20
    PING = 30
    PONG = 31
    ESTADO = 40
    ENCERRAR = 50


class ErroProtocolo(Exception):
    """Erro de violação do protocolo (quadro inválido ou incompatível)."""


# ---------------------------------------------------------------------------
# Empacotamento
# ---------------------------------------------------------------------------


def empacotar(tipo: TipoMensagem, carga: bytes = b"") -> bytes:
    """Monta um quadro completo pronto para envio pelo socket.

    Args:
        tipo: tipo da mensagem.
        carga: bytes da carga útil (pode ser vazia).

    Returns:
        Quadro binário (cabeçalho + carga).
    """
    return _CABECALHO.pack(MAGICO, int(tipo), len(carga)) + carga


def desempacotar_cabecalho(cabecalho: bytes) -> tuple[TipoMensagem, int]:
    """Interpreta um cabeçalho de ``TAMANHO_CABECALHO`` bytes.

    Raises:
        ErroProtocolo: se o prefixo mágico ou o tipo forem inválidos.
    """
    if len(cabecalho) != TAMANHO_CABECALHO:
        raise ErroProtocolo(
            f"Cabeçalho com tamanho inesperado: {len(cabecalho)} bytes"
        )
    magico, tipo, tamanho = _CABECALHO.unpack(cabecalho)
    if magico != MAGICO:
        raise ErroProtocolo("Prefixo mágico inválido: fluxo dessincronizado")
    try:
        return TipoMensagem(tipo), tamanho
    except ValueError as erro:  # tipo desconhecido
        raise ErroProtocolo(f"Tipo de mensagem desconhecido: {tipo}") from erro


# ---------------------------------------------------------------------------
# Utilidades de carga útil
# ---------------------------------------------------------------------------


def codificar_json(objeto: Any) -> bytes:
    """Serializa um objeto Python em bytes JSON (UTF-8)."""
    return json.dumps(objeto, ensure_ascii=False).encode("utf-8")


def decodificar_json(dados: bytes) -> dict[str, Any]:
    """Desserializa bytes JSON em dicionário.

    Raises:
        ErroProtocolo: se o conteúdo não for um objeto JSON válido.
    """
    try:
        objeto = json.loads(dados.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as erro:
        raise ErroProtocolo("Carga JSON inválida") from erro
    if not isinstance(objeto, dict):
        raise ErroProtocolo("Carga JSON deve ser um objeto")
    return objeto


def gerar_token(senha: str) -> str:
    """Gera o token de autenticação (SHA-256) para a senha informada.

    Uma senha vazia produz token vazio, indicando sessão sem senha.
    """
    if not senha:
        return ""
    return hashlib.sha256(senha.encode("utf-8")).hexdigest()


def tokens_equivalentes(token_a: str, token_b: str) -> bool:
    """Compara dois tokens de forma resistente a ataques de tempo."""
    import hmac

    return hmac.compare_digest(token_a or "", token_b or "")


def agora_ms() -> int:
    """Marca de tempo monotônica em milissegundos (para medir latência)."""
    return int(time.monotonic() * 1000)


# ---------------------------------------------------------------------------
# Mensagens de alto nível
# ---------------------------------------------------------------------------


def mensagem_chat(autor: str, conteudo: str) -> bytes:
    """Cria a carga JSON de uma mensagem de chat."""
    return codificar_json(
        {
            "autor": autor,
            "conteudo": conteudo,
            "horario": time.strftime("%H:%M:%S"),
        }
    )


def mensagem_handshake(apelido: str, token: str) -> bytes:
    """Cria a carga JSON do pedido de conexão enviado pelo cliente."""
    return codificar_json(
        {
            "versao": VERSAO_PROTOCOLO,
            "apelido": apelido,
            "token": token,
        }
    )
