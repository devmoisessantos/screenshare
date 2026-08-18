"""Enumeração das fontes de imagem disponíveis para compartilhamento."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

import mss

from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)


@dataclass
class FonteCaptura:
    """Uma tela, monitor ou janela que pode ser compartilhada."""

    identificador: str
    titulo: str
    tipo: str
    regiao: dict[str, int] | None
    indice_monitor: int | None
    identificador_janela: int | None


def _regiao_valida(regiao: dict[str, Any]) -> dict[str, int]:
    """Converte uma região do mss para o formato público do módulo."""
    return {
        "left": int(regiao["left"]),
        "top": int(regiao["top"]),
        "width": int(regiao["width"]),
        "height": int(regiao["height"]),
    }


def _listar_monitores() -> list[dict[str, int]]:
    """Lê os monitores com tolerância a ambientes sem servidor gráfico."""
    try:
        with mss.mss() as captura:
            return [_regiao_valida(monitor) for monitor in captura.monitors]
    except Exception as erro:
        _registrador.warning("Não foi possível listar monitores: %s", erro)
        return []


def _suporte_janelas() -> tuple[bool, str]:
    """Informa se há um mecanismo de enumeração de janelas na plataforma."""
    if sys.platform.startswith("win") and hasattr(ctypes, "windll"):
        return True, ""
    if sys.platform == "darwin":
        try:
            import Quartz  # noqa: PLC0415

            del Quartz
            return True, ""
        except Exception as erro:
            return False, f"Quartz indisponível: {erro}"
    if shutil.which("xdotool") or shutil.which("wmctrl"):
        return True, ""
    return False, "xdotool e wmctrl não estão instalados"


JANELAS_DISPONIVEIS, MOTIVO_JANELAS_INDISPONIVEIS = _suporte_janelas()


def _janelas_windows() -> list[FonteCaptura]:
    """Enumera janelas visíveis pelo user32 do Windows."""
    if not hasattr(ctypes, "windll"):  # pragma: no cover - depende do Windows
        return []

    user32 = ctypes.windll.user32
    janelas: list[FonteCaptura] = []
    processo_atual = os.getpid()

    class Retangulo(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    def ao_enumerar(janela: int, _parametro: int) -> bool:
        if not user32.IsWindowVisible(janela) or user32.IsIconic(janela):
            return True
        tamanho = user32.GetWindowTextLengthW(janela)
        if tamanho <= 0:
            return True
        titulo = ctypes.create_unicode_buffer(tamanho + 1)
        user32.GetWindowTextW(janela, titulo, tamanho + 1)
        if not titulo.value.strip():
            return True
        identificador_processo = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(janela, ctypes.byref(identificador_processo))
        if identificador_processo.value == processo_atual:
            return True
        retangulo = Retangulo()
        if not user32.GetWindowRect(janela, ctypes.byref(retangulo)):
            return True
        largura = retangulo.right - retangulo.left
        altura = retangulo.bottom - retangulo.top
        if largura <= 0 or altura <= 0:
            return True
        janelas.append(
            FonteCaptura(
                identificador=f"janela:{janela}",
                titulo=titulo.value.strip(),
                tipo="janela",
                regiao={
                    "left": retangulo.left,
                    "top": retangulo.top,
                    "width": largura,
                    "height": altura,
                },
                indice_monitor=None,
                identificador_janela=int(janela),
            )
        )
        return True

    tipo_callback = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
    )
    callback = tipo_callback(ao_enumerar)
    user32.EnumWindows(callback, 0)
    return janelas


def _executar(comando: list[str]) -> str:
    """Executa uma consulta gráfica curta, sem propagar falhas externas."""
    resultado = subprocess.run(
        comando,
        check=False,
        capture_output=True,
        text=True,
        timeout=0.5,
    )
    if resultado.returncode != 0:
        return ""
    return resultado.stdout.strip()


def _janelas_xdotool() -> list[FonteCaptura]:
    """Enumera janelas no Linux pelo xdotool, quando presente."""
    if not shutil.which("xdotool"):
        return []
    identificadores = _executar(["xdotool", "search", "--onlyvisible", "--name", "."])
    janelas: list[FonteCaptura] = []
    for texto_identificador in identificadores.splitlines():
        try:
            identificador = int(texto_identificador)
        except ValueError:
            continue
        processo = _executar(["xdotool", "getwindowpid", str(identificador)])
        if processo.isdigit() and int(processo) == os.getpid():
            continue
        geometria = _executar(["xdotool", "getwindowgeometry", "--shell", str(identificador)])
        valores = dict(
            linha.split("=", 1) for linha in geometria.splitlines() if "=" in linha
        )
        try:
            regiao = {
                "left": int(valores["X"]),
                "top": int(valores["Y"]),
                "width": int(valores["WIDTH"]),
                "height": int(valores["HEIGHT"]),
            }
        except (KeyError, ValueError):
            continue
        titulo = _executar(["xdotool", "getwindowname", str(identificador)]).strip()
        if titulo and regiao["width"] > 0 and regiao["height"] > 0:
            janelas.append(
                FonteCaptura(
                    identificador=f"janela:{identificador}",
                    titulo=titulo,
                    tipo="janela",
                    regiao=regiao,
                    indice_monitor=None,
                    identificador_janela=identificador,
                )
            )
    return janelas


def _janelas_wmctrl() -> list[FonteCaptura]:
    """Enumera janelas no Linux pelo wmctrl, quando presente."""
    if not shutil.which("wmctrl"):
        return []
    janelas: list[FonteCaptura] = []
    for linha in _executar(["wmctrl", "-lG"]).splitlines():
        partes = linha.split(maxsplit=7)
        if len(partes) < 8:
            continue
        try:
            identificador = int(partes[0], 16)
            area_trabalho, esquerda, topo, largura, altura = map(int, partes[1:6])
        except ValueError:
            continue
        titulo = partes[7].strip()
        if area_trabalho < 0 or not titulo or largura <= 0 or altura <= 0:
            continue
        janelas.append(
            FonteCaptura(
                identificador=f"janela:{identificador}",
                titulo=titulo,
                tipo="janela",
                regiao={
                    "left": esquerda,
                    "top": topo,
                    "width": largura,
                    "height": altura,
                },
                indice_monitor=None,
                identificador_janela=identificador,
            )
        )
    return janelas


def _janelas_macos() -> list[FonteCaptura]:
    """Enumera janelas visíveis do macOS por Quartz."""
    try:
        import Quartz  # noqa: PLC0415
    except Exception:  # pragma: no cover - depende do macOS
        return []
    opcoes = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    janelas: list[FonteCaptura] = []
    for informacao in Quartz.CGWindowListCopyWindowInfo(opcoes, Quartz.kCGNullWindowID):
        titulo = str(informacao.get(Quartz.kCGWindowName, "")).strip()
        identificador = int(informacao.get(Quartz.kCGWindowNumber, 0))
        dono = int(informacao.get(Quartz.kCGWindowOwnerPID, 0))
        limites = informacao.get(Quartz.kCGWindowBounds, {})
        if dono == os.getpid() or not titulo or not identificador:
            continue
        regiao = {
            "left": int(limites.get("X", 0)),
            "top": int(limites.get("Y", 0)),
            "width": int(limites.get("Width", 0)),
            "height": int(limites.get("Height", 0)),
        }
        if regiao["width"] > 0 and regiao["height"] > 0:
            janelas.append(
                FonteCaptura(
                    identificador=f"janela:{identificador}",
                    titulo=titulo,
                    tipo="janela",
                    regiao=regiao,
                    indice_monitor=None,
                    identificador_janela=identificador,
                )
            )
    return janelas


def _listar_janelas() -> list[FonteCaptura]:
    """Lista janelas usando o mecanismo disponível na plataforma."""
    try:
        if sys.platform.startswith("win"):
            return _janelas_windows()
        if sys.platform == "darwin":
            return _janelas_macos()
        return _janelas_xdotool() or _janelas_wmctrl()
    except Exception as erro:
        _registrador.warning("Não foi possível listar janelas: %s", erro)
        return []


def listar_fontes() -> list[FonteCaptura]:
    """Lista a área de trabalho, monitores individuais e janelas visíveis."""
    monitores = _listar_monitores()
    regiao_total = monitores[0] if monitores else None
    fontes = [
        FonteCaptura(
            identificador="tela-inteira",
            titulo="Toda a área de trabalho",
            tipo="tela_inteira",
            regiao=regiao_total,
            indice_monitor=0 if regiao_total is not None else None,
            identificador_janela=None,
        )
    ]
    for indice, monitor in enumerate(monitores[1:], start=1):
        fontes.append(
            FonteCaptura(
                identificador=f"monitor:{indice}",
                titulo=f"Monitor {indice} ({monitor['width']}x{monitor['height']})",
                tipo="monitor",
                regiao=monitor,
                indice_monitor=indice,
                identificador_janela=None,
            )
        )
    if JANELAS_DISPONIVEIS:
        fontes.extend(_listar_janelas())
    return fontes


def regiao_da_janela(identificador: int | str) -> dict[str, int] | None:
    """Reconsulta a região de uma janela, pois ela pode ter sido movida."""
    identificador_texto = str(identificador).removeprefix("janela:")
    try:
        identificador_numerico = int(identificador_texto)
    except ValueError:
        return None
    if not JANELAS_DISPONIVEIS:
        return None
    for janela in _listar_janelas():
        if janela.identificador_janela == identificador_numerico:
            return janela.regiao
    return None
