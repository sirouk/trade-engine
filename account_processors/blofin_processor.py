import asyncio
import datetime
from blofin import BloFinClient # https://github.com/nomeida/blofin-python
from core.credentials import load_blofin_credentials
from core.utils.modifiers import round_to_tick_size
from core.unified_position import UnifiedPosition

# Load BloFin API key and secret from your credentials file
credentials = load_blofin_credentials()

# Initialize the BloFin client
blofin_client = BloFinClient(
    api_key=credentials.blofin.api_key,
    api_secret=credentials.blofin.api_secret,
    passphrase=credentials.blofin.api_passphrase
)


async def fetch_balance(instrument="USDT"):
    try:
        # Get futures balance
        balance = blofin_client.account.get_balance(account_type="futures", currency=instrument)
        # {'code': '0', 'msg': 'success', 'data': [{'currency': 'USDT', 'balance': '0.000000000000000000', 'available': '0.000000000000000000', 'frozen': '0.000000000000000000', 'bonus': '0.000000000000000000'}]}
        
        # get coin balance available to trade
        balance = balance["data"][0]["available"]
        
        print(f"Account Balance: {balance}")
        return balance
    except Exception as e:
        print(f"Error fetching balance: {str(e)}")

async def fetch_open_positions(symbol):
    try:
        # Get open positions for a specific instrument (example: BTC-USDT)
        positions = blofin_client.trading.get_positions(inst_id=symbol)
        print(f"Open Positions: {positions}")
        return positions
    except Exception as e:
        print(f"Error fetching open positions: {str(e)}")

async def fetch_open_orders():
    try:
        # Get open orders for a specific instrument (example: BTC-USDT)
        orders = blofin_client.trading.get_order_history()
        print(f"Open Orders: {orders}")
        return orders
    except Exception as e:
        print(f"Error fetching open orders: {str(e)}")

async def fetch_tickers(symbol):
    try:
        # Get tickers for BTC-USDT
        tickers = blofin_client.public.get_tickers(inst_id=symbol)
        print(f"Tickers: {tickers}")
        return tickers
    except Exception as e:
        print(f"Error fetching tickers: {str(e)}")

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

def map_blofin_position_to_unified(position: dict) -> UnifiedPosition:
    """Convert a BloFin position response into a UnifiedPosition object."""
    size = abs(float(position.get("positions", 0)))  # Handle both long and short positions
    direction = "long" if float(position.get("positions", 0)) > 0 else "short"

    return UnifiedPosition(
        symbol=position["instId"],
        size=size,
        average_entry_price=float(position.get("averagePrice", 0)),
        leverage=float(position.get("leverage", 1)),
        direction=direction,
        unrealized_pnl=float(position.get("unrealizedPnl", 0)),
        exchange="BloFin"
    )

async def fetch_and_map_positions(symbol: str):
    """Fetch open positions from BloFin and convert them to UnifiedPosition objects."""
    try:
        # Fetch positions filtered by symbol directly
        response = blofin_client.trading.get_positions(inst_id=symbol)
        positions = response.get("data", [])

        # Convert to UnifiedPosition objects
        unified_positions = [
            map_blofin_position_to_unified(pos) 
            for pos in positions 
            if float(pos.get("positions", 0)) != 0
        ]

        for unified_position in unified_positions:
            print(f"Unified Position: {unified_position}")

        return unified_positions
    except Exception as e:
        print(f"Error mapping BloFin positions: {str(e)}")
        return []

async def main():

    balance = await fetch_balance(instrument="USDT")      # Fetch futures balance
    print(balance)
    
    orders = await fetch_open_orders()          # Fetch open orders
    print(orders)
    
    tickers = await fetch_tickers(symbol="BTC-USDT")  # Fetch market tickers
    print(tickers)
    
    # order_results = await place_limit_order()
    # print(order_results)
    
    #await fetch_open_positions(symbol="BTC-USDT")       # Fetch open positions
    positions = await fetch_and_map_positions(symbol="BTC-USDT")
    print(positions)
    
if __name__ == "__main__":
    asyncio.run(main())
