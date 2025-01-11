import asyncio
import datetime
from kucoin_futures.client import UserData, Trade, Market # https://github.com/Kucoin/kucoin-futures-python-sdk
from config.credentials import load_kucoin_credentials
from core.utils.modifiers import round_to_tick_size, calculate_lots
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
        
        self.margin_mode_map = {
            "isolated": "ISOLATED",
            "cross": "CROSS"
        }

        self.inverse_margin_mode_map = {v: k for k, v in self.margin_mode_map.items()}

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
        
    # fetch all open positions
    async def fetch_all_open_positions(self):
        try:
            positions = self.trade_client.get_all_position()
            #print(f"All Open Positions: {positions}")
            return positions
        except Exception as e:
            print(f"Error fetching all open positions: {str(e)}")

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

    async def fetch_and_map_positions(self, symbol: str):
        """Fetch and map KuCoin positions to UnifiedPosition."""
        try:
            positions = self.trade_client.get_position_details(symbol=symbol)

            # Convert each position to UnifiedPosition
            unified_positions = [
                self.map_kucoin_position_to_unified(pos) 
                for pos in [positions] 
                if float(pos.get("currentQty", 0)) != 0
            ]

            for unified_position in unified_positions:
                print(f"Unified Position: {unified_position}")

            return unified_positions
        except Exception as e:
            print(f"Error mapping KuCoin positions: {str(e)}")
            return []
            
    def map_kucoin_position_to_unified(self, position: dict) -> UnifiedPosition:
        """Convert a KuCoin position response into a UnifiedPosition object."""
        size = abs(float(position.get("currentQty", 0)))  # Handle long/short positions
        direction = "long" if float(position.get("currentQty", 0)) > 0 else "short"
        # adjust size for short positions
        if direction == "short":
            size = -size
            
        # Use provided margin mode if available, otherwise derive from tradeMode
        kucoin_margin_mode = position.get("marginMode")
        if kucoin_margin_mode is None:
            raise ValueError("Margin mode not found in position data.")
        
        margin_mode = self.inverse_margin_mode_map.get(kucoin_margin_mode, kucoin_margin_mode)
            
        return UnifiedPosition(
            symbol=position["symbol"],
            size=size,
            average_entry_price=float(position.get("avgEntryPrice", 0)),
            leverage=float(position.get("leverage", 1)),
            direction=direction,
            unrealized_pnl=float(position.get("unrealisedPnl", 0)),
            margin_mode=margin_mode,
            exchange=self.exchange_name,
        )
        
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

    async def get_symbol_details(self, symbol: str):
        """Fetch instrument details including tick size, lot size, and contract value."""
        # Fetch the instrument details from the market client
        instrument = self.market_client.get_contract_detail(symbol)

        # Check if the response contains the desired symbol
        if instrument["symbol"] == symbol:
            #print(f"Instrument: {instrument}")
            lot_size = float(instrument["multiplier"])  # Lot size (e.g., 1)
            min_lots = float(instrument["lotSize"])  # Minimum order size in lots
            tick_size = float(instrument["tickSize"])  # Tick size for price (e.g., 0.1)
            contract_value = float(instrument["multiplier"])  # Contract value (e.g., 0.001 BTC per lot)

            return lot_size, min_lots, tick_size, contract_value
        raise ValueError(f"Symbol {symbol} not found.")
    
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

        return size_in_lots, price, lot_size
    
    async def _place_limit_order_test(self, ):
        """Place a limit order on KuCoin Futures."""
        try:
            # Test limit order
            # https://www.kucoin.com/docs/rest/futures-trading/orders/place-order
            # NOTE: althought we can pass the margin mode, it must match with the user interface
            symbol="XBTUSDTM"
            side="buy" # buy, sell
            price=62957
            size=0.003 # in quantity of symbol
            leverage=3
            order_type="limit" # limit or market
            time_in_force="IOC" # GTC, GTT, IOC, FOK (IOC as FOK has unexpected behavior)
            kucoin_margin_mode="ISOLATED" # ISOLATED, CROSS, default: ISOLATED
            client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

            # Fetch and scale the size and price
            lots, price, _ = await self.scale_size_and_price(symbol, size, price)
            print(f"Ordering {lots} lots @ {price}")
            #quit()
            
            # set margin mode    
            try:
                self.trade_client.modify_margin_mode(
                    symbol=symbol,
                    marginMode=kucoin_margin_mode,
                )
            except Exception as e:
                print(f"Margin Mode unchanged: {str(e)}")
            
            #create_limit_order(self, symbol, side, lever, size, price, clientOid='', **kwargs):
            order_id = self.trade_client.create_limit_order(
                symbol=symbol,
                side=side.lower(),
                price=price,
                size=lots,
                lever=leverage,
                orderType=order_type,
                timeInForce=time_in_force,
                marginMode=kucoin_margin_mode,
                clientOid=client_oid
            )
            print(f"Limit Order Placed: {order_id}")
        except Exception as e:
            print(f"Error placing limit order: {str(e)}")

    async def open_market_position(self, symbol: str, side: str, size: float, leverage: int, margin_mode: str, scale_lot_size: bool = True, adjust_margin_mode: bool = True):
        """Open a position with a market order on KuCoin Futures."""
        try:
            
            print(f"HERE: Opening a {side} position for {size} lots of {symbol} with {leverage}x leverage.")
            
            client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

            # If the size is already in lot size, don't scale it
            lots = (await self.scale_size_and_price(symbol, size, price=0))[0] if scale_lot_size else size
            print(f"Processing {lots} lots of {symbol} with a {side} order")
            
            kucoin_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
            
            if adjust_margin_mode:
                print(f"Adjusting account margin mode to {kucoin_margin_mode}.")
                try:
                    self.trade_client.modify_margin_mode(
                        symbol=symbol,
                        marginMode=kucoin_margin_mode,
                    )
                except Exception as e:
                    print(f"Margin Mode unchanged: {str(e)}")
                    
            print(f"Placing a market order for {lots} lots of {symbol} with {kucoin_margin_mode} margin mode and {leverage}x leverage.")
            

            # Place the market order
            order = self.trade_client.create_market_order(
                symbol=symbol,
                side=side.lower(),
                size=lots,
                lever=leverage,
                clientOid=client_oid,
                marginMode=kucoin_margin_mode,
            )
            print(f"Market Order Placed: {order}")
            return order

        except Exception as e:
            print(f"Error placing market order: {str(e)}")

    async def close_position(self, symbol: str):
        """Close the open position for a specific symbol on KuCoin Futures."""
        try:
            # Fetch open positions
            position = await self.fetch_open_positions(symbol)
            if not position:
                print(f"No open position found for {symbol}.")
                return None

            # Extract position details
            size = abs(float(position["currentQty"]))  # Use absolute size for closing
            side = "sell" if float(position["currentQty"]) > 0 else "buy"  # Reverse side to close

            print(f"Closing {size} lots of {symbol} with market order.")

            # Place the market order to close the position
            close_order = await self.open_market_position(
                symbol=symbol,
                side=side.lower(),
                size=size,
                leverage=int(position["leverage"]),
                margin_mode=position["marginMode"], # this is kucoin margin mode
                scale_lot_size=False,
            )
            print(f"Position Closed: {close_order}")
            return close_order

        except Exception as e:
            print(f"Error closing position: {str(e)}")
            
    async def reconcile_position(self, symbol: str, size: float, leverage: int, margin_mode: str):
        """
        Reconcile the current position with the target size, leverage, and margin mode.
        """
        try:
            unified_positions = await self.fetch_and_map_positions(symbol)
            current_position = unified_positions[0] if unified_positions else None

            # Scale the target size to match exchange requirements
            if size != 0:
                size, _, lot_size = await self.scale_size_and_price(symbol, size, price=0)  # No price needed for market orders

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

                    # print(f"Adjusting account margin mode to {margin_mode}.")
                    # kucoin_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
                    # try:
                    #     self.trade_client.modify_margin_mode(
                    #         symbol=symbol,
                    #         marginMode=kucoin_margin_mode,
                    #     )
                    # except Exception as e:
                    #     print(f"Margin Mode unchanged: {str(e)}")

                # if the leverage is not within a 10% tolerance, close the position
                if current_leverage > 0 and abs(current_leverage - leverage) > 0.10 * leverage and current_size != 0:
                    print("KuCoin does not allow adjustment for leverage on an open position.")
                    print(f"Closing position to modify leverage from {current_leverage} to {leverage}.")
                    await self.close_position(symbol)  # Close the current position
                    current_size = 0 # Update current size to 0 after closing the position

            # Calculate size difference with proper precision
            size_diff = size - current_size
            decimal_places = len(str(lot_size).split('.')[-1]) if '.' in str(lot_size) else 0
            size_diff = float(f"%.{decimal_places}f" % size_diff)
            
            print(f"Current size: {current_size}, Target size: {size}, Size difference: {size_diff}")

            if size_diff == 0:
                print(f"Position for {symbol} is already at the target size.")
                return

            # Determine the side of the new order (buy/sell)
            side = "Buy" if size_diff > 0 else "Sell"
            size_diff = abs(size_diff)  # Work with absolute size for the order

            print(f"Placing a {side} order with {leverage}x leverage to adjust position by {size_diff}.")
            await self.open_market_position(
                symbol=symbol,
                side=side.lower(),
                size=size_diff,
                leverage=leverage,
                margin_mode=margin_mode,
                scale_lot_size=False,
                adjust_margin_mode=current_size == 0,
            )
        except Exception as e:
            print(f"Error reconciling position: {str(e)}")

    async def test_symbol_formats(self):
        """Test function to dump symbol information for mapping."""
        try:
            # Test common symbols
            test_symbols = ["XBTUSDTM", "ETHUSDTM"]
            
            for symbol in test_symbols:
                try:
                    # Get contract details
                    contract = self.market_client.get_contract_detail(symbol)
                    
                    print(f"\nKuCoin Symbol Information for {symbol}:")
                    print(f"Native Symbol Format: {symbol}")
                    #print(f"Full Response: {contract}")
                    
                    # Try to fetch a ticker to verify symbol works
                    ticker = await self.fetch_tickers(symbol)
                    #print(f"Ticker Test: {ticker}")
                    
                except Exception as e:
                    print(f"Error testing {symbol}: {str(e)}")
                    
            # Test symbol mapping
            test_signals = ["BTCUSDT", "ETHUSDT"]
            print("\nTesting symbol mapping:")
            for symbol in test_signals:
                mapped = self.map_signal_symbol_to_exchange(symbol)
                print(f"Signal symbol: {symbol} -> Exchange symbol: {mapped}")
                
        except Exception as e:
            print(f"Error in symbol format test: {str(e)}")

    def map_signal_symbol_to_exchange(self, signal_symbol: str) -> str:
        """Convert signal symbol format (e.g. BTCUSDT) to exchange format."""
        # KuCoin uses XBTUSDTM for BTC and adds M suffix for others
        if "USDT" in signal_symbol:
            base = signal_symbol.replace("USDT", "")
            # Special case for BTC
            if base == "BTC":
                return "XBTUSDTM"
            return f"{base}USDTM"
        return signal_symbol

    async def fetch_total_account_value(self) -> float:
        """Calculate total account value from balance and initial margin of positions."""
        try:
            # Get available balance
            balance = await self.fetch_balance("USDT")
            available_balance = float(balance) if balance else 0.0
            print(f"Available Balance: {available_balance} USDT")
            
            # Get positions directly - KuCoin provides posInit (initial margin)
            positions = await self.fetch_all_open_positions()
            position_margin = 0.0
            for pos in positions:
                position_margin += float(pos["posInit"])  # Direct initial margin value
            print(f"Position Initial Margin: {position_margin} USDT")
            
            total_value = available_balance + position_margin
            print(f"KuCoin Total Account Value: {total_value} USDT")
            return total_value
            
        except Exception as e:
            print(f"Error calculating total account value: {str(e)}")
            return 0.0


