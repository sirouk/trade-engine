#!/usr/bin/env python3
"""
Read-only Bybit sizing validator.

Fetches public instrument metadata and tickers, then compares the legacy native
quantity scaling against the corrected linear-contract scaling.
"""

import argparse
import asyncio

from account_processors.bybit_processor import ByBit
from core.utils.modifiers import scale_size_and_price


async def validate_symbols(symbols: list[str], notionals: list[float]):
    processor = ByBit()

    for symbol in symbols:
        ticker = await processor.fetch_tickers(symbol)
        if not ticker or not ticker.last:
            print(f"{symbol}: could not fetch ticker")
            continue

        lot_size, min_size, tick_size, contract_value, max_size = await processor.get_symbol_details(symbol)
        legacy_contract_value = lot_size / min_size if min_size else 0.0

        print(f"\n{symbol}")
        print(f"  Price: {ticker.last}")
        print(f"  Qty Step: {lot_size}")
        print(f"  Min Qty: {min_size}")
        print(f"  Tick Size: {tick_size}")
        print(f"  Corrected Contract Value: {contract_value}")
        print(f"  Legacy Derived Contract Value: {legacy_contract_value}")
        print(f"  Max Qty: {max_size}")

        for notional in notionals:
            target_size = notional / ticker.last
            corrected_size, _, _ = scale_size_and_price(
                symbol,
                size=target_size,
                price=0,
                lot_size=lot_size,
                min_lots=min_size,
                tick_size=tick_size,
                contract_value=contract_value,
            )
            legacy_size, _, _ = scale_size_and_price(
                symbol,
                size=target_size,
                price=0,
                lot_size=lot_size,
                min_lots=min_size,
                tick_size=tick_size,
                contract_value=legacy_contract_value or 1.0,
            )
            print(
                f"  Notional ${notional:>7.2f}: corrected={corrected_size} "
                f"legacy={legacy_size}"
            )


def parse_args():
    parser = argparse.ArgumentParser(description="Validate Bybit linear quantity scaling without placing orders")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT", "ADAUSDT"],
        help="Bybit linear symbols to inspect",
    )
    parser.add_argument(
        "--notionals",
        nargs="+",
        type=float,
        default=[10.0, 25.0, 50.0, 100.0],
        help="Target USD notionals to compare",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(validate_symbols(args.symbols, args.notionals))
