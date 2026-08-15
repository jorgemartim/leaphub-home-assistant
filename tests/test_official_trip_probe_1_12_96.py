from __future__ import annotations

import importlib.util
import io
import json
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))
import official_trip_probe as probe  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if "leaphub_connector" not in sys.modules:
    connector = load_module("leaphub_connector", APP / "connector.py")
else:
    connector = sys.modules["leaphub_connector"]
telemetry = load_module("leaphub_telemetry_probe_1_12_96", APP / "telemetry_engine.py")


class _Headers:
    def to_dict(self):
        return {"signed": "yes"}


class FakeClient:
    sign_key = b"sign-key"
    device_id = "device-123"
    language = "en-GB"
    account_cert = ("cert.pem", "key.pem")
    timeout = 30

    def __init__(self, *, fail_secret: str = ""):
        self.posts = []
        self.last_api_results = {}
        self.fail_secret = fail_secret

    def _auth_headers(self):
        return {"Authorization": "Bearer SECRET-TOKEN"}

    def _post(self, **kwargs):
        self.posts.append(kwargs)
        if self.fail_secret:
            raise RuntimeError(self.fail_secret)
        return {"status_code": 200, "body": '{"code":0,"message":"ok","data":{"totalEnergy":123.456}}'}

    def _parse_api_body(self, status_code, body, label):
        assert status_code == 200 and label == probe.PARSE_LABEL
        self.last_api_results[label] = {"message": "SECRET-CLOUD-MESSAGE"}
        return {
            "data": {
                "totalEnergy": 123.456,
                "mileage": 78.9,
                "reference": "SECRET-TRIP-REFERENCE",
                "items": [{"value": 42}],
            }
        }


class FakeLimiter:
    def __init__(self, on_acquire=None):
        self.active = 0
        self.on_acquire = on_acquire

    def acquire(self, blocking=True, timeout=-1, priority=False):
        self.active += 1
        if self.on_acquire:
            self.on_acquire()
        return True

    def release(self):
        assert self.active > 0
        self.active -= 1


class FakeAccountLock:
    def __init__(self, on_acquire=None):
        self.lock = threading.Lock()
        self.on_acquire = on_acquire

    def acquire(self, blocking=True, timeout=-1):
        acquired = self.lock.acquire(blocking, timeout)
        if acquired and self.on_acquire:
            self.on_acquire()
        return acquired

    def release(self):
        self.lock.release()


CREDS = {"email": "owner@example.invalid", "password": "secret", "certificate_pem": "cert", "private_key_pem": "key"}
BEGIN = 1_765_000_000_000
END = BEGIN + 3_600_000


def close_engine(engine) -> None:
    engine.close_storage()
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()


def make_engine(tmp: str, *, manual_state=None, limiter=None, account_lock=None):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = tmp
    manual_state = manual_state if manual_state is not None else {"pending": False}
    limiter = limiter or FakeLimiter()
    account_lock = account_lock or FakeAccountLock()
    engine = telemetry.TelemetryEngine(
        {}, {"staging": "s" * 32, "production": "p" * 32}, limiter,
        account_lock_provider=lambda _env, _payload: account_lock,
        manual_pending_provider=lambda _env, _payload: bool(manual_state["pending"]),
        manual_active_provider=lambda _env, _payload: bool(manual_state["pending"]),
    )
    return engine, limiter, account_lock, manual_state


def add_subscription(engine, sid: str, remote_ids: list[str]):
    result = engine.upsert("staging", {
        "subscription_id": sid,
        "account_id": 1,
        "credentials": dict(CREDS),
        "vehicle_ids": remote_ids,
        "enabled": True,
    })
    assert result["subscription_id"] == sid


def inject_session(engine, sid: str, client, vehicles):
    with engine.session_lock:
        engine.sessions[sid] = {
            "client": client,
            "vehicles": list(vehicles),
            "vehicles_cached_at": time.time(),
            "last_used_at": time.time(),
            "created_at": time.time(),
        }


def vehicle(remote_id: str, vin: str):
    return SimpleNamespace(car_id=remote_id, vin=vin)


def test_window_signature_single_post_size_and_redaction(monkeypatch):
    signed = {}
    def fake_builder(**kwargs):
        signed.update(kwargs)
        return _Headers()
    monkeypatch.setattr(probe, "build_signed_headers", fake_builder)
    client = FakeClient()
    vin = "LPS12345678901234"
    result = probe.probe_windowed_mileage_energy(client, vin=vin, begin_ms=BEGIN, end_ms=END)
    assert signed["body_params"] == {"begintime": str(BEGIN), "endtime": str(END)}
    assert signed["vin"] == vin
    assert len(client.posts) == 1 and client.posts[0]["path"] == probe.WINDOW_PATH
    encoded = json.dumps(result, ensure_ascii=False)
    for secret in ("123.456", "78.9", "SECRET-TRIP-REFERENCE", vin, "SECRET-TOKEN", "SECRET-CLOUD-MESSAGE"):
        assert secret not in encoded
    assert result["response_body_bytes"] > 0
    assert result["response_shape_nodes"] > 0
    assert result["response_shape"]["data"]["totalEnergy"] == "number"
    assert result["mapped_fields"] == [] and result["raw_values_included"] is False
    assert probe.PARSE_LABEL not in client.last_api_results


