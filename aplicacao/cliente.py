"""Cliente (espectador): quem assiste à tela compartilhada.

Além do handshake, o cliente implementa reconexão automática: quando a
sessão cai por motivo de rede, novas tentativas são feitas conforme as
configurações (``tentativas_reconexao`` e ``intervalo_reconexao``).
"""

from __future__ import annotations

import threading
from typing import Callable

from configuracao.configuracoes import Configuracoes
from nucleo.conexao import Conexao, ConexaoEncerrada, conectar
from nucleo.protocolo import (
    ErroProtocolo,
    TipoMensagem,
    decodificar_json,
    gerar_token,
    mensagem_handshake,
)
from nucleo.sessao import Retornos, Sessao
from utilitarios.rede import validar_endereco, validar_porta
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)


class ErroCliente(Exception):
    """Falha ao conectar ou durante o handshake do cliente."""


class ClienteVisualizador:
    """Conecta-se a um host, recebe vídeo/áudio e participa do chat."""

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
        self.informacoes_host: dict = {}
        self._endereco = ""
        self._porta = 0
        self._parando = threading.Event()
        self._reconectando = False

    # -- Propriedades -------------------------------------------------------

    @property
    def conectado(self) -> bool:
        """``True`` enquanto existe sessão ativa com o host."""
        return self.sessao is not None and self.sessao.ativa

    # -- Conexão ------------------------------------------------------------

    def conectar(self, endereco: str, porta: int | str) -> None:
        """Valida os parâmetros, conecta e inicia a sessão.

        Raises:
            ErroCliente: se o endereço for inválido, a conexão falhar ou o
                handshake for recusado (senha incorreta, versão incompatível).
        """
        try:
            self._endereco = validar_endereco(endereco)
            self._porta = validar_porta(porta)
        except ValueError as erro:
            raise ErroCliente(str(erro)) from erro

        self._parando.clear()
        self._abrir_sessao()

    def _abrir_sessao(self) -> None:
        """Executa a conexão + handshake e inicia a sessão de recepção."""
        self._informar(f"Conectando a {self._endereco}:{self._porta}...")
        try:
            conexao = conectar(
                self._endereco, self._porta, self.configuracoes.rede.tempo_limite
            )
        except ConexaoEncerrada as erro:
            raise ErroCliente(str(erro)) from erro

        try:
            self.informacoes_host = self._executar_handshake(conexao)
        except (ConexaoEncerrada, ErroProtocolo, ErroCliente) as erro:
            conexao.fechar()
            raise ErroCliente(str(erro)) from erro

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
            transmitir_video=False,
            apelido=self.configuracoes.interface.apelido,
            retornos=retornos,
        )
        self.sessao.iniciar()

        if self.ao_conectar:
            self.ao_conectar(self.informacoes_host)
        self._informar(
            "Conectado a "
            f"{self.informacoes_host.get('apelido', self._endereco)} "
            f"({self.informacoes_host.get('resolucao', '?')} @ "
            f"{self.informacoes_host.get('fps', '?')} fps)"
        )

    def _executar_handshake(self, conexao: Conexao) -> dict:
        """Negocia versão e senha com o host; devolve as informações do host."""
        conexao.enviar(
            TipoMensagem.HANDSHAKE_PEDIDO,
            mensagem_handshake(
                self.configuracoes.interface.apelido,
                gerar_token(self.configuracoes.rede.senha),
            ),
        )
        tipo, carga = conexao.receber()
        if tipo is TipoMensagem.HANDSHAKE_RECUSADO:
            motivo = decodificar_json(carga).get("motivo", "conexão recusada")
            raise ErroCliente(f"Conexão recusada pelo host: {motivo}")
        if tipo is not TipoMensagem.HANDSHAKE_ACEITO:
            raise ErroProtocolo("Resposta inesperada durante o handshake")

        informacoes = decodificar_json(carga)
        conexao.enviar(TipoMensagem.PRONTO)
        return informacoes

    # -- Reconexão ----------------------------------------------------------

    def _ao_encerrar_sessao(self, motivo: str) -> None:
        """Trata o fim da sessão, tentando reconectar quando apropriado."""
        self.sessao = None
        if self.retornos.ao_encerrar:
            self.retornos.ao_encerrar(motivo)
        if self._parando.is_set() or self._reconectando:
            return
        if self.configuracoes.rede.tentativas_reconexao > 0:
            threading.Thread(
                target=self._tentar_reconectar, name="reconexao", daemon=True
            ).start()

    def _tentar_reconectar(self) -> None:
        """Tenta restabelecer a sessão algumas vezes antes de desistir."""
        self._reconectando = True
        rede = self.configuracoes.rede
        try:
            for tentativa in range(1, rede.tentativas_reconexao + 1):
                if self._parando.is_set():
                    return
                self._informar(
                    f"Tentando reconectar ({tentativa}/{rede.tentativas_reconexao})..."
                )
                self._parando.wait(rede.intervalo_reconexao)
                if self._parando.is_set():
                    return
                try:
                    self._abrir_sessao()
                    return
                except ErroCliente as erro:
                    _registrador.warning("Reconexão falhou: %s", erro)
            self._informar("Não foi possível reconectar ao host.")
        finally:
            self._reconectando = False

    # -- Encerramento -------------------------------------------------------

    def desconectar(self, motivo: str = "Desconectado pelo espectador") -> None:
        """Encerra a sessão e desativa a reconexão automática."""
        self._parando.set()
        if self.sessao is not None:
            self.sessao.encerrar(motivo)
            self.sessao = None
        self._informar("Desconectado")

    # -- Auxiliares ---------------------------------------------------------

    def _informar(self, mensagem: str) -> None:
        """Envia uma mensagem de status para a interface e para o log."""
        _registrador.info(mensagem)
        if self.ao_status:
            self.ao_status(mensagem)
