import time
import threading
import random
from typing import Optional


class TokenBucket:
    """Simple token-bucket rate limiter (tokens per second).

    Methods:
    - consume(tokens=1): return True if tokens available immediately
    - wait(tokens=1, timeout=None): block until tokens are available or timeout
    """

    def __init__(self, rate: float, capacity: Optional[float] = None):
        self.rate = float(rate)
        self.capacity = capacity if capacity is not None else float(rate)
        self._tokens = float(self.capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        delta = now - self._last
        if delta <= 0:
            return
        self._tokens = min(self.capacity, self._tokens + delta * self.rate)
        self._last = now

    def consume(self, tokens: float = 1.0) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait(self, tokens: float = 1.0, timeout: Optional[float] = None) -> bool:
        start = time.monotonic()
        while True:
            if self.consume(tokens):
                return True
            if timeout is not None and (time.monotonic() - start) >= timeout:
                return False
            # sleep a little proportional to deficit
            with self._lock:
                deficit = max(0.0001, tokens - self._tokens)
            time.sleep(min(0.1, deficit / max(0.1, self.rate)))


class CircuitBreaker:
    """Basic circuit breaker.

    - failure_threshold: consecutive failures before opening
    - recovery_time: seconds to keep open before allowing attempts
    """

    def __init__(self, failure_threshold: int = 5, recovery_time: int = 60):
        self.failure_threshold = int(failure_threshold)
        self.recovery_time = int(recovery_time)
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._lock = threading.Lock()

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            # if recovery time elapsed, half-open: allow attempt and reset failures
            if (time.monotonic() - self._opened_at) >= self.recovery_time:
                self._failures = 0
                self._opened_at = None
                return False
            return True


def full_jitter_backoff(attempt: int, base: float = 0.5, cap: float = 10.0) -> float:
    """Return a backoff delay using exponential full jitter."""
    expo = min(cap, base * (2**attempt))
    return random.uniform(0, expo)
