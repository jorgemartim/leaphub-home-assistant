from __future__ import annotations

import importlib.util
import io
import sqlite3
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
TARGET = "1.12.118"


def test_release_versions_and_dependency_pins() -> None:
    requirements = (APP / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "cryptography==50.0.0" in requirements
    assert "Pillow==12.3.0" in requirements
    assert (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip() == TARGET
    config = (APP / "config.yaml").read_text(encoding="utf-8")
    assert ('version: "1.12.117"' in config) != ('version: "1.12.118"' in config)

    expected = {
        "connector.py": f'CONNECTOR_VERSION = "{TARGET}"',
        "connector_server.py": f'VERSION = "{TARGET}"',
        "gateway_manager.py": f'VERSION = "{TARGET}"',
        "ocpp_gateway.py": f'GATEWAY_VERSION = "{TARGET}"',
        "official_trip_probe.py": f'PROBE_VERSION = "{TARGET}"',
        "privacy.py": f'PRIVACY_VERSION = "{TARGET}"',
        "telemetry_engine.py": f'ENGINE_VERSION = "{TARGET}"',
    }
    for filename, marker in expected.items():
        assert marker in (APP / filename).read_text(encoding="utf-8"), filename
    assert f'PROBE_VERSION == "{TARGET}"' in (APP / "Dockerfile").read_text(encoding="utf-8")
    connector_server = (APP / "connector_server.py").read_text(encoding="utf-8")
    assert "factory=ClosingSQLiteConnection" in connector_server
    assert "with closing(sqlite3.connect" in (APP / "gateway_manager.py").read_text(encoding="utf-8")


def test_cryptography_fernet_contract() -> None:
    fernet = Fernet(Fernet.generate_key())
    payload = b"leaphub-1.12.118-synthetic"
    assert fernet.decrypt(fernet.encrypt(payload)) == payload


def test_pillow_c10_render_contract() -> None:
    base = Image.new("RGBA", (32, 16), (0, 0, 0, 0))
    layer = Image.new("RGBA", base.size, (20, 40, 60, 128))
    composed = Image.alpha_composite(base, layer)
    composed.thumbnail((16, 16), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    composed.save(output, format="PNG")
    with Image.open(io.BytesIO(output.getvalue())) as decoded:
        assert decoded.format == "PNG"
        assert decoded.size == (16, 8)


def test_ocpp_context_closes_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEAPHUB_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("LEAPHUB_OCPP_STATE_DB", str(tmp_path / "state.sqlite"))
    sys.path.insert(0, str(APP))
    module_name = "ocpp_gateway_1_12_118_close_contract"
    spec = importlib.util.spec_from_file_location(module_name, APP / "ocpp_gateway.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    with module.state_db() as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
