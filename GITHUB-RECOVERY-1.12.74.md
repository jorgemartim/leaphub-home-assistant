# Recuperação GitHub — Gateway 1.12.74

1. Envie somente os arquivos de `CHANGED-FILES-1.12.74.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.74`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.73` até a imagem nova estar
   pública. O commit da 1.12.74 não toca esse arquivo, então a promoção anterior
   fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`, a matriz de comandos, o schema do
add-on nem o orçamento de leituras da janela de confirmação. Ela muda **quando**
essas leituras acontecem e **quantas esperas** um comando físico gera.

Duas mudanças, ambas em `leaphub_gateway/telemetry_engine.py`:

- `COMMAND_FIRST_POLL_CEILING_SECONDS` (novo) e a escada
  `self.command_cadence`. O teto vive em código, não no `config.yaml`: a
  instalação existente guarda o valor antigo de `telemetry_command_seconds` e
  nunca releria um padrão novo. É o mesmo motivo de
  `COMMAND_DISPATCH_TIMEOUT_FLOOR_SECONDS` e `COMMAND_MAX_POLLS_FLOOR`, e o
  contrato novo prova o teto contra uma instalação que guarda `12`.
- `_settled_confirmation()` (novo), consultado por `_register_confirmation()`
  **somente** quando o boost chega sem `request_id` e **somente** depois de a
  busca por espera pendente falhar. A ordem importa: inverter as duas mata a
  adoção que a 1.12.62 comprou. **A guarda lê `status='confirmed'`, não
  `status<>'pending'`**: se ela passar a suprimir também janela esgotada, a
  recuperação de um comando sem veredito morre com ela — e esse é o defeito
  oposto e pior.

Contratos tocados nesta release, e por quê:

- `tests/test_command_confirmation_twin_1_12_74.py` — novo. Dez casos, três
  deles controles negativos das restrições acima.
- `tests/test_remote_confirmation_1_12_22.py`,
  `tests/test_command_window_backoff_1_12_70.py`,
  `tests/test_driving_record_probe_1_12_72.py`,
  `tests/test_awake_cadence_1_12_65.py` — carimbavam a tupla da cadência ou o
  primeiro degrau. Reescritos para afirmar a garantia (o mapeamento leitura ↔
  degrau, a cobertura da janela, o teto lido da constante) em vez de copiar
  números.
- `tests/test_contracts.py` e `tests/test_fast_install_1_12_18.py` — o par
  `{versão anterior, versão atual}` era escrito à mão a cada release e não
  sobrevive a uma substituição geral de versão, que colapsa as duas pontas no
  mesmo número. Agora leem o `RELEASE_TARGET` e afirmam `config <= alvo`.
