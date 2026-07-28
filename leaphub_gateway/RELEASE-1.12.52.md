# Leap Hub Gateway 1.12.52 — a outra metade do keep-alive da entrega

## Por que esta versão existe

A 1.12.51 passou a reaproveitar a conexão TLS com o site entre lotes de telemetria. O ganho era
real, mas faltou a outra metade: `http.client` **não verifica** se o socket do pool continua
aberto. Ele escreve a requisição inteira e só descobre o problema no `getresponse()`.

Na hospedagem compartilhada a conexão ociosa é fechada em poucos segundos. Os lotes de telemetria
saem a cada 20-120s. O resultado observado em campo foi quase toda entrega reaproveitada falhando
com `Remote end closed connection without response` — **sem o PHP do site chegar a executar** — e o
lote inteiro voltando para o backoff.

O log do site confirma o outro lado. As poucas requisições que chegavam vinham truncadas:

```
[Leap Hub] Telemetria interna recusada: Assinatura interna ausente.
[Leap Hub] Falha temporária ao processar telemetria: Lote de telemetria vazio ou acima do limite.
[Leap Hub] Payload de telemetria inválido: O conteúdo enviado está vazio.
```

Como a reconciliação de comandos (`reconcilePendingCommands`) roda **dentro** da ingestão do site,
cada entrega perdida adiava a confirmação de `lock`/`unlock` por um ciclo inteiro de backoff. O
comando saía em ~3s e a confirmação demorava minutos.

## Correções

- **A conexão ociosa além da janela de keep-alive é descartada antes do envio.** O padrão é
  conservador (5s) e passa a seguir o `Keep-Alive: timeout=N` quando o servidor informa um,
  sempre dentro de limites de segurança.
- **Uma falha de transporte sobre conexão reaproveitada ganha uma tentativa imediata em conexão
  nova.** É seguro: ali o servidor comprovadamente não respondeu, e a ingestão do site é
  idempotente pelo `event_id`. A alternativa era esperar o backoff inteiro por um socket morto.
- **Cada tentativa recebe assinatura própria.** O site trata o nonce como uso único
  (`gateway_telemetry_nonces`), então repetir com o cabeçalho anterior seria recusado como
  requisição repetida. Sem uma função de assinatura disponível, o comportamento continua sendo o
  de tentativa única.

## O que não mudou

O ganho da 1.12.51 é preservado: dentro de uma rajada de lotes a conexão continua sendo
reaproveitada, que é exatamente quando o handshake pesava numa conexão residencial.

Nada de comando físico, credencial, vínculo, OCPP, MQTT, schema ou migration foi alterado. Toda a
fila persistente, o paralelismo de coleta, a confirmação FAST e a observabilidade da 1.12.51
permanecem exatamente como estavam.

## Validação

Suíte completa do repositório, incluindo o novo contrato
`tests/test_delivery_keepalive_1_12_52.py`, que cobre: reaproveitamento dentro da janela, descarte
depois dela, repetição em conexão nova com nonce novo, ausência de repetição sem função de
assinatura, e os limites do `Keep-Alive: timeout=N` anunciado pelo servidor.
