# Histórico de mudanças

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
o projeto segue o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

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
