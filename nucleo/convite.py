"""Criação e interpretação de convites para salas ScreenShare."""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import secrets
import zlib
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlsplit

from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

ESQUEMA = "screenshare"
CODIGO_TAMANHO = 6
_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_PADRAO_CODIGO = re.compile(rf"^[{_ALFABETO}]{{{CODIGO_TAMANHO}}}$")
_PADRAO_IP_PORTA = re.compile(r"^(?P<ip>[^:]+):(?P<porta>[0-9]{1,5})$")


class ErroConvite(ValueError):
    """Indica que um convite não tem um formato aceito."""


def gerar_codigo_sala() -> str:
    """Gera um código de sala legível e sem caracteres ambíguos."""
    return "".join(secrets.choice(_ALFABETO) for _ in range(CODIGO_TAMANHO))


@dataclass
class Convite:
    """Representa os dados mínimos para entrar em uma sala."""

    codigo: str
    servidor: str = ""
    senha: str = ""
    modo: str = "internet"
    endereco: str = ""

    def __post_init__(self) -> None:
        """Normaliza e valida os valores recebidos."""
        self.codigo = self.codigo.strip().upper()
        self.servidor = self.servidor.strip()
        self.senha = self.senha.strip()
        self.modo = self.modo.strip().lower()
        self.endereco = self.endereco.strip()

        if not _PADRAO_CODIGO.fullmatch(self.codigo):
            raise ErroConvite(
                f"O código da sala deve ter {CODIGO_TAMANHO} caracteres sem ambiguidades."
            )
        if self.modo not in {"internet", "local"}:
            raise ErroConvite("O modo do convite deve ser 'internet' ou 'local'.")
        if self.modo == "local" and not self.endereco:
            raise ErroConvite("Um convite local precisa de um endereço IP.")

    @property
    def link(self) -> str:
        """Devolve o link compartilhável associado ao convite."""
        parametros: list[str] = []
        destino = "sala"
        if self.modo == "internet":
            if self.servidor:
                parametros.append(f"s={quote(self.servidor, safe='')}")
        else:
            destino = "local"
            parametros.append(f"e={quote(self.endereco, safe='')}")
        if self.senha:
            parametros.append(f"p={quote(self.senha, safe='')}")

        consulta = f"?{'&'.join(parametros)}" if parametros else ""
        return f"{ESQUEMA}://{destino}/{self.codigo}{consulta}"

    @property
    def texto_amigavel(self) -> str:
        """Produz um texto ASCII pronto para colar em aplicativos de mensagem."""
        linhas = [
            "Convite para compartilhar tela",
            "",
            f"Codigo da sala: {self.codigo}",
            f"Modo: {self.modo}",
        ]
        if self.modo == "internet" and self.servidor:
            linhas.append(f"Servidor: {self.servidor}")
        if self.modo == "local":
            linhas.append(f"Endereco local: {self.endereco}")
        if self.senha:
            linhas.append(f"Senha: {self.senha}")
        linhas.extend(["", "Abra o ScreenShare e cole este link:", self.link])
        return "\n".join(linhas)


def interpretar(texto: str) -> Convite:
    """Interpreta link, código de sala ou endereço local informado pelo usuário."""
    valor = texto.strip()
    if not valor:
        raise ErroConvite("Informe um convite, código de sala ou endereço IP.")

    if valor.lower().startswith(f"{ESQUEMA}://"):
        return _interpretar_link(valor)

    codigo = valor.upper()
    if _PADRAO_CODIGO.fullmatch(codigo):
        return Convite(codigo=codigo)

    endereco = _normalizar_endereco_local(valor)
    if endereco:
        return Convite(codigo=gerar_codigo_sala(), modo="local", endereco=endereco)

    raise ErroConvite(
        "Convite não reconhecido. Use um link ScreenShare, código de sala ou endereço IP."
    )


