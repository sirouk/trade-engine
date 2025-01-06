import os
from datetime import datetime, timedelta

import ujson as json

SIGNAL_SOURCE = "TradingView"

RAW_SIGNALS_DIR = "raw_signals/tradingview"

# Core asset mapping dictionary to normalize symbols to a standardized format
CORE_ASSET_MAPPING = {
    "BTCUSDT": "BTCUSDT",
    "ETHUSDT": "ETHUSDT",
    # Add more mappings as needed
}

def get_recent_files(directory, days=7):
    cutoff = datetime.now() - timedelta(days=days)
    recent_files = []
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        if os.path.isfile(file_path) and datetime.fromtimestamp(os.path.getmtime(file_path)) > cutoff:
            recent_files.append(file_path)
    return recent_files

def normalize_symbol(signal_symbol):
    """Normalize the symbol based on the core asset mapping."""
    return CORE_ASSET_MAPPING.get(signal_symbol, signal_symbol)

def parse_signal_file(file_path, symbol_dates):
    signals = {}
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            # Parse the line that looks like: 2024-10-25 10:03:04.954132 { "symbol": "ETHUSDT", "direction": "flat", "action": "sell", "leverage": "", "size": "Exit @ 3.425", "priority": "high", "takeprofit": "0.00", "trailstop": "0.00" }
            date, timestamp, signal_data = line.split(" ", 2)
            signal_data = json.loads(signal_data)
            signal_symbol = signal_data.get("symbol")
            if not signal_symbol:
                continue

            # Normalize the symbol to match core asset format
            signal_symbol = normalize_symbol(signal_symbol)

            # If the symbol has been seen before, check if the current signal is newer
            line_timestamp = datetime.strptime(f"{date} {timestamp}", "%Y-%m-%d %H:%M:%S.%f")
            if signal_symbol in symbol_dates and symbol_dates[signal_symbol] > line_timestamp:
                continue
            # Record the timestamp for the symbol
            symbol_dates[signal_symbol] = line_timestamp

            # Only update to latest direction per symbol
            direction = signal_data.get("direction")
            if direction not in ["long", "short", "flat"]:
                print(f"Invalid direction: {direction}")
                continue

            # Calculate depth based on the "size" field
            depth = 0.0
            if signal_symbol in signals and direction == "flat":
                depth = 0.0
            elif "/" in signal_data["size"]:
                numerator, denominator = signal_data["size"].split("/")
                depth = abs(float(numerator) / float(denominator))
                if numerator.startswith("-"):
                    depth = -depth
            else:
                continue

            price = float(signal_data.get("price", 0.0))
            if price == 0.0:
                print(f"Invalid price: {price}")
                continue

            signals[signal_symbol] = {
                "original_symbol": signal_symbol,
                "depth": depth,
                "price": price,
                "timestamp": line_timestamp,
            }
    return signals, symbol_dates

def fetch_tradingview_signals():
    recent_files = get_recent_files(RAW_SIGNALS_DIR)
    all_signals = {}
    symbol_dates = {}
    for file_path in recent_files:
        signals, symbol_dates = parse_signal_file(file_path, symbol_dates)
        all_signals |= signals  # Merge to keep the latest status per asset
    return all_signals  # Return all signals instead of printing

# Test Function
if __name__ == '__main__':
    tradingview_signals = fetch_tradingview_signals()
    for symbol, data in tradingview_signals.items():
        print(f"Latest signal for {symbol}: {data}")
