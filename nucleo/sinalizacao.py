"""Cliente WebSocket para o protocolo de sinalização WebRTC."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

import aiohttp

from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

RetornoBemVindo = Callable[[str, str, list[dict[str, str]]], None]
RetornoEntrou = Callable[[str, str], None]
RetornoSaiu = Callable[[str], None]
RetornoSinal = Callable[[str, dict[str, Any]], None]
RetornoErro = Callable[[str, str], None]
RetornoDesconectar = Callable[[], None]


class ClienteSinalizacao:
    """Mantém uma conexão WebSocket e repassa eventos por callbacks síncronos.

    Os callbacks recebem, respectivamente: ``(id, sala, participantes)`` em
    ``ao_bem_vindo``; ``(id, apelido)`` em ``ao_entrou``; ``id`` em ``ao_saiu``;
    ``(origem, dados)`` em ``ao_sinal``; ``(codigo, mensagem)`` em ``ao_erro``;
    e nenhum argumento em ``ao_desconectar``.
    """

    def __init__(
        self,
        url: str,
        ao_bem_vindo: RetornoBemVindo | None = None,
        ao_entrou: RetornoEntrou | None = None,
        ao_saiu: RetornoSaiu | None = None,
        ao_sinal: RetornoSinal | None = None,
        ao_erro: RetornoErro | None = None,
        ao_desconectar: RetornoDesconectar | None = None,
        *,
        tentativas_reconexao: int = 5,
    ) -> None:
        self.url = url
        self.ao_bem_vindo = ao_bem_vindo
        self.ao_entrou = ao_entrou
        self.ao_saiu = ao_saiu
        self.ao_sinal = ao_sinal
        self.ao_erro = ao_erro
        self.ao_desconectar = ao_desconectar
        self.tentativas_reconexao = max(0, tentativas_reconexao)

        self._sessao: aiohttp.ClientSession | None = None
        self._conexao_websocket: aiohttp.ClientWebSocketResponse | None = None
        self._tarefa_leitura: asyncio.Task[None] | None = None
        self._tarefa_ping: asyncio.Task[None] | None = None
        self._encerrando = False
        self._evento_encerramento = asyncio.Event()
        self._id_local: str | None = None
        self._participantes: dict[str, str] = {}
        self._pedido_entrada: dict[str, str] | None = None

    @property
    def conectado(self) -> bool:
        """Indica se há uma conexão WebSocket aberta."""
        return self._conexao_websocket is not None and not self._conexao_websocket.closed

    @property
    def id_local(self) -> str | None:
        """Identificador atribuído pelo servidor após a entrada na sala."""
        return self._id_local

    @property
    def participantes(self) -> list[dict[str, str]]:
        """Lista independente dos demais participantes conhecidos da sala."""
        return [
            {"id": identificador, "apelido": apelido}
            for identificador, apelido in self._participantes.items()
        ]

    async def conectar(self) -> bool:
        """Abre o WebSocket e inicia os laços de leitura e de ping."""
        if self.conectado:
            return True
        self._encerrando = False
        self._evento_encerramento.clear()
        if not await self._abrir_conexao():
            return False
        self._iniciar_tarefas()
        return True

    async def entrar(self, sala: str, apelido: str, senha: str = "") -> bool:
        """Solicita entrada em uma sala e guarda os dados para reconexão."""
        if not isinstance(sala, str) or not isinstance(apelido, str) or not isinstance(senha, str):
            self._notificar_erro("DADOS_INVALIDOS", "Sala, apelido e senha devem ser textos válidos.")
            return False
        codigo = "".join(sala.upper().split())
        if not codigo or not apelido.strip():
            self._notificar_erro("DADOS_INVALIDOS", "Informe um código de sala e um apelido.")
            return False
        if not self.conectado and not await self.conectar():
            return False

        pedido = {"sala": codigo, "apelido": apelido.strip(), "senha": senha}
        if not await self._enviar_json({"tipo": "entrar", **pedido}):
            return False
        self._pedido_entrada = pedido
        return True

    async def enviar_sinal(self, destino: str, dados: dict[str, Any]) -> bool:
        """Encaminha uma oferta, resposta ou candidato ao par indicado."""
        if not isinstance(destino, str) or not isinstance(dados, dict):
            self._notificar_erro(
                "DADOS_INVALIDOS", "Destino e dados de sinalização são obrigatórios."
            )
            return False
        return await self._enviar_json({"tipo": "sinal", "destino": destino, "dados": dados})

    async def sair(self) -> bool:
        """Sai da sala atual sem necessariamente fechar o WebSocket."""
        enviado = True
        if self.conectado:
            enviado = await self._enviar_json({"tipo": "sair"})
        self._limpar_entrada()
        return enviado

    async def fechar(self) -> None:
        """Encerra tarefas, WebSocket e sessão HTTP sem tentar reconectar."""
        if self._encerrando and self._sessao is None:
            return
        if self.conectado:
            await self.sair()
        self._encerrando = True
        self._evento_encerramento.set()

        conexao = self._conexao_websocket
        self._conexao_websocket = None
        if conexao is not None and not conexao.closed:
            with contextlib.suppress(aiohttp.ClientError, RuntimeError):
                await conexao.close()

        tarefa_atual = asyncio.current_task()
        await self._cancelar_tarefa(self._tarefa_leitura, tarefa_atual)
        await self._cancelar_tarefa(self._tarefa_ping, tarefa_atual)
        self._tarefa_leitura = None
        self._tarefa_ping = None

        if self._sessao is not None:
            with contextlib.suppress(aiohttp.ClientError, RuntimeError):
                await self._sessao.close()
            self._sessao = None
        self._limpar_entrada()

    async def _abrir_conexao(self) -> bool:
        """Abre uma conexão, convertendo falhas de rede em callback de erro."""
        try:
            if self._sessao is None or self._sessao.closed:
                self._sessao = aiohttp.ClientSession()
            self._conexao_websocket = await self._sessao.ws_connect(self.url, heartbeat=30.0)
            _registrador.info("Conectado ao servidor de sinalização.")
            return True
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as erro:
            self._conexao_websocket = None
            self._notificar_erro("CONEXAO_FALHOU", f"Não foi possível conectar: {erro}")
            return False

    def _iniciar_tarefas(self) -> None:
        """Garante que os dois laços de trabalho estejam ativos."""
        if self._tarefa_leitura is None or self._tarefa_leitura.done():
            self._tarefa_leitura = asyncio.create_task(
                self._laco_leitura(), name="leitura-sinalizacao"
            )
        if self._tarefa_ping is None or self._tarefa_ping.done():
            self._tarefa_ping = asyncio.create_task(self._laco_ping(), name="ping-sinalizacao")

    async def _laco_leitura(self) -> None:
        """Recebe mensagens e refaz a conexão quando ela cai inesperadamente."""
        while not self._encerrando:
            conexao = self._conexao_websocket
            if conexao is None:
                if not await self._reconectar():
                    return
                continue

            try:
                async for mensagem in conexao:
                    if mensagem.type is aiohttp.WSMsgType.TEXT:
                        self._tratar_mensagem(mensagem.json())
                    elif mensagem.type is aiohttp.WSMsgType.ERROR:
                        _registrador.warning("WebSocket encerrado com erro: %s", conexao.exception())
                        break
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as erro:
                self._notificar_erro("ERRO_REDE", f"Conexão de sinalização interrompida: {erro}")
            finally:
                if self._conexao_websocket is conexao:
                    self._conexao_websocket = None

            if self._encerrando:
                return
            self._notificar_callback(self.ao_desconectar)
            if not await self._reconectar():
                return

    async def _laco_ping(self) -> None:
        """Envia a mensagem de ping definida pelo protocolo a cada 15 segundos."""
        while not self._encerrando:
            try:
                await asyncio.wait_for(self._evento_encerramento.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                if self.conectado:
                    await self._enviar_json({"tipo": "ping"})
                continue
            return

    async def _reconectar(self) -> bool:
        """Tenta reconectar com espera progressiva até o limite configurado."""
        for tentativa in range(1, self.tentativas_reconexao + 1):
            if self._encerrando:
                return False
            try:
                await asyncio.wait_for(self._evento_encerramento.wait(), timeout=float(tentativa))
                return False
            except asyncio.TimeoutError:
                pass
            if await self._abrir_conexao():
                await self._restaurar_entrada()
                return True
        self._notificar_erro(
            "RECONEXAO_ESGOTADA", "Não foi possível restabelecer a conexão de sinalização."
        )
        return False

    async def _restaurar_entrada(self) -> None:
        """Entra novamente na última sala depois de uma reconexão bem-sucedida."""
        if self._pedido_entrada is None:
            return
        self._id_local = None
        self._participantes.clear()
        await self._enviar_json({"tipo": "entrar", **self._pedido_entrada})

    async def _enviar_json(self, dados: dict[str, Any]) -> bool:
        """Envia JSON e traduz falhas de rede para o callback de erro."""
        conexao = self._conexao_websocket
        if conexao is None or conexao.closed:
            self._notificar_erro("NAO_CONECTADO", "Não há conexão com o servidor de sinalização.")
            return False
        try:
            await conexao.send_json(dados)
            return True
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, RuntimeError) as erro:
            self._notificar_erro("ERRO_REDE", f"Não foi possível enviar sinalização: {erro}")
            with contextlib.suppress(aiohttp.ClientError, RuntimeError):
                await conexao.close()
            return False

    def _tratar_mensagem(self, dados: Any) -> None:
        """Atualiza o estado local e chama o callback correspondente."""
        if not isinstance(dados, dict):
            self._notificar_erro("DADOS_INVALIDOS", "O servidor enviou uma mensagem inválida.")
            return
        tipo = dados.get("tipo")
        if tipo == "bem_vindo":
            self._tratar_bem_vindo(dados)
        elif tipo == "entrou":
            identificador = dados.get("id")
            apelido = dados.get("apelido")
            if isinstance(identificador, str) and isinstance(apelido, str):
                self._participantes[identificador] = apelido
                self._notificar_callback(self.ao_entrou, identificador, apelido)
        elif tipo == "saiu":
            identificador = dados.get("id")
            if isinstance(identificador, str):
                self._participantes.pop(identificador, None)
                self._notificar_callback(self.ao_saiu, identificador)
        elif tipo == "sinal":
            origem = dados.get("origem")
            sinal = dados.get("dados")
            if isinstance(origem, str) and isinstance(sinal, dict):
                self._notificar_callback(self.ao_sinal, origem, sinal)
        elif tipo == "erro":
            codigo = dados.get("codigo")
            mensagem = dados.get("mensagem")
            if isinstance(codigo, str) and isinstance(mensagem, str):
                self._notificar_erro(codigo, mensagem)
        elif tipo != "pong":
            self._notificar_erro("TIPO_DESCONHECIDO", "O servidor enviou um tipo desconhecido.")

    def _tratar_bem_vindo(self, dados: dict[str, Any]) -> None:
        """Registra a lista inicial devolvida pelo servidor ao entrar na sala."""
        identificador = dados.get("id")
        sala = dados.get("sala")
        participantes = dados.get("participantes")
        if not isinstance(identificador, str) or not isinstance(sala, str) or not isinstance(
            participantes, list
        ):
            self._notificar_erro("DADOS_INVALIDOS", "A mensagem de boas-vindas é inválida.")
            return
        novos_participantes: dict[str, str] = {}
        for participante in participantes:
            if not isinstance(participante, dict):
                continue
            id_par = participante.get("id")
            apelido = participante.get("apelido")
            if isinstance(id_par, str) and isinstance(apelido, str):
                novos_participantes[id_par] = apelido
        self._id_local = identificador
        self._participantes = novos_participantes
        self._notificar_callback(self.ao_bem_vindo, identificador, sala, self.participantes)

    def _limpar_entrada(self) -> None:
        """Descarta o estado local da sala atual."""
        self._id_local = None
        self._participantes.clear()
        self._pedido_entrada = None

    def _notificar_erro(self, codigo: str, mensagem: str) -> None:
        """Registra e repassa erros sem permitir que callbacks interrompam tarefas."""
        _registrador.warning("%s: %s", codigo, mensagem)
        self._notificar_callback(self.ao_erro, codigo, mensagem)

    @staticmethod
    async def _cancelar_tarefa(
        tarefa: asyncio.Task[None] | None, tarefa_atual: asyncio.Task[Any] | None
    ) -> None:
        """Cancela uma tarefa distinta da tarefa que chamou o encerramento."""
        if tarefa is None or tarefa is tarefa_atual or tarefa.done():
            return
        tarefa.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarefa

    @staticmethod
    def _notificar_callback(retorno: Callable[..., None] | None, *argumentos: Any) -> None:
        """Executa callback síncrono sem comprometer o transporte de sinalização."""
        if retorno is None:
            return
        try:
            retorno(*argumentos)
        except Exception as erro:
            _registrador.exception("Callback de sinalização falhou: %s", erro)
