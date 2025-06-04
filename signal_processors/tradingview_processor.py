import os
from datetime import datetime, timedelta
import ujson as json
import zipfile

class TradingViewProcessor:
    SIGNAL_SOURCE = "tradingview"
    RAW_SIGNALS_DIR = "raw_signals/tradingview"
    ARCHIVE_DIR = "raw_signals/tradingview/archive"
    SIGNAL_FILE_PREFIX = "trade_requests"
    ASSET_MAPPING_CONFIG = "asset_mapping_config.json"
    
    def __init__(self, *, enabled=True):
        self.enabled = enabled
        self.verbose = __name__ == '__main__'
        self.CORE_ASSET_MAPPING = self._load_asset_mapping()

    def _load_asset_mapping(self):
        """Load asset mapping from configuration file."""
        try:
            with open(self.ASSET_MAPPING_CONFIG, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get(self.SIGNAL_SOURCE, {})
        except (FileNotFoundError, json.JSONDecodeError):
            # Return default mapping if config file doesn't exist or is invalid
            return {
                "BTCUSDT": "BTCUSDT",
                "ETHUSDT": "ETHUSDT",
                #"ADAUSDT": "ADAUSDT",
            }

    def reload_asset_mapping(self):
        """Reload asset mapping configuration."""
        self.CORE_ASSET_MAPPING = self._load_asset_mapping()

    def fetch_signals(self):
        """Main entry point to fetch and process signals."""
        # Reload asset mapping configuration before processing signals
        self.reload_asset_mapping()
        
        self._archive_old_files()
        recent_files = self._get_recent_files(self.RAW_SIGNALS_DIR)
        signals = {}
        symbol_dates = {}
        for file_path in recent_files:
            signals, symbol_dates = self._parse_signal_file(file_path, signals, symbol_dates)
        return signals

    def _get_recent_files(self, directory, days=60):
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
        if self.verbose:
            print(f"\nProcessing file: {file_path}")
        
        # First, collect all signals from the file
        all_signals = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    # Skip comment lines or empty lines
                    if line.strip().startswith('#') or line.strip() == '':
                        if self.verbose:
                            print(f"Skipping comment line: {line.strip()}")
                        continue
                        
                    # Parse the timestamp and signal data
                    date, timestamp, signal_data = line.split(" ", 2)
                    signal_data = json.loads(signal_data)
                    if self.verbose:
                        print(f"\nAnalyzing signal: {date} {timestamp}")
                        print(f"Signal data: {signal_data}")
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
                        depth = abs(numerator) / abs(denominator)
                        if numerator < 0 or direction == "short":
                            depth = -depth
                    else:
                        print(f"Unexpected size format: {size}")
                        continue
                except (ValueError, ZeroDivisionError):
                    print(f"Error parsing size: {size}")
                    continue

                # Parse price
                try:
                    price = float(signal_data.get("price", 0.0)) if "price" in signal_data else None
                except ValueError:
                    print(f"Price parsing error in line: {line}")
                    continue

                # Store the signal with all its data
                signal_entry = {
                    "symbol": symbol,
                    "original_symbol": original_symbol,
                    "direction": direction,
                    "depth": depth,
                    "price": price if price is not None and price > 0 else None,
                    "timestamp": line_timestamp,
                    "original_timestamp": line_timestamp.isoformat(),  # Preserve original timestamp
                    "raw_data": signal_data  # Keep raw data for audit purposes
                }
                
                all_signals.append(signal_entry)
        
        # Now process signals with race condition handling
        # Group signals by symbol
        symbol_signals = {}
        for signal in all_signals:
            symbol = signal["symbol"]
            if symbol not in symbol_signals:
                symbol_signals[symbol] = []
            symbol_signals[symbol].append(signal)
        
        # Process each symbol's signals
        for symbol, symbol_signal_list in symbol_signals.items():
            # Sort by timestamp
            symbol_signal_list.sort(key=lambda x: x["timestamp"])
            
            # Handle race conditions for close timestamps
            processed_signals = self._handle_race_conditions(symbol_signal_list)
            
            # Find the most recent valid signal
            latest_signal = None
            latest_timestamp = None
            
            for signal in processed_signals:
                # Skip if we already have a newer signal from another file
                if symbol in symbol_dates and signal["timestamp"] < symbol_dates[symbol]:
                    if self.verbose:
                        print(f"Skipping older signal for {symbol}. Current: {symbol_dates[symbol]}, This: {signal['timestamp']}")
                    continue
                
                latest_signal = signal
                latest_timestamp = signal["timestamp"]
            
            # Update the signals dictionary with the latest signal
            if latest_signal:
                if self.verbose:
                    print(f"Using signal for {symbol}. Timestamp: {latest_timestamp}")
                symbol_dates[symbol] = latest_timestamp
                
                signals[symbol] = {
                    "symbol": symbol,
                    "original_symbols": [latest_signal["original_symbol"]],
                    "depth": latest_signal["depth"],
                    "price": latest_signal["price"],
                    "average_price": None,
                    "timestamp": latest_signal["timestamp"],
                    "audit": {
                        "original_timestamp": latest_signal["original_timestamp"],
                        "adjusted": latest_signal.get("timestamp_adjusted", False),
                        "adjustment_reason": latest_signal.get("adjustment_reason", None)
                    }
                }
                
        return signals, symbol_dates

    def _handle_race_conditions(self, signal_list):
        """Handle race conditions when signals are very close in time.
        
        Specifically targets the pattern where a position close (flat) and 
        a new position open arrive in quick succession, which should be 
        processed as a single position transition.
        """
        if len(signal_list) < 2:
            return signal_list
        
        # Define threshold for "close" timestamps (5 seconds for single-threaded strategies)
        CLOSE_THRESHOLD = timedelta(seconds=5)
        
        processed = []
        i = 0
        
        while i < len(signal_list):
            current = signal_list[i]
            
            # Only look for race conditions if current signal is involved in a position transition
            if current["direction"] in ["flat", "long", "short"]:
                # Look for the specific pattern: flat followed by position, or position followed by flat
                if i + 1 < len(signal_list):
                    next_signal = signal_list[i + 1]
                    time_diff = next_signal["timestamp"] - current["timestamp"]
                    
                    # Check if this is a position transition pattern within threshold
                    if time_diff <= CLOSE_THRESHOLD:
                        is_transition = False
                        transition_group = []
                        
                        # Pattern 1: Position followed by flat (wrong order - needs reordering)
                        if (current["direction"] in ["long", "short"] and 
                            next_signal["direction"] == "flat"):
                            is_transition = True
                            # Reorder: flat should come first
                            transition_group = [next_signal, current]
                            if self.verbose:
                                print(f"Detected out-of-order position transition for {current['symbol']}: "
                                      f"{current['direction']} -> flat")
                        
                        # Pattern 2: Flat followed by position (correct order - keep as is)
                        elif (current["direction"] == "flat" and 
                              next_signal["direction"] in ["long", "short"]):
                            is_transition = True
                            transition_group = [current, next_signal]
                            if self.verbose:
                                print(f"Detected position transition for {current['symbol']}: "
                                      f"flat -> {next_signal['direction']}")
                        
                        if is_transition:
                            # Adjust timestamps to maintain order
                            base_time = transition_group[0]["timestamp"]
                            for idx, signal in enumerate(transition_group):
                                if idx > 0:
                                    # Add microseconds to ensure proper ordering
                                    signal["timestamp"] = base_time + timedelta(microseconds=idx * 1000)
                                    signal["timestamp_adjusted"] = True
                                    signal["adjustment_reason"] = "position_transition_reorder"
                            
                            processed.extend(transition_group)
                            i += 2  # Skip the next signal as we've already processed it
                            continue
            
            # No race condition detected, add signal as-is
            processed.append(current)
            i += 1
        
        return processed
    
    def _reorder_position_transitions(self, signal_group):
        """DEPRECATED: Replaced by more targeted logic in _handle_race_conditions.
        
        This method is kept for backward compatibility but is no longer used.
        """
        # Separate flat and position signals
        flat_signals = [s for s in signal_group if s["direction"] == "flat"]
        position_signals = [s for s in signal_group if s["direction"] in ["long", "short"]]
        
        # If we have both flat and position signals, ensure flat comes first
        if flat_signals and position_signals:
            if self.verbose:
                print(f"Reordering signals for proper position transition")
            return flat_signals + position_signals
        
        # Otherwise, keep original order
        return signal_group

    def _archive_old_files(self, days=60):
        """Archive files older than specified days."""
        if not os.path.exists(self.ARCHIVE_DIR):
            os.makedirs(self.ARCHIVE_DIR)
            
        cutoff = datetime.now() - timedelta(days=days)
        
        for filename in os.listdir(self.RAW_SIGNALS_DIR):
            # Only process trade request files
            if not filename.startswith(f'{self.SIGNAL_FILE_PREFIX}_') or filename == 'archive' or filename.startswith('.'):
                continue
                
            file_path = os.path.join(self.RAW_SIGNALS_DIR, filename)
            if not os.path.isfile(file_path):
                continue
                
            file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
            if file_time < cutoff:
                # Create zip file name with original timestamp
                zip_filename = f"{os.path.splitext(filename)[0]}.zip"
                zip_path = os.path.join(self.ARCHIVE_DIR, zip_filename)
                
                # Create zip file and add the old file
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(file_path, filename)
                
                # Remove the original file
                os.remove(file_path)
                print(f"Archived {filename} to {zip_filename}")

# Test Function
if __name__ == '__main__':
    processor = TradingViewProcessor()
    result_signals = processor.fetch_signals()
    print(f"Total signals: {len(result_signals)}") 
    print(result_signals)
