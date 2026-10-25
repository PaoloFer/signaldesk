"""Protezione brute-force sugli endpoint di autenticazione.

Contatore in memoria per chiave (IP + email) con finestra scorrevole e
lockout progressivo: ogni volta che i tentativi falliti nella finestra
superano la soglia, la chiave viene bloccata per una durata che raddoppia
a ogni sforamento consecutivo (fino a un massimo).

Il contatore vive nel processo applicativo: con più worker/repliche il
limite si applica per singolo processo. Per un'unica istanza (setup MVP
documentato) è sufficiente; per scaling orizzontale va spostato su Redis.
"""

from __future__ import annotations

import os
import threading
import time


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


class RateLimitExceeded(RuntimeError):
    def __init__(self, retry_after: int):
        super().__init__(f"Troppi tentativi: riprova tra {retry_after} secondi")
        self.retry_after = retry_after


class SlidingWindowRateLimiter:
    """Finestra scorrevole con lockout progressivo per chiave."""

    def __init__(
        self,
        max_attempts: int | None = None,
        window_seconds: int | None = None,
        lockout_seconds: int | None = None,
        max_lockout_seconds: int | None = None,
    ):
        self.max_attempts = max_attempts or _int_env("AUTH_RATE_LIMIT_ATTEMPTS", 5)
        self.window_seconds = window_seconds or _int_env("AUTH_RATE_LIMIT_WINDOW_SECONDS", 900)
        self.lockout_seconds = lockout_seconds or _int_env("AUTH_RATE_LIMIT_LOCKOUT_SECONDS", 300)
        self.max_lockout_seconds = max_lockout_seconds or _int_env(
            "AUTH_RATE_LIMIT_MAX_LOCKOUT_SECONDS", 3600
        )
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lockout_level: dict[str, int] = {}

    def _retry_after(self, key: str, now: float) -> int:
        locked_until = self._locked_until.get(key, 0.0)
        if locked_until > now:
            return max(1, round(locked_until - now))
        return 0

    def check(self, key: str) -> None:
        """Verifica che la chiave possa tentare. Solleva RateLimitExceeded."""
        now = time.monotonic()
        retry_after = self._retry_after(key, now)
        if retry_after:
            raise RateLimitExceeded(retry_after)

    def record_failure(self, key: str) -> None:
        """Registra un tentativo fallito; se oltre soglia, blocca la chiave."""
        now = time.monotonic()
        retry_after = self._retry_after(key, now)
        if retry_after:
            return
        failures = [
            stamp for stamp in self._failures.get(key, [])
            if now - stamp < self.window_seconds
        ]
        failures.append(now)
        if len(failures) >= self.max_attempts:
            level = self._lockout_level.get(key, 0) + 1
            self._lockout_level[key] = level
            duration = min(
                self.lockout_seconds * (2 ** (level - 1)), self.max_lockout_seconds
            )
            self._locked_until[key] = now + duration
            self._failures[key] = []
        else:
            self._failures[key] = failures

    def reset(self, key: str) -> None:
        """Azzera il contatore dopo un successo."""
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)
        self._lockout_level.pop(key, None)


# Istanza condivisa dagli endpoint di autenticazione.
auth_rate_limiter = SlidingWindowRateLimiter()


class FixedWindowRateLimiter:
    """Limite semplice per operazioni costose, thread-safe per singolo processo."""

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max(1, max_attempts)
        self.window_seconds = max(1, window_seconds)
        self._attempts: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check_and_record(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            attempts = [
                stamp for stamp in self._attempts.get(key, [])
                if now - stamp < self.window_seconds
            ]
            if len(attempts) >= self.max_attempts:
                retry_after = max(1, round(self.window_seconds - (now - attempts[0])))
                raise RateLimitExceeded(retry_after)
            attempts.append(now)
            self._attempts[key] = attempts