async def main():
    
    # Start a time
    start_time = datetime.datetime.now()
    
    kucoin = KuCoin()
    
    # balance = await kucoin.fetch_balance(instrument="USDT")      # Fetch futures balance
    # print(balance)

    # tickers = await kucoin.fetch_tickers(symbol="XBTUSDTM")  # Fetch market tickers
    # print(tickers)
    
    # order_results = await kucoin._place_limit_order_test()
    # print(order_results)
    
    # # Open a market position
    # open_order = await kucoin.open_market_position(
    #     symbol="XBTUSDTM",
    #     side="sell",
    #     size=0.002,
    #     leverage=5,
    #     margin_mode="ISOLATED",
    # )
    # print(open_order)

    # import time
    # time.sleep(5)  # Wait for a bit to ensure the order is processed

    # Example usage of reconcile_position to adjust position to the desired size, leverage, and margin type
    #await kucoin.reconcile_position(
    #    symbol="XBTUSDTM",   # Symbol to adjust
    #    size=0,  # Desired position size (positive for long, negative for short, zero to close)
    #    leverage=3,         # Desired leverage (only applies to new positions and averaged for existing ones)
    #    margin_mode="isolated"  # Desired margin mode (position must be closed to adjust)
    #)
    
    # # Close the position
    # close_order = await kucoin.close_position(symbol="XBTUSDTM")
    # print(close_order)
    
    # orders = await kucoin.fetch_open_orders(symbol="XBTUSDTM")          # Fetch open orders
    # print(orders)    
    
    # #await kucoin.fetch_open_positions(symbol="XBTUSDTM")       # Fetch open positions
    # positions = await kucoin.fetch_and_map_positions(symbol="XBTUSDTM")
    # #print(positions)
    
    # Test symbol formats
    # await kucoin.test_symbol_formats()
    
    # Test total account value calculation
    print("\nTesting total account value calculation:")
    total_value = await kucoin.fetch_total_account_value()
    print(f"Final Total Account Value: {total_value} USDT")
    
    # End time
    end_time = datetime.datetime.now()
    print(f"Time taken: {end_time - start_time}")
    
if __name__ == "__main__":
    asyncio.run(main())
