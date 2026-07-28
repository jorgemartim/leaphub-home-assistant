# Recuperação GitHub — Gateway 1.12.52

1. Envie somente os arquivos de `CHANGED-FILES-1.12.52.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.52`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.48` até a imagem nova estar pública.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `leaphub_gateway/Dockerfile`. A mudança está inteira em
`telemetry_engine.py`: a conexão de entrega reaproveitada passa a respeitar a janela de keep-alive
do servidor e ganha uma repetição imediata, com assinatura nova, quando o socket do pool já estava
fechado.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada pelo Home
Assistant. Corrija a causa e execute novamente; dados em `/data`, credenciais, filas e vínculos não
precisam ser removidos.
