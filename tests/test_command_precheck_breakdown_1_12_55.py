# Contract updated by Gateway 1.12.86.
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_RELEASE_TARGET = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
APP = ROOT / "leaphub_gateway"

ENGINE = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
CONNECTOR = (APP / "connector.py").read_text(encoding="utf-8")
SERVER = (APP / "connector_server.py").read_text(encoding="utf-8")

SUBPHASES = ("auth_status_ms", "engine_lock_wait_ms", "subscription_read_ms")


def execute_command_body() -> str:
    tree = ast.parse(ENGINE)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "execute_command":
            return ast.get_source_segment(ENGINE, node) or ""
    raise AssertionError("execute_command desapareceu do motor")


def test_engine_publishes_the_three_subphases():
    for field in SUBPHASES:
        assert f'phase["{field}"] = {field}' in ENGINE, field


def test_auth_status_is_measured_before_subscription_read():
    started = ENGINE.index("engine_started = time.monotonic()")
    auth = ENGINE.index("auth_status_ms = int(round((time.monotonic() - engine_started) * 1000))")
    read_started = ENGINE.index("subscription_read_started = time.monotonic()", auth)
    assert started < auth < read_started


def test_command_subscription_lookup_is_lock_free():
    body = execute_command_body()
    start = body.index("subscription_read_started = time.monotonic()")
    end = body.index("if row is None:", start)
    lookup = body[start:end]
    assert "with self._db() as db:" in lookup
    assert "self.lock.acquire" not in lookup
    assert "self.lock.release" not in lookup
    assert "with self.lock" not in lookup


def test_engine_lock_metric_is_retained_as_zero():
    body = execute_command_body()
    assert "engine_lock_wait_ms = 0" in body
    assert 'phase["engine_lock_wait_ms"] = engine_lock_wait_ms' in body


def test_historical_timeout_constant_remains_sane_for_compatibility():
    match = re.search(r"^ENGINE_LOCK_COMMAND_TIMEOUT_SECONDS = ([0-9.]+)$", ENGINE, re.MULTILINE)
    assert match
    assert 5.0 <= float(match.group(1)) <= 30.0


def test_subphases_reach_the_server_latency():
    for field in SUBPHASES:
        assert f'"{field}": int(phase_latency.get("{field}") or 0),' in SERVER, field


def test_subphases_do_not_double_count_in_unaccounted():
    unaccounted = SERVER[SERVER.index('"unaccounted_ms": max(0,'):]
    unaccounted = unaccounted[: unaccounted.index("))")]
    for field in SUBPHASES:
        assert field not in unaccounted, field


def test_subphases_reach_the_log_line():
    for label in ("status_conta=%sms", "trava_motor=%sms", "leitura_assinatura=%sms"):
        assert label in SERVER, label


def test_log_line_placeholders_match_its_arguments():
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
    assert checked == 1


def test_version_follows_the_release():
    assert f'ENGINE_VERSION = "{_RELEASE_TARGET}"' in ENGINE
    assert f'CONNECTOR_VERSION = "{_RELEASE_TARGET}"' in CONNECTOR
