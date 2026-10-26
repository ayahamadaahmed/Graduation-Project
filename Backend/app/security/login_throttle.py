"""Failed staff-login throttling, per normalized email.

After ``max_failures`` wrong-password attempts for one email within
``window_seconds``, further attempts for that email get 429 until the oldest
failure leaves the window. A successful login clears the email's failures.

Process-local and in memory (no new infrastructure): it holds per backend
worker and resets on restart. The backend already runs as one worker (AI chat
sessions are in memory too); with several workers each has its own counts.
Keyed by email, not client IP, because behind a proxy every client shares
one IP. Unknown emails are counted the same way, so the throttle does not
reveal which accounts exist.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable


class LoginThrottle:
    def __init__(
        self,
        *,
        max_failures: int,
        window_seconds: float,
        max_tracked: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_failures < 1 or window_seconds <= 0 or max_tracked < 1:
            raise ValueError("Invalid login throttle settings.")

        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.max_tracked = max_tracked
        self._clock = clock
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key_for(email: str) -> str:
        return email.strip().lower()

    def _prune(self, key: str, now: float) -> deque[float] | None:
        failures = self._failures.get(key)
        if failures is None:
            return None

        while failures and failures[0] <= now - self.window_seconds:
            failures.popleft()

        if not failures:
            del self._failures[key]
            return None

        return failures

    def retry_after(self, email: str) -> int | None:
        """Seconds until the next attempt is allowed, or None if allowed now."""
        key = self.key_for(email)
        now = self._clock()

        with self._lock:
            failures = self._prune(key, now)

            if failures is None or len(failures) < self.max_failures:
                return None

            # Allowed again once enough failures have left the window.
            unlock_at = failures[len(failures) - self.max_failures] + self.window_seconds

            return max(1, int(unlock_at - now + 0.999))

    def register_failure(self, email: str) -> None:
        key = self.key_for(email)
        now = self._clock()

        with self._lock:
            failures = self._prune(key, now)

            if failures is None:
                failures = deque(maxlen=self.max_failures)
                self._failures[key] = failures

            failures.append(now)
            self._failures.move_to_end(key)

            # Bounded memory: forget the least recently failed emails first.
            while len(self._failures) > self.max_tracked:
                self._failures.popitem(last=False)

    def reset(self, email: str) -> None:
        with self._lock:
            self._failures.pop(self.key_for(email), None)


_throttle: LoginThrottle | None = None
_throttle_lock = threading.Lock()


def get_login_throttle() -> LoginThrottle:
    global _throttle

    with _throttle_lock:
        if _throttle is None:
            from app.core.config import get_settings

            settings = get_settings()
            _throttle = LoginThrottle(
                max_failures=settings.staff_login_max_failures,
                window_seconds=settings.staff_login_window_minutes * 60,
            )

        return _throttle
