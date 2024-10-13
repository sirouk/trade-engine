import asyncio
import datetime
from pybit.unified_trading import HTTP # https://github.com/bybit-exchange/pybit/
from core.credentials import load_bybit_credentials
from core.utils.modifiers import round_to_tick_size

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

async def get_symbol_details(symbol):
    """Fetch instrument details including tick size and lot size."""
    instruments = bybit_client.get_instruments_info(category="linear", symbol=symbol)
    # print(instruments)
    # quit()
    for instrument in instruments["result"]["list"]:
        if instrument["symbol"] == symbol:
            return float(instrument["lotSizeFilter"]["minOrderQty"]), float(instrument["lotSizeFilter"]["qtyStep"])
    raise ValueError(f"Symbol {symbol} not found.")

async def place_limit_order():
    """Place a limit order on Bybit."""
    try:
        # Test limit order
        category="linear"
        symbol="BTCUSDT"
        side="Buy"
        price=60000
        size=0.01
        leverage=1
        order_type="Limit"
        time_in_force="IOC"
        reduce_only=False
        close_on_trigger=False
        client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
        
        # Get correct lot size and tick size for the symbol
        min_size, tick_size = await get_symbol_details(symbol)
        print(f"Symbol {symbol} -> Lot Size: {min_size}, Tick Size: {tick_size}")

        # Adjust size to meet minimum lot size and align with tick size
        size = max(size, min_size)
        size = round_to_tick_size(size, tick_size)
        
        order = bybit_client.place_order(
            category=category,
            symbol=symbol,
            side=side,
            price=price,
            qty=size,
            leverage=leverage,
            order_type=order_type,
            time_in_force=time_in_force, # GTC, IOC, FOK, PostOnly (use IOK)
            reduce_only=reduce_only,
            close_on_trigger=close_on_trigger,
            orderLinkId=client_oid,
            positionIdx=0, # one-way mode
        )
        print(f"Limit Order Placed: {order}")
    except Exception as e:
        print(f"Error placing limit order: {str(e)}")
        

async def main():
    # await fetch_balance()            # Fetch account balance
    # await fetch_open_positions()     # Fetch open positions
    # await fetch_open_orders()        # Fetch open orders
    # await fetch_tickers(symbol="BTCUSDT")            # Fetch market tickers
    await place_limit_order()        # Place a limit order

if __name__ == "__main__":
    asyncio.run(main())
