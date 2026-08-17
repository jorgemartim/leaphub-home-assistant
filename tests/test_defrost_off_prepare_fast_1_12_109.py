"""Gateway 1.12.109 — OFF parametrizado, Prepare FAST e matriz preservada."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if "leaphub_connector" not in sys.modules:
    connector = load_module("leaphub_connector", APP / "connector.py")
else:
    connector = sys.modules["leaphub_connector"]
telemetry = load_module("leaphub_telemetry_1_12_109", APP / "telemetry_engine.py")


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


CREDENTIALS = {
    "email": "dono@example.invalid",
    "password": "segredo",
    "certificate_pem": "cert",
    "private_key_pem": "key",
}


class Harness:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="leaphub-109-")
        os.environ["LEAPHUB_TELEMETRY_DIR"] = self.tmp.name
        self.engine = telemetry.TelemetryEngine(
            {
                "telemetry_beta_enabled": True,
                "telemetry_beta_internal_url": "https://example.invalid/telemetry",
                "telemetry_background_enabled": True,
            },
            {"staging": "s" * 32, "production": "p" * 32},
            threading.BoundedSemaphore(2),
        )

    def subscribe(self, sid: str = "sub-109") -> str:
        result = self.engine.upsert(
            "staging",
            {
                "subscription_id": sid,
                "account_id": 1,
                "credentials": dict(CREDENTIALS),
                "vehicle_ids": ["V1"],
                "enabled": True,
            },
        )
        assert result["ok"] is True
        return sid

    def rows(self, sid: str):
        with self.engine.lock, self.engine._db() as db:
            return list(
                db.execute(
                    "SELECT * FROM command_confirmations WHERE subscription_id=? ORDER BY started_at",
                    (sid,),
                ).fetchall()
            )

    def close(self) -> None:
        self.engine.close_storage()
        handle = getattr(self.engine, "_instance_lock_handle", None)
        if handle is not None:
            handle.close()
        try:
            self.tmp.cleanup()
        except (OSError, PermissionError):
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_versions_and_global_guardrails() -> None:
    assert version_tuple(connector.CONNECTOR_VERSION) >= (1, 12, 109)
    assert version_tuple(telemetry.ENGINE_VERSION) >= (1, 12, 109)
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert "windshield_defrost" not in connector.ACK_FIRST_COMMANDS
    assert tuple(telemetry.TelemetryEngine.COMMAND_POST_DISPATCH_EARLY_CADENCE) == (5, 5, 8)
    assert tuple(telemetry.TelemetryEngine.COMMAND_TRANSIENT_BACKOFF) == (8, 15, 25, 40, 60, 90)


def test_public_command_matrix_is_exactly_preserved() -> None:
    assert len(connector.COMMAND_METHODS) == 40
    assert len(connector.EXPERIMENTAL_COMMAND_METHODS) == 12
    assert len(connector.ALL_COMMAND_METHODS) == 52
    assert connector.COMMAND_METHODS["windshield_defrost"] == "windshield_defrost"
    assert connector.COMMAND_REQUIRED_RIGHT["windshield_defrost"] == 460
    assert "windshield_defrost_off" not in connector.ALL_COMMAND_METHODS
    assert "windshield_defrost_off" not in connector.COMMAND_REQUIRED_RIGHT


def test_defrost_off_changes_only_wshld_and_uses_same_public_command() -> None:
    on = connector.windshield_defrost_parameters()
    off = connector.windshield_defrost_off_parameters()
    assert on["wshld"] == "2"
    assert off["wshld"] == "0"
    assert {k: v for k, v in on.items() if k != "wshld"} == {
        k: v for k, v in off.items() if k != "wshld"
    }
    calls = []

    def method(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True}

    connector.execute_vehicle_command(method, "windshield_defrost", "VIN", {})
    connector.execute_vehicle_command(method, "windshield_defrost", "VIN", {"enabled": False})
    assert calls[0] == (("VIN",), {"params": on})
    assert calls[1] == (("VIN",), {"params": off})


def test_defrost_enabled_parameter_is_strict_and_legacy_defaults_to_on() -> None:
    assert connector.windshield_defrost_enabled({}) is True
    assert connector.windshield_defrost_enabled({"enabled": True}) is True
    assert connector.windshield_defrost_enabled({"enabled": False}) is False
    for invalid in (0, 1, "false", "true", None):
        try:
            connector.windshield_defrost_enabled({"enabled": invalid})
        except ValueError:
            pass
        else:
            raise AssertionError(f"enabled invalido foi aceito: {invalid!r}")


def test_defrost_telemetry_matcher_uses_context_parameter() -> None:
    with Harness() as h:
        active = {"climate_details": {"windshield_defrost": True}}
        inactive = {"climate_details": {"windshield_defrost": False}}
        assert h.engine._command_confirmation(
            "windshield_defrost", active, {"parameters": {"enabled": True}}
        ) == (True, True)
        assert h.engine._command_confirmation(
            "windshield_defrost", inactive, {"parameters": {"enabled": False}}
        ) == (True, True)
        assert h.engine._command_confirmation(
            "windshield_defrost", active, {"parameters": {}}
        ) == (True, True)


def test_defrost_new_request_supersedes_previous_direction_same_command_key() -> None:
    with Harness() as h:
        sid = h.subscribe()
        on = h.engine.boost(
            sid, 180, "command",
            {
                "command_key": "windshield_defrost",
                "vehicle_remote_id": "V1",
                "request_id": "req-defrost-on-109",
                "parameters": {"enabled": True},
            },
        )
        off = h.engine.boost(
            sid, 180, "command",
            {
                "command_key": "windshield_defrost",
                "vehicle_remote_id": "V1",
                "request_id": "req-defrost-off-109",
                "parameters": {"enabled": False},
            },
        )
        assert on["ok"] is True and off["ok"] is True
        status = {str(r["request_id"]): str(r["status"]) for r in h.rows(sid)}
        assert status["req-defrost-on-109"] == "superseded"
        assert status["req-defrost-off-109"] == "pending"


def test_repeated_same_defrost_request_reuses_wait() -> None:
    with Harness() as h:
        sid = h.subscribe("same-req")
        context = {
            "command_key": "windshield_defrost",
            "vehicle_remote_id": "V1",
            "request_id": "req-same-109",
            "parameters": {"enabled": False},
        }
        first = h.engine.boost(sid, 180, "command", context)
        second = h.engine.boost(sid, 180, "command", context)
        assert first["ok"] is True
        assert second["confirmation_window_reused"] is True
        pending = [r for r in h.rows(sid) if str(r["status"]) == "pending"]
        assert len(pending) == 1


def prepare_context(mode: str, temperature: float, fan: int) -> dict[str, object]:
    return {
        "parameters": {
            "climate": True,
            "climate_mode": mode,
            "temperature": temperature,
            "wind_level": fan,
        }
    }


def sample(mode: int, operate_mode: int, temperature: float, fan: int) -> dict[str, object]:
    return {
        "climate_on": True,
        "climate_details": {
            "mode": mode,
            "operate_mode": operate_mode,
            "left_temperature_c": temperature,
            "right_temperature_c": temperature,
            "fan_level": fan,
            "windshield_defrost": False,
        },
    }


def test_prepare_fast_auto_cooling_heating() -> None:
    with Harness() as h:
        assert h.engine._command_confirmation(
            "prepare_car", sample(0, 1, 24, 3), prepare_context("auto", 24, 3)
        ) == (True, True)
        assert h.engine._command_confirmation(
            "prepare_car", sample(1, 0, 18, 7), prepare_context("cold", 18, 7)
        ) == (True, True)
        assert h.engine._command_confirmation(
            "prepare_car", sample(3, 0, 32, 7), prepare_context("hot", 32, 7)
        ) == (True, True)


def test_prepare_mismatch_and_missing_fields_are_safe() -> None:
    with Harness() as h:
        assert h.engine._command_confirmation(
            "prepare_car", sample(1, 0, 18, 5), prepare_context("cold", 18, 7)
        ) == (False, True)
        missing = sample(0, 1, 24, 3)
        details = dict(missing["climate_details"])
        details.pop("left_temperature_c")
        details.pop("right_temperature_c")
        missing["climate_details"] = details
        assert h.engine._command_confirmation(
            "prepare_car", missing, prepare_context("auto", 24, 3)
        ) == (False, False)


def test_prepare_stays_experimental_but_is_fast_confirmable() -> None:
    assert connector.EXPERIMENTAL_COMMAND_METHODS["prepare_car"] == "prepare_car"
    assert "prepare_car" not in connector.COMMAND_METHODS
    assert "prepare_car" in telemetry.TELEMETRY_CONFIRMABLE_COMMANDS
    assert "prepare_car" in telemetry.CONFIRMATION_SUPERSESSION_FAMILIES["climate"]
    assert telemetry.TelemetryEngine.COMMAND_CONFIRMATION_FIELDS["prepare_car"] == (
        "climate_on", "climate_details",
    )


def test_pending_arm_uses_boost_without_standalone_supersede() -> None:
    with Harness() as h:
        supersede_calls = []
        boost_calls = []

        def forbidden_supersede(*_args, **_kwargs):
            supersede_calls.append(True)
            raise AssertionError("pending path must not supersede twice")

        def fake_boost(subscription_id, seconds, profile, context):
            boost_calls.append((subscription_id, seconds, profile, context))
            return {"ok": True, "confirmation_window_reused": False}

        h.engine._supersede_pending_confirmations = forbidden_supersede
        h.engine.boost = fake_boost
        result = {"command_dispatched": True, "cloud_accepted": True, "confirmation_pending": True}
        h.engine._arm_command_confirmation(
            "sub-109",
            {
                "command": "prepare_car",
                "vehicle_id": "V1",
                "request_id": "req-109",
                "parameters": {"climate_mode": "auto", "temperature": 24, "wind_level": 3},
            },
            result,
        )
        assert supersede_calls == []
        assert len(boost_calls) == 1
        assert result["confirmation_armed_by_gateway"] is True


def test_direct_completed_command_keeps_supersession_without_boost() -> None:
    with Harness() as h:
        supersede_calls = []
        boost_calls = []

        def fake_supersede(*_args, **_kwargs):
            supersede_calls.append(True)
            return 0

        def forbidden_boost(*_args, **_kwargs):
            boost_calls.append(True)
            raise AssertionError("direct completed command must not open a new window")

        h.engine._supersede_pending_confirmations = fake_supersede
        h.engine.boost = forbidden_boost
        result = {"command_dispatched": True, "cloud_accepted": True, "confirmation_pending": False}
        h.engine._arm_command_confirmation(
            "sub-direct",
            {"command": "quick_heat", "vehicle_id": "V1", "request_id": "req-direct", "parameters": {}},
            result,
        )
        assert len(supersede_calls) == 1
        assert boost_calls == []
        assert result["confirmation_armed_by_gateway"] is False
