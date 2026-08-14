from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

connector = (
    ROOT / "leaphub_gateway" / "connector.py"
).read_text(encoding="utf-8")

server = (
    ROOT / "leaphub_gateway" / "connector_server.py"
).read_text(encoding="utf-8")

telemetry = (
    ROOT / "leaphub_gateway" / "telemetry_engine.py"
).read_text(encoding="utf-8")

target = (
    ROOT / "leaphub_gateway" / "RELEASE_TARGET"
).read_text(encoding="utf-8").strip()


def test_gateway_1_12_87_restores_known_good_runtime():
    assert target == "1.12.87"

    assert 'CONNECTOR_VERSION = "1.12.87"' in connector
    assert 'ENGINE_VERSION = "1.12.87"' in telemetry

    # Caminho conhecido da 1.12.84.
    assert "TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in telemetry
    assert "allow_slow_network=not (interactive or command_mode)" in telemetry
    assert "include_secondary_network=False" in telemetry

    # Confirmacao nao bloqueia a intencao mais nova.
    assert "self._supersede_pending_confirmations(" in telemetry

    # Resultado do comando continua sendo anunciado imediatamente.
    assert "announce_command_result_async(" in server

    # C10 OFF permanece exatamente no contrato homologado.
    assert 'return method(vehicle_id, params={"operate": "off"})' in connector

    # Retry protegido.
    assert "repeat_exact_state_command" in connector
    assert "command_attempts < 2" in connector

    # Experimentos posteriores nao podem voltar escondidos.
    assert "_TelemetryOneShotClient" not in telemetry
    assert "TELEMETRY_SESSION_LOCK_WAIT_CEILING_SECONDS" not in telemetry
