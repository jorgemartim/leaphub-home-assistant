# Recuperação GitHub — Gateway 1.12.61

1. Envie somente os arquivos de `CHANGED-FILES-1.12.61.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.61`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.60` até a imagem nova estar pública.
   A CI promoveu a 1.12.60 em `c2990ae` enquanto esta release estava em preparo. O
   commit da 1.12.61 foi rebaseado sobre ela e não toca esse arquivo, então a
   promoção anterior fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile` nem a matriz de comandos. Ela conserta a
confirmação de comando, que nunca concluía.

**Causa, medida em produção:** `captured_at` chega sem fuso (a `leapmotor_api` faz
`strptime` ingênuo) e o portão de frescura presumia UTC. Num host em `-03:00` isso
lê o carimbo 3 horas mais cedo, e toda amostra é descartada por idade. Três
comandos consecutivos relataram 10739s, 10740s e 10777s de atraso aparente — sem
crescer com os 2 min entre eles, o que prova deslocamento fixo e não atraso.

**Mudanças:**

- `connector.py` — `iso_timestamp()` anexa o fuso local a datetime ingênuo e
  preserva o offset quando já existe.
- `telemetry_engine.py` — carimbo sem fuso é lido como hora local; frescura e
  atraso derivam de um único `_command_sample_epoch()`; amostra mais de 15 min no
  futuro não confirma (guarda contra errar a direção do fuso).

A margem de 2s da frescura não mudou de valor, apenas de lugar.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada
pelo Home Assistant. Corrija a causa e execute novamente.
