from core.utils.order_retry_guard import OrderRetryGuard, is_risk_reducing_adjustment


def test_retry_guard_exponential_backoff_and_reset():
    guard = OrderRetryGuard(base_delay_seconds=5.0, max_delay_seconds=60.0, cooldown_log_interval_seconds=10.0)
    now = 1000.0

    can_attempt, retry_in = guard.can_attempt("ETHUSDT", now=now)
    assert can_attempt is True
    assert retry_in == 0.0

    delay_1, failures_1 = guard.record_failure("ETHUSDT", error_signature="network timeout", now=now)
    assert failures_1 == 1
    assert delay_1 == 5.0

    can_attempt, retry_in = guard.can_attempt("ETHUSDT", now=1002.0)
    assert can_attempt is False
    assert round(retry_in, 1) == 3.0

    delay_2, failures_2 = guard.record_failure("ETHUSDT", error_signature="network timeout", now=1005.0)
    assert failures_2 == 2
    assert delay_2 == 10.0

    guard.record_success("ETHUSDT")
    can_attempt, retry_in = guard.can_attempt("ETHUSDT", now=1006.0)
    assert can_attempt is True
    assert retry_in == 0.0


def test_retry_guard_supports_forced_delay_and_cooldown_log_throttle():
    guard = OrderRetryGuard(base_delay_seconds=5.0, max_delay_seconds=120.0, cooldown_log_interval_seconds=15.0)
    now = 2000.0

    delay, failures = guard.record_failure(
        "SOLUSDT",
        error_signature="minimum value violation",
        forced_delay_seconds=90.0,
        now=now,
    )
    assert failures == 1
    assert delay == 90.0

    can_attempt, retry_in = guard.can_attempt("SOLUSDT", now=2050.0)
    assert can_attempt is False
    assert round(retry_in, 1) == 40.0

    should_log, suppressed = guard.should_log_cooldown("SOLUSDT", now=2050.0)
    assert should_log is True
    assert suppressed == 0

    should_log, suppressed = guard.should_log_cooldown("SOLUSDT", now=2055.0)
    assert should_log is False
    assert suppressed == 1

    should_log, suppressed = guard.should_log_cooldown("SOLUSDT", now=2066.0)
    assert should_log is True
    assert suppressed == 1


def test_is_risk_reducing_adjustment():
    assert is_risk_reducing_adjustment(1.5, 1.0) is True
    assert is_risk_reducing_adjustment(-2.0, -1.0) is True
    assert is_risk_reducing_adjustment(1.5, 0.0) is True
    assert is_risk_reducing_adjustment(-1.5, 0.0) is True
    assert is_risk_reducing_adjustment(0.0, 1.0) is False
    assert is_risk_reducing_adjustment(1.0, 1.5) is False
    assert is_risk_reducing_adjustment(-1.0, -1.5) is False
    assert is_risk_reducing_adjustment(1.0, -0.5) is False
