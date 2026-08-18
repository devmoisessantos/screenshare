"""Funções auxiliares de rede: descoberta de endereços, validações e diagnóstico.

Este módulo concentra o conhecimento sobre "por que a conexão não funciona",
que é a dúvida mais comum ao usar o aplicativo. Ele sabe:

* listar **todos** os endereços IPv4 da máquina, classificando-os (rede local,
  VPN, adaptador virtual), porque publicar o endereço errado é a causa número
  um de falha de conexão;
* testar se uma porta remota está realmente alcançável e traduzir o resultado
  em uma explicação acionável em português;
* verificar e criar a regra de firewall do Windows para a porta usada.
"""

from __future__ import annotations

import ipaddress
import socket
import subprocess
import sys
from dataclasses import dataclass

from utilitarios.registro import obter_registrador

_registrador = obter_registrador(__name__)

NOME_REGRA_FIREWALL = "ScreenShare"

# Prefixos de endereço típicos de adaptadores virtuais e VPNs. Endereços
# nessas faixas quase nunca são alcançáveis pelo espectador em uma rede local.
_PREFIXOS_VPN = ("100.64.", "100.65.", "100.7", "100.8", "100.9", "100.1")
_PREFIXOS_VIRTUAIS = ("172.17.", "172.18.", "172.19.", "172.20.", "192.168.56.")


@dataclass
class EnderecoLocal:
    """Um endereço IPv4 da máquina, já classificado para exibição."""

    ip: str
    categoria: str  # "local", "vpn", "virtual" ou "loopback"
    descricao: str

    @property
    def recomendado(self) -> bool:
        """``True`` para endereços de rede local, os mais indicados."""
        return self.categoria == "local"

    def __str__(self) -> str:
        return f"{self.ip} - {self.descricao}"


def _classificar(ip: str) -> tuple[str, str]:
    """Classifica um IPv4 em categoria e descrição legível."""
    if ip.startswith("127."):
        return "loopback", "somente esta máquina (testes locais)"
    # 169.254.x.x (APIPA) e o endereço que o sistema atribui a si mesmo quando
    # nao encontra um servidor DHCP: significa "sem rede", nunca e alcancavel.
    if ip.startswith("169.254."):
        return "virtual", "sem rede (169.254) - verifique o cabo/Wi-Fi"
    if ip.startswith(_PREFIXOS_VPN):
        return "vpn", "VPN (Tailscale/ZeroTier) - use pela internet"
    if ip.startswith(_PREFIXOS_VIRTUAIS):
        return "virtual", "adaptador virtual (Docker/VirtualBox) - evite"
    try:
        endereco = ipaddress.ip_address(ip)
    except ValueError:  # pragma: no cover - entrada inesperada
        return "virtual", "endereço desconhecido"
    if endereco.is_private:
        return "local", "rede local (recomendado)"
    return "local", "endereço público"


def listar_ips_locais() -> list[EnderecoLocal]:
    """Lista todos os endereços IPv4 da máquina, os recomendados primeiro.

    Publicar o endereço errado (de uma VPN ou de um adaptador virtual do
    Docker/VirtualBox) faz o espectador receber "timed out", porque o pacote
    nunca chega ao host. Mostrar todos os endereços permite que o usuário
    escolha o correto.
    """
    encontrados: dict[str, None] = {}

    # Endereço usado para sair da máquina (consulta a tabela de roteamento).
    preferido = obter_ip_local()
    if preferido:
        encontrados[preferido] = None

    # Todos os endereços associados ao nome da máquina.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            encontrados[info[4][0]] = None
    except OSError as erro:  # pragma: no cover - depende do sistema
        _registrador.debug("Falha ao resolver o nome da máquina: %s", erro)

    enderecos = [
        EnderecoLocal(ip, *_classificar(ip)) for ip in encontrados if ip
    ]
    if not any(endereco.ip.startswith("127.") for endereco in enderecos):
        enderecos.append(EnderecoLocal("127.0.0.1", *_classificar("127.0.0.1")))

    ordem = {"local": 0, "vpn": 1, "virtual": 2, "loopback": 3}
    enderecos.sort(key=lambda item: (ordem.get(item.categoria, 9), item.ip))
    return enderecos


