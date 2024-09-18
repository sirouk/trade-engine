import asyncio
import aiohttp
import ujson
import os
from core.credentials import Credentials, BittensorCredentials  # Import dataclass
from signal_processors.credentials import load_credentials, save_credentials, ensure_bittensor_credentials  # Import functions

CREDENTIALS_FILE = "signal_processors/credentials.json"
BITTENSOR_URL = "https://sn8.wildsage.io/miner-positions"

async def fetch_bittensor_signals(api_key: str):
    """Fetch signals from Bittensor subnet 8 validator endpoint."""
    headers = {'Content-Type': 'application/json'}
    data = {'api_key': api_key}

    async with aiohttp.ClientSession() as session:
        async with session.get(BITTENSOR_URL, json=data, headers=headers) as response:
            if response.status == 200:
                return await response.json(loads=ujson.loads)
            print(f"Failed to fetch data: {response.status}")
            return None

def prompt_and_load_credentials():
    """Ensure all credentials are present, and load them if necessary."""
    # Load existing credentials or prompt user for missing ones
    credentials = load_credentials(CREDENTIALS_FILE)
    credentials = ensure_bittensor_credentials(credentials)
    
    # Save any updated credentials back to the file
    save_credentials(credentials, CREDENTIALS_FILE)
    
    return credentials

async def fetch_bittensor_signal():
    """Main function to fetch Bittensor signals and process them."""
    credentials = prompt_and_load_credentials()
    api_key = credentials.bittensor_sn8.api_key
    
    # Fetch signals
    positions_data = await fetch_bittensor_signals(api_key)
    
    if positions_data:
        print("Fetched Bittensor signals:", positions_data)
        # Process the positions_data as needed (e.g., save to raw_signals directory)
    else:
        print("No data received.")

# Run the function standalone or as part of a larger system
if __name__ == '__main__':
    asyncio.run(fetch_bittensor_signal())
