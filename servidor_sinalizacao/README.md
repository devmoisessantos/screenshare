# Servidor de sinalização WebRTC

Este pequeno servidor WebSocket reúne participantes que usam o mesmo código de
sala e encaminha as mensagens necessárias para iniciar conexões WebRTC.

Ele somente faz o encontro entre os pares. Áudio e vídeo **não passam por este
servidor**: depois da negociação, eles seguem diretamente entre os participantes
via WebRTC (ou por um TURN configurado pelo aplicativo, quando necessário).

## Rodar localmente

1. Instale a dependência:

   ```bash
   pip install -r servidor_sinalizacao/requirements.txt
   ```

2. Na raiz do projeto, inicie o serviço:

   ```bash
   python servidor_sinalizacao/servidor.py
   ```

3. O WebSocket estará em `ws://127.0.0.1:8080/ws` e a verificação de saúde em
   `http://127.0.0.1:8080/saude`.

Para outra porta, use por exemplo:

```bash
python servidor_sinalizacao/servidor.py --porta 9000
```

Em hospedagens, a variável de ambiente `PORT` é usada automaticamente quando
`--porta` não é informado.

## Implantar gratuitamente

Os planos gratuitos podem mudar de nome ou disponibilidade. Escolha um serviço
e mantenha o processo ativo conforme as regras atuais da plataforma.

### Render

1. Envie este projeto para um repositório Git.
2. No Render, crie um **Web Service** e conecte o repositório.
3. Defina o diretório raiz como `screenshare/servidor_sinalizacao` se o
   repositório contiver a pasta `screenshare`; caso contrário, use
   `servidor_sinalizacao`.
4. Use `pip install -r requirements.txt` como comando de instalação.
5. Use `python servidor.py --host 0.0.0.0 --porta $PORT` como comando de início.
6. Após publicar, copie a URL HTTPS fornecida e troque `https://` por `wss://`,
   acrescentando `/ws`.

### Fly.io

1. Instale a ferramenta de linha de comando do Fly.io e entre na sua conta.
2. No diretório `servidor_sinalizacao`, execute `fly launch`.
3. Quando solicitado, use o `Dockerfile` incluído e aceite a porta interna
   `8080`.
4. Publique com `fly deploy`.
5. Use `wss://NOME-DO-APP.fly.dev/ws` como endereço no aplicativo.

### Railway

1. Envie este projeto para um repositório Git e crie um novo projeto no Railway.
2. Escolha **Deploy from GitHub Repo**.
3. Configure o diretório raiz para `screenshare/servidor_sinalizacao` ou
   `servidor_sinalizacao`, conforme a posição dessa pasta no repositório.
4. O Railway instala `requirements.txt`; se necessário, configure o comando de
   início como `python servidor.py --host 0.0.0.0 --porta $PORT`.
5. Gere um domínio público no painel do serviço.
6. Converta a URL HTTPS do domínio para `wss://` e acrescente `/ws`.

## Apontar o aplicativo

No campo de configuração `servidor_sinalizacao` do aplicativo, informe a URL do
WebSocket, por exemplo:

```text
wss://meu-servidor.exemplo/ws
```

Em desenvolvimento local, use:

```text
ws://127.0.0.1:8080/ws
```

O endereço precisa terminar em `/ws`. O endpoint `/saude` é exclusivo para
monitoramento da hospedagem.
