import json

import pytest

from core.utils.disabled_account_guard import DisabledAccountGuard
from core.utils import disabled_account_guard as disabled_account_guard_module
from execute_trades import TradeExecutor


class FakeSignalManager:
    def __init__(self, changed_symbols):
        self.changed_symbols = list(changed_symbols)
        self.confirm_calls = []

    def get_changed_symbols(self, _account_name):
        return list(self.changed_symbols)

    def get_target_leverage(self, account_name, symbol, fallback=1):
        _ = (account_name, symbol)
        return fallback

    async def confirm_execution(self, account_name, success):
        self.confirm_calls.append((account_name, success))


class FakeDisabledAccount:
    def __init__(self, *, auth_error: str | None = None):
        self.exchange_name = "KuCoin"
        self.account_name = "KuCoin"
        self.enabled = False
        self.auth_error = auth_error
        self.last_reconcile_error = None
        self.reconcile_calls = 0
        self.map_calls = 0

    def map_signal_symbol_to_exchange(self, signal_symbol: str) -> str:
        self.map_calls += 1
        return f"mapped::{signal_symbol}"

    async def reconcile_position(self, symbol: str, size: float, leverage: int, margin_mode: str):
        _ = (symbol, size, leverage, margin_mode)
        self.reconcile_calls += 1
        if self.auth_error:
            self.last_reconcile_error = self.auth_error
            return False
        self.last_reconcile_error = None
        return True


def build_executor(changed_symbols, *, weight_symbols=None):
    if weight_symbols is None:
        weight_symbols = ["BTCUSDT"]
    executor = object.__new__(TradeExecutor)
    executor.weight_config = [
        {"symbol": symbol, "leverage": 3, "sources": []}
        for symbol in weight_symbols
    ]
    executor.signal_manager = FakeSignalManager(changed_symbols)
    executor._account_retry_state = {}
    executor._disabled_account_guard = DisabledAccountGuard(
        base_delay_seconds=0.01,
        max_delay_seconds=0.05,
        quarantine_after_failures=4,
        cooldown_log_interval_seconds=0.01,
    )
    return executor


@pytest.mark.asyncio
async def test_disabled_account_with_zero_cached_depth_makes_no_api_calls(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with open(tmp_path / "account_asset_depths.json", "w", encoding="utf-8") as f:
        json.dump({"KuCoin": {"BTCUSDT": 0}}, f)

    executor = build_executor(["BTCUSDT"])
    account = FakeDisabledAccount()

    success, error = await executor.process_account(account, signals={})

    assert success is True
    assert error is None
    assert account.map_calls == 0
    assert account.reconcile_calls == 0
    assert executor.signal_manager.confirm_calls == []


@pytest.mark.asyncio
async def test_disabled_account_auth_failures_quarantine_after_fourth_attempt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with open(tmp_path / "account_asset_depths.json", "w", encoding="utf-8") as f:
        json.dump({"KuCoin": {"BTCUSDT": 0.25}}, f)

    executor = build_executor(["BTCUSDT"])
    account = FakeDisabledAccount(auth_error="invalid api key")
    account_key = TradeExecutor._get_account_key(account)
    clock = {"now": 1000.0}

    monkeypatch.setattr(
        disabled_account_guard_module.time,
        "time",
        lambda: clock["now"],
    )

    for _ in range(4):
        success, error = await executor.process_account(account, signals={})
        assert success is False
        assert "disabled-close failures" in error
        clock["now"] += 0.11

    state = executor._disabled_account_guard.state(account_key)
    assert state.quarantined is True
    assert account.reconcile_calls == 4

    success, error = await executor.process_account(account, signals={})
    assert success is False
    assert "retry cooldown or quarantine" in error
    assert account.reconcile_calls == 4
    assert executor.signal_manager.confirm_calls == []


@pytest.mark.asyncio
async def test_disabled_account_stops_after_first_auth_failure_in_cycle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with open(tmp_path / "account_asset_depths.json", "w", encoding="utf-8") as f:
        json.dump({"KuCoin": {"BTCUSDT": 0.25, "ETHUSDT": -0.1}}, f)

    executor = build_executor(
        ["BTCUSDT", "ETHUSDT"],
        weight_symbols=["BTCUSDT", "ETHUSDT"],
    )
    account = FakeDisabledAccount(auth_error="invalid api key")

    success, error = await executor.process_account(account, signals={})

    assert success is False
    assert "disabled-close failures" in error
    assert account.reconcile_calls == 1
    assert account.map_calls == 1
