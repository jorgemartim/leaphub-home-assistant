"""Contrato 1.12.56 — as fases do comando precisam fechar `remote_execute_ms`.

Dois comandos de campo deixaram ~90s de 94s sem atribuição, com todas as fases
medidas em zero e o dispatch em ~4s. A soma precisa ser fechável, senão a
próxima investigação vira palpite de novo.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"

ENGINE = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
CONNECTOR = (APP / "connector.py").read_text(encoding="utf-8")
SERVER = (APP / "connector_server.py").read_text(encoding="utf-8")


def test_engine_publishes_the_three_missing_phases():
    for field in ("engine_precheck_ms", "handle_command_ms", "confirmation_arm_ms"):
        assert f'phase["{field}"] = {field}' in ENGINE, field


def test_precheck_starts_before_the_cloud_allowance_check():
    # engine_started tem de vir antes de assert_account_cloud_allowed, senão a
    # fase mede menos do que existe.
    started = ENGINE.index("engine_started = time.monotonic()")
    allowed = ENGINE.index("self.assert_account_cloud_allowed(environment, account_id, \"command\")")
    assert started < allowed


def test_handle_command_and_arm_are_measured_even_on_failure():
    assert "finally:\n                    handle_command_ms = int(round((time.monotonic() - handle_started) * 1000))" in ENGINE
    assert "finally:\n                    confirmation_arm_ms = int(round((time.monotonic() - arm_started) * 1000))" in ENGINE


def test_progress_journal_is_measured_inside_the_connector():
    assert '"progress_ms": 0,' in CONNECTOR
    assert 'phase_latency_ms["progress_ms"] += int(round((time.monotonic() - report_started) * 1000))' in CONNECTOR


def test_report_is_never_called_before_the_counter_exists():
    """`report` é closure: chamar antes de `phase_latency_ms` seria NameError."""
    definition = CONNECTOR.index("    def report(stage: str, message: str, extra: dict[str, Any] | None = None) -> None:")
    counters = CONNECTOR.index("    phase_latency_ms: dict[str, int] = {")
    body = CONNECTOR[definition:counters]
    # A própria definição contém "progress(" e "report_started"; o que não pode
    # existir é uma CHAMADA a report() nesse intervalo.
    assert "\n        report(" not in body
    assert "\n    report(" not in body


def test_unaccounted_does_not_double_count_the_inner_phases():
    """preparo/dispatch/verificacao/progresso vivem dentro de handle_command."""
    assert 'latency["engine_precheck_ms"] + latency["session_wait_ms"]' in SERVER
    assert '+ latency["session_login_ms"] + latency["handle_command_ms"]' in SERVER
    assert '+ latency["confirmation_arm_ms"]' in SERVER
    unaccounted = SERVER[SERVER.index('"unaccounted_ms": max(0,'):]
    unaccounted = unaccounted[: unaccounted.index("))")]
    for inner in ("session_prepare_ms", "dispatch_ms", "verification_ms", "progress_ms"):
        assert inner not in unaccounted, inner


def test_log_line_placeholders_match_its_arguments():
    """Um %s a mais derruba o log do comando em produção."""
    tree = ast.parse(SERVER)
    checked = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        if "Comando remoto %s finalizado no worker" not in first.value:
            continue
        checked += 1
        assert first.value.count("%s") == len(node.args) - 1
    assert checked == 1, "a linha de log do comando remoto sumiu ou duplicou"


def test_new_phases_reach_the_log_line():
    for field in ("precheck_motor=%sms", "handle_command=%sms", "arme_confirmacao=%sms", "progresso=%sms"):
        assert field in SERVER, field


def test_version_follows_the_release():
    assert 'ENGINE_VERSION = "1.12.77"' in ENGINE
    assert 'CONNECTOR_VERSION = "1.12.77"' in CONNECTOR
