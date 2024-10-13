import asyncio
import datetime
from kucoin_futures.client import UserData, Trade, Market # https://github.com/Kucoin/kucoin-futures-python-sdk
from core.credentials import load_kucoin_credentials
from core.utils.modifiers import round_to_tick_size

# Load KuCoin Futures API credentials from the credentials file
credentials = load_kucoin_credentials()

# Initialize KuCoin Futures clients
user_client = UserData(
    key=credentials.kucoin.api_key, 
    secret=credentials.kucoin.api_secret, 
    passphrase=credentials.kucoin.api_passphrase,
)

trade_client = Trade(
    key=credentials.kucoin.api_key, 
    secret=credentials.kucoin.api_secret, 
    passphrase=credentials.kucoin.api_passphrase,
)

market_client = Market()


async def fetch_balance():
    """Fetch futures account balance."""
    try:
        balance = user_client.get_account_overview(currency="USDT")
        print(f"Futures Account Balance: {balance}")
    except Exception as e:
        print(f"Error fetching balance: {str(e)}")

async def fetch_open_positions():
    """Fetch open futures positions."""
    try:
        positions = trade_client.get_all_position()
        print(f"Open Positions: {positions}")
    except Exception as e:
        print(f"Error fetching open positions: {str(e)}")

async def fetch_open_orders():
    """Fetch open futures orders."""
    try:
        open_orders = trade_client.get_open_order_details(symbol="XBTUSDTM")
        print(f"Open Orders: {open_orders}")
    except Exception as e:
        print(f"Error fetching open orders: {str(e)}")

async def place_limit_order():
    """Place a limit order on KuCoin Futures."""
    try:
        # Test limit order
        symbol="XBTUSDTM"
        side="buy"
        price=60000
        size=0.1
        leverage=3
        order_type="limit"
        margin_mode="ISOLATED" # ISOLATED, CROSS, default: ISOLATED
        client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

        # Fetch symbol details to confirm correct size increment and tick size
        symbol_details = market_client.get_contract_detail(symbol)
        min_size = float(symbol_details["lotSize"])
        tick_size = float(symbol_details["tickSize"])
        print(f"Symbol {symbol} -> Lot Size: {min_size}, Tick Size: {tick_size}")

        # Adjust size to be at least the minimum lot size and align with tick size precision
        size = max(size, min_size)
        size = round_to_tick_size(size, tick_size)
        
        order_id = trade_client.create_limit_order(
            symbol=symbol,
            side=side,
            price=price,
            size=size,
            lever=leverage,
            orderType=order_type,
            marginMode=margin_mode,
            clientOid=client_oid
        )
        print(f"Limit Order Placed: {order_id}")
    except Exception as e:
        print(f"Error placing limit order: {str(e)}")

async def fetch_tickers(symbol):
    try:
        # Get tickers for BTC-USDT
        tickers = market_client.get_ticker(symbol=symbol)
        print(f"Tickers: {tickers}")
    except Exception as e:
        print(f"Error fetching tickers: {str(e)}")


async def main():
    # await fetch_balance()      # Fetch futures balance
    # await fetch_open_positions()       # Fetch open positions
    # await fetch_open_orders()          # Fetch open orders
    # await fetch_tickers(symbol="XBTUSDTM")  # Fetch market tickers
    await place_limit_order()
    
if __name__ == "__main__":
    asyncio.run(main())
