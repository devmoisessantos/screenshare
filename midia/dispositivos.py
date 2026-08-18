"""Enumeração uniforme dos dispositivos de áudio disponíveis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from midia import captura_audio
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

AUDIO_DISPONIVEL = captura_audio.AUDIO_DISPONIVEL
MOTIVO_AUDIO_INDISPONIVEL = captura_audio.MOTIVO_AUDIO_INDISPONIVEL


@dataclass
class DispositivoAudio:
    """Metadados de um dispositivo de entrada ou saída."""

    indice: int
    nome: str
    canais: int
    taxa_padrao: float
    entrada: bool
    padrao: bool


def _padrao_sounddevice(entrada: bool) -> int | None:
    """Obtém o índice padrão do sounddevice para a direção solicitada."""
    try:
        padrao = captura_audio._sounddevice.default.device
        indice = padrao[0 if entrada else 1]
        return None if indice is None or int(indice) < 0 else int(indice)
    except Exception:
        return None


def _listar_sounddevice(entrada: bool) -> list[DispositivoAudio]:
    """Converte dispositivos do sounddevice para o modelo público."""
    chave_canais = "max_input_channels" if entrada else "max_output_channels"
    indice_padrao = _padrao_sounddevice(entrada)
    dispositivos: list[DispositivoAudio] = []
    try:
        for indice, informacao in enumerate(captura_audio._sounddevice.query_devices()):
            canais = int(informacao.get(chave_canais, 0) or 0)
            if canais > 0:
                dispositivos.append(
                    DispositivoAudio(
                        indice=indice,
                        nome=str(informacao.get("name", f"Dispositivo {indice}")),
                        canais=canais,
                        taxa_padrao=float(informacao.get("default_samplerate", 48000)),
                        entrada=entrada,
                        padrao=indice == indice_padrao,
                    )
                )
    except Exception as erro:
        _registrador.warning("Falha ao listar dispositivos de áudio: %s", erro)
    return dispositivos


def _padrao_pyaudio(instancia: Any, entrada: bool) -> int | None:
    """Obtém o índice padrão do PyAudio para a direção solicitada."""
    try:
        informacao = (
            instancia.get_default_input_device_info()
            if entrada
            else instancia.get_default_output_device_info()
        )
        return int(informacao["index"])
    except Exception:
        return None


def _listar_pyaudio(entrada: bool) -> list[DispositivoAudio]:
    """Converte dispositivos do PyAudio para o modelo público."""
    instancia: Any = None
    chave_canais = "maxInputChannels" if entrada else "maxOutputChannels"
    try:
        instancia = captura_audio._pyaudio.PyAudio()
        indice_padrao = _padrao_pyaudio(instancia, entrada)
        dispositivos = []
        for indice in range(instancia.get_device_count()):
            informacao = instancia.get_device_info_by_index(indice)
            canais = int(informacao.get(chave_canais, 0) or 0)
            if canais > 0:
                dispositivos.append(
                    DispositivoAudio(
                        indice=indice,
                        nome=str(informacao.get("name", f"Dispositivo {indice}")),
                        canais=canais,
                        taxa_padrao=float(informacao.get("defaultSampleRate", 48000)),
                        entrada=entrada,
                        padrao=indice == indice_padrao,
                    )
                )
        return dispositivos
    except Exception as erro:
        _registrador.warning("Falha ao listar dispositivos de áudio: %s", erro)
        return []
    finally:
        if instancia is not None:
            try:
                instancia.terminate()
            except Exception:  # pragma: no cover - adaptador externo
                pass


def _listar(entrada: bool) -> list[DispositivoAudio]:
    """Escolhe o adaptador de enumeração do motor de áudio ativo."""
    if captura_audio.MOTOR_AUDIO == captura_audio.MOTOR_SOUNDDEVICE:
        return _listar_sounddevice(entrada)
    if captura_audio.MOTOR_AUDIO == captura_audio.MOTOR_PYAUDIO:
        return _listar_pyaudio(entrada)
    return []


def listar_entradas() -> list[DispositivoAudio]:
    """Lista microfones e demais dispositivos de entrada."""
    return _listar(entrada=True)


def listar_saidas() -> list[DispositivoAudio]:
    """Lista alto-falantes e demais dispositivos de saída."""
    return _listar(entrada=False)


def dispositivo_padrao(entrada: bool) -> DispositivoAudio | None:
    """Retorna o dispositivo padrão ou o primeiro disponível."""
    dispositivos = _listar(entrada)
    return next((item for item in dispositivos if item.padrao), None) or (
        dispositivos[0] if dispositivos else None
    )


def nome_do_dispositivo(indice: int | None, entrada: bool) -> str:
    """Retorna o nome legível de um dispositivo, sem lançar erro."""
    if indice is None:
        padrao = dispositivo_padrao(entrada)
        return padrao.nome if padrao is not None else "Dispositivo padrão"
    for dispositivo in _listar(entrada):
        if dispositivo.indice == indice:
            return dispositivo.nome
    return f"Dispositivo {indice}"