def obter_ip_local() -> str:
    """Descobre o IP local usado para sair da máquina.

    Não envia tráfego: apenas consulta a tabela de roteamento por meio de um
    socket UDP não conectado.
    """
    soquete = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        soquete.connect(("8.8.8.8", 80))
        return soquete.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        soquete.close()


def ip_local_recomendado() -> str:
    """Devolve o melhor endereço para publicar ao espectador."""
    enderecos = listar_ips_locais()
    for endereco in enderecos:
        if endereco.recomendado:
            return endereco.ip
    return enderecos[0].ip if enderecos else "127.0.0.1"


def porta_disponivel(porta: int, endereco: str = "0.0.0.0") -> bool:
    """Informa se a porta TCP está livre para escuta."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soquete:
        soquete.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            soquete.bind((endereco, porta))
        except OSError:
            return False
    return True


def validar_porta(valor: str | int) -> int:
    """Valida e converte um número de porta.

    Raises:
        ValueError: se a porta não estiver entre 1 e 65535.
    """
    try:
        porta = int(valor)
    except (TypeError, ValueError) as erro:
        raise ValueError("A porta deve ser um número inteiro") from erro
    if not 1 <= porta <= 65535:
        raise ValueError("A porta deve estar entre 1 e 65535")
    return porta


def validar_endereco(valor: str) -> str:
    """Valida um endereço IP ou nome de host.

    Raises:
        ValueError: se o endereço estiver vazio ou não puder ser resolvido.
    """
    endereco = (valor or "").strip()
    if not endereco:
        raise ValueError("Informe o endereço IP do servidor")
    try:
        ipaddress.ip_address(endereco)
        return endereco
    except ValueError:
        pass
    try:
        socket.getaddrinfo(endereco, None)
    except OSError as erro:
        raise ValueError(f"Endereço inválido ou não resolvido: {endereco}") from erro
    return endereco


def separar_endereco_porta(valor: str, porta_padrao: int) -> tuple[str, int]:
    """Separa uma entrada no formato ``ip`` ou ``ip:porta``.

    Aceita também o formato com espaços ao redor, comum ao colar o endereço.
    """
    texto = (valor or "").strip()
    if texto.count(":") == 1:
        ip, _, porta = texto.partition(":")
        porta = porta.strip()
        if porta.isdigit():
            return ip.strip(), validar_porta(porta)
        return ip.strip(), porta_padrao
    return texto, porta_padrao


def formatar_taxa(bytes_por_segundo: float) -> str:
    """Formata uma taxa de transferência em unidade legível."""
    bits = bytes_por_segundo * 8
    if bits >= 1_000_000:
        return f"{bits / 1_000_000:.1f} Mbps"
    if bits >= 1_000:
        return f"{bits / 1_000:.0f} kbps"
    return f"{bits:.0f} bps"


# ---------------------------------------------------------------------------
# Diagnóstico de conectividade
# ---------------------------------------------------------------------------


@dataclass
class ResultadoDiagnostico:
    """Resultado de um teste de alcance a um host e porta."""

    alcancavel: bool
    situacao: str  # "aberta", "recusada", "tempo_esgotado" ou "erro"
    mensagem: str
    sugestao: str

    @property
    def texto_completo(self) -> str:
        """Mensagem e sugestão combinadas, prontas para exibição."""
        if self.sugestao:
            return f"{self.mensagem}\n\n{self.sugestao}"
        return self.mensagem


def testar_alcance(ip: str, porta: int, tempo_limite: float = 5.0) -> ResultadoDiagnostico:
    """Tenta abrir uma conexão TCP e traduz o resultado em orientação.

    Distinguir os erros é essencial: "recusada" significa que a máquina foi
    encontrada mas nada está escutando na porta (o host não iniciou o
    compartilhamento), enquanto "tempo esgotado" significa que o pacote foi
    bloqueado ou o endereço está errado - problemas totalmente diferentes.
    """
    soquete = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soquete.settimeout(tempo_limite)
    try:
        soquete.connect((ip, porta))
        return ResultadoDiagnostico(
            alcancavel=True,
            situacao="aberta",
            mensagem=f"A porta {porta} de {ip} está acessível.",
            sugestao="",
        )
    except (TimeoutError, socket.timeout):
        return ResultadoDiagnostico(
            alcancavel=False,
            situacao="tempo_esgotado",
            mensagem=(
                f"Tempo esgotado ao tentar alcançar {ip}:{porta}. "
                "A máquina não respondeu, ou seja, o pacote foi bloqueado "
                "antes de chegar ao aplicativo."
            ),
            sugestao=(
                "Causas mais comuns, em ordem:\n"
                "1. Firewall do Windows bloqueando a porta no host. No host, "
                'execute como administrador o arquivo '
                '"build/liberar_firewall_windows.bat".\n'
                "2. Endereço IP errado. No host, confira a lista de endereços "
                'em "Diagnóstico" e use o marcado como rede local.\n'
                "3. As duas máquinas estão em redes diferentes (por exemplo uma "
                "no Wi-Fi de visitantes). Pela internet, use Tailscale ou ZeroTier.\n"
                "4. O antivírus está bloqueando o aplicativo."
            ),
        )
    except ConnectionRefusedError:
        return ResultadoDiagnostico(
            alcancavel=False,
            situacao="recusada",
            mensagem=(
                f"A máquina {ip} respondeu, mas recusou a conexão na porta {porta}: "
                "nada está escutando nessa porta."
            ),
            sugestao=(
                "A rede está boa - falta iniciar a transmissão. Verifique se:\n"
                '1. No host, o botão "Iniciar compartilhamento" foi acionado.\n'
                "2. A porta informada aqui é a mesma exibida no host."
            ),
        )
    except OSError as erro:
        return ResultadoDiagnostico(
            alcancavel=False,
            situacao="erro",
            mensagem=f"Falha ao alcançar {ip}:{porta} ({erro}).",
            sugestao=(
                "Confira se o endereço está digitado corretamente e se esta "
                "máquina está conectada à rede."
            ),
        )
    finally:
        soquete.close()


# ---------------------------------------------------------------------------
# Firewall do Windows
# ---------------------------------------------------------------------------


def _executar_oculto(comando: list[str]) -> subprocess.CompletedProcess:
    """Executa um comando sem abrir janela de console no Windows."""
    parametros: dict = {"capture_output": True, "text": True, "timeout": 20}
    if sys.platform.startswith("win"):  # pragma: no cover - específico do Windows
        parametros["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(comando, check=False, **parametros)


def firewall_liberado(porta: int) -> bool | None:
    """Informa se existe regra de firewall do Windows para a porta.

    Returns:
        ``True`` se a regra existe, ``False`` se não existe e ``None`` quando
        não é possível determinar (sistema diferente de Windows ou erro).
    """
    if not sys.platform.startswith("win"):
        return None
    try:  # pragma: no cover - específico do Windows
        resultado = _executar_oculto(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "show",
                "rule",
                f"name={NOME_REGRA_FIREWALL} {porta}",
            ]
        )
        return resultado.returncode == 0
    except (OSError, subprocess.SubprocessError) as erro:  # pragma: no cover
        _registrador.debug("Não foi possível consultar o firewall: %s", erro)
        return None


def liberar_firewall(porta: int) -> tuple[bool, str]:
    """Tenta criar a regra de entrada do firewall do Windows para a porta.

    A criação exige privilégios de administrador; quando eles não existem, a
    função devolve uma orientação em vez de falhar silenciosamente.

    Returns:
        Uma tupla ``(sucesso, mensagem)``.
    """
    if not sys.platform.startswith("win"):
        return False, (
            "Liberação automática disponível apenas no Windows. No Linux, use:\n"
            f"sudo ufw allow {porta}/tcp"
        )
    try:  # pragma: no cover - específico do Windows
        resultado = _executar_oculto(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                f"name={NOME_REGRA_FIREWALL} {porta}",
                "dir=in",
                "action=allow",
                "protocol=TCP",
                f"localport={porta}",
            ]
        )
        if resultado.returncode == 0:
            _registrador.info("Regra de firewall criada para a porta %s", porta)
            return True, f"Porta {porta} liberada no firewall do Windows."
        return False, (
            "Não foi possível criar a regra automaticamente (é necessário "
            "executar o aplicativo como administrador).\n\n"
            'Alternativa: clique com o botão direito em "build/'
            'liberar_firewall_windows.bat" e escolha "Executar como '
            'administrador".'
        )
    except (OSError, subprocess.SubprocessError) as erro:  # pragma: no cover
        return False, f"Falha ao configurar o firewall: {erro}"
