import time
from dataclasses import dataclass


@dataclass
class DisabledAccountState:
    auth_failures: int = 0
    next_retry_at: float = 0.0
    quarantined: bool = False
    last_error_signature: str = ""
    last_error_at: float = 0.0
    last_skip_log_at: float = 0.0
    suppressed_skip_logs: int = 0


class DisabledAccountGuard:
    """
    Retry pacing for disabled accounts that are allowed to attempt close-only flows.

    After a small number of auth failures, the account is quarantined in-memory for
    the rest of the process lifetime to avoid repeatedly hitting dead credentials.
    """

    def __init__(
        self,
        *,
        base_delay_seconds: float = 5.0,
        max_delay_seconds: float = 60.0,
        quarantine_after_failures: int = 4,
        cooldown_log_interval_seconds: float = 30.0,
    ):
        self.base_delay_seconds = max(0.1, float(base_delay_seconds))
        self.max_delay_seconds = max(self.base_delay_seconds, float(max_delay_seconds))
        self.quarantine_after_failures = max(1, int(quarantine_after_failures))
        self.cooldown_log_interval_seconds = max(1.0, float(cooldown_log_interval_seconds))
        self._states: dict[str, DisabledAccountState] = {}

    @staticmethod
    def _normalize_key(account_key: str) -> str:
        return str(account_key or "").strip().lower()

    def state(self, account_key: str) -> DisabledAccountState:
        key = self._normalize_key(account_key)
        return self._states.setdefault(key, DisabledAccountState())

    def can_attempt(self, account_key: str, now: float | None = None) -> tuple[bool, float]:
        state = self.state(account_key)
        current = time.time() if now is None else float(now)
        if state.quarantined:
            return False, float("inf")
        remaining = state.next_retry_at - current
        if remaining <= 0:
            return True, 0.0
        return False, remaining

    def should_log_skip(self, account_key: str, now: float | None = None) -> tuple[bool, int]:
        state = self.state(account_key)
        current = time.time() if now is None else float(now)
        if (current - state.last_skip_log_at) >= self.cooldown_log_interval_seconds:
            suppressed = state.suppressed_skip_logs
            state.suppressed_skip_logs = 0
            state.last_skip_log_at = current
            return True, suppressed
        state.suppressed_skip_logs += 1
        return False, state.suppressed_skip_logs

    def record_success(self, account_key: str):
        state = self.state(account_key)
        state.auth_failures = 0
        state.next_retry_at = 0.0
        state.quarantined = False
        state.last_error_signature = ""
        state.last_error_at = 0.0
        state.suppressed_skip_logs = 0

    def record_auth_failure(
        self,
        account_key: str,
        *,
        error_signature: str = "",
        now: float | None = None,
    ) -> tuple[bool, float, int]:
        state = self.state(account_key)
        current = time.time() if now is None else float(now)
        state.auth_failures += 1
        state.last_error_signature = str(error_signature or "").strip().lower()
        state.last_error_at = current

        if state.auth_failures >= self.quarantine_after_failures:
            state.quarantined = True
            state.next_retry_at = float("inf")
            return True, float("inf"), state.auth_failures

        delay = self.base_delay_seconds * (2 ** min(state.auth_failures - 1, 10))
        delay = min(delay, self.max_delay_seconds)
        state.next_retry_at = current + delay
        return False, delay, state.auth_failures
