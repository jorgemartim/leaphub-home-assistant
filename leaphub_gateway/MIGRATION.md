# Migração para o Leap Hub Gateway

## Antes de começar

Não remova os Apps antigos. Eles serão mantidos parados por alguns dias como caminho de reversão.

Apps antigos:

- Leap Hub Connector;
- Leap Hub OCPP Beta;
- Leap Hub OCPP Produção;
- Leap Hub Cloudflare Tunnel.

## Etapas

1. Instale **Leap Hub Gateway** pelo repositório oficial.
2. Copie as chaves atuais para a configuração única:
   - `staging_secret`: chave do Connector Beta;
   - `production_secret`: chave do Connector Produção;
   - `ocpp_beta_secret`: chave do OCPP Beta;
   - `ocpp_production_secret`: chave do OCPP Produção;
   - `tunnel_token`: token atual do Cloudflare Tunnel.
3. Mantenha `tunnel_enabled: false`.
4. Inicie o Gateway.
5. Abra o painel lateral e confirme Connector e OCPP Beta em execução.
6. No Cloudflare Tunnel, altere uma rota por vez:
   - `connector.leaphub.com.br` → `http://127.0.0.1:8094`;
   - `ocpp-beta.leaphub.com.br` → `http://127.0.0.1:8092`.
7. Teste os endpoints públicos e o botão **Testar gateway** no Leap Hub Beta.
8. Ative `tunnel_enabled` e reinicie o Gateway.
9. Pare o Tunnel antigo.
10. Teste novamente.
11. Pare os Apps antigos de Connector e OCPP.
12. Desative **Iniciar na inicialização** e **Watchdog** nos Apps antigos.

## Reversão

1. Pare o Gateway unificado.
2. Restaure as origens antigas no Cloudflare:

   ```text
   http://local-leaphub-connector:8094
   http://local-leaphub-ocpp-beta:8092
   ```

3. Inicie novamente os Apps antigos.
4. Teste os endpoints públicos.

## Remoção dos Apps antigos

Remova-os somente depois de alguns dias de funcionamento estável e após confirmar que as chaves foram preservadas em local seguro.


## Telemetria contínua 1.11.56

O Gateway guarda credenciais e eventos criptografados em `/data/telemetry`, usa intervalos adaptativos e reenvia a fila quando o site volta. Eventos usam identificadores determinísticos para impedir duplicidade. Uma queda do Home Assistant inteiro cria uma lacuna real; o sistema não inventa rota, consumo ou posições.
