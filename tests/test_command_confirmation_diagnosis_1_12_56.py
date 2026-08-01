"""Contrato 1.12.56 — falha de confirmação precisa dizer por quê.

O comando executa (o carro destrava), mas o dono vê "A ação foi enviada, mas o
novo estado não foi confirmado dentro da janela segura". O log dizia apenas
"sem confirmação conclusiva", sem distinguir três causas muito diferentes: o
veículo-alvo não apareceu, as amostras vieram velhas demais, ou o campo que o
matcher consulta não veio na telemetria.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"

ENGINE = (APP / "telemetry_engine.py").read_text(encoding="utf-8")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# `telemetry_engine` importa o conector por este nome exato. Registrar sob outro
# nome faria o teste passar só quando outro módulo o tivesse carregado antes.
if "leaphub_connector" not in sys.modules:
    load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_diag", APP / "telemetry_engine.py")


class _Gaps:
    """Só o mapa e o classificador; nenhum estado de motor é necessário."""

    COMMAND_CONFIRMATION_FIELDS = telemetry.TelemetryEngine.COMMAND_CONFIRMATION_FIELDS
    _command_confirmation_gaps = telemetry.TelemetryEngine._command_confirmation_gaps


def matcher_commands() -> set[str]:
    """Comandos tratados dentro de `_command_confirmation`, lidos da fonte."""
    start = ENGINE.index("    def _command_confirmation(\n")
    body = ENGINE[start:]
    body = body[: body.index("\n    def ", 10)]
    found: set[str] = set()
    for group in re.findall(r"if command in \{([^}]+)\}", body):
        found.update(re.findall(r'"([a-z_]+)"', group))
    found.update(re.findall(r'if command == "([a-z_]+)"', body))
    return found


def test_map_covers_every_command_the_matcher_handles():
    """Anti-deriva: um comando novo no matcher sem entrada aqui volta a ser cego."""
    missing = matcher_commands() - set(_Gaps.COMMAND_CONFIRMATION_FIELDS)
    assert not missing, f"comandos sem campos declarados: {sorted(missing)}"


def test_map_has_no_entries_the_matcher_ignores():
    extra = set(_Gaps.COMMAND_CONFIRMATION_FIELDS) - matcher_commands()
    assert not extra, f"campos declarados para comandos inexistentes: {sorted(extra)}"


def test_absent_field_is_reported_as_absent():
    """O caso de campo: unlock com `locked` fora da telemetria."""
    assert _Gaps()._command_confirmation_gaps("unlock", {"speed": 0}) == ["locked=ausente"]


def test_null_field_is_distinguished_from_absent():
    """`is_locked` exposto porém nulo é um defeito diferente de nao existir."""
    assert _Gaps()._command_confirmation_gaps("unlock", {"locked": None}) == ["locked=nulo"]


def test_present_field_produces_no_gap():
    assert _Gaps()._command_confirmation_gaps("unlock", {"locked": True}) == []
    assert _Gaps()._command_confirmation_gaps("lock", {"locked": False}) == []


def test_nested_and_empty_containers():
    assert _Gaps()._command_confirmation_gaps("trunk_open", {"doors": {}}) == ["doors.trunk=ausente"]
    assert _Gaps()._command_confirmation_gaps("trunk_open", {"doors": {"trunk": True}}) == []
    # `windows` vazio é exatamente o que torna windows_open inconclusivo.
    assert _Gaps()._command_confirmation_gaps("windows_open", {"windows": {}}) == ["windows=vazio"]


def test_unknown_command_reports_nothing_instead_of_raising():
    assert _Gaps()._command_confirmation_gaps("localizar", {}) == []


def test_three_causes_are_counted_separately():
    # 1.12.62 — os contadores perderam o prefixo `command_` ao saírem do corpo do
    # ciclo para `_evaluate_confirmation()`, que julga uma espera por vez. A
    # garantia é a mesma: as três causas de "sem confirmação conclusiva" seguem
    # contadas em separado, senão o diagnóstico volta a ser palpite.
    for counter in ("stale_samples", "evaluated_samples", "field_gaps"):
        assert f"{counter} = " in ENGINE, counter
    assert "stale_samples += 1" in ENGINE
    assert "evaluated_samples += 1" in ENGINE
    # E continuam saindo juntos no mesmo veredito, um por comando pendente.
    for chave in ('"stale_samples":', '"evaluated_samples":', '"field_gaps":'):
        assert chave in ENGINE, chave


def test_diagnosis_is_logged_when_the_window_is_exhausted():
    assert "Confirmação inconclusiva de %s em %s: amostras avaliadas=%s, descartadas por idade=%s, " in ENGINE
    assert "campos exigidos sem valor=[%s], chaves presentes na telemetria=[%s]." in ENGINE


def test_diagnosis_never_logs_telemetry_values():
    """A mesma leitura carrega localização e identificadores do veículo."""
    start = ENGINE.index("Confirmação inconclusiva de %s em %s")
    call = ENGINE[start:]
    call = call[: call.index("            )")]
    # Só nomes de chave e contadores podem sair; nunca o dicionário nem valores.
    assert "telemetry)" not in call
    assert "telemetry," not in call
    assert "telemetry.values()" not in call
    assert "sorted(str(key) for key in telemetry.keys())[:40]" in ENGINE


def test_version_follows_the_release():
    assert 'ENGINE_VERSION = "1.12.67"' in ENGINE
    assert 'CONNECTOR_VERSION = "1.12.67"' in (APP / "connector.py").read_text(encoding="utf-8")
