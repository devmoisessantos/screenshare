# ScreenShare 2.0

Aplicativo desktop em Python para chamadas de voz, vídeo, compartilhamento de tela e chat. A versão 2.0 usa WebRTC para conectar participantes pela internet diretamente entre si, sem enviar a mídia pelo servidor de sinalização.

O projeto, os nomes, os comentários e a documentação estão em português do Brasil. O modo TCP direto da versão anterior continua disponível como alternativa avançada de rede local.

## Recursos

- Chamadas pela internet em **topologia de malha**: cada participante estabelece uma conexão WebRTC direta com os demais.
- Até **6 participantes** por sala (`LIMITE_PARTICIPANTES`).
- Sinalização por WebSocket, com servidor próprio incluído em `servidor_sinalizacao/`.
- ICE/STUN para descoberta de rotas e TURN opcional para redes restritivas ou CGNAT.
- Criação de sala por código de seis caracteres e convite por link `screenshare://`.
- Áudio bidirecional, chat da sala e canal de controle por WebRTC.
- Compartilhamento de toda a área de trabalho, de um monitor ou de uma janela específica.
- Interface inspirada no Discord, com grade de vídeo, painel de participantes, avatar por iniciais, indicadores de microfone e tela, métricas e modo tela cheia.
- Chat com seletor e atalhos de emojis. Os emojis são renderizados como imagens para contornar a limitação do Tcl/Tk 8.6 com caracteres fora de UCS-2.
- Gravação local em MP4 e clipes a partir de buffer circular.
- Modo TCP direto anterior preservado na aba **Rede local (avançado)**.

## Requisitos

- Python **3.10 ou superior**.
- Tkinter. No Ubuntu/Debian: `sudo apt install python3-tk`.
- No Linux, PortAudio para o áudio: `sudo apt install libportaudio2`.
- Em Linux, a seleção de janelas depende de `xdotool` ou `wmctrl`; instale um deles se quiser compartilhar uma janela específica.

As dependências WebRTC e de mídia usam pacotes nativos. Para criar executáveis, faça o empacotamento no mesmo sistema operacional de destino.

## Instalação

```bash
git clone https://github.com/<seu-usuario>/screenshare.git
cd screenshare

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python principal.py
```

O áudio prefere `sounddevice`; se ele não puder ser usado, o aplicativo tenta PyAudio quando já estiver instalado. Sem motor de áudio disponível, a aplicação continua com vídeo e chat.

## Como fazer a primeira chamada pela internet

O código de sala **só funciona quando todos conseguem acessar o mesmo servidor de sinalização**. O servidor acompanha o repositório e pode ser executado localmente ou publicado em um serviço como Render, Fly.io ou Railway.

1. Prepare um servidor de sinalização:
   - para testar na mesma máquina, execute `python servidor_sinalizacao/servidor.py` e use `ws://127.0.0.1:8080/ws`;
   - para pessoas em redes diferentes, publique a pasta `servidor_sinalizacao/`. As instruções, `Dockerfile`, `render.yaml` e `fly.toml` estão em [servidor_sinalizacao/README.md](servidor_sinalizacao/README.md).
2. Abra o ScreenShare e informe o endereço WebSocket no campo **Servidor de sinalização**. Em hospedagem com HTTPS, o endereço normalmente é `wss://seu-dominio/ws`.
3. Na aba **Chamada pela internet**, informe seu apelido e clique em **Criar sala e entrar**. O aplicativo gera um código quando o campo estiver vazio.
4. Na janela da chamada, clique em **Copiar convite** e envie o texto para a outra pessoa.
5. A outra pessoa abre o ScreenShare, cola o link `screenshare://...` no campo **Ou cole um convite**, clica em **Usar convite** e depois em **Entrar na sala**. Também é possível digitar o código, desde que o mesmo servidor de sinalização já esteja configurado.
6. Depois que os pares estiverem conectados, clique em **Transmitir tela**, escolha a fonte e confirme.

O servidor de sinalização apenas cria salas e encaminha oferta, resposta e candidatos ICE. Áudio, vídeo, tela e chat seguem por conexões WebRTC entre os participantes; a mídia nunca passa pelo servidor de sinalização.

