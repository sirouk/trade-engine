import asyncio
from blofin import BloFinClient
from core.credentials import load_blofin_credentials

# Load BloFin API key and secret from your credentials file
credentials = load_blofin_credentials()

# Initialize the BloFin client
blofin_client = BloFinClient(api_key=credentials.blofin.api_key, api_secret=credentials.blofin.api_secret, passphrase=credentials.blofin.api_passphrase)

async def fetch_balance():
    try:
        # Get futures balance
        balance = blofin_client.account.get_balance(account_type='futures')
        print(f"Account Balance: {balance}")
    except Exception as e:
        print(f"Error fetching balance: {str(e)}")

async def fetch_open_positions():
    try:
        # Get open positions for a specific instrument (example: BTC-USDT)
        positions = blofin_client.trading.get_positions()
        print(f"Open Positions: {positions}")
    except Exception as e:
        print(f"Error fetching open positions: {str(e)}")

async def fetch_open_orders():
    try:
        # Get open orders for a specific instrument (example: BTC-USDT)
        open_orders = blofin_client.trading.get_order_history()
        print(f"Open Orders: {open_orders}")
    except Exception as e:
        print(f"Error fetching open orders: {str(e)}")

async def fetch_tickers():
    try:
        # Get tickers for BTC-USDT
        tickers = blofin_client.public.get_tickers(inst_id='BTC-USDT')
        print(f"Tickers: {tickers}")
    except Exception as e:
        print(f"Error fetching tickers: {str(e)}")

async def main():
    await fetch_balance()           # Fetch account balance
    await fetch_open_positions()    # Fetch open positions
    await fetch_open_orders()       # Fetch open orders
    await fetch_tickers()           # Fetch market tickers

if __name__ == '__main__':
    asyncio.run(main())
