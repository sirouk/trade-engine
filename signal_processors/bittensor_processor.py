import asyncio
import aiohttp
import ujson
import os
from datetime import datetime
from config.credentials import load_bittensor_credentials
from core.bittensor_signals import BTTSN8MinerSignal, BTTSN8Position, BTTSN8Order, BTTSN8TradePair

SIGNAL_SOURCE = "bittensor"

RAW_SIGNALS_DIR = "raw_signals/bittensor"

CORE_ASSET_MAPPING = {
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT"
    # Add more mappings as necessary
}

LEVERAGE_LIMIT_CRYPTO = 0.5 # we will need to differentiate between crypto and forex leverage limits if we add other types in the future


async def fetch_bittensor_signals(api_key: str, endpoint: str):
    headers = {'Content-Type': 'application/json'}
    data = {'api_key': api_key}

    async with aiohttp.ClientSession() as session:
        async with session.get(endpoint, json=data, headers=headers) as response:
            if response.status == 200:
                return await response.json(loads=ujson.loads)
            print(f"Failed to fetch data: {response.status}")
            return None

def store_signal_on_disk(data):
    if not os.path.exists(RAW_SIGNALS_DIR):
        os.makedirs(RAW_SIGNALS_DIR)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"bittensor_signal_{timestamp}.json"
    file_path = os.path.join(RAW_SIGNALS_DIR, filename)
    
    with open(file_path, 'w') as f:
        ujson.dump(data, f, indent=4)
    
    print(f"Raw signal stored at {file_path}")

def calculate_gradient_allocation(max_rank):
    """Calculate gradient allocation weights for each rank based on their inverted priority."""
    # Total weight is the sum of all rank values
    total_weight = sum(max_rank + 1 - rank for rank in range(1, max_rank + 1))
    
    # Create a dictionary with rank as key and allocation as the fractional value
    allocations = {}
    for rank in range(1, max_rank + 1):
        inverted_rank = max_rank + 1 - rank
        allocations[rank] = inverted_rank / total_weight
    return allocations

def compute_net_position_and_average_price(orders):
    """
    Given a list of orders, returns:
      net_position, average_entry_price

    Orders can have a positive or negative 'leverage' to represent
    quantity (long vs. short). We assume:
      +leverage => long
      -leverage => short

    This function:
      1. Sorts orders by processed_ms (chronological).
      2. Iterates through them, maintaining net position & cost basis
         while accounting for partial/full offsets.
      3. If an order is FLAT, we zero out net_position but keep the
         current cost_basis.
    """

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


def process_signals(data, top_miners=None, mapped_only=True):
    if data is None:
        return []

    # Sort miners by all_time_returns and select the top if specified
    sorted_miners = sorted(data.items(), key=lambda x: x[1].get('all_time_returns', 0), reverse=True)
    if top_miners:
        sorted_miners = sorted_miners[:top_miners]

    # Get allocation for each miner based on rank
    allocations = calculate_gradient_allocation(len(sorted_miners))

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
                    if trade_pair in CORE_ASSET_MAPPING
                ),
                None,
            )
            if mapped_only and not original_symbol:
                #print(f"Skipping {original_symbol} as it is not mapped to a core asset.")
                continue

            # Normalize the symbol to match core asset format
            symbol = CORE_ASSET_MAPPING[original_symbol]

            # add an entry for the symbol with the net from the miner
            if symbol not in asset_depths:
                asset_depths[symbol] = []
            
            # Skip if the position has no net leverage or is closed
            if position_data["net_leverage"] == 0 or position_data["is_closed_position"]:
               #print(f"Skipping {symbol} as it has no net leverage.")
               continue
            
            net_pos, avg_price = compute_net_position_and_average_price(position_data["orders"])
                
            capped_leverage = min(net_pos, LEVERAGE_LIMIT_CRYPTO)
            normalized_depth = (capped_leverage / LEVERAGE_LIMIT_CRYPTO) * allocation_weight
            
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
        net_pos, avg_price = compute_net_position_and_average_price(entries)

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

async def fetch_bittensor_signal(top_miners=None):
    credentials = load_bittensor_credentials()
    api_key = credentials.bittensor_sn8.api_key
    endpoint = credentials.bittensor_sn8.endpoint
    
    positions_data = await fetch_bittensor_signals(api_key, endpoint)
    if positions_data:
        store_signal_on_disk(positions_data)
        return process_signals(positions_data, top_miners=top_miners)
    else:
        print("No data received.")
        return []

# Example standalone usage
if __name__ == '__main__':
    # return signals and print them
    signals = asyncio.run(fetch_bittensor_signal(top_miners=5))
    print(f"Total signals: {len(signals)}") 
    print(signals)
    
