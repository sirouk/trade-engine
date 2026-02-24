import time
from dataclasses import dataclass


@dataclass
class RetryState:
    failures: int = 0
    next_retry_at: float = 0.0
    last_error_signature: str = ""
    last_error_at: float = 0.0
    last_cooldown_log_at: float = 0.0
    suppressed_cooldown_count: int = 0


class OrderRetryGuard:
    """
    Per-symbol retry pacing to prevent tight failure loops.

    This guard is intentionally deterministic (no jitter) so behavior is easy to
    reason about during live trading incidents and postmortems.
    """

    def __init__(
        self,
        base_delay_seconds: float = 5.0,
        max_delay_seconds: float = 120.0,
        cooldown_log_interval_seconds: float = 15.0,
    ):
        self.base_delay_seconds = max(0.1, float(base_delay_seconds))
        self.max_delay_seconds = max(self.base_delay_seconds, float(max_delay_seconds))
        self.cooldown_log_interval_seconds = max(1.0, float(cooldown_log_interval_seconds))
        self._states: dict[str, RetryState] = {}

    @staticmethod
    def _normalize_key(symbol: str) -> str:
        return str(symbol or "").strip().upper()

    def _state(self, symbol: str) -> RetryState:
        key = self._normalize_key(symbol)
        return self._states.setdefault(key, RetryState())

    def can_attempt(self, symbol: str, now: float | None = None) -> tuple[bool, float]:
        state = self._state(symbol)
        current = time.time() if now is None else float(now)
        remaining = state.next_retry_at - current
        if remaining <= 0:
            return True, 0.0
        return False, remaining

    def should_log_cooldown(self, symbol: str, now: float | None = None) -> tuple[bool, int]:
        state = self._state(symbol)
        current = time.time() if now is None else float(now)
        if (current - state.last_cooldown_log_at) >= self.cooldown_log_interval_seconds:
            suppressed = state.suppressed_cooldown_count
            state.suppressed_cooldown_count = 0
            state.last_cooldown_log_at = current
            return True, suppressed
        state.suppressed_cooldown_count += 1
        return False, state.suppressed_cooldown_count

    def record_success(self, symbol: str):
        state = self._state(symbol)
        state.failures = 0
        state.next_retry_at = 0.0
        state.last_error_signature = ""
        state.last_error_at = 0.0
        state.suppressed_cooldown_count = 0

    def record_failure(
        self,
        symbol: str,
        error_signature: str = "",
        forced_delay_seconds: float | None = None,
        now: float | None = None,
    ) -> tuple[float, int]:
        state = self._state(symbol)
        current = time.time() if now is None else float(now)
        signature = str(error_signature or "").strip().lower()

        if forced_delay_seconds is not None:
            state.failures = max(1, state.failures + 1)
            delay = max(self.base_delay_seconds, min(float(forced_delay_seconds), self.max_delay_seconds))
        else:
            if signature and state.last_error_signature and signature != state.last_error_signature:
                # Treat a new error class as a new failure sequence.
                state.failures = 0

            state.failures += 1
            delay = self.base_delay_seconds * (2 ** min(state.failures - 1, 10))
            delay = min(delay, self.max_delay_seconds)

        state.next_retry_at = current + delay
        state.last_error_signature = signature
        state.last_error_at = current
        return delay, state.failures


def is_risk_reducing_adjustment(current_size: float, target_size: float, zero_epsilon: float = 1e-12) -> bool:
    """
    Return True when moving from `current_size` to `target_size` is exposure-reducing.
    """
    current = float(current_size)
    target = float(target_size)

    if abs(current) <= zero_epsilon:
        return False
    if abs(target) <= zero_epsilon:
        return True
    if (current > 0 > target) or (current < 0 < target):
        return False
    return abs(target) + zero_epsilon < abs(current)
