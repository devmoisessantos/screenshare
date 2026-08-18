# Arquitetura do ScreenShare 1.0

Documento de referência técnica para manutenção e evolução do projeto.

## 1. Visão geral

O ScreenShare é uma aplicação desktop cliente-servidor de compartilhamento de tela ponto a ponto. Não existe servidor central: o próprio usuário que compartilha a tela hospeda o serviço TCP, e o espectador conecta diretamente a ele.

```
+--------------------------------------------------+
|                    interface/                    |  Camada de apresentação (Tkinter)
| inicial | servidor | cliente | diagnostico       |
+--------------------------------------------------+
                        | callbacks / PonteInterface
+--------------------------------------------------+
|                   aplicacao/                     |  Casos de uso
|      servidor.py            cliente.py           |
+--------------------------------------------------+
                        |
+--------------------------------------------------+
|                     nucleo/                      |  Comunicação
|   protocolo.py    conexao.py    sessao.py        |
+--------------------------------------------------+
                        |
+---------------------------+ +--------------------+
|          midia/           | |   utilitarios/     |  Infraestrutura
| captura_tela  compressao  | | registro  rede     |
| captura_audio  previa     | | recursos           |
+---------------------------+ +--------------------+
                        |
+--------------------------------------------------+
|                 configuracao/                    |  Configuração e temas
+--------------------------------------------------+
```

Regras de dependência (respeitadas por todo o código):

1. `interface/` pode depender de tudo, mas nunca manipula sockets diretamente.
2. `aplicacao/` depende de `nucleo/`, `midia/`, `configuracao/` e `utilitarios/`.
3. `nucleo/` não conhece a interface: comunica-se por callbacks (`Retornos`).
4. `midia/` e `utilitarios/` não dependem de nenhuma camada superior.
5. `configuracao/` não depende de nada além da biblioteca padrão.

## 2. Modelo de threads

Cada participante da sessão executa até cinco threads além da thread principal (interface):

| Thread | Local | Responsabilidade |
| --- | --- | --- |
| `recepcao` | ambos | lê quadros do socket e despacha por tipo de mensagem |
| `ping` | ambos | envia `PING` periódico e calcula a latência com o `PONG` |
| `estatisticas` | ambos | agrega FPS, taxas e descartes a cada segundo |
| `envio-video` | apenas host | captura a tela, comprime em JPEG e envia |
| `envio-audio` | ambos | lê o microfone e envia blocos PCM |

A thread de reprodução de áudio é criada pelo `ReprodutorAudio` (fila com descarte dos blocos antigos, para evitar acúmulo de latência).

### Segurança entre threads

- `Conexao.enviar` é protegido por um `threading.Lock`, garantindo que quadros de vídeo, áudio e chat nunca se intercalem no socket.
- Widgets Tkinter só são tocados pela thread principal. As threads de rede publicam eventos em uma fila e a classe `PonteInterface` a esvazia via `after(30 ms)`.
- O `VisualizadorVideo` guarda apenas o quadro mais recente (slot único com lock), então a interface nunca renderiza quadros atrasados.

## 3. Protocolo

Formato do quadro:

```
+----------+--------+-------------+-----------------+
| 2 bytes  | 1 byte |   4 bytes   |    N bytes      |
|  "SS"    |  tipo  |  tamanho N  |   carga útil    |
+----------+--------+-------------+-----------------+
        struct "!2sBI" -> cabeçalho de 7 bytes
```

O prefixo mágico `SS` permite detectar imediatamente dessincronização ou conexões de clientes inválidos, algo que um cabeçalho apenas com o tamanho (4 bytes) não permite. O campo `tipo` de 1 byte evita ter de decodificar JSON para saber o que é a carga útil — essencial para o desempenho do fluxo de vídeo.

Tipos de mensagem em `nucleo/protocolo.py` (`TipoMensagem`):

| Faixa | Uso |
| --- | --- |
| 1–9 | negociação (`HANDSHAKE_PEDIDO`, `HANDSHAKE_ACEITO`, `HANDSHAKE_RECUSADO`, `PRONTO`) |
| 10–19 | mídia (`VIDEO`, `AUDIO`) |
| 20–29 | interação (`CHAT`) |
| 30–39 | manutenção (`PING`, `PONG`) |
| 40–49 | sincronização de estado (`ESTADO`) |
| 50+ | encerramento (`ENCERRAR`) |

A reserva de faixas permite adicionar mensagens futuras sem quebrar a compatibilidade da versão do protocolo (`VERSAO_PROTOCOLO`), que é validada no handshake.

### Handshake

```
Espectador                                Host
    |  HANDSHAKE_PEDIDO {versao, apelido, token}  |
    |-------------------------------------------->|
    |                                             |  valida versão e token
    |  HANDSHAKE_ACEITO {resolucao, fps, audio}   |
    |<--------------------------------------------|  (ou HANDSHAKE_RECUSADO {motivo})
    |  PRONTO                                     |
    |-------------------------------------------->|
    |  VIDEO / AUDIO ... (fluxo contínuo)         |
    |<========================================>   |  CHAT / PING / ESTADO nos dois sentidos
```

