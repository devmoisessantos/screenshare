# Guia de conexão — ScreenShare 1.2

O ScreenShare oferece **vários caminhos** para conectar duas pessoas.  
Escolha o que for mais simples no seu caso.

---

## 1. Rede local (mesma Wi-Fi / cabo)

Funciona direto com o modo **TCP**.

1. Host clica em **Iniciar compartilhamento**.
2. Copia o endereço mostrado (ex.: `192.168.0.15:9999`).
3. Na primeira vez, abre **Diagnóstico** e libera a porta no firewall.
4. Espectador cola o endereço e conecta.

**Causas comuns de timed out**
- Firewall do Windows bloqueando → use o botão “Liberar porta”.
- IP errado (VPN, Docker, WSL) → no Diagnóstico escolha o IP marcado como **rede local**.
- Redes de visitantes / isolamento de cliente → use cabo ou outra rede.

---

## 2. Entre estados / países — Tailscale ou ZeroTier (recomendado hoje)

É a forma **mais estável e simples** no momento.

### Passo a passo (Tailscale)

1. Nos **dois** computadores instale: https://tailscale.com  
2. Faça login com a **mesma conta**.
3. No host, abra o ScreenShare → Diagnóstico → veja o IP que começa com `100.x.x.x`.
4. Use esse IP no modo TCP (ex.: `100.64.1.23:9999`).
5. O espectador cola esse endereço e conecta.

ZeroTier funciona do mesmo jeito (IPs geralmente `10.x` ou `172.x` da rede virtual).

**Vantagens**
- Não precisa abrir porta no roteador.
- Funciona de qualquer lugar do mundo.
- Latência geralmente boa.
- O app continua usando o protocolo TCP já estável.

---

## 3. Modo WebRTC (em desenvolvimento — 1.2)

Objetivo: conexão pela internet **sem instalar nada extra**, estilo Discord.

Status atual:
- Base de transporte e dependências (`aiortc`) preparadas.
- Servidores STUN públicos configurados.
- Fluxo completo de salas + sinalização será liberado nas próximas iterações.

Para testar quando disponível:
```bash
pip install aiortc aiohttp
```

---

## 4. Resumo rápido

| Situação                         | Melhor opção              |
|----------------------------------|---------------------------|
| Mesma casa / mesmo escritório    | TCP + IP local            |
| Cidades/estados/países diferentes| **Tailscale ou ZeroTier** |
| Quer zero instalação extra       | WebRTC (em breve)         |

---

## Dicas anti-timed-out

1. Sempre abra o **Diagnóstico** no host antes de pedir para o outro conectar.
2. Prefira o IP classificado como **rede local** ou **VPN (Tailscale)**.
3. Evite IPs `169.254.x.x`, `172.17.x.x` (Docker) e `192.168.56.x` (VirtualBox).
4. No Windows, execute uma vez o script `build/liberar_firewall_windows.bat` como administrador.
5. Se usar antivírus agressivo, adicione exceção para o `ScreenShare.exe`.
