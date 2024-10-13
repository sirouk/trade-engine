import asyncio
import datetime
from kucoin_futures.client import UserData, Trade, Market # https://github.com/Kucoin/kucoin-futures-python-sdk
from core.credentials import load_kucoin_credentials
from core.utils.modifiers import round_to_tick_size
from core.unified_position import UnifiedPosition
from core.unified_ticker import UnifiedTicker


class KuCoin:
    def __init__(self):
        
        self.exchange_name = "KuCoin"
        
        # Load KuCoin Futures API credentials from the credentials file
        self.credentials = load_kucoin_credentials()

        # Initialize KuCoin Futures clients
        self.user_client = UserData(
            key=self.credentials.kucoin.api_key, 
            secret=self.credentials.kucoin.api_secret, 
            passphrase=self.credentials.kucoin.api_passphrase,
        )

        self.trade_client = Trade(
            key=self.credentials.kucoin.api_key, 
            secret=self.credentials.kucoin.api_secret, 
            passphrase=self.credentials.kucoin.api_passphrase,
        )

        self.market_client = Market()


    async def fetch_balance(self, instrument="USDT"):
        """Fetch futures account balance."""
        try:
            balance = self.user_client.get_account_overview(currency=instrument)
            # {'accountEquity': 0.58268157, 'unrealisedPNL': 0.0, 'marginBalance': 0.58268157, 'positionMargin': 0.0, 'orderMargin': 0.0, 'frozenFunds': 0.0, 'availableBalance': 0.58268157, 'currency': 'USDT'}
            
            # get coin balance available to trade
            balance = balance.get("availableBalance", 0)
            print(f"Account Balance for {instrument}: {balance}")
            return balance
        except Exception as e:
            print(f"Error fetching balance: {str(e)}")

    async def fetch_open_positions(self, symbol):
        """Fetch open futures positions."""
        try:
            positions = self.trade_client.get_position_details(symbol=symbol)
            print(f"Open Positions: {positions}")
            return positions
        except Exception as e:
            print(f"Error fetching open positions: {str(e)}")

    async def fetch_open_orders(self, symbol):
        """Fetch open futures orders."""
        try:
            orders = self.trade_client.get_open_order_details(symbol=symbol)
            print(f"Open Orders: {orders}")
            return orders
        except Exception as e:
            print(f"Error fetching open orders: {str(e)}")

    async def fetch_tickers(self, symbol):
        try:
            tickers = self.market_client.get_ticker(symbol=symbol)
            contract = self.market_client.get_contract_detail(symbol=symbol)
            
            print(f"Tickers: {tickers}")
            return UnifiedTicker(
                symbol=symbol,
                bid=float(tickers.get("bestBidPrice", 0)),
                ask=float(tickers.get("bestAskPrice", 0)),
                last=float(tickers.get("price", 0)),
                volume=float(contract.get("volumeOf24h", 0)),
                exchange=self.exchange_name
            )
        except Exception as e:
            print(f"Error fetching tickers from KuCoin: {str(e)}")

    async def get_symbol_details(self, symbol):
        """Fetch instrument details including tick size and lot size."""
        instrument = self.market_client.get_contract_detail(symbol)
        if instrument["symbol"] == symbol:
            return float(instrument["lotSize"]), float(instrument["tickSize"])
        raise ValueError(f"Symbol {symbol} not found.")
    
    async def place_limit_order(self, ):
        """Place a limit order on KuCoin Futures."""
        try:
            # Test limit order
            # https://www.kucoin.com/docs/rest/futures-trading/orders/place-order
            # NOTE: althought we can pass the margin mode, it must match with the user interface
            symbol="XBTUSDTM"
            side="buy" # buy, sell
            price=60000
            size=0.001
            leverage=3
            order_type="limit" # limit or market
            time_in_force="IOC" # GTC, GTT, IOC, FOK (IOC as FOK has unexpected behavior)
            margin_mode="ISOLATED" # ISOLATED, CROSS, default: ISOLATED
            client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

            # Fetch symbol details to confirm correct size increment and tick size
            min_size, tick_size = await self.get_symbol_details(symbol)
            print(f"Symbol {symbol} -> Lot Size: {min_size}, Tick Size: {tick_size}")

            # Adjust size to be at least the minimum lot size and align with tick size precision
            print(f"Size before: {size}")
            size = max(size, min_size)
            print(f"Size after checking min: {size}")
            
            print(f"Price before: {price}")
            price = round_to_tick_size(price, tick_size)
            print(f"Price after tick rounding: {price}")  
            
            #create_limit_order(self, symbol, side, lever, size, price, clientOid='', **kwargs):
            order_id = self.trade_client.create_limit_order(
                symbol=symbol,
                side=side,
                price=price,
                size=size,
                lever=leverage,
                orderType=order_type,
                timeInForce=time_in_force,
                marginMode=margin_mode,
                clientOid=client_oid
            )
            print(f"Limit Order Placed: {order_id}")
        except Exception as e:
            print(f"Error placing limit order: {str(e)}")

    def map_kucoin_position_to_unified(self, position: dict) -> UnifiedPosition:
        """Convert a KuCoin position response into a UnifiedPosition object."""
        size = abs(float(position.get("currentQty", 0)))  # Handle long/short positions
        direction = "long" if float(position.get("currentQty", 0)) > 0 else "short"

        return UnifiedPosition(
            symbol=position["symbol"],
            size=size,
            average_entry_price=float(position.get("avgEntryPrice", 0)),
            leverage=float(position.get("leverage", 1)),
            direction=direction,
            unrealized_pnl=float(position.get("unrealisedPnl", 0)),
            exchange=self.exchange_name,
        )

    async def fetch_and_map_positions(self, symbol: str):
        """Fetch and map KuCoin positions to UnifiedPosition."""
        try:
            response = self.trade_client.get_position_details(symbol=symbol)
            positions = response.get("data", [])

            # Convert each position to UnifiedPosition
            unified_positions = [
                self.map_kucoin_position_to_unified(pos) 
                for pos in positions 
                if float(pos.get("currentQty", 0)) != 0
            ]

            for unified_position in unified_positions:
                print(f"Unified Position: {unified_position}")

            return unified_positions
        except Exception as e:
            print(f"Error mapping KuCoin positions: {str(e)}")
            return []


async def main():
    
    # Start a time
    start_time = datetime.datetime.now()
    
    kucoin = KuCoin()
    
    # balance = await kucoin.fetch_balance(instrument="USDT")      # Fetch futures balance
    # print(balance)

    # tickers = await kucoin.fetch_tickers(symbol="XBTUSDTM")  # Fetch market tickers
    # print(tickers)
    
    order_results = await kucoin.place_limit_order()
    print(order_results)
    
    # orders = await kucoin.fetch_open_orders(symbol="XBTUSDTM")          # Fetch open orders
    # print(orders)    
    
    # #await kucoin.fetch_open_positions(symbol="XBTUSDTM")       # Fetch open positions
    # positions = await kucoin.fetch_and_map_positions(symbol="XBTUSDTM")
    # #print(positions)
    
    # End time
    end_time = datetime.datetime.now()
    print(f"Time taken: {end_time - start_time}")
    
if __name__ == "__main__":
    asyncio.run(main())