def test_shape_redacts_opaque_dynamic_keys():
    vin = "LPS12345678901234"
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    opaque = "ref_0123456789abcdef"
    long_hex = "aabbccddeeff00112233445566778899"
    shape = probe.describe_shape({"data": {vin: 1, uuid: 2, opaque: 3, long_hex: 4, "trip20260815112233": 5, "totalEnergy": 6}})
    encoded = json.dumps(shape, ensure_ascii=False)
    for secret in (vin, uuid, opaque, long_hex, "trip20260815112233"):
        assert secret not in encoded
    assert "totalEnergy" in encoded and "<dynamic-key>" in encoded


def test_window_milliseconds_order_and_bound():
    with pytest.raises(ValueError, match="milissegundos"):
        probe.normalize_window({"begintime": 1_765_000_000, "endtime": 1_765_003_600})
    with pytest.raises(ValueError, match="posterior"):
        probe.normalize_window({"begintime_ms": BEGIN, "endtime_ms": BEGIN})
    with pytest.raises(ValueError, match="7 dias"):
        probe.normalize_window({"begintime_ms": BEGIN, "endtime_ms": BEGIN + probe.MAX_WINDOW_MS + 1})


def test_engine_selects_ready_authorized_session_not_merely_latest(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="leaphub-probe-multi-") as tmp:
        engine, limiter, _lock, _manual = make_engine(tmp)
        try:
            add_subscription(engine, "sub-ready", ["V1"])
            time.sleep(0.01)
            add_subscription(engine, "sub-newer-no-session", ["V2"])
            client = FakeClient()
            inject_session(engine, "sub-ready", client, [vehicle("V1", "LPS12345678901234")])
            monkeypatch.setattr(probe, "build_signed_headers", lambda **kwargs: _Headers())
            result = engine.execute_driving_record_probe("staging", {"account_id": 1, "vehicle_id": "V1", "begintime_ms": BEGIN, "endtime_ms": END})
            assert result["ok"] is True and result["session_reused"] is True
            assert len(client.posts) == 1 and limiter.active == 0
        finally:
            close_engine(engine)


def test_no_target_is_rejected_when_multiple_authorized_vehicles_are_ready(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="leaphub-probe-ambiguous-") as tmp:
        engine, limiter, _lock, _manual = make_engine(tmp)
        try:
            add_subscription(engine, "sub-one", ["V1"])
            add_subscription(engine, "sub-two", ["V2"])
            c1 = FakeClient(); c2 = FakeClient()
            inject_session(engine, "sub-one", c1, [vehicle("V1", "LPS12345678901234")])
            inject_session(engine, "sub-two", c2, [vehicle("V2", "LPS99999999999999")])
            monkeypatch.setattr(probe, "build_signed_headers", lambda **kwargs: _Headers())
            with pytest.raises(ValueError, match="mais de um veículo autorizado"):
                engine.execute_driving_record_probe("staging", {"account_id": 1, "begintime_ms": BEGIN, "endtime_ms": END})
            assert c1.posts == [] and c2.posts == [] and limiter.active == 0
        finally:
            close_engine(engine)


def test_same_account_vehicle_outside_subscription_scope_is_rejected(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="leaphub-probe-scope-") as tmp:
        engine, limiter, _lock, _manual = make_engine(tmp)
        try:
            add_subscription(engine, "sub-one", ["V1"])
            client = FakeClient()
            inject_session(engine, "sub-one", client, [
                vehicle("V1", "LPS12345678901234"),
                vehicle("V2", "LPS99999999999999"),
            ])
            monkeypatch.setattr(probe, "build_signed_headers", lambda **kwargs: _Headers())
            with pytest.raises(ValueError, match="escopo autorizado"):
                engine.execute_driving_record_probe("staging", {"account_id": 1, "vehicle_id": "V2", "vehicle_vin": "LPS99999999999999", "begintime_ms": BEGIN, "endtime_ms": END})
            assert client.posts == [] and limiter.active == 0
        finally:
            close_engine(engine)


