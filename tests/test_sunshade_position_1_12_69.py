"""1.12.69 — a cortina do teto aceita posição, e a escala é convertida.

A cortina é o único comando desta matriz em que a escala de LEITURA e a de
ESCRITA não coincidem:

  - leitura: no C10/B10 a nuvem publica a abertura da cortina em
    `security.roof_opening`, um percentual (medido em campo em 30/07/2026:
    aberta=100, fechada=0). O gateway o entrega como `sunshade_percent`, 0-100,
    e é esse número que o dono lê na figura do carro ("CORT. 45%").
  - escrita: `leapmotor_api.models.SunshadeValue` documenta a faixa 0-10, com
    `OPEN = "10"` e `CLOSE = "0"` — 11 degraus de 10%.

O gateway recebe 0-100, para falar a mesma língua do site e do dono, e converte
antes de chamar a biblioteca. Sem a conversão o carro receberia um valor fora da
faixa que ele declara aceitar — e a nuvem responde `code=0` de qualquer jeito,
então o erro seria silencioso: o dono pediria 45% e nada aconteceria.

Este teste EXERCITA `execute_vehicle_command` com um dublê que registra o que
seria enviado, em vez de procurar a linha que faz a conversão.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "leaphub_gateway"))

import connector  # noqa: E402

checks = 0
falhas: list[str] = []


def confere(condicao: bool, mensagem: str) -> None:
    global checks
    checks += 1
    if not condicao:
        falhas.append(mensagem)


class DubleCliente:
    """Registra o `value` que chegaria à biblioteca."""

    def __init__(self) -> None:
        self.enviados: list[str] = []

    def __call__(self, vehicle_id: str, *, value: str) -> dict:
        self.enviados.append(value)
        return {"code": 0}


def envia(percent) -> str:
    duble = DubleCliente()
    connector.execute_vehicle_command(duble, "sunshade_position", "VIN", {"sunshade_position": percent})
    assert len(duble.enviados) == 1
    return duble.enviados[0]


# ------------------------------------------------ a matriz conhece o comando
confere(
    connector.COMMAND_METHODS.get("sunshade_position") == "control_sunshade",
    "sunshade_position nao aponta para control_sunshade",
)
# `open_sunshade`/`close_sunshade` mandam o cmd 161 nos extremos; `control_sunshade`
# e o mesmo comando com posicao. Usar open_sunshade aqui perderia o valor.
confere(
    connector.COMMAND_REQUIRED_RIGHT.get("sunshade_position") == 161,
    "sunshade_position nao exige o direito 161, o mesmo de sunshade_open/close",
)
confere(
    "sunshade_position" not in connector.EXPERIMENTAL_COMMAND_METHODS,
    "sunshade_position entrou na matriz experimental; ele pertence a estavel, como windows_position",
)

# ------------------------------------------------------------- a conversao
# Os extremos sao os que a biblioteca nomeia: CLOSE="0" e OPEN="10".
confere(envia(0) == "0", 'cortina em 0% deveria virar "0" (SunshadeValue.CLOSE)')
confere(envia(100) == "10", 'cortina em 100% deveria virar "10" (SunshadeValue.OPEN)')
confere(envia(50) == "5", 'cortina em 50% deveria virar "5"')
confere(envia(30) == "3", 'cortina em 30% deveria virar "3"')

# Valor entre degraus vai para o mais proximo — nunca para fora da faixa.
confere(envia(45) == "5", 'cortina em 45% deveria arredondar para "5"')
confere(envia(44) == "4", 'cortina em 44% deveria arredondar para "4"')

# O que sai NUNCA pode estar fora de 0..10, para qualquer entrada valida.
for percent in range(0, 101):
    nativo = int(envia(percent))
    if nativo < 0 or nativo > 10:
        falhas.append(f"cortina em {percent}% saiu como {nativo}, fora da faixa 0-10 da biblioteca")
        break
checks += 1

# -------------------------------------------------------------- as recusas
for invalido, motivo in ((-1, "negativo"), (101, "acima de 100"), (1000, "muito acima")):
    checks += 1
    try:
        envia(invalido)
        falhas.append(f"cortina aceitou posicao {motivo} ({invalido})")
    except ValueError:
        pass

for vazio in (None, "", "abre"):
    checks += 1
    try:
        envia(vazio)
        falhas.append(f"cortina aceitou posicao ilegivel: {vazio!r}")
    except ValueError:
        pass

# ------------------------------------------------------- controle negativo
# Sem a conversao, 45% viraria "45" — valor que a biblioteca nao declara aceitar
# e que o carro ignora em silencio. Se a medicao acima nao dependesse da
# conversao, este bloco passaria com o defeito reintroduzido.
checks += 1
duble = DubleCliente()
connector.execute_vehicle_command(duble, "windows_position", "VIN", {"window_position": 45})
confere(
    duble.enviados == ["45"],
    "windows_position deixou de passar a porcentagem direto; a janela e 0-100 na biblioteca",
)
confere(
    envia(45) != "45",
    "controle negativo: a cortina esta mandando a porcentagem crua, como se fosse janela",
)

# -------------------------------------- a premissa de escala da LEITURA de pe
# A conversao so faz sentido enquanto a leitura chegar em 0-100. Ela chega
# porque, no C10/B10 sem campo proprio de cortina, `security.roof_opening`
# alimenta `sunshade_percent` — a troca condicionada por modelo da 1.12.63. Se
# essa troca sair, a leitura muda de origem e possivelmente de escala, e a
# conversao aqui vira erro em vez de conserto. O teste falha ANTES, dizendo
# onde olhar, em vez de deixar o dono descobrir com a cortina no lugar errado.
fonte = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
checks += 1
confere(
    "sunshade_position = roof_opening" in fonte and 'visual_model_family(model) in {"c10", "b10"}' in fonte,
    "a troca de 1.12.63 saiu: a cortina pode ter mudado de origem e de escala, e a conversao da 1.12.69 assume 0-100",
)

if falhas:
    print({"ok": False, "falhas": falhas, "version": "1.12.69"})
    raise SystemExit(1)

print({"ok": True, "checks": checks, "version": "1.12.69"})
