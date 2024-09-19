import asyncio
from pybit.unified_trading import HTTP
from core.credentials import load_credentials, CREDENTIALS_FILE  # Load your unified credentials

# Load Bybit API key and secret from your credentials file
credentials = load_credentials(CREDENTIALS_FILE)

BYBIT_API_KEY = credentials.bybit.api_key
BYBIT_API_SECRET = credentials.bybit.api_secret
TESTNET = False  # Change to False for production

# Initialize the Bybit client
bybit_client = HTTP(api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET, testnet=TESTNET)

async def fetch_open_positions():
    try:
        response = bybit_client.get_positions(category="linear")  # Linear is for futures contracts
        print(f"Open Positions: {response}")
    except Exception as e:
        print(f"Error fetching open positions: {str(e)}")

async def fetch_open_orders():
    try:
        response = bybit_client.get_open_orders(category="linear")  # Linear for futures contracts
        print(f"Open Orders: {response}")
    except Exception as e:
        print(f"Error fetching open orders: {str(e)}")

async def main():
    await fetch_open_positions()
    await fetch_open_orders()

if __name__ == '__main__':
    asyncio.run(main())
