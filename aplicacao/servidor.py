"""Servidor (host): quem compartilha a tela.

Responsabilidades:
    * escutar na porta configurada;
    * validar o handshake (versão do protocolo + senha opcional);
    * criar a :class:`~nucleo.sessao.Sessao` de transmissão;
    * aceitar um novo espectador automaticamente após uma desconexão.
"""

from __future__ import annotations

import socket
import threading
from typing import Callable

from configuracao.configuracoes import VERSAO_APLICACAO, Configuracoes
from nucleo.conexao import Conexao, ConexaoEncerrada, criar_socket_escuta
from nucleo.protocolo import (
    VERSAO_PROTOCOLO,
    ErroProtocolo,
    TipoMensagem,
    decodificar_json,
    gerar_token,
    tokens_equivalentes,
)
from nucleo.sessao import Retornos, Sessao
from utilitarios.rede import obter_ip_local
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

TEMPO_LIMITE_HANDSHAKE = 20.0


class ErroServidor(Exception):
    """Falha ao iniciar ou operar o servidor."""


class ServidorCompartilhamento:
    """Servidor ponto-a-ponto que transmite tela, áudio e chat."""

    def __init__(
        self,
        configuracoes: Configuracoes,
        retornos: Retornos | None = None,
        ao_status: Callable[[str], None] | None = None,
        ao_conectar: Callable[[dict], None] | None = None,
    ) -> None:
        self.configuracoes = configuracoes
        self.retornos = retornos or Retornos()
        self.ao_status = ao_status
        self.ao_conectar = ao_conectar

        self.sessao: Sessao | None = None
        self._soquete_escuta: socket.socket | None = None
        self._thread_aceite: threading.Thread | None = None
        self._parando = threading.Event()

    # -- Propriedades -------------------------------------------------------

    @property
    def em_execucao(self) -> bool:
        """``True`` enquanto o servidor está escutando."""
        return self._soquete_escuta is not None and not self._parando.is_set()

    @property
    def endereco_publicado(self) -> str:
        """Endereço que deve ser informado ao espectador."""
        return f"{obter_ip_local()}:{self.configuracoes.rede.porta}"

    # -- Ciclo de vida ------------------------------------------------------

    def iniciar(self) -> None:
        """Coloca o servidor em escuta e passa a aceitar conexões.

        Raises:
            ErroServidor: se a porta estiver ocupada ou indisponível.
        """
        if self.em_execucao:
            return
        self._parando.clear()
        rede = self.configuracoes.rede
        try:
            self._soquete_escuta = criar_socket_escuta(rede.endereco_escuta, rede.porta)
        except OSError as erro:
            raise ErroServidor(
                f"Não foi possível escutar na porta {rede.porta}: {erro}"
            ) from erro

        self._soquete_escuta.settimeout(1.0)
        self._thread_aceite = threading.Thread(
            target=self._laco_aceite, name="aceite-conexoes", daemon=True
        )
        self._thread_aceite.start()
        self._informar(f"Aguardando conexão em {self.endereco_publicado}")

    def parar(self, motivo: str = "Compartilhamento encerrado pelo host") -> None:
        """Encerra a sessão ativa e para de aceitar conexões."""
        self._parando.set()
        if self.sessao is not None:
            self.sessao.encerrar(motivo)
            self.sessao = None
        if self._soquete_escuta is not None:
            try:
                self._soquete_escuta.close()
            except OSError:  # pragma: no cover
                pass
            self._soquete_escuta = None
        self._informar("Servidor parado")

    # -- Aceite de conexões -------------------------------------------------

    def _laco_aceite(self) -> None:
        """Aceita um espectador por vez, reabrindo a escuta após desconexões."""
        while not self._parando.is_set() and self._soquete_escuta is not None:
            try:
                soquete_cliente, endereco = self._soquete_escuta.accept()
            except socket.timeout:
                continue
            except OSError:
                return

            if self.sessao is not None and self.sessao.ativa:
                _registrador.info("Conexão de %s recusada: sessão já em uso", endereco)
                self._recusar(soquete_cliente, "Já existe um espectador conectado")
                continue

            self._informar(f"Conexão recebida de {endereco[0]}")
            try:
                self._tratar_cliente(soquete_cliente, endereco)
            except Exception as erro:  # pragma: no cover - proteção da thread
                _registrador.exception("Falha ao tratar cliente: %s", erro)

    def _recusar(self, soquete_cliente: socket.socket, motivo: str) -> None:
        """Recusa educadamente uma conexão e fecha o socket."""
        conexao = Conexao(soquete_cliente, ("", 0))
        try:
            conexao.enviar_json(TipoMensagem.HANDSHAKE_RECUSADO, {"motivo": motivo})
        except ConexaoEncerrada:
            pass
        finally:
            conexao.fechar()

    def _tratar_cliente(self, soquete_cliente: socket.socket, endereco: tuple) -> None:
        """Executa o handshake e inicia a sessão de transmissão."""
        soquete_cliente.settimeout(TEMPO_LIMITE_HANDSHAKE)
        conexao = Conexao(
            soquete_cliente, endereco, self.configuracoes.rede.tamanho_maximo_carga
        )

        try:
            tipo, carga = conexao.receber()
            if tipo is not TipoMensagem.HANDSHAKE_PEDIDO:
                raise ErroProtocolo("Handshake esperado como primeira mensagem")
            dados = decodificar_json(carga)

            if dados.get("versao") != VERSAO_PROTOCOLO:
                conexao.enviar_json(
                    TipoMensagem.HANDSHAKE_RECUSADO,
                    {"motivo": f"Versão incompatível (servidor: {VERSAO_PROTOCOLO})"},
                )
                raise ErroProtocolo("Versão de protocolo incompatível")

            token_esperado = gerar_token(self.configuracoes.rede.senha)
            if not tokens_equivalentes(token_esperado, str(dados.get("token", ""))):
                conexao.enviar_json(
                    TipoMensagem.HANDSHAKE_RECUSADO, {"motivo": "Senha incorreta"}
                )
                raise ErroProtocolo("Senha incorreta")

            apelido_cliente = str(dados.get("apelido") or "Espectador")
            conexao.enviar_json(
                TipoMensagem.HANDSHAKE_ACEITO,
                {
                    "versao": VERSAO_PROTOCOLO,
                    "aplicacao": VERSAO_APLICACAO,
                    "apelido": self.configuracoes.interface.apelido,
                    "resolucao": self.configuracoes.video.resolucao,
                    "fps": self.configuracoes.video.fps,
                    "audio": self.configuracoes.audio.ativo,
                },
            )

            tipo, _ = conexao.receber()
            if tipo is not TipoMensagem.PRONTO:
                raise ErroProtocolo("Cliente não confirmou estar pronto")
        except (ConexaoEncerrada, ErroProtocolo) as erro:
            _registrador.warning("Handshake falhou com %s: %s", endereco, erro)
            conexao.fechar()
            self._informar(f"Conexão recusada: {erro}")
            return

        soquete_cliente.settimeout(None)

        retornos = Retornos(
            ao_video=self.retornos.ao_video,
            ao_chat=self.retornos.ao_chat,
            ao_estado=self.retornos.ao_estado,
            ao_estatisticas=self.retornos.ao_estatisticas,
            ao_encerrar=self._ao_encerrar_sessao,
            ao_erro=self.retornos.ao_erro,
        )
        self.sessao = Sessao(
            conexao=conexao,
            configuracoes=self.configuracoes,
            transmitir_video=True,
            apelido=self.configuracoes.interface.apelido,
            retornos=retornos,
        )
        self.sessao.iniciar()

        if self.ao_conectar:
            self.ao_conectar({"apelido": apelido_cliente, "ip": endereco[0]})
        self._informar(f"{apelido_cliente} conectado - transmitindo")

    def _ao_encerrar_sessao(self, motivo: str) -> None:
        """Reage ao fim da sessão, liberando a vaga para um novo espectador."""
        self.sessao = None
        if self.retornos.ao_encerrar:
            self.retornos.ao_encerrar(motivo)
        if not self._parando.is_set():
            self._informar(f"{motivo}. Aguardando nova conexão...")

    # -- Auxiliares ---------------------------------------------------------

    def _informar(self, mensagem: str) -> None:
        """Envia uma mensagem de status para a interface e para o log."""
        _registrador.info(mensagem)
        if self.ao_status:
            self.ao_status(mensagem)