O token é `sha256(senha)`; senha vazia gera token vazio. A comparação usa `hmac.compare_digest`, resistente a ataques de tempo. O handshake tem tempo limite de 20 segundos (`TEMPO_LIMITE_HANDSHAKE`).

## 4. Pipeline de vídeo

```
mss.grab (BGRA) -> descarta alfa (BGR) -> redimensiona (cv2) ->
  cv2.imencode JPEG (qualidade dinâmica) -> Conexao.enviar(VIDEO)
       ...rede...
  cv2.imdecode -> BGR->RGB -> PIL.Image -> ImageTk (thread da interface)
```

O `ControladorQualidade` (em `midia/compressao.py`) ajusta o pipeline conforme a latência medida:

| Latência | Ação |
| --- | --- |
| < 80 ms | aumenta gradualmente a qualidade JPEG (até o máximo configurado) |
| 80–200 ms | mantém a qualidade |
| > 200 ms (`LIMITE_LATENCIA_MS`) | reduz a qualidade JPEG |
| > 2× o limite | além de reduzir, descarta quadros (`deve_descartar_quadro`) |

Descartar quadros é preferível a enfileirá-los: em transmissão ao vivo, o quadro atrasado já perdeu utilidade.

## 5. Pipeline de áudio

Captura: 16 bits assinados, mono, 44.100 Hz, blocos de 1.024 amostras (~23 ms). Cada bloco vai direto para a rede como `AUDIO`, sem compressão — em rede local, o custo (~700 kbps) é aceitável e elimina a latência de um codec.

### Dois motores atrás de uma única interface

`midia/captura_audio.py` não depende de uma biblioteca específica. O módulo detecta o motor em tempo de execução (`_detectar_motor()`) na ordem `sounddevice` → `pyaudio` → nenhum, e expõe `MOTOR_AUDIO`, `AUDIO_DISPONIVEL`, `MOTIVO_AUDIO_INDISPONIVEL` e `descrever_motor_audio()` para a interface.

Cada motor é encapsulado em um adaptador privado que implementa a mesma interface mínima (`abrir`/`ler`/`fechar` na entrada, `abrir`/`escrever`/`fechar` na saída):

| Papel | sounddevice | PyAudio |
| --- | --- | --- |
| Entrada | `_EntradaSounddevice` | `_EntradaPyAudio` |
| Saída | `_SaidaSounddevice` | `_SaidaPyAudio` |

As classes públicas `CapturadorAudio` e `ReprodutorAudio` conhecem apenas essa interface, escolhida pelas fábricas `_criar_entrada()` / `_criar_saida()`. Acrescentar um terceiro motor exige apenas dois adaptadores novos e uma linha em cada fábrica — nenhuma outra camada muda.

O `sounddevice` é o preferencial porque distribui rodas prontas para o Python 3.13/3.14, enquanto o PyAudio ainda exige compilação nessas versões. O PyAudio permanece como alternativa automática para ambientes já configurados.

Se nenhum motor carregar (biblioteca ausente ou PortAudio não encontrado), `AUDIO_DISPONIVEL` fica `False`, o aplicativo registra um aviso e continua funcionando com vídeo e chat, com a interface exibindo o motivo exato.

### Mudo e surdo

Os dois controles são independentes e resolvidos em camadas diferentes:

- `Sessao.alternar_microfone()` interrompe o envio e **notifica o outro lado** com uma mensagem `ESTADO`, para que o rótulo remoto reflita o estado.
- `Sessao.alternar_som()` é puramente local: `_despachar` simplesmente deixa de escrever no reprodutor enquanto `som_ativo` for `False`. Nada trafega na rede, o que torna o religamento instantâneo.

Diferente da especificação original (áudio somente do host), o áudio é **bidirecional** — sem isso, uma conversa de suporte remoto exigiria uma segunda ferramenta de voz.

## 5.1. Prévia local da transmissão

`midia/previa.py` (`PreVisualizadorTela`) roda uma thread própria de captura, independente da `Sessao`. Essa separação é deliberada: o host precisa ver o que está transmitindo **desde o instante em que inicia o compartilhamento**, antes de qualquer espectador conectar — e a `Sessao` só existe depois do handshake.

Para não competir com a transmissão, a prévia usa parâmetros reduzidos: 10 fps (`ConfiguracaoVideo.fps_previa`) e 640 px de largura (`LARGURA_PREVIA`), com a altura derivada da proporção real do monitor por `_calcular_dimensoes()`. Os quadros são entregues por callback e renderizados pela janela do host no mesmo `VisualizadorVideo` usado pelo espectador.

## 5.2. Diagnóstico de rede

`utilitarios/rede.py` concentra a lógica que responde à falha mais comum do projeto, o tempo esgotado:

| Função | Responsabilidade |
| --- | --- |
| `listar_ips_locais()` | enumera os endereços da máquina como `EnderecoLocal` |
| `_classificar()` | separa rede local, VPN, adaptador virtual, `127.0.0.1` e `169.254.x.x` |
| `ip_local_recomendado()` | escolhe o endereço que o espectador realmente alcança |
| `testar_alcance()` | tenta a conexão TCP e traduz o resultado em `ResultadoDiagnostico` |
| `firewall_liberado()` / `liberar_firewall()` | consultam e criam a regra `netsh` no Windows |

