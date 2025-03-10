import asyncio
import aiohttp
import ujson
import os
import argparse
from datetime import datetime, timedelta, UTC
from config.credentials import load_bittensor_credentials
import zipfile
import numpy as np
from math import sqrt
import logging
import ujson as json

# Configure logging with a more robust setup
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# Remove all handlers to ensure we don't add duplicates
for handler in logger.handlers[:]:
    logger.removeHandler(handler)
# Prevent propagation to root logger
logger.propagate = False
# Add our handler
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%Y-%m-%d %I:%M:%S %p')
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)

class BittensorProcessor:
    SIGNAL_SOURCE = "bittensor"
    RAW_SIGNALS_DIR = "raw_signals/bittensor"
    ARCHIVE_DIR = "raw_signals/bittensor/archive"
    SIGNAL_FILE_PREFIX = "bittensor_signal"
    SIGNAL_FREQUENCY = 0.5  # seconds between signal preparations
    ASSET_MAPPING_CONFIG = "asset_mapping_config.json"
    PROCESSOR_CONFIG = "bittensor_processor_config.json"
    
    def __init__(self, *, enabled=True):
        self.credentials = load_bittensor_credentials()
        self.enabled = enabled
        self.miner_count_cache_filename = "miner_count_cache.txt"
        self.miner_count_cache_path = os.path.join(self.RAW_SIGNALS_DIR, self.miner_count_cache_filename)
        self.CORE_ASSET_MAPPING = self._load_asset_mapping()
        self._last_config_check = 0
        
        # Default configuration values
        self.min_trades = 10
        self.max_drawdown_threshold = -0.5
        self.min_profitable_rate = 0.6
        self.min_total_return = 0.0
        self.drawdown_exponent = 6
        self.sharpe_exponent = 2
        self.profitable_rate_exponent = 5
        self.position_count_divisor = 5
        self.min_trades_per_asset = 0
        self.max_trade_age_days = 14
        self.leverage_limit_crypto = 0.5
        
        # Load configuration from file if it exists
        self._load_processor_config()

    def _load_asset_mapping(self):
        """Load asset mapping from configuration file."""
        try:
            with open(self.ASSET_MAPPING_CONFIG, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get(self.SIGNAL_SOURCE, {})
        except (FileNotFoundError, json.JSONDecodeError):
            # Return default mapping if config file doesn't exist or is invalid
            return {
                "BTCUSD": "BTCUSDT",
                "ETHUSD": "ETHUSDT",
            }
        
    def reload_asset_mapping(self):
        """Reload asset mapping configuration."""
        self.CORE_ASSET_MAPPING = self._load_asset_mapping()
        
    def _should_reload_config(self):
        """Check if the processor configuration file has been modified."""
        try:
            if not os.path.exists(self.PROCESSOR_CONFIG):
                return False
            
            current_mtime = os.path.getmtime(self.PROCESSOR_CONFIG)
            if current_mtime > self._last_config_check:
                self._last_config_check = current_mtime
                return True
                
            return False
        except Exception as e:
            logger.error(f"Error checking processor config modification time: {e}")
            return False

    async def prepare_signals(self, verbose=False):
        """Fetch, process, and store signals from ranked miners."""
        # Check for configuration changes
        if self._should_reload_config():
            logger.info("Processor configuration file changed, reloading settings...")
            self._load_processor_config()
        
        # Reload asset mapping configuration before processing signals
        self.reload_asset_mapping()
        
        # Get raw signals and rank miners
        positions_data = await self._fetch_raw_signals()
        if not positions_data:
            logger.error("Failed to fetch miner data")
            return {}

        # Check key count
        previous_key_count = self.fetch_key_count()
        current_key_count = len(positions_data)
        if previous_key_count >= 0 and (current_key_count <= 50 or abs(current_key_count - previous_key_count) > 10):
            logger.error("The number of keys fetched is not within the expected tolerance.")
            return {}
        self.store_key_count(current_key_count)

        # Get rankings using all available assets
        assets_to_trade = list(self.CORE_ASSET_MAPPING.keys())
        rankings, ranked_miners = self.rank_miners(positions_data, assets_to_trade)
        if not ranked_miners:
            logger.error("No qualified miners found")
            return {}

        # Store miner metrics for later reference
        miner_metrics = {}
        if verbose:
            print("\n=== Qualified Miners ===")
            for rank, miner in enumerate(ranked_miners, 1):
                miner_metrics[miner['hotkey']] = {
                    'rank': rank,
                    'total_score': miner['total_score'],
                    'profitability': miner['percentage_profitable']*100,
                    'sharpe_ratio': miner['sharpe_ratio']
                }
                #print(f"\nRank #{rank} - Miner: {miner['hotkey']}")
                #print(f"    Total Score: {miner['total_score']:.4f}")
                #print(f"    Profitability: {miner['percentage_profitable']*100:.2f}%")
                #print(f"    Sharpe Ratio scaled: {miner['sharpe_ratio']:.4f}")

        # Calculate gradient allocation weights for miners
        allocations = self._calculate_gradient_allocation(len(ranked_miners))
        #if verbose:
            #print("\n=== Gradient Allocations ===")
            #for rank, weight in allocations.items():
            #    print(f"Rank {rank}: {weight:.4f}")

        # Initialize asset depths
        asset_depths = {asset: [] for asset in assets_to_trade}

        # Get current processing timestamp
        current_timestamp = int(datetime.now(UTC).timestamp() * 1000)

        # Get last known signals to compare for changes
        last_signals = {}
        for asset in self.CORE_ASSET_MAPPING.values():
            last_signal = self.fetch_last_signal(asset)
            if last_signal:
                last_signals[asset] = last_signal

        # Process each ranked miner's positions
        for rank, miner_data in enumerate(ranked_miners, 1):
            miner_hotkey = miner_data['hotkey']
            miner_weight = allocations[rank]  # Get miner's weight based on rank
            miner_positions = positions_data[miner_hotkey]['positions']

            if verbose and any(position['trade_pair'][0] in assets_to_trade for position in miner_positions):
                metrics = miner_metrics[miner_hotkey]
                print(f"\nRank #{metrics['rank']} - Miner: {miner_hotkey}")
                print(f"    Total Score: {metrics['total_score']:.4f}")
                print(f"    Profitability: {metrics['profitability']:.2f}%")
                print(f"    Sharpe Ratio scaled: {metrics['sharpe_ratio']:.4f}")
                print(f"    Weight: {miner_weight:.4f}")

            # Group positions by asset
            for position in miner_positions:
                asset = position['trade_pair'][0]
                if asset not in assets_to_trade:
                    continue

                # Calculate net leverage for this position
                orders = position.get("orders", [])
                net_pos, avg_price = self._compute_net_position_and_average_price(orders)
                
                if net_pos != 0:  # Only include non-zero positions
                    weighted_leverage = net_pos * miner_weight
                    
                    if verbose:
                        print(f"    Position in {asset}:")
                        print(f"        Net Position: {net_pos:.4f}")
                        print(f"        Average Price: ${avg_price:.2f}")
                        print(f"        Trade Count: {len(orders)}")
                        print(f"        Weighted Leverage: {weighted_leverage:.4f}")
                    
                    asset_depths[asset].append({
                        'miner': miner_hotkey,
                        'weight': miner_weight,
                        'leverage': net_pos,
                        'price': avg_price,
                        'trade_count': len(orders)
                    })

        # Combine miner positions into final signals
        signals = {}
        if verbose:
            print("\n=== Final Combined Signals ===")
            
        for asset, positions in asset_depths.items():
            if not positions:
                continue

            # Calculate weighted average leverage and price
            total_weighted_leverage = sum(pos['leverage'] * pos['weight'] for pos in positions)
            
            # Cap the total leverage at 1.0 or -1.0
            capped_leverage = max(min(total_weighted_leverage, 1.0), -1.0)
            
            # Calculate weighted average price
            total_weight = sum(abs(pos['leverage'] * pos['weight']) for pos in positions)
            weighted_price = (
                sum(pos['price'] * abs(pos['leverage'] * pos['weight']) for pos in positions) / total_weight
                if total_weight > 0 else 0
            )

            # Use the mapped symbol for storage
            mapped_asset = self.CORE_ASSET_MAPPING[asset]
            
            # Check if signal has changed
            last_signal = last_signals.get(mapped_asset, {})
            last_depth = last_signal.get('depth', 0.0)
            last_price = last_signal.get('price', 0.0)
            
            # Only update timestamp if depth or price has changed
            timestamp = current_timestamp if (
                abs(capped_leverage - last_depth) > 0 or  # Depth changed
                abs(weighted_price - last_price) > 0  # Price changed
            ) else last_signal.get('timestamp', current_timestamp)
            
            signals[mapped_asset] = {
                'depth': capped_leverage,
                'price': weighted_price,
                'timestamp': timestamp
            }
            
            if verbose:
                print(f"\n{asset} -> {mapped_asset}:")
                print(f"  Final Depth: {capped_leverage:.4f}")
                print(f"  Average Price: ${weighted_price:.2f}")
                print(f"  Latest Update: {datetime.fromtimestamp(timestamp/1000, UTC).strftime('%Y-%m-%d %I:%M:%S %p')} UTC")
                print(f"  Contributing Miners: {len(positions)}")
                if positions:  # Only show contributions if there are any
                    print("  Individual Contributions:")
                    for pos in positions:
                        print(f"    {pos['miner']}: leverage={pos['leverage']:.4f}, "
                              f"weight={pos['weight']:.4f}, trades={pos['trade_count']}")

        # Ensure all mapped assets have an entry
        for mapped_asset in self.CORE_ASSET_MAPPING.values():
            if mapped_asset not in signals:
                # Get the last known signal for this asset
                last_signal = last_signals.get(mapped_asset, {})
                signals[mapped_asset] = {
                    'depth': 0.0, # Closed position
                    'price': last_signal.get('price', 0.0),
                    'timestamp': last_signal.get('timestamp', current_timestamp)  # Keep old timestamp if no change
                }

        # Store signals to disk and clean up old files
        self._store_signal_on_disk(signals)
        self._archive_old_files()
        
        return signals

    def fetch_signals(self):
        """Read and combine signals from stored files, keeping only the latest for each asset."""
        # Initialize with all core assets at zero depth using mapped symbols
        latest_signals = {
            self.CORE_ASSET_MAPPING[asset]: {
                'depth': 0.0,
                'price': 0.0,
                'timestamp': 0
            } for asset in self.CORE_ASSET_MAPPING.keys()
        }
        
        # Ensure directory exists
        if not os.path.exists(self.RAW_SIGNALS_DIR):
            logger.warning(f"Signal directory {self.RAW_SIGNALS_DIR} does not exist")
            return latest_signals
            
        # Read all signal files
        signal_files = sorted([
            f for f in os.listdir(self.RAW_SIGNALS_DIR) 
            if f.startswith(self.SIGNAL_FILE_PREFIX) and f.endswith('.json')
        ], reverse=True)  # Sort newest first
        
        #logger.info(f"Found {len(signal_files)} signal files to process")
        
        for filename in signal_files:
            file_path = os.path.join(self.RAW_SIGNALS_DIR, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    signals = ujson.load(f)
                    
                # Update latest signals based on timestamp
                for asset, signal in signals.items():
                    if asset in latest_signals:
                        current_timestamp = latest_signals[asset]['timestamp']
                        new_timestamp = signal['timestamp']
                        
                        if new_timestamp > current_timestamp:
                            latest_signals[asset] = {
                                'depth': signal['depth'],
                                'price': signal['price'],
                                'timestamp': new_timestamp
                            }
                            logger.debug(
                                f"Updated {asset} signal from {filename}: "
                                f"depth={signal['depth']:.4f}, "
                                f"price=${signal['price']:.2f}, "
                                f"time={datetime.fromtimestamp(new_timestamp/1000, UTC).strftime('%Y-%m-%d %I:%M:%S %p')} UTC"
                            )
                            
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Error reading signal file {filename}: {e}")
                continue
        
        # Log final signals
        logger.info(f"Final signals after processing all {len(signal_files)} signal files:")
        for asset, signal in latest_signals.items():
            logger.info(
                "%s: depth=%.4f, price=$%.2f, time=%s UTC",
                asset, signal['depth'], signal['price'],
                datetime.fromtimestamp(signal['timestamp']/1000, UTC).strftime('%Y-%m-%d %I:%M:%S %p')
            )
            
        return latest_signals

    async def run_signal_loop(self):
        """Main loop for preparing signals at regular intervals."""
        logger.info("Starting Bittensor signal processor loop")
        while True:
            try:
                logger.info("Fetching signals from Bittensor SN8 API...")
                signals = await self.prepare_signals(verbose=True)
                #if signals:
                #    logger.info(f"Successfully prepared signals for {len(signals)} assets")
                #else:
                #    logger.warning("No signals were prepared in this cycle")
                logger.info(f"Signal preparation complete. There were {len(signals)} signals prepared. Waiting {self.SIGNAL_FREQUENCY} seconds for next cycle...")
                await asyncio.sleep(self.SIGNAL_FREQUENCY)
            except Exception as e:
                logger.error(f"Error in signal loop: {e}")
                logger.info("Retrying in 5 seconds...")
                await asyncio.sleep(5)  # Short sleep on error before retry

    async def _fetch_raw_signals(self):
        """Fetch raw signals from the API."""
        headers = {'Content-Type': 'application/json'}
        data = {'api_key': self.credentials.bittensor_sn8.api_key}

        async with aiohttp.ClientSession() as session:
            async with session.get(self.credentials.bittensor_sn8.endpoint, json=data, headers=headers) as response:
                if response.status == 200:
                    return await response.json(loads=ujson.loads)
                print(f"Failed to fetch data: {response.status}")
                return None

    def _store_signal_on_disk(self, data):
        """Store raw signal data to disk using atomic operations."""
        if not os.path.exists(self.RAW_SIGNALS_DIR):
            os.makedirs(self.RAW_SIGNALS_DIR)
        
        # Create temp directory if it doesn't exist
        temp_dir = os.path.join(self.RAW_SIGNALS_DIR, 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        
        # Create filenames
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d")
        filename = f"{self.SIGNAL_FILE_PREFIX}_{timestamp}.json"
        temp_path = os.path.join(temp_dir, filename)
        final_path = os.path.join(self.RAW_SIGNALS_DIR, filename)
        
        # Write to temporary file first
        with open(temp_path, 'w', encoding='utf-8') as f:
            ujson.dump(data, f, indent=4)
            
        # Atomic rename operation
        os.replace(temp_path, final_path)

    def _process_signals(self, data, top_miners=None, mapped_only=True):
        """Process raw signals into standardized format."""
        if data is None:
            return []

        # Sort miners by all_time_returns and select the top if specified
        sorted_miners = sorted(data.items(), key=lambda x: x[1].get('all_time_returns', 0), reverse=True)
        if top_miners:
            sorted_miners = sorted_miners[:top_miners]

        # Get allocation for each miner based on rank
        allocations = self._calculate_gradient_allocation(len(sorted_miners))

        # Initialize asset tracking dictionaries
        asset_depths = {}
        miner_tracker = []  # Track miners that have been processed

        # Iterate through the ranked miners and apply gradient allocations
        for rank, (miner_hotkey, miner_positions) in enumerate(sorted_miners, start=1):

            # Skip if this asset has already been counted for this miner
            if miner_hotkey in miner_tracker:
                print(f"Skipping miner {miner_hotkey} as it has already been processed.")
                continue

            miner_tracker.append(miner_hotkey)  # Mark this asset as seen for this miner
            #print(f"Processing miner {miner_hotkey} at rank {rank}")

            allocation_weight = allocations[rank]

            for position_data in miner_positions.get('positions', []):

                # iterate all trade pairs and get the original symbol which has a mapping in CORE_ASSET_MAPPING
                original_symbol = next(
                    (
                        trade_pair
                        for trade_pair in position_data['trade_pair']
                        if trade_pair in self.CORE_ASSET_MAPPING
                    ),
                    None,
                )
                if mapped_only and not original_symbol:
                    #print(f"Skipping {original_symbol} as it is not mapped to a core asset.")
                    continue

                # Normalize the symbol to match core asset format
                symbol = self.CORE_ASSET_MAPPING[original_symbol]

                # add an entry for the symbol with the net from the miner
                if symbol not in asset_depths:
                    asset_depths[symbol] = []
                
                # Skip if the position has no net leverage or is closed
                if position_data["net_leverage"] == 0 or position_data["is_closed_position"]:
                    #print(f"Skipping {symbol} as it has no net leverage.")
                    continue
               
                net_pos, avg_price = self._compute_net_position_and_average_price(position_data["orders"])
                    
                capped_leverage = min(net_pos, self.leverage_limit_crypto)
                normalized_depth = (capped_leverage / self.leverage_limit_crypto) * allocation_weight
                
                latest_order_ms = max(order['processed_ms'] for order in position_data['orders'])
                latest_order_tstamp = datetime.fromtimestamp(latest_order_ms / 1000, UTC).strftime("%Y-%m-%d %H:%M:%S")
                    
                print(f"Miner {miner_hotkey} in {symbol} with {normalized_depth:.2%} depth of ${avg_price:.2f} at {latest_order_tstamp}")
                
                # Add the net position to the total depth
                for order in position_data["orders"]:                
                    asset_depths[symbol].append(
                        {
                            "order_type": order["order_type"],
                            "leverage": order["leverage"] * allocation_weight,
                            "price": order["price"],
                            "processed_ms": order["processed_ms"],
                            "original_symbol": original_symbol,
                        }
                    )


        # Prepare final results with capped depth and weighted average price
        results = []

        for symbol, entries in asset_depths.items():
            # Re-calculate net position and average price
            net_pos, avg_price = self._compute_net_position_and_average_price(entries)

            # Get the last entry date for the symbol
            last_entry_ms = max(entry["processed_ms"] for entry in entries)
            last_entry_date = datetime.fromtimestamp(last_entry_ms / 1000, UTC).strftime("%Y-%m-%d %H:%M:%S")

            # Get the latest recorded price for the symbol using the last entry date
            last_price = next(
                (
                    entry["price"]
                    for entry in entries
                    if entry["processed_ms"] == last_entry_ms
                ),
                None,
            )

            # get a unique list of original symbols
            original_symbols = list({entry["original_symbol"] for entry in entries})

            results.append(
                {
                    "symbol": symbol,
                    "original_symbols": original_symbols,
                    "depth": net_pos,
                    "price": last_price,
                    "average_price": avg_price,
                    "timestamp": last_entry_date,
                }
            )

        return results

    def _calculate_gradient_allocation(self, max_rank):
        """Calculate gradient allocation weights."""
        # Total weight is the sum of all rank values
        total_weight = sum(max_rank + 1 - rank for rank in range(1, max_rank + 1))
        
        # Create a dictionary with rank as key and allocation as the fractional value
        allocations = {}
        for rank in range(1, max_rank + 1):
            inverted_rank = max_rank + 1 - rank
            allocations[rank] = inverted_rank / total_weight
        return allocations

    def _compute_net_position_and_average_price(self, orders):
        """Compute net position and average price from orders."""
        # Sort chronologically:
        sorted_orders = sorted(orders, key=lambda x: x["processed_ms"])

        net_position = 0.0
        cost_basis   = 0.0  # Weighted average cost of the net_position
        
        # if any orders are flat, we will return with zero net position and zero cost basis
        if any(order["order_type"].upper().strip() == "FLAT" for order in sorted_orders):
            #print("Found FLAT order. Resetting net position and cost basis.")
            return net_position, cost_basis

        for order in sorted_orders:
            # Skip zero-sized orders, but DO NOT skip FLAT orders anymore!
            if abs(order["leverage"]) == 0:
                continue

            qty   = order["leverage"]
            price = order["price"]

            if net_position * qty > 0:
                # Same direction => Weighted average
                new_position = net_position + qty
                cost_basis   = (net_position * cost_basis + qty * price) / new_position
                net_position = new_position
            else:
                # Opposite direction => offset or flip
                if abs(qty) > abs(net_position):
                    # Flip from net_position to leftover
                    leftover     = qty + net_position
                    net_position = leftover
                    cost_basis   = price  # brand-new position's cost basis
                else:
                    # Partial or full close of existing position
                    net_position += qty
                    if abs(net_position) < 1e-15:
                        # fully closed
                        net_position = 0.0
                        cost_basis   = 0.0  # or keep if you have a special reason not to reset

        return net_position, cost_basis

    def _archive_old_files(self, days=3):
        """Archive files older than specified days."""
        if not os.path.exists(self.ARCHIVE_DIR):
            os.makedirs(self.ARCHIVE_DIR)
            
        cutoff = datetime.now(UTC) - timedelta(days=days)
        
        for filename in os.listdir(self.RAW_SIGNALS_DIR):
            # Only process bittensor signal files
            if not filename.startswith(f'{self.SIGNAL_FILE_PREFIX}_') or filename == 'archive' or filename.startswith('.'):
                continue
            
            file_path = os.path.join(self.RAW_SIGNALS_DIR, filename)
            if not os.path.isfile(file_path):
                continue
            
            file_time = datetime.fromtimestamp(os.path.getmtime(file_path), UTC)
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

    def filter_positions_by_assets(self, data, asset_list):
        """Filter positions to include only those with specified assets."""
        filtered_data = {}
        for miner, details in data.items():
            if details["thirty_day_returns"] <= 0:
                continue
            
            if details["all_time_returns"] <= 0:
                continue
            
            profitable_trades = 0
            total_trades = 0
            asset_trades = {}
            latest_trade = 0
            for position in details["positions"]:
                if position["trade_pair"][0] not in asset_list:
                    continue
                
                asset_trades[position["trade_pair"][0]] = asset_trades.get(position["trade_pair"][0], 0) + 1
                
                if position["is_closed_position"]:
                    return_at_close = position["return_at_close"] - 1
                    if return_at_close > 0:
                        profitable_trades += 1
                    latest_trade = max(latest_trade, position["close_ms"])
                    total_trades += 1
            
            if self.min_trades_per_asset > 0:
                skip = False
                for asset in asset_list:
                    if asset_trades.get(asset, 0) < self.min_trades_per_asset:
                        skip = True
                        break
                if skip:
                    continue
            
            if self.max_trade_age_days < float('inf'):
                if latest_trade < datetime.now(UTC).timestamp() * 1000 - self.max_trade_age_days * 24 * 60 * 60 * 1000:
                    continue
            
            filtered_positions = [
                pos for pos in details["positions"]
                if pos["trade_pair"][0] in asset_list
            ]
            if filtered_positions:
                filtered_data[miner] = {**details, "positions": filtered_positions}
        return filtered_data

    async def get_ranked_miners(self, assets_to_trade=None):
        """Fetch and rank miners."""
        positions_data = await self._fetch_raw_signals()
        if positions_data is None:
            logger.error("Failed to fetch miner data")
            return None, None
        
        # Check key count
        previous_key_count = self.fetch_key_count()
        current_key_count = len(positions_data)
        if previous_key_count >= 0 and (current_key_count <= 50 or abs(current_key_count - previous_key_count) > 10):
            raise ValueError("The number of keys fetched is not within the expected tolerance.")
        self.store_key_count(current_key_count)
        
        # Calculate rankings
        rankings, ranked_miners = self.rank_miners(positions_data, assets_to_trade)
        
        # Format and display results
        formatted_results = self.format_miner_results(ranked_miners, positions_data, assets_to_trade)
        self.display_ranked_miners(formatted_results)
        
        return rankings, ranked_miners

    def calculate_miner_scores(self, data):
        """Calculate scores for each miner based on their trading performance."""
        metrics_data = []
        
        for hotkey, miner in data.items():
            if not miner['positions']:
                continue
                
            position_returns = []
            profitable_trades = 0
            total_trades = 0
            
            # Calculate max drawdown from filtered positions
            max_drawdown = self.calculate_max_drawdown_from_positions(miner['positions'])
            
            # Skip miners with extreme drawdowns
            if max_drawdown < self.max_drawdown_threshold:
                continue
            
            # Process each position for returns and profitability
            for position in miner['positions']:
                if position['is_closed_position']:
                    return_at_close = position['return_at_close'] - 1
                    position_returns.append(return_at_close)
                    if return_at_close > 0:
                        profitable_trades += 1
                else:
                    current_return = position['current_return'] - 1
                    position_returns.append(current_return)
                    if current_return > 0:
                        profitable_trades += 1
                total_trades += 1
            
            # Apply minimum trade requirement
            if total_trades < self.min_trades:
                continue
                
            percentage_profitable = profitable_trades / total_trades
            if percentage_profitable < self.min_profitable_rate:
                continue
                
            # Calculate metrics
            sharpe_ratio = self.calculate_sharpe_ratio(position_returns)
            consistency_score = self.get_trade_consistency_score(miner)
            position_count = total_trades
            total_return = sum(position_returns)
            
            # Skip if below minimum return
            if total_return <= self.min_total_return:
                continue
            
            metrics_data.append({
                'hotkey': hotkey,
                'metrics': {
                    'max_drawdown': max_drawdown,
                    'sharpe_ratio': sharpe_ratio,
                    'total_return': total_return,
                    'percentage_profitable': percentage_profitable,
                    'position_count': position_count,
                    'consistency_score': consistency_score
                }
            })
        
        if not metrics_data:
            return []
        
        # Calculate percentile ranks for metrics that should be normalized
        all_metrics = [m['metrics'] for m in metrics_data]
        sharpe_percentiles = self.normalize_to_percentile([m['sharpe_ratio'] for m in all_metrics])
        position_count_percentiles = self.normalize_to_percentile([m['position_count'] for m in all_metrics])
        consistency_percentiles = self.normalize_to_percentile([m['consistency_score'] for m in all_metrics])
        
        # Create normalized scores
        normalized_metrics = []
        for idx, miner_data in enumerate(metrics_data):
            metrics = miner_data['metrics']
            
            # Convert drawdown to positive score and apply penalty
            drawdown_score = 1.0 + metrics['max_drawdown']
            drawdown_score = drawdown_score ** 2
            
            # Convert total return to absolute value
            return_score = 1.0 + metrics['total_return']
            
            # Calculate position count bonus
            position_count_bonus = np.log1p(metrics['position_count']) / self.position_count_divisor
            
            normalized = {
                'hotkey': miner_data['hotkey'],
                'max_drawdown': float(drawdown_score),
                'total_return': float(return_score),
                'sharpe_ratio': float(sharpe_percentiles[idx]),
                'percentage_profitable': float(metrics['percentage_profitable']),
                'position_count': float(position_count_percentiles[idx]),
                'consistency_score': float(consistency_percentiles[idx])
            }
            
            # Calculate total score with configured weights
            normalized['total_score'] = float(
                normalized['max_drawdown']**self.drawdown_exponent +
                normalized['sharpe_ratio']**self.sharpe_exponent +
                normalized['total_return'] +
                normalized['percentage_profitable']**self.profitable_rate_exponent +
                normalized['position_count'] * position_count_bonus +
                normalized['consistency_score']
            )
            
            normalized_metrics.append(normalized)
        
        return sorted(normalized_metrics, key=lambda x: x['total_score'], reverse=True)

    def rank_miners(self, positions_data, assets_to_trade=None):
        """Rank miners by their total score."""
        # Filter by assets
        if assets_to_trade:
            positions_data = self.filter_positions_by_assets(positions_data, assets_to_trade)
        
        # Calculate scores and sort miners
        ranked_miners = self.calculate_miner_scores(positions_data)
        
        # Build rankings dictionary
        rankings = {miner['hotkey']: rank + 1 for rank, miner in enumerate(ranked_miners)}
        
        return rankings, ranked_miners

    def normalize_metric(self, name, value, min_value, max_value):
        """Normalize a metric to a 0-1 scale."""
        if max_value - min_value == 0:
            return 0
        normalized = (value - min_value) / (max_value - min_value)
        return normalized

    def calculate_sharpe_ratio(self, position_returns):
        """Calculate the Sharpe Ratio for a series of returns."""
        if len(position_returns) < 2:
            return 0
        returns = np.array(position_returns)
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        return mean_return / std_return if std_return != 0 else 0

    def calculate_max_drawdown_from_orders(self, orders):
        """Calculate max drawdown for a position considering leverage and price changes."""
        cumulative_leverage = 0
        weighted_sum_price = 0
        max_drawdown = 0
        current_price = None

        for order in orders:
            if not isinstance(order, dict):
                raise ValueError("Each order must be a dictionary")

            price = order.get("price", 0)
            leverage = order.get("leverage", 0)

            if leverage == 0 or price == 0:
                continue

            cumulative_leverage += leverage
            if cumulative_leverage == 0:
                continue
            
            weighted_sum_price += leverage * price
            average_price = weighted_sum_price / cumulative_leverage
            current_price = price

            if cumulative_leverage > 0:  # Long position
                price_drawdown = (current_price - average_price) / average_price
                account_drawdown = price_drawdown * abs(cumulative_leverage)
            else:  # Short position
                price_drawdown = (average_price - current_price) / average_price
                account_drawdown = price_drawdown * abs(cumulative_leverage)

            max_drawdown = min(max_drawdown, -abs(account_drawdown))

        return max_drawdown

    def calculate_max_drawdown_from_positions(self, positions):
        """Calculate the largest max drawdown from all positions."""
        max_drawdown = 0
        for position in positions:
            orders = position.get("orders", [])
            drawdown = self.calculate_max_drawdown_from_orders(orders)
            max_drawdown = min(max_drawdown, drawdown)
        return max_drawdown

    def get_trade_consistency_score(self, miner):
        """Calculate consistency based on the standard deviation of trade intervals."""
        positions = sorted(miner['positions'], key=lambda pos: pos['open_ms'])
        if len(positions) < 2:
            return 0

        intervals = [
            positions[i]['open_ms'] - positions[i - 1]['close_ms']
            for i in range(1, len(positions))
        ]
        
        mean_interval = sum(intervals) / len(intervals)
        std_interval = sqrt(sum((x - mean_interval) ** 2 for x in intervals) / len(intervals))
        
        return 1 - (std_interval / mean_interval if mean_interval != 0 else 0)

    def get_position_count_score(self, n_positions, max_positions):
        """Calculate position count score using logarithmic scaling."""
        return np.log1p(n_positions) / np.log1p(max_positions)

    def normalize_to_percentile(self, values, reverse=False):
        """Normalize values to percentile ranks (0-1)."""
        if not values:
            return []
        
        sorted_with_idx = sorted(enumerate(values), key=lambda x: x[1], reverse=not reverse)
        n = len(sorted_with_idx)
        
        ranks = [0] * n
        for rank, (idx, _) in enumerate(sorted_with_idx):
            ranks[idx] = 1.0 - (rank / (n - 1) if n > 1 else 0)
        
        return ranks

    def calculate_asset_metrics(self, positions, asset):
        """Calculate metrics for a specific asset from positions."""
        asset_positions = [p for p in positions if p["trade_pair"][0] == asset]
        
        if not asset_positions:
            return None
            
        total_trades = len(asset_positions)
        total_return = sum(
            (p["return_at_close"] - 1) if p["is_closed_position"] 
            else (p["current_return"] - 1) 
            for p in asset_positions
        )
        
        total_entries = sum(len(p.get("orders", [])) for p in asset_positions)
        avg_entries = total_entries / total_trades if total_trades > 0 else 0
        
        max_drawdown = self.calculate_max_drawdown_from_positions(asset_positions)
        
        return {
            "total_trades": total_trades,
            "total_return": total_return,
            "avg_entries": avg_entries,
            "max_drawdown": max_drawdown
        }

    def format_miner_results(self, ranked_miners, positions_data, assets_to_trade):
        """Format miner results in a clean, readable way."""
        formatted_results = []
        
        for miner in ranked_miners:
            hotkey = miner['hotkey']
            scores = {
                'total_score': miner['total_score'],
                'sharpe_ratio': miner['sharpe_ratio'],
                'percentage_profitable': miner['percentage_profitable'] * 100,  # Convert to percentage
                'consistency_score': miner['consistency_score']
            }
            
            asset_metrics = {}
            for asset in assets_to_trade:
                positions = [p for p in positions_data[hotkey]['positions'] if p["trade_pair"][0] == asset]
                metrics = self.calculate_asset_metrics(positions, asset)
                if metrics:
                    # Calculate per-asset profitable trade percentage
                    profitable_trades = sum(
                        1 for p in positions 
                        if (p["is_closed_position"] and p["return_at_close"] > 1) or 
                           (not p["is_closed_position"] and p["current_return"] > 1)
                    )
                    metrics["profitable_percentage"] = (profitable_trades / len(positions)) * 100 if positions else 0
                    asset_metrics[asset] = metrics
            
            formatted_results.append({
                'hotkey': hotkey,
                'scores': scores,
                'asset_metrics': asset_metrics
            })
        
        return formatted_results

    def display_ranked_miners(self, formatted_results):
        """Display the formatted results in a clean, readable way."""
        for rank, result in enumerate(formatted_results, 1):
            print("\n" + "="*80)
            print(f"Rank #{rank} - Miner: {result['hotkey']}")
            print("-"*80)
            
            scores = result['scores']
            print("Overall Scores:")
            print(f"  Total Score: {scores['total_score']:.4f}")
            print(f"  Sharpe Ratio Rank: {scores['sharpe_ratio']:.4f}")
            print(f"  Trade Profitability: {scores['percentage_profitable']:.2f}%")
            print(f"  Consistency Score: {scores['consistency_score']:.4f}")
            
            print("\nPer-Asset Metrics:")
            for asset, metrics in result['asset_metrics'].items():
                print(f"\n  {asset}:")
                print(f"    Trades: {metrics['total_trades']}")
                print(f"    Profitable: {metrics['profitable_percentage']:.2f}%")
                print(f"    Max Drawdown: {(1 + metrics['max_drawdown'])*100:.2f}%")
                print(f"    Avg Entries/Position: {metrics['avg_entries']:.2f}")
                print(f"    Total Return: {(1 + metrics['total_return'])*100:.2f}%")

    def store_key_count(self, current_key_count):
        """Store the number of keys to a cache file."""
        with open(self.miner_count_cache_path, 'w', encoding='utf-8') as f:
            f.write(str(current_key_count))
        
    def fetch_key_count(self):
        """Fetch the number of keys from the cache file."""
        if not os.path.exists(self.miner_count_cache_path):
            return -1
        with open(self.miner_count_cache_path, 'r', encoding='utf-8') as f:
            return int(f.read())

    def fetch_last_signal(self, asset):
        """Fetch the last known signal for an asset from stored files."""
        if not os.path.exists(self.RAW_SIGNALS_DIR):
            return None
            
        # Get all signal files sorted by date (newest first)
        signal_files = sorted([
            f for f in os.listdir(self.RAW_SIGNALS_DIR) 
            if f.startswith(self.SIGNAL_FILE_PREFIX) and f.endswith('.json')
        ], reverse=True)
        
        # Look through files until we find the last signal for this asset
        for filename in signal_files:
            file_path = os.path.join(self.RAW_SIGNALS_DIR, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    signals = ujson.load(f)
                    if asset in signals:
                        return signals[asset]
            except (json.JSONDecodeError, KeyError):
                continue
                
        return None

    def _load_processor_config(self):
        """Load processor configuration from file or use defaults."""
        try:
            with open(self.PROCESSOR_CONFIG, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                self.min_trades = config_data.get('min_trades', self.min_trades)
                self.max_drawdown_threshold = config_data.get('max_drawdown_threshold', self.max_drawdown_threshold)
                self.min_profitable_rate = config_data.get('min_profitable_rate', self.min_profitable_rate)
                self.min_total_return = config_data.get('min_total_return', self.min_total_return)
                self.drawdown_exponent = config_data.get('drawdown_exponent', self.drawdown_exponent)
                self.sharpe_exponent = config_data.get('sharpe_exponent', self.sharpe_exponent)
                self.profitable_rate_exponent = config_data.get('profitable_rate_exponent', self.profitable_rate_exponent)
                self.position_count_divisor = config_data.get('position_count_divisor', self.position_count_divisor)
                self.min_trades_per_asset = config_data.get('min_trades_per_asset', self.min_trades_per_asset)
                self.max_trade_age_days = config_data.get('max_trade_age_days', self.max_trade_age_days)
                self.leverage_limit_crypto = config_data.get('leverage_limit_crypto', self.leverage_limit_crypto)
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # Use default values if file doesn't exist or is invalid

    def save_processor_config(self):
        """Save current processor configuration to file."""
        config_data = {
            'min_trades': self.min_trades,
            'max_drawdown_threshold': self.max_drawdown_threshold,
            'min_profitable_rate': self.min_profitable_rate,
            'min_total_return': self.min_total_return,
            'drawdown_exponent': self.drawdown_exponent,
            'sharpe_exponent': self.sharpe_exponent,
            'profitable_rate_exponent': self.profitable_rate_exponent,
            'position_count_divisor': self.position_count_divisor,
            'min_trades_per_asset': self.min_trades_per_asset,
            'max_trade_age_days': self.max_trade_age_days,
            'leverage_limit_crypto': self.leverage_limit_crypto
        }
        with open(self.PROCESSOR_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4)

    def configure(self):
        """Interactive configuration of processor parameters."""
        print("\nBittensor Processor Configuration")
        print("================================")
        
        # Filtering thresholds
        print("\nFiltering Thresholds:")
        self.min_trades = int(input(f"Minimum trades required ({self.min_trades}): ") or self.min_trades)
        self.max_drawdown_threshold = float(input(f"Maximum drawdown threshold ({self.max_drawdown_threshold}): ") or self.max_drawdown_threshold)
        self.min_profitable_rate = float(input(f"Minimum profitable rate ({self.min_profitable_rate}): ") or self.min_profitable_rate)
        self.min_total_return = float(input(f"Minimum total return ({self.min_total_return}): ") or self.min_total_return)
        
        # Scoring weights
        print("\nScoring Weights:")
        self.drawdown_exponent = int(input(f"Drawdown exponent ({self.drawdown_exponent}): ") or self.drawdown_exponent)
        self.sharpe_exponent = int(input(f"Sharpe ratio exponent ({self.sharpe_exponent}): ") or self.sharpe_exponent)
        self.profitable_rate_exponent = int(input(f"Profitable rate exponent ({self.profitable_rate_exponent}): ") or self.profitable_rate_exponent)
        self.position_count_divisor = int(input(f"Position count divisor ({self.position_count_divisor}): ") or self.position_count_divisor)
        
        # Asset filtering
        print("\nAsset Filtering:")
        self.min_trades_per_asset = int(input(f"Minimum trades per asset ({self.min_trades_per_asset}): ") or self.min_trades_per_asset)
        self.max_trade_age_days = int(input(f"Maximum trade age in days ({self.max_trade_age_days}): ") or self.max_trade_age_days)
        
        # Trading limits
        print("\nTrading Limits:")
        self.leverage_limit_crypto = float(input(f"Leverage limit for crypto ({self.leverage_limit_crypto}): ") or self.leverage_limit_crypto)
        
        # Save configuration
        self.save_processor_config()
        print("\nConfiguration saved successfully!")

    def add_arguments(self, parser):
        """Add processor-specific arguments to argument parser."""
        parser.add_argument('--config', action='store_true',
                          help='Configure Bittensor processor parameters')

# Example standalone usage
if __name__ == '__main__':
    # Use the keys from CORE_ASSET_MAPPING
    #assets_to_trade = list(BittensorProcessor.CORE_ASSET_MAPPING.keys())
    #processor = BittensorProcessor(enabled=True)
    #rankings, ranked_miners = asyncio.run(processor.get_ranked_miners(assets_to_trade))
    #if rankings is None:
    #    print("Failed to get rankings")
    #    exit(1)
    
    #processor = BittensorProcessor(enabled=True)
    #resulting_signals = asyncio.run(processor.prepare_signals(verbose=False))
    #resulting_signals = processor.fetch_signals()
    #print(resulting_signals)
    
    parser = argparse.ArgumentParser(description='Bittensor Signal Processor')
    processor = BittensorProcessor(enabled=True)
    processor.add_arguments(parser)
    args = parser.parse_args()
    
    if args.config:
        processor.configure()
    else:
        # Initialize processor and run the signal loop
        asyncio.run(processor.run_signal_loop())