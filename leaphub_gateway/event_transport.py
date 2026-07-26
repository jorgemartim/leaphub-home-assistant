from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from typing import Any, Callable


class EventTransportCoordinator:
    """Fundação event-driven com fallback REST.

    Não abre uma conexão MQTT por conta própria. O adaptador de nuvem só será
    ativado quando autenticação, tópicos e payloads forem homologados. Enquanto
    isso, a mesma interface já oferece deduplicação e wake-up seguro para um
    futuro consumidor de eventos legítimo.
    """

    DEDUPE_SECONDS = 30
    WAKE_COALESCE_SECONDS = 1.5
    MAX_HINTS = 512

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._wake_callback: Callable[[str, int, str, str], bool] | None = None
        self._recent: dict[str, float] = {}
        self._accepted = 0
        self._deduplicated = 0
        self._wakeups = 0
        self._coalesced_wakeups = 0
        self._last_wake_by_target: dict[str, float] = {}
        self._last_hint_at = 0.0
        self._sources: deque[str] = deque(maxlen=16)

    @staticmethod
    def _fingerprint(environment: str, account_id: int, vehicle_id: str, source: str, event_key: str) -> str:
        raw = f"{environment}|{int(account_id)}|{vehicle_id}|{source}|{event_key}".encode("utf-8", "replace")
        return hashlib.sha256(raw).hexdigest()

    def register_wake_callback(self, callback: Callable[[str, int, str, str], bool]) -> None:
        with self._lock:
            self._wake_callback = callback

    def ingest_hint(
        self,
        environment: str,
        account_id: int,
        vehicle_id: str = "",
        *,
        source: str = "event",
        event_key: str = "state_changed",
    ) -> dict[str, Any]:
        env = str(environment or "").strip().lower()
        src = str(source or "event").strip().lower()[:40]
        key = str(event_key or "state_changed").strip().lower()[:80]
        vehicle = str(vehicle_id or "").strip()[:190]
        now = time.time()
        fingerprint = self._fingerprint(env, int(account_id), vehicle, src, key)
        with self._lock:
            expired = [item for item, seen_at in self._recent.items() if seen_at < now - self.DEDUPE_SECONDS]
            for item in expired:
                self._recent.pop(item, None)
            if fingerprint in self._recent:
                self._deduplicated += 1
                return {"accepted": True, "deduplicated": True, "woken": False}
            if len(self._recent) >= self.MAX_HINTS:
                oldest = min(self._recent, key=self._recent.get)
                self._recent.pop(oldest, None)
            self._recent[fingerprint] = now
            self._accepted += 1
            self._last_hint_at = now
            if src not in self._sources:
                self._sources.append(src)
            callback = self._wake_callback
        woken = False
        coalesced = False
        wake_target = self._fingerprint(env, int(account_id), vehicle, "wake", "target")
        if callback is not None and int(account_id) > 0:
            with self._lock:
                last_wake = float(self._last_wake_by_target.get(wake_target) or 0.0)
                if last_wake > 0 and now - last_wake < self.WAKE_COALESCE_SECONDS:
                    coalesced = True
                    self._coalesced_wakeups += 1
                else:
                    self._last_wake_by_target[wake_target] = now
                    if len(self._last_wake_by_target) > self.MAX_HINTS:
                        cutoff = now - max(self.DEDUPE_SECONDS, self.WAKE_COALESCE_SECONDS * 4)
                        stale_targets = [item for item, seen_at in self._last_wake_by_target.items() if seen_at < cutoff]
                        for item in stale_targets[:256]:
                            self._last_wake_by_target.pop(item, None)
            if not coalesced:
                try:
                    woken = bool(callback(env, int(account_id), vehicle, src))
                except Exception:
                    woken = False
        if woken:
            with self._lock:
                self._wakeups += 1
        return {"accepted": True, "deduplicated": False, "woken": woken, "wake_coalesced": coalesced}

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            last_age = max(0, int(now - self._last_hint_at)) if self._last_hint_at > 0 else None
            return {
                "preferred_strategy": "events_then_rest",
                "active_telemetry_transport": "rest_polling",
                "command_transport": "rest_authenticated",
                "event_driven_ready": self._wake_callback is not None,
                "rest_fallback": True,
                "mqtt": {
                    "active": False,
                    "status": "awaiting_homologation",
                    "reason": "cloud_auth_topics_payload_not_homologated",
                },
                "event_hints": {
                    "accepted": self._accepted,
                    "deduplicated": self._deduplicated,
                    "wakeups": self._wakeups,
                    "coalesced_wakeups": self._coalesced_wakeups,
                    "wake_coalesce_seconds": self.WAKE_COALESCE_SECONDS,
                    "last_hint_seconds_ago": last_age,
                    "sources_seen": len(self._sources),
                },
            }


EVENT_TRANSPORT = EventTransportCoordinator()