A classificação existe porque máquinas com VPN, Docker, WSL ou VirtualBox têm vários endereços, e sugerir o errado produz exatamente o tempo esgotado relatado. `169.254.x.x` (APIPA) é tratado como endereço inválido: indica ausência de DHCP.

`nucleo/conexao.py` traduz cada exceção de socket em uma mensagem acionável distinta (tempo esgotado → firewall/IP, `ConnectionRefusedError` → host não está compartilhando, `gaierror` → endereço inválido), em vez de um erro genérico. `interface/janela_diagnostico.py` expõe tudo isso em uma janela, e a janela do espectador oferece abri-la automaticamente após uma falha.

## 6. Ciclo de vida da sessão

- `ServidorCompartilhamento` abre o socket de escuta, aceita conexões com tempo limite de 1 segundo (para permitir parada limpa), valida o handshake e cria a `Sessao`. Um segundo espectador é recusado com `HANDSHAKE_RECUSADO`; após a desconexão, a escuta é reaberta automaticamente.
- `ClienteVisualizador` valida o endereço, conecta, faz o handshake e, em caso de queda, tenta reconectar segundo `tentativas_reconexao` e `intervalo_reconexao`.
- `Sessao.encerrar` é idempotente: fecha a conexão, sinaliza as threads pelo evento de parada e libera os recursos de mídia.

## 7. Configuração e persistência

`configuracao/configuracoes.py` define dataclasses (`ConfiguracaoVideo`, `ConfiguracaoAudio`, `ConfiguracaoRede`, `ConfiguracaoInterface`) agregadas em `Configuracoes`, com `salvar()`/`carregar()` em JSON. Um arquivo corrompido não impede a inicialização: os padrões são restaurados e o erro é registrado.

Diretórios por sistema operacional (`diretorio_dados()`): `%APPDATA%\ScreenShare` no Windows, `~/.config/screenshare` no Linux e `~/Library/Application Support/ScreenShare` no macOS.

## 8. Registro de log

`utilitarios/registro.py` configura um `RotatingFileHandler` (arquivo `screenshare.log`) e saída no console. O nível DEBUG é ativado por `--depurar`. Todos os módulos usam `obter_registrador(__name__)`, o que mantém a origem da mensagem rastreável.

## 9. Estratégia de testes

74 testes automatizados, todos executáveis sem monitor, placa de som ou rede externa:

- **Unitários** — protocolo (empacotamento, tokens, JSON), mídia (JPEG, redimensionamento, qualidade adaptativa), configuração (padrões, persistência, arquivos corrompidos, validações), áudio (detecção de motor, captura, reprodução, descarte), rede (classificação de IPs, diagnóstico, firewall) e prévia local.
- **Áudio com motor simulado** — como o PortAudio pode não existir no ambiente de CI, `teste_audio.py` injeta um módulo `sounddevice` falso em `sys.modules`. Isso testa os adaptadores sem placa de som e sem depender do motor real.
- **Integração** — sobem um host e um espectador reais em `127.0.0.1`, com dublês para `Sessao._laco_video`, `_laco_audio` e `_iniciar_reproducao_audio`. Cobrem handshake, senha correta e incorreta, quadro de vídeo simulado, chat bidirecional, recusa do segundo espectador e limpeza após desconexão.

Comando: `python -m unittest discover -s testes -p "teste_*.py" -v` (execute na raiz do projeto).

## 10. Empacotamento

O PyInstaller gera um único arquivo a partir de `build/screenshare.spec`, com `recursos/` embutido e `PIL._tkinter_finder` mais os back-ends do `mss` e o motor de áudio (`sounddevice`, `_sounddevice`, `cffi`, `pyaudio`) declarados como importações ocultas — sem isso, o executável falha ao iniciar. `utilitarios/recursos.py` resolve os caminhos usando `sys._MEIPASS`, funcionando tanto no código-fonte quanto no executável.

Não há compilação cruzada: o `.exe` do Windows deve ser gerado no Windows e o binário Linux no Linux.

## 11. Pontos de extensão

| Objetivo | Onde alterar |
| --- | --- |
| Novo codec de vídeo | `midia/compressao.py` (manter a assinatura de `comprimir_jpeg`/`descomprimir_jpeg`) |
| Nova fonte de captura (janela específica) | `midia/captura_tela.py` |
| Novo tipo de mensagem | `nucleo/protocolo.py` (novo valor em `TipoMensagem`) + tratamento em `nucleo/sessao.py` |
| Múltiplos espectadores | `aplicacao/servidor.py` (lista de sessões) e o laço de envio em `nucleo/sessao.py` |
| Criptografia do canal | envolver o socket em `nucleo/conexao.py` com `ssl.wrap_socket` |
| Novo tema visual | `configuracao/configuracoes.py` (`TEMAS`) — a interface se adapta automaticamente |