def test_discovery_does_not_wait_for_engine_global_lock(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="leaphub-probe-nolock-") as tmp:
        engine, limiter, _lock, _manual = make_engine(tmp)
        held = threading.Event(); release = threading.Event()
        try:
            add_subscription(engine, "sub-one", ["V1"])
            client = FakeClient()
            inject_session(engine, "sub-one", client, [vehicle("V1", "LPS12345678901234")])
            monkeypatch.setattr(probe, "build_signed_headers", lambda **kwargs: _Headers())
            def holder():
                with engine.lock:
                    held.set(); release.wait(2)
            thread = threading.Thread(target=holder, daemon=True); thread.start(); assert held.wait(1)
            started = time.monotonic()
            result = engine.execute_driving_record_probe("staging", {"account_id": 1, "vehicle_id": "V1", "begintime_ms": BEGIN, "endtime_ms": END})
            elapsed = time.monotonic() - started
            assert result["ok"] is True and elapsed < 0.75
        finally:
            release.set()
            close_engine(engine)


def test_manual_priority_after_account_or_global_slot_preempts_before_network(monkeypatch):
    monkeypatch.setattr(probe, "build_signed_headers", lambda **kwargs: _Headers())
    for stage in ("account", "slot"):
        with tempfile.TemporaryDirectory(prefix=f"leaphub-probe-preempt-{stage}-") as tmp:
            manual = {"pending": False}
            if stage == "account":
                account_lock = FakeAccountLock(on_acquire=lambda: manual.__setitem__("pending", True))
                limiter = FakeLimiter()
            else:
                account_lock = FakeAccountLock()
                limiter = FakeLimiter(on_acquire=lambda: manual.__setitem__("pending", True))
            engine, limiter, _lock, _state = make_engine(tmp, manual_state=manual, limiter=limiter, account_lock=account_lock)
            try:
                add_subscription(engine, "sub-one", ["V1"])
                client = FakeClient()
                inject_session(engine, "sub-one", client, [vehicle("V1", "LPS12345678901234")])
                result = engine.execute_driving_record_probe("staging", {"account_id": 1, "vehicle_id": "V1", "begintime_ms": BEGIN, "endtime_ms": END})
                assert result["reason"] == "manual_priority"
                assert client.posts == [] and limiter.active == 0
            finally:
                close_engine(engine)


def test_session_busy_defers_quickly_and_does_not_leak_locks(monkeypatch):
    monkeypatch.setattr(probe, "build_signed_headers", lambda **kwargs: _Headers())
    with tempfile.TemporaryDirectory(prefix="leaphub-probe-session-busy-") as tmp:
        engine, limiter, _account, _manual = make_engine(tmp)
        release = threading.Event(); held = threading.Event()
        try:
            add_subscription(engine, "sub-one", ["V1"])
            client = FakeClient()
            inject_session(engine, "sub-one", client, [vehicle("V1", "LPS12345678901234")])
            lock = engine._session_operation_lock("sub-one")
            def holder():
                with lock:
                    held.set(); release.wait(2)
            thread = threading.Thread(target=holder, daemon=True); thread.start(); assert held.wait(1)
            for _ in range(3):
                started = time.monotonic()
                result = engine.execute_driving_record_probe("staging", {"account_id": 1, "vehicle_id": "V1", "begintime_ms": BEGIN, "endtime_ms": END})
                assert result["reason"] == "session_busy" and time.monotonic() - started < 0.5
                assert limiter.active == 0 and client.posts == []
            release.set(); thread.join(timeout=1)
            result = engine.execute_driving_record_probe("staging", {"account_id": 1, "vehicle_id": "V1", "begintime_ms": BEGIN, "endtime_ms": END})
            assert result["ok"] is True and limiter.active == 0 and len(client.posts) == 1
        finally:
            release.set()
            close_engine(engine)


def test_unknown_failure_never_logs_raw_exception_text(monkeypatch):
    monkeypatch.setattr(probe, "build_signed_headers", lambda **kwargs: _Headers())
    secret = "SECRET_RAW_BODY_ABC"
    with tempfile.TemporaryDirectory(prefix="leaphub-probe-log-") as tmp:
        engine, limiter, _account, _manual = make_engine(tmp)
        stream = io.StringIO(); handler = logging.StreamHandler(stream)
        logger = logging.getLogger("leaphub.telemetry"); logger.addHandler(handler); old = logger.level; logger.setLevel(logging.INFO)
        try:
            add_subscription(engine, "sub-one", ["V1"])
            client = FakeClient(fail_secret=secret)
            inject_session(engine, "sub-one", client, [vehicle("V1", "LPS12345678901234")])
            result = engine.execute_driving_record_probe("staging", {"account_id": 1, "vehicle_id": "V1", "begintime_ms": BEGIN, "endtime_ms": END})
            assert result["reason"] == "probe_failed"
            assert secret not in stream.getvalue()
            assert secret not in json.dumps(result, ensure_ascii=False)
            assert limiter.active == 0
        finally:
            logger.removeHandler(handler); logger.setLevel(old)
            close_engine(engine)
