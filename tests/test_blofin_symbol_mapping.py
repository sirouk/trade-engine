from account_processors.blofin_processor import BloFin


def test_blofin_1000pepe_mapping_override():
    processor = object.__new__(BloFin)
    processor.SIGNAL_SYMBOL_OVERRIDES = BloFin.SIGNAL_SYMBOL_OVERRIDES

    assert processor.map_signal_symbol_to_exchange("1000PEPEUSDT") == "PEPE-USDT"
    assert processor.map_signal_symbol_to_exchange("1000BONKUSDT") == "1000BONK-USDT"


def test_blofin_fallback_symbol_for_1000_prefix():
    processor = object.__new__(BloFin)

    assert processor._fallback_symbol("1000PEPE-USDT") == "PEPE-USDT"
    assert processor._fallback_symbol("BTC-USDT") is None
