"""Contrato 1.12.55 — `engine_precheck_ms` precisa ser quebrável e ter teto.

Um comando de campo mediu `precheck_motor=135718ms` com todas as demais fases
somando ~5s (`dispatch=4199ms`, `handle_command=5219ms`, `nao_atribuido=1ms`).
A 1.12.54 nomeou o balde; ele cobre tres coisas distintas e a aquisicao da trava
global do motor era a unica do arquivo sem limite de espera. Sem quebrar e sem
teto, a proxima investigacao vira palpite outra vez e o dono continua olhando a
tela por dois minutos.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"

ENGINE = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
CONNECTOR = (APP / "connector.py").read_text(encoding="utf-8")
SERVER = (APP / "connector_server.py").read_text(encoding="utf-8")

SUBPHASES = ("auth_status_ms", "engine_lock_wait_ms", "subscription_read_ms")


def execute_command_body() -> str:
    """Corpo de `execute_command`, onde a janela do precheck vive."""
    tree = ast.parse(ENGINE)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "execute_command":
            return ast.get_source_segment(ENGINE, node) or ""
    raise AssertionError("execute_command desapareceu do motor")


def test_engine_publishes_the_three_subphases():
    for field in SUBPHASES:
        assert f'phase["{field}"] = {field}' in ENGINE, field


def test_auth_status_is_measured_before_the_lock():
    """Se o status vier depois, a fase mede menos do que existe."""
    started = ENGINE.index("engine_started = time.monotonic()")
    auth = ENGINE.index("auth_status_ms = int(round((time.monotonic() - engine_started) * 1000))")
    lock = ENGINE.index("engine_lock_started = time.monotonic()")
    assert started < auth < lock


def test_engine_lock_acquisition_is_bounded():
    """O defeito de campo: `with self.lock` sem timeout no caminho do comando."""
    body = execute_command_body()
    assert "with self.lock" not in body, "a aquisicao voltou a ser sem teto"
    assert "self.lock.acquire(timeout=ENGINE_LOCK_COMMAND_TIMEOUT_SECONDS)" in body


def test_engine_lock_is_released_even_on_failure():
    """Perder a trava trava o motor inteiro para sempre."""
    body = execute_command_body()
    assert "finally:\n            self.lock.release()" in body


def test_timeout_constant_is_sane():
    match = re.search(r"^ENGINE_LOCK_COMMAND_TIMEOUT_SECONDS = ([0-9.]+)$", ENGINE, re.MULTILINE)
    assert match, "constante do teto ausente"
    # Curto o bastante para o dono nao esperar, longo o bastante para nao
    # recusar comando por contencao normal de SQLite.
    assert 5.0 <= float(match.group(1)) <= 30.0


def test_timeout_failure_is_temporary_and_did_not_reach_the_vehicle():
    """503 + temporary faz o site manter na fila; o dispatch vem bem depois."""
    body = execute_command_body()
    assert "raise connector.ConnectorTemporaryError(" in body
    assert "O comando não foi enviado ao veículo e continua na fila." in body
    # O tipo precisa continuar mapeado para 503 temporario no servidor.
    assert "except connector.ConnectorTemporaryError as exc:" in SERVER
    temporary_branch = SERVER[SERVER.index("except connector.ConnectorTemporaryError as exc:"):]
    temporary_branch = temporary_branch[: temporary_branch.index("except connector.ConnectorAuthenticationError")]
    assert "self.send_json(503, {" in temporary_branch
    assert '"temporary": True,' in temporary_branch


def test_subphases_reach_the_server_latency():
    for field in SUBPHASES:
        assert f'"{field}": int(phase_latency.get("{field}") or 0),' in SERVER, field


def test_subphases_do_not_double_count_in_unaccounted():
    """As tres vivem DENTRO de engine_precheck_ms."""
    unaccounted = SERVER[SERVER.index('"unaccounted_ms": max(0,'):]
    unaccounted = unaccounted[: unaccounted.index("))")]
    for field in SUBPHASES:
        assert field not in unaccounted, field


def test_subphases_reach_the_log_line():
    for label in ("status_conta=%sms", "trava_motor=%sms", "leitura_assinatura=%sms"):
        assert label in SERVER, label


def test_log_line_placeholders_match_its_arguments():
    """Um %s a mais derruba o log do comando em producao."""
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


def test_version_follows_the_release():
    assert 'ENGINE_VERSION = "1.12.70"' in ENGINE
    assert 'CONNECTOR_VERSION = "1.12.70"' in CONNECTOR
