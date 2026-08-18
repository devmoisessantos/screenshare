"""Funções auxiliares de rede (descoberta de IP e validações)."""

from __future__ import annotations

import ipaddress
import socket


def obter_ip_local() -> str:
    """Descobre o IP local usado para sair da máquina.

    Não envia tráfego: apenas consulta a tabela de roteamento por meio de um
    socket UDP não conectado.
    """
    soquete = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        soquete.connect(("8.8.8.8", 80))
        return soquete.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        soquete.close()


def porta_disponivel(porta: int, endereco: str = "0.0.0.0") -> bool:
    """Informa se a porta TCP está livre para escuta."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soquete:
        soquete.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            soquete.bind((endereco, porta))
        except OSError:
            return False
    return True


def validar_porta(valor: str | int) -> int:
    """Valida e converte um número de porta.

    Raises:
        ValueError: se a porta não estiver entre 1 e 65535.
    """
    try:
        porta = int(valor)
    except (TypeError, ValueError) as erro:
        raise ValueError("A porta deve ser um número inteiro") from erro
    if not 1 <= porta <= 65535:
        raise ValueError("A porta deve estar entre 1 e 65535")
    return porta


def validar_endereco(valor: str) -> str:
    """Valida um endereço IP ou nome de host.

    Raises:
        ValueError: se o endereço estiver vazio ou não puder ser resolvido.
    """
    endereco = (valor or "").strip()
    if not endereco:
        raise ValueError("Informe o endereço IP do servidor")
    try:
        ipaddress.ip_address(endereco)
        return endereco
    except ValueError:
        pass
    try:
        socket.getaddrinfo(endereco, None)
    except OSError as erro:
        raise ValueError(f"Endereço inválido ou não resolvido: {endereco}") from erro
    return endereco


def formatar_taxa(bytes_por_segundo: float) -> str:
    """Formata uma taxa de transferência em unidade legível."""
    bits = bytes_por_segundo * 8
    if bits >= 1_000_000:
        return f"{bits / 1_000_000:.1f} Mbps"
    if bits >= 1_000:
        return f"{bits / 1_000:.0f} kbps"
    return f"{bits:.0f} bps"
