from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
TELEMETRY = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")


def test_current_version_and_existing_priority_are_preserved() -> None:
    assert 'VERSION = "1.12.36"' in SERVER
    assert 'CONNECTOR_VERSION = "1.12.36"' in CONNECTOR
    assert 'ENGINE_VERSION = "1.12.36"' in TELEMETRY
    assert "manual_operation_enter(environment, payload)" in SERVER
    assert "manual_pending_provider=manual_operation_pending" in SERVER


def test_telemetry_passes_live_manual_priority_callback_into_vehicle_serialization() -> None:
    assert "manual_should_yield=manual_should_yield" in TELEMETRY
    start = CONNECTOR.index("def serialize_vehicle(")
    end = CONNECTOR.index("\ndef create_client", start)
    block = CONNECTOR[start:end]
    assert "manual_should_yield: Callable[[], bool] | None = None" in block
    assert "defer_secondary_network" in block
    assert "Telemetria adiou imagem oficial" in block


def test_picture_refresh_yields_between_network_calls() -> None:
    start = CONNECTOR.index("def _official_picture_package(")
    end = CONNECTOR.index("\ndef _official_render_cache_key", start)
    block = CONNECTOR[start:end]
    assert "manual_should_yield" in block
    assert "if manual_pending:" in block
    assert "should_refresh = False" in block
    metadata = block.index("metadata = client.get_car_picture(vehicle)")
    recheck = block.index("manual_pending = bool(manual_should_yield and manual_should_yield())", metadata)
    download = block.index("client.download_car_picture_package", recheck)
    assert metadata < recheck < download


def test_no_new_physical_retry_was_added() -> None:
    assert "safe_retry_performed" in SERVER
    # A mudança de 1.12.36 é de scheduling/telemetria, não de repetição do comando.
    new_block = CONNECTOR[CONNECTOR.index("# 1.12.28 — o status do veículo"):]
    assert "execute_command(" not in new_block[:2200]
