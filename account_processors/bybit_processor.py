import asyncio
from pybit.unified_trading import HTTP # https://github.com/bybit-exchange/pybit/
from core.credentials import load_bybit_credentials

# Load Bybit API key and secret from your credentials file
credentials = load_bybit_credentials()

TESTNET = False  # Change to False for production
SETTLE_COIN = "USDT"

# Initialize the Bybit client
bybit_client = HTTP(
    api_key=credentials.bybit.api_key,
    api_secret=credentials.bybit.api_secret,
    testnet=TESTNET
)


async def fetch_balance():
    try:
        response = bybit_client.get_wallet_balance(accountType="UNIFIED", coin=SETTLE_COIN)
        print(f"Account Balance: {response}")
    except Exception as e:
        print(f"Error fetching balance: {str(e)}")

async def fetch_open_positions():
    try:
        response = bybit_client.get_positions(category="linear", settleCoin=SETTLE_COIN)
        print(f"Open Positions: {response}")
    except Exception as e:
        print(f"Error fetching open positions: {str(e)}")

async def fetch_open_orders():
    try:
        response = bybit_client.get_open_orders(category="linear", settleCoin=SETTLE_COIN)
        print(f"Open Orders: {response}")
    except Exception as e:
        print(f"Error fetching open orders: {str(e)}")

async def fetch_tickers(symbol):
    try:
        response = bybit_client.get_tickers(category="linear", symbol=symbol)
        print(f"Tickers: {response}")
    except Exception as e:
        print(f"Error fetching tickers: {str(e)}")

async def place_limit_order():
    """Place a limit order on Bybit."""
    try:
        # Test limit order
        category="linear",
        symbol='BTCUSDT',
        side='Buy',
        price=60000,
        qty=0.01,
        leverage=1,
        order_type='Limit',
        time_in_force='GoodTillCancel',
        reduce_only=False,
        close_on_trigger=False
        
        order = bybit_client.place_order(
            category=category,
            symbol=symbol,
            side=side,
            price=price,
            qty=qty,
            leverage=leverage,
            order_type=order_type,
            time_in_force=time_in_force,
            reduce_only=reduce_only,
            close_on_trigger=close_on_trigger
        )
        print(f"Limit Order Placed: {order}")
    except Exception as e:
        print(f"Error placing limit order: {str(e)}")


async def main():
    await fetch_balance()            # Fetch account balance
    await fetch_open_positions()     # Fetch open positions
    await fetch_open_orders()        # Fetch open orders
    await fetch_tickers(symbol="BTCUSDT")            # Fetch market tickers
    #await place_limit_order()        # Place a limit order

if __name__ == '__main__':
    asyncio.run(main())
