#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import random
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

import leaphub_connector as connector

LOG = logging.getLogger("leaphub.telemetry")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=connector.json_default).encode("utf-8")


class TelemetryEngine:
    """Adaptive polling and encrypted persistent delivery queue."""

    def __init__(self, options: dict[str, Any], secrets: dict[str, str], operation_semaphore: threading.BoundedSemaphore) -> None:
        self.options = options
        self.secrets = secrets
        self.operation_semaphore = operation_semaphore
        self.data_dir = Path(os.getenv("LEAPHUB_TELEMETRY_DIR", "/data/telemetry"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "telemetry.sqlite"
        self.key_path = self.data_dir / "telemetry.key"
        self.fernet = Fernet(self._load_key())
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.lock = threading.RLock()
        self.active_seconds = self._bounded("telemetry_active_seconds", 15, 10, 120)
        self.charging_seconds = self._bounded("telemetry_charging_seconds", 30, 15, 300)
        self.parked_seconds = self._bounded("telemetry_parked_seconds", 300, 60, 1800)
        self.sleep_seconds = self._bounded("telemetry_sleep_seconds", 900, 300, 7200)
        self.batch_size = self._bounded("telemetry_batch_size", 25, 1, 50)
        self.retention_days = self._bounded("telemetry_retention_days", 7, 1, 60)
        self.queue_max = self._bounded("telemetry_queue_max_events", 10000, 100, 100000)
        self.delivery_urls = {
            "staging": str(options.get("telemetry_beta_internal_url") or "").strip(),
            "production": str(options.get("telemetry_production_internal_url") or "").strip(),
        }
        self.environment_enabled = {
            "staging": bool(options.get("telemetry_beta_enabled", True)),
            "production": bool(options.get("telemetry_production_enabled", False)),
        }
        self._init_db()

    def _bounded(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self.options.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def _load_key(self) -> bytes:
        if self.key_path.is_file():
            key = self.key_path.read_bytes().strip()
            try:
                Fernet(key)
                return key
            except (ValueError, TypeError):
                raise RuntimeError("A chave local da fila de telemetria está inválida.")
        key = Fernet.generate_key()
        descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(key + b"\n")
        return key

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _init_db(self) -> None:
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    environment TEXT NOT NULL,
                    account_id INTEGER NOT NULL,
                    credentials_encrypted BLOB NOT NULL,
                    vehicle_ids_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'waiting',
                    next_run_at REAL NOT NULL,
                    last_run_at TEXT NULL,
                    last_success_at TEXT NULL,
                    last_delivery_at TEXT NULL,
                    last_error TEXT NULL,
                    last_state TEXT NULL,
                    parked_streak INTEGER NOT NULL DEFAULT 0,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_subscriptions_due ON subscriptions(enabled, next_run_at);
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    subscription_id TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    account_id INTEGER NOT NULL,
                    remote_id TEXT NOT NULL,
                    source_at TEXT NOT NULL,
                    payload_encrypted BLOB NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL,
                    last_error TEXT NULL,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT NULL,
                    FOREIGN KEY(subscription_id) REFERENCES subscriptions(subscription_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_events_delivery ON events(status, next_attempt_at, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_subscription ON events(subscription_id, created_at);
                """
            )

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._run, name="leaphub-telemetry", daemon=True)
        self.worker.start()
        LOG.info("Telemetria contínua iniciada com fila persistente em %s.", self.db_path)

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=12)

    def upsert(self, environment: str, payload: dict[str, Any]) -> dict[str, Any]:
        subscription_id = str(payload.get("subscription_id") or "").strip()[:190]
        account_id = int(payload.get("account_id") or 0)
        credentials = payload.get("credentials")
        ids = payload.get("vehicle_ids")
        enabled = bool(payload.get("enabled", True))
        if not subscription_id or account_id < 1 or not isinstance(credentials, dict) or not isinstance(ids, list):
            raise ValueError("Assinatura de telemetria incompleta.")
        if environment not in self.secrets or len(self.secrets[environment]) < 32:
            raise ValueError("Ambiente sem chave válida.")
        vehicle_ids = sorted({str(item).strip()[:190] for item in ids if str(item).strip()})
        if not vehicle_ids:
            raise ValueError("Nenhum veículo informado para a assinatura.")
        for key in ("email", "password", "certificate_pem", "private_key_pem"):
            if not str(credentials.get(key) or "").strip():
                raise ValueError("Credenciais de telemetria incompletas.")
        encrypted = self.fernet.encrypt(canonical_json(credentials))
        now = utc_iso()
        next_run = time.time() + random.uniform(1.0, 4.0)
        with self.lock, self._db() as db:
            db.execute(
                """
                INSERT INTO subscriptions
                (subscription_id, environment, account_id, credentials_encrypted, vehicle_ids_json, enabled, status, next_run_at,
                 last_run_at, last_success_at, last_delivery_at, last_error, last_state, parked_streak, consecutive_failures, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'waiting', ?, NULL, NULL, NULL, NULL, NULL, 0, 0, ?, ?)
                ON CONFLICT(subscription_id) DO UPDATE SET
                    environment=excluded.environment, account_id=excluded.account_id,
                    credentials_encrypted=excluded.credentials_encrypted, vehicle_ids_json=excluded.vehicle_ids_json,
                    enabled=excluded.enabled, status='waiting', next_run_at=excluded.next_run_at,
                    last_error=NULL, consecutive_failures=0, updated_at=excluded.updated_at
                """,
                (subscription_id, environment, account_id, encrypted, json.dumps(vehicle_ids), 1 if enabled else 0, next_run, now, now),
            )
        self.wake_event.set()
        return {"ok": True, "subscription_id": subscription_id, "vehicle_count": len(vehicle_ids), "next_run_seconds": int(max(0, next_run - time.time()))}

    def remove(self, subscription_id: str) -> dict[str, Any]:
        subscription_id = str(subscription_id or "").strip()[:190]
        if not subscription_id:
            raise ValueError("Identificador da assinatura ausente.")
        with self.lock, self._db() as db:
            cursor = db.execute("UPDATE subscriptions SET enabled=0, status='disabled', updated_at=? WHERE subscription_id=?", (utc_iso(), subscription_id))
        self.wake_event.set()
        return {"ok": True, "subscription_id": subscription_id, "disabled": cursor.rowcount > 0}

    def boost(self, subscription_id: str, seconds: int = 900) -> dict[str, Any]:
        subscription_id = str(subscription_id or "").strip()[:190]
        with self.lock, self._db() as db:
            cursor = db.execute("UPDATE subscriptions SET next_run_at=?, last_state='boost', updated_at=? WHERE subscription_id=? AND enabled=1", (time.time() + 0.5, utc_iso(), subscription_id))
        self.wake_event.set()
        return {"ok": cursor.rowcount > 0, "subscription_id": subscription_id, "boost_seconds": max(60, min(3600, int(seconds)))}

    def status(self) -> dict[str, Any]:
        with self.lock, self._db() as db:
            totals = db.execute(
                "SELECT COUNT(*) subscriptions, SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) enabled, SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) errors FROM subscriptions"
            ).fetchone()
            queue = db.execute(
                "SELECT COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) pending, "
                "COALESCE(SUM(CASE WHEN status='delivered' THEN 1 ELSE 0 END),0) delivered, "
                "MIN(CASE WHEN status='pending' THEN created_at END) oldest_pending FROM events"
            ).fetchone()
            recent = [dict(row) for row in db.execute(
                "SELECT subscription_id, environment, account_id, status, last_run_at, last_success_at, last_delivery_at, last_error, last_state, next_run_at FROM subscriptions ORDER BY updated_at DESC LIMIT 20"
            ).fetchall()]
        for item in recent:
            item["next_run_in_seconds"] = max(0, int(float(item.pop("next_run_at") or 0) - time.time()))
            if item.get("last_error"):
                item["last_error"] = str(item["last_error"])[:240]
        return {
            "ok": True,
            "subscriptions": int(totals["subscriptions"] or 0),
            "enabled_subscriptions": int(totals["enabled"] or 0),
            "subscription_errors": int(totals["errors"] or 0),
            "pending_events": int(queue["pending"] or 0),
            "delivered_events": int(queue["delivered"] or 0),
            "oldest_pending": queue["oldest_pending"],
            "profiles": {
                "driving_seconds": self.active_seconds,
                "charging_seconds": self.charging_seconds,
                "parked_seconds": self.parked_seconds,
                "sleep_seconds": self.sleep_seconds,
            },
            "recent": recent,
        }

    def _run(self) -> None:
        while not self.stop_event.is_set():
            did_work = False
            try:
                did_work = self._deliver_due() or did_work
                subscription = self._next_due_subscription()
                if subscription is not None:
                    self._poll_subscription(subscription)
                    did_work = True
                self._maintenance()
            except Exception:  # noqa: BLE001
                LOG.exception("Falha no ciclo de telemetria")
            wait = 0.5 if did_work else min(5.0, self._seconds_until_next())
            self.wake_event.wait(max(0.25, wait))
            self.wake_event.clear()

    def _next_due_subscription(self) -> sqlite3.Row | None:
        with self.lock, self._db() as db:
            return db.execute(
                "SELECT * FROM subscriptions WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at ASC LIMIT 1", (time.time(),)
            ).fetchone()

    def _seconds_until_next(self) -> float:
        with self.lock, self._db() as db:
            row = db.execute("SELECT MIN(next_run_at) due FROM subscriptions WHERE enabled=1").fetchone()
            delivery = db.execute("SELECT MIN(next_attempt_at) due FROM events WHERE status='pending'").fetchone()
        values = [float(item["due"]) for item in (row, delivery) if item and item["due"] is not None]
        return max(0.25, min(values) - time.time()) if values else 5.0

    def _poll_subscription(self, subscription: sqlite3.Row) -> None:
        sid = str(subscription["subscription_id"])
        # Nunca deixa o armazenamento crescer sem limite. Quando só restam
        # eventos ainda não entregues, a coleta pausa de forma explícita em vez
        # de apagar dados silenciosamente.
        with self.lock, self._db() as db:
            queued = int(db.execute("SELECT COUNT(*) FROM events WHERE status='pending'").fetchone()[0])
        if queued >= self.queue_max:
            self._reschedule(sid, 60, "queue_full", "Fila persistente atingiu o limite; aguardando entrega ao site.", failed=False)
            LOG.error("Fila de telemetria cheia (%s eventos). Coleta pausada até a entrega liberar espaço.", queued)
            return
        environment = str(subscription["environment"])
        if not self.environment_enabled.get(environment, False) or not self.delivery_urls.get(environment):
            self._reschedule(sid, self.sleep_seconds, "disabled", "URL de entrega ou ambiente desativado.", failed=True)
            return
        try:
            credentials = json.loads(self.fernet.decrypt(bytes(subscription["credentials_encrypted"])).decode("utf-8"))
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._reschedule(sid, self.sleep_seconds, "error", "Credenciais locais não puderam ser descriptografadas.", failed=True)
            LOG.error("Assinatura %s com credencial inválida: %s", sid, exc)
            return
        try:
            vehicle_ids = set(json.loads(str(subscription["vehicle_ids_json"])))
        except (ValueError, TypeError, json.JSONDecodeError):
            vehicle_ids = set()

        acquired = self.operation_semaphore.acquire(timeout=5)
        if not acquired:
            self._reschedule(sid, 5, "waiting", "Aguardando vaga no Connector.", failed=False)
            return
        try:
            result = connector.handle_account({"credentials": credentials, "read_only": True}, sync=True)
        except Exception as exc:  # noqa: BLE001
            failures = int(subscription["consecutive_failures"] or 0) + 1
            delay = min(self.sleep_seconds, max(30, 15 * (2 ** min(failures, 6))))
            self._reschedule(sid, delay, "error", connector.clean_message(str(exc)), failed=True)
            return
        finally:
            self.operation_semaphore.release()
            credentials.clear()

        vehicles = [item for item in (result.get("vehicles") or []) if isinstance(item, dict)]
        if vehicle_ids:
            vehicles = [item for item in vehicles if str(item.get("remote_id") or "") in vehicle_ids]
        if not vehicles:
            self._reschedule(sid, self.sleep_seconds, "error", "Nenhum veículo autorizado foi retornado.", failed=True)
            return

        states: list[str] = []
        for vehicle in vehicles:
            telemetry = vehicle.get("telemetry") if isinstance(vehicle.get("telemetry"), dict) else {}
            source_at = str(telemetry.get("captured_at") or utc_iso())
            state = self._state_of(telemetry)
            states.append(state)
            self._queue_event(subscription, vehicle, source_at)

        interval, aggregate_state, parked_streak = self._adaptive_interval(states, int(subscription["parked_streak"] or 0))
        jitter = random.uniform(0, max(1.0, interval * 0.08))
        now = utc_iso()
        with self.lock, self._db() as db:
            db.execute(
                "UPDATE subscriptions SET status='active', next_run_at=?, last_run_at=?, last_success_at=?, last_error=NULL, last_state=?, parked_streak=?, consecutive_failures=0, updated_at=? WHERE subscription_id=?",
                (time.time() + interval + jitter, now, now, aggregate_state, parked_streak, now, sid),
            )
        LOG.info("Telemetria %s: %s veículo(s), estado %s, próxima consulta em %ss.", sid, len(vehicles), aggregate_state, int(interval + jitter))
        self.wake_event.set()

    def _state_of(self, telemetry: dict[str, Any]) -> str:
        state = str(telemetry.get("vehicle_state") or "").lower()
        charging = str(telemetry.get("charging_status") or "").lower()
        try:
            speed = float(telemetry.get("speed_kmh") or 0)
        except (TypeError, ValueError):
            speed = 0
        if speed > 1 or state in {"driving", "ready"} or telemetry.get("ready_state") is True or telemetry.get("ignition_on") is True:
            return "driving"
        if charging == "charging" or state == "charging":
            return "charging"
        if telemetry.get("is_parked") is True or state == "parked":
            return "parked"
        return "sleep"

    def _adaptive_interval(self, states: list[str], previous_parked_streak: int) -> tuple[int, str, int]:
        if "driving" in states:
            return self.active_seconds, "driving", 0
        if "charging" in states:
            return self.charging_seconds, "charging", 0
        if "parked" in states:
            streak = previous_parked_streak + 1
            if streak >= 4:
                return self.sleep_seconds, "sleep", streak
            return self.parked_seconds, "parked", streak
        return self.sleep_seconds, "sleep", previous_parked_streak + 1

    def _queue_event(self, subscription: sqlite3.Row, vehicle: dict[str, Any], source_at: str) -> None:
        environment = str(subscription["environment"])
        account_id = int(subscription["account_id"])
        remote_id = str(vehicle.get("remote_id") or "")[:190]
        payload_hash = hashlib.sha256(canonical_json(vehicle)).hexdigest()
        event_id = hashlib.sha256(f"{environment}|{account_id}|{remote_id}|{source_at}|{payload_hash}".encode()).hexdigest()
        encrypted = self.fernet.encrypt(canonical_json(vehicle))
        now = utc_iso()
        with self.lock, self._db() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO events
                (event_id, subscription_id, environment, account_id, remote_id, source_at, payload_encrypted, payload_hash, status, attempts, next_attempt_at, last_error, created_at, delivered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, NULL, ?, NULL)
                """,
                (event_id, str(subscription["subscription_id"]), environment, account_id, remote_id, source_at, encrypted, payload_hash, time.time(), now),
            )

    def _deliver_due(self) -> bool:
        with self.lock, self._db() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE status='pending' AND next_attempt_at<=? ORDER BY created_at ASC LIMIT ?",
                (time.time(), self.batch_size),
            ).fetchall()
        if not rows:
            return False
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(str(row["environment"]), []).append(row)
        for environment, group in grouped.items():
            self._deliver_group(environment, group)
        return True

    def _deliver_group(self, environment: str, rows: list[sqlite3.Row]) -> None:
        url = self.delivery_urls.get(environment, "")
        secret = self.secrets.get(environment, "")
        if not url or len(secret) < 32:
            self._delivery_failed(rows, "Destino ou chave do ambiente não configurado.")
            return
        events = []
        valid_rows = []
        for row in rows:
            try:
                vehicle = json.loads(self.fernet.decrypt(bytes(row["payload_encrypted"])).decode("utf-8"))
            except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
                self._mark_permanent_failure(str(row["event_id"]), "Evento local corrompido.")
                continue
            events.append({
                "event_id": str(row["event_id"]),
                "account_id": int(row["account_id"]),
                "source_at": str(row["source_at"]),
                "vehicle": vehicle,
            })
            valid_rows.append(row)
        if not events:
            return
        body = canonical_json({"events": events, "gateway_version": "1.11.55", "sent_at": utc_iso()})
        parsed = urllib.parse.urlparse(url)
        path = parsed.path or "/"
        timestamp = str(int(time.time()))
        nonce = os.urandom(16).hex()
        canonical = f"POST\n{path}\n{timestamp}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()
        signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "LeapHubGateway/1.11.55",
                "X-LeapHub-Timestamp": timestamp,
                "X-LeapHub-Nonce": nonce,
                "X-LeapHub-Environment": environment,
                "X-LeapHub-Signature": signature,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read(2 * 1024 * 1024)
                payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("Resposta de entrega inválida.")
            by_id = {str(item.get("event_id")): item for item in (payload.get("results") or []) if isinstance(item, dict)}
            delivered_ids = []
            failed_rows = []
            for row in valid_rows:
                item = by_id.get(str(row["event_id"]))
                if item and item.get("ok") is True:
                    delivered_ids.append(str(row["event_id"]))
                else:
                    failed_rows.append(row)
            if delivered_ids:
                now = utc_iso()
                with self.lock, self._db() as db:
                    db.executemany("UPDATE events SET status='delivered', delivered_at=?, last_error=NULL WHERE event_id=?", [(now, event_id) for event_id in delivered_ids])
                    subscription_ids = sorted({str(row["subscription_id"]) for row in valid_rows if str(row["event_id"]) in delivered_ids})
                    db.executemany("UPDATE subscriptions SET last_delivery_at=?, updated_at=? WHERE subscription_id=?", [(now, now, sid) for sid in subscription_ids])
            if failed_rows:
                self._delivery_failed(failed_rows, "O site recusou parte do lote.")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._delivery_failed(valid_rows, connector.clean_message(str(exc)))

    def _delivery_failed(self, rows: list[sqlite3.Row], message: str) -> None:
        now = time.time()
        updates = []
        for row in rows:
            attempts = int(row["attempts"] or 0) + 1
            delay = min(1800, max(10, 5 * (2 ** min(attempts, 8)))) + random.uniform(0, 5)
            updates.append((attempts, now + delay, str(message)[:500], str(row["event_id"])))
        with self.lock, self._db() as db:
            db.executemany("UPDATE events SET attempts=?, next_attempt_at=?, last_error=? WHERE event_id=?", updates)
        LOG.warning("Entrega de %s evento(s) adiada: %s", len(rows), message)

    def _mark_permanent_failure(self, event_id: str, message: str) -> None:
        with self.lock, self._db() as db:
            db.execute("UPDATE events SET status='failed', last_error=? WHERE event_id=?", (message[:500], event_id))

    def _reschedule(self, subscription_id: str, delay: int, status: str, error: str | None, failed: bool) -> None:
        now = utc_iso()
        with self.lock, self._db() as db:
            if failed:
                db.execute(
                    "UPDATE subscriptions SET status=?, next_run_at=?, last_run_at=?, last_error=?, consecutive_failures=consecutive_failures+1, updated_at=? WHERE subscription_id=?",
                    (status, time.time() + delay + random.uniform(0, 5), now, str(error or "")[:500], now, subscription_id),
                )
            else:
                db.execute(
                    "UPDATE subscriptions SET status=?, next_run_at=?, last_run_at=?, last_error=?, updated_at=? WHERE subscription_id=?",
                    (status, time.time() + delay, now, str(error or "")[:500] or None, now, subscription_id),
                )

    def _maintenance(self) -> None:
        # Executada de forma barata; o SQLite ignora as remoções quando não há registros antigos.
        cutoff = time.time() - self.retention_days * 86400
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat().replace("+00:00", "Z")
        with self.lock, self._db() as db:
            db.execute("DELETE FROM events WHERE status='delivered' AND delivered_at<?", (cutoff_iso,))
            total = int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            if total > self.queue_max:
                excess = total - self.queue_max
                db.execute(
                    "DELETE FROM events WHERE event_id IN (SELECT event_id FROM events WHERE status='delivered' ORDER BY delivered_at ASC LIMIT ?)",
                    (excess,),
                )
