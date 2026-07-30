#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import http.client
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
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from cryptography.fernet import Fernet, InvalidToken

import leaphub_connector as connector
try:
    from leaphub_connection_orchestrator import ORCHESTRATOR
except ModuleNotFoundError:
    try:
        from connection_orchestrator import ORCHESTRATOR
    except ModuleNotFoundError:
        import importlib.util as _importlib_util
        _orchestrator_path = Path(__file__).with_name("connection_orchestrator.py")
        _orchestrator_spec = _importlib_util.spec_from_file_location("leaphub_connection_orchestrator_local", _orchestrator_path)
        if _orchestrator_spec is None or _orchestrator_spec.loader is None:
            raise
        _orchestrator_module = _importlib_util.module_from_spec(_orchestrator_spec)
        _orchestrator_spec.loader.exec_module(_orchestrator_module)
        ORCHESTRATOR = _orchestrator_module.ORCHESTRATOR
try:
    from leaphub_event_transport import EVENT_TRANSPORT
except ModuleNotFoundError:
    try:
        from event_transport import EVENT_TRANSPORT
    except ModuleNotFoundError:
        import importlib.util as _event_importlib_util
        _event_transport_path = Path(__file__).with_name("event_transport.py")
        _event_transport_spec = _event_importlib_util.spec_from_file_location("leaphub_event_transport_local", _event_transport_path)
        if _event_transport_spec is None or _event_transport_spec.loader is None:
            raise
        _event_transport_module = _event_importlib_util.module_from_spec(_event_transport_spec)
        _event_transport_spec.loader.exec_module(_event_transport_module)
        EVENT_TRANSPORT = _event_transport_module.EVENT_TRANSPORT

LOG = logging.getLogger("leaphub.telemetry")
ENGINE_VERSION = "1.12.59"  # diagnostico de confirmacao inconclusiva

# Hospedagem compartilhada (Apache/LiteSpeed) fecha a conexão ociosa em poucos
# segundos. Reaproveitar depois disso escreve num socket já fechado e devolve
# "Remote end closed connection without response" sem que o PHP chegue a rodar.
DELIVERY_IDLE_DEFAULT_SECONDS = 5.0
DELIVERY_IDLE_MIN_SECONDS = 2.0
DELIVERY_IDLE_MAX_SECONDS = 30.0

# 1.12.56 — teto para o comando esperar a trava global do motor. `with self.lock`
# no caminho do comando era a única aquisição sem limite do arquivo; compare com
# `self.lock.acquire(timeout=0.15)` e `account_lock.acquire(timeout=...)`. Um
# comando de campo mediu precheck_motor=135718ms com todas as demais fases
# somando ~5s. Sem teto, trava presa e leitura lenta são indistinguíveis e o
# dono fica dois minutos olhando a tela sem resposta.
ENGINE_LOCK_COMMAND_TIMEOUT_SECONDS = 20.0

