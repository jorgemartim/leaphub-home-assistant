# Recuperação GitHub — Gateway 1.12.60

1. Envie somente os arquivos de `CHANGED-FILES-1.12.60.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.60`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.59` até a imagem nova estar pública.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile` e **não** altera comportamento de
comando: a matriz, o critério de confirmação e a janela FAST seguem idênticos.
Toda a mudança está no diagnóstico, em `telemetry_engine.py`:

- As chaves observadas na telemetria passam a ser registradas para qualquer
  amostra do veículo-alvo, antes do descarte por idade. Antes ficavam dentro do
  ramo `if not evaluable`, então amostra velha deixava a lista vazia e o log dizia
  `chaves presentes na telemetria=[nenhuma]` — que se lê como telemetria vazia
  quando o caso era só atraso.
- Novo `_command_sample_lag()`: a linha de confirmação inconclusiva informa a
  distância entre a captura e o envio (`amostra mais recente 3600s antes do
  comando`), que é o que diz se o desalinhamento é de segundos ou de horas.

O portão de frescura (`captured_at >= command_started_at - 2.0`) foi mantido de
propósito. Ele hoje rejeita 100% das amostras, mas corrigi-lo antes de ter o
número seria escolher no escuro entre alargar a margem e trocar a origem do
`captured_at`.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada
pelo Home Assistant. Corrija a causa e execute novamente.