## Sem servidor nenhum: convite manual de SDP

O núcleo inclui o formato de convite manual de SDP `SS1-`: ele compacta uma oferta ou resposta SDP com `zlib` e Base64 URL-safe. As funções `codificar_sdp()` e `decodificar_sdp()` estão em `nucleo/convite.py` e permitem transportar a negociação por qualquer mensageiro, sem servidor de sinalização.

Use este caminho somente quando puder fazer a troca de oferta e resposta manualmente. A entrada principal da interface gráfica para chamadas pela internet usa o servidor de sinalização; portanto, para o fluxo comum por código de sala ou link, publique, aponte ou execute o servidor incluído.

## Quando precisa de TURN (CGNAT)

Na maior parte das redes domésticas, STUN e ICE encontram uma rota direta. Se a conexão direta falhar em uma operadora com CGNAT, em uma rede corporativa ou em uma rede que bloqueia UDP, configure um servidor TURN em **Ajustes**:

1. Informe endereço, usuário e senha do TURN, por exemplo `turn:servidor:3478`.
2. Tente a chamada novamente.
3. Use `forcar_relay` apenas quando precisar obrigar o tráfego a passar pelo TURN ou durante diagnóstico.

TURN pode retransmitir a mídia quando não há caminho direto. O servidor de sinalização do repositório não substitui um servidor TURN.

## Uso da interface

### Janela inicial

- **Chamada pela internet**: cria ou entra em uma sala WebRTC. Configure servidor de sinalização, código, senha opcional e convite.
- **Rede local (avançado)**: abre o modo TCP direto anterior como host ou espectador.
- **Ajustes**: seleciona tema, servidor TURN, pasta de gravação e ativação automática do buffer de clipes.

### Durante uma chamada

- **Mutar microfone**: interrompe o envio do seu microfone e atualiza seu estado para os demais.
- **Desligar som**: silencia localmente o áudio recebido.
- **Transmitir tela**: abre o seletor de área de trabalho, monitor ou janela. Clique outra vez para parar de transmitir.
- **Participantes**: exibe avatar com iniciais, estado da conexão e indicadores `mudo` e `tela`.
- **Chat da sala**: envia mensagens e aceita atalhos como `:)`, `:(`, `<3`, `:fogo:`, `:ok:` e `:festa:`.
- **Copiar convite** e **Ver convite**: compartilham o link da sala.
- **Tela cheia (F11)**: alterna entre janela e tela cheia; `Esc` sai da tela cheia.
- **Destacar transmissão**: abre o vídeo escolhido em outra janela quando esse controle estiver disponível na chamada.
- **Métricas**: a barra inferior mostra pares conectados, taxa estimada e perdas reportadas pelas estatísticas WebRTC.

Atalhos disponíveis:

| Atalho | Ação |
| --- | --- |
| `Ctrl+M` | Mutar/desmutar o microfone |
| `Ctrl+D` | Ligar/desligar o som recebido |
| `Ctrl+S` | Abrir o seletor ou parar o compartilhamento |
| `Ctrl+R` | Iniciar/parar a gravação local |
| `Ctrl+G` | Salvar clipe recente |
| `F11` | Tela cheia |
| `Esc` | Sair da tela cheia |
| `Ctrl+Q` | Encerrar a janela atual |

## Gravação e clipes

A gravação é local. O `GerenciadorGravacao` grava a imagem transmitida em MP4 e pode manter um buffer circular para exportar os últimos segundos como clipe.

- Os arquivos vão, por padrão, para `Vídeos/ScreenShare` dentro da pasta pessoal, ou para a pasta escolhida em **Ajustes**.
- O buffer padrão mantém **120 segundos**.
- Para reduzir o consumo de memória, o buffer armazena JPEG a **15 fps** e qualidade **55** por padrão. Os campos persistidos são `fps_buffer` e `qualidade_buffer`.
- O consumo efetivo guardado pelo buffer pode ser consultado por `memoria_estimada_bytes`.
- Use `Ctrl+R` para iniciar/parar a gravação e `Ctrl+G` para salvar a duração de clipe configurada, que é 30 segundos por padrão.

