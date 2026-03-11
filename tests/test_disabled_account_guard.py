from core.utils.disabled_account_guard import DisabledAccountGuard


def test_disabled_account_guard_backoff_then_quarantine():
    guard = DisabledAccountGuard(
        base_delay_seconds=5.0,
        max_delay_seconds=60.0,
        quarantine_after_failures=4,
        cooldown_log_interval_seconds=10.0,
    )
    now = 1000.0

    can_attempt, retry_in = guard.can_attempt("KuCoin", now=now)
    assert can_attempt is True
    assert retry_in == 0.0

    quarantined, retry_in, failures = guard.record_auth_failure(
        "KuCoin",
        error_signature="invalid api key",
        now=now,
    )
    assert quarantined is False
    assert retry_in == 5.0
    assert failures == 1

    quarantined, retry_in, failures = guard.record_auth_failure(
        "KuCoin",
        error_signature="invalid api key",
        now=1005.0,
    )
    assert quarantined is False
    assert retry_in == 10.0
    assert failures == 2

    quarantined, retry_in, failures = guard.record_auth_failure(
        "KuCoin",
        error_signature="invalid api key",
        now=1015.0,
    )
    assert quarantined is False
    assert retry_in == 20.0
    assert failures == 3

    quarantined, retry_in, failures = guard.record_auth_failure(
        "KuCoin",
        error_signature="invalid api key",
        now=1035.0,
    )
    assert quarantined is True
    assert retry_in == float("inf")
    assert failures == 4

    can_attempt, retry_in = guard.can_attempt("KuCoin", now=999999.0)
    assert can_attempt is False
    assert retry_in == float("inf")

    guard.record_success("KuCoin")
    can_attempt, retry_in = guard.can_attempt("KuCoin", now=1000000.0)
    assert can_attempt is True
    assert retry_in == 0.0
