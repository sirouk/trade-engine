import json

from signal_processors.tradingview_processor import TradingViewProcessor


def write_log(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line)


def build_processor(tmp_path, cache_data):
    raw_dir = tmp_path / "raw_signals"
    archive_dir = raw_dir / "archive"
    raw_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    cache_file = tmp_path / "account_asset_depths.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache_data, f)

    processor = TradingViewProcessor()
    processor.RAW_SIGNALS_DIR = str(raw_dir)
    processor.ARCHIVE_DIR = str(archive_dir)
    processor.ACCOUNT_DEPTH_CACHE = str(cache_file)
    return processor


def test_tradingview_uses_close_then_open_when_prior_state_is_open(tmp_path):
    processor = build_processor(tmp_path, {"ByBit": {"ETHUSDT": 0.5}})
    write_log(
        tmp_path / "raw_signals" / "trade_requests_2026-03-10.log",
        [
            '2026-03-10 10:00:00.100000 {"symbol":"ETHUSDT","direction":"long","size":"1/1"}\n',
            '2026-03-10 10:00:00.200000 {"symbol":"ETHUSDT","direction":"flat","size":"0/1"}\n',
        ],
    )

    signals = processor.fetch_signals()

    assert signals["ETHUSDT"]["depth"] == 1.0
    assert signals["ETHUSDT"]["audit"]["ordering_basis"] == "stateful_close_then_open"
    assert signals["ETHUSDT"]["audit"]["prior_state_used"] == "open"
    assert signals["ETHUSDT"]["audit"]["adjusted"] is True


def test_tradingview_uses_open_then_close_when_prior_state_is_flat(tmp_path):
    processor = build_processor(tmp_path, {"ByBit": {"ETHUSDT": 0}})
    write_log(
        tmp_path / "raw_signals" / "trade_requests_2026-03-10.log",
        [
            '2026-03-10 10:00:00.100000 {"symbol":"ETHUSDT","direction":"flat","size":"0/1"}\n',
            '2026-03-10 10:00:00.200000 {"symbol":"ETHUSDT","direction":"long","size":"1/1"}\n',
        ],
    )

    signals = processor.fetch_signals()

    assert signals["ETHUSDT"]["depth"] == 0.0
    assert signals["ETHUSDT"]["audit"]["ordering_basis"] == "stateful_open_then_close"
    assert signals["ETHUSDT"]["audit"]["prior_state_used"] == "flat"
    assert signals["ETHUSDT"]["audit"]["adjusted"] is True


def test_tradingview_signal_sequence_overrides_stateful_transition_order(tmp_path):
    processor = build_processor(tmp_path, {"ByBit": {"ETHUSDT": 0.5}})
    write_log(
        tmp_path / "raw_signals" / "trade_requests_2026-03-10.log",
        [
            '2026-03-10 10:00:00.100000 {"symbol":"ETHUSDT","direction":"long","size":"1/1","signal_seq":1}\n',
            '2026-03-10 10:00:00.100000 {"symbol":"ETHUSDT","direction":"flat","size":"0/1","signal_seq":2}\n',
        ],
    )

    signals = processor.fetch_signals()

    assert signals["ETHUSDT"]["depth"] == 0.0
    assert signals["ETHUSDT"]["audit"]["ordering_basis"] == "explicit_sequence"
    assert signals["ETHUSDT"]["audit"]["prior_state_used"] == "open"