A gravação começa depois que houver um quadro local. O buffer pode ser ativado automaticamente ao transmitir, nas configurações.

## Modo rede local avançado

O modo antigo mantém a conexão TCP direta entre host e espectador. Ele é útil em uma LAN, mas **não atravessa NAT** e não resolve CGNAT. Para chamadas entre cidades ou redes domésticas diferentes, use a aba **Chamada pela internet** com sinalização WebRTC e, se necessário, TURN.

No modo local, o host pode precisar liberar a porta TCP 9999 no firewall. O script `build/liberar_firewall_windows.bat` cria a regra de entrada no Windows quando executado como administrador.

## Linha de comando

```bash
python principal.py
python principal.py --sala ABC123 --servidor-sinalizacao wss://meu-servidor.exemplo/ws
python principal.py --convite "screenshare://sala/ABC123?s=wss%3A%2F%2Fmeu-servidor.exemplo%2Fws"
python principal.py --host
python principal.py --assistir 192.168.0.10
python principal.py --host --console
python principal.py --versao
```

## Gerar o executável no Windows

O PyInstaller não faz compilação cruzada. Gere o `.exe` no Windows:

```bat
build\gerar_executavel_windows.bat
```

O resultado é `dist\ScreenShare.exe`. O script cria ou reutiliza `.venv`, instala as dependências, executa os testes e chama `build/screenshare.spec`. As importações ocultas necessárias para aiortc, PyAV e suas dependências transitivas já estão declaradas no arquivo `.spec`.

No Linux, use:

```bash
bash build/gerar_executavel_linux.sh
```

## Executar os testes

```bash
ruff check .
python -m compileall -q .
xvfb-run -a -s "-screen 0 1280x800x24" python -m unittest discover -s testes -p "teste_*.py"
```

A suíte usa `unittest` e possui 110 testes. O alvo `make testes` executa a descoberta padrão; `make sinalizacao` inicia o servidor local de sinalização.

## Estrutura de pastas

```text
screenshare/
├── principal.py                  # Ponto de entrada e argumentos de linha de comando
├── configuracao/                 # Preferências persistidas, rede, WebRTC e gravação
├── nucleo/                       # Convites, sinalização, pares WebRTC e orquestração
├── midia/                        # Fontes, faixas WebRTC, áudio e gravação
├── interface/                    # Janelas Tkinter, vídeo, chat, emojis e participantes
├── aplicacao/                    # Modo TCP direto legado
├── servidor_sinalizacao/         # Serviço aiohttp, Docker e manifestos de publicação
├── testes/                       # Testes unitários e de integração
├── build/                        # Scripts e especificação do PyInstaller
└── recursos/                     # Ícones da aplicação
```

Para detalhes das responsabilidades e dos fluxos, consulte [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## Limitações honestas

- Uma sala aceita no máximo seis participantes e usa malha: cada participante envia mídia diretamente para os demais, aumentando o consumo de banda de subida conforme entram pessoas.
- Código de sala e link de convite pela internet exigem um servidor de sinalização acessível. Publique o servidor incluído gratuitamente em Render, Fly.io ou Railway, ou execute-o em uma máquina acessível. Sem isso, use a troca manual de SDP `SS1-`.
- Redes em CGNAT muito restritas, redes corporativas ou redes que bloqueiam UDP podem exigir um TURN configurado pelo usuário.
- O servidor de sinalização não transporta mídia e não funciona como TURN.
- A seleção de janelas depende dos recursos do sistema operacional e, no Linux, de `xdotool` ou `wmctrl`.
- A captura de tela no Linux costuma exigir uma sessão X11 compatível com `mss`; em Wayland pode haver limitações.
- A gravação requer PyAV e um codec de vídeo compatível no ambiente.

## Licença

Distribuído sob a licença MIT. Consulte [LICENSE](LICENSE).

Desenvolvido por **Moises M Santos**, Goiânia/GO, Brasil.
