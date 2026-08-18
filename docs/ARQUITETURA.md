# Arquitetura do ScreenShare 2.0

Documento técnico de referência para manutenção, empacotamento e evolução do ScreenShare 2.0.

## 1. Visão geral

O ScreenShare é uma aplicação desktop Tkinter para chamadas de voz, vídeo, compartilhamento de tela e chat. O caminho principal da versão 2.0 usa WebRTC em topologia de malha: cada pessoa abre uma conexão direta com cada outra pessoa da sala. O limite é de seis participantes (`LIMITE_PARTICIPANTES`), pois a quantidade de conexões e a banda de subida crescem com a sala.

Há dois modos independentes:

1. **Chamada pela internet**: WebRTC, com sinalização WebSocket, ICE/STUN e TURN opcional.
2. **Rede local (avançado)**: modo TCP direto legado, mantido para máquinas que conseguem se alcançar diretamente. Ele não atravessa NAT.

O servidor de sinalização é um componente separado em `servidor_sinalizacao/`. Ele cria salas, identifica participantes e encaminha mensagens de negociação. Ele não recebe áudio, vídeo, tela nem chat depois que os pares WebRTC estão conectados.

```text
+------------------------------------------------------------------+
|                         interface/                               |
| janela_inicial | janela_chamada | seletor_fonte | chat_rico      |
| painel_participantes | emojis | componentes/PonteInterface       |
+------------------------------------------------------------------+
                              | callbacks agendados no Tk
+------------------------------------------------------------------+
|                           nucleo/                                |
| chamada.py (orquestrador) | sinalizacao.py | par_webrtc.py       |
| convite.py (links/codigos/SDP manual)                             |
+------------------------------------------------------------------+
                         |                         |
+-------------------------------+   +------------------------------+
|            midia/             |   |       configuracao/          |
| fontes | faixas_webrtc        |   | WebRTC, TURN, gravação, UI   |
| dispositivos | gravador       |   +------------------------------+
+-------------------------------+
                              |
+------------------------------------------------------------------+
|       aiortc / av / mss / sounddevice ou PyAudio                 |
+------------------------------------------------------------------+

Modo legado em paralelo: aplicacao/ + nucleo/conexao.py +
nucleo/protocolo.py + nucleo/sessao.py (TCP direto).
```

## 2. Fluxos de sinalização e mídia

### 2.1 Entrada em sala e negociação

```text
Participante A             Servidor de sinalização             Participante B
      |                              |                                |
      |--- WebSocket: entrar -------->|                                |
      |<-- bem_vindo / participantes -|                                |
      |                              |<------- WebSocket: entrar ------|
      |<--------- entrou -------------|--------- bem_vindo ----------->|
      |                              |                                |
      |--- oferta SDP/ICE ----------->|--- oferta SDP/ICE ------------>|
      |<-- resposta SDP/ICE ----------|<-- resposta SDP/ICE -----------|
      |                              |                                |
      |================ WebRTC direto (ICE/STUN/TURN) ===============>|
```

- `ClienteSinalizacao` mantém o WebSocket, envia `entrar`, `sinal`, `sair` e `ping`, e entrega os eventos por callbacks.
- O servidor aceita `GET /ws` e limita cada sala a seis participantes. `GET /saude` fornece o estado mínimo para monitoramento de hospedagem.
- O participante que chega depois inicia a oferta, evitando ofertas simultâneas.
- `ParRemoto` transforma oferta, resposta e candidatos ICE em operações de `RTCPeerConnection`.
- STUN ajuda a descobrir candidatos de conexão. TURN é opcional e pode retransmitir tráfego se não existir rota direta. A preferência `forcar_relay` é preservada na configuração ICE como intenção do usuário.

### 2.2 Mídia e dados após a negociação

```text
Fonte local / microfone
        |
        v
FaixaTela / FaixaMicrofone  --->  MediaRelay
        |                         |        |
        |                         |        +--> prévia local / gravação
        |                         |
        |                         +--> um assinante para cada ParRemoto
        v
RTCPeerConnection  ===== WebRTC direto =====>  RTCPeerConnection remoto
                                                     |          |
                                                     v          v
                                      ConsumidorFaixaVideo  ReprodutorFaixaRemota
                                                     |          |
                                                     v          v
                                               grade Tk     saída de áudio

Canal de dados WebRTC: chat, estado de microfone, estado de compartilhamento e saída.
```

A mídia não passa pelo servidor de sinalização. `FaixaTela` captura com `mss`, adapta a imagem à resolução configurada e cria `av.VideoFrame`. `FaixaMicrofone` produz áudio PCM mono a 48 kHz em blocos de 20 ms. `ConsumidorFaixaVideo` converte os quadros recebidos para BGR antes de enviá-los à interface; `ReprodutorFaixaRemota` reamostra e reproduz o áudio remoto.

O orquestrador `Chamada` executa uma thread dedicada com um laço `asyncio`. Métodos públicos chamados pela interface usam `run_coroutine_threadsafe`, e retornos da rede são transferidos de volta para a thread Tkinter pela `PonteInterface`. Widgets Tkinter não devem ser manipulados pela thread de rede.

