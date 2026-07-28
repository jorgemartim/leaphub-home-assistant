from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANAGER = (ROOT / "leaphub_gateway" / "gateway_manager.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8")
TARGET = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()


def test_staged_release_metadata():
    assert any(v in CONFIG for v in ('version: \"1.12.47\"', 'version: \"1.12.49\"'))
    assert TARGET == "1.12.49"
    assert 'VERSION = "1.12.49"' in MANAGER


def test_tunnel_starts_after_local_origin_gate():
    assert "def wait_for_local_origins" in MANAGER
    origin_start = MANAGER.index('if name != "tunnel":\n        service.start()')
    readiness = MANAGER.index("origin_readiness = wait_for_local_origins")
    tunnel_start = MANAGER.index('SERVICES["tunnel"].start()')
    assert origin_start < readiness < tunnel_start


def test_planned_shutdown_closes_tunnel_first():
    shutdown = MANAGER[MANAGER.index("def shutdown"):MANAGER.index("for signal_name")]
    assert '("tunnel", "ocpp_wallbox", "connector")' in shutdown
