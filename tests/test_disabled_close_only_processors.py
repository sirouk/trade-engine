import pytest

from account_processors.kucoin_processor import KuCoin
from account_processors.mexc_processor import MEXC


def build_disabled_kucoin():
    processor = object.__new__(KuCoin)
    processor.enabled = False
    processor.log_prefix = "[KuCoin]"
    processor.leverage_override = 0
    processor.leverage_tolerance = 0.1
    processor.last_reconcile_error = None
    processor._record_order_success = lambda symbol: None
    processor._record_order_failure = lambda symbol, error: None
    calls = {"fetch": 0}

    async def fetch_and_map_positions(symbol):
        _ = symbol
        calls["fetch"] += 1
        return []

    async def get_symbol_details(symbol):
        _ = symbol
        return 1.0, 1.0, 0.1, 1.0, 100.0

    processor.fetch_and_map_positions = fetch_and_map_positions
    processor.get_symbol_details = get_symbol_details
    return processor, calls


def build_disabled_mexc():
    processor = object.__new__(MEXC)
    processor.enabled = False
    processor.log_prefix = "[MEXC]"
    processor.leverage_override = 0
    processor.leverage_tolerance = 0.1
    processor.last_reconcile_error = None
    processor._record_order_success = lambda symbol: None
    processor._record_order_failure = lambda symbol, error: None
    calls = {"fetch_open": 0, "fetch_map": 0}

    async def fetch_open_positions(symbol):
        _ = symbol
        calls["fetch_open"] += 1
        return []

    async def fetch_and_map_positions(symbol):
        _ = symbol
        calls["fetch_map"] += 1
        return []

    async def get_symbol_details(symbol):
        _ = symbol
        return 1.0, 1.0, 0.1, 1.0, 100.0

    processor.fetch_open_positions = fetch_open_positions
    processor.fetch_and_map_positions = fetch_and_map_positions
    processor.get_symbol_details = get_symbol_details
    return processor, calls


@pytest.mark.asyncio
async def test_kucoin_disabled_accounts_allow_close_only_reconciliation():
    processor, calls = build_disabled_kucoin()

    result = await processor.reconcile_position(
        symbol="XBTUSDTM",
        size=0,
        leverage=3,
        margin_mode="isolated",
    )

    assert result is True
    assert calls["fetch"] == 1
    assert processor.last_reconcile_error is None


@pytest.mark.asyncio
async def test_kucoin_disabled_accounts_reject_non_zero_targets_without_api_calls():
    processor, calls = build_disabled_kucoin()

    result = await processor.reconcile_position(
        symbol="XBTUSDTM",
        size=1,
        leverage=3,
        margin_mode="isolated",
    )

    assert result is False
    assert calls["fetch"] == 0
    assert "close-only reconciliation" in processor.last_reconcile_error


@pytest.mark.asyncio
async def test_mexc_disabled_accounts_allow_close_only_reconciliation():
    processor, calls = build_disabled_mexc()

    result = await processor.reconcile_position(
        symbol="BTC_USDT",
        size=0,
        leverage=3,
        margin_mode="isolated",
    )

    assert result is True
    assert calls["fetch_open"] == 1
    assert calls["fetch_map"] == 1
    assert processor.last_reconcile_error is None


@pytest.mark.asyncio
async def test_mexc_disabled_accounts_reject_non_zero_targets_without_api_calls():
    processor, calls = build_disabled_mexc()

    result = await processor.reconcile_position(
        symbol="BTC_USDT",
        size=1,
        leverage=3,
        margin_mode="isolated",
    )

    assert result is False
    assert calls["fetch_open"] == 0
    assert calls["fetch_map"] == 0
    assert "close-only reconciliation" in processor.last_reconcile_error
