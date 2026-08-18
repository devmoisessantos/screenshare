"""Contrato comum para qualquer transporte de mídia/chat."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable


class ModoTransporte(str, Enum):
    """Modos de conexão disponíveis."""

    TCP = "tcp"  # rede local ou VPN (Tailscale/ZeroTier)
    WEBRTC = "webrtc"  # internet com NAT traversal


class TransporteBase(ABC):
    """Interface mínima que servidor e cliente de transporte implementam."""

    @abstractmethod
    def iniciar(self) -> None:
        """Coloca o transporte em operação."""

    @abstractmethod
    def parar(self, motivo: str = "") -> None:
        """Encerra o transporte de forma limpa."""

    @property
    @abstractmethod
    def ativo(self) -> bool:
        """True enquanto o transporte estiver operacional."""

    def definir_callbacks(
        self,
        ao_status: Callable[[str], None] | None = None,
        ao_conectar: Callable[[dict], None] | None = None,
        ao_desconectar: Callable[[str], None] | None = None,
    ) -> None:
        """Registra callbacks de status (opcional)."""
        self._ao_status = ao_status
        self._ao_conectar = ao_conectar
        self._ao_desconectar = ao_desconectar
