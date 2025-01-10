import asyncio
import datetime
from pymexc import futures
from config.credentials import load_mexc_credentials
from core.utils.modifiers import round_to_tick_size, calculate_lots
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
        
        self.margin_mode_map = {
            "isolated": 1,
            "cross": 2
        }

        self.inverse_margin_mode_map = {v: k for k, v in self.margin_mode_map.items()}

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

    async def fetch_and_map_positions(self, symbol: str):
        """Fetch and map MEXC positions to UnifiedPosition."""
        try:
            response = self.futures_client.open_positions(symbol=symbol)
            positions = response.get("data", [])

            unified_positions = [
                self.map_mexc_position_to_unified(pos) 
                for pos in positions 
                if float(pos.get("vol", 0)) != 0
            ]

            for unified_position in unified_positions:
                print(f"Unified Position: {unified_position}")

            return unified_positions
        except Exception as e:
            print(f"Error mapping MEXC positions: {str(e)}")
            return []

    def map_mexc_position_to_unified(self, position: dict) -> UnifiedPosition:
        """Convert a MEXC position response into a UnifiedPosition object."""
        size = abs(float(position.get("vol", 0)))
        direction = "long" if int(position.get("posSide", 1)) == 1 else "short"
        # adjust size for short positions
        if direction == "short":
            size = -size
            
        # Use provided margin mode if available, otherwise derive from tradeMode
        mexc_margin_mode = position.get("open_type")
        if mexc_margin_mode is None:
            raise ValueError("Margin mode not found in position data.")
        
        margin_mode = self.margin_mode_map.get(mexc_margin_mode, mexc_margin_mode)
        
        return UnifiedPosition(
            symbol=position["symbol"],
            size=size,
            average_entry_price=float(position.get("avgPrice", 0)),
            leverage=float(position.get("leverage", 1)),
            direction=direction,
            unrealized_pnl=float(position.get("unrealizedPnl", 0)),
            margin_mode=margin_mode,
            exchange=self.exchange_name,
        )
        
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
        """Fetch instrument details including lot size, min size, tick size, and contract value."""
        try:
            # Fetch all contract details for the given symbol
            response = self.futures_client.detail(symbol=symbol)

            # Check if the API call was successful
            if not response.get("success", False):
                raise ValueError(f"Failed to fetch contract details: {response}")

            # Extract the instrument data
            instrument = response["data"]
            if instrument["symbol"] != symbol:
                raise ValueError(f"Symbol {symbol} not found.")

            #print(f"Instrument: {instrument}")
            lot_size = float(instrument["contractSize"])    # Lot size (e.g., 0.0001 BTC per lot)
            min_lots = float(instrument["minVol"])           # Minimum trade size in lots (e.g., 1)
            tick_size = float(instrument["priceUnit"])       # Minimum price change (e.g., 0.1 USDT)
            contract_value = float(instrument["contractSize"])  # Value per contract

            return lot_size, min_lots, tick_size, contract_value

        except KeyError as e:
            raise ValueError(f"Missing expected key: {e}") from e

        except Exception as e:
            print(f"Error fetching symbol details: {str(e)}")
            return None
            
    async def scale_size_and_price(self, symbol: str, size: float, price: float):
        """Scale size and price to match exchange requirements."""
        
        # Fetch symbol details (e.g., contract value, lot size, tick size)
        lot_size, min_lots, tick_size, contract_value = await self.get_symbol_details(symbol)
        print(f"Symbol {symbol} -> Lot Size: {lot_size}, Min Size: {min_lots}, Tick Size: {tick_size}, Contract Value: {contract_value}")
        
        # Step 1: Calculate the number of lots required
        print(f"Desired size: {size}")
        size_in_lots = calculate_lots(size, contract_value)
        print(f"Size in lots: {size_in_lots}")

        # Step 2: Ensure the size meets the minimum size requirement
        sign = -1 if size_in_lots < 0 else 1  # Capture the original sign
        size_in_lots = max(abs(size_in_lots), min_lots)  # Work with absolute value
        size_in_lots *= sign  # Reapply the original sign
        print(f"Size after checking min: {size_in_lots}")

        # Step 3: Round the price to the nearest tick size
        print(f"Price before: {price}")
        price = round_to_tick_size(price, tick_size)
        print(f"Price after tick rounding: {price}")

        return size_in_lots, price
    
    async def _place_limit_order_test(self, ):
        """Place a limit order on MEXC Futures."""
        try:
            # Test limit order
            # https://mexcdevelop.github.io/apidocs/contract_v1_en/#order-under-maintenance
            symbol="BTC_USDT"
            side=1 # 1 open long , 2 close short, 3 open short , 4 close l
            price=62530
            size=0.001 # in quantity of symbol
            leverage=3
            order_type=1 # Limit order
            mex_margin_mode=1 # 1:isolated 2:cross
            client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

            # Fetch and scale the size and price
            lots, price = await self.scale_size_and_price(symbol, size, price)
            print(f"Ordering {lots} lots @ {price}")
            #quit()
            
            order = self.futures_client.order(
                symbol=symbol,
                price=price,
                vol=lots,
                side=side,
                type=order_type,
                open_type=mex_margin_mode,
                leverage=leverage,
                external_oid=client_oid
            )
            print(f"Limit Order Placed: {order}")
        except Exception as e:
            print(f"Error placing limit order: {str(e)}")
        
    async def open_market_position(self, symbol: str, side: str, size: float, leverage: int, margin_mode: str, scale_lot_size: bool = True):
        """Open a market position."""
        try:
            client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
            
            # If the size is already in lot size, don't scale it
            lots = (await self.scale_size_and_price(symbol, size, price=0))[0] if scale_lot_size else size
            print(f"Processing {lots} lots of {symbol} with a {side} order")
            
            mexc_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
            
            order = self.futures_client.order(
                symbol=symbol,
                vol=lots,
                side=side,
                price=0,  # Market order
                type=2,  # Market order
                open_type=mexc_margin_mode,
                leverage=leverage,
                external_oid=client_oid
            )
            print(f"Market Order Placed: {order}")
            return order
        except Exception as e:
            print(f"Error placing market order: {str(e)}")

    async def close_position(self, symbol: str):
        """Close the open position."""
        try:
            positions = await self.fetch_open_positions(symbol)
            if not positions:
                print(f"No open position found for {symbol}.")
                return None

            position = positions[0]
            size = abs(float(position["vol"]))
            side = 2 if position["posSide"] == 1 else 4  # Reverse side

            print(f"Closing {size} lots of {symbol} with market order.")
            return await self.open_market_position(symbol, side, size, leverage=int(position["leverage"]))
        except Exception as e:
            print(f"Error closing position: {str(e)}")
            
    async def reconcile_position(self, symbol: str, size: float, leverage: int, margin_mode: str):
        """
        Reconcile the current position with the target size, leverage, and margin mode.
        """
        try:
            unified_positions = await self.fetch_and_map_positions(symbol)
            current_position = unified_positions[0] if unified_positions else None

            if size != 0:
                size, _ = await self.scale_size_and_price(symbol, size, price=0)  # No price for market orders

            # Initialize position state variables
            current_size = current_position.size if current_position else 0
            current_margin_mode = current_position.margin_mode if current_position else None
            current_leverage = current_position.leverage if current_position else None

            # Determine if we need to close the current position before opening a new one
            if (current_size > 0 and size < 0) or (current_size < 0 and size > 0):
                print(f"Flipping position from {current_size} to {size}. Closing current position.")
                await self.close_position(symbol)  # Close the current position
                current_size = 0 # Update current size to 0 after closing the position

            # Check for margin mode or leverage changes
            if current_size != 0 and size != 0:
                if current_margin_mode != margin_mode:

                    print(f"Closing position to modify margin mode to {margin_mode}.")
                    await self.close_position(symbol)  # Close the current position
                    current_size = 0 # Update current size to 0 after closing the position

                    print(f"Adjusting account margin mode to {margin_mode}.")
                    mexc_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
                    try:
                        self.trade_client.modify_margin_mode(
                            symbol=symbol,
                            marginMode=mexc_margin_mode,
                        )
                    except Exception as e:
                        print(f"Margin Mode unchanged: {str(e)}")

                # if the leverage is not within a 10% tolerance, close the position
                if current_leverage > 0 and abs(current_leverage - leverage) > 0.10 * leverage and current_size != 0:
                    print("KuCoin does not allow adjustment for leverage on an open position.")
                    print(f"Closing position to modify leverage from {current_leverage} to {leverage}.")
                    await self.close_position(symbol)  # Close the current position
                    current_size = 0 # Update current size to 0 after closing the position

            # Calculate the remaining size difference after any position closure
            size_diff = size - current_size
            print(f"Current size: {current_size}, Target size: {size}, Size difference: {size_diff}")

            if size_diff == 0:
                print(f"Position for {symbol} is already at the target size.")
                return

            # Determine the side of the new order (buy/sell)
            side = 1 if size_diff > 0 else 3
            size_diff = abs(size_diff)  # Work with absolute size for the order

            print(f"Placing a {side} order with {leverage}x leverage to adjust position by {size_diff}.")
            await self.open_market_position(
                symbol=symbol,
                side=side,
                size=size_diff,
                leverage=leverage,
                margin_mode=margin_mode,
                scale_lot_size=False
            )
        except Exception as e:
            print(f"Error reconciling position: {str(e)}")

    async def test_symbol_formats(self):
        """Test function to dump symbol information for mapping."""
        try:
            # Test common symbols
            test_symbols = ["BTC_USDT", "ETH_USDT"]
            
            for symbol in test_symbols:
                try:
                    # Get contract details
                    contract = self.futures_client.detail(symbol=symbol)
                    
                    print(f"\nMEXC Symbol Information for {symbol}:")
                    print(f"Native Symbol Format: {symbol}")
                    print(f"Full Response: {contract}")
                    
                    # Try to fetch a ticker to verify symbol works
                    ticker = await self.fetch_tickers(symbol)
                    print(f"Ticker Test: {ticker}")
                    
                except Exception as e:
                    print(f"Error testing {symbol}: {str(e)}")
                    
        except Exception as e:
            print(f"Error in symbol format test: {str(e)}")


