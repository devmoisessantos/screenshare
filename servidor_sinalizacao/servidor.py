"""Servidor WebSocket independente para a sinalização WebRTC do ScreenShare."""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web

LIMITE_PARTICIPANTES = 6
_REGISTRADOR = logging.getLogger(__name__)


@dataclass
class _Participante:
    """Dados privados de uma conexão participante."""

    apelido: str
    websocket: web.WebSocketResponse


@dataclass
class Sala:
    """Agrupa os participantes de uma mesma sala de sinalização."""

    codigo: str
    senha: str = ""
    participantes: dict[str, _Participante] = field(default_factory=dict)

    @property
    def vazia(self) -> bool:
        """Indica se a sala já não possui participantes."""
        return not self.participantes


class ServidorSinalizacao:
    """Coordena salas e encaminha mensagens de sinalização entre pares."""

    def __init__(self) -> None:
        self.salas: dict[str, Sala] = {}

    def criar_aplicacao(self) -> web.Application:
        """Cria a aplicação aiohttp que expõe WebSocket e verificação de saúde."""
        aplicacao = web.Application()
        aplicacao.router.add_get("/ws", self.tratar_websocket)
        aplicacao.router.add_get("/saude", self.tratar_saude)
        return aplicacao

    async def tratar_saude(self, requisicao: web.Request) -> web.Response:
        """Devolve o estado mínimo usado por serviços de hospedagem."""
        del requisicao
        participantes = sum(len(sala.participantes) for sala in self.salas.values())
        return web.json_response(
            {"situacao": "ok", "salas": len(self.salas), "participantes": participantes}
        )

    async def tratar_websocket(self, requisicao: web.Request) -> web.WebSocketResponse:
        """Recebe, valida e despacha as mensagens de uma conexão WebSocket."""
        websocket = web.WebSocketResponse(heartbeat=30.0)
        await websocket.prepare(requisicao)
        id_participante: str | None = None
        sala_atual: Sala | None = None

        try:
            async for mensagem in websocket:
                if mensagem.type is WSMsgType.TEXT:
                    dados = self._ler_mensagem(mensagem.data)
                    if dados is None:
                        await self._enviar_erro(websocket, "JSON_INVALIDO", "Mensagem JSON inválida.")
                        continue
                    id_participante, sala_atual = await self._despachar(
                        websocket, dados, id_participante, sala_atual
                    )
                elif mensagem.type is WSMsgType.ERROR:
                    _REGISTRADOR.warning("WebSocket encerrado com erro: %s", websocket.exception())
                    break
                elif mensagem.type is WSMsgType.BINARY:
                    await self._enviar_erro(
                        websocket, "DADOS_INVALIDOS", "A mensagem deve ser um objeto JSON."
                    )
        finally:
            if id_participante is not None and sala_atual is not None:
                await self._sair_da_sala(sala_atual, id_participante)
        return websocket

    @staticmethod
    def _ler_mensagem(texto: str) -> dict[str, Any] | None:
        """Converte uma mensagem textual em objeto JSON do protocolo."""
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError:
            return None
        return dados if isinstance(dados, dict) else None

    async def _despachar(
        self,
        websocket: web.WebSocketResponse,
        dados: dict[str, Any],
        id_participante: str | None,
        sala_atual: Sala | None,
    ) -> tuple[str | None, Sala | None]:
        """Executa a ação correspondente ao tipo recebido."""
        tipo = dados.get("tipo")
        if not isinstance(tipo, str):
            await self._enviar_erro(websocket, "DADOS_INVALIDOS", "O campo tipo é obrigatório.")
            return id_participante, sala_atual

        if tipo == "entrar":
            return await self._entrar(websocket, dados, id_participante, sala_atual)
        if tipo == "sinal":
            await self._encaminhar_sinal(websocket, dados, id_participante, sala_atual)
        elif tipo == "sair":
            if id_participante is not None and sala_atual is not None:
                await self._sair_da_sala(sala_atual, id_participante)
                return None, None
        elif tipo == "ping":
            await self._enviar_json(websocket, {"tipo": "pong"})
        else:
            await self._enviar_erro(websocket, "TIPO_DESCONHECIDO", "Tipo de mensagem desconhecido.")
        return id_participante, sala_atual

    async def _entrar(
        self,
        websocket: web.WebSocketResponse,
        dados: dict[str, Any],
        id_anterior: str | None,
        sala_anterior: Sala | None,
    ) -> tuple[str | None, Sala | None]:
        """Inclui uma conexão em uma sala, criando-a quando necessário."""
        codigo = self._normalizar_codigo(dados.get("sala"))
        apelido = dados.get("apelido")
        senha = dados.get("senha", "")
        if not codigo or not isinstance(apelido, str) or not apelido.strip() or not isinstance(senha, str):
            await self._enviar_erro(
                websocket, "DADOS_INVALIDOS", "Sala, apelido e senha devem ser textos válidos."
            )
            return id_anterior, sala_anterior

        sala = self.salas.get(codigo)
        if sala is not None and sala.senha and not hmac.compare_digest(
            sala.senha.encode("utf-8"), senha.encode("utf-8")
        ):
            await self._enviar_erro(websocket, "SENHA_INCORRETA", "A senha da sala está incorreta.")
            return id_anterior, sala_anterior
        if sala is not None and len(sala.participantes) >= LIMITE_PARTICIPANTES:
            await self._enviar_erro(websocket, "SALA_CHEIA", "A sala já atingiu o limite de participantes.")
            return id_anterior, sala_anterior

        if id_anterior is not None and sala_anterior is not None:
            await self._sair_da_sala(sala_anterior, id_anterior)

        if sala is None:
            sala = Sala(codigo=codigo, senha=senha)
            self.salas[codigo] = sala

        participantes = [
            {"id": identificador, "apelido": participante.apelido}
            for identificador, participante in sala.participantes.items()
        ]
        identificador = uuid.uuid4().hex[:12]
        sala.participantes[identificador] = _Participante(apelido.strip(), websocket)
        await self._enviar_json(
            websocket,
            {"tipo": "bem_vindo", "id": identificador, "sala": codigo, "participantes": participantes},
        )
        await self._difundir(
            sala,
            {"tipo": "entrou", "id": identificador, "apelido": apelido.strip()},
            exceto=identificador,
        )
        _REGISTRADOR.info("Participante entrou na sala %s", codigo)
        return identificador, sala

    async def _encaminhar_sinal(
        self,
        websocket: web.WebSocketResponse,
        dados: dict[str, Any],
        origem: str | None,
        sala: Sala | None,
    ) -> None:
        """Encaminha dados de WebRTC somente ao participante de destino."""
        destino = dados.get("destino")
        sinal = dados.get("dados")
        if origem is None or sala is None:
            await self._enviar_erro(websocket, "SALA_INEXISTENTE", "Entre em uma sala antes de sinalizar.")
            return
        if not isinstance(destino, str) or not isinstance(sinal, dict):
            await self._enviar_erro(
                websocket, "DADOS_INVALIDOS", "Destino e dados de sinalização são obrigatórios."
            )
            return
        participante = sala.participantes.get(destino)
        if participante is None:
            await self._enviar_erro(
                websocket, "PARTICIPANTE_INEXISTENTE", "O participante de destino não está na sala."
            )
            return
        await self._enviar_json(participante.websocket, {"tipo": "sinal", "origem": origem, "dados": sinal})

    async def _sair_da_sala(self, sala: Sala, identificador: str) -> None:
        """Remove o participante e avisa os pares restantes."""
        if sala.participantes.pop(identificador, None) is None:
            return
        await self._difundir(sala, {"tipo": "saiu", "id": identificador})
        if sala.vazia:
            self.salas.pop(sala.codigo, None)
        _REGISTRADOR.info("Participante saiu da sala %s", sala.codigo)

    @staticmethod
    def _normalizar_codigo(codigo: Any) -> str:
        """Remove espaços e normaliza o código de sala para letras maiúsculas."""
        return "".join(codigo.upper().split()) if isinstance(codigo, str) else ""

    async def _difundir(
        self, sala: Sala, dados: dict[str, Any], exceto: str | None = None
    ) -> None:
        """Envia uma mensagem aos participantes atuais sem expor seus sockets."""
        for identificador, participante in tuple(sala.participantes.items()):
            if identificador != exceto:
                await self._enviar_json(participante.websocket, dados)

    @staticmethod
    async def _enviar_json(websocket: web.WebSocketResponse, dados: dict[str, Any]) -> None:
        """Envia um único objeto JSON, ignorando conexões já encerradas."""
        if websocket.closed:
            return
        try:
            await websocket.send_json(dados)
        except (ConnectionResetError, RuntimeError):
            _REGISTRADOR.debug("Não foi possível enviar mensagem a uma conexão encerrada.")

    async def _enviar_erro(
        self, websocket: web.WebSocketResponse, codigo: str, mensagem: str
    ) -> None:
        """Envia uma resposta de erro definida pelo protocolo."""
        await self._enviar_json(websocket, {"tipo": "erro", "codigo": codigo, "mensagem": mensagem})


def _porta_padrao() -> int:
    """Obtém a porta definida pela hospedagem sem falhar para valor inválido."""
    try:
        return int(os.environ.get("PORT", "8080"))
    except ValueError:
        return 8080


def main() -> None:
    """Inicia o servidor por linha de comando."""
    argumentos = argparse.ArgumentParser(description="Servidor de sinalização WebRTC.")
    argumentos.add_argument("--host", default="0.0.0.0", help="Endereço de escuta.")
    argumentos.add_argument("--porta", type=int, default=_porta_padrao(), help="Porta de escuta.")
    opcoes = argumentos.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    servidor = ServidorSinalizacao()
    web.run_app(servidor.criar_aplicacao(), host=opcoes.host, port=opcoes.porta)


if __name__ == "__main__":
    main()
