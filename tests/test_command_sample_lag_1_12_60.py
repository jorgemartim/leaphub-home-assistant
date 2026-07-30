"""Contrato 1.12.60 — o diagnóstico da confirmação não pode mentir.

A instrumentação da 1.12.56 tinha um defeito que custou duas conclusões erradas:
`command_available_keys` só era preenchido dentro do ramo `if not evaluable`,
alcançável apenas por amostra que sobrevive ao teste de frescura. Amostra velha
caía no `continue` sem tocar a lista, e o log saía
`chaves presentes na telemetria=[nenhuma]` — que se lê como "a telemetria veio
vazia" quando o caso era apenas atraso. A leitura errada do próprio log levou ao
diagnóstico errado de que o carro não estava reportando nada.

O que este contrato protege:

1. As chaves observadas são registradas para **qualquer** amostra, não só para a
   que passa na frescura. Sem isso o log volta a confundir "vazia" com "velha".
2. Existe `_command_sample_lag()`, e a linha de log informa a distância entre a
   captura e o envio. `descartadas por idade` sozinho não diz se o carro está
   3 segundos ou 3 horas atrás do comando — e é essa distância que separa
   "recebeu e não obedeceu" de "não reportou".
3. `sunshade_open`/`sunshade_close` e `windows_open`/`windows_close` continuam
   com matcher declarado. Um teste do proprietário em 30/07/2026 mostrou a
   cortina abrindo e fechando de fato, sem a tela concluir: se o matcher
   desaparecer, perde-se a única via de confirmar esses comandos.

Nenhuma asserção fixa a versão exata.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


# ------------------------------------------------------- 1) o helper existe
check(
    "def _command_sample_lag(" in ENGINE,
    "_command_sample_lag() desapareceu; sem ele o log não informa o atraso da amostra",
)
check(
    # 1.12.62 — a variável perdeu o prefixo `command_`. Afirmar a chamada, e não
    # o nome, evita que o contrato passe por acidente: `command_sample_lag`
    # continuaria casando com o nome do próprio método.
    "self._command_sample_lag(telemetry, started_at)" in ENGINE and "sample_lag" in ENGINE,
    "a variável do atraso não é mais calculada no laço da confirmação",
)
check(
    "antes do comando" in ENGINE and "depois do comando" in ENGINE,
    "a linha de log deixou de expressar o atraso em relação ao envio",
)

# --------------------------- 2) as chaves saem de fora do ramo `not evaluable`
# O defeito original: a captura das chaves estava depois do `continue` da
# frescura. Aqui se afirma a ordem — chaves antes do descarte por idade.
#
# 1.12.62 — o laço saiu do corpo do ciclo e virou `_evaluate_confirmation()`,
# uma avaliação por comando pendente; os contadores perderam o prefixo
# `command_`. A garantia é a mesma e continua verificável: o que importa é a
# ordem dentro do laço, não onde ele mora.
loop = ENGINE[ENGINE.find("def _evaluate_confirmation("):]
loop = loop[: loop.find("poll_count = int(entry")]
pos_keys = loop.find("available_keys = sorted(")
pos_stale = loop.find("stale_samples += 1")
check(pos_keys != -1, "a captura das chaves observadas saiu do laço da confirmação")
check(pos_stale != -1, "o contador de amostras descartadas por idade saiu do laço")
check(
    pos_keys != -1 and pos_stale != -1 and pos_keys < pos_stale,
    "as chaves voltaram a ser capturadas só depois do descarte por idade: "
    "amostra velha zera a lista e o log volta a dizer [nenhuma]",
)
# E não podem estar condicionadas à amostra ser avaliável.
trecho_chaves = loop[max(0, pos_keys - 400):pos_keys]
check(
    "if not evaluable:" not in trecho_chaves,
    "a captura das chaves voltou para dentro do ramo `if not evaluable`",
)

# ------------------------------- 3) matcher dos comandos de abertura preservado
bloco = re.search(
    r"COMMAND_CONFIRMATION_FIELDS: dict\[str, tuple\[str, \.\.\.\]\] = \{(.*?)\n    \}",
    ENGINE,
    re.S,
)
check(bloco is not None, "COMMAND_CONFIRMATION_FIELDS não foi encontrado")
if bloco is not None:
    declarados = set(re.findall(r'"([a-z0-9_]+)":', bloco.group(1)))
    for comando in ("sunshade_open", "sunshade_close", "windows_open", "windows_close"):
        check(
            comando in declarados,
            f"{comando} perdeu o matcher de confirmação; ele executa de fato no carro "
            "e sem matcher a tela nunca conclui",
        )
    # Guarda de sanidade: o mapa não pode encolher sem alguém notar.
    check(
        len(declarados) >= 24,
        f"o mapa de confirmação encolheu para {len(declarados)} comandos (era 24)",
    )

# ----------------------------------------- 4) a regra de frescura segue explícita
check(
    "_command_sample_is_fresh" in ENGINE,
    "a regra de frescura desapareceu; o atraso perde referência",
)
# 1.12.61 — este check afirmava a expressão literal `command_started_at - 2.0`.
# O refactor que centralizou o parsing do carimbo passou a comparar o atraso já
# calculado (`lag <= 2.0`) e o literal deixou de existir, quebrando o contrato por
# forma e não por garantia. O que importa é a margem de 2s continuar existindo e
# visível, não como ela é escrita.
check(
    "lag <= 2.0" in ENGINE or "command_started_at - 2.0" in ENGINE,
    "a margem de 2s da frescura desapareceu; ela é o que separa amostra de antes "
    "e de depois do comando, e o valor precisa ficar visível no código",
)

if failures:
    raise SystemExit("command sample lag contract failed:\n- " + "\n- ".join(failures))

print({"ok": True, "checks": 12, "version": "1.12.63"})
