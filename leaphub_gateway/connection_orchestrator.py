from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import defaultdict, deque
from typing import Any


class ConnectionOrchestrator:
    """Coordena saúde da nuvem, redução de carga e métricas sem PII.

    O circuit breaker nunca bloqueia comandos manuais. Ele só reduz telemetria
    automática e trabalho secundário quando várias contas indicam instabilidade
    no mesmo ambiente.
    """

    FAILURE_WINDOW_SECONDS = 180
    DEGRADED_SECONDS = 120
    DEGRADED_PROBE_SECONDS = 60
    MAX_EVENTS = 256

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._failures: dict[str, deque[tuple[float, str]]] = defaultdict(lambda: deque(maxlen=64))
        self._degraded_until: dict[str, float] = defaultdict(float)
        self._last_probe_at: dict[str, float] = defaultdict(float)
        self._last_error_at: dict[str, float] = defaultdict(float)
        self._last_success_at: dict[str, float] = defaultdict(float)
        self._consecutive_successes: dict[str, int] = defaultdict(int)
        self._deduplicated: dict[str, int] = defaultdict(int)
        self._latencies: dict[str, deque[dict[str, float]]] = defaultdict(lambda: deque(maxlen=self.MAX_EVENTS))

    @staticmethod
    def _environment(value: str) -> str:
        value = str(value or "").strip().lower()
        return value if value in {"staging", "production"} else "unknown"

    @staticmethod
    def _account_fingerprint(value: Any) -> str:
        raw = str(value or "anonymous").encode("utf-8", "replace")
        return hashlib.sha256(raw).hexdigest()[:16]

    def _prune_locked(self, environment: str, now: float) -> None:
        failures = self._failures[environment]
        cutoff = now - self.FAILURE_WINDOW_SECONDS
        while failures and failures[0][0] < cutoff:
            failures.popleft()

    def record_cloud_failure(self, environment: str, account_key: Any = None) -> None:
        env = self._environment(environment)
        now = time.time()
        fingerprint = self._account_fingerprint(account_key)
        with self._lock:
            self._prune_locked(env, now)
            self._failures[env].append((now, fingerprint))
            failures = self._failures[env]
            affected = len({item[1] for item in failures})
            if len(failures) >= 5 or (len(failures) >= 3 and affected >= 2):
                self._degraded_until[env] = max(self._degraded_until[env], now + self.DEGRADED_SECONDS)
            self._last_error_at[env] = now
            self._consecutive_successes[env] = 0

    def record_cloud_success(self, environment: str) -> None:
        env = self._environment(environment)
        now = time.time()
        with self._lock:
            self._prune_locked(env, now)
            self._last_success_at[env] = now
            self._consecutive_successes[env] += 1
            # Duas respostas recentes bem-sucedidas encerram cedo o modo
            # degradado. Falhas antigas continuam na janela apenas para
            # observabilidade; não prendem o serviço em degradação.
            if self._consecutive_successes[env] >= 2:
                self._degraded_until[env] = 0.0

    def is_degraded(self, environment: str) -> bool:
        env = self._environment(environment)
        now = time.time()
        with self._lock:
            self._prune_locked(env, now)
            return self._degraded_until[env] > now

    def claim_background_probe(self, environment: str) -> bool:
        """Permite uma sonda automática moderada por ambiente durante degradação."""
        env = self._environment(environment)
        now = time.time()
        with self._lock:
            self._prune_locked(env, now)
            if self._degraded_until[env] <= now:
                return True
            if now - self._last_probe_at[env] >= self.DEGRADED_PROBE_SECONDS:
                self._last_probe_at[env] = now
                return True
            return False

    def secondary_network_allowed(self, environment: str) -> bool:
        return not self.is_degraded(environment)

    def record_deduplicated(self, kind: str) -> None:
        key = str(kind or "unknown")[:80]
        with self._lock:
            self._deduplicated[key] += 1

    def record_command_latency(
        self,
        environment: str,
        *,
        account_wait_ms: float,
        connector_slot_ms: float,
        remote_execute_ms: float,
        total_ms: float,
    ) -> None:
        env = self._environment(environment)
        sample = {
            "account_wait_ms": max(0.0, float(account_wait_ms)),
            "connector_slot_ms": max(0.0, float(connector_slot_ms)),
            "remote_execute_ms": max(0.0, float(remote_execute_ms)),
            "total_ms": max(0.0, float(total_ms)),
        }
        with self._lock:
            self._latencies[env].append(sample)

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> int | None:
        if not values:
            return None
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, math.ceil((percentile / 100.0) * len(ordered)) - 1))
        return int(round(ordered[index]))

    @staticmethod
    def _age(value: float, now: float) -> int | None:
        return max(0, int(now - value)) if value > 0 else None

    def snapshot(self, environment: str) -> dict[str, Any]:
        env = self._environment(environment)
        now = time.time()
        with self._lock:
            self._prune_locked(env, now)
            failures = list(self._failures[env])
            affected = len({item[1] for item in failures})
            degraded_for = max(0, int(self._degraded_until[env] - now))
            samples = list(self._latencies[env])
            totals = [item["total_ms"] for item in samples]
            account_waits = [item["account_wait_ms"] for item in samples]
            slot_waits = [item["connector_slot_ms"] for item in samples]
            remote_times = [item["remote_execute_ms"] for item in samples]
            return {
                "state": "degraded" if degraded_for > 0 else "healthy",
                "transient_failures_3m": len(failures),
                "affected_accounts_3m": affected,
                "automatic_reduction_active": degraded_for > 0,
                "degraded_for_seconds": degraded_for,
                "next_background_probe_in_seconds": max(
                    0,
                    int(self.DEGRADED_PROBE_SECONDS - (now - self._last_probe_at[env])),
                ) if degraded_for > 0 else 0,
                "last_error_seconds_ago": self._age(self._last_error_at[env], now),
                "last_success_seconds_ago": self._age(self._last_success_at[env], now),
                "command_latency": {
                    "samples": len(samples),
                    "total_p50_ms": self._percentile(totals, 50),
                    "total_p95_ms": self._percentile(totals, 95),
                    "account_wait_p95_ms": self._percentile(account_waits, 95),
                    "connector_slot_p95_ms": self._percentile(slot_waits, 95),
                    "remote_execute_p95_ms": self._percentile(remote_times, 95),
                },
                "deduplicated": dict(self._deduplicated),
            }


ORCHESTRATOR = ConnectionOrchestrator()
