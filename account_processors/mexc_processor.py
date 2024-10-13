import asyncio
import datetime
from pymexc import futures
from core.credentials import load_mexc_credentials
from core.utils.modifiers import round_to_tick_size
from core.unified_position import UnifiedPosition

# Load MEXC Futures API credentials from the credentials file
credentials = load_mexc_credentials()

# Initialize MEXC Futures client
futures_client = futures.HTTP(api_key=credentials.mexc.api_key, api_secret=credentials.mexc.api_secret)


async def fetch_balance(instrument="USDT"):
    """Fetch the futures account balance for a specific instrument."""
    try:
        # Fetch the asset details for the given instrument
        balance = futures_client.asset(currency=instrument)

        # Check if the API call was successful
        if not balance.get("success", False):
            raise ValueError(f"Failed to fetch assets: {balance}")

        # Extract the data from the response
        balance = balance.get("data", {})
        balance = balance.get("availableBalance", 0)

        print(f"Account Balance for {instrument}: {balance}")
        return balance
    except Exception as e:
        print(f"Error fetching balance: {str(e)}")

async def fetch_open_positions(symbol):
    """Fetch open futures positions."""
    try:
        response = futures_client.open_positions(symbol=symbol)
        print(f"Open Positions: {response}")
        return response.get("data", [])
    except Exception as e:
        print(f"Error fetching open positions: {str(e)}")

async def fetch_open_orders(symbol):
    """Fetch open futures orders."""
    try:
        response = futures_client.open_orders(symbol=symbol)
        print(f"Open Orders: {response}")
        return response.get("data", [])
    except Exception as e:
        print(f"Error fetching open orders: {str(e)}")

async def fetch_tickers(symbol):
    """Fetch ticker information."""
    try:
        response = futures_client.ticker(symbol=symbol)
        print(f"Ticker: {response}")
        return response.get("data", {})
    except Exception as e:
        print(f"Error fetching tickers: {str(e)}")

async def place_limit_order():
    """Place a limit order on MEXC Futures."""
    try:
        symbol = "BTC_USDT"
        side = 1  # 1 for open long, 3 for open short
        price = 60000
        volume = 0.1
        leverage = 3
        order_type = 1  # Limit order
        client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

        # Adjust volume to meet minimum size and tick size requirements
        min_size = 0.001  # Adapt to MEXC's requirements
        tick_size = 0.0001
        volume = max(volume, min_size)
        volume = round_to_tick_size(volume, tick_size)

        order = futures_client.order(
            symbol=symbol,
            price=price,
            vol=volume,
            side=side,
            type=order_type,
            open_type=1,  # 1 for isolated margin
            leverage=leverage,
            external_oid=client_oid
        )
        print(f"Limit Order Placed: {order}")
    except Exception as e:
        print(f"Error placing limit order: {str(e)}")

def map_mexc_position_to_unified(position: dict) -> UnifiedPosition:
    """Convert a MEXC position response into a UnifiedPosition object."""
    size = abs(float(position.get("vol", 0)))
    direction = "long" if int(position.get("posSide", 1)) == 1 else "short"

    return UnifiedPosition(
        symbol=position["symbol"],
        size=size,
        average_entry_price=float(position.get("avgPrice", 0)),
        leverage=float(position.get("leverage", 1)),
        direction=direction,
        unrealized_pnl=float(position.get("unrealizedPnl", 0)),
        exchange="MEXC"
    )

async def fetch_and_map_positions(symbol: str):
    """Fetch and map MEXC positions to UnifiedPosition."""
    try:
        response = futures_client.open_positions(symbol=symbol)
        positions = response.get("data", [])

        unified_positions = [
            map_mexc_position_to_unified(pos) for pos in positions if float(pos.get("vol", 0)) != 0
        ]

        for unified_position in unified_positions:
            print(f"Unified Position: {unified_position}")

        return unified_positions
    except Exception as e:
        print(f"Error mapping MEXC positions: {str(e)}")
        return []

async def main():
 
    balance = await fetch_balance(instrument="USDT")      # Fetch futures balance
    print(balance)
    
    orders = await fetch_open_orders()          # Fetch open orders
    print(orders)
    
    tickers = await fetch_tickers(symbol="BTC_USDT")  # Fetch market tickers
    print(tickers)
    
    # order_results = await place_limit_order()
    # print(order_results)
    
    #await fetch_open_positions(symbol="BTC_USDT")       # Fetch open positions
    positions = await fetch_and_map_positions(symbol="BTC_USDT")
    print(positions)


if __name__ == "__main__":
    asyncio.run(main())
