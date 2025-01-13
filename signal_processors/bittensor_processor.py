import asyncio
import aiohttp
import ujson
import os
from datetime import datetime
from config.credentials import load_bittensor_credentials
from core.bittensor_signals import BTTSN8MinerSignal, BTTSN8Position, BTTSN8Order, BTTSN8TradePair

class BittensorProcessor:
    SIGNAL_SOURCE = "bittensor"
    RAW_SIGNALS_DIR = "raw_signals/bittensor"
    
    CORE_ASSET_MAPPING = {
        "BTCUSD": "BTCUSDT",
        "ETHUSD": "ETHUSDT",
        "ADAUSD": "ADAUSDT"
    }
    
    LEVERAGE_LIMIT_CRYPTO = 0.5

    def __init__(self, *, enabled=True):
        self.credentials = load_bittensor_credentials()
        #self.enabled = enabled
        self.enabled = False
        
    async def fetch_signals(self):
        """Main entry point to fetch and process signals."""
        positions_data = await self._fetch_raw_signals()
        if positions_data:
            self._store_signal_on_disk(positions_data)
            return self._process_signals(positions_data, top_miners=5)
        print("No data received.")
        return []

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
        """Store raw signal data to disk."""
        if not os.path.exists(self.RAW_SIGNALS_DIR):
            os.makedirs(self.RAW_SIGNALS_DIR)
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"bittensor_signal_{timestamp}.json"
        file_path = os.path.join(self.RAW_SIGNALS_DIR, filename)
        
        with open(file_path, 'w') as f:
            ujson.dump(data, f, indent=4)

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
        asset_entries = {}
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
                    
                capped_leverage = min(net_pos, self.LEVERAGE_LIMIT_CRYPTO)
                normalized_depth = (capped_leverage / self.LEVERAGE_LIMIT_CRYPTO) * allocation_weight
                
                latest_order_ms = max(order['processed_ms'] for order in position_data['orders'])
                latest_order_tstamp = datetime.fromtimestamp(latest_order_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
                    
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
            last_entry_date = datetime.fromtimestamp(last_entry_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

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

    @staticmethod
    def _calculate_gradient_allocation(max_rank):
        """Calculate gradient allocation weights."""
        # Total weight is the sum of all rank values
        total_weight = sum(max_rank + 1 - rank for rank in range(1, max_rank + 1))
        
        # Create a dictionary with rank as key and allocation as the fractional value
        allocations = {}
        for rank in range(1, max_rank + 1):
            inverted_rank = max_rank + 1 - rank
            allocations[rank] = inverted_rank / total_weight
        return allocations

    @staticmethod
    def _compute_net_position_and_average_price(orders):
        """Compute net position and average price from orders."""
        # Sort chronologically:
        sorted_orders = sorted(orders, key=lambda x: x["processed_ms"])

        net_position = 0.0
        cost_basis   = 0.0  # Weighted average cost of the net_position
        
        # if any orders are flat, we will return with zero net position and zero cost basis
        if any(order["order_type"].upper().strip() == "FLAT" for order in sorted_orders):
            print("Found FLAT order. Resetting net position and cost basis.")
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

# Example standalone usage
if __name__ == '__main__':
    # return signals and print them
    processor = BittensorProcessor()
    signals = asyncio.run(processor.fetch_signals())
    print(f"Total signals: {len(signals)}") 
    print(signals)
    
