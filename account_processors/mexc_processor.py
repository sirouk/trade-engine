import asyncio
import datetime
from pymexc import futures
from core.credentials import load_mexc_credentials
from core.utils.modifiers import round_to_tick_size
from core.unified_position import UnifiedPosition
from core.unified_ticker import UnifiedTicker


class MEXC:
    def __init__(self):
        
        self.exchange_name = "MEXC"
        
        # Load MEXC Futures API credentials from the credentials file
        self.credentials = load_mexc_credentials()

        # Initialize MEXC Futures client
        self.futures_client = futures.HTTP(
            api_key=self.credentials.mexc.api_key, 
            api_secret=self.credentials.mexc.api_secret
        )


    async def fetch_balance(self, instrument="USDT"):
        """Fetch the futures account balance for a specific instrument."""
        try:
            # Fetch the asset details for the given instrument
            balance = self.futures_client.asset(currency=instrument)

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

    async def fetch_open_positions(self, symbol):
        """Fetch open futures positions."""
        try:
            response = self.futures_client.open_positions(symbol=symbol)
            print(f"Open Positions: {response}")
            return response.get("data", [])
        except Exception as e:
            print(f"Error fetching open positions: {str(e)}")

    async def fetch_open_orders(self, symbol):
        """Fetch open futures orders."""
        try:
            response = self.futures_client.open_orders(symbol=symbol)
            print(f"Open Orders: {response}")
            return response.get("data", [])
        except Exception as e:
            print(f"Error fetching open orders: {str(e)}")

    async def fetch_tickers(self, symbol):
        try:
            response = self.futures_client.ticker(symbol=symbol)
            ticker_data = response.get("data", {})
            
            # Quantity traded in the last 24 hours
            amount24 = float(ticker_data.get("amount24", 0))
            lastPrice = float(ticker_data.get("lastPrice", 0))

            print(f"Ticker: {ticker_data}")
            return UnifiedTicker(
                symbol=symbol,
                bid=float(ticker_data.get("bid1", 0)),
                ask=float(ticker_data.get("ask1", 0)),
                last=float(ticker_data.get("lastPrice", 0)),
                volume=float(amount24 / lastPrice),
                exchange=self.exchange_name
            )
        except Exception as e:
            print(f"Error fetching tickers from MEXC: {str(e)}")

    async def get_symbol_details(self, symbol: str):
        """Fetch instrument details including lot size and tick size for MEXC Futures."""
        try:
            # Fetch all contract details
            response = self.futures_client.detail()

            # Check if the API call was successful
            if not response.get("success", False):
                raise ValueError(f"Failed to fetch contract details: {response}")

            # Search for the requested symbol in the response data
            for instrument in response.get("data", []):
                if instrument["symbol"] == symbol:
                    # Extract the relevant details
                    return float(instrument.get("volUnit", 1)), float(instrument.get("priceUnit", 0.5))

            # Raise an error if the symbol is not found
            raise ValueError(f"Symbol {symbol} not found.")
        
        except Exception as e:
            print(f"Error fetching symbol details: {str(e)}")
    
    async def place_limit_order(self, ):
        """Place a limit order on MEXC Futures."""
        try:
            # Test limit order
            # https://mexcdevelop.github.io/apidocs/contract_v1_en/#order-under-maintenance
            symbol="BTC_USDT"
            side=1 # 1 open long , 2 close short, 3 open short , 4 close l
            price=60000
            size=0.001
            leverage=3
            order_type=1 # Limit order
            margin_mode=1 # 1:isolated 2:cross
            client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

            # Fetch symbol details to confirm correct size increment and tick size
            min_size, tick_size = self.get_symbol_details(symbol)
            print(f"Symbol {symbol} -> Lot Size: {min_size}, Tick Size: {tick_size}")

            # Adjust size to be at least the minimum lot size and align with tick size precision
            print(f"Size before: {size}")
            size = max(size, min_size)
            print(f"Size after checking min: {size}")
            
            print(f"Price before: {price}")
            price = round_to_tick_size(price, tick_size)
            print(f"Price after tick rounding: {price}")  
            
            order = self.futures_client.order(
                symbol=symbol,
                price=price,
                vol=size,
                side=side,
                type=order_type,
                open_type=margin_mode,
                leverage=leverage,
                external_oid=client_oid
            )
            print(f"Limit Order Placed: {order}")
        except Exception as e:
            print(f"Error placing limit order: {str(e)}")

    def map_mexc_position_to_unified(self, position: dict) -> UnifiedPosition:
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
            exchange=self.exchange_name,
        )

    async def fetch_and_map_positions(self, symbol: str):
        """Fetch and map MEXC positions to UnifiedPosition."""
        try:
            response = self.futures_client.open_positions(symbol=symbol)
            positions = response.get("data", [])

            unified_positions = [
                self.map_mexc_position_to_unified(pos) for pos in positions if float(pos.get("vol", 0)) != 0
            ]

            for unified_position in unified_positions:
                print(f"Unified Position: {unified_position}")

            return unified_positions
        except Exception as e:
            print(f"Error mapping MEXC positions: {str(e)}")
            return []


async def main():
    
    # Start a time
    start_time = datetime.datetime.now()
    
    mexc = MEXC()
    
    balance = await mexc.fetch_balance(instrument="USDT")      # Fetch futures balance
    print(balance)
    
    tickers = await mexc.fetch_tickers(symbol="BTC_USDT")  # Fetch market tickers
    print(tickers)
    
    order_results = await mexc.place_limit_order()
    print(order_results)
    
    orders = await mexc.fetch_open_orders(symbol="BTC_USDT")          # Fetch open orders
    print(orders)
    
    #await mexc.fetch_open_positions(symbol="BTC_USDT")       # Fetch open positions
    positions = await mexc.fetch_and_map_positions(symbol="BTC_USDT")
    #print(positions)
    
    # End time
    end_time = datetime.datetime.now()
    print(f"Time taken: {end_time - start_time}")


if __name__ == "__main__":
    asyncio.run(main())
