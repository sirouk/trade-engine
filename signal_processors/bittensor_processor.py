import asyncio
import aiohttp
import ujson
import os
from datetime import datetime
from core.credentials import Credentials, BittensorCredentials
from signal_processors.credentials import load_credentials, save_credentials, ensure_bittensor_credentials

CREDENTIALS_FILE = "signal_processors/credentials.json"
BITTENSOR_URL = "https://sn8.wildsage.io/miner-positions"
RAW_SIGNALS_DIR = "raw_signals/bittensor"  # Directory to store raw signals


def prompt_and_load_credentials():
    """Ensure all credentials are present, and load them if necessary."""
    credentials = load_credentials(CREDENTIALS_FILE)
    credentials = ensure_bittensor_credentials(credentials)
    
    # Save any updated credentials back to the file
    save_credentials(credentials, CREDENTIALS_FILE)
    
    return credentials


async def fetch_bittensor_signals(api_key: str):
    """Fetch signals from Bittensor subnet 8 validator endpoint."""
    headers = {'Content-Type': 'application/json'}
    data = {'api_key': api_key}

    async with aiohttp.ClientSession() as session:
        async with session.get(BITTENSOR_URL, json=data, headers=headers) as response:
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


async def fetch_bittensor_signal():
    """Main function to fetch Bittensor signals and store them."""
    credentials = prompt_and_load_credentials()
    api_key = credentials.bittensor_sn8.api_key
    
    # Fetch signals
    positions_data = await fetch_bittensor_signals(api_key)
    
    if positions_data:
        print("Fetched Bittensor signals:", str(positions_data)[:100])  # Truncate for cleanliness
        store_signal_on_disk(positions_data)  # Store the raw data on disk
    else:
        print("No data received.")


# Run the function standalone or as part of a larger system
if __name__ == '__main__':
    asyncio.run(fetch_bittensor_signal())
