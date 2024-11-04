import asyncio
import aiohttp
import ujson
import os
from datetime import datetime
from core.credentials import load_bittensor_credentials
from core.bittensor_signals import BTTSN8MinerSignal, BTTSN8Position, BTTSN8Order, BTTSN8TradePair

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

def process_signals(data, top_miners=None):
    if data is None:
        return []
    
    signals = []
    # Sort miners by all_time_returns and select the top if specified
    sorted_miners = sorted(data.items(), key=lambda x: x[1].get('all_time_returns', 0), reverse=True)
    if top_miners:
        sorted_miners = sorted_miners[:top_miners]

    for miner_hotkey, miner_positions in sorted_miners:
        all_time_returns = miner_positions['all_time_returns']
        n_positions = miner_positions['n_positions']
        percentage_profitable = miner_positions['percentage_profitable']
        positions = []

        for position_data in miner_positions.get('positions', []):
            trade_pair_data = position_data['trade_pair']
            trade_pair = BTTSN8TradePair(
                symbol=CORE_ASSET_MAPPING.get(trade_pair_data[0], trade_pair_data[0]),
                original_symbol=trade_pair_data[0],
                pair=trade_pair_data[1],
                spread=trade_pair_data[2],
                volume=trade_pair_data[3],
                decimal_places=trade_pair_data[4]
            )
            
            # Calculate and cap the depth based on net_leverage
            capped_leverage = min(position_data['net_leverage'], LEVERAGE_LIMIT_CRYPTO)  # Cap depth as per https://docs.taoshi.io/ptn/miner/overview/#leverage-limits
            
            # Convert net_leverage into a depth ratio
            depth = capped_leverage / LEVERAGE_LIMIT_CRYPTO

            orders = [
                BTTSN8Order(
                    leverage=order_data['leverage'],
                    order_type=order_data['order_type'],
                    order_uuid=order_data['order_uuid'],
                    price=order_data['price'],
                    price_sources=order_data['price_sources'],
                    processed_ms=order_data['processed_ms'],
                    rank=order_data.get('rank', 0),
                    trade_pair=trade_pair
                )
                for order_data in position_data['orders']
            ]

            position = BTTSN8Position(
                depth= depth,
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

        miner_signal = BTTSN8MinerSignal(
            all_time_returns=all_time_returns,
            n_positions=n_positions,
            percentage_profitable=percentage_profitable,
            positions=positions,
            thirty_day_returns=miner_positions.get('thirty_day_returns')
        )

        signals.append(miner_signal)

    return signals

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
    asyncio.run(fetch_bittensor_signal(top_miners=5))
