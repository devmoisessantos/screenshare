"""Informações e utilitários do modo WebRTC.

O WebRTC (via aiortc) é o caminho para conexões pela internet sem abrir
portas no roteador. Nesta versão a base está pronta; o fluxo completo de
sinalização (oferta/resposta) e tracks de vídeo/áudio será ativado de forma
incremental.

Servidores STUN públicos usados para descoberta de IP externo e NAT traversal:
"""

from __future__ import annotations

# Servidores STUN públicos e estáveis (Google + outros).
SERVIDORES_STUN = [
    "stun:stun.l.google.com:19302",
    "stun:stun1.l.google.com:19302",
    "stun:stun.cloudflare.com:3478",
    "stun:stun.stunprotocol.org:3478",
]

# Mensagem exibida quando o aiortc não está instalado.
MSG_WEBRTC_INDISPONIVEL = (
    "Modo WebRTC indisponível. Instale com:\n"
    "  pip install aiortc aiohttp\n"
    "Reinicie o aplicativo após a instalação."
)

# Texto de ajuda para o usuário (modo internet).
AJUDA_WEBRTC = (
    "Modo Internet (WebRTC)\n\n"
    "• Funciona de qualquer lugar do mundo (diferentes estados/países).\n"
    "• Não precisa abrir porta no roteador nem liberar firewall.\n"
    "• Usa STUN para atravessar NAT.\n"
    "• Em redes muito restritas pode precisar de um servidor TURN "
    "(configurável no futuro).\n\n"
    "Como usar:\n"
    "1. Host cria uma sala e copia o código de convite.\n"
    "2. Espectador cola o código e entra.\n"
    "3. A conexão é negociada automaticamente."
)

AJUDA_TAILSCALE = (
    "Tailscale / ZeroTier (recomendado e mais estável hoje)\n\n"
    "1. Instale o Tailscale (ou ZeroTier) nos dois computadores:\n"
    "   https://tailscale.com  ou  https://www.zerotier.com\n"
    "2. Faça login com a mesma conta nos dois lados.\n"
    "3. Use o IP do Tailscale/ZeroTier (geralmente 100.x.x.x) no modo TCP.\n"
    "4. Funciona como se estivessem na mesma rede local — sem timed out.\n\n"
    "É a forma mais simples e confiável de conectar entre estados/países "
    "enquanto o modo WebRTC completo é finalizado."
)


def webrtc_disponivel() -> bool:
    """Verifica se a biblioteca aiortc está instalada."""
    try:
        import aiortc  # noqa: F401
        return True
    except ImportError:
        return False


def descrever_modo_webrtc() -> str:
    """Texto curto para a interface."""
    if webrtc_disponivel():
        return "WebRTC disponível (aiortc detectado)"
    return "WebRTC não instalado — use: pip install aiortc aiohttp"
