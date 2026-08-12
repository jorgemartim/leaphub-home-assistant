"""1.12.75 — o orçamento de leituras voltou a ser TETO, e não critério de fim.

O defeito, medido em campo em 11/08/2026 (conta acct_1c8b987d):

    14:52:07  unlock  8 leituras,  135s  (orçamento de leituras esgotado)
    14:53:02  unlock  8 leituras,   60s  (orçamento de leituras esgotado)

Nas duas a janela permitia 180s. 14:52:07 − 135s = 14:49:52 e 14:53:02 − 60s =
14:52:02, exatamente os instantes em que os dois despachos de `unlock`
terminaram — a conta fecha no segundo.

A causa foi minha, na 1.12.74: adensei a escada e mantive "as mesmas 8
leituras". Com a escada antiga a 8ª leitura caía aos 382s, muito além dos 180s,
e o teto NUNCA disparava primeiro; com a nova ela cai aos 195s, e basta uma
leitura extra para o teto passar na frente do prazo. Leitura extra é comum: a
cadência acompanha a espera mais nova (`min(poll_count)`) enquanto CADA leitura
consome o orçamento de TODAS as pendentes, então apertar um segundo botão
reinicia a escada no primeiro degrau e queima o resto do orçamento do comando
anterior em segundos.

Este contrato afirma a GARANTIA, nunca o número: nenhuma leitura que caiba na
janela pode encerrar a espera pelo orçamento. Ele reprova a 1.12.74.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# `telemetry_engine` faz `import leaphub_connector`; ele precisa existir com
# esse nome antes da carga, como nos demais contratos.
load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_budget_window_test", APP / "telemetry_engine.py")
motor_fonte = (APP / "telemetry_engine.py").read_text(encoding="utf-8")

JANELA = telemetry.TelemetryEngine.COMMAND_WINDOW_CEILING_SECONDS


def _espera(agora: float, decorrido: float, leituras_ja_feitas: int, restante: float) -> dict:
    """Uma linha de `command_confirmations` como `_evaluate_confirmation` a lê."""
    return {
        "confirmation_id": "cid",
        "command_key": "unlock",
        "command_vehicle_id": "veh-1",
        "request_id": "req-1",
        "context_json": "{}",
        "started_at": agora - decorrido,
        "expires_at": agora + restante,
        "poll_count": leituras_ja_feitas,
    }


with tempfile.TemporaryDirectory(prefix="leaphub-budget-") as tmp:
    os.environ["LEAPHUB_TELEMETRY_DIR"] = tmp
    engine = telemetry.TelemetryEngine(
        {
            "telemetry_beta_enabled": True,
            "telemetry_beta_internal_url": "https://example.invalid/telemetry",
            # De propósito: os valores que a instalação de campo guarda. Uma
            # opção armazenada nunca relê um padrão novo, então o piso tem de
            # vencer o valor gravado — é a mesma razão de
            # COMMAND_DISPATCH_TIMEOUT_FLOOR_SECONDS.
            "telemetry_command_seconds": 12,
            "telemetry_command_max_polls": 8,
        },
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )
    try:
        agora = 1_800_000_000.0
        primeiro_degrau = engine.command_cadence[0]

        # --- a garantia, dita como desigualdade ---------------------------------
        # Com o menor degrau possível, o número de leituras que cabem na janela é
        # JANELA // primeiro_degrau. O orçamento precisa ser maior que isso, ou
        # ele volta a ser o critério de encerramento.
        cabem_na_janela = JANELA // primeiro_degrau
        assert engine.command_max_polls > cabem_na_janela, (
            f"orçamento {engine.command_max_polls} não cobre as {cabem_na_janela} leituras "
            f"que cabem em {JANELA}s a cada {primeiro_degrau}s — o teto volta a fechar antes do prazo"
        )
        # A 1.12.74 tinha 8: este é o valor que o contrato precisa reprovar.
        assert 8 <= cabem_na_janela, "a aritmética do defeito mudou; revise o contrato"

        # --- nenhuma leitura do prazo encerra por orçamento ----------------------
        for leitura in range(1, cabem_na_janela + 1):
            decorrido = min(JANELA - 1, leitura * primeiro_degrau)
            item = engine._evaluate_confirmation(
                _espera(agora, decorrido, leitura - 1, JANELA - decorrido), [], agora
            )
            assert not item["exhausted"], (
                f"a {leitura}ª leitura encerrou a espera aos {int(decorrido)}s "
                f"com {int(JANELA - decorrido)}s de janela ainda disponíveis"
            )

        # --- o caso de campo, com os números do log -----------------------------
        # 8ª leitura aos 135s, 45s de janela restantes. A 1.12.74 fechava aqui.
        campo = engine._evaluate_confirmation(_espera(agora, 135.0, 7, 45.0), [], agora)
        assert not campo["exhausted"], "o caso de 11/08 às 14:52:07 continua fechando por orçamento"
        # 8ª leitura aos 60s, 120s restantes — a janela colapsada pelo comando vizinho.
        vizinho = engine._evaluate_confirmation(_espera(agora, 60.0, 7, 120.0), [], agora)
        assert not vizinho["exhausted"], "o caso de 11/08 às 14:53:02 continua fechando por orçamento"

        # --- controles negativos ------------------------------------------------
        # 1. O PRAZO continua encerrando. Sem isto, "não encerra por orçamento"
        #    seria satisfeito por uma espera que nunca termina.
        vencida = engine._evaluate_confirmation(_espera(agora, JANELA + 5, 3, -5.0), [], agora)
        assert vencida["exhausted"] and vencida["reason"] == "window_deadline", (
            "a espera vencida deixou de ser encerrada pelo prazo"
        )
        # 2. O teto de segurança continua EXISTINDO. Ele só não pode chegar antes
        #    do prazo; removê-lo de vez deixaria uma cadência patológica sem freio.
        estourada = engine._evaluate_confirmation(
            _espera(agora, 10.0, engine.command_max_polls, JANELA), [], agora
        )
        assert estourada["exhausted"] and estourada["reason"] == "poll_budget", (
            "o teto de segurança desapareceu"
        )
        # 3. A escada NÃO cresceu para acompanhar o orçamento: o índice satura.
        #    Um orçamento de 31 com uma escada de 31 degraus seria outro defeito.
        assert len(engine.command_cadence) < engine.command_max_polls
        assert engine._adaptive_interval(
            ["parked"], 0, command_mode=True, command_poll_count=engine.command_max_polls
        )[0] == engine.command_cadence[-1], "leitura além da escada não saturou no último degrau"

        # --- o piso é derivado, não escolhido -----------------------------------
        # Um número escrito à mão volta a descolar da escada no próximo ajuste,
        # que é exatamente como a 1.12.74 quebrou.
        assert "COMMAND_WINDOW_CEILING_SECONDS" in motor_fonte
        assert "derived_floor" in motor_fonte and "first_step" in motor_fonte, (
            "o piso voltou a ser literal"
        )
        # E o manager não pode estrangular o que o motor derivou: ele normaliza a
        # opção ANTES de o motor vê-la.
        manager_fonte = (APP / "gateway_manager.py").read_text(encoding="utf-8")
        assert "max({}, min({}".format(
            telemetry.TelemetryEngine.COMMAND_MAX_POLLS_FLOOR,
            telemetry.TelemetryEngine.COMMAND_MAX_POLLS_CEILING,
        ) in manager_fonte, "o manager e o motor discordam do intervalo da opção"
    finally:
        engine.close_storage()
        if engine._instance_lock_handle is not None:
            engine._instance_lock_handle.close()

print("contrato 1.12.75: orçamento de leituras não encerra espera dentro do prazo")
