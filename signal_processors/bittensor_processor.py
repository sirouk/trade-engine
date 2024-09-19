import asyncio
import aiohttp
import ujson
import os
from datetime import datetime
from core.credentials import load_credentials, ensure_bittensor_credentials
from core.bittensor_signals import BTTSN8MinerSignal, BTTSN8Position, BTTSN8Order, BTTSN8TradePair

CREDENTIALS_FILE = "credentials.json"
RAW_SIGNALS_DIR = "raw_signals/bittensor"  # Directory to store raw signals


def load_bittensor_credentials():
    """Ensure all credentials are present, and load them if necessary."""
    credentials = load_credentials(CREDENTIALS_FILE)
    assert ensure_bittensor_credentials(credentials, skip_prompt=True)
    
    return credentials


async def fetch_bittensor_signals(api_key: str, endpoint: str):
    """Fetch signals from the Bittensor validator endpoint."""
    headers = {'Content-Type': 'application/json'}
    data = {'api_key': api_key}

    async with aiohttp.ClientSession() as session:
        async with session.get(endpoint, json=data, headers=headers) as response:
            if response.status == 200:
                return await response.json(loads=ujson.loads)  # Use ujson for speed
            print(f"Failed to fetch data: {response.status}")
            return None


def store_signal_on_disk(data):
    """Store the raw signal data on disk."""
    if not os.path.exists(RAW_SIGNALS_DIR):
        os.makedirs(RAW_SIGNALS_DIR)
    
    # Create a unique filename using the current timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"bittensor_signal_{timestamp}.json"
    file_path = os.path.join(RAW_SIGNALS_DIR, filename)
    
    # Write the data to a JSON file
    with open(file_path, 'w') as f:
        ujson.dump(data, f, indent=4)
    
    print(f"Raw signal stored at {file_path}")


def process_signals(data):
    """Process the raw signal data."""
    
    # Process signals
    if data is None:
        return
    
    # Iterate over each miner hotkey
    signals = []
    for miner_hotkey, miner_positions in data.items():
        print(f"Processing miner hotkey: {miner_hotkey}")

        # Extract miner signal metadata
        all_time_returns = miner_positions['all_time_returns']
        n_positions = miner_positions['n_positions']
        percentage_profitable = miner_positions['percentage_profitable']
        positions = []

        # Process positions
        for position_data in miner_positions.get('positions', []):
            # Process trade pair
            trade_pair_data = position_data['trade_pair']
            trade_pair = BTTSN8TradePair(
                symbol=trade_pair_data[0],
                pair=trade_pair_data[1],
                spread=trade_pair_data[2],
                volume=trade_pair_data[3],
                decimal_places=trade_pair_data[4]
            )

            # Process orders in position
            orders = []
            for order_data in position_data['orders']:
                order = BTTSN8Order(
                    leverage=order_data['leverage'],
                    order_type=order_data['order_type'],
                    order_uuid=order_data['order_uuid'],
                    price=order_data['price'],
                    price_sources=order_data['price_sources'],
                    processed_ms=order_data['processed_ms'],
                    rank=order_data['rank'] if 'rank' in order_data else 0,
                    trade_pair=trade_pair
                )
                orders.append(order)

            # Process position
            position = BTTSN8Position(
                average_entry_price=position_data['average_entry_price'],
                close_ms=position_data.get('close_ms'),
                current_return=position_data['current_return'],
                is_closed_position=position_data['is_closed_position'],
                miner_hotkey=position_data['miner_hotkey'],
                net_leverage=position_data['net_leverage'],
                open_ms=position_data['open_ms'],
                orders=orders,
                position_type=position_data['position_type'],
                position_uuid=position_data['position_uuid'],
                return_at_close=position_data.get('return_at_close'),
                trade_pair=trade_pair
            )
            positions.append(position)

        # Create BTTSN8MinerSignal instance
        miner_signal = BTTSN8MinerSignal(
            all_time_returns=all_time_returns,
            n_positions=n_positions,
            percentage_profitable=percentage_profitable,
            positions=positions,
            thirty_day_returns=miner_positions.get('thirty_day_returns')
        )

        signals.append(miner_signal)
        print(f"Fetched Bittensor signal: {str(miner_signal)[:100]}...")  # Truncate for cleanliness

    return signals


async def fetch_bittensor_signal():
    """Main function to fetch Bittensor signals and store them."""
    credentials = load_bittensor_credentials()
    api_key = credentials.bittensor_sn8.api_key
    endpoint = credentials.bittensor_sn8.endpoint  # Get the endpoint from the credentials
    
    # Fetch signals
    positions_data = await fetch_bittensor_signals(api_key, endpoint)
    if positions_data is not None:
        # Store them to disk
        store_signal_on_disk(positions_data)

        # Process the signals for validation
        process_signals(positions_data)

    else:
        print("No data received.")


# Run the function standalone or as part of a larger system
if __name__ == '__main__':
    asyncio.run(fetch_bittensor_signal())
