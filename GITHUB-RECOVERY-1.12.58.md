# Recuperação GitHub — Gateway 1.12.58

1. Envie somente os arquivos de `CHANGED-FILES-1.12.58.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.58`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.57` até a imagem nova estar pública.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`. Toda a mudança de comportamento está em
`connector.py`:

- Seis comandos entram na matriz estável: `sunroof_open`/`sunroof_close` (300, direito
  **160** — não confundir com a cortina do teto, direito 161), `windows_position` (230,
  de 0 a 100), `set_speed_limit` (510) e `music`/`video` (270/290, com
  play/pause/next/previous). Faixa conferida no gateway antes de qualquer ida à nuvem.
- `prepare_car` (360) entra como **experimental**, exigindo confirmação explícita do
  proprietário, com envelope allow-listed montado no gateway.
- `SENTRY_COMMANDS` passou a ser um conjunto explícito, para que o segundo experimental
  não herde a sonda de diagnóstico do Sentinela.

Nenhum comando físico é repetido e nenhum é enviado sozinho: os comandos novos só saem
quando o proprietário os aciona, e apenas para o carro que declara o direito. `autopark`
e `piloted_parking`, que movem o carro, ficaram deliberadamente fora.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada pelo
Home Assistant. Corrija a causa e execute novamente.
