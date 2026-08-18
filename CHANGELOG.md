# Histórico de mudanças

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
o projeto segue o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [1.1.0] - 2026-08-18

### Adicionado
- **Prévia da própria transmissão** na janela do host (`midia/previa.py`), ativa
  desde o início do compartilhamento, antes de qualquer espectador conectar.
- **Controles de áudio no estilo Discord** (`BarraControleAudio`): botões
  independentes de mudo do microfone e de desativar o som recebido, com estado
  visual e exibição do estado do outro lado.
- Atalho `Ctrl+D` para ativar/desativar o som recebido.
- **Janela de diagnóstico de rede** (`interface/janela_diagnostico.py`): lista os
  endereços da máquina classificados (rede local, VPN, adaptador virtual, sem
  rede), verifica e libera a porta no firewall e testa o alcance de um host.
- Script `build/liberar_firewall_windows.bat`, que cria a regra de entrada TCP
  necessária no Windows.
- Camada de diagnóstico em `utilitarios/rede.py`: `listar_ips_locais`,
  `ip_local_recomendado`, `testar_alcance`, `firewall_liberado` e
  `liberar_firewall`.
- 29 novos testes automatizados (total de 74).

### Alterado
- **Áudio migrado para o `sounddevice`**, com o PyAudio mantido como alternativa
  automática, garantindo compatibilidade com o Python 3.13 e 3.14. O motor é
  detectado em tempo de execução e exibido na interface.
- Mensagens de erro de conexão agora são específicas e acionáveis: tempo
  esgotado, conexão recusada e endereço inválido têm orientações distintas em vez
  de um erro genérico.
- O endereço sugerido ao host passa a ser o de rede local realmente alcançável,
  ignorando VPNs, adaptadores virtuais e endereços `169.254.x.x`.
- Janela do host reorganizada em duas colunas (configurações e prévia/chat), com
  passo a passo de conexão visível.
- Tempo limite de conexão elevado para 8 segundos.
- Dependências com versões mínimas em vez de fixas.

## [1.0.0] - 2026-08-18

### Adicionado
- Compartilhamento de tela ponto a ponto (1:1) sobre TCP, com captura via `mss`
  e compressão JPEG em 480p, 720p ou 1080p, de 15 a 60 fps.
- Áudio bidirecional (44,1 kHz, mono, 16 bits) com botão de mudo em ambos os lados.
- Chat bidirecional com autor, horário e mensagens de sistema.
- Protocolo binário próprio com prefixo mágico, tipos de mensagem e limite de carga.
- Handshake com verificação de versão e senha opcional (token SHA-256).
- Qualidade JPEG adaptativa e descarte de quadros conforme a latência medida.
- Reconexão automática do espectador após queda de conexão.
- Seleção de monitor (multimonitor) e de dispositivos de áudio.
- Interface gráfica em Tkinter com temas escuro e claro e atalhos de teclado.
- Estatísticas ao vivo: FPS, latência, qualidade, taxas de transferência e descartes.
- Persistência de configurações em JSON e log rotativo em arquivo.
- Modo console (`--console`) para host sem interface gráfica.
- 45 testes automatizados (unitários e de integração).
- Scripts de build com PyInstaller para Windows e Linux.
