import asyncio
import datetime
from blofin import BloFinClient # https://github.com/nomeida/blofin-python
from core.credentials import load_blofin_credentials
from core.utils.modifiers import round_to_tick_size
from core.unified_position import UnifiedPosition
from core.unified_ticker import UnifiedTicker


class BloFin:
    def __init__(self):
        
        self.exchange_name = "BloFin"
        
        self.credentials = load_blofin_credentials()
        
        # Initialize the BloFin client
        self.blofin_client = BloFinClient(
            api_key=self.credentials.blofin.api_key,
            api_secret=self.credentials.blofin.api_secret,
            passphrase=self.credentials.blofin.api_passphrase
        )

    async def fetch_balance(self, instrument="USDT"):
        try:
            # Get futures balance
            balance = self.blofin_client.account.get_balance(account_type="futures", currency=instrument)
            # {'code': '0', 'msg': 'success', 'data': [{'currency': 'USDT', 'balance': '0.000000000000000000', 'available': '0.000000000000000000', 'frozen': '0.000000000000000000', 'bonus': '0.000000000000000000'}]}
            
            # get coin balance available to trade
            balance = balance["data"][0]["available"]
            print(f"Account Balance for {instrument}: {balance}")
            return balance
        except Exception as e:
            print(f"Error fetching balance: {str(e)}")

    async def fetch_open_positions(self, symbol):
        try:
            # Get open positions for a specific instrument (example: BTC-USDT)
            positions = self.blofin_client.trading.get_positions(inst_id=symbol)
            print(f"Open Positions: {positions}")
            return positions
        except Exception as e:
            print(f"Error fetching open positions: {str(e)}")

    async def fetch_open_orders(self, symbol):
        try:
            # Get open orders for a specific instrument (example: BTC-USDT)
            orders = self.blofin_client.trading.get_order_history(inst_id=symbol)
            print(f"Open Orders: {orders}")
            return orders
        except Exception as e:
            print(f"Error fetching open orders: {str(e)}")

    async def fetch_tickers(self, symbol):
        try:
            tickers = self.blofin_client.public.get_tickers(inst_id=symbol)
            ticker_data = tickers["data"][0]  # Assuming the first entry is the relevant ticker

            print(f"Ticker: {ticker_data}")
            return UnifiedTicker(
                symbol=symbol,
                bid=float(ticker_data.get("bidPrice", 0)),
                ask=float(ticker_data.get("askPrice", 0)),
                last=float(ticker_data.get("last", 0)),
                volume=float(ticker_data.get("volCurrency24h", 0)),
                exchange=self.exchange_name
            )
        except Exception as e:
            print(f"Error fetching tickers from Blofin: {str(e)}")

    async def get_symbol_details(self, symbol):
        """Fetch instrument details including tick size and lot size."""
        instruments = self.blofin_client.public.get_instruments(inst_type="SWAP")
        for instrument in instruments["data"]:
            if instrument["instId"] == symbol:
                return float(instrument["lotSize"]), float(instrument["tickSize"])
        raise ValueError(f"Symbol {symbol} not found.")

    async def place_limit_order(self, ):
        """Place a limit order on BloFin."""
        try:
            # Test limit order
            # https://docs.blofin.com/index.html#place-order
            # NOTE: margin mode is able to be switched here in the API
            symbol="BTC-USDT"
            side="buy"
            position_side="net" # net for one-way, long/short for hedge mode
            price=62957
            size=0.001
            leverage=3
            order_type="ioc" # market: market order, limit: limit order, post_only: Post-only order, fok: Fill-or-kill order, ioc: Immediate-or-cancel order
            # time_in_force is implied in order_type
            margin_mode="isolated" # isolated, cross
            client_order_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
            
            # Fetch the correct lot size and tick size for the symbol
            min_size, tick_size = await self.get_symbol_details(symbol)
            print(f"Symbol {symbol} -> Lot Size: {min_size}, Tick Size: {tick_size}")

            # Adjust size to be at least the minimum and align with tick size precision
            print(f"Size before: {size}")
            size = max(size, min_size)
            print(f"Size after checking min: {size}")
            
            print(f"Price before: {price}")
            price = round_to_tick_size(price, tick_size)
            print(f"Price after tick rounding: {price}")  
            
            order = self.blofin_client.trading.place_order(
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

    def map_blofin_position_to_unified(self, position: dict) -> UnifiedPosition:
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
            exchange=self.exchange_name,
        )

    async def fetch_and_map_positions(self, symbol: str):
        """Fetch open positions from BloFin and convert them to UnifiedPosition objects."""
        try:
            # Fetch positions filtered by symbol directly
            response = self.blofin_client.trading.get_positions(inst_id=symbol)
            positions = response.get("data", [])

            # Convert to UnifiedPosition objects
            unified_positions = [
                self.map_blofin_position_to_unified(pos) 
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

    # Start a time
    start_time = datetime.datetime.now()
    
    blofin = BloFin()
    
    balance = await blofin.fetch_balance(instrument="USDT")      # Fetch futures balance
    print(balance)

    tickers = await blofin.fetch_tickers(symbol="BTC-USDT")  # Fetch market tickers
    print(tickers)
    
    order_results = await blofin.place_limit_order()
    print(order_results)
    
    orders = await blofin.fetch_open_orders(symbol="BTC-USDT")          # Fetch open orders
    print(orders)   
    
    #await blofin.fetch_open_positions(symbol="BTC-USDT")       # Fetch open positions
    positions = await blofin.fetch_and_map_positions(symbol="BTC-USDT")
    #print(positions)
    
    # End time
    end_time = datetime.datetime.now()
    print(f"Time taken: {end_time - start_time}")
    
if __name__ == "__main__":
    asyncio.run(main())