async def main():
    
    # Start a time
    start_time = datetime.datetime.now()
    
    mexc = MEXC()
    
    # balance = await mexc.fetch_balance(instrument="USDT")      # Fetch futures balance
    # print(balance)
    
    # tickers = await mexc.fetch_tickers(symbol="BTC_USDT")  # Fetch market tickers
    # print(tickers)
    
    # order_results = await mexc._place_limit_order_test()
    # print(order_results)
    
    # open_order = await mexc.open_market_position(
    #     symbol="BTC_USDT",
    #     side=1, # 1 open long , 2 close short, 3 open short , 4 close l
    #     size=0.002,
    #     leverage=5,
    # )
    # print(open_order)

    # import time
    # time.sleep(5)  # Wait for a bit to ensure the order is processed
    
    # Example usage of reconcile_position to adjust position to the desired size, leverage, and margin type
    await mexc.reconcile_position(
        symbol="BTC_USDT",   # Symbol to adjust
        size=-0.001,  # Desired position size (positive for long, negative for short, zero to close)
        leverage=3,         # Desired leverage (only applies to new positions and averaged for existing ones)
        margin_mode="isolated"  # 1:isolated 2:cross
    )    

    # Close the position
    # close_order = await mexc.close_position(symbol="BTC_USDT")
    # print(close_order)
    
    # orders = await mexc.fetch_open_orders(symbol="BTC_USDT")          # Fetch open orders
    # print(orders)
    
    # #await mexc.fetch_open_positions(symbol="BTC_USDT")       # Fetch open positions
    # positions = await mexc.fetch_and_map_positions(symbol="BTC_USDT")
    # #print(positions)
    
    # End time
    end_time = datetime.datetime.now()
    print(f"Time taken: {end_time - start_time}")

if __name__ == "__main__":
    asyncio.run(main())
