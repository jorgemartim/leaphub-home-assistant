#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import random
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cryptography.fernet import Fernet, InvalidToken

import leaphub_connector as connector

LOG = logging.getLogger("leaphub.telemetry")
ENGINE_VERSION = "1.11.98"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=connector.json_default).encode("utf-8")


VOLATILE_SEMANTIC_KEYS = {
    "captured_at",
    "collect_time",
    "create_time",
    "synced_at",
    "sent_at",
    "gateway_collected_at",
    "visual_sample_fingerprint",
    "sample_fingerprint",
    "data_base64",
}


def semantic_snapshot(value: Any, parent_key: str = "") -> Any:
    """Remove transport timestamps while preserving every actual vehicle state."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key in VOLATILE_SEMANTIC_KEYS:
                continue
            if parent_key == "maintenance" and key == "synced_at":
                continue
            result[key] = semantic_snapshot(item, key)
        return result
    if isinstance(value, list):
        return [semantic_snapshot(item, parent_key) for item in value]
    return value


class TelemetryYieldForManual(RuntimeError):
    """A coleta automática cedeu a conta para uma operação manual."""


class TelemetryEngine:
    """Adaptive polling and encrypted persistent delivery queue."""

    def __init__(
        self,
        options: dict[str, Any],
        secrets: dict[str, str],
        operation_semaphore: threading.BoundedSemaphore,
        account_lock_provider: Callable[[str, dict[str, Any]], Any] | None = None,
        account_wait_seconds: int = 20,
        manual_pending_provider: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self.options = options
        self.secrets = secrets
        self.operation_semaphore = operation_semaphore
        self.account_lock_provider = account_lock_provider
        self.account_wait_seconds = max(2, min(60, int(account_wait_seconds)))
        self.manual_pending_provider = manual_pending_provider
        self.data_dir = Path(os.getenv("LEAPHUB_TELEMETRY_DIR", "/data/telemetry"))
        self.db_path = self.data_dir / "telemetry.sqlite"
        self.key_path = self.data_dir / "telemetry.key"
        self.migration_marker_path = self.data_dir / ".journal-migration.lock"
        self.instance_lock_path = self.data_dir / ".engine.lock"
        self._instance_lock_handle = None
        self.storage_lock = threading.RLock()
        self.storage_healthy = False
        self.storage_failures = 0
        self.storage_last_error = ""
        self.storage_last_error_at = ""
        self.storage_next_retry_at = 0.0
        self.storage_next_log_at = 0.0
        self.storage_journal_mode = "unknown"
        self._prepare_storage(probe=True)
        self._acquire_instance_lock()
        self.fernet = Fernet(self._load_key())
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.lock = threading.RLock()
        self.active_seconds = self._bounded("telemetry_active_seconds", 30, 15, 300)
        self.interactive_seconds = self._bounded("telemetry_interactive_seconds", 20, 15, 60)
        # Janela curta após comandos remotos. É propositalmente separada da
        # navegação comum para confirmar rapidamente o novo estado sem manter
        # consultas agressivas à nuvem durante todo o dia.
        self.command_seconds = self._bounded("telemetry_command_seconds", 3, 3, 10)
        self.command_max_polls = self._bounded("telemetry_command_max_polls", 8, 4, 12)
        self.command_cadence = (self.command_seconds, 6, 10, 15)
        self.charging_seconds = self._bounded("telemetry_charging_seconds", 30, 15, 600)
        self.parked_seconds = self._bounded("telemetry_parked_seconds", 300, 60, 3600)
        self.sleep_seconds = self._bounded("telemetry_sleep_seconds", 900, 300, 14400)
        self.presence_window_seconds = self._bounded("telemetry_presence_window_seconds", 420, 300, 1800)
        self.rate_limit_cooldown_seconds = self._bounded("telemetry_rate_limit_cooldown_seconds", 900, 300, 3600)
        self.login_cooldown_max_seconds = 300
        self.charge_watch_seconds = max(5, min(15, self.charging_seconds * 2))
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
        self.sessions: dict[str, dict[str, Any]] = {}
        # A tabela de sessões usa uma trava curta. Cada conta possui uma trava
        # própria para que contas diferentes possam ser consultadas em paralelo
        # sem permitir que upsert/remoção fechem uma sessão durante a leitura.
        self.session_lock = threading.RLock()
        self.session_locks_guard = threading.RLock()
        self.session_locks: dict[str, threading.RLock] = {}
        self.session_max_age_seconds = 2700
        self.session_idle_seconds = 900
        self._init_db()
        self.storage_healthy = True

    def _bounded(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self.options.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def _prepare_storage(self, probe: bool = False) -> None:
        """Garante que a fila persistente continue gravável após atualização/reinício."""
        with self.storage_lock:
            if self.data_dir.exists() and not self.data_dir.is_dir():
                raise OSError(f"O caminho de telemetria não é um diretório: {self.data_dir}")
            self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                self.data_dir.chmod(0o700)
            except OSError:
                pass
            for candidate in (
                self.db_path,
                self.key_path,
                Path(str(self.db_path) + "-wal"),
                Path(str(self.db_path) + "-shm"),
                Path(str(self.db_path) + "-journal"),
            ):
                if candidate.exists():
                    if not candidate.is_file():
                        raise OSError(f"Armazenamento inválido em {candidate}")
                    try:
                        candidate.chmod(0o600)
                    except OSError:
                        pass
            if not probe:
                return
            probe_path = self.data_dir / f".write-probe-{os.getpid()}-{threading.get_ident()}"
            descriptor = os.open(probe_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as handle:
                    handle.write(b"ok\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                try:
                    probe_path.unlink(missing_ok=True)
                except OSError:
                    pass

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
            handle.flush()
            os.fsync(handle.fileno())
        return key

    def _acquire_instance_lock(self) -> None:
        """Impede dois Connector de abrirem a mesma fila ao mesmo tempo."""
        try:
            import fcntl
        except ImportError:
            return
        handle = self.instance_lock_path.open("a+", encoding="utf-8")
        deadline = time.monotonic() + 45.0
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                handle.seek(0)
                handle.truncate()
                handle.write(f"pid={os.getpid()} started={utc_iso()}\n")
                handle.flush()
                self._instance_lock_handle = handle
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise RuntimeError("Outra instância do Connector ainda utiliza a fila de telemetria.")
                time.sleep(0.5)

    @contextmanager
    def _journal_migration_guard(self):
        """Sinaliza ao painel que a fila está em migração e não deve ser consultada."""
        self.migration_marker_path.write_text(
            json.dumps({"pid": os.getpid(), "started_at": utc_iso()}),
            encoding="utf-8",
        )
        try:
            self.migration_marker_path.chmod(0o600)
        except OSError:
            pass
        try:
            yield
        finally:
            try:
                self.migration_marker_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _db(self, timeout_seconds: float = 30.0) -> sqlite3.Connection:
        self._prepare_storage(probe=False)
        db: sqlite3.Connection | None = None
        try:
            timeout_seconds = max(0.05, min(30.0, float(timeout_seconds)))
            db = sqlite3.connect(self.db_path, timeout=timeout_seconds, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute(f"PRAGMA busy_timeout={max(50, int(timeout_seconds * 1000))}")
            db.execute("PRAGMA foreign_keys=ON")
            # Evita depender de /tmp ou de arquivos temporários externos ao /data.
            db.execute("PRAGMA temp_store=MEMORY")
            return db
        except Exception:
            if db is not None:
                db.close()
            raise

    def _configure_journal(self, db: sqlite3.Connection) -> None:
        """Migra WAL com espera e não pede trava exclusiva quando já está em DELETE."""
        current_row = db.execute("PRAGMA journal_mode").fetchone()
        current = str(current_row[0] if current_row else "unknown").lower()

        # PRAGMA journal_mode=DELETE exige trava exclusiva até quando o banco já
        # está em DELETE. Evitar a escrita desnecessária elimina a disputa com o painel.
        if current == "delete":
            self.storage_journal_mode = current
            db.execute("PRAGMA synchronous=FULL")
            return

        last_error: Exception | None = None
        for attempt in range(12):
            try:
                if current == "wal":
                    try:
                        db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    except sqlite3.OperationalError as exc:
                        if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                            raise
                mode_row = db.execute("PRAGMA journal_mode=DELETE").fetchone()
                mode = str(mode_row[0] if mode_row else current).lower()
                self.storage_journal_mode = mode
                if mode != "delete":
                    raise sqlite3.OperationalError(f"journal SQLite incompatível: {mode}")
                db.execute("PRAGMA synchronous=FULL")
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                message = str(exc).lower()
                if "locked" not in message and "busy" not in message:
                    raise
                # Dá tempo para uma leitura curta terminar. O painel respeita o
                # marcador e deixa de abrir novas conexões durante esta janela.
                time.sleep(min(3.0, 0.25 * (attempt + 1)))
                current_row = db.execute("PRAGMA journal_mode").fetchone()
                current = str(current_row[0] if current_row else current).lower()
                if current == "delete":
                    self.storage_journal_mode = current
                    db.execute("PRAGMA synchronous=FULL")
                    return
        raise sqlite3.OperationalError(
            "Não foi possível obter acesso exclusivo para migrar a fila SQLite."
        ) from last_error

    def _init_db(self) -> None:
        self._prepare_storage(probe=True)
        with self._journal_migration_guard():
            with self._db() as db:
                self._configure_journal(db)
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
                        cooldown_until REAL NOT NULL DEFAULT 0,
                        active_until REAL NOT NULL DEFAULT 0,
                        interactive_until REAL NOT NULL DEFAULT 0,
                        command_until REAL NOT NULL DEFAULT 0,
                        command_key TEXT NULL,
                        command_vehicle_id TEXT NULL,
                        command_context_json TEXT NULL,
                        command_poll_count INTEGER NOT NULL DEFAULT 0,
                        command_started_at REAL NOT NULL DEFAULT 0,
                        last_presence_at TEXT NULL,
                        auth_required INTEGER NOT NULL DEFAULT 0,
                        credential_hash TEXT NULL,
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
                columns = {str(row[1]) for row in db.execute("PRAGMA table_info(subscriptions)").fetchall()}
                if "cooldown_until" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN cooldown_until REAL NOT NULL DEFAULT 0")
                if "active_until" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN active_until REAL NOT NULL DEFAULT 0")
                if "interactive_until" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN interactive_until REAL NOT NULL DEFAULT 0")
                if "command_until" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_until REAL NOT NULL DEFAULT 0")
                if "command_key" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_key TEXT NULL")
                if "command_vehicle_id" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_vehicle_id TEXT NULL")
                if "command_context_json" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_context_json TEXT NULL")
                if "command_poll_count" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_poll_count INTEGER NOT NULL DEFAULT 0")
                if "command_started_at" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_started_at REAL NOT NULL DEFAULT 0")
                if "last_presence_at" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN last_presence_at TEXT NULL")
                if "auth_required" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN auth_required INTEGER NOT NULL DEFAULT 0")
                if "credential_hash" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN credential_hash TEXT NULL")
                event_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(events)").fetchall()}
                if "sequence" not in event_columns:
                    db.execute("ALTER TABLE events ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0")
                if "semantic_hash" not in event_columns:
                    db.execute("ALTER TABLE events ADD COLUMN semantic_hash TEXT NULL")
                if "state_changed" not in event_columns:
                    db.execute("ALTER TABLE events ADD COLUMN state_changed INTEGER NOT NULL DEFAULT 1")
                if "event_kind" not in event_columns:
                    db.execute("ALTER TABLE events ADD COLUMN event_kind TEXT NOT NULL DEFAULT 'change'")
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS vehicle_state_cache (
                        subscription_id TEXT NOT NULL,
                        remote_id TEXT NOT NULL,
                        semantic_hash TEXT NOT NULL,
                        visual_fingerprint TEXT NULL,
                        last_source_at TEXT NULL,
                        last_queued_at REAL NOT NULL DEFAULT 0,
                        sequence INTEGER NOT NULL DEFAULT 0,
                        skipped_unchanged INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(subscription_id, remote_id),
                        FOREIGN KEY(subscription_id) REFERENCES subscriptions(subscription_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_vehicle_state_updated ON vehicle_state_cache(updated_at);
                    CREATE INDEX IF NOT EXISTS idx_events_vehicle_order ON events(subscription_id, remote_id, status, sequence);
                    """
                )
                # 1.11.92 podia converter "try again in 2 minutes" em 6 horas.
                # Somente cooldowns de LOGIN com prazo absurdo são liberados;
                # limites gerais de API continuam preservados.
                now_epoch = time.time()
                repaired = db.execute(
                    "UPDATE subscriptions SET status='waiting',cooldown_until=0,next_run_at=?,"
                    "consecutive_failures=0,updated_at=? WHERE status='cooldown' "
                    "AND cooldown_until>? AND (LOWER(COALESCE(last_error,'')) LIKE '%password error limit%' "
                    "OR LOWER(COALESCE(last_error,'')) LIKE '%try again in%' "
                    "OR LOWER(COALESCE(last_error,'')) LIKE '%login attempt limit%')",
                    (now_epoch + 2, utc_iso(), now_epoch + self.login_cooldown_max_seconds),
                ).rowcount
                if repaired:
                    LOG.warning("Corrigidos %s cooldown(s) de login com prazo inválido da versão anterior.", repaired)
                # Versões anteriores também podiam manter um limite geral sem
                # Retry-After por seis horas. Ele não é removido imediatamente:
                # é reduzido para uma reavaliação única e segura em cinco minutos.
                repaired_general = db.execute(
                    "UPDATE subscriptions SET cooldown_until=?,next_run_at=?,updated_at=? "
                    "WHERE status='cooldown' AND cooldown_until>? "
                    "AND LOWER(COALESCE(last_error,'')) NOT LIKE '%password error limit%' "
                    "AND LOWER(COALESCE(last_error,'')) NOT LIKE '%try again in%' "
                    "AND LOWER(COALESCE(last_error,'')) NOT LIKE '%login attempt limit%'",
                    (now_epoch + 300, now_epoch + 300, utc_iso(), now_epoch + 3600),
                ).rowcount
                if repaired_general:
                    LOG.warning("Reduzidos %s cooldown(s) gerais antigos para reavaliação segura em 300s.", repaired_general)

    def _set_account_login_cooldown(self, environment: str, account_id: int, retry_after_seconds: int, message: str) -> None:
        delay = max(30, min(self.login_cooldown_max_seconds, int(retry_after_seconds or 135)))
        until = time.time() + delay
        now = utc_iso()
        with self.lock, self._db() as db:
            rows = db.execute(
                "SELECT subscription_id FROM subscriptions WHERE environment=? AND account_id=?",
                (str(environment or ""), int(account_id or 0)),
            ).fetchall()
            db.execute(
                "UPDATE subscriptions SET status='cooldown',cooldown_until=?,next_run_at=?,last_error=?,updated_at=? "
                "WHERE environment=? AND account_id=?",
                (until, until, connector.clean_message(message)[:500], now, str(environment or ""), int(account_id or 0)),
            )
        for row in rows:
            self._close_session(str(row["subscription_id"] or ""))
        self.wake_event.set()

    def _clear_account_login_cooldown(self, environment: str, account_id: int) -> None:
        if int(account_id or 0) < 1:
            return
        now = utc_iso()
        with self.lock, self._db() as db:
            db.execute(
                "UPDATE subscriptions SET cooldown_until=0,status=CASE WHEN status='cooldown' THEN 'waiting' ELSE status END,"
                "next_run_at=CASE WHEN status='cooldown' THEN MIN(next_run_at,?) ELSE next_run_at END,"
                "last_error=CASE WHEN status='cooldown' THEN NULL ELSE last_error END,updated_at=? "
                "WHERE environment=? AND account_id=?",
                (time.time() + 2, now, str(environment or ""), int(account_id or 0)),
            )
        self.wake_event.set()

    def execute_command(
        self,
        environment: str,
        payload: dict[str, Any],
        progress: Callable[[str, str, dict[str, Any] | None], None] | None = None,
    ) -> dict[str, Any]:
        """Executa a ação sob a mesma sessão e trava usadas pela telemetria.

        Uma sessão válida nunca é destruída apenas porque o usuário acionou um
        comando. Se não houver sessão ativa, o conector mantém o fluxo isolado
        anterior como fallback. Falhas transitórias preservam a sessão.
        """
        try:
            account_id = int(payload.get("account_id") or 0)
        except (TypeError, ValueError):
            account_id = 0
        if account_id < 1:
            return connector.handle_command(payload, progress=progress)

        with self.lock, self._db() as db:
            row = db.execute(
                "SELECT subscription_id,cooldown_until,status FROM subscriptions "
                "WHERE environment=? AND account_id=? AND enabled=1 "
                "ORDER BY updated_at DESC LIMIT 1",
                (str(environment or ""), account_id),
            ).fetchone()
        if row is None:
            return connector.handle_command(payload, progress=progress)

        subscription_id = str(row["subscription_id"] or "")
        if not subscription_id:
            return connector.handle_command(payload, progress=progress)
        cooldown_until = float(row["cooldown_until"] or 0)
        if cooldown_until > time.time():
            raise connector.ConnectorLoginCooldownError(
                "A Leapmotor limitou temporariamente novas autenticações. O comando continua protegido na fila.",
                max(30, int(cooldown_until - time.time())),
            )

        def isolated_command() -> dict[str, Any]:
            try:
                result = connector.handle_command(payload, progress=progress)
                self._clear_account_login_cooldown(environment, account_id)
                return result
            except connector.ConnectorLoginCooldownError as exc:
                self._set_account_login_cooldown(environment, account_id, exc.retry_after_seconds, str(exc))
                raise

        with self._session_operation_lock(subscription_id):
            with self.session_lock:
                session = self.sessions.get(subscription_id)
            if not isinstance(session, dict) or session.get("client") is None:
                return isolated_command()

            now_epoch = time.time()
            command_credentials = payload.get("credentials") if isinstance(payload.get("credentials"), dict) else {}
            session_credentials = dict(command_credentials)
            session_credentials.pop("operation_password", None)
            expected_hash = hashlib.sha256(canonical_json(session_credentials)).hexdigest() if session_credentials else ""
            session_stale = (
                expected_hash == ""
                or session.get("credential_hash") != expected_hash
                or now_epoch - float(session.get("created_at") or 0) >= self.session_max_age_seconds
                or now_epoch - float(session.get("last_used_at") or 0) >= self.session_idle_seconds
            )
            if session_stale:
                self._close_session_locked(subscription_id)
                return isolated_command()

            session["last_used_at"] = now_epoch
            try:
                result = connector.handle_command(
                    payload,
                    progress=progress,
                    borrowed_client=session["client"],
                    borrowed_vehicles=session.get("vehicles") if isinstance(session.get("vehicles"), list) else None,
                )
                session["last_used_at"] = time.time()
                self._clear_account_login_cooldown(environment, account_id)
                return result
            except Exception as exc:
                session["last_used_at"] = time.time()
                if connector.is_command_certificate_session_error(exc):
                    # cert/sync recusou o token antes da ação chegar ao veículo.
                    # A sessão compartilhada é descartada e o mesmo comando é
                    # tentado uma única vez em uma autenticação limpa. Outros
                    # erros de token, especialmente após aceite, nunca entram aqui.
                    LOG.warning(
                        "Sessão de %s expirou durante cert/sync; recriando uma única vez antes do envio.",
                        subscription_id,
                    )
                    self._close_session_locked(subscription_id)
                    if progress is not None:
                        try:
                            progress(
                                "reconnecting",
                                "A sessão expirou antes do envio. Criando uma conexão limpa e protegida.",
                                {"session_recovery": True},
                            )
                        except Exception:
                            pass
                    recovered = isolated_command()
                    recovered["session_recovered"] = True
                    recovered["session_reused"] = False
                    return recovered
                if isinstance(exc, connector.ConnectorLoginCooldownError):
                    self._set_account_login_cooldown(environment, account_id, exc.retry_after_seconds, str(exc))
                if connector.is_authentication_error(exc):
                    self._close_session_locked(subscription_id)
                raise

    def invalidate_account_session(self, environment: str, payload: dict[str, Any]) -> int:
        """Feche a sessão automática antes de uma operação manual da conta.

        A nuvem pode rejeitar dois tokens simultâneos. O servidor chama este
        método somente depois de adquirir a trava exclusiva da conta.
        """
        try:
            account_id = int(payload.get("account_id") or 0)
        except (TypeError, ValueError):
            account_id = 0
        if account_id < 1:
            return 0
        with self.lock, self._db() as db:
            rows = db.execute(
                "SELECT subscription_id FROM subscriptions WHERE environment=? AND account_id=?",
                (str(environment or ""), account_id),
            ).fetchall()
        for row in rows:
            self._close_session(str(row["subscription_id"]))
        if rows:
            LOG.info("Sessão automática de %s conta(s) encerrada antes da operação manual para evitar conflito de token.", len(rows))
        return len(rows)

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        # O worker respeita next_run_at exatamente como foi persistido. Reiniciar
        # o App não antecipa cooldown nem espera progressiva.
        self.worker = threading.Thread(target=self._run, name="leaphub-telemetry", daemon=True)
        self.worker.start()
        LOG.info("Telemetria contínua iniciada com fila persistente em %s.", self.db_path)

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=12)
        self._close_all_sessions()

    def upsert(self, environment: str, payload: dict[str, Any]) -> dict[str, Any]:
        subscription_id = str(payload.get("subscription_id") or "").strip()[:190]
        account_id = int(payload.get("account_id") or 0)
        credentials = payload.get("credentials")
        ids = payload.get("vehicle_ids")
        enabled = bool(payload.get("enabled", True))
        credentials_verified = bool(payload.get("credentials_verified", False))
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

        now = utc_iso()
        now_epoch = time.time()
        credential_hash = hashlib.sha256(canonical_json(credentials)).hexdigest()
        with self.lock, self._db() as db:
            existing = db.execute(
                "SELECT credential_hash, credentials_encrypted, auth_required, cooldown_until, active_until, interactive_until, command_until, next_run_at, status, enabled "
                "FROM subscriptions WHERE subscription_id=? LIMIT 1",
                (subscription_id,),
            ).fetchone()

        previous_hash = str(existing["credential_hash"] or "") if existing is not None else ""
        if existing is not None and not previous_hash:
            # Primeira execução após atualizar uma base antiga: calcula o hash
            # das credenciais já armazenadas para não apagar cooldown ou bloqueio
            # de autenticação apenas porque a coluna ainda estava vazia.
            try:
                previous_payload = self.fernet.decrypt(bytes(existing["credentials_encrypted"]))
                previous_hash = hashlib.sha256(previous_payload).hexdigest()
            except (InvalidToken, ValueError, TypeError):
                previous_hash = ""
        credentials_changed = existing is None or not previous_hash or not hmac.compare_digest(previous_hash, credential_hash)
        existing_auth_required = bool(existing is not None and int(existing["auth_required"] or 0) == 1)
        existing_cooldown_until = float(existing["cooldown_until"] or 0) if existing is not None else 0.0
        protected_auth = enabled and existing_auth_required and not credentials_changed and not credentials_verified
        protected_cooldown = enabled and existing_cooldown_until > now_epoch and not credentials_changed and not credentials_verified

        # Reenvios comuns com as mesmas credenciais preservam a proteção. O site
        # pode enviar credentials_verified somente depois de uma consulta manual
        # bem-sucedida à nuvem. Essa confirmação assinada elimina o bloqueio preso
        # sem exigir que o usuário altere e salve a mesma senha novamente.
        if protected_auth:
            status = "auth_required"
            active_until = 0.0
            interactive_until = 0.0
            command_until = 0.0
            next_run = now_epoch + 86400
            auth_required = 1
            cooldown_until = 0.0
        elif protected_cooldown:
            status = "cooldown"
            active_until = 0.0
            interactive_until = 0.0
            command_until = 0.0
            next_run = existing_cooldown_until
            auth_required = 0
            cooldown_until = existing_cooldown_until
        elif not enabled:
            status = "disabled"
            active_until = 0.0
            interactive_until = 0.0
            command_until = 0.0
            next_run = now_epoch + self.sleep_seconds
            auth_required = 0
            cooldown_until = 0.0
        else:
            status = "waiting"
            previous_active = float(existing["active_until"] or 0) if existing is not None else 0.0
            active_until = max(previous_active, now_epoch + self.presence_window_seconds)
            previous_interactive = float(existing["interactive_until"] or 0) if existing is not None and not credentials_changed else 0.0
            interactive_until = max(0.0, previous_interactive)
            previous_command = float(existing["command_until"] or 0) if existing is not None and not credentials_changed else 0.0
            command_until = max(0.0, previous_command)
            previous_next = float(existing["next_run_at"] or 0) if existing is not None else 0.0
            next_run = min(previous_next, now_epoch + 1.0) if previous_next > now_epoch else now_epoch + random.uniform(0.5, 1.5)
            auth_required = 0
            cooldown_until = 0.0

        if credentials_changed or credentials_verified or not enabled or protected_auth or protected_cooldown:
            self._close_session(subscription_id)
        encrypted = self.fernet.encrypt(canonical_json(credentials))
        with self.lock, self._db() as db:
            db.execute(
                """
                INSERT INTO subscriptions
                (subscription_id, environment, account_id, credentials_encrypted, vehicle_ids_json, enabled, status, next_run_at,
                 last_run_at, last_success_at, last_delivery_at, last_error, last_state, parked_streak, consecutive_failures,
                 cooldown_until, active_until, interactive_until, command_until, last_presence_at, auth_required, credential_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subscription_id) DO UPDATE SET
                    environment=excluded.environment, account_id=excluded.account_id,
                    credentials_encrypted=excluded.credentials_encrypted, vehicle_ids_json=excluded.vehicle_ids_json,
                    enabled=excluded.enabled, status=excluded.status, next_run_at=excluded.next_run_at,
                    last_error=CASE WHEN excluded.status IN ('auth_required','cooldown') THEN subscriptions.last_error ELSE NULL END,
                    consecutive_failures=CASE WHEN excluded.status IN ('auth_required','cooldown') THEN subscriptions.consecutive_failures ELSE 0 END,
                    cooldown_until=excluded.cooldown_until, active_until=excluded.active_until,
                    interactive_until=excluded.interactive_until,
                    command_until=excluded.command_until,
                    last_presence_at=excluded.last_presence_at, auth_required=excluded.auth_required,
                    credential_hash=excluded.credential_hash, updated_at=excluded.updated_at
                """,
                (subscription_id, environment, account_id, encrypted, json.dumps(vehicle_ids), 1 if enabled else 0,
                 status, next_run, cooldown_until, active_until, interactive_until, command_until, now, auth_required, credential_hash, now, now),
            )

        self.wake_event.set()
        if protected_auth:
            return {
                "ok": False,
                "subscription_id": subscription_id,
                "auth_required": True,
                "protected": True,
                "credentials_changed": False,
                "message": "Credenciais recusadas anteriormente; confirme a conta antes de uma nova tentativa.",
            }
        if protected_cooldown:
            return {
                "ok": False,
                "subscription_id": subscription_id,
                "cooldown": True,
                "protected": True,
                "credentials_changed": False,
                "retry_after_seconds": max(1, int(existing_cooldown_until - now_epoch)),
                "message": "Proteção contra limite de requisições ainda está ativa.",
            }
        return {
            "ok": True,
            "subscription_id": subscription_id,
            "vehicle_count": len(vehicle_ids),
            "active_seconds": max(0, int(active_until - time.time())),
            "next_run_seconds": int(max(0, next_run - time.time())),
            "credentials_changed": credentials_changed,
            "credentials_verified": credentials_verified,
            "auth_reset": credentials_verified and existing_auth_required,
            "cooldown_reset": credentials_verified and existing_cooldown_until > now_epoch,
            "session_preserved": not credentials_changed and not credentials_verified and self._has_session(subscription_id),
        }

    def remove(self, subscription_id: str) -> dict[str, Any]:
        subscription_id = str(subscription_id or "").strip()[:190]
        if not subscription_id:
            raise ValueError("Identificador da assinatura ausente.")
        self._close_session(subscription_id)
        with self.lock, self._db() as db:
            cursor = db.execute(
                "UPDATE subscriptions SET enabled=0, status='disabled', active_until=0, interactive_until=0, command_until=0, command_key=NULL, command_vehicle_id=NULL, command_context_json=NULL, command_poll_count=0, command_started_at=0, updated_at=? WHERE subscription_id=?",
                (utc_iso(), subscription_id),
            )
        self.wake_event.set()
        return {"ok": True, "subscription_id": subscription_id, "disabled": cursor.rowcount > 0}

    def release_interactive(self, subscription_id: str) -> dict[str, Any]:
        subscription_id = str(subscription_id or "").strip()[:190]
        if not subscription_id:
            raise ValueError("Identificador da assinatura ausente.")
        now_epoch = time.time()
        now_iso = utc_iso()
        with self.lock, self._db() as db:
            row = db.execute(
                "SELECT enabled, status, next_run_at, command_until FROM subscriptions WHERE subscription_id=? LIMIT 1",
                (subscription_id,),
            ).fetchone()
            if row is None:
                return {"ok": True, "subscription_id": subscription_id, "released": False}
            status = str(row["status"] or "")
            next_run = float(row["next_run_at"] or 0)
            command_active = float(row["command_until"] or 0) > now_epoch
            # Fechar a aba remove somente a janela interativa normal. Uma janela
            # de confirmação criada por comando remoto continua ativa para que o
            # carro possa acordar e o novo estado chegue mesmo sem a tela aberta.
            if command_active:
                if status not in {"auth_required", "cooldown", "recovering", "error"}:
                    status = "waiting"
                    next_run = min(next_run, now_epoch + 0.5) if next_run > now_epoch else now_epoch + 0.5
            elif status not in {"auth_required", "cooldown", "recovering", "error"}:
                status = "idle"
                next_run = max(next_run, now_epoch + self.sleep_seconds)
            cursor = db.execute(
                "UPDATE subscriptions SET status=?,interactive_until=0,next_run_at=?,updated_at=? WHERE subscription_id=?",
                (status, next_run, now_iso, subscription_id),
            )
        self.wake_event.set()
        return {
            "ok": True,
            "subscription_id": subscription_id,
            "released": cursor.rowcount > 0,
            "command_window_preserved": command_active,
            "session_preserved": self._has_session(subscription_id),
        }

    def boost(
        self,
        subscription_id: str,
        seconds: int = 900,
        profile: str = "background",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        subscription_id = str(subscription_id or "").strip()[:190]
        requested_profile = str(profile or "").strip().lower()
        context = context if isinstance(context, dict) else {}
        command_key = str(context.get("command_key") or "").strip()[:80]
        command_vehicle_id = str(context.get("vehicle_remote_id") or "").strip()[:190]
        safe_context = {
            "command_id": int(context.get("command_id") or 0),
            "parameters": context.get("parameters") if isinstance(context.get("parameters"), dict) else {},
            "request_id": str(context.get("request_id") or "")[:96],
        }
        command_context_json = json.dumps(safe_context, ensure_ascii=False, separators=(",", ":"))[:4000]
        profile = requested_profile if requested_profile in {"background", "interactive", "command"} else "background"
        if profile == "command":
            seconds = max(30, min(180, int(seconds)))
        elif profile == "interactive":
            seconds = max(60, min(3600, int(seconds)))
        else:
            seconds = max(300, min(3600, int(seconds)))
        now_epoch = time.time()
        now_iso = utc_iso()
        with self.lock, self._db() as db:
            row = db.execute(
                "SELECT auth_required, cooldown_until, enabled, next_run_at, status FROM subscriptions WHERE subscription_id=? LIMIT 1",
                (subscription_id,),
            ).fetchone()
            if row is None or int(row["enabled"] or 0) != 1:
                return {"ok": False, "subscription_id": subscription_id, "message": "Assinatura inexistente ou desativada."}
            if int(row["auth_required"] or 0) == 1:
                return {"ok": False, "subscription_id": subscription_id, "auth_required": True, "message": "Credenciais precisam ser confirmadas antes de retomar."}
            cooldown_until = float(row["cooldown_until"] or 0)
            if cooldown_until > now_epoch:
                return {
                    "ok": False,
                    "subscription_id": subscription_id,
                    "cooldown": True,
                    "retry_after_seconds": int(cooldown_until - now_epoch),
                    "message": "Proteção contra limite de requisições ainda está ativa.",
                }
            current_next = float(row["next_run_at"] or 0)
            current_status = str(row["status"] or "").strip().lower()
            protected_wait = current_status in {"recovering", "error", "cooldown", "auth_required"} and current_next > now_epoch
            requested_next = now_epoch + 0.35
            next_run = current_next if protected_wait else (min(current_next, requested_next) if current_next > now_epoch else requested_next)
            interactive_until = now_epoch + seconds if profile == "interactive" else 0.0
            command_until = now_epoch + seconds if profile == "command" else 0.0
            if protected_wait:
                cursor = db.execute(
                    "UPDATE subscriptions SET active_until=MAX(active_until,?),interactive_until=MAX(interactive_until,?),"
                    "command_until=MAX(command_until,?),last_presence_at=?,updated_at=? WHERE subscription_id=? AND enabled=1",
                    (now_epoch + seconds, interactive_until, command_until, now_iso, now_iso, subscription_id),
                )
                return {
                    "ok": True,
                    "subscription_id": subscription_id,
                    "profile": profile,
                    "protected_wait": True,
                    "retry_after_seconds": max(1, int(current_next - now_epoch)),
                }
            if profile == "command":
                cursor = db.execute(
                    "UPDATE subscriptions SET status='waiting', next_run_at=?, active_until=MAX(active_until, ?), "
                    "interactive_until=MAX(interactive_until, ?), command_until=?, command_key=?, command_vehicle_id=?, "
                    "command_context_json=?, command_poll_count=0, command_started_at=?, "
                    "last_presence_at=?, last_error=NULL, updated_at=? WHERE subscription_id=? AND enabled=1",
                    (
                        next_run,
                        now_epoch + seconds,
                        interactive_until,
                        command_until,
                        command_key or None,
                        command_vehicle_id or None,
                        command_context_json,
                        now_epoch,
                        now_iso,
                        now_iso,
                        subscription_id,
                    ),
                )
            elif profile == "interactive":
                cursor = db.execute(
                    "UPDATE subscriptions SET status='waiting', next_run_at=?, active_until=MAX(active_until, ?), "
                    "interactive_until=MAX(interactive_until, ?), last_presence_at=?, last_error=NULL, updated_at=? "
                    "WHERE subscription_id=? AND enabled=1",
                    (next_run, now_epoch + seconds, interactive_until, now_iso, now_iso, subscription_id),
                )
            else:
                cursor = db.execute(
                    "UPDATE subscriptions SET status='waiting', next_run_at=?, active_until=MAX(active_until, ?), "
                    "last_presence_at=?, last_error=NULL, updated_at=? WHERE subscription_id=? AND enabled=1",
                    (next_run, now_epoch + seconds, now_iso, now_iso, subscription_id),
                )
        self.wake_event.set()
        return {
            "ok": cursor.rowcount > 0,
            "subscription_id": subscription_id,
            "boost_seconds": seconds,
            "profile": profile,
            "interactive": profile in {"interactive", "command"},
            "command_confirmation": profile == "command",
            "adaptive_polling": profile == "command",
            "poll_schedule_seconds": list(self.command_cadence) if profile == "command" else [self.interactive_seconds],
            "max_command_polls": self.command_max_polls if profile == "command" else None,
        }

    def storage_status(self) -> dict[str, Any]:
        now = time.time()
        return {
            "healthy": bool(self.storage_healthy),
            "path": str(self.db_path),
            "journal_mode": self.storage_journal_mode,
            "consecutive_failures": int(self.storage_failures),
            "last_error": self.storage_last_error or None,
            "last_error_at": self.storage_last_error_at or None,
            "retry_in_seconds": max(0, int(self.storage_next_retry_at - now)),
        }

    def status_fast(self) -> dict[str, Any]:
        """Bounded health snapshot that never holds Cloudflare health checks hostage."""
        acquired = self.lock.acquire(timeout=0.15)
        if not acquired:
            return {
                "ok": True,
                "busy": True,
                "message": "Telemetria ocupada em uma coleta; armazenamento continua ativo.",
                "storage": self.storage_status(),
            }
        try:
            with self._db(0.2) as db:
                row = db.execute(
                    "SELECT COUNT(*) subscriptions, "
                    "SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) enabled, "
                    "SUM(CASE WHEN status IN ('error','auth_required') THEN 1 ELSE 0 END) errors "
                    "FROM subscriptions"
                ).fetchone()
                pending = db.execute("SELECT COUNT(*) FROM events WHERE status='pending'").fetchone()[0]
            return {
                "ok": True,
                "storage": self.storage_status(),
                "subscriptions": int(row["subscriptions"] or 0),
                "enabled_subscriptions": int(row["enabled"] or 0),
                "subscriptions_with_errors": int(row["errors"] or 0),
                "pending_events": int(pending or 0),
            }
        except (OSError, sqlite3.Error) as exc:
            return {
                "ok": True,
                "busy": True,
                "message": "Resumo temporariamente ocupado; o worker permanece ativo.",
                "storage": self.storage_status(),
                "detail": str(exc)[:160],
            }
        finally:
            self.lock.release()

    def status(self) -> dict[str, Any]:
        try:
            with self.lock, self._db() as db:
                totals = db.execute(
                    "SELECT COUNT(*) subscriptions, SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) enabled, "
                    "SUM(CASE WHEN status IN ('error','auth_required') THEN 1 ELSE 0 END) errors, "
                    "SUM(CASE WHEN enabled=1 AND active_until>? THEN 1 ELSE 0 END) active_windows, "
                    "SUM(CASE WHEN enabled=1 AND interactive_until>? THEN 1 ELSE 0 END) interactive_windows, "
                    "SUM(CASE WHEN enabled=1 AND command_until>? THEN 1 ELSE 0 END) command_windows FROM subscriptions",
                    (time.time(), time.time(), time.time()),
                ).fetchone()
                queue = db.execute(
                    "SELECT COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) pending, "
                    "COALESCE(SUM(CASE WHEN status='delivered' THEN 1 ELSE 0 END),0) delivered, "
                    "MIN(CASE WHEN status='pending' THEN created_at END) oldest_pending FROM events"
                ).fetchone()
                recent = [dict(row) for row in db.execute(
                    "SELECT subscription_id, environment, account_id, status, last_run_at, last_success_at, last_delivery_at, "
                    "last_error, last_state, next_run_at, active_until, interactive_until, command_until, command_key, command_vehicle_id, command_poll_count, command_started_at, last_presence_at, auth_required, cooldown_until "
                    "FROM subscriptions ORDER BY updated_at DESC LIMIT 20"
                ).fetchall()]
                dedupe = db.execute(
                    "SELECT COALESCE(SUM(skipped_unchanged),0) skipped, COUNT(*) vehicles, MAX(updated_at) last_state_update FROM vehicle_state_cache"
                ).fetchone()
                recent_states = [dict(row) for row in db.execute(
                    "SELECT subscription_id, remote_id, sequence, skipped_unchanged, last_source_at, updated_at FROM vehicle_state_cache ORDER BY updated_at DESC LIMIT 20"
                ).fetchall()]
        except (OSError, sqlite3.Error) as exc:
            self._record_storage_failure(exc)
            return {
                "ok": False,
                "message": "Fila persistente temporariamente indisponível.",
                "storage": self.storage_status(),
                "subscriptions": 0,
                "enabled_subscriptions": 0,
                "pending_events": 0,
                "recent_vehicle_states": [],
                "recent": [],
            }
        self._record_storage_success()
        now_epoch = time.time()
        for item in recent:
            item["next_run_in_seconds"] = max(0, int(float(item.pop("next_run_at") or 0) - now_epoch))
            item["active_for_seconds"] = max(0, int(float(item.pop("active_until") or 0) - now_epoch))
            item["interactive_for_seconds"] = max(0, int(float(item.pop("interactive_until") or 0) - now_epoch))
            item["command_for_seconds"] = max(0, int(float(item.pop("command_until") or 0) - now_epoch))
            item["command_started_seconds_ago"] = max(0, int(now_epoch - float(item.pop("command_started_at") or now_epoch)))
            item["cooldown_seconds"] = max(0, int(float(item.pop("cooldown_until") or 0) - now_epoch))
            item["session_reused"] = self._has_session(str(item.get("subscription_id") or ""))
            if item.get("last_error"):
                item["last_error"] = str(item["last_error"])[:240]
        return {
            "ok": True,
            "storage": self.storage_status(),
            "subscriptions": int(totals["subscriptions"] or 0),
            "enabled_subscriptions": int(totals["enabled"] or 0),
            "active_windows": int(totals["active_windows"] or 0),
            "interactive_windows": int(totals["interactive_windows"] or 0),
            "command_windows": int(totals["command_windows"] or 0),
            "subscription_errors": int(totals["errors"] or 0),
            "pending_events": int(queue["pending"] or 0),
            "delivered_events": int(queue["delivered"] or 0),
            "oldest_pending": queue["oldest_pending"],
            "deduplicated_events": int(dedupe["skipped"] or 0),
            "tracked_vehicles": int(dedupe["vehicles"] or 0),
            "last_state_update": dedupe["last_state_update"],
            "profiles": {
                "driving_seconds": self.active_seconds,
                "interactive_seconds": self.interactive_seconds,
                "command_seconds": self.command_seconds,
                "command_cadence_seconds": list(self.command_cadence),
                "command_max_polls": self.command_max_polls,
                "manual_priority": self.manual_pending_provider is not None,
                "charging_seconds": self.charging_seconds,
                "charge_watch_seconds": self.charge_watch_seconds,
                "parked_seconds": self.parked_seconds,
                "sleep_seconds": self.sleep_seconds,
                "rate_limit_cooldown_seconds": self.rate_limit_cooldown_seconds,
                "presence_window_seconds": self.presence_window_seconds,
                "presence_driven": True,
                "session_reuse": True,
            },
            "recent_vehicle_states": recent_states,
            "recent": recent,
        }

    def _record_storage_failure(self, exc: BaseException) -> float:
        self.storage_healthy = False
        self.storage_failures += 1
        message = str(exc).strip() or type(exc).__name__
        self.storage_last_error = message[:240]
        self.storage_last_error_at = utc_iso()
        steps = (2, 5, 10, 20, 30, 60, 120, 300)
        delay = float(steps[min(self.storage_failures - 1, len(steps) - 1)])
        now = time.time()
        self.storage_next_retry_at = now + delay
        if self.storage_failures == 1 or now >= self.storage_next_log_at:
            LOG.error(
                "Fila SQLite indisponível (%s). Nova tentativa em %ss. Caminho: %s",
                self.storage_last_error,
                int(delay),
                self.db_path,
            )
            self.storage_next_log_at = now + max(30.0, delay)
        try:
            self._prepare_storage(probe=True)
        except OSError:
            pass
        return delay

    def _record_storage_success(self) -> None:
        if self.storage_failures > 0:
            LOG.info("Acesso à fila SQLite recuperado em %s.", self.db_path)
        self.storage_healthy = True
        self.storage_failures = 0
        self.storage_last_error = ""
        self.storage_last_error_at = ""
        self.storage_next_retry_at = 0.0
        self.storage_next_log_at = 0.0

    def _run(self) -> None:
        while not self.stop_event.is_set():
            did_work = False
            storage_wait: float | None = None
            try:
                did_work = self._deliver_due() or did_work
                subscription = self._next_due_subscription()
                if subscription is not None:
                    self._poll_subscription(subscription)
                    did_work = True
                self._maintenance()
                self._record_storage_success()
            except (OSError, sqlite3.Error) as exc:
                storage_wait = self._record_storage_failure(exc)
            except Exception:  # noqa: BLE001
                LOG.exception("Falha no ciclo de telemetria")
            if storage_wait is not None:
                wait = storage_wait
            else:
                try:
                    wait = 0.5 if did_work else min(5.0, self._seconds_until_next())
                except (OSError, sqlite3.Error) as exc:
                    wait = self._record_storage_failure(exc)
            self.wake_event.wait(max(0.25, wait))
            self.wake_event.clear()

    def _next_due_subscription(self) -> sqlite3.Row | None:
        with self.lock, self._db() as db:
            now_epoch = time.time()
            return db.execute(
                "SELECT * FROM subscriptions WHERE enabled=1 AND auth_required=0 AND active_until>? AND next_run_at<=? "
                "ORDER BY CASE WHEN command_until>? THEN 0 WHEN interactive_until>? THEN 1 ELSE 2 END, next_run_at ASC LIMIT 1",
                (now_epoch, now_epoch, now_epoch, now_epoch),
            ).fetchone()

    def _seconds_until_next(self) -> float:
        with self.lock, self._db() as db:
            row = db.execute("SELECT MIN(next_run_at) due FROM subscriptions WHERE enabled=1 AND auth_required=0 AND active_until>?", (time.time(),)).fetchone()
            delivery = db.execute("SELECT MIN(next_attempt_at) due FROM events WHERE status='pending'").fetchone()
        values = [float(item["due"]) for item in (row, delivery) if item and item["due"] is not None]
        return max(0.25, min(values) - time.time()) if values else 5.0

    def _poll_subscription(self, subscription: sqlite3.Row) -> None:
        sid = str(subscription["subscription_id"])
        now_epoch = time.time()
        active_until = float(subscription["active_until"] or 0)
        interactive = float(subscription["interactive_until"] or 0) > now_epoch
        command_mode = float(subscription["command_until"] or 0) > now_epoch
        fast_mode = interactive or command_mode
        if active_until <= now_epoch:
            self._close_session(sid)
            with self.lock, self._db() as db:
                db.execute(
                    "UPDATE subscriptions SET status='idle', next_run_at=?, interactive_until=0, command_until=0, command_key=NULL, command_vehicle_id=NULL, command_context_json=NULL, command_poll_count=0, command_started_at=0, last_error=NULL, updated_at=? WHERE subscription_id=?",
                    (now_epoch + self.sleep_seconds, utc_iso(), sid),
                )
            return

        with self.lock, self._db() as db:
            queued = int(db.execute("SELECT COUNT(*) FROM events WHERE status='pending'").fetchone()[0])
        if queued >= self.queue_max:
            self._reschedule(sid, 300, "queue_full", "Fila persistente atingiu o limite; aguardando entrega ao site.", failed=False)
            LOG.error("Fila de telemetria cheia (%s eventos). Coleta pausada até a entrega liberar espaço.", queued)
            return

        cooldown_until = float(subscription["cooldown_until"] or 0)
        if cooldown_until > now_epoch:
            self._close_session(sid)
            self._reschedule(sid, max(60, int(cooldown_until - now_epoch)), "cooldown", "Proteção de limite ativa; aguardando antes da próxima consulta.", failed=False)
            return
        environment = str(subscription["environment"])
        if not self.environment_enabled.get(environment, False) or not self.delivery_urls.get(environment):
            self._close_session(sid)
            self._reschedule(sid, self.sleep_seconds, "disabled", "URL de entrega ou ambiente desativado.", failed=False)
            return
        try:
            credentials = json.loads(self.fernet.decrypt(bytes(subscription["credentials_encrypted"])).decode("utf-8"))
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._close_session(sid)
            self._mark_auth_required(sid, "Credenciais locais não puderam ser descriptografadas.")
            LOG.error("Assinatura %s com credencial inválida: %s", sid, exc)
            return
        try:
            vehicle_ids = set(json.loads(str(subscription["vehicle_ids_json"])))
        except (ValueError, TypeError, json.JSONDecodeError):
            vehicle_ids = set()
        command_target_vehicle = str(subscription["command_vehicle_id"] or "").strip()
        if command_mode and command_target_vehicle:
            vehicle_ids = {command_target_vehicle}

        operation_payload = {
            "account_id": int(subscription["account_id"] or 0),
            "credentials": credentials,
        }
        if self.manual_pending_provider is not None and self.manual_pending_provider(environment, operation_payload):
            credentials.clear()
            self._reschedule(sid, 2, "waiting", "Comando do usuário tem prioridade sobre a telemetria automática.", failed=False)
            return

        acquired = self.operation_semaphore.acquire(timeout=5)
        if not acquired:
            credentials.clear()
            self._reschedule(sid, 30, "waiting", "Aguardando vaga no Connector.", failed=False)
            return

        if self.manual_pending_provider is not None and self.manual_pending_provider(environment, operation_payload):
            self.operation_semaphore.release()
            credentials.clear()
            self._reschedule(sid, 2, "waiting", "Comando do usuário aguardando execução; telemetria cedendo a conexão.", failed=False)
            return

        account_lock = None
        account_acquired = False
        if self.account_lock_provider is not None:
            account_lock = self.account_lock_provider(environment, operation_payload)
            account_acquired = account_lock.acquire(timeout=self.account_wait_seconds)
            if not account_acquired:
                self.operation_semaphore.release()
                credentials.clear()
                self._reschedule(
                    sid,
                    15,
                    "waiting",
                    "A conta já está sendo consultada por outra operação; a telemetria aguardará sem criar outro login.",
                    failed=False,
                )
                return
        manual_should_yield = (
            (lambda: bool(self.manual_pending_provider and self.manual_pending_provider(environment, operation_payload)))
            if self.manual_pending_provider is not None
            else None
        )
        try:
            result = self._collect_with_session(
                sid,
                credentials,
                vehicle_ids,
                command_mode=command_mode,
                manual_should_yield=manual_should_yield,
            )
        except TelemetryYieldForManual:
            self._reschedule(sid, 2, "waiting", "Telemetria cedeu a conta para o comando do usuário.", failed=False)
            LOG.info("Telemetria de %s interrompida em ponto seguro para priorizar comando manual.", sid)
            return
        except Exception as exc:  # noqa: BLE001
            message = connector.clean_message(str(exc))
            failures = int(subscription["consecutive_failures"] or 0) + 1
            transient = connector.is_transient_cloud_error(exc) or isinstance(exc, connector.ConnectorTemporaryError)
            if not transient or failures >= 3:
                self._close_session(sid)
            if isinstance(exc, connector.ConnectorLoginCooldownError):
                self._close_session(sid)
                delay = max(30, min(self.login_cooldown_max_seconds, int(exc.retry_after_seconds or 135)))
                now = utc_iso()
                with self.lock, self._db() as db:
                    db.execute(
                        "UPDATE subscriptions SET status='cooldown',cooldown_until=?,next_run_at=?,last_run_at=?,last_error=?,consecutive_failures=consecutive_failures+1,updated_at=? WHERE subscription_id=?",
                        (time.time() + delay, time.time() + delay, now, message[:500], now, sid),
                    )
                LOG.warning("Autenticação de %s aguardará %ss antes da próxima tentativa; credenciais permanecem protegidas.", sid, delay)
            elif self._looks_rate_limited(message):
                self._close_session(sid)
                delay = connector.rate_limit_cooldown_seconds(message, self.rate_limit_cooldown_seconds)
                if delay <= 0:
                    delay = self.rate_limit_cooldown_seconds
                now = utc_iso()
                with self.lock, self._db() as db:
                    db.execute(
                        "UPDATE subscriptions SET status='cooldown', cooldown_until=?, active_until=0, interactive_until=0, command_until=0, command_key=NULL, command_vehicle_id=NULL, command_context_json=NULL, command_poll_count=0, command_started_at=0, next_run_at=?, last_run_at=?, last_error=?, consecutive_failures=consecutive_failures+1, updated_at=? WHERE subscription_id=?",
                        (time.time() + delay, time.time() + delay, now, message[:500], now, sid),
                    )
                LOG.warning("Proteção contra limite ativada para %s por %ss: %s", sid, delay, message)
            elif isinstance(exc, connector.ConnectorAuthenticationError) or connector.is_authentication_error(exc):
                self._mark_auth_required(sid, message)
                LOG.warning("A assinatura %s foi pausada até as credenciais serem confirmadas: %s", sid, message)
            elif transient:
                verification_challenge = any(marker in message.lower() for marker in (
                    "information verification failed",
                    "please try again later",
                ))
                if verification_challenge:
                    # Logo após um comando a nuvem pode invalidar o token usado
                    # na leitura anterior. Em janela de confirmação, encerra a
                    # sessão e tenta uma única reconexão moderada antes de adotar
                    # o backoff conservador normal.
                    self._close_session(sid)
                    schedule = (30, 60, 180, 600, 1800, 3600) if command_mode else (120, 300, 900, 1800, 3600, 10800)
                    delay = schedule[min(max(1, failures) - 1, len(schedule) - 1)]
                else:
                    delay = self._transient_backoff(failures, fast_mode)
                self._reschedule(sid, delay, "recovering", message, failed=True)
                if failures >= 3:
                    LOG.warning("Sessão Leapmotor de %s será refeita após %ss por falhas temporárias repetidas: %s", sid, delay, message)
                else:
                    LOG.warning("Falha temporária em %s; sessão preservada e nova leitura em %ss: %s", sid, delay, message)
            else:
                delay = self._failure_backoff(failures)
                self._reschedule(sid, delay, "error", message, failed=True)
            return
        finally:
            if account_acquired and account_lock is not None:
                account_lock.release()
            self.operation_semaphore.release()
            credentials.clear()

        vehicles = [item for item in (result.get("vehicles") or []) if isinstance(item, dict)]
        if vehicle_ids:
            vehicles = [item for item in vehicles if str(item.get("remote_id") or "") in vehicle_ids]
        if not vehicles:
            self._close_session(sid)
            self._reschedule(sid, self._failure_backoff(int(subscription["consecutive_failures"] or 0) + 1), "error", "Nenhum veículo autorizado foi retornado.", failed=True)
            return

        states: list[str] = []
        queued_events = 0
        skipped_events = 0
        for vehicle in vehicles:
            telemetry = vehicle.get("telemetry") if isinstance(vehicle.get("telemetry"), dict) else {}
            source_at = str(telemetry.get("captured_at") or utc_iso())
            state = self._state_of(telemetry)
            states.append(state)
            queued = self._queue_event(subscription, vehicle, source_at, state, interactive=fast_mode)
            if queued.get("queued"):
                queued_events += 1
            else:
                skipped_events += 1

        previous_state = str(subscription["last_state"] or "")
        current_command_poll = int(subscription["command_poll_count"] or 0)
        command_confirmed = False
        command_evaluable = False
        command_key = str(subscription["command_key"] or "")
        command_vehicle_id = str(subscription["command_vehicle_id"] or "")
        command_context: dict[str, Any] = {}
        try:
            parsed_context = json.loads(str(subscription["command_context_json"] or "{}"))
            command_context = parsed_context if isinstance(parsed_context, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            command_context = {}

        command_target_seen = False
        if command_mode and command_key:
            for vehicle in vehicles:
                if command_vehicle_id and str(vehicle.get("remote_id") or "") != command_vehicle_id:
                    continue
                command_target_seen = True
                telemetry = vehicle.get("telemetry") if isinstance(vehicle.get("telemetry"), dict) else {}
                if not self._command_sample_is_fresh(telemetry, float(subscription["command_started_at"] or 0)):
                    continue
                matched, evaluable = self._command_confirmation(command_key, telemetry, command_context)
                command_evaluable = command_evaluable or evaluable
                if matched:
                    command_confirmed = True
                    break

        next_command_poll = current_command_poll + 1 if command_mode else 0
        command_budget_exhausted = command_mode and next_command_poll >= self.command_max_polls
        effective_command_mode = command_mode and not command_confirmed and not command_budget_exhausted
        interval, aggregate_state, parked_streak = self._adaptive_interval(
            states,
            int(subscription["parked_streak"] or 0),
            interactive=interactive,
            command_mode=effective_command_mode,
            command_poll_count=next_command_poll,
        )
        jitter = random.uniform(0, 0.25) if effective_command_mode else random.uniform(0, min(4.0, max(0.5, interval * 0.04)))
        now = utc_iso()
        next_run = time.time() + interval + jitter
        clear_expired_command = not command_mode and float(subscription["command_until"] or 0) > 0
        clear_command = (command_mode and (command_confirmed or command_budget_exhausted)) or clear_expired_command
        with self.lock, self._db() as db:
            if clear_command:
                db.execute(
                    "UPDATE subscriptions SET status='active', next_run_at=?, last_run_at=?, last_success_at=?, last_error=NULL, last_state=?, parked_streak=?, consecutive_failures=0, cooldown_until=0, command_until=0, command_key=NULL, command_vehicle_id=NULL, command_context_json=NULL, command_poll_count=0, command_started_at=0, updated_at=? WHERE subscription_id=?",
                    (next_run, now, now, aggregate_state, parked_streak, now, sid),
                )
            else:
                db.execute(
                    "UPDATE subscriptions SET status='active', next_run_at=?, last_run_at=?, last_success_at=?, last_error=NULL, last_state=?, parked_streak=?, consecutive_failures=0, cooldown_until=0, command_poll_count=?, updated_at=? WHERE subscription_id=?",
                    (next_run, now, now, aggregate_state, parked_streak, next_command_poll, now, sid),
                )
        if command_confirmed:
            LOG.info("Comando %s confirmado pela telemetria de %s após %s leitura(s); janela rápida encerrada.", command_key, sid, next_command_poll)
        elif command_budget_exhausted:
            if command_vehicle_id and not command_target_seen:
                LOG.warning("Janela rápida de %s não encontrou o veículo-alvo do comando entre os dados retornados; assinatura será reconciliada pelo site.", sid)
            LOG.warning("Janela rápida de %s encerrada após %s leitura(s) sem confirmação conclusiva; telemetria voltou ao modo adaptativo.", sid, next_command_poll)
        elif previous_state != aggregate_state:
            LOG.info("Telemetria %s mudou de %s para %s; próxima consulta em %ss.", sid, previous_state or "inicial", aggregate_state, int(interval + jitter))
        else:
            LOG.debug(
                "Telemetria %s: sessão reutilizada, %s veículo(s), estado %s, %s evento(s) enfileirado(s), %s leitura(s) idêntica(s) suprimida(s), próxima consulta em %ss%s.",
                sid, len(vehicles), aggregate_state, queued_events, skipped_events, int(interval + jitter),
                " (confirmação adaptativa)" if effective_command_mode else "",
            )
        self.wake_event.set()

    def _session_operation_lock(self, subscription_id: str) -> threading.RLock:
        key = str(subscription_id or "").strip()
        with self.session_locks_guard:
            lock = self.session_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self.session_locks[key] = lock
            return lock

    def _collect_with_session(
        self,
        subscription_id: str,
        credentials: dict[str, Any],
        vehicle_ids: set[str],
        command_mode: bool = False,
        manual_should_yield: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        # Somente a sessão desta conta fica bloqueada durante a chamada de rede.
        # Outras contas respeitam o limite global do Connector, mas não ficam
        # paradas atrás de uma autenticação lenta ou de um veículo offline.
        with self._session_operation_lock(subscription_id):
            return self._collect_with_session_locked(
                subscription_id,
                credentials,
                vehicle_ids,
                command_mode=command_mode,
                manual_should_yield=manual_should_yield,
            )

    def _collect_with_session_locked(
        self,
        subscription_id: str,
        credentials: dict[str, Any],
        vehicle_ids: set[str],
        command_mode: bool = False,
        manual_should_yield: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        now_epoch = time.time()
        credential_hash = hashlib.sha256(canonical_json(credentials)).hexdigest()
        with self.session_lock:
            session = self.sessions.get(subscription_id)
        if session is not None and (
            session.get("credential_hash") != credential_hash
            or now_epoch - float(session.get("created_at") or 0) >= self.session_max_age_seconds
            or now_epoch - float(session.get("last_used_at") or 0) >= self.session_idle_seconds
        ):
            self._close_session_locked(subscription_id)
            session = None

        if session is None:
            temp_dir = connector.secure_temp_directory()
            client = None
            try:
                client = connector.create_client(credentials, temp_dir, None, request_timeout_seconds=10)
                # Uma única tentativa de login. Falhas nunca geram uma sequência
                # imediata de novas autenticações.
                client.login()
            except Exception as exc:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
                shutil.rmtree(temp_dir, ignore_errors=True)
                delay = connector.login_cooldown_seconds(exc)
                if delay > 0:
                    raise connector.ConnectorLoginCooldownError(
                        "A Leapmotor limitou temporariamente novas autenticações. A próxima tentativa respeitará o prazo informado pela nuvem.",
                        delay,
                    ) from exc
                raise
            session = {
                "client": client,
                "temp_dir": temp_dir,
                "credential_hash": credential_hash,
                "created_at": now_epoch,
                "last_used_at": now_epoch,
            }
            with self.session_lock:
                self.sessions[subscription_id] = session
            LOG.info("Sessão Leapmotor criada para %s; será reutilizada durante a janela ativa.", subscription_id)

        client = session["client"]
        try:
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual aguardando a conta.")
            vehicles_value = client.get_vehicle_list()
            vehicles = vehicles_value if isinstance(vehicles_value, list) else list(vehicles_value or [])
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual aguardando a conta.")
            selected = vehicles
            if vehicle_ids:
                selected = [
                    item for item in vehicles
                    if str(connector.attribute(item, "car_id", "") or connector.attribute(item, "vin", "")) in vehicle_ids
                ]
            messages: list[Any] = []
            get_messages = getattr(client, "get_message_list", None)
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual aguardando a conta.")
            if not command_mode and callable(get_messages):
                if manual_should_yield is not None and manual_should_yield():
                    raise TelemetryYieldForManual("Operação manual aguardando a conta.")
                try:
                    message_page = get_messages(page_no=1, page_size=100)
                    messages = list(connector.attribute(message_page, "messages", []) or [])
                except Exception:
                    messages = []
            serialized: list[dict[str, Any]] = []
            for item in selected:
                if manual_should_yield is not None and manual_should_yield():
                    raise TelemetryYieldForManual("Operação manual aguardando a conta.")
                serialized.append(
                    connector.serialize_vehicle(
                        item,
                        include_status=True,
                        client=client,
                        messages=messages,
                        allow_unscoped_messages=len(selected) == 1,
                    )
                )
            if not serialized:
                raise RuntimeError("Nenhum veículo foi encontrado para esta conta.")
            session["last_used_at"] = time.time()
            session["vehicles"] = vehicles
            return {
                "ok": True,
                "account_name": "Conta Leapmotor",
                "vehicles": serialized,
                "connector_version": connector.CONNECTOR_VERSION,
                "library_version": connector.package_version(),
                "session_reused": True,
            }
        except TelemetryYieldForManual:
            session["last_used_at"] = time.time()
            raise
        except Exception as exc:
            if connector.is_transient_cloud_error(exc) or isinstance(exc, connector.ConnectorTemporaryError):
                # Um timeout de transporte não prova que o token morreu. A
                # sessão é mantida nas primeiras falhas para evitar novo login.
                session["last_used_at"] = time.time()
                raise
            self._close_session_locked(subscription_id)
            raise

    def _close_session_locked(self, subscription_id: str) -> None:
        with self.session_lock:
            session = self.sessions.pop(str(subscription_id), None)
        if not session:
            return
        client = session.get("client")
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        temp_dir = session.get("temp_dir")
        if temp_dir:
            shutil.rmtree(Path(temp_dir), ignore_errors=True)

    def _close_session(self, subscription_id: str) -> None:
        with self._session_operation_lock(subscription_id):
            self._close_session_locked(subscription_id)

    def _close_all_sessions(self) -> None:
        with self.session_lock:
            subscription_ids = list(self.sessions)
        for subscription_id in subscription_ids:
            self._close_session(subscription_id)

    def _has_session(self, subscription_id: str) -> bool:
        with self.session_lock:
            return str(subscription_id) in self.sessions

    def _mark_auth_required(self, subscription_id: str, message: str) -> None:
        now = utc_iso()
        with self.lock, self._db() as db:
            db.execute(
                "UPDATE subscriptions SET status='auth_required', auth_required=1, active_until=0, interactive_until=0, command_until=0, command_key=NULL, command_vehicle_id=NULL, command_context_json=NULL, command_poll_count=0, command_started_at=0, next_run_at=?, last_run_at=?, last_error=?, consecutive_failures=consecutive_failures+1, updated_at=? WHERE subscription_id=?",
                (time.time() + 86400, now, str(message or "")[:500], now, subscription_id),
            )

    @staticmethod
    def _transient_backoff(failures: int, interactive: bool) -> int:
        schedule = (45, 90, 180, 300, 900, 1800) if interactive else (120, 300, 900, 1800, 3600, 10800)
        return schedule[min(max(1, int(failures)), len(schedule)) - 1]

    @staticmethod
    def _failure_backoff(failures: int) -> int:
        schedule = (300, 900, 1800, 3600, 10800, 21600)
        return schedule[min(max(1, int(failures)), len(schedule)) - 1]

    def _state_of(self, telemetry: dict[str, Any]) -> str:
        state = str(telemetry.get("vehicle_state") or "").lower()
        charging = str(telemetry.get("charging_status") or "").lower()
        try:
            speed = float(telemetry.get("speed_kmh") or 0)
        except (TypeError, ValueError):
            speed = 0
        if charging in {"charging", "active", "fast_charging", "slow_charging", "dc_charging", "ac_charging"} or state == "charging":
            return "charging"
        if speed > 1 or state in {"driving", "ready"} or telemetry.get("ready_state") is True or telemetry.get("ignition_on") is True:
            return "driving"
        if telemetry.get("plugged") is True or charging == "plugged":
            return "charge_watch"
        if telemetry.get("is_parked") is True or state == "parked":
            return "parked"
        return "sleep"

    def _adaptive_interval(
        self,
        states: list[str],
        previous_parked_streak: int,
        interactive: bool = False,
        command_mode: bool = False,
        command_poll_count: int = 0,
    ) -> tuple[int, str, int]:
        if command_mode:
            if "driving" in states:
                aggregate = "driving"
            elif "charging" in states:
                aggregate = "charging"
            elif "charge_watch" in states:
                aggregate = "charge_watch"
            elif "parked" in states:
                aggregate = "parked"
            else:
                aggregate = "sleep"
            streak = 0 if aggregate in {"driving", "charging"} else previous_parked_streak + 1
            cadence_index = min(max(1, int(command_poll_count)) - 1, len(self.command_cadence) - 1)
            return int(self.command_cadence[cadence_index]), aggregate, streak
        if interactive:
            if "driving" in states:
                return min(self.active_seconds, self.interactive_seconds), "driving", 0
            if "charging" in states:
                return min(self.charging_seconds, self.interactive_seconds), "charging", 0
            if "charge_watch" in states:
                return self.interactive_seconds, "charge_watch", 0
            if "parked" in states:
                return self.interactive_seconds, "parked", previous_parked_streak + 1
            return self.interactive_seconds, "sleep", previous_parked_streak + 1
        if "driving" in states:
            return self.active_seconds, "driving", 0
        if "charging" in states:
            return self.charging_seconds, "charging", 0
        if "charge_watch" in states:
            return self.charge_watch_seconds, "charge_watch", 0
        if "parked" in states:
            streak = previous_parked_streak + 1
            if streak >= 20:
                return self.sleep_seconds, "sleep", streak
            return self.parked_seconds, "parked", streak
        return self.sleep_seconds, "sleep", previous_parked_streak + 1

    @staticmethod
    def _command_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on", "open", "opened", "active", "running", "charging"}:
            return True
        if normalized in {"0", "false", "no", "off", "closed", "close", "inactive", "stopped", "idle", "not_charging"}:
            return False
        return None

    @staticmethod
    def _command_sample_is_fresh(telemetry: dict[str, Any], command_started_at: float) -> bool:
        if command_started_at <= 0:
            return True
        raw = telemetry.get("captured_at")
        if not raw:
            return True
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp() >= command_started_at - 2.0
        except (TypeError, ValueError, OverflowError):
            return True

    def _command_confirmation(
        self,
        command_key: str,
        telemetry: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[bool, bool]:
        command = str(command_key or "").strip().lower()
        parameters = context.get("parameters") if isinstance(context.get("parameters"), dict) else {}
        if command in {"lock", "unlock"}:
            state = self._command_bool(telemetry.get("locked"))
            return (state is (command == "lock"), state is not None)
        if command in {"climate_on", "climate_off", "quick_cool", "quick_heat"}:
            state = self._command_bool(telemetry.get("climate_on"))
            expected = command != "climate_off"
            return (state is expected, state is not None)
        if command == "windshield_defrost":
            details = telemetry.get("climate_details") if isinstance(telemetry.get("climate_details"), dict) else {}
            state = self._command_bool(details.get("windshield_defrost"))
            return (state is True, state is not None)
        if command in {"battery_preheat_on", "battery_preheat_off"}:
            details = telemetry.get("climate_details") if isinstance(telemetry.get("climate_details"), dict) else {}
            state = self._command_bool(details.get("battery_preheat"))
            expected = command == "battery_preheat_on"
            return (state is expected, state is not None)
        if command in {"trunk_open", "trunk_close"}:
            doors = telemetry.get("doors") if isinstance(telemetry.get("doors"), dict) else {}
            state = self._command_bool(doors.get("trunk"))
            expected = command == "trunk_open"
            return (state is expected, state is not None)
        if command in {"sunshade_open", "sunshade_close"}:
            state = self._command_bool(telemetry.get("sunshade_open"))
            expected = command == "sunshade_open"
            return (state is expected, state is not None)
        if command in {"windows_open", "windows_close"}:
            windows = telemetry.get("windows") if isinstance(telemetry.get("windows"), dict) else {}
            known = [self._command_bool(value) for value in windows.values()]
            known = [value for value in known if value is not None]
            if not known:
                return False, False
            return (any(known) if command == "windows_open" else not any(known), True)
        if command in {"start_charging", "stop_charging"}:
            charging = str(telemetry.get("charging_status") or "").strip().lower()
            try:
                power = float(telemetry.get("charging_power_kw") or 0)
            except (TypeError, ValueError):
                power = 0.0
            active = charging in {"charging", "active", "fast_charging", "slow_charging", "dc_charging", "ac_charging", "in_progress"} or power > 0.15
            known = bool(charging) or telemetry.get("charging_power_kw") is not None
            return (active if command == "start_charging" else not active, known)
        if command == "set_charge_limit":
            expected = parameters.get("charge_limit_percent")
            actual = telemetry.get("charge_limit_percent")
            try:
                return abs(float(actual) - float(expected)) <= 1.0, actual is not None and expected is not None
            except (TypeError, ValueError):
                return False, False
        # Localizar, liberar conector e enviar destino não possuem um estado
        # confiável de confirmação na telemetria atual.
        return False, False

    @staticmethod
    def _looks_rate_limited(message: str) -> bool:
        normalized = str(message or "").lower()
        if connector.login_cooldown_seconds(normalized) > 0:
            return False
        return any(token in normalized for token in (
            "429", "too many", "password error limit", "login attempt limit", "rate limit", "rate-limit", "throttle", "temporarily blocked",
            "muitas solicitações", "limite de requisições", "conta bloqueada",
        ))

    def _heartbeat_interval(self, state: str, interactive: bool = False) -> int:
        if interactive:
            return max(30, self.interactive_seconds * 2)
        if state in {"driving", "charging"}:
            return 60
        if state == "charge_watch":
            return 120
        if state == "parked":
            return 300
        return 900

    def _queue_event(self, subscription: sqlite3.Row, vehicle: dict[str, Any], source_at: str, state: str, interactive: bool = False) -> dict[str, Any]:
        environment = str(subscription["environment"])
        account_id = int(subscription["account_id"])
        subscription_id = str(subscription["subscription_id"])
        remote_id = str(vehicle.get("remote_id") or "").strip()[:190]
        if not remote_id:
            LOG.warning("Veículo sem remote_id ignorado na assinatura %s.", subscription_id)
            return {"queued": False, "reason": "missing_remote_id"}

        semantic_hash = hashlib.sha256(canonical_json(semantic_snapshot(vehicle))).hexdigest()
        telemetry = vehicle.get("telemetry") if isinstance(vehicle.get("telemetry"), dict) else {}
        visual_fingerprint = str(telemetry.get("visual_fingerprint") or "").strip().lower()
        if len(visual_fingerprint) != 64 or any(char not in "0123456789abcdef" for char in visual_fingerprint):
            visual_fingerprint = ""
        now_epoch = time.time()
        now_iso = utc_iso()
        source_at = str(source_at or now_iso).strip()[:80] or now_iso

        with self.lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                cached = db.execute(
                    "SELECT * FROM vehicle_state_cache WHERE subscription_id=? AND remote_id=?",
                    (subscription_id, remote_id),
                ).fetchone()
                unchanged = cached is not None and str(cached["semantic_hash"] or "") == semantic_hash
                last_queued_at = float(cached["last_queued_at"] or 0) if cached is not None else 0.0
                if unchanged and now_epoch - last_queued_at < self._heartbeat_interval(state, interactive=interactive):
                    db.execute(
                        "UPDATE vehicle_state_cache SET visual_fingerprint=?, last_source_at=?, skipped_unchanged=skipped_unchanged+1, updated_at=? WHERE subscription_id=? AND remote_id=?",
                        (visual_fingerprint or None, source_at, now_iso, subscription_id, remote_id),
                    )
                    db.execute("COMMIT")
                    return {"queued": False, "reason": "unchanged", "sequence": int(cached["sequence"] or 0)}

                sequence = (int(cached["sequence"] or 0) if cached is not None else 0) + 1
                state_changed = not unchanged
                event_kind = "change" if state_changed else "heartbeat"
                enriched = json.loads(canonical_json(vehicle).decode("utf-8"))
                enriched_telemetry = enriched.get("telemetry") if isinstance(enriched.get("telemetry"), dict) else {}
                enriched_telemetry["gateway_delivery"] = {
                    "version": 1,
                    "engine_version": ENGINE_VERSION,
                    "sequence": sequence,
                    "state_changed": state_changed,
                    "event_kind": event_kind,
                    "vehicle_state": state,
                    "source_at": source_at,
                    "gateway_collected_at": now_iso,
                    "semantic_hash": semantic_hash[:16],
                }
                enriched["telemetry"] = enriched_telemetry
                payload_bytes = canonical_json(enriched)
                payload_hash = hashlib.sha256(payload_bytes).hexdigest()
                event_id = hashlib.sha256(
                    f"{environment}|{account_id}|{subscription_id}|{remote_id}|{sequence}|{payload_hash}".encode()
                ).hexdigest()
                encrypted = self.fernet.encrypt(payload_bytes)
                db.execute(
                    """
                    INSERT INTO events
                    (event_id, subscription_id, environment, account_id, remote_id, source_at, payload_encrypted, payload_hash,
                     status, attempts, next_attempt_at, last_error, created_at, delivered_at, sequence, semantic_hash, state_changed, event_kind)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, NULL, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        event_id, subscription_id, environment, account_id, remote_id, source_at, encrypted, payload_hash,
                        now_epoch, now_iso, sequence, semantic_hash, 1 if state_changed else 0, event_kind,
                    ),
                )
                db.execute(
                    """
                    INSERT INTO vehicle_state_cache
                    (subscription_id, remote_id, semantic_hash, visual_fingerprint, last_source_at, last_queued_at, sequence, skipped_unchanged, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                    ON CONFLICT(subscription_id, remote_id) DO UPDATE SET
                        semantic_hash=excluded.semantic_hash,
                        visual_fingerprint=excluded.visual_fingerprint,
                        last_source_at=excluded.last_source_at,
                        last_queued_at=excluded.last_queued_at,
                        sequence=excluded.sequence,
                        updated_at=excluded.updated_at
                    """,
                    (subscription_id, remote_id, semantic_hash, visual_fingerprint or None, source_at, now_epoch, sequence, now_iso),
                )
                db.execute("COMMIT")
                return {"queued": True, "sequence": sequence, "event_kind": event_kind, "state_changed": state_changed}
            except Exception:
                db.execute("ROLLBACK")
                raise

    def _deliver_due(self) -> bool:
        with self.lock, self._db() as db:
            rows = db.execute(
                """
                SELECT e.*
                FROM events e
                WHERE e.status='pending' AND e.next_attempt_at<=?
                  AND NOT EXISTS (
                      SELECT 1 FROM events older
                      WHERE older.status='pending'
                        AND older.subscription_id=e.subscription_id
                        AND older.remote_id=e.remote_id
                        AND (
                            (older.sequence>0 AND e.sequence>0 AND older.sequence<e.sequence)
                            OR (older.sequence=0 AND older.created_at<e.created_at)
                        )
                  )
                ORDER BY e.created_at ASC
                LIMIT ?
                """,
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
                "sequence": int(row["sequence"] or 0),
                "state_changed": bool(row["state_changed"]),
                "event_kind": str(row["event_kind"] or "change"),
                "vehicle": vehicle,
            })
            valid_rows.append(row)
        if not events:
            return
        body = canonical_json({"events": events, "gateway_version": ENGINE_VERSION, "sent_at": utc_iso()})
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
                "User-Agent": f"LeapHubGateway/{ENGINE_VERSION}",
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
        now_epoch = time.time()
        # Executada de forma barata; o SQLite ignora as remoções quando não há registros antigos.
        cutoff = time.time() - self.retention_days * 86400
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat().replace("+00:00", "Z")
        expired_sessions: list[str] = []
        with self.lock, self._db() as db:
            expired_sessions = [str(row[0]) for row in db.execute(
                "SELECT subscription_id FROM subscriptions WHERE enabled=1 AND active_until<=? AND status NOT IN ('idle','disabled','auth_required','cooldown')",
                (now_epoch,),
            ).fetchall()]
            if expired_sessions:
                placeholders = ",".join("?" for _ in expired_sessions)
                db.execute(
                    f"UPDATE subscriptions SET status='idle', interactive_until=0, command_until=0, last_error=NULL, updated_at=? WHERE subscription_id IN ({placeholders})",
                    (utc_iso(), *expired_sessions),
                )
            db.execute("DELETE FROM events WHERE status='delivered' AND delivered_at<?", (cutoff_iso,))
            total = int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            if total > self.queue_max:
                excess = total - self.queue_max
                db.execute(
                    "DELETE FROM events WHERE event_id IN (SELECT event_id FROM events WHERE status='delivered' ORDER BY delivered_at ASC LIMIT ?)",
                    (excess,),
                )
        for subscription_id in expired_sessions:
            self._close_session(subscription_id)
