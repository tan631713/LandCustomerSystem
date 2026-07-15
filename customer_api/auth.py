"""Short-lived server-side sessions and login throttling."""

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass

from customer_api.types import AuthenticatedUser


@dataclass(frozen=True)
class ApiSession:
    user: AuthenticatedUser
    expires_at: float


class SessionStore:
    def __init__(self, ttl_seconds=8 * 60 * 60, clock=None):
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.clock = clock or time.time
        self._sessions = {}
        self._lock = threading.Lock()

    @staticmethod
    def _digest(token):
        return hashlib.sha256(str(token).encode("utf-8")).hexdigest()

    def create(self, user):
        token = secrets.token_urlsafe(48)
        expires_at = self.clock() + self.ttl_seconds
        with self._lock:
            self._purge_locked()
            self._sessions[self._digest(token)] = ApiSession(user, expires_at)
        return token, expires_at

    def get(self, token):
        if not token:
            return None
        with self._lock:
            self._purge_locked()
            return self._sessions.get(self._digest(token))

    def revoke(self, token):
        with self._lock:
            return self._sessions.pop(self._digest(token), None) is not None

    def _purge_locked(self):
        now = self.clock()
        expired = [key for key, session in self._sessions.items() if session.expires_at <= now]
        for key in expired:
            self._sessions.pop(key, None)


class LoginThrottle:
    def __init__(self, max_failures=5, lock_seconds=5 * 60, clock=None):
        self.max_failures = max(1, int(max_failures))
        self.lock_seconds = max(1, int(lock_seconds))
        self.clock = clock or time.monotonic
        self._failures = {}
        self._lock = threading.Lock()

    def retry_after(self, key):
        with self._lock:
            _failures, locked_until = self._failures.get(str(key), (0, 0.0))
            remaining = locked_until - self.clock()
            if remaining <= 0:
                if locked_until:
                    self._failures.pop(str(key), None)
                return 0
            return max(1, int(remaining + 0.999))

    def failure(self, key):
        key = str(key)
        with self._lock:
            failures, locked_until = self._failures.get(key, (0, 0.0))
            if locked_until > self.clock():
                return
            failures += 1
            if failures >= self.max_failures:
                self._failures[key] = (failures, self.clock() + self.lock_seconds)
            else:
                self._failures[key] = (failures, 0.0)

    def success(self, key):
        with self._lock:
            self._failures.pop(str(key), None)