def codificar_sdp(sdp: str, tipo: str) -> str:
    """Empacota uma oferta ou resposta SDP para envio manual por mensagem."""
    if not isinstance(sdp, str) or not sdp:
        raise ErroConvite("O SDP manual deve ser um texto não vazio.")
    tipo_validado = _validar_tipo_sdp(tipo)
    dados = {"sdp": sdp, "tipo": tipo_validado, "versao": 1}
    bruto = json.dumps(dados, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    comprimido = zlib.compress(bruto)
    codificado = base64.urlsafe_b64encode(comprimido).decode("ascii").rstrip("=")
    return f"SS1-{codificado}"


def decodificar_sdp(blob: str) -> tuple[str, str]:
    """Desempacota um SDP manual devolvendo ``(sdp, tipo)``."""
    if not isinstance(blob, str) or not blob.startswith("SS1-"):
        raise ErroConvite("O bloco manual deve começar com 'SS1-'.")

    try:
        corpo = blob[4:]
        complemento = "=" * (-len(corpo) % 4)
        bruto = base64.b64decode(corpo + complemento, altchars=b"-_", validate=True)
        dados = json.loads(zlib.decompress(bruto).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, zlib.error) as erro:
        raise ErroConvite("O bloco manual de SDP está inválido.") from erro

    if not isinstance(dados, dict) or dados.get("versao") != 1:
        raise ErroConvite("O bloco manual de SDP não tem uma versão aceita.")
    sdp = dados.get("sdp")
    tipo = dados.get("tipo")
    if not isinstance(sdp, str) or not sdp:
        raise ErroConvite("O bloco manual não contém um SDP válido.")
    return sdp, _validar_tipo_sdp(tipo)


def _interpretar_link(link: str) -> Convite:
    """Converte um link ScreenShare em convite."""
    partes = urlsplit(link)
    if partes.scheme.lower() != ESQUEMA or partes.username or partes.password:
        raise ErroConvite("O link ScreenShare está inválido.")

    modo = partes.netloc.lower()
    codigo = partes.path.strip("/").upper()
    parametros = parse_qs(partes.query, keep_blank_values=True)
    senha = _primeiro_parametro(parametros, "p")

    if modo == "sala":
        return Convite(
            codigo=codigo,
            servidor=_primeiro_parametro(parametros, "s"),
            senha=senha,
            modo="internet",
        )
    if modo == "local":
        endereco = _normalizar_endereco_local(_primeiro_parametro(parametros, "e"))
        if not endereco:
            raise ErroConvite("O link local precisa de um endereço IP válido.")
        return Convite(codigo=codigo, senha=senha, modo="local", endereco=endereco)
    raise ErroConvite("O link ScreenShare precisa indicar 'sala' ou 'local'.")


def _primeiro_parametro(parametros: dict[str, list[str]], nome: str) -> str:
    """Obtém o primeiro valor de uma consulta URL."""
    valores = parametros.get(nome, [""])
    return valores[0]


def _normalizar_endereco_local(valor: str) -> str:
    """Valida um IPv4 isolado ou IPv4 seguido de porta."""
    valor = valor.strip()
    if not valor:
        return ""

    encontrado = _PADRAO_IP_PORTA.fullmatch(valor)
    ip_texto = encontrado.group("ip") if encontrado else valor
    porta_texto = encontrado.group("porta") if encontrado else ""
    try:
        ip = ipaddress.ip_address(ip_texto)
    except ValueError:
        return ""

    if ip.version != 4:
        return ""
    if porta_texto:
        porta = int(porta_texto)
        if not 1 <= porta <= 65535:
            return ""
        return f"{ip}:{porta}"
    return str(ip)


def _validar_tipo_sdp(tipo: object) -> str:
    """Valida o tipo de descrição aceito na troca manual."""
    if tipo not in {"oferta", "resposta"}:
        raise ErroConvite("O tipo de SDP deve ser 'oferta' ou 'resposta'.")
    return tipo
