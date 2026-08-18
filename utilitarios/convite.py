"""Geração e interpretação de códigos / links de convite.

Formatos suportados:
* ``IP:porta`` (clássico)
* ``screenshare://IP:porta`` (link)
* ``screenshare://IP:porta?senha=...`` (com senha)
* Código curto legível para o usuário copiar/colar
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse


@dataclass
class Convite:
    """Dados extraídos de um convite."""

    endereco: str
    porta: int
    senha: str = ""
    modo: str = "tcp"  # "tcp" ou "webrtc"
    sala: str = ""  # usado no futuro pelo WebRTC

    def para_texto(self) -> str:
        """Formato legível para colar no campo do espectador."""
        base = f"{self.endereco}:{self.porta}"
        if self.senha:
            return f"{base} (senha: {self.senha})"
        return base

    def para_link(self) -> str:
        """Link no formato screenshare://"""
        params = {}
        if self.senha:
            params["senha"] = self.senha
        if self.modo != "tcp":
            params["modo"] = self.modo
        if self.sala:
            params["sala"] = self.sala
        query = f"?{urlencode(params)}" if params else ""
        return f"screenshare://{self.endereco}:{self.porta}{query}"

    def para_mensagem(self) -> str:
        """Texto completo pronto para enviar por WhatsApp/Discord/etc."""
        linhas = [
            "Convite ScreenShare",
            f"Endereço: {self.endereco}:{self.porta}",
        ]
        if self.senha:
            linhas.append(f"Senha: {self.senha}")
        linhas.append("")
        linhas.append("Como conectar:")
        linhas.append("1. Abra o ScreenShare → Assistir a uma tela")
        linhas.append(f"2. Cole o endereço: {self.endereco}:{self.porta}")
        if self.senha:
            linhas.append(f"3. Informe a senha: {self.senha}")
        linhas.append("")
        linhas.append(
            "Se der timed out: use o mesmo Tailscale/ZeroTier nos dois PCs "
            "e cole o IP da VPN (100.x.x.x), ou abra o Diagnóstico no host."
        )
        return "\n".join(linhas)


def criar_convite(
    endereco: str,
    porta: int,
    senha: str = "",
    modo: str = "tcp",
    sala: str = "",
) -> Convite:
    """Cria um objeto de convite a partir dos dados do host."""
    return Convite(
        endereco=endereco.strip(),
        porta=int(porta),
        senha=senha or "",
        modo=modo or "tcp",
        sala=sala or "",
    )


def interpretar_convite(texto: str, porta_padrao: int = 9999) -> Convite:
    """Interpreta texto colado pelo usuário (IP, IP:porta ou link)."""
    bruto = (texto or "").strip()
    if not bruto:
        raise ValueError("Cole o endereço ou o link de convite")

    # Link screenshare://
    if bruto.lower().startswith("screenshare://"):
        parseado = urlparse(bruto)
        host = parseado.hostname or ""
        porta = parseado.port or porta_padrao
        qs = parse_qs(parseado.query)
        senha = (qs.get("senha") or [""])[0]
        modo = (qs.get("modo") or ["tcp"])[0]
        sala = (qs.get("sala") or [""])[0]
        if not host:
            raise ValueError("Link de convite inválido (sem endereço)")
        return Convite(endereco=host, porta=porta, senha=senha, modo=modo, sala=sala)

    # Formato IP:porta ou só IP
    # Remove possíveis textos extras tipo "(senha: xxx)"
    limpo = re.split(r"\s*\(|\s+senha", bruto, maxsplit=1, flags=re.IGNORECASE)[0].strip()

    if limpo.count(":") == 1:
        ip, _, porta_txt = limpo.partition(":")
        porta_txt = porta_txt.strip()
        if porta_txt.isdigit():
            return Convite(endereco=ip.strip(), porta=int(porta_txt))
        return Convite(endereco=ip.strip(), porta=porta_padrao)

    return Convite(endereco=limpo, porta=porta_padrao)
