"""Testes do módulo de áudio com motores simulados.

O PortAudio (base do sounddevice) e o PyAudio não estão presentes em
ambientes de integração contínua, portanto os motores são substituídos por
duplos de teste injetados em ``sys.modules``. Isso valida a lógica de adaptação
sem depender de hardware de áudio.
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest import mock

from configuracao.configuracoes import ConfiguracaoAudio


class FluxoFalso:
    """Substitui ``RawInputStream``/``RawOutputStream`` do sounddevice."""

    def __init__(self, **parametros: object) -> None:
        self.parametros = parametros
        self.iniciado = False
        self.fechado = False
        self.escritos: list[bytes] = []

    def start(self) -> None:
        self.iniciado = True

    def stop(self) -> None:
        self.iniciado = False

    def close(self) -> None:
        self.fechado = True

    def read(self, quadros: int) -> tuple[bytes, bool]:
        return b"\x00\x01" * quadros, False

    def write(self, dados: bytes) -> None:
        self.escritos.append(bytes(dados))


def criar_modulo_sounddevice() -> types.ModuleType:
    """Cria um módulo ``sounddevice`` falso com a API que o projeto usa."""
    modulo = types.ModuleType("sounddevice")
    modulo.RawInputStream = FluxoFalso  # type: ignore[attr-defined]
    modulo.RawOutputStream = FluxoFalso  # type: ignore[attr-defined]
    modulo.PortAudioError = RuntimeError  # type: ignore[attr-defined]
    modulo.query_devices = lambda: [  # type: ignore[attr-defined]
        {"name": "Microfone falso", "max_input_channels": 2, "max_output_channels": 0},
        {"name": "Alto-falante falso", "max_input_channels": 0, "max_output_channels": 2},
    ]
    modulo.__version__ = "0.0-teste"  # type: ignore[attr-defined]
    return modulo


class TesteMotorSounddevice(unittest.TestCase):
    """Valida a captura e a reprodução usando o sounddevice simulado."""

    def setUp(self) -> None:
        self._modulos_originais = {
            nome: sys.modules.get(nome) for nome in ("sounddevice", "pyaudio")
        }
        sys.modules["sounddevice"] = criar_modulo_sounddevice()
        sys.modules.pop("pyaudio", None)
        self.audio = importlib.reload(importlib.import_module("midia.captura_audio"))

    def tearDown(self) -> None:
        for nome, modulo in self._modulos_originais.items():
            if modulo is None:
                sys.modules.pop(nome, None)
            else:
                sys.modules[nome] = modulo
        importlib.reload(importlib.import_module("midia.captura_audio"))

    def test_motor_detectado_e_sounddevice(self) -> None:
        self.assertTrue(self.audio.AUDIO_DISPONIVEL)
        self.assertEqual(self.audio.MOTOR_AUDIO, self.audio.MOTOR_SOUNDDEVICE)
        self.assertIn("sounddevice", self.audio.descrever_motor_audio())

    def test_capturador_le_blocos(self) -> None:
        capturador = self.audio.CapturadorAudio(ConfiguracaoAudio(tamanho_bloco=64))
        capturador.abrir()
        try:
            bloco = capturador.ler()
        finally:
            capturador.fechar()
        self.assertEqual(len(bloco), 64 * 2)

    def test_reprodutor_escreve_blocos(self) -> None:
        reprodutor = self.audio.ReprodutorAudio(ConfiguracaoAudio(tamanho_bloco=32))
        reprodutor.iniciar()
        try:
            reprodutor.escrever(b"\x00\x01" * 32)
            self.assertTrue(reprodutor.disponivel)
        finally:
            reprodutor.parar()

    def test_reprodutor_descarta_ao_encher_a_fila(self) -> None:
        """Com a fila cheia, o bloco mais antigo cede lugar ao mais recente."""
        reprodutor = self.audio.ReprodutorAudio(
            ConfiguracaoAudio(tamanho_bloco=32), limite_fila=2
        )
        reprodutor._ativo = True  # evita depender da thread de reprodução
        for indice in range(5):
            reprodutor.escrever(bytes([indice]))
        self.assertEqual(reprodutor.blocos_descartados, 3)
        self.assertEqual(reprodutor._fila.qsize(), 2)

    def test_listar_dispositivos_de_entrada(self) -> None:
        dispositivos = self.audio.listar_dispositivos(entrada=True)
        self.assertEqual(len(dispositivos), 1)
        self.assertIn("Microfone falso", dispositivos[0])


class TesteAudioIndisponivel(unittest.TestCase):
    """Garante degradação suave quando nenhum motor está presente."""

    def setUp(self) -> None:
        self._modulos_originais = {
            nome: sys.modules.get(nome) for nome in ("sounddevice", "pyaudio")
        }
        for nome in ("sounddevice", "pyaudio"):
            sys.modules.pop(nome, None)
        self._importacao = mock.patch.dict(
            sys.modules, {"sounddevice": None, "pyaudio": None}
        )
        self._importacao.start()
        self.audio = importlib.reload(importlib.import_module("midia.captura_audio"))

    def tearDown(self) -> None:
        self._importacao.stop()
        for nome, modulo in self._modulos_originais.items():
            if modulo is None:
                sys.modules.pop(nome, None)
            else:
                sys.modules[nome] = modulo
        importlib.reload(importlib.import_module("midia.captura_audio"))

    def test_sem_motor_o_audio_fica_indisponivel(self) -> None:
        self.assertFalse(self.audio.AUDIO_DISPONIVEL)
        self.assertTrue(self.audio.MOTIVO_AUDIO_INDISPONIVEL)

    def test_capturador_recusa_abertura(self) -> None:
        capturador = self.audio.CapturadorAudio(ConfiguracaoAudio())
        self.assertFalse(capturador.disponivel)
        with self.assertRaises(self.audio.ErroAudio):
            capturador.abrir()

    def test_reprodutor_ignora_escritas(self) -> None:
        reprodutor = self.audio.ReprodutorAudio(ConfiguracaoAudio())
        self.assertFalse(reprodutor.disponivel)
        reprodutor.escrever(b"\x00\x01")  # não deve lançar exceção
        reprodutor.parar()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
