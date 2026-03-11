from types import SimpleNamespace

import pytest

from account_processors.bybit_processor import ByBit
from core.utils.modifiers import scale_size_and_price


@pytest.mark.asyncio
async def test_bybit_linear_contract_value_is_one_for_symbol_details():
    processor = object.__new__(ByBit)
    processor.bybit_client = SimpleNamespace(
        get_instruments_info=lambda **kwargs: {
            "result": {
                "list": [
                    {
                        "symbol": kwargs["symbol"],
                        "lotSizeFilter": {
                            "qtyStep": "0.001",
                            "minOrderQty": "0.01",
                            "maxOrderQty": "500",
                        },
                        "priceFilter": {"tickSize": "0.1"},
                    }
                ]
            }
        }
    )

    lot_size, min_size, tick_size, contract_value, max_size = await processor.get_symbol_details("BTCUSDT")

    assert lot_size == 0.001
    assert min_size == 0.01
    assert tick_size == 0.1
    assert contract_value == 1.0
    assert max_size == 500.0


def test_bybit_corrected_linear_scaling_avoids_legacy_contract_ratio_error():
    size = 0.0196
    lot_size = 0.001
    min_size = 0.01
    tick_size = 0.1

    corrected_lots, _, _ = scale_size_and_price(
        "BTCUSDT",
        size=size,
        price=0,
        lot_size=lot_size,
        min_lots=min_size,
        tick_size=tick_size,
        contract_value=1.0,
    )
    legacy_lots, _, _ = scale_size_and_price(
        "BTCUSDT",
        size=size,
        price=0,
        lot_size=lot_size,
        min_lots=min_size,
        tick_size=tick_size,
        contract_value=lot_size / min_size,
    )

    assert corrected_lots == 0.02
    assert legacy_lots == 0.196
    assert corrected_lots < legacy_lots
