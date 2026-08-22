from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "leaphub_gateway" / "gateway_manager.py"
PT_BR = ROOT / "leaphub_gateway" / "translations" / "pt-BR.yaml"


def test_dashboard_version_is_dynamic_and_configuration_is_sanitized() -> None:
    source = MANAGER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "configuration_profile")
    body = ast.get_source_segment(source, function) or ""

    assert 'v__VERSION__' in source
    assert '.replace("__VERSION__", VERSION)' in source
    assert '"configuration": configuration_profile()' in source
    assert "staging_secret" not in body
    assert "production_secret" not in body
    assert "ocpp_beta_secret" not in body
    assert "tunnel_token" not in body
    assert '"telemetry_request_timeout_seconds": (15' in body
    assert '"telemetry_command_max_polls": (5' in body


def test_advanced_options_have_owner_facing_portuguese_labels() -> None:
    translation = PT_BR.read_text(encoding="utf-8")
    for key in (
        "connector_manual_settle_seconds",
        "telemetry_interactive_seconds",
        "telemetry_command_seconds",
        "telemetry_command_max_polls",
        "telemetry_request_timeout_seconds",
        "telemetry_poll_workers",
        "ocpp_ping_interval_seconds",
        "ocpp_liveness_timeout_seconds",
        "tunnel_protocol",
    ):
        assert f"  {key}:\n" in translation
