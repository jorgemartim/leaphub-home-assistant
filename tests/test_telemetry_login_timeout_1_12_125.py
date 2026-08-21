from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))

import connector  # noqa: E402


class FakeLeapmotorApiClient:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))


def _install_fake_client(monkeypatch) -> None:
    fake_module = types.ModuleType("leapmotor_api")
    fake_module.LeapmotorApiClient = FakeLeapmotorApiClient
    monkeypatch.setitem(sys.modules, "leapmotor_api", fake_module)
    monkeypatch.setattr(connector, "validate_pem", lambda value, _labels, _label: value)
    monkeypatch.setattr(connector, "write_secret", lambda _path, _content: None)
    FakeLeapmotorApiClient.calls.clear()


def _credentials() -> dict[str, str]:
    return {
        "email": "owner@example.invalid",
        "password": "test-only-password",
        "certificate_pem": "test-certificate",
        "private_key_pem": "test-private-key",
    }


def test_automatic_telemetry_client_honors_four_second_ceiling(monkeypatch, tmp_path: Path) -> None:
    _install_fake_client(monkeypatch)

    connector.create_client(_credentials(), tmp_path, request_timeout_seconds=4)

    assert len(FakeLeapmotorApiClient.calls) == 1
    assert FakeLeapmotorApiClient.calls[0]["timeout"] == 4


def test_manual_command_client_keeps_larger_timeout(monkeypatch, tmp_path: Path) -> None:
    _install_fake_client(monkeypatch)

    connector.create_client(_credentials(), tmp_path, request_timeout_seconds=15)

    assert len(FakeLeapmotorApiClient.calls) == 1
    assert FakeLeapmotorApiClient.calls[0]["timeout"] == 15
