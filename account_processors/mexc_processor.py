import asyncio
import datetime
from pymexc import futures
from core.credentials import load_mexc_credentials
from core.utils.modifiers import round_to_tick_size
from core.unified_position import UnifiedPosition

# Load MEXC Futures API credentials from the credentials file
credentials = load_mexc_credentials()

# Initialize MEXC Futures clients
futures_client = futures.HTTP(
    api_key=credentials.mexc.api_key, 
    api_secret=credentials.mexc.api_secret
)

async def fetch_balance(instrument="USDT"):
    """Fetch futures account balance."""
    try:
        response = futures_client.account_information()
        balances = response.get('assets', [])
        if balance := next(
            (b for b in balances if b['asset'] == instrument), None
        ):
            available_balance = balance.get("marginBalance", 0)
            print(f"Account Balance: {available_balance}")
            return available_balance
        else:
            print(f"No balance found for {instrument}.")
            return 0
    except Exception as e:
        print(f"Error fetching balance: {str(e)}")

async def fetch_open_positions(symbol):
    """Fetch open futures positions."""
    try:
        response = futures_client.position_info()
        positions = [p for p in response if p['symbol'] == symbol]
        print(f"Open Positions: {positions}")
        return positions
    except Exception as e:
        print(f"Error fetching open positions: {str(e)}")

async def fetch_open_orders(symbol):
    """Fetch open futures orders."""
    try:
        orders = futures_client.open_orders(symbol=symbol)
        print(f"Open Orders: {orders}")
        return orders
    except Exception as e:
        print(f"Error fetching open orders: {str(e)}")

async def fetch_tickers(symbol):
    """Fetch ticker information."""
    try:
        ticker = futures_client.market_price(symbol=symbol)
        print(f"Ticker: {ticker}")
        return ticker
    except Exception as e:
        print(f"Error fetching tickers: {str(e)}")

async def place_limit_order():
    """Place a limit order on MEXC Futures."""
    try:
        symbol = "BTCUSDT"
        side = "buy"
        price = 60000
        size = 0.1
        leverage = 3
        order_type = "limit"
        client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

        # Adjust size to meet minimum and tick size requirements
        min_size = 0.001  # Example: adjust based on MEXC API details
        tick_size = 0.0001
        size = max(size, min_size)
        size = round_to_tick_size(size, tick_size)

        order = futures_client.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=str(price),
            quantity=str(size),
            client_order_id=client_oid
        )
        print(f"Limit Order Placed: {order}")
    except Exception as e:
        print(f"Error placing limit order: {str(e)}")

def map_mexc_position_to_unified(position: dict) -> UnifiedPosition:
    """Convert a MEXC position response into a UnifiedPosition object."""
    size = abs(float(position.get("positionAmt", 0)))
    direction = "long" if float(position.get("positionAmt", 0)) > 0 else "short"

    return UnifiedPosition(
        symbol=position["symbol"],
        size=size,
        average_entry_price=float(position.get("entryPrice", 0)),
        leverage=float(position.get("leverage", 1)),
        direction=direction,
        unrealized_pnl=float(position.get("unrealizedProfit", 0)),
        exchange="MEXC"
    )

async def fetch_and_map_positions(symbol: str):
    """Fetch and map MEXC positions to UnifiedPosition."""
    try:
        response = futures_client.position_info()
        positions = [p for p in response if p['symbol'] == symbol]

        unified_positions = [
            map_mexc_position_to_unified(pos)
            for pos in positions if float(pos.get("positionAmt", 0)) != 0
        ]

        for unified_position in unified_positions:
            print(f"Unified Position: {unified_position}")

        return unified_positions
    except Exception as e:
        print(f"Error mapping MEXC positions: {str(e)}")
        return []

async def main():
    
    balance = await fetch_balance(instrument="USDT")  # Fetch futures balance
    print(balance)

    orders = await fetch_open_orders(symbol="BTCUSDT")  # Fetch open orders
    print(orders)

    tickers = await fetch_tickers(symbol="BTCUSDT")  # Fetch ticker information
    print(tickers)

    await place_limit_order()  # Place a limit order

    positions = await fetch_and_map_positions(symbol="BTCUSDT")
    print(positions)

if __name__ == "__main__":
    asyncio.run(main())
