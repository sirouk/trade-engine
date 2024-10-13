import asyncio
import datetime
from kucoin_futures.client import UserData, Trade, Market # https://github.com/Kucoin/kucoin-futures-python-sdk
from core.credentials import load_kucoin_credentials

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
        size=0.01
        lever=1
        client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
        
        order_id = trade_client.create_limit_order(
            symbol=symbol, 
            side=side, 
            price=price, 
            size=size,
            lever=lever,
            clientOid=client_oid,
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
    await fetch_balance()      # Fetch futures balance
    await fetch_open_positions()       # Fetch open positions
    await fetch_open_orders()          # Fetch open orders
    await fetch_tickers(symbol="XBTUSDTM")  # Fetch market tickers
    #await place_limit_order()
    
if __name__ == '__main__':
    asyncio.run(main())
