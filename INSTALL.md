# Instalação do Leap Hub Gateway

## Requisitos

- Home Assistant OS ou Home Assistant Supervised com suporte a Apps;
- acesso à Loja de Apps;
- arquitetura `amd64`;
- chaves HMAC geradas no Leap Hub;
- token do Cloudflare Tunnel, quando o Tunnel integrado for utilizado.

## Adicionar o repositório

1. No Home Assistant, abra **Configurações → Apps → Loja de Apps**.
2. Abra o menu de três pontos e selecione **Repositórios**.
3. Adicione:

   ```text
   https://github.com/jorgemartim/leaphub-home-assistant
   ```

4. Feche a janela e atualize a Loja.
5. Abra **Leap Hub Gateway** e clique em **Instalar**.

A instalação baixa uma imagem pronta do GitHub Container Registry. Não existe compilação local.

## Configuração inicial segura

Preencha as chaves correspondentes, sem compartilhá-las em capturas ou mensagens.

Mantenha inicialmente:

```yaml
tunnel_enabled: false
ocpp_production_enabled: false
```

Inicie o App e confirme no painel lateral:

- Connector Leapmotor: em execução;
- OCPP Beta: em execução;
- OCPP Produção: desativado;
- Cloudflare Tunnel: desativado.

## Migração das rotas

No Cloudflare Tunnel, altere somente as origens internas:

```text
connector.leaphub.com.br
→ http://local-leaphub-gateway:8094

ocpp-beta.leaphub.com.br
→ http://local-leaphub-gateway:8092
```

Não altere os hostnames públicos, DNS ou certificados.

Depois teste:

```text
https://connector.leaphub.com.br/health
https://ocpp-beta.leaphub.com.br/health
```

O retorno público esperado é:

```json
{"ok":true}
```

Quando os testes estiverem corretos, ative `tunnel_enabled`, reinicie o Gateway e pare os Apps antigos.

## Atualizações

Quando uma nova versão for publicada, o Home Assistant exibirá **Atualização disponível**. A atualização apenas baixa a nova imagem pronta.
