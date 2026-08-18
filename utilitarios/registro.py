"""Configuração centralizada de log (registro de eventos)."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from configuracao.configuracoes import ARQUIVO_REGISTRO

_FORMATO = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
_configurado = False


def configurar_registro(nivel: int = logging.INFO) -> None:
    """Configura os manipuladores de log (console + arquivo rotativo).

    A função é idempotente: chamadas repetidas não duplicam manipuladores.
    """
    global _configurado
    if _configurado:
        return

    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    formatador = logging.Formatter(_FORMATO)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatador)
    raiz.addHandler(console)

    try:
        arquivo = logging.handlers.RotatingFileHandler(
            ARQUIVO_REGISTRO, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        arquivo.setFormatter(formatador)
        raiz.addHandler(arquivo)
    except OSError:  # pragma: no cover - sem permissão de escrita
        raiz.warning("Não foi possível criar o arquivo de log em %s", ARQUIVO_REGISTRO)

    _configurado = True


def obter_registrador(nome: str) -> logging.Logger:
    """Devolve um logger nomeado, garantindo que o log esteja configurado."""
    configurar_registro()
    return logging.getLogger(nome)
