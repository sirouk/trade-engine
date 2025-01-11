import os
from datetime import datetime, timedelta
import ujson as json

class TradingViewProcessor:
    SIGNAL_SOURCE = "tradingview"
    RAW_SIGNALS_DIR = "raw_signals/tradingview"
    
    CORE_ASSET_MAPPING = {
        "BTCUSDT": "BTCUSDT",
        "ETHUSDT": "ETHUSDT",
    }

    def __init__(self, *, enabled=True):
        self.enabled = enabled

    def fetch_signals(self):
        """Main entry point to fetch and process signals."""
        recent_files = self._get_recent_files(self.RAW_SIGNALS_DIR)
        signals = {}
        symbol_dates = {}
        for file_path in recent_files:
            signals, symbol_dates = self._parse_signal_file(file_path, signals, symbol_dates)
        return signals

    def _get_recent_files(self, directory, days=70):
        """Retrieve files modified within the last `days`."""
        cutoff = datetime.now() - timedelta(days=days)
        recent_files = []
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path) and datetime.fromtimestamp(os.path.getmtime(file_path)) > cutoff:
                recent_files.append(file_path)
        return recent_files

    def _normalize_symbol(self, symbol):
        """Normalize the symbol based on the core asset mapping."""
        return self.CORE_ASSET_MAPPING.get(symbol, symbol)

    def _parse_signal_file(self, file_path, signals, symbol_dates):
        """Parse a signal file and update signals with the latest data."""
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    # Parse the timestamp and signal data
                    date, timestamp, signal_data = line.split(" ", 2)
                    signal_data = json.loads(signal_data)
                except ValueError:
                    print(f"Malformed line skipped: {line}")
                    continue

                # Extract and normalize the symbol
                original_symbol = signal_data.get("symbol")
                if not original_symbol:
                    print("No symbol found in line; skipping.")
                    continue
                symbol = self._normalize_symbol(original_symbol)

                # Parse timestamp
                try:
                    line_timestamp = datetime.strptime(f"{date} {timestamp}", "%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    print(f"Invalid timestamp in line: {line}")
                    continue

                # Skip older signals
                if symbol in symbol_dates and symbol_dates[symbol] > line_timestamp:
                    continue
                symbol_dates[symbol] = line_timestamp  # Update timestamp

                # Validate and parse direction
                direction = signal_data.get("direction")
                if direction not in ["long", "short", "flat"]:
                    print(f"Invalid direction: {direction}")
                    continue

                # Calculate depth
                depth = 0.0
                size = signal_data.get("size", "").strip()
                try:
                    if direction == "flat":
                        depth = 0.0
                    elif "/" in size:
                        numerator, denominator = map(float, size.split("/"))
                        depth = abs(numerator / denominator)
                        if numerator < 0:
                            depth = -depth
                    else:
                        print(f"Unexpected size format: {size}")
                        continue
                except (ValueError, ZeroDivisionError):
                    print(f"Error parsing size: {size}")
                    continue

                # Parse price
                try:
                    price = float(signal_data.get("price", 0.0))
                    if price <= 0.0:
                        print(f"Invalid price: {price}")
                        continue
                except ValueError:
                    print(f"Price parsing error in line: {line}")
                    continue

                # Update signals
                signals[symbol] = {
                    "symbol": symbol,
                    "original_symbols": [original_symbol],
                    "depth": depth,
                    "price": price,
                    "average_price": None,
                    "timestamp": line_timestamp,
                }
        return signals, symbol_dates

# Test Function
if __name__ == '__main__':
    processor = TradingViewProcessor()
    signals = processor.fetch_signals()
    print(f"Total signals: {len(signals)}") 
    print(signals)
