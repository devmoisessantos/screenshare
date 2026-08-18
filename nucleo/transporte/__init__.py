"""Camada de transporte: TCP clássico e WebRTC (em evolução).

O app passa a ter dois modos de conexão:

* **TCP** — rede local ou redes unificadas (Tailscale / ZeroTier).
* **WebRTC** — conexão pela internet com NAT traversal (STUN + futuro TURN).

A interface e a sessão usam a mesma API de alto nível; apenas o transporte muda.
"""

from nucleo.transporte.base import ModoTransporte, TransporteBase

__all__ = ["ModoTransporte", "TransporteBase"]
