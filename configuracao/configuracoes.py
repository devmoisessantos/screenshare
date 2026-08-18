"""Configurações globais do ScreenShare.

Este módulo centraliza todos os parâmetros ajustáveis da aplicação.
As configurações são persistidas em disco (JSON) para que as escolhas
do usuário sobrevivam entre execuções.

Diretório de dados:
    Windows: %APPDATA%/ScreenShare
    Linux/macOS: ~/.config/screenshare
"""

from __future__ import annotations

import json
import os
import socket
import sys
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constantes gerais
# ---------------------------------------------------------------------------

NOME_APLICACAO = "ScreenShare"
VERSAO_APLICACAO = "1.0.0"

#: Resoluções suportadas para o compartilhamento de tela.
RESOLUCOES: dict[str, tuple[int, int]] = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}

#: Quadros por segundo permitidos na interface.
TAXAS_QUADROS: tuple[int, ...] = (15, 24, 30, 45, 60)

#: Porta TCP padrão da aplicação.
PORTA_PADRAO = 9999

#: Latência (ida e volta) a partir da qual quadros começam a ser descartados.
LIMITE_LATENCIA_MS = 200

#: Tamanho máximo aceito para uma carga útil (proteção contra abuso).
TAMANHO_MAXIMO_CARGA = 10 * 1024 * 1024  # 10 MB


def diretorio_dados() -> Path:
    """Retorna (criando se necessário) o diretório de dados da aplicação."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home())) / NOME_APLICACAO
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / NOME_APLICACAO
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        base = base / NOME_APLICACAO.lower()
    base.mkdir(parents=True, exist_ok=True)
    return base


ARQUIVO_CONFIGURACOES = diretorio_dados() / "configuracoes.json"
ARQUIVO_REGISTRO = diretorio_dados() / "screenshare.log"


# ---------------------------------------------------------------------------
# Estruturas de configuração
# ---------------------------------------------------------------------------


@dataclass
class ConfiguracaoVideo:
    """Parâmetros de captura e compressão de vídeo."""

    resolucao: str = "720p"
    fps: int = 30
    qualidade_jpeg: int = 70
    qualidade_minima: int = 35
    qualidade_maxima: int = 90
    monitor: int = 1
    compressao_adaptativa: bool = True

    @property
    def dimensoes(self) -> tuple[int, int]:
        """Largura e altura em pixels da resolução selecionada."""
        return RESOLUCOES.get(self.resolucao, RESOLUCOES["720p"])

    @property
    def intervalo_quadro(self) -> float:
        """Intervalo, em segundos, entre dois quadros consecutivos."""
        return 1.0 / max(1, self.fps)


@dataclass
class ConfiguracaoAudio:
    """Parâmetros de captura e reprodução de áudio."""

    ativo: bool = True
    taxa_amostragem: int = 44100
    canais: int = 1
    tamanho_bloco: int = 1024
    dispositivo_entrada: int | None = None
    dispositivo_saida: int | None = None


@dataclass
class ConfiguracaoRede:
    """Parâmetros de rede e segurança da conexão."""

    endereco_escuta: str = "0.0.0.0"
    porta: int = PORTA_PADRAO
    senha: str = ""
    tempo_limite: float = 15.0
    intervalo_ping: float = 3.0
    tentativas_reconexao: int = 3
    intervalo_reconexao: float = 3.0
    tamanho_maximo_carga: int = TAMANHO_MAXIMO_CARGA


@dataclass
class ConfiguracaoInterface:
    """Preferências visuais e de identificação do usuário."""

    tema: str = "escuro"
    apelido: str = ""
    mostrar_estatisticas: bool = True

    def __post_init__(self) -> None:
        if not self.apelido:
            try:
                self.apelido = socket.gethostname()
            except OSError:  # pragma: no cover - ambiente sem hostname
                self.apelido = "Usuario"


@dataclass
class Configuracoes:
    """Agregado de todas as configurações da aplicação."""

    video: ConfiguracaoVideo = field(default_factory=ConfiguracaoVideo)
    audio: ConfiguracaoAudio = field(default_factory=ConfiguracaoAudio)
    rede: ConfiguracaoRede = field(default_factory=ConfiguracaoRede)
    interface: ConfiguracaoInterface = field(default_factory=ConfiguracaoInterface)

    # -- Serialização -------------------------------------------------------

    def para_dicionario(self) -> dict[str, Any]:
        """Converte as configurações em um dicionário serializável."""
        return asdict(self)

    def salvar(self, caminho: Path | None = None) -> Path:
        """Grava as configurações em disco e devolve o caminho utilizado."""
        destino = Path(caminho) if caminho else ARQUIVO_CONFIGURACOES
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(self.para_dicionario(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return destino

    @classmethod
    def de_dicionario(cls, dados: dict[str, Any]) -> Configuracoes:
        """Cria uma instância a partir de um dicionário (tolerante a erros)."""
        instancia = cls()
        for campo in fields(cls):
            secao = dados.get(campo.name)
            if not isinstance(secao, dict):
                continue
            objeto = getattr(instancia, campo.name)
            if not is_dataclass(objeto):
                continue
            for subcampo in fields(objeto):
                if subcampo.name in secao:
                    setattr(objeto, subcampo.name, secao[subcampo.name])
        return instancia

    @classmethod
    def carregar(cls, caminho: Path | None = None) -> Configuracoes:
        """Carrega as configurações do disco; usa os padrões em caso de falha."""
        origem = Path(caminho) if caminho else ARQUIVO_CONFIGURACOES
        if not origem.exists():
            return cls()
        try:
            dados = json.loads(origem.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls.de_dicionario(dados)


# ---------------------------------------------------------------------------
# Temas visuais
# ---------------------------------------------------------------------------

TEMAS: dict[str, dict[str, str]] = {
    "escuro": {
        "fundo": "#1e2124",
        "fundo_painel": "#2b2f33",
        "fundo_campo": "#36393f",
        "texto": "#f2f3f5",
        "texto_secundario": "#a3a6aa",
        "destaque": "#5865f2",
        "sucesso": "#3ba55d",
        "alerta": "#faa61a",
        "erro": "#ed4245",
    },
    "claro": {
        "fundo": "#f4f6f8",
        "fundo_painel": "#ffffff",
        "fundo_campo": "#e9edf1",
        "texto": "#12141a",
        "texto_secundario": "#5a616b",
        "destaque": "#3a6ff7",
        "sucesso": "#1f8a4c",
        "alerta": "#b8860b",
        "erro": "#c62828",
    },
}


def obter_tema(nome: str) -> dict[str, str]:
    """Devolve a paleta do tema informado (com fallback para o tema escuro)."""
    return TEMAS.get(nome, TEMAS["escuro"])


#: Atalhos de teclado documentados e usados pela interface.
ATALHOS: dict[str, str] = {
    "<Control-q>": "Encerrar a janela atual",
    "<Control-m>": "Ativar/desativar o microfone",
    "<Control-s>": "Iniciar/parar o compartilhamento",
    "<Control-Return>": "Enviar mensagem do chat",
}
