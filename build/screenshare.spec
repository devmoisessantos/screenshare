# -*- mode: python ; coding: utf-8 -*-
"""Especificação PyInstaller do ScreenShare.

Gera um único executável, sem console, com o ícone e os recursos embutidos.

Uso (dentro da pasta do projeto, com o ambiente virtual ativo)::

    pyinstaller build/screenshare.spec --noconfirm
"""

import sys
from pathlib import Path

RAIZ = Path(SPECPATH).resolve().parent
ICONE = RAIZ / "recursos" / ("icone.ico" if sys.platform.startswith("win") else "icone.png")

analise = Analysis(
    [str(RAIZ / "principal.py")],
    pathex=[str(RAIZ)],
    binaries=[],
    datas=[(str(RAIZ / "recursos"), "recursos")],
    hiddenimports=[
        "PIL._tkinter_finder",
        "mss.windows",
        "mss.linux",
        "mss.darwin",
        # Motor de áudio preferencial e sua extensão nativa; o PyAudio segue
        # listado apenas como alternativa opcional.
        "sounddevice",
        "_sounddevice",
        "cffi",
        "pyaudio",
        # WebRTC, PyAV e dependências carregadas dinamicamente pelo aiortc.
        "aiortc",
        "av",
        "aioice",
        "pylibsrtp",
        "google_crc32c",
        "ifaddr",
        "pyee",
        "dns",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "pytest", "tests"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analise.pure)

executavel = EXE(
    pyz,
    analise.scripts,
    analise.binaries,
    analise.datas,
    [],
    name="ScreenShare",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # aplicação gráfica: sem janela de terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICONE) if ICONE.exists() else None,
)
