#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TEMP_ROOT = tempfile.TemporaryDirectory(prefix="leaphub-gateway-tests-")
os.environ["LEAPHUB_TELEMETRY_DIR"] = str(Path(_TEMP_ROOT.name) / "telemetry")
os.environ["LEAPHUB_PRIVACY_KEY_PATH"] = str(Path(_TEMP_ROOT.name) / "privacy.key")

import connector  # noqa: E402
import privacy  # noqa: E402
sys.modules.setdefault("leaphub_connector", connector)
sys.modules.setdefault("leaphub_privacy", privacy)
from telemetry_engine import TelemetryEngine  # noqa: E402


class DestinationLegacy:
    def __init__(self) -> None:
        self.received = None

    def send_destination(self, vehicle_id: str, address: str, latitude: float, longitude: float):
        self.received = (vehicle_id, address, latitude, longitude)
        return self.received


class DestinationModern:
    def __init__(self) -> None:
        self.received = None

    def send_destination(self, vehicle_id: str, name: str, address: str, latitude: float, longitude: float):
        self.received = (vehicle_id, name, address, latitude, longitude)
        return self.received


class GatewayRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = TelemetryEngine(
            {
                "telemetry_active_seconds": 20,
                "telemetry_charging_seconds": 25,
                "telemetry_parked_seconds": 90,
                "telemetry_sleep_seconds": 600,
                "telemetry_beta_enabled": True,
                "telemetry_production_enabled": False,
            },
            {"staging": "s" * 32, "production": "p" * 32},
            threading.BoundedSemaphore(1),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.stop()
        handle = getattr(cls.engine, "_instance_lock_handle", None)
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
            except OSError:
                pass
        _TEMP_ROOT.cleanup()

    def payload(self) -> dict:
        return {
            "subscription_id": "staging-account-9",
            "account_id": 9,
            "credentials": {
                "email": "owner@example.com",
                "password": "not-a-real-password",
                "certificate_pem": "certificate-placeholder",
                "private_key_pem": "private-key-placeholder",
            },
            "vehicle_ids": ["LFA12345678901234"],
            "enabled": True,
        }

    def test_identical_upsert_is_local_noop(self) -> None:
        first = self.engine.upsert("staging", self.payload())
        self.assertTrue(first["ok"])
        self.engine.wake_event.clear()
        with self.engine._db() as db:
            before = db.execute(
                "SELECT status,next_run_at,active_until,interactive_until,command_until FROM subscriptions WHERE subscription_id=?",
                ("staging-account-9",),
            ).fetchone()
        second = self.engine.upsert("staging", self.payload())
        with self.engine._db() as db:
            after = db.execute(
                "SELECT status,next_run_at,active_until,interactive_until,command_until FROM subscriptions WHERE subscription_id=?",
                ("staging-account-9",),
            ).fetchone()
        self.assertTrue(second["deduplicated"])
        self.assertEqual(tuple(before), tuple(after))
        self.assertFalse(self.engine.wake_event.is_set(), "upsert idêntico não pode acordar o worker")

    def test_global_auth_gate_and_progressive_backoff(self) -> None:
        with self.engine._db() as db:
            db.execute("DELETE FROM account_auth_state WHERE environment='staging' AND account_id=42")
        reservation = self.engine.begin_account_auth("staging", 42, "telemetry")
        self.assertTrue(reservation["managed"])
        with self.assertRaises(connector.ConnectorLoginCooldownError):
            self.engine.begin_account_auth("staging", 42, "manual_sync")
        first = self.engine.record_account_auth_failure("staging", 42, "telemetry", "try again in 120 seconds", 135, True)
        second = self.engine.record_account_auth_failure("staging", 42, "command", "try again in 300 seconds", 300, True)
        third = self.engine.record_account_auth_failure("staging", 42, "sync", "blocked", 300, True)
        fourth = self.engine.record_account_auth_failure("staging", 42, "recovery", "blocked", 300, True)
        self.assertEqual((first, second, third, fourth), (300, 600, 1200, 1800))
        status = self.engine.account_auth_status("staging", 42)
        self.assertEqual(status["block_count"], 4)
        self.assertEqual(status["last_origin"], "recovery")
        self.engine.record_account_auth_success("staging", 42, "session_refresh")
        status = self.engine.account_auth_status("staging", 42)
        self.assertFalse(status["cooldown"])
        self.assertEqual(status["block_count"], 0)

    def test_conservative_state_and_sleep_intervals(self) -> None:
        self.assertEqual(self.engine._state_of({"vehicle_state": "ready", "ignition": True, "speed_kmh": 0}), "parked")
        self.assertEqual(self.engine._state_of({"vehicle_state": "driving", "speed_kmh": 0}), "driving")
        self.assertEqual(self.engine._state_of({"vehicle_state": "driving", "speed_kmh": 8}), "driving")
        self.assertEqual(self.engine._state_of({"gear": "D", "ready_state": True, "speed_kmh": 0}), "parked")
        self.assertEqual(self.engine._adaptive_interval(["driving"], 0)[0], 20)
        self.assertEqual(self.engine._adaptive_interval(["charging"], 0)[0], 25)
        self.assertEqual(self.engine._adaptive_interval(["parked"], 0)[0], 90)
        self.assertEqual(self.engine._adaptive_interval(["sleep"], 1)[0], 600)
        self.assertEqual(self.engine._adaptive_interval(["sleep"], 3)[0], 600)

        stable, candidate, count = self.engine._confirm_state_transition("sleep", "", 0, "driving")
        self.assertEqual((stable, candidate, count), ("sleep", "driving", 1))
        stable, candidate, count = self.engine._confirm_state_transition(stable, candidate, count, "driving")
        self.assertEqual(stable, "driving")
        stable, candidate, count = self.engine._confirm_state_transition(stable, candidate, count, "driving")
        self.assertEqual(stable, "driving")

    def test_destination_signature_compatibility(self) -> None:
        params = {"name": "Casa", "address": "Rua Exemplo", "latitude": -24.75, "longitude": -51.75}
        legacy = DestinationLegacy()
        modern = DestinationModern()
        connector.execute_vehicle_command(legacy.send_destination, "send_destination", "VEHICLE", params)
        connector.execute_vehicle_command(modern.send_destination, "send_destination", "VEHICLE", params)
        self.assertEqual(legacy.received, ("VEHICLE", "Rua Exemplo", -24.75, -51.75))
        self.assertEqual(modern.received, ("VEHICLE", "Casa", "Rua Exemplo", -24.75, -51.75))

    def test_privacy_filter_removes_real_identifiers_and_secrets(self) -> None:
        raw = (
            "VIN LFA12345678901234 account leaphub-staging-account-42 "
            "Charge point connected: CPTEST9A8B7C6D5 ip=203.0.113.42 "
            "trace=abcdefabcdefabcdefabcdef password=Secret123 token=abc owner@example.com"
        )
        protected = privacy.sanitize_log(raw)
        for forbidden in (
            "LFA12345678901234", "leaphub-staging-account-42", "CPTEST9A8B7C6D5",
            "203.0.113.42", "abcdefabcdefabcdefabcdef", "Secret123", "owner@example.com",
        ):
            self.assertNotIn(forbidden, protected)
        self.assertIn("veh_", protected)
        self.assertIn("acct_", protected)
        self.assertIn("cp_", protected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
