# Recuperação GitHub — Gateway 1.12.57

1. Envie somente os arquivos de `CHANGED-FILES-1.12.57.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.57`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.56` até a imagem nova estar pública.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`. Toda a mudança de comportamento está em `connector.py`:

- `send_destination` passa a preencher o kwarg obrigatório `address_name` da `leapmotor_api` 0.3.2.
  Sem ele a introspecção de assinatura tratava um parâmetro exigido como não suportado e o comando
  falhava com `RuntimeError` antes de qualquer requisição — nenhum destino chegava ao carro.
- `seat_heat` (301) e `seat_ventilation` (370) entram na matriz estável recebendo posição (1-6) e
  nível (0-3). A faixa é conferida no gateway; valor inválido é recusado sem ida à nuvem.

Nenhum comando físico é repetido e nenhum é enviado sozinho: os dois comandos novos só saem quando o
proprietário os aciona, e apenas para o carro que declara o direito correspondente.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada pelo Home
Assistant. Corrija a causa e execute novamente.