## 3. Camadas e módulos

| Área | Módulo | Responsabilidade |
| --- | --- | --- |
| Entrada | `principal.py` | Analisa argumentos, carrega configurações e abre a interface ou o host TCP de console. |
| Configuração | `configuracao/configuracoes.py` | Define dataclasses, valores de STUN, limite de participantes, TURN, gravação, temas e persistência JSON. |
| Convites | `nucleo/convite.py` | Gera códigos de sala, cria/interpreta links `screenshare://` e codifica/decodifica blocos manuais de SDP `SS1-`. |
| Sinalização | `nucleo/sinalizacao.py` | Cliente WebSocket `aiohttp`, reconexão, ping e callbacks de entrada, saída, sinal e erro. |
| Par WebRTC | `nucleo/par_webrtc.py` | Encapsula uma conexão com um par, canal de dados, SDP, candidatos ICE, faixas, estados e estatísticas. |
| Orquestração | `nucleo/chamada.py` | Mantém sala, participantes, pares, `MediaRelay`, compartilhamento, chat, estados, áudio e métricas. |
| Fontes | `midia/fontes.py` | Enumera área de trabalho, monitores e janelas; reconsulta a região de uma janela que se move. |
| Áudio | `midia/dispositivos.py` | Lista entradas e saídas por `sounddevice` ou PyAudio e identifica dispositivos padrão. |
| Faixas | `midia/faixas_webrtc.py` | Implementa as faixas WebRTC locais, consumo de vídeo remoto e reprodução de áudio remoto. |
| Gravação | `midia/gravador.py` | Grava MP4 por PyAV, mantém buffer circular JPEG/PCM e exporta clipes. |
| Interface inicial | `interface/janela_inicial.py` | Oferece as abas de internet, rede local avançada e ajustes de TURN/gravação. |
| Interface da chamada | `interface/janela_chamada.py` | Monta a chamada, a grade, controles, métricas, convite, tela cheia e integração de gravação. |
| Seletor de fonte | `interface/seletor_fonte.py` | Mostra telas e janelas em cartões com miniaturas capturadas em thread. |
| Participantes | `interface/painel_participantes.py` | Exibe avatar por iniciais, estado, microfone mudo e compartilhamento. |
| Chat | `interface/chat_rico.py` | Apresenta histórico, mensagens de sistema/erro, atalhos e seletor de emojis. |
| Emojis | `interface/emojis.py` | Localiza fontes do sistema e renderiza emojis como `PhotoImage` com fallback de texto. |
| Sinalização hospedável | `servidor_sinalizacao/servidor.py` | Expõe salas WebSocket por `aiohttp`, rotas `/ws` e `/saude`, e encaminha sinais entre participantes. |
| Modo legado | `aplicacao/`, `nucleo/conexao.py`, `nucleo/protocolo.py`, `nucleo/sessao.py` | Mantém compartilhamento TCP direto, protocolo binário, áudio, chat e diagnóstico local. |
| Utilitários | `utilitarios/` | Configura logs, recursos do executável e diagnósticos de rede do modo TCP. |

## 4. Convites e modos de conexão

### Código e link de sala

`Convite` normaliza códigos de seis caracteres e produz links no formato:

```text
screenshare://sala/ABC123?s=wss%3A%2F%2Fmeu-servidor%2Fws
```

O parâmetro `s` contém o WebSocket de sinalização e `p`, quando presente, contém a senha. Um código isolado não informa o servidor; por isso a configuração `internet.servidor_sinalizacao` precisa apontar para um servidor acessível pelos participantes.

### Troca manual de SDP

`codificar_sdp(sdp, tipo)` produz um bloco `SS1-` com JSON comprimido por `zlib` e Base64 URL-safe. `decodificar_sdp(blob)` devolve o SDP e o tipo (`oferta` ou `resposta`). É o formato de base para levar uma negociação manualmente por outro meio, sem servidor de sinalização.

A interface gráfica padrão faz chamadas pela internet pelo fluxo de sala e WebSocket; o formato manual está isolado no núcleo e deve ser integrado por quem controlar manualmente a troca de SDP.

### Modo TCP direto legado

O modo legado é deliberadamente separado da pilha WebRTC. Ele escuta uma porta TCP, usa o protocolo binário de `nucleo/protocolo.py` e aceita um único espectador. É apropriado para rede local, mas não é uma solução de travessia de NAT.

## 5. Fontes e faixas de mídia

`listar_fontes()` sempre oferece a área de trabalho total e inclui monitores individuais quando a enumeração gráfica está disponível. Janelas específicas são obtidas por mecanismos da plataforma:

| Plataforma | Mecanismo de janelas |
| --- | --- |
| Windows | `user32` via `ctypes` |
| macOS | Quartz, quando disponível |
| Linux | `xdotool` ou `wmctrl`, quando instalados |

