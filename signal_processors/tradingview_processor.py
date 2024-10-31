import os
import math
import time
import ujson as json
from datetime import datetime, timedelta

RAW_SIGNALS_DIR = "raw_signals/tradingview"

def get_recent_files(directory, days=1):
    cutoff = datetime.now() - timedelta(days=days)
    recent_files = []
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        if os.path.isfile(file_path) and datetime.fromtimestamp(os.path.getmtime(file_path)) > cutoff:
            recent_files.append(file_path)
    return recent_files

def parse_signal_file(file_path, symbol_dates):
    signals = {}
    with open(file_path, 'r') as f:
        for line in f:
            # parse the line that looks like: 2024-10-25 10:03:04.954132 { "symbol": "ETHUSDT", "direction": "flat", "action": "sell", "leverage": "", "size": "Exit @ 3.425", "priority": "high", "takeprofit": "0.00", "trailstop": "0.00" }
            date, timestamp, data = line.split(" ", 2)
            signal_data = json.loads(data)
            symbol = signal_data.get("symbol")
            if not symbol:
                continue

            # If the symbol has been seen before, check if the current signal is newer
            line_timestamp = datetime.strptime(f"{date} {timestamp}", "%Y-%m-%d %H:%M:%S.%f")
            if symbol in symbol_dates and symbol_dates[symbol] > line_timestamp:
                continue
            # Record the timestamp for the symbol
            symbol_dates[symbol] = line_timestamp

            # Only update to latest direction per symbol
            # interpret the percent of 1.0 representing the depth of the signal
            direction = signal_data.get("direction")
            if direction not in ["long", "short", "flat"]:
                print(f"Invalid direction: {direction}")
                continue
            
            depth = 0.0
            if symbol in signals and signal_data["direction"] == "flat":
                depth = 0.0
            elif "/" in signal_data["size"]:
                numerator, denominator = signal_data["size"].split("/")
                # take the absolute value of the numerator divided by the denominator
                depth = abs(float(numerator) / float(denominator))
                
                # If the signal is negatve, then the depth is negative
                if numerator.startswith("-"):
                    depth = -depth
            else:
                continue
            
            price = float(signal_data.get("price"))
            if not price:
                print(f"Invalid price: {price}")
                continue
                    
            signals[symbol] = {
                "depth": depth,
                "price": price,
                "timestamp": line_timestamp,
            }
    return signals, symbol_dates

def fetch_tradingview_signals():
    recent_files = get_recent_files(RAW_SIGNALS_DIR)
    print(recent_files)
    all_signals = {}
    symbol_dates = {}
    for file_path in recent_files:
        signals, symbol_dates = parse_signal_file(file_path, symbol_dates)
        for symbol, signal_data in signals.items():
            all_signals[symbol] = signal_data  # Update to latest status per asset
    return all_signals

# Test Function
if __name__ == '__main__':
    tradingview_signals = fetch_tradingview_signals()
    for symbol, data in tradingview_signals.items():
        print(f"Latest signal for {symbol}: {data}")