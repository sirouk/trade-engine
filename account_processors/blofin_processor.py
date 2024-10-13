import asyncio
import datetime
from blofin import BloFinClient # https://github.com/nomeida/blofin-python
from core.credentials import load_blofin_credentials
from core.utils.modifiers import round_to_tick_size

# Load BloFin API key and secret from your credentials file
credentials = load_blofin_credentials()

# Initialize the BloFin client
blofin_client = BloFinClient(
    api_key=credentials.blofin.api_key,
    api_secret=credentials.blofin.api_secret,
    passphrase=credentials.blofin.api_passphrase
)


async def fetch_balance():
    try:
        # Get futures balance
        balance = blofin_client.account.get_balance(account_type="futures")
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

async def get_symbol_details(symbol):
    """Fetch instrument details including tick size and lot size."""
    instruments = blofin_client.public.get_instruments(inst_type="SWAP")
    for instrument in instruments["data"]:
        if instrument["instId"] == symbol:
            return float(instrument["lotSize"]), float(instrument["tickSize"])
    raise ValueError(f"Symbol {symbol} not found.")

async def place_limit_order():
    """Place a limit order on BloFin."""
    try:
        # Test limit order
        symbol="BTC-USDT"
        side="buy"
        position_side="net" # net for one-way, long/short for hedge mode
        price=60000
        size=0.1
        leverage=3
        order_type="limit"
        margin_mode="cross"
        client_order_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
        
        # Fetch the correct lot size and tick size for the symbol
        min_size, tick_size = await get_symbol_details(symbol)
        print(f"Symbol {symbol} -> Lot Size: {min_size}, Tick Size: {tick_size}")

        # Adjust size to be at least the minimum and align with tick size precision
        size = max(size, min_size)
        size = round_to_tick_size(size, tick_size)
        
        order = blofin_client.trading.place_order(
            inst_id=symbol,
            side=side,
            position_side=position_side,
            price=price,
            size=size,
            leverage=leverage,
            order_type=order_type,
            margin_mode=margin_mode,
            clientOrderId=client_order_id,
        )
        print(f"Limit Order Placed: {order}")
    except Exception as e:
        print(f"Error placing limit order: {str(e)}")

async def fetch_tickers(symbol):
    try:
        # Get tickers for BTC-USDT
        tickers = blofin_client.public.get_tickers(inst_id=symbol)
        print(f"Tickers: {tickers}")
    except Exception as e:
        print(f"Error fetching tickers: {str(e)}")


async def main():
    #await fetch_balance()           # Fetch account balance
    #await fetch_open_positions()    # Fetch open positions
    #await fetch_open_orders()       # Fetch open orders
    #await fetch_tickers(symbol="BTC-USDT")           # Fetch market tickers
    await place_limit_order()       # Place a limit order

if __name__ == "__main__":
    asyncio.run(main())