Para uma fonte de janela, `FaixaTela` pode consultar novamente a região antes de capturar, acompanhando sua movimentação. A captura e a conversão são deslocadas para uma thread com `asyncio.to_thread`, mantendo o laço assíncrono livre.

## 6. Gravação e buffer de clipes

`GerenciadorGravacao` é a fachada usada pela janela da chamada. Ele encaminha cada quadro local para a gravação contínua e para o `BufferClipes`, quando ativo.

| Componente | Função |
| --- | --- |
| `Gravador` | Abre o MP4, codifica vídeo e áudio e fecha o arquivo. |
| `_CodificadorMp4` | Configura streams de vídeo e AAC com PyAV; prefere `libx264` e usa `mpeg4` quando necessário. |
| `BufferClipes` | Retém JPEGs e PCM recentes em memória e exporta os últimos segundos em MP4. |
| `GerenciadorGravacao` | Trata erros para a interface, ativa/desativa buffer, grava e salva clipes. |

Os valores padrão do buffer são 120 segundos, 15 fps (`fps_buffer`) e JPEG qualidade 55 (`qualidade_buffer`). Os JPEGs substituem quadros BGR crus para reduzir a memória. `memoria_estimada_bytes` reporta a soma dos JPEGs e PCM guardados, sem a sobrecarga dos objetos Python.

## 7. Interface e segurança entre threads

A janela de chamada atualiza vídeos periodicamente. Cada `VisualizadorVideo` recebe o quadro mais novo, e a renderização é feita na thread Tkinter. A janela também mantém uma visualização destacada opcional para outra janela.

O chat não coloca emojis diretamente em widgets como garantia de compatibilidade: `RenderizadorEmojis` tenta encontrar uma fonte de emoji do sistema, desenha com Pillow e insere uma imagem Tk. Se isso falhar, há fallback de texto e atalhos digitáveis. A checagem de suporte direto mede a fonte no Tk antes de confiar no caractere.

## 8. Configuração e persistência

`Configuracoes` agrega as seções `video`, `audio`, `rede`, `internet`, `gravacao` e `interface`, serializadas com JSON UTF-8. A leitura é tolerante a arquivo ausente ou JSON inválido: nesse caso os padrões são usados.

Diretórios de dados:

- Windows: `%APPDATA%\ScreenShare`
- macOS: `~/Library/Application Support/ScreenShare`
- Linux: `$XDG_CONFIG_HOME/screenshare` ou `~/.config/screenshare`

A seção `internet` guarda servidor de sinalização, lista STUN, TURN, credenciais, `forcar_relay` e última sala. A seção `gravacao` guarda pasta, taxa de bits, duração e parâmetros do buffer.

## 9. Servidor de sinalização e publicação

O servidor é independente do executável de desktop e depende apenas de `aiohttp`. Ele mantém salas em memória: quando o último participante sai, a sala é removida. O processo lê `PORT` automaticamente quando `--porta` não é informado.

```bash
python -m pip install -r servidor_sinalizacao/requirements.txt
python servidor_sinalizacao/servidor.py
```

Em desenvolvimento, os endpoints são `ws://127.0.0.1:8080/ws` e `http://127.0.0.1:8080/saude`. O diretório inclui `Dockerfile`, `render.yaml` e `fly.toml`; instruções adicionais estão em [../servidor_sinalizacao/README.md](../servidor_sinalizacao/README.md).

## 10. Testes e empacotamento

A suíte `unittest` cobre convite, sinalização, pares WebRTC, chamada, fontes, faixas, gravação, emojis, interface, mídia e o caminho TCP legado. A versão 2.0 possui 110 testes automatizados.

```bash
ruff check .
python -m compileall -q .
xvfb-run -a -s "-screen 0 1280x800x24" python -m unittest discover -s testes -p "teste_*.py"
```

`build/screenshare.spec` inclui recursos e importações ocultas para Tk/Pillow, `mss`, áudio e a cadeia WebRTC/PyAV. Como há extensões nativas, gere o executável Windows no Windows e o binário Linux no Linux. Os scripts de `build/` instalam dependências, executam os testes e chamam PyInstaller.

## 11. Pontos de extensão

| Objetivo | Onde alterar |
| --- | --- |
| Mudar servidores STUN/TURN padrão | `configuracao/configuracoes.py` e a montagem ICE em `nucleo/par_webrtc.py`. |
| Acrescentar evento de sinalização | Cliente em `nucleo/sinalizacao.py`, roteamento em `servidor_sinalizacao/servidor.py` e tratamento em `nucleo/chamada.py`. |
| Novo tipo de mensagem de chat/estado | Canal de dados em `nucleo/chamada.py` e apresentação em `interface/chat_rico.py`. |
| Nova fonte de captura | `midia/fontes.py` e o contrato `FonteCaptura`. |
| Novo destino de gravação ou codec | `midia/gravador.py`. |
| Novo emoji ou atalho | Catálogo em `interface/emojis.py`. |
| Evoluir o modo TCP | `nucleo/protocolo.py`, `nucleo/sessao.py` e `aplicacao/`. |
