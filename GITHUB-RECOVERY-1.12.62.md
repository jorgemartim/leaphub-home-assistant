# Recuperação GitHub — Gateway 1.12.62

1. Envie somente os arquivos de `CHANGED-FILES-1.12.62.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.62`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.61` até a imagem nova estar
   pública. A CI promoveu a 1.12.61 em `33417f8`; o commit da 1.12.62 não toca
   esse arquivo, então a promoção anterior fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile` nem a matriz de comandos. Ela conserta
o esquecimento de comandos concorrentes na janela de confirmação.

**Causa, medida em produção (30/07/2026):** a janela morava em colunas únicas da
linha da assinatura. `sunshade_open` às 13:34:40, `unlock` às 13:36:03, janela
fechando às 13:37:38 com log de `unlock` apenas — o segundo comando sobrescreveu
o contexto do primeiro, que nunca recebeu veredito.

**Mudanças:**

- `telemetry_engine.py` — tabela nova `command_confirmations`, uma espera por
  `request_id`, avaliada a cada leitura; janela encerrada por prazo, com a
  contagem de leituras como teto de segurança (piso 8, cobre os 180s); janela
  herdada da versão anterior é adotada; `/status` informa as esperas pendentes.
- `gateway_manager.py` — piso e teto do orçamento de leituras acompanham o motor.

**Migração:** a tabela é criada com `CREATE TABLE IF NOT EXISTS` no mesmo caminho
que já cria as demais. Nenhuma coluna foi removida e as antigas continuam
preenchidas, então uma reversão para a 1.12.61 volta a funcionar com a janela
única, sem perder dado.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada
pelo Home Assistant. Corrija a causa e execute novamente.
