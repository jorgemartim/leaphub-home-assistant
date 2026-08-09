# Recuperação GitHub — Gateway 1.12.73

1. Envie somente os arquivos de `CHANGED-FILES-1.12.73.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.73`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.72` até a imagem nova estar
   pública. O commit da 1.12.73 não toca esse arquivo, então a promoção anterior
   fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`, a matriz de comandos, a cadência nem
o schema do add-on. Ela muda o que a fila de telemetria faz com uma entrega
recusada.

Duas partes, e elas são independentes de propósito — a segunda vale mesmo contra
um site que não conhece a primeira:

- `_deliver_group()` passa a separar o resultado marcado `permanent` pelo site
  (1.12.328 em diante) do resultado sem marca. O marcado sai da fila por
  `_mark_permanent_failure()`, com o motivo; o sem marca continua em
  `_delivery_failed()`, exatamente como antes. **A leitura é `is True`, não
  "valor verdadeiro"**: se ela virar `is not None` ou `bool(...)`, um `"false"`
  vindo de um proxy passaria a descartar telemetria boa.
- `_maintenance()` passa a abandonar o evento `pending` mais velho que a janela
  de retenção, e a podar também o `failed` — antes só o `delivered` era podado,
  e por isso o não entregue nunca envelhecia. Sem a segunda linha, o descarte
  troca repetição infinita por linha infinita no disco.

Nada depende de estado no disco: não há migração. Um evento que a 1.12.73 tiver
marcado como `failed` continua sendo apenas uma linha terminal para a 1.12.72,
que a ignora na entrega — voltar não recria o laço nem perde leitura nova.

O contrato desta release é `tests/test_permanent_rejection_1_12_73.py`. Ele
mede as três garantias com o controle negativo de cada uma: a recusa transitória
tem de continuar sendo repetida, o evento dentro da janela tem de continuar
pendente e o descarte recente tem de continuar no banco.
