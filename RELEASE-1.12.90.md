# Leap Hub Gateway 1.12.90 — confirmação de clima por modo físico

Base publicada obrigatória: **1.12.89** (`33c89232c1a3582f41367580723377a05c5f53ac`).

## Problema comprovado

A confirmação de `climate_on`, `quick_cool` e `quick_heat` usava somente `climate_on=true`.
Isso prova apenas que o HVAC está ligado. Em teste de campo, um `quick_heat` podia ser
registrado como confirmado mesmo se o estado final ainda fosse resfriamento.

## Correção

A confirmação passa a distinguir a intenção física:
- `climate_on` -> `auto`;
- `quick_cool` -> `cooling`;
- `quick_heat` -> `heating`;
- `climate_off` -> `off`.

O matcher é deliberadamente model-agnostic:
- reconhece os valores 0/1/3 já validados no C10;
- aceita sinais textuais equivalentes em `mode`, `operate_mode` e `cooling_and_heating`;
- se um B10 ou modelo futuro publicar modo diferente/desconhecido, a confirmação fica
  inconclusiva em vez de mentir que o comando foi confirmado.

Nenhuma nova chamada de rede é criada. O `connector.py` apenas serializa o sinal
`ac_cooling_and_heating` quando ele já veio no status atual.

## Guardrails preservados

- payload de dispatch do C10 não muda;
- `climate_off` continua `ac_switch(..., params={"operate":"off"})`;
- máximo de duas transmissões exatas para OFF, nunca terceira;
- ACK-first preservado;
- polling não aumenta;
- mesmo cliente persistente, sem segundo cliente concorrente;
- bounded reads 1.12.89 preservados;
- Site não faz parte desta release.

`config.yaml` permanece 1.12.89 no commit funcional e só é promovido a 1.12.90
pelo GitHub Actions após validação, build, smoke test e publicação da imagem.
