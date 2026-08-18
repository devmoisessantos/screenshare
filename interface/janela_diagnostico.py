"""Janela de diagnóstico de rede.

Concentra em um só lugar as informações necessárias para resolver os erros de
conexão mais comuns:

* **Meus endereços** - lista todos os IPv4 da máquina, destacando o de rede
  local (o correto para informar ao espectador) e marcando os de VPN e de
  adaptadores virtuais, que costumam ser publicados por engano.
* **Firewall** - mostra se a porta está liberada no Windows e permite criar a
  regra com um clique.
* **Testar conexão** - tenta alcançar um host e explica o resultado, separando
  "tempo esgotado" (bloqueio/endereço errado) de "recusada" (host não está
  compartilhando).
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from configuracao.configuracoes import NOME_APLICACAO, Configuracoes
from interface.tema import FONTE_MONO, aplicar_tema
from utilitarios.recursos import aplicar_icone
from utilitarios.rede import (
    firewall_liberado,
    liberar_firewall,
    listar_ips_locais,
    porta_disponivel,
    separar_endereco_porta,
    testar_alcance,
)
from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)


class JanelaDiagnostico(tk.Toplevel):
    """Diálogo de diagnóstico de rede, usado pelo host e pelo espectador."""

    def __init__(
        self,
        mestre: tk.Misc,
        configuracoes: Configuracoes,
        endereco_sugerido: str = "",
    ) -> None:
        super().__init__(mestre)
        self.configuracoes = configuracoes
        self.title(f"{NOME_APLICACAO} - Diagnóstico de rede")
        self.geometry("640x680")
        self.minsize(600, 620)

        self._paleta = aplicar_tema(self, configuracoes.interface.tema)
        aplicar_icone(self)
        self._endereco_sugerido = endereco_sugerido

        self._construir_interface()
        self._carregar_enderecos()
        self._atualizar_firewall()
        self.bind("<Control-q>", lambda _e: self.destroy())
        self.transient(mestre)

    # -- Construção da interface -------------------------------------------

    def _construir_interface(self) -> None:
        """Monta as três seções do diagnóstico."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        cabecalho = ttk.Frame(self, padding=(16, 14, 16, 4))
        cabecalho.grid(row=0, column=0, sticky="ew")
        ttk.Label(cabecalho, text="Diagnóstico de rede", style="Titulo.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            cabecalho,
            text="Use esta tela quando a conexão falhar com tempo esgotado.",
            style="Secundario.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        self._construir_secao_enderecos()
        self._construir_secao_firewall()
        self._construir_secao_teste()

    def _construir_secao_enderecos(self) -> None:
        """Seção com os endereços IPv4 da máquina."""
        secao = ttk.Labelframe(self, text=" Meus endereços ", padding=12)
        secao.grid(row=1, column=0, sticky="ew", padx=16, pady=6)
        secao.columnconfigure(0, weight=1)

        ttk.Label(
            secao,
            text=(
                "Informe ao espectador o endereço marcado como rede local. "
                "Endereços de VPN só funcionam se os dois lados usarem a mesma VPN."
            ),
            style="Secundario.TLabel",
            wraplength=560,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self._quadro_enderecos = ttk.Frame(secao)
        self._quadro_enderecos.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._quadro_enderecos.columnconfigure(0, weight=1)

        ttk.Button(secao, text="Atualizar lista", command=self._carregar_enderecos).grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )

    def _construir_secao_firewall(self) -> None:
        """Seção com o estado do firewall e da porta."""
        secao = ttk.Labelframe(self, text=" Firewall e porta ", padding=12)
        secao.grid(row=2, column=0, sticky="ew", padx=16, pady=6)
        secao.columnconfigure(0, weight=1)

        self._var_firewall = tk.StringVar(value="Verificando...")
        ttk.Label(
            secao,
            textvariable=self._var_firewall,
            style="Secundario.TLabel",
            wraplength=560,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        self._botao_liberar = ttk.Button(
            secao,
            text=f"Liberar porta {self.configuracoes.rede.porta} no firewall",
            style="Destaque.TButton",
            command=self._liberar_firewall,
        )
        self._botao_liberar.grid(row=1, column=0, sticky="w", pady=(10, 0))

        ttk.Button(secao, text="Verificar novamente", command=self._atualizar_firewall).grid(
            row=1, column=1, sticky="e", pady=(10, 0)
        )

    def _construir_secao_teste(self) -> None:
        """Seção de teste de alcance de um host remoto."""
        secao = ttk.Labelframe(self, text=" Testar conexão com um host ", padding=12)
        secao.grid(row=3, column=0, sticky="nsew", padx=16, pady=(6, 14))
        secao.columnconfigure(1, weight=1)
        secao.rowconfigure(2, weight=1)

        endereco, porta = separar_endereco_porta(
            self._endereco_sugerido, self.configuracoes.rede.porta
        )
        self._var_ip = tk.StringVar(value=endereco)
        self._var_porta = tk.StringVar(value=str(porta))

        ttk.Label(secao, text="IP do host").grid(row=0, column=0, sticky="w")
        ttk.Entry(secao, textvariable=self._var_ip).grid(
            row=0, column=1, sticky="ew", padx=(8, 8)
        )
        ttk.Label(secao, text="Porta").grid(row=0, column=2, sticky="w")
        ttk.Entry(secao, textvariable=self._var_porta, width=8).grid(
            row=0, column=3, sticky="w", padx=(8, 0)
        )

        self._botao_testar = ttk.Button(
            secao, text="Testar", style="Destaque.TButton", command=self._testar
        )
        self._botao_testar.grid(row=1, column=0, sticky="w", pady=(10, 8))

        self._texto_resultado = tk.Text(
            secao,
            height=9,
            wrap="word",
            background=self._paleta["fundo_painel"],
            foreground=self._paleta["texto_secundario"],
            insertbackground=self._paleta["texto"],
            font=FONTE_MONO,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            state="disabled",
        )
        self._texto_resultado.grid(
            row=2, column=0, columnspan=4, sticky="nsew", pady=(0, 0)
        )
        self._texto_resultado.tag_configure("sucesso", foreground=self._paleta["sucesso"])
        self._texto_resultado.tag_configure("erro", foreground=self._paleta["erro"])
        self._escrever(
            "Digite o endereço informado pelo host e clique em Testar.", "normal"
        )

    # -- Endereços ----------------------------------------------------------

    def _carregar_enderecos(self) -> None:
        """Preenche a lista de endereços locais da máquina."""
        for filho in self._quadro_enderecos.winfo_children():
            filho.destroy()

        for linha, endereco in enumerate(listar_ips_locais()):
            cor = (
                self._paleta["sucesso"]
                if endereco.recomendado
                else self._paleta["texto_secundario"]
            )
            texto = f"{endereco.ip}:{self.configuracoes.rede.porta}"
            rotulo = tk.Label(
                self._quadro_enderecos,
                text=f"{texto}   {endereco.descricao}",
                background=self._paleta["fundo"],
                foreground=cor,
                font=FONTE_MONO,
                anchor="w",
            )
            rotulo.grid(row=linha, column=0, sticky="ew", pady=2)
            ttk.Button(
                self._quadro_enderecos,
                text="Copiar",
                width=8,
                command=lambda valor=texto: self._copiar(valor),
            ).grid(row=linha, column=1, padx=(8, 0), pady=2)

    def _copiar(self, valor: str) -> None:
        """Copia um endereço para a área de transferência."""
        self.clipboard_clear()
        self.clipboard_append(valor)
        self._escrever(f"Endereço {valor} copiado para a área de transferência.", "normal")

    # -- Firewall -----------------------------------------------------------

    def _atualizar_firewall(self) -> None:
        """Consulta o estado da porta e do firewall."""
        porta = self.configuracoes.rede.porta
        livre = porta_disponivel(porta)
        estado_porta = (
            f"A porta {porta} está livre nesta máquina."
            if livre
            else f"A porta {porta} já está em uso (o compartilhamento pode estar ativo)."
        )

        liberado = firewall_liberado(porta)
        if liberado is True:
            estado_firewall = "Regra de firewall do Windows encontrada para esta porta."
            self._botao_liberar.configure(state="disabled")
        elif liberado is False:
            estado_firewall = (
                "Não existe regra de firewall para esta porta. Esta é a causa mais "
                'comum do erro "tempo esgotado" no espectador.'
            )
            self._botao_liberar.configure(state="normal")
        else:
            estado_firewall = (
                "Verificação automática de firewall disponível apenas no Windows. "
                f"No Linux, libere a porta com: sudo ufw allow {porta}/tcp"
            )
            self._botao_liberar.configure(state="normal")

        self._var_firewall.set(f"{estado_porta}\n{estado_firewall}")

    def _liberar_firewall(self) -> None:
        """Tenta criar a regra de firewall e informa o resultado."""
        sucesso, mensagem = liberar_firewall(self.configuracoes.rede.porta)
        self._escrever(mensagem, "sucesso" if sucesso else "erro")
        self._atualizar_firewall()

    # -- Teste de alcance ---------------------------------------------------

    def _testar(self) -> None:
        """Dispara o teste de alcance em uma thread separada."""
        ip = self._var_ip.get().strip()
        if not ip:
            self._escrever("Informe o IP do host antes de testar.", "erro")
            return
        try:
            porta = int(self._var_porta.get())
        except ValueError:
            self._escrever("Porta inválida.", "erro")
            return

        self._botao_testar.configure(state="disabled", text="Testando...")
        self._escrever(f"Testando {ip}:{porta}...", "normal")
        threading.Thread(
            target=self._testar_em_segundo_plano,
            args=(ip, porta),
            name="diagnostico-rede",
            daemon=True,
        ).start()

    def _testar_em_segundo_plano(self, ip: str, porta: int) -> None:
        """Executa o teste fora da thread da interface."""
        resultado = testar_alcance(ip, porta)
        try:
            self.after(
                0,
                lambda: self._concluir_teste(
                    resultado.texto_completo, resultado.alcancavel
                ),
            )
        except tk.TclError:  # pragma: no cover - janela fechada durante o teste
            _registrador.debug("Janela de diagnóstico fechada antes do resultado")

    def _concluir_teste(self, texto: str, sucesso: bool) -> None:
        """Mostra o resultado e reabilita o botão."""
        self._botao_testar.configure(state="normal", text="Testar")
        self._escrever(texto, "sucesso" if sucesso else "erro")

    # -- Auxiliares ---------------------------------------------------------

    def _escrever(self, texto: str, marca: str) -> None:
        """Substitui o conteúdo da área de resultado."""
        self._texto_resultado.configure(state="normal")
        self._texto_resultado.delete("1.0", "end")
        etiquetas = (marca,) if marca in ("sucesso", "erro") else ()
        self._texto_resultado.insert("1.0", texto, etiquetas)
        self._texto_resultado.configure(state="disabled")
