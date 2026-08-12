# Recuperação GitHub — Gateway 1.12.78

1. Envie somente os arquivos de `CHANGED-FILES-1.12.78.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.78`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.77` até a imagem nova estar
   pública. O commit da 1.12.78 não toca esse arquivo.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Uma única mudança de comportamento, repartida em dois arquivos:

- `leaphub_gateway/telemetry_engine.py` ganha `announce_command_result`, um POST
  assinado ao site em `/api/internal/commands/result` com o mesmo payload que
  `/v1/vehicles/command/status` devolveria. Destino derivado da URL de telemetria
  já configurada; conexão própria, curta, fora do `_delivery_guard` da thread de
  entrega; timeout de 8s, sem retry.
- `leaphub_gateway/connector_server.py` chama esse anúncio ao concluir o worker,
  em thread daemon, e `command_journal_finish` passa a devolver o payload que
  grava no diário para que exista uma fonte só.

Nada muda na matriz de comandos, na telemetria de fundo, no schema do add-on
nem no Dockerfile. Um site que ainda não expõe a rota responde 404, o anúncio
desiste em silêncio e a reconciliação segue pelo ciclo do cron, como antes.

**Depende do site na 1.12.333 ou maior para ter efeito.** Publicar só o Gateway
não regride nada — apenas não acelera nada.