TELEMETRY_CONFIRMABLE_COMMANDS = frozenset({
    "lock",
    "unlock",
    "climate_on",
    "climate_off",
    "quick_cool",
    "quick_heat",
    "windshield_defrost",
    "battery_preheat_on",
    "battery_preheat_off",
    "steering_wheel_heat_on",
    "steering_wheel_heat_off",
    "rearview_mirror_heat_on",
    "rearview_mirror_heat_off",
    "trunk_open",
    "trunk_close",
    "sunshade_open",
    "sunshade_close",
    "windows_open",
    "windows_close",
    "sentry_on",
    "sentry_off",
    "start_charging",
    "stop_charging",
    "set_charge_limit",
})


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
        manual_active_provider: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self.options = options
        self.secrets = secrets
        self.operation_semaphore = operation_semaphore
        self.account_lock_provider = account_lock_provider
        self.account_wait_seconds = max(2, min(60, int(account_wait_seconds)))
        self.manual_pending_provider = manual_pending_provider
        # A confirmação de um comando pode ignorar apenas a janela de "settle"
        # deixada para uma possível ação seguinte. Um comando realmente pendente
        # continua tendo prioridade e faz a coleta ceder no próximo ponto seguro.
        self.manual_active_provider = manual_active_provider or manual_pending_provider
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
        self._connections: dict[int, sqlite3.Connection] = {}
        self._busy_ms: dict[int, int] = {}
        self._connections_guard = threading.RLock()
        self._storage_checked_at = 0.0
        self._maintenance_last_at = 0.0
        # 1.12.50 — a coleta de uma conta não atrasa mais a das outras. O teto
        # real de chamadas simultâneas à nuvem continua sendo o semáforo global
        # do Connector; isto apenas deixa de serializar tudo antes dele.
        self.poll_workers = self._bounded("telemetry_poll_workers", 3, 1, 6)
        self._poll_pool: ThreadPoolExecutor | None = None
        self._inflight: set[str] = set()
        self._inflight_guard = threading.RLock()
        self.delivery_event = threading.Event()
        self.delivery_worker: threading.Thread | None = None
        # 1.12.51 — conexao TLS reaproveitada entre lotes de entrega.
        self._delivery_connection: http.client.HTTPConnection | None = None
        self._delivery_connection_key = ""
        self._delivery_guard = threading.RLock()
        # 1.12.52 — a conexao so pode ser reaproveitada dentro da janela de
        # keep-alive do servidor. Os lotes saem a cada 20-120s e a hospedagem
        # fecha a conexao ociosa muito antes disso.
        self._delivery_connection_idle_since = 0.0
        self._delivery_idle_max = DELIVERY_IDLE_DEFAULT_SECONDS
        self.active_seconds = self._bounded("telemetry_active_seconds", 20, 15, 300)
        self.interactive_seconds = self._bounded("telemetry_interactive_seconds", 20, 15, 60)
        # Janela curta após comandos remotos. É propositalmente separada da
        # navegação comum para confirmar rapidamente o novo estado sem manter
        # consultas agressivas à nuvem durante todo o dia.
        # A confirmação após comando usa poucas leituras espaçadas. O app
        # mantém o último estado confirmado enquanto aguarda, portanto não há
        # motivo para consultar a nuvem a cada três segundos.
        self.command_seconds = self._bounded("telemetry_command_seconds", 12, 10, 60)
        # Cinco amostras cobrem o atraso normal entre a aceitação da nuvem e a
        # telemetria física do veículo. Instalações atualizadas que ainda tenham
        # o valor legado 3 recebem o novo mínimo automaticamente.
        self.command_max_polls = self._bounded("telemetry_command_max_polls", 5, 5, 8)
        self.command_cadence = (self.command_seconds, 20, 35, 45, 60, 90, 120, 120)
        self.charging_seconds = self._bounded("telemetry_charging_seconds", 25, 15, 600)
        self.parked_seconds = self._bounded("telemetry_parked_seconds", 90, 60, 3600)
        self.sleep_seconds = self._bounded("telemetry_sleep_seconds", 600, 300, 14400)
        # A presença no site controla somente a cadência rápida. Quando o modo
        # de fundo está ativo, assinaturas habilitadas continuam elegíveis mesmo
        # depois de active_until expirar. O limite econômico evita ficar horas
        # sem perceber uma viagem curta, sem consultar agressivamente o carro
        # enquanto ele está parado.
        self.background_enabled = bool(options.get("telemetry_background_enabled", True))
        self.background_seconds = self._bounded("telemetry_background_seconds", 300, 120, 1800)
        self.presence_window_seconds = self._bounded("telemetry_presence_window_seconds", 420, 300, 1800)
        self.rate_limit_cooldown_seconds = self._bounded("telemetry_rate_limit_cooldown_seconds", 900, 300, 3600)
        self.login_cooldown_max_seconds = 1800
        self.login_backoff_schedule = (300, 600, 1200, 1800)
        # Evita que reinícios, várias abas ou reativações próximas iniciem novos
        # logins antes do intervalo seguro. O marcador fica no SQLite e, por
        # isso, continua válido mesmo após reiniciar o App.
        self.auth_attempt_min_interval_seconds = 150
        self.started_at = time.time()
        self.charge_watch_seconds = max(60, min(120, self.charging_seconds * 3))
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
        self.session_max_age_seconds = 0
        # Uma janela de telemetria encerrada não invalida o token. Preserve o
        # cliente por algumas horas e descarte somente por inatividade real,
        # credencial alterada, expiração confirmada ou desligamento do Gateway.
        self.session_idle_seconds = self._bounded("telemetry_session_idle_seconds", 21600, 1800, 86400)
        self.vehicle_list_cache_seconds = self._bounded("telemetry_vehicle_list_cache_seconds", 1800, 300, 7200)
        self.message_cache_seconds = self._bounded("telemetry_message_cache_seconds", 1800, 300, 14400)
        # 1.12.38 — o estado essencial é FAST; mensagens/imagem oficial são SLOW.
        # Não adicionamos uma opção obrigatória ao schema do add-on para manter
        # atualização compatível com instalações antigas.
        self.slow_interval_seconds = max(600, min(1800, self.message_cache_seconds))
        self.request_timeout_seconds = self._bounded("telemetry_request_timeout_seconds", 15, 10, 30)
        self._init_db()
        self.storage_healthy = True
        # 1.12.38 — a telemetria já aceita hints de um futuro transporte por
        # eventos. O REST continua como fallback e nenhuma conexão MQTT é aberta
        # enquanto autenticação/tópicos/payloads não estiverem homologados.
        EVENT_TRANSPORT.register_wake_callback(self._wake_from_event)

    def _wake_from_event(self, environment: str, account_id: int, vehicle_id: str, source: str) -> bool:
        now = time.time()
        target_vehicle = str(vehicle_id or "").strip()[:190]
        with self.lock, self._db() as db:
            candidates = db.execute(
                "SELECT subscription_id,active_until,next_run_at,vehicle_ids_json FROM subscriptions WHERE environment=? AND account_id=? AND enabled=1 AND auth_required=0",
                (str(environment or ""), int(account_id)),
            ).fetchall()
            rows = []
            for row in candidates:
                if target_vehicle:
                    try:
                        configured = {str(item).strip() for item in json.loads(str(row["vehicle_ids_json"] or "[]"))}
                    except (TypeError, ValueError, json.JSONDecodeError):
                        configured = set()
                    if target_vehicle not in configured:
                        continue
                rows.append(row)
            for row in rows:
                active_until = max(float(row["active_until"] or 0), now + 90)
                next_run = min(float(row["next_run_at"] or now), now)
                db.execute(
                    "UPDATE subscriptions SET active_until=?, next_run_at=?, status='event_hint', updated_at=? WHERE subscription_id=?",
                    (active_until, next_run, utc_iso(), str(row["subscription_id"])),
                )
        if rows:
            LOG.debug("Hint de evento %s acordou %s assinatura(s) sem abrir chamada extra por conta própria.", str(source or "event")[:40], len(rows))
            self.wake_event.set()
            return True
        return False

    def _bounded(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self.options.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def _manual_operation_blocks(
        self, environment: str, operation_payload: dict[str, Any], *, command_mode: bool
    ) -> bool:
        provider = self.manual_active_provider if command_mode else self.manual_pending_provider
        return bool(provider and provider(environment, operation_payload))

    def _prepare_storage(self, probe: bool = False) -> None:
        """Garante que a fila persistente continue gravável após atualização/reinício."""
        if not probe:
            now = time.monotonic()
            if now - self._storage_checked_at < 60.0:
                return
            self._storage_checked_at = now
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

    def _drop_connection(self, key: int) -> None:
        with self._connections_guard:
            db = self._connections.pop(key, None)
            self._busy_ms.pop(key, None)
        if db is not None:
            try:
                db.close()
            except sqlite3.Error:
                pass

    def close_storage(self) -> None:
        """Fecha as conexões SQLite abertas por todas as threads.

        Chamado por ``stop()`` depois que worker, entrega e pool já terminaram.
        Como a conexão passou a ser reaproveitada, sem isto o arquivo da fila
        permaneceria aberto até o processo encerrar.
        """
        with self._connections_guard:
            connections = list(self._connections.values())
            self._connections.clear()
            self._busy_ms.clear()
        for db in connections:
            try:
                db.close()
            except sqlite3.Error:
                pass

    def _connection(self) -> sqlite3.Connection:
        """Reaproveita uma conexão SQLite por thread em vez de reconectar por consulta."""
        key = threading.get_ident()
        with self._connections_guard:
            db = self._connections.get(key)
        if db is not None:
            try:
                db.execute("SELECT 1").fetchone()
                return db
            except sqlite3.Error:
                self._drop_connection(key)

        self._prepare_storage(probe=False)
        db = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA temp_store=MEMORY")
        # journal_mode é persistente no arquivo; synchronous é por conexão.
        mode_row = db.execute("PRAGMA journal_mode").fetchone()
        mode = str(mode_row[0] if mode_row else "").lower()
        db.execute("PRAGMA synchronous=NORMAL" if mode == "wal" else "PRAGMA synchronous=FULL")
        with self._connections_guard:
            self._connections[key] = db
            self._busy_ms[key] = 30000
        return db

    @contextmanager
    def _db(self, timeout_seconds: float = 30.0) -> Iterator[sqlite3.Connection]:
        key = threading.get_ident()
        db = self._connection()
        milliseconds = max(50, int(max(0.05, min(30.0, float(timeout_seconds))) * 1000))
        with self._connections_guard:
            current = self._busy_ms.get(key)
        if milliseconds != current:
            db.execute(f"PRAGMA busy_timeout={milliseconds}")
            with self._connections_guard:
                self._busy_ms[key] = milliseconds
        try:
            yield db
        except sqlite3.Error:
            # Uma conexão que falhou pode ter transação pendente. Descartar aqui
            # garante que a próxima consulta abra uma limpa, sem herdar estado.
            self._drop_connection(key)
            raise


    def _configure_journal(self, db: sqlite3.Connection) -> None:
        """Prefere WAL e mantém DELETE como fallback quando o volume não o aceita.

        1.12.50 — com DELETE e synchronous=FULL cada escrita cria e apaga um
        journal com vários fsync, e leitor bloqueia escritor. Em disco mecânico
        isso custa dezenas de milissegundos por transação e era a causa direta
        do /health passar de 3s e derrubar o watchdog. WAL transforma a escrita
        em append sequencial e não bloqueia leitura. Nenhuma linha, tabela ou
        migration é tocada; se o volume não aceitar o arquivo -shm, o PRAGMA
        devolve o modo anterior e o caminho antigo continua valendo integralmente.
        """
        current_row = db.execute("PRAGMA journal_mode").fetchone()
        current = str(current_row[0] if current_row else "unknown").lower()

        if current != "wal":
            try:
                mode_row = db.execute("PRAGMA journal_mode=WAL").fetchone()
                current = str(mode_row[0] if mode_row else current).lower()
            except sqlite3.OperationalError as exc:
                LOG.warning("WAL indisponível neste volume (%s); mantendo o journal atual.", exc)
                current_row = db.execute("PRAGMA journal_mode").fetchone()
                current = str(current_row[0] if current_row else current).lower()

        if current == "wal":
            self.storage_journal_mode = "wal"
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("PRAGMA wal_autocheckpoint=256")
            LOG.info("Fila de telemetria em WAL; leituras deixam de bloquear a escrita.")
            return

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
                        cooldown_reason TEXT NULL,
                        last_auth_attempt_at REAL NOT NULL DEFAULT 0,
                        last_auth_success_at REAL NOT NULL DEFAULT 0,
                        config_hash TEXT NULL,
                        candidate_state TEXT NULL,
                        candidate_count INTEGER NOT NULL DEFAULT 0,
                        sleep_streak INTEGER NOT NULL DEFAULT 0,
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
                    CREATE TABLE IF NOT EXISTS account_auth_state (
                        environment TEXT NOT NULL,
                        account_id INTEGER NOT NULL,
                        cooldown_until REAL NOT NULL DEFAULT 0,
                        block_count INTEGER NOT NULL DEFAULT 0,
                        attempt_guard_until REAL NOT NULL DEFAULT 0,
                        last_attempt_at REAL NOT NULL DEFAULT 0,
                        last_success_at REAL NOT NULL DEFAULT 0,
                        last_origin TEXT NULL,
                        last_error TEXT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(environment, account_id)
                    );
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
                if "cooldown_reason" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN cooldown_reason TEXT NULL")
                if "last_auth_attempt_at" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN last_auth_attempt_at REAL NOT NULL DEFAULT 0")
                if "last_auth_success_at" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN last_auth_success_at REAL NOT NULL DEFAULT 0")
                if "config_hash" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN config_hash TEXT NULL")
                if "candidate_state" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN candidate_state TEXT NULL")
                if "candidate_count" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN candidate_count INTEGER NOT NULL DEFAULT 0")
                if "sleep_streak" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN sleep_streak INTEGER NOT NULL DEFAULT 0")
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

    @staticmethod
    def _account_id(payload_or_id: dict[str, Any] | int) -> int:
        try:
            if isinstance(payload_or_id, dict):
                return int(payload_or_id.get("account_id") or 0)
            return int(payload_or_id or 0)
        except (TypeError, ValueError):
            return 0

    def account_auth_status(self, environment: str, payload_or_id: dict[str, Any] | int) -> dict[str, Any]:
        account_id = self._account_id(payload_or_id)
        if account_id < 1:
            return {"managed": False, "account_id": 0, "cooldown": False, "retry_after_seconds": 0}
        now_epoch = time.time()
        with self.lock, self._db() as db:
            row = db.execute(
                "SELECT cooldown_until,attempt_guard_until,block_count,last_origin,last_error,last_attempt_at,last_success_at "
                "FROM account_auth_state WHERE environment=? AND account_id=? LIMIT 1",
                (str(environment or ""), account_id),
            ).fetchone()
        if row is None:
            return {"managed": True, "account_id": account_id, "cooldown": False, "retry_after_seconds": 0}
        blocked_until = max(float(row["cooldown_until"] or 0), float(row["attempt_guard_until"] or 0))
        return {
            "managed": True,
            "account_id": account_id,
            "cooldown": blocked_until > now_epoch,
            "retry_after_seconds": max(0, int(blocked_until - now_epoch)),
            "block_count": int(row["block_count"] or 0),
            "last_origin": str(row["last_origin"] or ""),
            "last_error": connector.clean_message(str(row["last_error"] or "")),
            "last_attempt_at": float(row["last_attempt_at"] or 0),
            "last_success_at": float(row["last_success_at"] or 0),
        }

    def assert_account_cloud_allowed(self, environment: str, payload_or_id: dict[str, Any] | int, origin: str) -> None:
        status = self.account_auth_status(environment, payload_or_id)
        if status.get("cooldown"):
            previous = str(status.get("last_origin") or "outra origem")[:80]
            raise connector.ConnectorLoginCooldownError(
                f"Cooldown global ativo para esta conta; origem anterior={previous}, origem atual={str(origin or 'unknown')[:80]}.",
                max(30, int(status.get("retry_after_seconds") or 30)),
            )

    def begin_account_auth(self, environment: str, payload_or_id: dict[str, Any] | int, origin: str) -> dict[str, Any]:
        """Reserve atomically the only login attempt allowed for an account."""
        account_id = self._account_id(payload_or_id)
        if account_id < 1:
            return {"managed": False, "account_id": 0, "origin": str(origin or "unknown")[:80]}
        environment = str(environment or "")
        origin = str(origin or "unknown")[:80]
        now_epoch = time.time()
        now_iso = utc_iso()
        with self.lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT cooldown_until,attempt_guard_until,block_count,last_origin FROM account_auth_state "
                    "WHERE environment=? AND account_id=? LIMIT 1",
                    (environment, account_id),
                ).fetchone()
                blocked_until = 0.0
                previous_origin = "outra origem"
                if row is not None:
                    blocked_until = max(float(row["cooldown_until"] or 0), float(row["attempt_guard_until"] or 0))
                    previous_origin = str(row["last_origin"] or previous_origin)
                if blocked_until > now_epoch:
                    db.execute("ROLLBACK")
                    raise connector.ConnectorLoginCooldownError(
                        f"Autenticação global protegida: {previous_origin} já reservou a tentativa desta conta; origem atual={origin}.",
                        max(30, int(blocked_until - now_epoch)),
                    )
                db.execute(
                    "INSERT INTO account_auth_state(environment,account_id,cooldown_until,block_count,attempt_guard_until,last_attempt_at,last_success_at,last_origin,last_error,updated_at) "
                    "VALUES(?,?,0,0,?,?,0,?,NULL,?) "
                    "ON CONFLICT(environment,account_id) DO UPDATE SET attempt_guard_until=excluded.attempt_guard_until,"
                    "last_attempt_at=excluded.last_attempt_at,last_origin=excluded.last_origin,last_error=NULL,updated_at=excluded.updated_at",
                    (environment, account_id, now_epoch + 240, now_epoch, origin, now_iso),
                )
                db.execute("COMMIT")
            except Exception:
                try:
                    db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
        LOG.info("Autenticação reservada para conta=%s origem=%s; tentativas paralelas foram bloqueadas.", account_id, origin)
        return {"managed": True, "account_id": account_id, "origin": origin}

    def record_account_auth_success(self, environment: str, payload_or_id: dict[str, Any] | int, origin: str = "success") -> None:
        account_id = self._account_id(payload_or_id)
        if account_id < 1:
            return
        now_epoch = time.time()
        now_iso = utc_iso()
        with self.lock, self._db() as db:
            db.execute(
                "INSERT INTO account_auth_state(environment,account_id,cooldown_until,block_count,attempt_guard_until,last_attempt_at,last_success_at,last_origin,last_error,updated_at) "
                "VALUES(?,?,0,0,0,0,?,?,NULL,?) "
                "ON CONFLICT(environment,account_id) DO UPDATE SET cooldown_until=0,block_count=0,attempt_guard_until=0,"
                "last_success_at=excluded.last_success_at,last_origin=excluded.last_origin,last_error=NULL,updated_at=excluded.updated_at",
                (str(environment or ""), account_id, now_epoch, str(origin or "success")[:80], now_iso),
            )
        self._clear_account_subscription_cooldown(environment, account_id)

    def record_account_auth_failure(
        self,
        environment: str,
        payload_or_id: dict[str, Any] | int,
        origin: str,
        message: str,
        retry_after_seconds: int = 300,
        blocked: bool = False,
    ) -> int:
        account_id = self._account_id(payload_or_id)
        requested = max(30, int(retry_after_seconds or 300))
        if account_id < 1:
            return min(self.login_cooldown_max_seconds, requested)
        environment = str(environment or "")
        now_epoch = time.time()
        now_iso = utc_iso()
        with self.lock, self._db() as db:
            row = db.execute(
                "SELECT block_count FROM account_auth_state WHERE environment=? AND account_id=? LIMIT 1",
                (environment, account_id),
            ).fetchone()
            previous = int(row["block_count"] or 0) if row is not None else 0
            block_count = min(len(self.login_backoff_schedule), previous + 1) if blocked else previous
            progressive = self.login_backoff_schedule[max(0, block_count - 1)] if blocked else min(240, requested)
            delay = max(requested, progressive)
            delay = max(30, min(self.login_cooldown_max_seconds, delay))
            until = now_epoch + delay
            db.execute(
                "INSERT INTO account_auth_state(environment,account_id,cooldown_until,block_count,attempt_guard_until,last_attempt_at,last_success_at,last_origin,last_error,updated_at) "
                "VALUES(?,?,?,?,0,?,0,?,?,?) "
                "ON CONFLICT(environment,account_id) DO UPDATE SET cooldown_until=excluded.cooldown_until,block_count=excluded.block_count,"
                "attempt_guard_until=0,last_origin=excluded.last_origin,last_error=excluded.last_error,updated_at=excluded.updated_at",
                (environment, account_id, until, block_count, now_epoch, str(origin or "unknown")[:80], connector.clean_message(message)[:500], now_iso),
            )
        self._apply_account_subscription_cooldown(environment, account_id, delay, message, "login" if blocked else "auth_guard")
        return delay

    def _apply_account_subscription_cooldown(
        self, environment: str, account_id: int, delay: int, message: str, reason: str
    ) -> None:
        until = time.time() + max(30, int(delay))
        now = utc_iso()
        with self.lock, self._db() as db:
            db.execute(
                "UPDATE subscriptions SET status='cooldown',cooldown_until=?,cooldown_reason=?,next_run_at=?,last_error=?,updated_at=? "
                "WHERE environment=? AND account_id=?",
                (until, str(reason or "login")[:40], until, connector.clean_message(message)[:500], now, str(environment or ""), int(account_id or 0)),
            )
        self.wake_event.set()

    def _clear_account_subscription_cooldown(self, environment: str, account_id: int) -> None:
        if int(account_id or 0) < 1:
            return
        now = utc_iso()
        with self.lock, self._db() as db:
            db.execute(
                "UPDATE subscriptions SET cooldown_until=0,cooldown_reason=NULL,status=CASE WHEN status='cooldown' THEN 'waiting' ELSE status END,"
                "next_run_at=CASE WHEN status='cooldown' THEN MIN(next_run_at,?) ELSE next_run_at END,"
                "last_error=CASE WHEN status='cooldown' THEN NULL ELSE last_error END,updated_at=? "
                "WHERE environment=? AND account_id=?",
                (time.time() + 2, now, str(environment or ""), int(account_id or 0)),
            )
        self.wake_event.set()

    @staticmethod
    def _try_refresh_client_session(client: Any) -> bool:
        """Try one logical refresh without multiplying cloud requests.

        Some leapmotor-api releases expose the same refresh implementation under
        multiple aliases. Calling every alias after a timeout, rate limit or
        cooldown could turn one recovery attempt into three cloud requests.
        Explicit ``False`` may fall through to another distinct implementation;
        any exception is classified once and stops the chain.
        """
        seen: set[tuple[int, int]] = set()
        # 1.12.53 — "token_refresh" é o nome real na leapmotor-api ("token refresh
        # is handled automatically (...) see token_refresh() for manual control").
        # Faltando da lista, nenhuma renovação acontecia e toda sessão vencida
        # caía direto no login completo, que custa de 5 a 18 s por conta.
        for method_name in ("token_refresh", "refresh_session", "refresh_token", "refresh"):
            method = getattr(client, method_name, None)
            if not callable(method):
                continue
            owner = getattr(method, "__self__", None)
            function = getattr(method, "__func__", method)
            identity = (id(owner), id(function))
            if identity in seen:
                continue
            seen.add(identity)
            try:
                result = method()
            except connector.ConnectorLoginCooldownError:
                raise
            except connector.ConnectorTemporaryError:
                raise
            except connector.ConnectorAuthenticationError:
                return False
            except Exception as exc:  # noqa: BLE001
                message = connector.clean_message(str(exc))
                cooldown = connector.login_cooldown_seconds(exc)
                if cooldown > 0:
                    raise connector.ConnectorLoginCooldownError(message, cooldown) from exc
                if connector.is_transient_cloud_error(exc):
                    raise connector.ConnectorTemporaryError(message) from exc
                LOG.info("Refresh de sessão por %s não foi aceito: %s", method_name, message)
                return False
            if result is not False:
                return True
        return False

    def execute_account_operation(self, environment: str, payload: dict[str, Any], sync: bool, origin: str) -> dict[str, Any]:
        """Execute account test/sync under the persistent account auth coordinator."""
        account_id = self._account_id(payload)
        self.assert_account_cloud_allowed(environment, payload, origin)

        # Reutilize a sessão da telemetria quando ela pertence às mesmas
        # credenciais. Assim sincronizar não cria um segundo token apenas para
        # consultar os mesmos veículos.
        subscription_id = ""
        credentials_value = payload.get("credentials") if sync else payload
        credentials = credentials_value if isinstance(credentials_value, dict) else {}
        expected_hash = hashlib.sha256(canonical_json(credentials)).hexdigest() if credentials else ""
        if account_id > 0:
            with self.lock, self._db() as db:
                row = db.execute(
                    "SELECT subscription_id,credentials_encrypted FROM subscriptions WHERE environment=? AND account_id=? AND enabled=1 "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (str(environment or ""), account_id),
                ).fetchone()
            subscription_id = str(row["subscription_id"] or "") if row is not None else ""
            if row is not None and credentials:
                try:
                    stored_credentials = json.loads(
                        self.fernet.decrypt(bytes(row["credentials_encrypted"])).decode("utf-8")
                    )
                    required = ("email", "password", "certificate_pem", "private_key_pem")
                    if isinstance(stored_credentials, dict) and all(
                        str(stored_credentials.get(key) or "") == str(credentials.get(key) or "")
                        for key in required
                    ):
                        expected_hash = str(self.sessions.get(subscription_id, {}).get("credential_hash") or expected_hash)
                except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
                    pass
        if subscription_id:
            with self._session_operation_lock(subscription_id):
                with self.session_lock:
                    session = self.sessions.get(subscription_id)
                if (
                    isinstance(session, dict)
                    and session.get("client") is not None
                    and expected_hash
                    and session.get("credential_hash") == expected_hash
                ):
                    try:
                        cached_for_operation = None
                        if sync and str(payload.get("vehicle_id") or "").strip():
                            cached_value = session.get("vehicles")
                            cached_at = float(session.get("vehicles_cached_at") or 0)
                            if isinstance(cached_value, list) and cached_value and time.time() - cached_at < self.vehicle_list_cache_seconds:
                                cached_for_operation = cached_value
                        result = connector.handle_account(
                            payload, sync=sync, borrowed_client=session["client"],
                            borrowed_vehicles=cached_for_operation,
                        )
                        session["last_used_at"] = time.time()
                        if isinstance(result.get("vehicles"), list):
                            # serialized vehicles are not suitable as library objects;
                            # keep the original borrowed list already stored.
                            pass
                        self.record_account_auth_success(environment, payload, origin + "_session")
                        return result
                    except connector.ConnectorAuthenticationError:
                        try:
                            refreshed = self._try_refresh_client_session(session["client"])
                        except connector.ConnectorLoginCooldownError as exc:
                            self._close_session_locked(subscription_id)
                            delay = self.record_account_auth_failure(
                                environment, payload, origin + "_refresh", str(exc), exc.retry_after_seconds, blocked=True
                            )
                            raise connector.ConnectorLoginCooldownError(str(exc), delay) from exc
                        except connector.ConnectorTemporaryError as exc:
                            session["last_used_at"] = time.time()
                            self.record_account_auth_failure(
                                environment, payload, origin + "_refresh", str(exc), 60, blocked=False
                            )
                            raise connector.ConnectorTemporaryError(str(exc)) from exc
                        if refreshed:
                            try:
                                cached_for_operation = None
                                if sync and str(payload.get("vehicle_id") or "").strip():
                                    cached_value = session.get("vehicles")
                                    cached_at = float(session.get("vehicles_cached_at") or 0)
                                    if isinstance(cached_value, list) and cached_value and time.time() - cached_at < self.vehicle_list_cache_seconds:
                                        cached_for_operation = cached_value
                                result = connector.handle_account(
                                    payload, sync=sync, borrowed_client=session["client"],
                                    borrowed_vehicles=cached_for_operation,
                                )
                                session["last_used_at"] = time.time()
                                self.record_account_auth_success(environment, payload, origin + "_refresh")
                                return result
                            except connector.ConnectorLoginCooldownError as exc:
                                self._close_session_locked(subscription_id)
                                delay = self.record_account_auth_failure(
                                    environment, payload, origin, str(exc), exc.retry_after_seconds, blocked=True
                                )
                                raise connector.ConnectorLoginCooldownError(str(exc), delay) from exc
                            except connector.ConnectorAuthenticationError:
                                # O refresh não recuperou a sessão. Feche somente
                                # esta sessão e siga para uma única autenticação
                                # coordenada, sem deixar o cliente inválido em uso.
                                self._close_session_locked(subscription_id)
                            except connector.ConnectorTemporaryError as exc:
                                self.record_account_auth_failure(
                                    environment, payload, origin, str(exc), 60, blocked=False
                                )
                                raise connector.ConnectorTemporaryError(str(exc)) from exc
                        else:
                            self._close_session_locked(subscription_id)
                    except connector.ConnectorLoginCooldownError as exc:
                        delay = self.record_account_auth_failure(
                            environment, payload, origin, str(exc), exc.retry_after_seconds, blocked=True
                        )
                        raise connector.ConnectorLoginCooldownError(str(exc), delay) from exc
                    except connector.ConnectorTemporaryError as exc:
                        self.record_account_auth_failure(
                            environment, payload, origin, str(exc), 60, blocked=False
                        )
                        raise connector.ConnectorTemporaryError(str(exc)) from exc

        reservation = self.begin_account_auth(environment, payload, origin)
        try:
            result = connector.handle_account(payload, sync=sync)
            self.record_account_auth_success(environment, payload, origin)
            return result
        except connector.ConnectorLoginCooldownError as exc:
            delay = self.record_account_auth_failure(
                environment, payload, origin, str(exc), exc.retry_after_seconds, blocked=True
            )
            raise connector.ConnectorLoginCooldownError(str(exc), delay) from exc
        except connector.ConnectorTemporaryError as exc:
            if reservation.get("managed"):
                self.record_account_auth_failure(environment, payload, origin, str(exc), 60, blocked=False)
                raise connector.ConnectorTemporaryError(str(exc)) from exc
            raise
        except Exception:
            if reservation.get("managed"):
                self.record_account_auth_failure(environment, payload, origin, "Falha de autenticação ou sincronização.", 60, blocked=False)
            raise

    def _set_account_login_cooldown(self, environment: str, account_id: int, retry_after_seconds: int, message: str) -> None:
        self.record_account_auth_failure(
            environment, account_id, "legacy", message, retry_after_seconds, blocked=True
        )

    def _clear_account_login_cooldown(self, environment: str, account_id: int) -> None:
        self.record_account_auth_success(environment, account_id, "session_ok")

    def _execute_isolated_command(
        self,
        environment: str,
        payload: dict[str, Any],
        account_id: int,
        progress: Callable[[str, str, dict[str, Any] | None], None] | None = None,
    ) -> dict[str, Any]:
        self.begin_account_auth(environment, account_id, "command")
        try:
            result = connector.handle_command(payload, progress=progress)
            self.record_account_auth_success(environment, account_id, "command")
            return result
        except connector.ConnectorLoginCooldownError as exc:
            delay = self.record_account_auth_failure(
                environment, account_id, "command", str(exc), exc.retry_after_seconds, blocked=True
            )
            raise connector.ConnectorLoginCooldownError(str(exc), delay) from exc
        except connector.ConnectorTemporaryError as exc:
            self.record_account_auth_failure(environment, account_id, "command", str(exc), 60, blocked=False)
            raise connector.ConnectorTemporaryError(str(exc)) from exc
        except Exception:
            self.record_account_auth_failure(
                environment, account_id, "command", "Falha durante autenticação de comando.", 60, blocked=False
            )
            raise

    def _create_persistent_session_locked(
        self,
        subscription_id: str,
        environment: str,
        account_id: int,
        credentials: dict[str, Any],
        origin: str,
        manual_should_yield: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Authenticate once and retain the client for commands and FAST telemetry.

        The caller must hold the subscription operation lock. Keeping the client
        created for a manual command prevents the confirmation cycle from opening
        a second Leapmotor login immediately after the action was accepted.
        """
        now_epoch = time.time()
        credential_hash = hashlib.sha256(canonical_json(credentials)).hexdigest()
        if manual_should_yield is not None and manual_should_yield():
            raise TelemetryYieldForManual("Operação manual aguardando antes da autenticação automática.")

        temp_dir = connector.secure_temp_directory()
        client = None
        try:
            client = connector.create_client(
                credentials,
                temp_dir,
                None,
                request_timeout_seconds=self.request_timeout_seconds,
            )
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual recebeu prioridade antes do login automático.")

            self.begin_account_auth(environment, account_id, origin)
            with self.lock, self._db() as db:
                db.execute(
                    "UPDATE subscriptions SET last_auth_attempt_at=?,updated_at=? WHERE subscription_id=?",
                    (time.time(), utc_iso(), subscription_id),
                )
            client.login()
            self.record_account_auth_success(environment, account_id, origin)
            with self.lock, self._db() as db:
                db.execute(
                    "UPDATE subscriptions SET last_auth_success_at=?,cooldown_reason=NULL,updated_at=? WHERE subscription_id=?",
                    (time.time(), utc_iso(), subscription_id),
                )
        except Exception as exc:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            shutil.rmtree(temp_dir, ignore_errors=True)
            if isinstance(exc, TelemetryYieldForManual):
                raise
            delay = connector.login_cooldown_seconds(exc)
            if delay > 0:
                protected_delay = self.record_account_auth_failure(
                    environment,
                    account_id,
                    origin,
                    str(exc),
                    delay,
                    blocked=True,
                )
                raise connector.ConnectorLoginCooldownError(
                    "A Leapmotor limitou temporariamente novas autenticações. A próxima tentativa respeitará o cooldown global.",
                    protected_delay,
                ) from exc
            if connector.is_transient_cloud_error(exc) or isinstance(exc, connector.ConnectorTemporaryError):
                self.record_account_auth_failure(environment, account_id, origin, str(exc), 60, blocked=False)
            else:
                self.record_account_auth_failure(
                    environment,
                    account_id,
                    origin,
                    "Falha de autenticação.",
                    60,
                    blocked=False,
                )
            raise

        session = {
            "client": client,
            "temp_dir": temp_dir,
            "credential_hash": credential_hash,
            "created_at": now_epoch,
            "last_used_at": now_epoch,
            "vehicles": [],
            "vehicles_cached_at": 0.0,
            "messages": [],
            "messages_cached_at": 0.0,
            # O primeiro ciclo após comando continua FAST. SLOW não disputa
            # a confirmação do estado físico.
            "slow_last_at": now_epoch,
        }
        with self.session_lock:
            self.sessions[subscription_id] = session
        LOG.info(
            "Sessão Leapmotor criada para %s por %s; será reutilizada pela próxima leitura FAST.",
            subscription_id,
            origin,
        )
        return session

    def execute_command(
        self,
        environment: str,
        payload: dict[str, Any],
        progress: Callable[[str, str, dict[str, Any] | None], None] | None = None,
    ) -> dict[str, Any]:
        """Executa a ação sob a mesma sessão e trava usadas pela telemetria.

        Uma sessão válida nunca é destruída apenas porque o usuário acionou um
        comando. Se não houver sessão ativa, o cliente autenticado pelo comando
        fica retido para a confirmação FAST. Falhas transitórias preservam a
        sessão e nenhuma ação aceita pela nuvem é repetida automaticamente.
        """
        try:
            account_id = int(payload.get("account_id") or 0)
        except (TypeError, ValueError):
            account_id = 0
        if account_id < 1:
            return connector.handle_command(payload, progress=progress)

        # 1.12.56 — nada entre a entrada do método e a trava de sessão tinha
        # contador. Com session_wait/login/prepare/verification todos em 0 e o
        # dispatch em ~4s, comandos de 94s deixavam 90s sem atribuição nenhuma.
        engine_started = time.monotonic()
        self.assert_account_cloud_allowed(environment, account_id, "command")
        auth_status_ms = int(round((time.monotonic() - engine_started) * 1000))

        # 1.12.56 — `engine_precheck_ms` virou um balde de 135s em campo, e ele
        # cobre três coisas distintas. Sem separar, a próxima investigação vira
        # palpite outra vez. A aquisição também ganha teto: se a trava não sair,
        # o comando falha rápido como transitório (503, `temporary: true`), o
        # site o mantém na fila e nenhuma ação física chega ao veículo — o
        # dispatch acontece bem depois deste ponto.
        engine_lock_started = time.monotonic()
        if not self.lock.acquire(timeout=ENGINE_LOCK_COMMAND_TIMEOUT_SECONDS):
            raise connector.ConnectorTemporaryError(
                "O Gateway estava ocupado com outra leitura e não liberou o motor a tempo. "
                "O comando não foi enviado ao veículo e continua na fila."
            )
        engine_lock_wait_ms = int(round((time.monotonic() - engine_lock_started) * 1000))
        subscription_read_started = time.monotonic()
        try:
            with self._db() as db:
                row = db.execute(
                    "SELECT subscription_id,cooldown_until,status FROM subscriptions "
                    "WHERE environment=? AND account_id=? AND enabled=1 "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (str(environment or ""), account_id),
                ).fetchone()
        finally:
            self.lock.release()
        subscription_read_ms = int(round((time.monotonic() - subscription_read_started) * 1000))
        if row is None:
            return self._execute_isolated_command(environment, payload, account_id, progress)

        subscription_id = str(row["subscription_id"] or "")
        if not subscription_id:
            return self._execute_isolated_command(environment, payload, account_id, progress)
        cooldown_until = float(row["cooldown_until"] or 0)
        if cooldown_until > time.time():
            raise connector.ConnectorLoginCooldownError(
                "A Leapmotor limitou temporariamente novas autenticações. O comando continua protegido na fila.",
                max(30, int(cooldown_until - time.time())),
            )

        # 1.12.50 — a espera pela trava de sessão e a autenticação feitas aqui
        # não tinham contador: ficavam dentro de remote_execute_ms sem aparecer
        # em nenhuma fase, e session_prepare_ms mede apenas o open_client() do
        # conector, que é ~0ms com cliente emprestado.
        session_wait_started = time.monotonic()
        engine_precheck_ms = int(round((session_wait_started - engine_started) * 1000))
        with self._session_operation_lock(subscription_id):
            session_wait_ms = int(round((time.monotonic() - session_wait_started) * 1000))
            session_login_ms = 0
            command_credentials = payload.get("credentials") if isinstance(payload.get("credentials"), dict) else {}
            session_credentials = dict(command_credentials)
            session_credentials.pop("operation_password", None)
            expected_hash = hashlib.sha256(canonical_json(session_credentials)).hexdigest() if session_credentials else ""
            if not expected_hash:
                return self._execute_isolated_command(environment, payload, account_id, progress)

            with self.session_lock:
                session = self.sessions.get(subscription_id)

            now_epoch = time.time()
            session_stale = (
                not isinstance(session, dict)
                or session.get("client") is None
                or session.get("credential_hash") != expected_hash
                or (self.session_max_age_seconds > 0 and now_epoch - float(session.get("created_at") or 0) >= self.session_max_age_seconds)
                or (self.session_idle_seconds > 0 and now_epoch - float(session.get("last_used_at") or 0) >= self.session_idle_seconds)
            )
            if session_stale:
                login_started = time.monotonic()
                self._close_session_locked(subscription_id)
                session = self._create_persistent_session_locked(
                    subscription_id,
                    environment,
                    account_id,
                    session_credentials,
                    "command",
                )
                session_login_ms = int(round((time.monotonic() - login_started) * 1000))

            session["last_used_at"] = now_epoch
            try:
                handle_started = time.monotonic()
                try:
                    result = connector.handle_command(
                        payload,
                        progress=progress,
                        borrowed_client=session["client"],
                        borrowed_vehicles=session.get("vehicles") if isinstance(session.get("vehicles"), list) else None,
                    )
                finally:
                    handle_command_ms = int(round((time.monotonic() - handle_started) * 1000))
                session["last_used_at"] = time.time()
                self.record_account_auth_success(environment, account_id, "command_session")
                result["session_retained_for_fast_confirmation"] = True
                arm_started = time.monotonic()
                try:
                    self._arm_command_confirmation(subscription_id, payload, result)
                finally:
                    confirmation_arm_ms = int(round((time.monotonic() - arm_started) * 1000))
                # As fases só entram depois do arme: assim `handle_command_ms` e
                # `confirmation_arm_ms` fecham a soma com remote_execute_ms e o
                # que sobrar de não atribuído fica realmente sem candidato.
                phase = result.get("phase_latency_ms")
                if isinstance(phase, dict):
                    phase["session_wait_ms"] = session_wait_ms
                    phase["session_login_ms"] = session_login_ms
                    phase["engine_precheck_ms"] = engine_precheck_ms
                    # As três somam engine_precheck_ms e dizem qual delas gastou.
                    phase["auth_status_ms"] = auth_status_ms
                    phase["engine_lock_wait_ms"] = engine_lock_wait_ms
                    phase["subscription_read_ms"] = subscription_read_ms
                    phase["handle_command_ms"] = handle_command_ms
                    phase["confirmation_arm_ms"] = confirmation_arm_ms
                return result
            except Exception as exc:
                session["last_used_at"] = time.time()
                if connector.is_command_certificate_session_error(exc):
                    # Cert/sync ou a verificação remota pré-envio recusaram o token
                    # antes de qualquer ação chegar ao veículo. A sessão compartilhada
                    # é descartada e o mesmo comando é tentado uma única vez em uma
                    # autenticação limpa. Erros de token após aceite nunca entram aqui.
                    LOG.warning(
                        "Sessão de %s expirou na verificação pré-envio; recriando uma única vez antes da ação.",
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
                    recovered_session = self._create_persistent_session_locked(
                        subscription_id,
                        environment,
                        account_id,
                        session_credentials,
                        "command_recovery",
                    )
                    try:
                        recovered = connector.handle_command(
                            payload,
                            progress=progress,
                            borrowed_client=recovered_session["client"],
                            borrowed_vehicles=None,
                        )
                    except Exception as recovered_exc:
                        recovered_session["last_used_at"] = time.time()
                        if connector.is_authentication_error(recovered_exc):
                            self._close_session_locked(subscription_id)
                        raise
                    recovered_session["last_used_at"] = time.time()
                    self.record_account_auth_success(environment, account_id, "command_recovery_session")
                    recovered["session_recovered"] = True
                    recovered["session_reused"] = True
                    recovered["session_retained_for_fast_confirmation"] = True
                    self._arm_command_confirmation(subscription_id, payload, recovered)
                    return recovered
                if isinstance(exc, connector.ConnectorLoginCooldownError):
                    self._set_account_login_cooldown(environment, account_id, exc.retry_after_seconds, str(exc))
                if connector.is_authentication_error(exc):
                    self._close_session_locked(subscription_id)
                raise

    def _arm_command_confirmation(
        self,
        subscription_id: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        """Arm FAST telemetry before the site starts polling command status.

        The command worker already knows the exact subscription, remote vehicle
        and immutable request id. Persisting that context here removes the
        dependency on a later PHP worker round-trip. The site may repeat the
        boost as a recovery signal; ``boost`` preserves an active window for the
        same request instead of resetting its samples.
        """
        command = str(payload.get("command") or "").strip().lower()
        if (
            command not in TELEMETRY_CONFIRMABLE_COMMANDS
            or not bool(result.get("confirmation_pending"))
            or not bool(result.get("command_dispatched") or result.get("cloud_accepted"))
        ):
            result["confirmation_armed_by_gateway"] = False
            return

        context = {
            "command_key": command,
            "command_id": 0,
            "vehicle_remote_id": str(payload.get("vehicle_id") or "").strip()[:190],
            "parameters": payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {},
            "request_id": str(payload.get("request_id") or "").strip()[:96],
        }
        try:
            armed = self.boost(
                subscription_id,
                seconds=180,
                profile="command",
                context=context,
            )
            result["confirmation_armed_by_gateway"] = bool(armed.get("ok"))
            result["confirmation_window_reused"] = bool(armed.get("confirmation_window_reused"))
            if not armed.get("ok"):
                LOG.warning(
                    "Comando %s foi aceito, mas a janela FAST interna de %s não pôde ser armada: %s",
                    command,
                    subscription_id,
                    connector.clean_message(str(armed.get("message") or "indisponível")),
                )
        except Exception as exc:  # noqa: BLE001
            # A ação física já foi aceita. Uma falha local ao armar a leitura
            # não transforma sucesso remoto em erro nem autoriza reenvio.
            result["confirmation_armed_by_gateway"] = False
            LOG.warning(
                "Comando %s foi aceito, mas a janela FAST interna de %s será recuperada pelo site: %s",
                command,
                subscription_id,
                connector.clean_message(str(exc)),
            )

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
        self._poll_pool = ThreadPoolExecutor(
            max_workers=self.poll_workers,
            thread_name_prefix="leaphub-telemetry-poll",
        )
        self.worker = threading.Thread(target=self._run, name="leaphub-telemetry", daemon=True)
        self.worker.start()
        self.delivery_worker = threading.Thread(
            target=self._run_delivery, name="leaphub-telemetry-delivery", daemon=True
        )
        self.delivery_worker.start()
        LOG.info(
            "Telemetria contínua iniciada com fila persistente em %s; %s coletas paralelas e entrega dedicada.",
            self.db_path,
            self.poll_workers,
        )

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        self.delivery_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=12)
        if self.delivery_worker and self.delivery_worker.is_alive():
            self.delivery_worker.join(timeout=12)
        pool, self._poll_pool = self._poll_pool, None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        self._close_all_sessions()
        self.close_storage()
        self._close_delivery_connection()

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
        config_hash = hashlib.sha256(canonical_json({
            "environment": environment,
            "account_id": account_id,
            "vehicle_ids": vehicle_ids,
            "enabled": enabled,
            "credential_hash": credential_hash,
        })).hexdigest()
        with self.lock, self._db() as db:
            existing = db.execute(
                "SELECT credential_hash, config_hash, credentials_encrypted, auth_required, cooldown_until, cooldown_reason, active_until, interactive_until, command_until, next_run_at, status, enabled "
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
        existing_config_hash = str(existing["config_hash"] or "") if existing is not None else ""
        session_present = existing is not None and self._has_session(subscription_id)
        verified_healthy_session = credentials_verified and not credentials_changed and session_present
        if (
            existing is not None
            and existing_config_hash
            and hmac.compare_digest(existing_config_hash, config_hash)
            and (not credentials_verified or verified_healthy_session)
        ):
            status = str(existing["status"] or "waiting")
            response = {
                "ok": not protected_auth and not protected_cooldown,
                "subscription_id": subscription_id,
                "vehicle_count": len(vehicle_ids),
                "unchanged": True,
                "deduplicated": True,
                "credentials_changed": False,
                "credentials_verified": credentials_verified,
                "auth_reset": False,
                "cooldown_reset": False,
                "session_preserved": session_present,
                "next_run_seconds": max(0, int(float(existing["next_run_at"] or 0) - now_epoch)),
                "status": status,
            }
            ORCHESTRATOR.record_deduplicated("telemetry_subscription_upsert")
            if protected_auth:
                response.update({"auth_required": True, "protected": True, "message": "Credenciais recusadas anteriormente; confirme a conta antes de uma nova tentativa."})
            elif protected_cooldown:
                response.update({
                    "cooldown": True,
                    "protected": True,
                    "retry_after_seconds": max(1, int(existing_cooldown_until - now_epoch)),
                    "cooldown_reason": str(existing["cooldown_reason"] or "login"),
                    "message": "A Leapmotor ainda não liberou novas chamadas. O Gateway aguardará automaticamente.",
                })
            return response

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

        # `credentials_verified` confirma que uma consulta manual funcionou,
        # mas não significa que a sessão ativa ficou inválida. Fechá-la aqui
        # aguardava a operação de telemetria em curso e fazia o site repetir o
        # mesmo upsert após o timeout. Somente uma verificação sem sessão ativa
        # precisa limpar o estado de recuperação e preparar uma nova sessão.
        verification_requires_reset = credentials_verified and not verified_healthy_session
        if credentials_changed or verification_requires_reset or not enabled:
            self._close_session(subscription_id)
        encrypted = self.fernet.encrypt(canonical_json(credentials))
        with self.lock, self._db() as db:
            db.execute(
                """
                INSERT INTO subscriptions
                (subscription_id, environment, account_id, credentials_encrypted, vehicle_ids_json, enabled, status, next_run_at,
                 last_run_at, last_success_at, last_delivery_at, last_error, last_state, parked_streak, consecutive_failures,
                 cooldown_until, active_until, interactive_until, command_until, last_presence_at, auth_required, credential_hash, config_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    credential_hash=excluded.credential_hash, config_hash=excluded.config_hash, updated_at=excluded.updated_at
                """,
                (subscription_id, environment, account_id, encrypted, json.dumps(vehicle_ids), 1 if enabled else 0,
                 status, next_run, cooldown_until, active_until, interactive_until, command_until, now, auth_required, credential_hash, config_hash, now, now),
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
                "cooldown_reason": str(existing["cooldown_reason"] or "rate_limit") if existing is not None else "rate_limit",
                "message": (
                    "A Leapmotor ainda não liberou uma nova autenticação. O Gateway aguardará automaticamente."
                    if existing is not None and str(existing["cooldown_reason"] or "") == "login"
                    else "Proteção contra limite de requisições ainda está ativa."
                ),
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
            "session_preserved": not credentials_changed and not verification_requires_reset and self._has_session(subscription_id),
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
                if self.background_enabled:
                    status = "background"
                    # Não adia uma leitura já próxima e nunca deixa o próximo
                    # teste de atividade além do limite econômico configurado.
                    next_run = min(max(next_run, now_epoch + 5), now_epoch + self.background_seconds)
                else:
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
                "SELECT auth_required, cooldown_until, cooldown_reason, enabled, next_run_at, status,"
                "command_until,command_key,command_vehicle_id,command_context_json,command_poll_count,command_started_at "
                "FROM subscriptions WHERE subscription_id=? LIMIT 1",
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
                    "cooldown_reason": str(row["cooldown_reason"] or "rate_limit"),
                    "message": (
                        "A Leapmotor ainda não liberou uma nova autenticação. O Gateway aguardará automaticamente."
                        if str(row["cooldown_reason"] or "") == "login"
                        else "Proteção contra limite de requisições ainda está ativa."
                    ),
                }
            current_next = float(row["next_run_at"] or 0)
            current_status = str(row["status"] or "").strip().lower()
            protected_wait = current_status in {"recovering", "error", "cooldown", "auth_required"} and current_next > now_epoch
            requested_next = now_epoch + 0.35
            next_run = current_next if protected_wait else (min(current_next, requested_next) if current_next > now_epoch else requested_next)
            interactive_until = now_epoch + seconds if profile == "interactive" else 0.0
            command_until = now_epoch + seconds if profile == "command" else 0.0
            existing_context: dict[str, Any] = {}
            try:
                parsed_context = json.loads(str(row["command_context_json"] or "{}"))
                if isinstance(parsed_context, dict):
                    existing_context = parsed_context
            except (TypeError, ValueError, json.JSONDecodeError):
                existing_context = {}
            requested_request_id = str(safe_context.get("request_id") or "")
            existing_request_id = str(existing_context.get("request_id") or "")
            same_command_window = (
                profile == "command"
                and float(row["command_until"] or 0) > now_epoch
                and str(row["command_key"] or "") == command_key
                and str(row["command_vehicle_id"] or "") == command_vehicle_id
                and (
                    requested_request_id == existing_request_id
                    or (not requested_request_id and bool(existing_request_id))
                )
            )
            if protected_wait:
                if profile == "command" and not same_command_window:
                    cursor = db.execute(
                        "UPDATE subscriptions SET active_until=MAX(active_until,?),"
                        "command_until=MAX(command_until,?),command_key=?,command_vehicle_id=?,command_context_json=?,"
                        "command_poll_count=0,command_started_at=?,last_presence_at=?,updated_at=? "
                        "WHERE subscription_id=? AND enabled=1",
                        (
                            now_epoch + seconds,
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
                else:
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
                    "confirmation_window_reused": same_command_window,
                    "retry_after_seconds": max(1, int(current_next - now_epoch)),
                }
            if profile == "command":
                if same_command_window:
                    cursor = db.execute(
                        "UPDATE subscriptions SET status='waiting',next_run_at=?,active_until=MAX(active_until,?),"
                        "command_until=MAX(command_until,?),last_presence_at=?,last_error=NULL,updated_at=? "
                        "WHERE subscription_id=? AND enabled=1",
                        (
                            next_run,
                            now_epoch + seconds,
                            command_until,
                            now_iso,
                            now_iso,
                            subscription_id,
                        ),
                    )
                else:
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
            "confirmation_window_reused": same_command_window if profile == "command" else False,
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

    def collection_status(self) -> dict[str, Any]:
        """Saturação da coleta paralela, sem tocar no banco.

        1.12.51 — diagnosticar a lentidão anterior exigiu ler o log linha a linha.
        Estes três números respondem de imediato se as coletas estão enfileiradas
        atrás dos workers e se o journal que ficou valendo é o esperado.
        """
        with self._inflight_guard:
            in_flight = len(self._inflight)
        return {
            "poll_workers": int(self.poll_workers),
            "polls_in_flight": in_flight,
            "workers_saturated": in_flight >= int(self.poll_workers),
            "delivery_connection_reused": self._delivery_connection is not None,
            "journal_mode": self.storage_journal_mode,
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
                "collection": self.collection_status(),
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
                "collection": self.collection_status(),
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
                    "last_error, last_state, next_run_at, active_until, interactive_until, command_until, command_key, command_vehicle_id, command_poll_count, command_started_at, last_presence_at, auth_required, cooldown_until, cooldown_reason, last_auth_attempt_at, last_auth_success_at "
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
            item["last_auth_attempt_seconds_ago"] = max(0, int(now_epoch - float(item.pop("last_auth_attempt_at") or now_epoch)))
            last_auth_success = float(item.pop("last_auth_success_at") or 0)
            item["last_auth_success_seconds_ago"] = max(0, int(now_epoch - last_auth_success)) if last_auth_success > 0 else None
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
                "collection_profiles": {
                    "fast": "status_and_vehicle_state",
                    "slow": "messages_and_official_visual",
                    "slow_interval_seconds": self.slow_interval_seconds,
                    "degraded_disables_slow": True,
                },
                "charging_seconds": self.charging_seconds,
                "charge_watch_seconds": self.charge_watch_seconds,
                "parked_seconds": self.parked_seconds,
                "sleep_seconds": self.sleep_seconds,
                "background_enabled": self.background_enabled,
                "background_seconds": self.background_seconds,
                "rate_limit_cooldown_seconds": self.rate_limit_cooldown_seconds,
                "auth_attempt_min_interval_seconds": self.auth_attempt_min_interval_seconds,
                "presence_window_seconds": self.presence_window_seconds,
                "presence_driven": not self.background_enabled,
                "presence_role": "fast_mode",
                "session_reuse": True,
            },
            "event_transport": EVENT_TRANSPORT.snapshot(),
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
        """Escalonador. A coleta vai para o pool; a entrega tem thread própria."""
        while not self.stop_event.is_set():
            did_work = False
            storage_wait: float | None = None
            try:
                did_work = self._dispatch_due_subscriptions()
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

    def _run_delivery(self) -> None:
        """Entrega ao site em thread dedicada.

        1.12.50 — o POST tem timeout próprio e a hospedagem do site pode demorar.
        Enquanto ele morava no laço principal, uma lentidão do site parava a
        coleta de todas as contas pelo mesmo tempo.
        """
        while not self.stop_event.is_set():
            wait = 2.0
            try:
                if self._deliver_due():
                    wait = 0.25
                # A recuperação do armazenamento é declarada apenas pelo
                # escalonador, que abre o banco em todo ciclo. Duas threads
                # zerando o mesmo contador só produziria log oscilante.
            except (OSError, sqlite3.Error) as exc:
                wait = self._record_storage_failure(exc)
            except Exception:  # noqa: BLE001
                LOG.exception("Falha na entrega de telemetria")
                wait = 5.0
            self.delivery_event.wait(max(0.25, wait))
            self.delivery_event.clear()

    def _dispatch_due_subscriptions(self) -> bool:
        """Entrega ao pool as assinaturas vencidas que ainda não estão em coleta."""
        pool = self._poll_pool
        if pool is None:
            return False
        dispatched = False
        while not self.stop_event.is_set():
            with self._inflight_guard:
                free = self.poll_workers - len(self._inflight)
            if free <= 0:
                break
            subscription = self._next_due_subscription()
            if subscription is None:
                break
            sid = str(subscription["subscription_id"])
            with self._inflight_guard:
                if sid in self._inflight:
                    break
                self._inflight.add(sid)
            dispatched = True
            pool.submit(self._poll_subscription_guarded, subscription, sid)
        return dispatched

    def _poll_subscription_guarded(self, subscription: sqlite3.Row, sid: str) -> None:
        try:
            self._poll_subscription(subscription)
        except (OSError, sqlite3.Error) as exc:
            self._record_storage_failure(exc)
        except Exception:  # noqa: BLE001
            LOG.exception("Falha ao consultar a assinatura %s", sid)
        finally:
            with self._inflight_guard:
                self._inflight.discard(sid)
            self.wake_event.set()

    def _next_due_subscription(self) -> sqlite3.Row | None:
        # A ordem de prioridade (comando -> interativo -> fundo) é preservada.
        # Uma assinatura já em coleta mantém next_run_at no passado até reagendar;
        # o conjunto _inflight é o que impede coleta duplicada da mesma conta.
        with self._inflight_guard:
            busy = set(self._inflight)
        with self.lock, self._db() as db:
            now_epoch = time.time()
            active_filter = "" if self.background_enabled else " AND active_until>?"
            parameters: tuple[float, ...]
            if self.background_enabled:
                parameters = (now_epoch, now_epoch, now_epoch)
            else:
                parameters = (now_epoch, now_epoch, now_epoch, now_epoch)
            rows = db.execute(
                "SELECT * FROM subscriptions WHERE enabled=1 AND auth_required=0"
                + active_filter
                + " AND next_run_at<=? "
                "ORDER BY CASE WHEN command_until>? THEN 0 WHEN interactive_until>? THEN 1 ELSE 2 END, next_run_at ASC LIMIT 12",
                parameters,
            ).fetchall()
        for row in rows:
            if str(row["subscription_id"]) not in busy:
                return row
        return None

    def _seconds_until_next(self) -> float:
        with self.lock, self._db() as db:
            if self.background_enabled:
                row = db.execute(
                    "SELECT MIN(next_run_at) due FROM subscriptions WHERE enabled=1 AND auth_required=0"
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT MIN(next_run_at) due FROM subscriptions WHERE enabled=1 AND auth_required=0 AND active_until>?",
                    (time.time(),),
                ).fetchone()
            delivery = db.execute("SELECT MIN(next_attempt_at) due FROM events WHERE status='pending'").fetchone()
        values = [float(item["due"]) for item in (row, delivery) if item and item["due"] is not None]
        return max(0.25, min(values) - time.time()) if values else 5.0

    def _poll_subscription(self, subscription: sqlite3.Row) -> None:
        sid = str(subscription["subscription_id"])
        now_epoch = time.time()
        active_until = float(subscription["active_until"] or 0)
        presence_active = active_until > now_epoch
        interactive = float(subscription["interactive_until"] or 0) > now_epoch
        command_mode = float(subscription["command_until"] or 0) > now_epoch
        fast_mode = interactive or command_mode
        if not presence_active and not self.background_enabled:
            # O fim da janela ativa pausa novas leituras, mas não encerra uma
            # sessão saudável. Fechar aqui obrigava um novo login a cada janela.
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

        environment = str(subscription["environment"])
        account_id = int(subscription["account_id"] or 0)
        # 1.12.47 — backpressure primeiro por conta. Uma única conta com
        # timeout/retry repetido reduz somente a própria telemetria de fundo.
        # O breaker global abaixo exige evidência de contas distintas.
        if (
            not fast_mode
            and ORCHESTRATOR.is_account_degraded(environment, account_id)
            and not ORCHESTRATOR.claim_account_background_probe(environment, account_id)
        ):
            self._reschedule(
                sid,
                60,
                "account_cloud_degraded",
                "Esta conta está em recuperação temporária; outras contas continuam com a cadência normal.",
                failed=False,
            )
            return

        # Breaker compartilhado: só reduz o ambiente quando contas distintas
        # falham na mesma janela, sinalizando indisponibilidade realmente comum.
        if not fast_mode and ORCHESTRATOR.is_degraded(environment) and not ORCHESTRATOR.claim_background_probe(environment):
            self._reschedule(
                sid,
                60,
                "cloud_degraded",
                "Nuvem Leapmotor degradada em múltiplas contas; telemetria automática reduzida sem afetar comandos manuais.",
                failed=False,
            )
            return
        global_auth = self.account_auth_status(environment, account_id)
        if global_auth.get("cooldown"):
            self._reschedule(
                sid,
                max(30, int(global_auth.get("retry_after_seconds") or 30)),
                "cooldown",
                "Cooldown desta conta ativo; as demais contas continuam independentes.",
                failed=False,
            )
            return
        cooldown_until = float(subscription["cooldown_until"] or 0)
        if cooldown_until > now_epoch:
            self._reschedule(sid, max(30, int(cooldown_until - now_epoch)), "cooldown", "Proteção de limite ativa; aguardando antes da próxima consulta.", failed=False)
            return
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
        # Uma leitura automática nunca abre outra autenticação poucos segundos
        # depois da anterior. Isso vale inclusive após reiniciar o App, pois o
        # horário fica persistido na assinatura. Comandos manuais continuam com
        # prioridade e usam o fluxo próprio.
        last_auth_attempt_at = float(subscription["last_auth_attempt_at"] or 0) if "last_auth_attempt_at" in subscription.keys() else 0.0
        if not command_mode and not self._has_session(sid) and last_auth_attempt_at > 0:
            remaining = self.auth_attempt_min_interval_seconds - int(now_epoch - last_auth_attempt_at)
            if remaining > 0:
                credentials.clear()
                self._reschedule(
                    sid,
                    max(5, remaining),
                    "waiting_auth",
                    "Aguardando o intervalo seguro antes de uma nova autenticação automática.",
                    failed=False,
                )
                return
        if self._manual_operation_blocks(environment, operation_payload, command_mode=command_mode):
            credentials.clear()
            self._reschedule(sid, 2, "waiting", "Comando do usuário tem prioridade sobre a telemetria automática.", failed=False)
            return

        # 1.12.47 — ordem única de aquisição: conta -> vaga global.
        # Antes a telemetria podia segurar uma vaga global enquanto aguardava
        # a trava de uma conta ocupada, invertendo a ordem usada pelos comandos
        # manuais. Isso permitia uma conta lenta consumir capacidade de outras.
        queue_started_at = time.monotonic()
        account_wait_ms = 0.0
        connector_slot_ms = 0.0
        account_lock = None
        account_acquired = False
        acquired = False
        if self.account_lock_provider is not None:
            account_lock = self.account_lock_provider(environment, operation_payload)
            account_wait_started_at = time.monotonic()
            account_acquired = account_lock.acquire(timeout=self.account_wait_seconds)
            account_wait_ms = (time.monotonic() - account_wait_started_at) * 1000.0
            if not account_acquired:
                credentials.clear()
                ORCHESTRATOR.record_telemetry_cycle(
                    environment,
                    profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                    duration_ms=0.0,
                    outcome="account_busy_yield",
                    account_wait_ms=account_wait_ms,
                    connector_slot_ms=0.0,
                )
                self._reschedule(
                    sid,
                    15,
                    "waiting",
                    "A conta já está sendo consultada por outra operação; nenhuma vaga global foi ocupada enquanto aguardava.",
                    failed=False,
                )
                return

        if self._manual_operation_blocks(environment, operation_payload, command_mode=command_mode):
            if account_acquired and account_lock is not None:
                account_lock.release()
            credentials.clear()
            ORCHESTRATOR.record_telemetry_cycle(
                environment,
                profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                duration_ms=0.0,
                outcome="manual_yield",
                account_wait_ms=account_wait_ms,
                connector_slot_ms=0.0,
            )
            self._reschedule(sid, 2, "waiting", "Comando do usuário aguardando execução; telemetria liberou a conta antes de usar uma vaga global.", failed=False)
            return

        slot_wait_started_at = time.monotonic()
        slot_deadline = slot_wait_started_at + 5.0
        while True:
            acquired = self.operation_semaphore.acquire(timeout=0.25)
            if acquired:
                break
            if self._manual_operation_blocks(environment, operation_payload, command_mode=command_mode):
                if account_acquired and account_lock is not None:
                    account_lock.release()
                credentials.clear()
                connector_slot_ms = (time.monotonic() - slot_wait_started_at) * 1000.0
                ORCHESTRATOR.record_telemetry_cycle(
                    environment,
                    profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                    duration_ms=0.0,
                    outcome="manual_yield",
                    account_wait_ms=account_wait_ms,
                    connector_slot_ms=connector_slot_ms,
                )
                self._reschedule(sid, 2, "waiting", "Telemetria liberou a conta para um comando manual antes de ocupar o Connector.", failed=False)
                return
            if time.monotonic() >= slot_deadline:
                if account_acquired and account_lock is not None:
                    account_lock.release()
                credentials.clear()
                connector_slot_ms = (time.monotonic() - slot_wait_started_at) * 1000.0
                ORCHESTRATOR.record_telemetry_cycle(
                    environment,
                    profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                    duration_ms=0.0,
                    outcome="slot_timeout",
                    account_wait_ms=account_wait_ms,
                    connector_slot_ms=connector_slot_ms,
                )
                self._reschedule(sid, 30, "waiting", "Aguardando vaga no Connector; a conta foi liberada para não bloquear comandos.", failed=False)
                return

        connector_slot_ms = (time.monotonic() - slot_wait_started_at) * 1000.0
        if self._manual_operation_blocks(environment, operation_payload, command_mode=command_mode):
            self.operation_semaphore.release()
            if account_acquired and account_lock is not None:
                account_lock.release()
            credentials.clear()
            ORCHESTRATOR.record_telemetry_cycle(
                environment,
                profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                duration_ms=0.0,
                outcome="manual_yield",
                account_wait_ms=account_wait_ms,
                connector_slot_ms=connector_slot_ms,
            )
            self._reschedule(sid, 2, "waiting", "Comando do usuário aguardando execução; telemetria cedeu a vaga imediatamente.", failed=False)
            return
        manual_provider = self.manual_active_provider if command_mode else self.manual_pending_provider
        manual_should_yield = (
            (lambda: bool(manual_provider and manual_provider(environment, operation_payload)))
            if manual_provider is not None
            else None
        )
        collection_started_at = time.monotonic()
        try:
            result = self._collect_with_session(
                sid,
                environment,
                int(subscription["account_id"] or 0),
                credentials,
                vehicle_ids,
                command_mode=command_mode,
                manual_should_yield=manual_should_yield,
            )
        except TelemetryYieldForManual:
            ORCHESTRATOR.record_telemetry_cycle(
                environment,
                profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                duration_ms=(time.monotonic() - collection_started_at) * 1000.0,
                outcome="manual_yield",
                account_wait_ms=account_wait_ms,
                connector_slot_ms=connector_slot_ms,
            )
            self._reschedule(sid, 2, "waiting", "Telemetria cedeu a conta para o comando do usuário.", failed=False)
            LOG.info("Telemetria de %s interrompida em ponto seguro para priorizar comando manual.", sid)
            return
        except Exception as exc:  # noqa: BLE001
            ORCHESTRATOR.record_telemetry_cycle(
                environment,
                profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                duration_ms=(time.monotonic() - collection_started_at) * 1000.0,
                outcome="failure",
                account_wait_ms=account_wait_ms,
                connector_slot_ms=connector_slot_ms,
            )
            message = connector.clean_message(str(exc))
            failures = int(subscription["consecutive_failures"] or 0) + 1
            transient = connector.is_transient_cloud_error(exc) or isinstance(exc, connector.ConnectorTemporaryError)
            if not transient or failures >= 3:
                self._close_session(sid)
            if isinstance(exc, connector.ConnectorSessionExpiredError):
                delay = 20
                self._reschedule(
                    sid,
                    delay,
                    "waiting_auth",
                    "Sessão expirada; uma única reconexão protegida foi agendada.",
                    failed=False,
                )
                LOG.info("Sessão de %s expirou; uma reconexão coordenada ocorrerá em %ss.", sid, delay)
                return
            if isinstance(exc, connector.ConnectorLoginCooldownError):
                delay = max(30, min(self.login_cooldown_max_seconds, int(exc.retry_after_seconds or 300)))
                self._apply_account_subscription_cooldown(
                    environment, int(subscription["account_id"] or 0), delay, message, "login"
                )
                LOG.warning(
                    "Autenticação de %s aguardará %ss pelo coordenador global; nenhuma origem chamará a nuvem antes disso.",
                    sid, delay,
                )
            elif self._looks_rate_limited(message):
                requested_delay = connector.rate_limit_cooldown_seconds(message, self.rate_limit_cooldown_seconds)
                if requested_delay <= 0:
                    requested_delay = self.rate_limit_cooldown_seconds
                delay = self.record_account_auth_failure(
                    environment, int(subscription["account_id"] or 0), "telemetry_rate_limit",
                    message, requested_delay, blocked=True,
                )
                LOG.warning("Proteção da conta contra limite ativada para %s por %ss: %s", sid, delay, message)
            elif isinstance(exc, connector.ConnectorAuthenticationError) or connector.is_authentication_error(exc):
                self._mark_auth_required(sid, message)
                LOG.warning("A assinatura %s foi pausada até as credenciais serem confirmadas: %s", sid, message)
            elif transient:
                ORCHESTRATOR.record_cloud_failure(environment, account_id)
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
            # Libera primeiro o recurso global; a trava da conta sai logo depois.
            # A ordem inversa de aquisição nunca é usada em nenhum caminho.
            self.operation_semaphore.release()
            if account_acquired and account_lock is not None:
                account_lock.release()
            credentials.clear()

        collection_profile = str(result.get("collection_profile") or ("confirmation" if command_mode else "fast"))
        ORCHESTRATOR.record_telemetry_cycle(
            environment,
            profile="confirmation" if command_mode else collection_profile,
            duration_ms=(time.monotonic() - collection_started_at) * 1000.0,
            outcome="success",
            account_wait_ms=account_wait_ms,
            connector_slot_ms=connector_slot_ms,
        )
        ORCHESTRATOR.record_cloud_success(environment, account_id)
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
            # Durante a confirmação de comando, até um snapshot semanticamente
            # idêntico precisa chegar ao site. Ex.: `unlock` solicitado quando o
            # carro já estava destravado. Suprimir essa amostra deixava a
            # interface presa em confirmation_pending e também escondia a base
            # necessária para reconciliar um auto-lock posterior.
            queued = self._queue_event(
                subscription,
                vehicle,
                source_at,
                state,
                interactive=fast_mode,
                force_delivery=command_mode,
            )
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
        # 1.12.56 — três causas distintas produzem o mesmo "sem confirmação
        # conclusiva": o veículo-alvo não apareceu, as amostras foram velhas
        # demais, ou o campo que o matcher consulta não veio. Sem separar,
        # o diagnóstico vira palpite.
        command_stale_samples = 0
        command_evaluated_samples = 0
        command_field_gaps: list[str] = []
        command_available_keys: list[str] = []
        if command_mode and command_key:
            for vehicle in vehicles:
                if command_vehicle_id and str(vehicle.get("remote_id") or "") != command_vehicle_id:
                    continue
                command_target_seen = True
                telemetry = vehicle.get("telemetry") if isinstance(vehicle.get("telemetry"), dict) else {}
                if not self._command_sample_is_fresh(telemetry, float(subscription["command_started_at"] or 0)):
                    command_stale_samples += 1
                    continue
                command_evaluated_samples += 1
                matched, evaluable = self._command_confirmation(command_key, telemetry, command_context)
                command_evaluable = command_evaluable or evaluable
                if not evaluable:
                    # Guarda a última amostra inconclusiva; só nomes de campo.
                    command_field_gaps = self._command_confirmation_gaps(command_key, telemetry)
                    command_available_keys = sorted(str(key) for key in telemetry.keys())[:40]
                if matched:
                    command_confirmed = True
                    break

        next_command_poll = current_command_poll + 1 if command_mode else 0
        command_budget_exhausted = command_mode and next_command_poll >= self.command_max_polls
        effective_command_mode = command_mode and not command_confirmed and not command_budget_exhausted
        interval, observed_state, parked_streak = self._adaptive_interval(
            states,
            int(subscription["parked_streak"] or 0),
            interactive=interactive,
            command_mode=effective_command_mode,
            command_poll_count=next_command_poll,
        )
        aggregate_state, candidate_state, candidate_count = self._confirm_state_transition(
            str(subscription["last_state"] or ""),
            str(subscription["candidate_state"] or ""),
            int(subscription["candidate_count"] or 0),
            observed_state,
        )
        if aggregate_state != observed_state and not effective_command_mode:
            interval, _, parked_streak = self._adaptive_interval(
                [aggregate_state],
                int(subscription["parked_streak"] or 0),
                interactive=interactive,
            )
        previous_sleep_streak = int(subscription["sleep_streak"] or 0)
        sleep_streak = previous_sleep_streak + 1 if aggregate_state == "sleep" else 0
        if aggregate_state == "sleep" and not effective_command_mode:
            interval = self.sleep_seconds if sleep_streak < 3 else max(self.sleep_seconds, min(900, int(self.sleep_seconds * 1.5)))
        if self.background_enabled and not presence_active and not effective_command_mode:
            interval = min(interval, self.background_seconds)
        jitter = random.uniform(0, 0.25) if effective_command_mode else random.uniform(0, min(4.0, max(0.5, interval * 0.04)))
        now = utc_iso()
        next_run = time.time() + interval + jitter
        clear_expired_command = not command_mode and float(subscription["command_until"] or 0) > 0
        clear_command = (command_mode and (command_confirmed or command_budget_exhausted)) or clear_expired_command
        with self.lock, self._db() as db:
            if clear_command:
                db.execute(
                    "UPDATE subscriptions SET status='active', next_run_at=?, last_run_at=?, last_success_at=?, last_error=NULL, last_state=?, parked_streak=?, candidate_state=?, candidate_count=?, sleep_streak=?, consecutive_failures=0, cooldown_until=0, cooldown_reason=NULL, command_until=0, command_key=NULL, command_vehicle_id=NULL, command_context_json=NULL, command_poll_count=0, command_started_at=0, updated_at=? WHERE subscription_id=?",
                    (next_run, now, now, aggregate_state, parked_streak, candidate_state or None, candidate_count, sleep_streak, now, sid),
                )
            else:
                db.execute(
                    "UPDATE subscriptions SET status='active', next_run_at=?, last_run_at=?, last_success_at=?, last_error=NULL, last_state=?, parked_streak=?, candidate_state=?, candidate_count=?, sleep_streak=?, consecutive_failures=0, cooldown_until=0, cooldown_reason=NULL, command_poll_count=?, updated_at=? WHERE subscription_id=?",
                    (next_run, now, now, aggregate_state, parked_streak, candidate_state or None, candidate_count, sleep_streak, next_command_poll, now, sid),
                )
        if command_confirmed:
            LOG.info("Comando %s confirmado pela telemetria de %s após %s leitura(s); janela rápida encerrada.", command_key, sid, next_command_poll)
        elif command_budget_exhausted:
            if command_vehicle_id and not command_target_seen:
                LOG.warning("Janela rápida de %s não encontrou o veículo-alvo do comando entre os dados retornados; assinatura será reconciliada pelo site.", sid)
            LOG.warning("Janela rápida de %s encerrada após %s leitura(s) sem confirmação conclusiva; telemetria voltou ao modo adaptativo.", sid, next_command_poll)
            # 1.12.56 — a linha acima diz que falhou; esta diz por quê.
            LOG.warning(
                "Confirmação inconclusiva de %s em %s: amostras avaliadas=%s, descartadas por idade=%s, "
                "campos exigidos sem valor=[%s], chaves presentes na telemetria=[%s].",
                command_key or "desconhecido",
                sid,
                command_evaluated_samples,
                command_stale_samples,
                ", ".join(command_field_gaps) or "nenhum",
                ", ".join(command_available_keys) or "nenhuma",
            )
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
        environment: str,
        account_id: int,
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
                environment,
                account_id,
                credentials,
                vehicle_ids,
                command_mode=command_mode,
                manual_should_yield=manual_should_yield,
            )

    def _collect_with_session_locked(
        self,
        subscription_id: str,
        environment: str,
        account_id: int,
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
            or (self.session_max_age_seconds > 0 and now_epoch - float(session.get("created_at") or 0) >= self.session_max_age_seconds)
            or (self.session_idle_seconds > 0 and now_epoch - float(session.get("last_used_at") or 0) >= self.session_idle_seconds)
        ):
            self._close_session_locked(subscription_id)
            session = None

        if session is None:
            # Verifique a prioridade manual antes de criar uma nova sessão e
            # novamente imediatamente antes do login. Isso fecha a corrida em
            # que a telemetria iniciava a autenticação no mesmo instante em que
            # o usuário enviava um comando.
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual aguardando antes da autenticação automática.")
            session = self._create_persistent_session_locked(
                subscription_id,
                environment,
                account_id,
                credentials,
                "telemetry",
                manual_should_yield=manual_should_yield,
            )

        client = session["client"]
        try:
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual aguardando a conta.")
            cached_vehicles = session.get("vehicles") if isinstance(session.get("vehicles"), list) else []
            vehicles_cached_at = float(session.get("vehicles_cached_at") or 0)
            cache_fresh = bool(cached_vehicles) and now_epoch - vehicles_cached_at < self.vehicle_list_cache_seconds
            selected_ids_present = not vehicle_ids or all(
                any(
                    str(connector.attribute(item, "car_id", "") or connector.attribute(item, "vin", "")) == vehicle_id
                    for item in cached_vehicles
                )
                for vehicle_id in vehicle_ids
            )
            if cache_fresh and selected_ids_present:
                vehicles = cached_vehicles
            else:
                try:
                    vehicles_value = client.get_vehicle_list()
                except Exception as exc:  # noqa: BLE001
                    if connector.is_session_expired_error(exc):
                        if self._try_refresh_client_session(client):
                            LOG.info("Sessão de %s renovada por refresh antes de considerar novo login.", subscription_id)
                            vehicles_value = client.get_vehicle_list()
                        else:
                            self._close_session_locked(subscription_id)
                            raise connector.ConnectorSessionExpiredError(
                                "A sessão Leapmotor expirou e será recriada uma única vez no próximo ciclo protegido."
                            ) from exc
                    else:
                        raise
                vehicles = vehicles_value if isinstance(vehicles_value, list) else list(vehicles_value or [])
                session["vehicles"] = vehicles
                session["vehicles_cached_at"] = time.time()
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual aguardando a conta.")
            selected = vehicles
            if vehicle_ids:
                selected = [
                    item for item in vehicles
                    if str(connector.attribute(item, "car_id", "") or connector.attribute(item, "vin", "")) in vehicle_ids
                ]
            messages: list[Any] = []
            slow_last_at = float(session.get("slow_last_at") or 0)
            slow_cycle = (
                not command_mode
                and ORCHESTRATOR.secondary_network_allowed(environment, account_id)
                and now_epoch - slow_last_at >= self.slow_interval_seconds
            )
            get_messages = getattr(client, "get_message_list", None)
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual aguardando a conta.")
            if slow_cycle and callable(get_messages):
                cached_messages = session.get("messages") if isinstance(session.get("messages"), list) else []
                messages_cached_at = float(session.get("messages_cached_at") or 0)
                if messages_cached_at > 0 and now_epoch - messages_cached_at < self.message_cache_seconds:
                    messages = cached_messages
                else:
                    if manual_should_yield is not None and manual_should_yield():
                        raise TelemetryYieldForManual("Operação manual aguardando a conta.")
                    try:
                        message_page = get_messages(page_no=1, page_size=100)
                        messages = list(connector.attribute(message_page, "messages", []) or [])
                        session["messages"] = messages
                        session["messages_cached_at"] = time.time()
                    except Exception as exc:  # noqa: BLE001
                        if connector.is_session_expired_error(exc):
                            if self._try_refresh_client_session(client):
                                LOG.info("Sessão de %s renovada por refresh durante a leitura de mensagens.", subscription_id)
                                message_page = get_messages(page_no=1, page_size=100)
                                messages = list(connector.attribute(message_page, "messages", []) or [])
                                session["messages"] = messages
                                session["messages_cached_at"] = time.time()
                            else:
                                self._close_session_locked(subscription_id)
                                raise connector.ConnectorSessionExpiredError(
                                    "A sessão Leapmotor expirou durante a leitura de mensagens."
                                ) from exc
                        else:
                            messages = cached_messages
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
                        manual_should_yield=manual_should_yield,
                        include_secondary_network=slow_cycle,
                    )
                )
            if not serialized:
                raise RuntimeError("Nenhum veículo foi encontrado para esta conta.")
            session["last_used_at"] = time.time()
            session["vehicles"] = vehicles
            if slow_cycle:
                session["slow_last_at"] = time.time()
            return {
                "ok": True,
                "account_name": "Conta Leapmotor",
                "vehicles": serialized,
                "connector_version": connector.CONNECTOR_VERSION,
                "library_version": connector.package_version(),
                "session_reused": True,
                "collection_profile": "slow" if slow_cycle else "fast",
            }
        except TelemetryYieldForManual:
            session["last_used_at"] = time.time()
            raise
        except Exception as exc:
            if connector.is_session_expired_error(exc) or isinstance(exc, connector.ConnectorSessionExpiredError):
                self._close_session_locked(subscription_id)
                raise connector.ConnectorSessionExpiredError(
                    "A sessão Leapmotor expirou; o próximo ciclo fará uma única autenticação coordenada."
                ) from exc
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
        # READY/ignição isolados variam mesmo com o carro parado em alguns
        # firmwares. Só velocidade real ou estado driving não contradito por
        # is_parked confirmam condução.
        if speed > 1 or (state == "driving" and telemetry.get("is_parked") is not True):
            return "driving"
        if telemetry.get("plugged") is True or charging == "plugged":
            return "charge_watch"
        if (
            telemetry.get("is_parked") is True
            or state in {"parked", "locked", "off", "ready"}
            or telemetry.get("ready_state") is True
            or telemetry.get("ignition_on") is True
        ):
            return "parked"
        return "sleep"

    @staticmethod
    def _confirm_state_transition(
        previous_state: str, candidate_state: str, candidate_count: int, observed_state: str
    ) -> tuple[str, str, int]:
        previous = str(previous_state or "").lower()
        observed = str(observed_state or "sleep").lower()
        if not previous:
            return observed, "", 0
        if observed == previous:
            return previous, "", 0
        required = 1 if observed == "charging" else 3 if observed == "sleep" else 2
        count = int(candidate_count or 0) + 1 if str(candidate_state or "") == observed else 1
        if count >= required:
            return observed, "", 0
        return previous, observed, count

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
            if streak >= 6:
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

    # 1.12.56 — os campos que `_command_confirmation` consulta, por comando.
    # Comandos confirmados executam e o dono vê "não foi confirmado dentro da
    # janela segura": o matcher devolve inconclusivo quando o campo esperado
    # não vem na telemetria, e não havia como saber qual campo faltou. Um
    # contrato garante que este mapa cobre todo comando tratado no matcher.
    COMMAND_CONFIRMATION_FIELDS: dict[str, tuple[str, ...]] = {
        "lock": ("locked",),
        "unlock": ("locked",),
        "climate_on": ("climate_on",),
        "climate_off": ("climate_on",),
        "quick_cool": ("climate_on",),
        "quick_heat": ("climate_on",),
        "windshield_defrost": ("climate_details.windshield_defrost",),
        "battery_preheat_on": ("climate_details.battery_preheat",),
        "battery_preheat_off": ("climate_details.battery_preheat",),
        "steering_wheel_heat_on": ("seat_comfort.steering_wheel_heating",),
        "steering_wheel_heat_off": ("seat_comfort.steering_wheel_heating",),
        "rearview_mirror_heat_on": ("mirrors.left_heating", "mirrors.right_heating"),
        "rearview_mirror_heat_off": ("mirrors.left_heating", "mirrors.right_heating"),
        "trunk_open": ("doors.trunk",),
        "trunk_close": ("doors.trunk",),
        "sunshade_open": ("sunshade_open",),
        "sunshade_close": ("sunshade_open",),
        "windows_open": ("windows",),
        "windows_close": ("windows",),
        "sentry_on": ("security.sentry_mode", "sentry_mode"),
        "sentry_off": ("security.sentry_mode", "sentry_mode"),
        "start_charging": ("charging_status", "charging_power_kw"),
        "stop_charging": ("charging_status", "charging_power_kw"),
        "set_charge_limit": ("charge_limit_percent",),
    }

    def _command_confirmation_gaps(self, command_key: str, telemetry: dict[str, Any]) -> list[str]:
        """Classifica cada campo exigido pelo matcher: ausente, nulo ou vazio.

        Só nomes de campo e classificação saem daqui. Nenhum valor de
        telemetria é registrado — a mesma leitura carrega localização e
        identificadores do veículo.
        """
        command = str(command_key or "").strip().lower()
        gaps: list[str] = []
        for path in self.COMMAND_CONFIRMATION_FIELDS.get(command, ()):  # desconhecido -> sem campo exigido
            node: Any = telemetry
            missing = False
            for part in path.split("."):
                if not isinstance(node, dict) or part not in node:
                    missing = True
                    break
                node = node[part]
            if missing:
                gaps.append(path + "=ausente")
            elif node is None:
                gaps.append(path + "=nulo")
            elif isinstance(node, dict) and not node:
                gaps.append(path + "=vazio")
        return gaps

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
        if command in {"steering_wheel_heat_on", "steering_wheel_heat_off"}:
            seat = telemetry.get("seat_comfort") if isinstance(telemetry.get("seat_comfort"), dict) else {}
            state = self._command_bool(seat.get("steering_wheel_heating"))
            expected = command == "steering_wheel_heat_on"
            return (state is expected, state is not None)
        if command in {"rearview_mirror_heat_on", "rearview_mirror_heat_off"}:
            mirrors = telemetry.get("mirrors") if isinstance(telemetry.get("mirrors"), dict) else {}
            known = [self._command_bool(mirrors.get(key)) for key in ("left_heating", "right_heating") if key in mirrors]
            known = [value for value in known if value is not None]
            if not known:
                return False, False
            active = any(known)
            expected = command == "rearview_mirror_heat_on"
            return (active is expected, True)
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
        if command in {"sentry_on", "sentry_off"}:
            security = telemetry.get("security") if isinstance(telemetry.get("security"), dict) else {}
            state = self._command_bool(security.get("sentry_mode", telemetry.get("sentry_mode")))
            expected = command == "sentry_on"
            return (state is expected, state is not None)
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

    def _queue_event(
        self,
        subscription: sqlite3.Row,
        vehicle: dict[str, Any],
        source_at: str,
        state: str,
        interactive: bool = False,
        force_delivery: bool = False,
    ) -> dict[str, Any]:
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
                if (
                    unchanged
                    and not force_delivery
                    and now_epoch - last_queued_at < self._heartbeat_interval(state, interactive=interactive)
                ):
                    db.execute(
                        "UPDATE vehicle_state_cache SET visual_fingerprint=?, last_source_at=?, skipped_unchanged=skipped_unchanged+1, updated_at=? WHERE subscription_id=? AND remote_id=?",
                        (visual_fingerprint or None, source_at, now_iso, subscription_id, remote_id),
                    )
                    db.execute("COMMIT")
                    return {"queued": False, "reason": "unchanged", "sequence": int(cached["sequence"] or 0)}

                sequence = (int(cached["sequence"] or 0) if cached is not None else 0) + 1
                state_changed = not unchanged
                event_kind = "confirmation" if force_delivery else ("change" if state_changed else "heartbeat")
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

        def sign_headers() -> dict[str, str]:
            """Assina o mesmo corpo com timestamp e nonce novos.

            1.12.52 — o site trata o nonce como uso único (`gateway_telemetry_nonces`).
            Repetir a entrega com o cabeçalho anterior seria recusado como
            repetição, então cada tentativa recebe sua própria assinatura.
            """
            timestamp = str(int(time.time()))
            nonce = os.urandom(16).hex()
            canonical = f"POST\n{path}\n{timestamp}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()
            signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
            return {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"LeapHubGateway/{ENGINE_VERSION}",
                "X-LeapHub-Timestamp": timestamp,
                "X-LeapHub-Nonce": nonce,
                "X-LeapHub-Environment": environment,
                "X-LeapHub-Signature": signature,
            }

        headers = sign_headers()
        try:
            # 1.12.50 — o PHP da hospedagem compartilhada costuma ser encerrado
            # por max_execution_time antes do timeout. Desistir primeiro devolve
            # o lote à fila com backoff curto em vez de segurar a thread de
            # entrega num socket que já não tem ninguém do outro lado.
            payload = self._post_delivery(url, headers, body, sign=sign_headers)
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
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            http.client.HTTPException,
            OSError,
            TimeoutError,
            ValueError,
            RuntimeError,
            json.JSONDecodeError,
        ) as exc:
            self._close_delivery_connection()
            self._delivery_failed(valid_rows, connector.clean_message(str(exc)))

    def _post_delivery(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes,
        sign: Callable[[], dict[str, str]] | None = None,
    ) -> Any:
        """POST assinado ao site reaproveitando a conexão TLS entre lotes.

        1.12.51 — cada lote abria uma conexão nova. Com o lote menor recomendado
        para hospedagem compartilhada isso multiplicou os handshakes TLS saindo
        de uma conexão residencial, e o handshake passou a custar mais que a
        própria entrega. A conexão é usada apenas pela thread de entrega e é
        descartada em qualquer erro de transporte, então nenhuma resposta pode
        ser lida fora de ordem.

        1.12.52 — faltava a outra metade do keep-alive. `http.client` não
        verifica se o socket do pool continua aberto: ele escreve e só descobre
        no `getresponse()`. Como a hospegadem fecha a conexão ociosa em poucos
        segundos e os lotes saem a cada 20-120s, praticamente toda entrega
        reaproveitada falhava com "Remote end closed connection without
        response" — sem o PHP sequer rodar — e o lote voltava para o backoff.
        Agora a conexão ociosa além da janela é descartada antes do envio, e uma
        falha de transporte sobre conexão reaproveitada ganha uma tentativa
        imediata em conexão nova, com assinatura nova.
        """
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        if not host:
            raise RuntimeError("Destino de entrega sem host válido.")
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        key = f"{parsed.scheme}://{host}:{parsed.port or ''}"
        # Sem `sign` não há como renovar o nonce, e o site recusaria a repetição
        # como requisição repetida. Nesse caso vale a tentativa única de antes.
        attempts = 2 if sign is not None else 1

        with self._delivery_guard:
            for attempt in range(attempts):
                reused = self._prepare_delivery_connection(key, parsed)
                connection = self._delivery_connection
                if connection is None:
                    raise RuntimeError("Conexão de entrega indisponível.")
                request_headers = dict(headers if attempt == 0 else sign())
                request_headers["Content-Length"] = str(len(body))
                request_headers.setdefault("Connection", "keep-alive")
                try:
                    connection.request("POST", target, body=body, headers=request_headers)
                    response = connection.getresponse()
                    raw = response.read(2 * 1024 * 1024)
                    status = int(response.status)
                    if response.will_close:
                        self._close_delivery_connection()
                    else:
                        self._delivery_connection_idle_since = time.monotonic()
                        self._remember_delivery_idle_window(response.getheader("Keep-Alive", ""))
                    break
                except Exception:
                    # Um socket meio-fechado nunca volta ao pool: a próxima
                    # entrega leria a resposta do lote anterior.
                    self._close_delivery_connection()
                    # Só a primeira tentativa sobre conexão reaproveitada pode
                    # repetir. Ali o servidor comprovadamente não respondeu, a
                    # ingestão é idempotente pelo event_id e a alternativa era
                    # esperar o backoff inteiro por um socket morto.
                    if reused and attempt + 1 < attempts:
                        LOG.debug("Conexão de entrega reaproveitada estava fechada; repetindo em conexão nova.")
                        continue
                    raise

        if status < 200 or status >= 300:
            raise RuntimeError(f"O site respondeu HTTP {status} à entrega de telemetria.")
        return json.loads(raw.decode("utf-8"))

    def _prepare_delivery_connection(self, key: str, parsed: urllib.parse.ParseResult) -> bool:
        """Devolve True quando a conexão do pool pôde ser reaproveitada."""
        connection = self._delivery_connection
        if connection is not None and self._delivery_connection_key != key:
            self._close_delivery_connection()
            connection = None
        if connection is not None and time.monotonic() - self._delivery_connection_idle_since >= self._delivery_idle_max:
            # Passou da janela de keep-alive anunciada/presumida do servidor. O
            # socket provavelmente já foi fechado do outro lado e escrever nele
            # custaria o lote inteiro.
            self._close_delivery_connection()
            connection = None
        if connection is not None:
            return True
        if parsed.scheme == "https":
            connection = http.client.HTTPSConnection(parsed.hostname or "", parsed.port, timeout=25)
        elif parsed.scheme == "http":
            connection = http.client.HTTPConnection(parsed.hostname or "", parsed.port, timeout=25)
        else:
            raise RuntimeError("Esquema de entrega não suportado.")
        self._delivery_connection = connection
        self._delivery_connection_key = key
        self._delivery_connection_idle_since = time.monotonic()
        return False

    def _remember_delivery_idle_window(self, keep_alive_header: str) -> None:
        """Usa o `Keep-Alive: timeout=N` do servidor quando ele informa um.

        Sem o cabeçalho vale o padrão conservador. A margem de um segundo cobre
        a latência da própria requisição seguinte.
        """
        for part in str(keep_alive_header or "").split(","):
            name, _, value = part.strip().partition("=")
            if name.strip().lower() != "timeout":
                continue
            try:
                advertised = float(value.strip())
            except ValueError:
                return
            self._delivery_idle_max = max(
                DELIVERY_IDLE_MIN_SECONDS,
                min(DELIVERY_IDLE_MAX_SECONDS, advertised - 1.0),
            )
            return

    def _close_delivery_connection(self) -> None:
        with self._delivery_guard:
            connection, self._delivery_connection = self._delivery_connection, None
            self._delivery_connection_key = ""
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass

    def _delivery_failed(self, rows: list[sqlite3.Row], message: str) -> None:
        now = time.time()
        updates = []
        for row in rows:
            attempts = int(row["attempts"] or 0) + 1
            # 1.12.50 — o teto anterior de 1800s deixava a telemetria de um
            # usuário muda por meia hora depois de duas lentidões da hospedagem.
            # A fila é persistente e o event_id é idempotente; repetir em até 2min
            # não duplica nada e não custa chamada à nuvem Leapmotor.
            delay = min(120, max(10, 5 * (2 ** min(attempts, 5)))) + random.uniform(0, 5)
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

    def _expire_idle_sessions(self, now_epoch: float) -> None:
        """Descarta sessões por inatividade real, não pelo fim da janela de coleta.

        Roda a cada ciclo: é uma varredura em memória, sem disco, e é ela que
        devolve o cliente Leapmotor depois da inatividade. Nunca deve ficar
        atrás do throttle da retenção da fila.
        """
        with self.session_lock:
            stale_sessions = [
                sid for sid, session in self.sessions.items()
                if now_epoch - float(session.get("last_used_at") or 0) >= self.session_idle_seconds
            ]
        for subscription_id in stale_sessions:
            self._close_session(subscription_id)


    def _maintenance(self) -> None:
        now_epoch = time.time()
        # A expiração de sessão é barata e precisa continuar acontecendo em todo
        # ciclo. Só a retenção da fila, que toca o disco, entra no throttle.
        self._expire_idle_sessions(now_epoch)
        if now_epoch - self._maintenance_last_at < 60.0:
            return
        self._maintenance_last_at = now_epoch
        # Executada de forma barata; o SQLite ignora as remoções quando não há registros antigos.
        cutoff = time.time() - self.retention_days * 86400
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat().replace("+00:00", "Z")
        expired_windows: list[str] = []
        with self.lock, self._db() as db:
            expired_windows = [str(row[0]) for row in db.execute(
                "SELECT subscription_id FROM subscriptions WHERE enabled=1 AND active_until<=? "
                "AND status NOT IN ('idle','background','disabled','auth_required','cooldown')",
                (now_epoch,),
            ).fetchall()]
            if expired_windows:
                placeholders = ",".join("?" for _ in expired_windows)
                expired_status = "background" if self.background_enabled else "idle"
                db.execute(
                    f"UPDATE subscriptions SET status=?, interactive_until=0, command_until=0, last_error=NULL, updated_at=? WHERE subscription_id IN ({placeholders})",
                    (expired_status, utc_iso(), *expired_windows),
                )
            db.execute("DELETE FROM events WHERE status='delivered' AND delivered_at<?", (cutoff_iso,))
            total = int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            if total > self.queue_max:
                excess = total - self.queue_max
                db.execute(
                    "DELETE FROM events WHERE event_id IN (SELECT event_id FROM events WHERE status='delivered' ORDER BY delivered_at ASC LIMIT ?)",
                    (excess,),
                )
