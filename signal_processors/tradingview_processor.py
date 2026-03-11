import os
from datetime import datetime, timedelta
import ujson as json
import zipfile
from typing import Any

class TradingViewProcessor:
    SIGNAL_SOURCE = "tradingview"
    RAW_SIGNALS_DIR = "raw_signals/tradingview"
    ARCHIVE_DIR = "raw_signals/tradingview/archive"
    SIGNAL_FILE_PREFIX = "trade_requests"
    ASSET_MAPPING_CONFIG = "asset_mapping_config.json"
    ACCOUNT_DEPTH_CACHE = "account_asset_depths.json"
    
    def __init__(self, *, enabled=True):
        self.enabled = enabled
        self.verbose = __name__ == '__main__'
        self.CORE_ASSET_MAPPING = self._load_asset_mapping()
        self._last_resolved_signals = {}
        self._cached_symbol_state = {}

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
        self._cached_symbol_state = self._load_cached_symbol_state()
        
        self._archive_old_files()
        recent_files = self._get_recent_files(self.RAW_SIGNALS_DIR)
        signals = {}
        symbol_dates = {}
        for file_order, file_path in enumerate(recent_files):
            signals, symbol_dates = self._parse_signal_file(
                file_path,
                file_order,
                signals,
                symbol_dates,
            )
        self._last_resolved_signals = {
            symbol: dict(signal)
            for symbol, signal in signals.items()
        }
        return signals

    def _get_recent_files(self, directory, days=60):
        """Retrieve files modified within the last `days`."""
        cutoff = datetime.now() - timedelta(days=days)
        recent_files = []
        if not os.path.isdir(directory):
            return recent_files
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path) and datetime.fromtimestamp(os.path.getmtime(file_path)) > cutoff:
                recent_files.append(file_path)
        return sorted(recent_files, key=lambda path: (os.path.basename(path), path))

    def _normalize_symbol(self, symbol):
        """Normalize the symbol based on the core asset mapping."""
        return self.CORE_ASSET_MAPPING.get(symbol, symbol)

    @staticmethod
    def _parse_leverage(raw_leverage, direction):
        """Parse optional leverage from TradingView payload."""
        if direction == "flat":
            return None
        if raw_leverage is None:
            return None
        leverage_str = str(raw_leverage).strip()
        if leverage_str == "":
            return None
        try:
            leverage = float(leverage_str)
        except (TypeError, ValueError):
            return None
        if leverage <= 0:
            return None
        return leverage

    def _load_cached_symbol_state(self):
        """
        Build a coarse symbol state from the aggregated account depth cache.
        """
        try:
            with open(self.ACCOUNT_DEPTH_CACHE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

        symbol_state = {}
        for account_depths in cache.values():
            if not isinstance(account_depths, dict):
                continue
            for symbol, depth in account_depths.items():
                try:
                    if float(depth) != 0:
                        symbol_state[symbol] = "open"
                    else:
                        symbol_state.setdefault(symbol, "flat")
                except (TypeError, ValueError):
                    continue
        return symbol_state

    @staticmethod
    def _signal_state(signal: dict | None) -> str | None:
        if not signal:
            return None
        try:
            return "open" if float(signal.get("depth", 0)) != 0 else "flat"
        except (TypeError, ValueError):
            return None

    def _resolve_prior_state(self, symbol: str, signals: dict) -> str | None:
        current_signal = signals.get(symbol)
        current_state = self._signal_state(current_signal)
        if current_state is not None:
            return current_state

        previous_signal = self._last_resolved_signals.get(symbol)
        previous_state = self._signal_state(previous_signal)
        if previous_state is not None:
            return previous_state

        return self._cached_symbol_state.get(symbol)

    @staticmethod
    def _parse_explicit_sequence(signal_data: dict[str, Any]) -> tuple[int, Any]:
        raw_seq = signal_data.get("signal_seq")
        if raw_seq not in (None, ""):
            try:
                return 0, int(str(raw_seq).strip())
            except (TypeError, ValueError):
                return 1, str(raw_seq).strip()

        raw_event_id = signal_data.get("event_id")
        if raw_event_id not in (None, ""):
            return 2, str(raw_event_id).strip()

        return 3, None

    @staticmethod
    def _signal_sort_key(signal: dict):
        return (
            signal["timestamp"],
            signal["sequence_rank"],
            signal["sequence_value"] if signal["sequence_value"] is not None else "",
            signal["file_order"],
            signal["line_number"],
        )

    @staticmethod
    def _compare_explicit_order(left: dict, right: dict) -> int | None:
        if left["sequence_rank"] == 3 or right["sequence_rank"] == 3:
            return None
        if left["sequence_rank"] != right["sequence_rank"]:
            return None
        if left["sequence_value"] == right["sequence_value"]:
            return None
        return -1 if left["sequence_value"] < right["sequence_value"] else 1

    @staticmethod
    def _is_transition_pair(left: dict, right: dict) -> bool:
        directions = {left.get("direction"), right.get("direction")}
        return "flat" in directions and any(direction in directions for direction in ("long", "short"))

    @staticmethod
    def _with_audit_fields(signal: dict, *, ordering_basis: str, prior_state_used: str | None):
        signal["ordering_basis"] = ordering_basis
        signal["prior_state_used"] = prior_state_used
        return signal

    def _normalize_pair_timestamps(self, ordered_pair, ordering_basis: str):
        raw_pair = sorted(ordered_pair, key=self._signal_sort_key)
        already_ordered = raw_pair == ordered_pair
        strictly_increasing = all(
            raw_pair[idx]["timestamp"] < raw_pair[idx + 1]["timestamp"]
            for idx in range(len(raw_pair) - 1)
        )
        if already_ordered and strictly_increasing:
            return ordered_pair

        base_time = min(signal["timestamp"] for signal in ordered_pair)
        for idx, signal in enumerate(ordered_pair):
            adjusted_time = base_time + timedelta(microseconds=idx * 1000)
            if signal["timestamp"] != adjusted_time:
                signal["timestamp"] = adjusted_time
                signal["timestamp_adjusted"] = True
                signal["adjustment_reason"] = ordering_basis
        return ordered_pair

    def _resolve_transition_pair(self, current: dict, next_signal: dict, prior_state: str | None):
        explicit_cmp = self._compare_explicit_order(current, next_signal)
        if explicit_cmp is not None:
            ordering_basis = "explicit_sequence"
            ordered_pair = [current, next_signal] if explicit_cmp <= 0 else [next_signal, current]
            return ordered_pair, ordering_basis, prior_state

        if prior_state == "open":
            ordering_basis = "stateful_close_then_open"
            flat_signal = current if current["direction"] == "flat" else next_signal
            position_signal = next_signal if flat_signal is current else current
            return [flat_signal, position_signal], ordering_basis, prior_state

        if prior_state == "flat":
            ordering_basis = "stateful_open_then_close"
            position_signal = current if current["direction"] != "flat" else next_signal
            flat_signal = next_signal if position_signal is current else current
            return [position_signal, flat_signal], ordering_basis, prior_state

        return [current, next_signal], "chronological", prior_state

    def _parse_signal_file(self, file_path, file_order, signals, symbol_dates):
        """Parse a signal file and update signals with the latest data."""
        if self.verbose:
            print(f"\nProcessing file: {file_path}")
        
        # First, collect all signals from the file
        all_signals = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_number, line in enumerate(f, start=1):
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

                leverage = self._parse_leverage(signal_data.get("leverage"), direction)
                sequence_rank, sequence_value = self._parse_explicit_sequence(signal_data)

                # Store the signal with all its data
                signal_entry = {
                    "symbol": symbol,
                    "original_symbol": original_symbol,
                    "direction": direction,
                    "depth": depth,
                    "leverage": leverage,
                    "price": price if price is not None and price > 0 else None,
                    "timestamp": line_timestamp,
                    "original_timestamp": line_timestamp.isoformat(),  # Preserve original timestamp
                    "raw_data": signal_data,  # Keep raw data for audit purposes
                    "file_order": file_order,
                    "file_name": os.path.basename(file_path),
                    "line_number": line_number,
                    "sequence_rank": sequence_rank,
                    "sequence_value": sequence_value,
                    "ordering_basis": "chronological",
                    "prior_state_used": None,
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
            symbol_signal_list.sort(key=self._signal_sort_key)
            
            # Handle race conditions for close timestamps
            processed_signals = self._handle_race_conditions(
                symbol,
                symbol_signal_list,
                self._resolve_prior_state(symbol, signals),
            )
            
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
                    "leverage": latest_signal.get("leverage"),
                    "price": latest_signal["price"],
                    "average_price": None,
                    "timestamp": latest_signal["timestamp"],
                    "audit": {
                        "original_timestamp": latest_signal["original_timestamp"],
                        "adjusted": latest_signal.get("timestamp_adjusted", False),
                        "adjustment_reason": latest_signal.get("adjustment_reason", None),
                        "ordering_basis": latest_signal.get("ordering_basis", "chronological"),
                        "prior_state_used": latest_signal.get("prior_state_used"),
                        "file_name": latest_signal.get("file_name"),
                        "line_number": latest_signal.get("line_number"),
                        "signal_seq": latest_signal["raw_data"].get("signal_seq"),
                        "event_id": latest_signal["raw_data"].get("event_id"),
                    }
                }
                
        return signals, symbol_dates

    def _handle_race_conditions(self, symbol, signal_list, prior_state):
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
        current_state = prior_state
        
        while i < len(signal_list):
            current = signal_list[i]
            
            # Only look for race conditions if current signal is involved in a position transition
            if current["direction"] in ["flat", "long", "short"]:
                # Look for the specific pattern: flat followed by position, or position followed by flat
                if i + 1 < len(signal_list):
                    next_signal = signal_list[i + 1]
                    time_diff = next_signal["timestamp"] - current["timestamp"]
                    
                    # Check if this is a position transition pattern within threshold
                    if time_diff <= CLOSE_THRESHOLD and self._is_transition_pair(current, next_signal):
                        transition_group, ordering_basis, prior_state_used = self._resolve_transition_pair(
                            current,
                            next_signal,
                            current_state,
                        )
                        transition_group = self._normalize_pair_timestamps(
                            transition_group,
                            ordering_basis,
                        )
                        if self.verbose:
                            print(
                                f"Resolved transition for {symbol}: basis={ordering_basis}, "
                                f"prior_state={prior_state_used}"
                            )
                        for signal in transition_group:
                            processed.append(
                                self._with_audit_fields(
                                    signal,
                                    ordering_basis=ordering_basis,
                                    prior_state_used=prior_state_used,
                                )
                            )
                            current_state = self._signal_state(signal) or current_state
                        i += 2
                        continue
            
            # No race condition detected, add signal as-is
            processed.append(
                self._with_audit_fields(
                    current,
                    ordering_basis=current.get("ordering_basis", "chronological"),
                    prior_state_used=current.get("prior_state_used"),
                )
            )
            current_state = self._signal_state(current) or current_state
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
                print("Reordering signals for proper position transition")
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
