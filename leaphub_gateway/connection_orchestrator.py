from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import defaultdict, deque
from typing import Any


class ConnectionOrchestrator:
    """Coordena saúde da nuvem, redução de carga e métricas sem PII.

    1.12.47 separa falha local de falha global:
    - uma única conta pode entrar em backpressure próprio;
    - degradação do ambiente exige evidência de contas distintas;
    - comandos manuais nunca são bloqueados por circuit breaker;
    - somente telemetria automática e trabalho secundário são reduzidos.
    """

    FAILURE_WINDOW_SECONDS = 180
    DEGRADED_SECONDS = 120
    DEGRADED_PROBE_SECONDS = 60
    RECOVERY_QUIET_SECONDS = 30
    RECOVERY_DISTINCT_ACCOUNTS = 2
    GLOBAL_MIN_FAILURES = 3
    GLOBAL_MIN_DISTINCT_ACCOUNTS = 2

    ACCOUNT_FAILURE_WINDOW_SECONDS = 180
    ACCOUNT_FAILURE_THRESHOLD = 3
    ACCOUNT_DEGRADED_SECONDS = 180
    ACCOUNT_PROBE_SECONDS = 60
    ACCOUNT_RECOVERY_QUIET_SECONDS = 30
    MAX_EVENTS = 256

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._failures: dict[str, deque[tuple[float, str]]] = defaultdict(lambda: deque(maxlen=64))
        self._degraded_until: dict[str, float] = defaultdict(float)
        self._last_probe_at: dict[str, float] = defaultdict(float)
        self._last_error_at: dict[str, float] = defaultdict(float)
        self._last_success_at: dict[str, float] = defaultdict(float)
        self._consecutive_successes: dict[str, int] = defaultdict(int)
        self._recovery_accounts: dict[str, set[str]] = defaultdict(set)

        # Circuit breaker isolado por conta. As chaves são fingerprints curtas,
        # nunca e-mail, VIN, account_id ou credencial bruta.
        self._account_failures: dict[str, dict[str, deque[float]]] = defaultdict(dict)
        self._account_degraded_until: dict[str, dict[str, float]] = defaultdict(dict)
        self._account_last_probe_at: dict[str, dict[str, float]] = defaultdict(dict)
        self._account_last_error_at: dict[str, dict[str, float]] = defaultdict(dict)
        self._account_last_success_at: dict[str, dict[str, float]] = defaultdict(dict)

        self._deduplicated: dict[str, int] = defaultdict(int)
        self._latencies: dict[str, deque[dict[str, float]]] = defaultdict(lambda: deque(maxlen=self.MAX_EVENTS))
        self._telemetry_cycles: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=self.MAX_EVENTS))

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

        account_cutoff = now - self.ACCOUNT_FAILURE_WINDOW_SECONDS
        account_failures = self._account_failures[environment]
        for fingerprint in list(account_failures):
            events = account_failures[fingerprint]
            while events and events[0] < account_cutoff:
                events.popleft()
            if not events:
                account_failures.pop(fingerprint, None)

        degraded = self._account_degraded_until[environment]
        for fingerprint, until in list(degraded.items()):
            if until <= now:
                degraded.pop(fingerprint, None)
                self._account_last_probe_at[environment].pop(fingerprint, None)

    def _record_account_failure_locked(self, env: str, fingerprint: str, now: float) -> None:
        events = self._account_failures[env].get(fingerprint)
        if events is None:
            events = deque(maxlen=32)
            self._account_failures[env][fingerprint] = events
        events.append(now)
        self._account_last_error_at[env][fingerprint] = now
        if len(events) >= self.ACCOUNT_FAILURE_THRESHOLD:
            self._account_degraded_until[env][fingerprint] = max(
                self._account_degraded_until[env].get(fingerprint, 0.0),
                now + self.ACCOUNT_DEGRADED_SECONDS,
            )

    def record_cloud_failure(self, environment: str, account_key: Any = None) -> None:
        env = self._environment(environment)
        now = time.time()
        fingerprint = self._account_fingerprint(account_key)
        with self._lock:
            self._prune_locked(env, now)
            self._failures[env].append((now, fingerprint))
            self._record_account_failure_locked(env, fingerprint, now)

            failures = self._failures[env]
            affected = len({item[1] for item in failures})
            # 1.12.47 — uma conta barulhenta NÃO degrada todo o ambiente.
            # O breaker global só entra quando contas distintas apresentam
            # falhas dentro da mesma janela, indicando problema compartilhado.
            if len(failures) >= self.GLOBAL_MIN_FAILURES and affected >= self.GLOBAL_MIN_DISTINCT_ACCOUNTS:
                self._degraded_until[env] = max(self._degraded_until[env], now + self.DEGRADED_SECONDS)
            self._last_error_at[env] = now
            self._consecutive_successes[env] = 0
            self._recovery_accounts[env].clear()

    def record_cloud_success(self, environment: str, account_key: Any = None) -> None:
        env = self._environment(environment)
        now = time.time()
        fingerprint = self._account_fingerprint(account_key)
        with self._lock:
            self._prune_locked(env, now)
            self._last_success_at[env] = now
            self._consecutive_successes[env] += 1
            self._account_last_success_at[env][fingerprint] = now
            if account_key not in (None, ""):
                self._recovery_accounts[env].add(fingerprint)

            # Backpressure local pode terminar cedo após uma janela quieta e
            # uma leitura bem-sucedida da própria conta. Não depende de outras.
            local_error_at = self._account_last_error_at[env].get(fingerprint, 0.0)
            if (
                self._account_degraded_until[env].get(fingerprint, 0.0) > now
                and now - local_error_at >= self.ACCOUNT_RECOVERY_QUIET_SECONDS
            ):
                self._account_degraded_until[env].pop(fingerprint, None)
                self._account_last_probe_at[env].pop(fingerprint, None)
                self._account_failures[env].pop(fingerprint, None)

            # Um sucesso isolado não prova que uma indisponibilidade global
            # terminou. Recuperação antecipada exige contas distintas.
            quiet_for = now - self._last_error_at[env]
            if (
                self._degraded_until[env] > now
                and quiet_for >= self.RECOVERY_QUIET_SECONDS
                and len(self._recovery_accounts[env]) >= self.RECOVERY_DISTINCT_ACCOUNTS
            ):
                self._degraded_until[env] = 0.0

    def is_degraded(self, environment: str) -> bool:
        """Estado compartilhado do ambiente; nunca é ativado por uma conta só."""
        env = self._environment(environment)
        now = time.time()
        with self._lock:
            self._prune_locked(env, now)
            return self._degraded_until[env] > now

    def is_account_degraded(self, environment: str, account_key: Any) -> bool:
        env = self._environment(environment)
        now = time.time()
        fingerprint = self._account_fingerprint(account_key)
        with self._lock:
            self._prune_locked(env, now)
            return self._account_degraded_until[env].get(fingerprint, 0.0) > now

    def claim_background_probe(self, environment: str) -> bool:
        """Permite uma sonda automática moderada por ambiente durante degradação global."""
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

    def claim_account_background_probe(self, environment: str, account_key: Any) -> bool:
        """Permite uma sonda da conta afetada sem reduzir outras contas."""
        env = self._environment(environment)
        now = time.time()
        fingerprint = self._account_fingerprint(account_key)
        with self._lock:
            self._prune_locked(env, now)
            if self._account_degraded_until[env].get(fingerprint, 0.0) <= now:
                return True
            last_probe = self._account_last_probe_at[env].get(fingerprint, 0.0)
            if now - last_probe >= self.ACCOUNT_PROBE_SECONDS:
                self._account_last_probe_at[env][fingerprint] = now
                return True
            return False

    def secondary_network_allowed(self, environment: str, account_key: Any = None) -> bool:
        if self.is_degraded(environment):
            return False
        if account_key not in (None, "") and self.is_account_degraded(environment, account_key):
            return False
        return True

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
        session_prepare_ms: float = 0.0,
        dispatch_ms: float = 0.0,
        verification_ms: float = 0.0,
    ) -> None:
        env = self._environment(environment)
        sample = {
            "account_wait_ms": max(0.0, float(account_wait_ms)),
            "connector_slot_ms": max(0.0, float(connector_slot_ms)),
            "remote_execute_ms": max(0.0, float(remote_execute_ms)),
            "total_ms": max(0.0, float(total_ms)),
            "session_prepare_ms": max(0.0, float(session_prepare_ms)),
            "dispatch_ms": max(0.0, float(dispatch_ms)),
            "verification_ms": max(0.0, float(verification_ms)),
        }
        with self._lock:
            self._latencies[env].append(sample)

    def record_telemetry_cycle(
        self,
        environment: str,
        *,
        profile: str,
        duration_ms: float,
        outcome: str = "success",
        account_wait_ms: float = 0.0,
        connector_slot_ms: float = 0.0,
    ) -> None:
        env = self._environment(environment)
        item = {
            "profile": str(profile or "unknown")[:24],
            "duration_ms": max(0.0, float(duration_ms)),
            "outcome": str(outcome or "unknown")[:24],
            "account_wait_ms": max(0.0, float(account_wait_ms)),
            "connector_slot_ms": max(0.0, float(connector_slot_ms)),
        }
        with self._lock:
            self._telemetry_cycles[env].append(item)

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
            account_degraded = {
                fingerprint: until
                for fingerprint, until in self._account_degraded_until[env].items()
                if until > now
            }
            max_account_backpressure = max(
                [max(0, int(until - now)) for until in account_degraded.values()] or [0]
            )
            samples = list(self._latencies[env])
            totals = [item["total_ms"] for item in samples]
            account_waits = [item["account_wait_ms"] for item in samples]
            slot_waits = [item["connector_slot_ms"] for item in samples]
            remote_times = [item["remote_execute_ms"] for item in samples]
            session_prepare_times = [item.get("session_prepare_ms", 0.0) for item in samples]
            dispatch_times = [item.get("dispatch_ms", 0.0) for item in samples]
            verification_times = [item.get("verification_ms", 0.0) for item in samples]
            phase_p95 = {
                "account_wait": self._percentile(account_waits, 95),
                "connector_slot": self._percentile(slot_waits, 95),
                "session_prepare": self._percentile(session_prepare_times, 95),
                "dispatch": self._percentile(dispatch_times, 95),
                "verification": self._percentile(verification_times, 95),
            }
            measurable = {key: int(value or 0) for key, value in phase_p95.items()}
            primary_bottleneck = max(measurable, key=measurable.get) if any(measurable.values()) else None
            telemetry_cycles = list(self._telemetry_cycles[env])
            telemetry_durations = [float(item.get("duration_ms") or 0.0) for item in telemetry_cycles]
            telemetry_fast = [float(item.get("duration_ms") or 0.0) for item in telemetry_cycles if item.get("profile") in {"fast", "interactive", "confirmation"}]
            telemetry_slow = [float(item.get("duration_ms") or 0.0) for item in telemetry_cycles if item.get("profile") == "slow"]
            telemetry_account_waits = [float(item.get("account_wait_ms") or 0.0) for item in telemetry_cycles]
            telemetry_slot_waits = [float(item.get("connector_slot_ms") or 0.0) for item in telemetry_cycles]
            manual_yields = sum(1 for item in telemetry_cycles if item.get("outcome") == "manual_yield")
            account_busy_yields = sum(1 for item in telemetry_cycles if item.get("outcome") == "account_busy_yield")
            slot_timeouts = sum(1 for item in telemetry_cycles if item.get("outcome") == "slot_timeout")
            failures_total = sum(1 for item in telemetry_cycles if item.get("outcome") == "failure")
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
                "cloud_isolation": {
                    "per_account_breaker": True,
                    "single_account_can_degrade_environment": False,
                    "global_min_failures": self.GLOBAL_MIN_FAILURES,
                    "global_distinct_accounts_required": self.GLOBAL_MIN_DISTINCT_ACCOUNTS,
                    "account_failure_threshold": self.ACCOUNT_FAILURE_THRESHOLD,
                    "account_backpressure_seconds": self.ACCOUNT_DEGRADED_SECONDS,
                    "degraded_accounts": len(account_degraded),
                    "max_account_backpressure_seconds": max_account_backpressure,
                },
                "recovery": {
                    "quiet_seconds_required": self.RECOVERY_QUIET_SECONDS,
                    "distinct_accounts_required": self.RECOVERY_DISTINCT_ACCOUNTS,
                    "distinct_accounts_confirmed": len(self._recovery_accounts[env]),
                },
                "command_latency": {
                    "samples": len(samples),
                    "total_p50_ms": self._percentile(totals, 50),
                    "total_p95_ms": self._percentile(totals, 95),
                    "account_wait_p95_ms": self._percentile(account_waits, 95),
                    "connector_slot_p95_ms": self._percentile(slot_waits, 95),
                    "remote_execute_p95_ms": self._percentile(remote_times, 95),
                    "session_prepare_p95_ms": phase_p95["session_prepare"],
                    "dispatch_p95_ms": phase_p95["dispatch"],
                    "verification_p95_ms": phase_p95["verification"],
                    "queue_account_p95_ms": phase_p95["account_wait"],
                    "queue_connector_p95_ms": phase_p95["connector_slot"],
                    "remote_dispatch_p95_ms": phase_p95["dispatch"],
                    "remote_result_p95_ms": None,
                    "remote_result_bundled_with_dispatch": True,
                    "post_state_verify_p95_ms": phase_p95["verification"],
                    "primary_bottleneck": primary_bottleneck,
                },
                "telemetry_latency": {
                    "samples": len(telemetry_cycles),
                    "total_p50_ms": self._percentile(telemetry_durations, 50),
                    "total_p95_ms": self._percentile(telemetry_durations, 95),
                    "fast_p95_ms": self._percentile(telemetry_fast, 95),
                    "slow_p95_ms": self._percentile(telemetry_slow, 95),
                    "account_wait_p95_ms": self._percentile(telemetry_account_waits, 95),
                    "connector_slot_p95_ms": self._percentile(telemetry_slot_waits, 95),
                    "manual_yields": manual_yields,
                    "account_busy_yields": account_busy_yields,
                    "slot_timeouts": slot_timeouts,
                    "lock_order": "account_then_connector",
                    "global_slot_held_while_waiting_account": False,
                    "failures": failures_total,
                },
                "deduplicated": dict(self._deduplicated),
            }


ORCHESTRATOR = ConnectionOrchestrator()
