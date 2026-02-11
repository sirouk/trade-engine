import asyncio
import datetime
from pymexc import futures
from config.credentials import load_mexc_credentials
from core.utils.modifiers import scale_size_and_price
from core.unified_position import UnifiedPosition
from core.unified_ticker import UnifiedTicker
from core.utils.execute_timed import execute_with_timeout


class MEXC:
    def __init__(self):
        
        self.exchange_name = "MEXC"
        self.enabled = False
        self.leverage_tolerance = 0.10
        
        # MEXC Rate Limits: Conservative limit for futures API
        self.MAX_CONCURRENT_SYMBOL_REQUESTS = 5
        
        # Add logger prefix
        self.log_prefix = f"[{self.exchange_name}]"
        
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

        self.leverage_override = self.credentials.mexc.leverage_override

    async def fetch_balance(self, instrument="USDT"):
        """Fetch the futures account balance for a specific instrument."""
        try:
            async with asyncio.timeout(5):
                balance = await execute_with_timeout(
                    self.futures_client.asset,
                    timeout=5,
                    currency=instrument
                )

            # Check if the API call was successful
            if not balance.get("success", False):
                raise ValueError(f"Failed to fetch assets: {balance}")

            # Extract the data from the response
            balance = balance.get("data", {})
            balance = balance.get("availableBalance", 0)

            print(f"{self.log_prefix} Account Balance for {instrument}: {balance}")
            return balance
        except Exception as e:
            print(f"{self.log_prefix} Error fetching balance: {str(e)}")
            
    # fetch all open positions
    async def fetch_all_open_positions(self):
        try:
            positions = await execute_with_timeout(
                self.futures_client.open_positions,
                timeout=5,
                symbol=None
            )
            #print(f"All Open Positions: {positions}")
            return positions
        except Exception as e:
            print(f"{self.log_prefix} Error fetching all open positions: {str(e)}")

    async def fetch_open_positions(self, symbol):
        """Fetch open futures positions."""
        try:
            positions = await execute_with_timeout(
                self.futures_client.open_positions,
                timeout=5,
                symbol=symbol
            )
            print(f"{self.log_prefix} Open Positions: {positions}")
            return positions.get("data", [])
        except Exception as e:
            print(f"{self.log_prefix} Error fetching open positions: {str(e)}")

    async def fetch_open_orders(self, symbol):
        """Fetch open futures orders."""
        try:
            response = await execute_with_timeout(
                self.futures_client.open_orders,
                timeout=5,
                symbol=symbol
            )
            print(f"{self.log_prefix} Open Orders: {response}")
            return response.get("data", [])
        except Exception as e:
            print(f"{self.log_prefix} Error fetching open orders: {str(e)}")

    async def fetch_and_map_positions(self, symbol: str):
        """Fetch and map MEXC positions to UnifiedPosition."""
        try:
            response = await execute_with_timeout(
                self.futures_client.open_positions,
                timeout=5,
                symbol=symbol
            )
            positions = response.get("data", [])

            unified_positions = [
                self.map_mexc_position_to_unified(pos) 
                for pos in positions 
                if float(pos.get("vol", 0)) != 0
            ]

            for unified_position in unified_positions:
                print(f"{self.log_prefix} Unified Position: {unified_position}")

            return unified_positions
        except Exception as e:
            print(f"{self.log_prefix} Error mapping MEXC positions: {str(e)}")
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
            ticker = await execute_with_timeout(
                self.futures_client.ticker,
                timeout=5,
                symbol=symbol
            )
            ticker_data = ticker.get("data", {})
            
            # Quantity traded in the last 24 hours
            amount24 = float(ticker_data.get("amount24", 0))
            lastPrice = float(ticker_data.get("lastPrice", 0))

            print(f"{self.log_prefix} Ticker: {ticker_data}")
            return UnifiedTicker(
                symbol=symbol,
                bid=float(ticker_data.get("bid1", 0)),
                ask=float(ticker_data.get("ask1", 0)),
                last=float(ticker_data.get("lastPrice", 0)),
                volume=float(amount24 / lastPrice),
                exchange=self.exchange_name
            )
        except Exception as e:
            print(f"{self.log_prefix} Error fetching tickers from MEXC: {str(e)}")

    async def get_symbol_details(self, symbol: str):
        """Fetch instrument details including lot size, min size, tick size, max size, and contract value."""
        try:
            # Fetch all contract details for the given symbol
            response = await execute_with_timeout(
                self.futures_client.detail,
                timeout=5,
                symbol=symbol
            )

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
            # MEXC uses maxVol for maximum order quantity
            max_size = float(instrument.get("maxVol", 1000000))  # Default to large number if not specified

            return lot_size, min_lots, tick_size, contract_value, max_size

        except KeyError as e:
            raise ValueError(f"Missing expected key: {e}") from e

        except Exception as e:
            print(f"{self.log_prefix} Error fetching symbol details: {str(e)}")
            return None
    
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
            
            # Fetch symbol details (e.g., contract value, lot size, tick size)
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(symbol)

            # Fetch and scale the size and price
            lots, price, _ = scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value)
            print(f"{self.log_prefix} Ordering {lots} lots @ {price}")
            #quit()
            
            order = await execute_with_timeout(
                self.futures_client.order,
                timeout=5,
                symbol=symbol,
                price=price,
                vol=lots,
                side=side,
                type=order_type,
                open_type=mex_margin_mode,
                leverage=leverage,
                external_oid=client_oid
            )
            print(f"{self.log_prefix} Limit Order Placed: {order}")
        except Exception as e:
            print(f"{self.log_prefix} Error placing limit order: {str(e)}")

    async def open_market_position(self, symbol: str, side: str, size: float, leverage: int, margin_mode: str, scale_lot_size: bool = True):
        """Open a market position."""
        try:
            # Fetch symbol details (e.g., contract value, lot size, tick size)
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(symbol)
            
            # If the size is already in lot size, don't scale it
            lots = (scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value))[0] if scale_lot_size else size
            print(f"{self.log_prefix} Processing {lots} lots of {symbol} with a {side} order")
            
            mexc_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
            
            # Check if order size exceeds maximum order quantity
            if lots > max_size:
                print(f"{self.log_prefix} Order size {lots} exceeds max order qty {max_size}. Splitting into chunks.")
                
                # Calculate number of full chunks and remainder
                num_full_chunks = int(lots // max_size)
                remainder = lots % max_size
                
                # Round remainder to lot size precision
                decimal_places = len(str(lot_size).rsplit('.', maxsplit=1)[-1]) if '.' in str(lot_size) else 0
                remainder = float(f"%.{decimal_places}f" % remainder)
                
                orders = []
                total_executed = 0
                
                # Place full-sized chunks
                for i in range(num_full_chunks):
                    chunk_size = max_size
                    print(f"{self.log_prefix} Placing chunk {i+1}/{num_full_chunks + (1 if remainder > 0 else 0)}: {chunk_size} lots")
                    
                    client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
                    
                    order = await execute_with_timeout(
                        self.futures_client.order,
                        timeout=5,
                        symbol=symbol,
                        vol=chunk_size,
                        side=side,
                        price=0,  # Market order
                        type=2,  # Market order
                        open_type=mexc_margin_mode,
                        leverage=leverage,
                        external_oid=client_oid
                    )
                    orders.append(order)
                    total_executed += chunk_size
                    print(f"{self.log_prefix} Chunk order placed: {order}")
                    
                    # Small delay between orders to avoid rate limiting
                    await asyncio.sleep(0.1)
                
                # Place remainder if exists
                if remainder > 0:
                    print(f"{self.log_prefix} Placing final chunk: {remainder} lots")
                    client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
                    
                    order = await execute_with_timeout(
                        self.futures_client.order,
                        timeout=5,
                        symbol=symbol,
                        vol=remainder,
                        side=side,
                        price=0,  # Market order
                        type=2,  # Market order
                        open_type=mexc_margin_mode,
                        leverage=leverage,
                        external_oid=client_oid
                    )
                    orders.append(order)
                    total_executed += remainder
                    print(f"{self.log_prefix} Final chunk order placed: {order}")
                
                print(f"{self.log_prefix} Successfully executed {total_executed} lots across {len(orders)} orders")
                return orders  # Return list of orders
            
            else:
                # Order size is within limits, proceed normally
                client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
                
                order = await execute_with_timeout(
                    self.futures_client.order,
                    timeout=5,  # Specify custom timeout
                    symbol=symbol,
                    vol=lots,
                    side=side,
                    price=0,  # Market order
                    type=2,  # Market order
                    open_type=mexc_margin_mode,
                    leverage=leverage,
                    external_oid=client_oid
                )
                print(f"{self.log_prefix} Market Order Placed: {order}")
                return order

        except Exception as e:
            print(f"{self.log_prefix} Error placing market order: {str(e)}")

    async def close_position(self, symbol: str):
        """Close the open position."""
        try:
            positions = await self.fetch_open_positions(symbol)
            if not positions:
                print(f"{self.log_prefix} No open position found for {symbol}.")
                return None

            position = positions[0]
            size = abs(float(position["vol"]))
            side = 2 if position["posSide"] == 1 else 4  # Reverse side

            print(f"{self.log_prefix} Closing {size} lots of {symbol} with market order.")
            # Get margin mode from position (1: isolated, 2: cross)
            mexc_margin_mode = position.get("open_type", 1)
            margin_mode = self.inverse_margin_mode_map.get(mexc_margin_mode, "isolated")
            return await self.open_market_position(symbol, side, size, leverage=int(position["leverage"]), margin_mode=margin_mode)
        except Exception as e:
            print(f"{self.log_prefix} Error closing position: {str(e)}")
            
    async def reconcile_position(self, symbol: str, size: float, leverage: int, margin_mode: str):
        """
        Reconcile the current position with the target size, leverage, and margin mode.
        """
        try:
            # First check if account is enabled
            if not self.enabled:
                return
            
            # Get current positions
            positions = await self.fetch_open_positions(symbol)
            current_position = positions[0] if positions else None
            
            # Initialize current_leverage to None
            current_leverage = None
            if current_position:
                current_leverage = float(current_position.get("leverage", 0))
            
            # Use leverage override if set
            if self.leverage_override > 0:
                print(f"{self.log_prefix} Using exchange-specific leverage override: {self.leverage_override}")
                leverage = self.leverage_override
                
            unified_positions = await self.fetch_and_map_positions(symbol)
            current_position = unified_positions[0] if unified_positions else None
            
            # Fetch symbol details (e.g., contract value, lot size, tick size)
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(symbol)
            
            #if size != 0:
            # Always scale as we need lot_size
            size, _, lot_size = scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value)  # No price for market orders

            # Initialize position state variables
            current_size = current_position.size if current_position else 0
            current_margin_mode = current_position.margin_mode if current_position else None

            # Determine if we need to close the current position before opening a new one
            if (current_size > 0 and size < 0) or (current_size < 0 and size > 0):
                print(f"{self.log_prefix} Flipping position from {current_size} to {size}. Closing current position.")
                await self.close_position(symbol)  # Close the current position
                current_size = 0 # Update current size to 0 after closing the position

            # Check for margin mode or leverage changes
            if current_size != 0 and size != 0:
                if current_margin_mode != margin_mode:

                    print(f"{self.log_prefix} Closing position to modify margin mode to {margin_mode}.")
                    await self.close_position(symbol)  # Close the current position
                    current_size = 0 # Update current size to 0 after closing the position

                    print(f"{self.log_prefix} Adjusting account margin mode to {margin_mode}.")
                    mexc_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
                    try:
                        await execute_with_timeout(
                            self.futures_client.modify_margin_mode,
                            timeout=5,
                            symbol=symbol,
                            marginMode=mexc_margin_mode,
                        )
                    except Exception as e:
                        print(f"{self.log_prefix} Margin Mode unchanged: {str(e)}")

            # if the leverage is not within a 10% tolerance, close the position
            if current_leverage is not None and current_leverage > 0 and abs(current_leverage - leverage) > self.leverage_tolerance * leverage and current_size != 0 and abs(size) > 0:
                print("KuCoin does not allow adjustment for leverage on an open position.")
                print(f"Closing position to modify leverage from {current_leverage} to {leverage}.")
                await self.close_position(symbol)  # Close the current position
                current_size = 0 # Update current size to 0 after closing the position

            # Calculate size difference with proper precision
            decimal_places = len(str(lot_size).rsplit('.', maxsplit=1)[-1]) if '.' in str(lot_size) else 0
            size_diff = float(f"%.{decimal_places}f" % (size - current_size))
            
            # Tolerance logic to prevent unnecessary trades:
            # 1. If closing position (target=0): only skip if already below tradable minimum (current < min_lots)
            # 2. If opening position (current=0): always proceed
            # 3. If both non-zero: use tolerance (lot_size or 0.1% of position) to avoid tiny adjustments
            if size == 0:
                # Closing position: only skip if current size is strictly below min tradable lot.
                # If size equals min_lots, it is still a real open position and must be closed.
                if abs(current_size) < min_lots:
                    print(f"{self.log_prefix} Position for {symbol} is already effectively closed (size={abs(current_size):.6f} < min={min_lots}).")
                    return
                # Otherwise, always close (size_diff ensures we proceed)
            elif abs(current_size) == 0:
                # Opening position: always proceed
                pass
            else:
                # Both non-zero: use tolerance to avoid unnecessary trades
                # Tolerance = max(lot_size, 0.1% of smaller position value)
                position_tolerance = max(lot_size, min(abs(current_size), abs(size)) * 0.001)
                
                if abs(size_diff) < position_tolerance:
                    print(f"{self.log_prefix} Position for {symbol} is already at target size (current={current_size:.6f}, target={size:.6f}, diff={size_diff:.6f}, tolerance={position_tolerance:.6f}).")
                    return
            
            print(f"{self.log_prefix} Adjusting position: current={current_size:.6f}, target={size:.6f}, diff={size_diff:.6f}")

            # Determine the side of the new order (buy/sell)
            side = 1 if size_diff > 0 else 3
            size_diff = abs(size_diff)  # Work with absolute size for the order

            print(f"{self.log_prefix} Placing a {side} order with {leverage}x leverage to adjust position by {size_diff}.")
            await self.open_market_position(
                symbol=symbol,
                side=side,
                size=size_diff,
                leverage=leverage,
                margin_mode=margin_mode,
                scale_lot_size=False
            )
        except Exception as e:
            print(f"{self.log_prefix} Error reconciling position: {str(e)}")

    async def test_symbol_formats(self):
        """Test function to dump symbol information for mapping."""
        try:
            # Test common symbols
            test_symbols = ["BTC_USDT", "ETH_USDT"]
            
            for symbol in test_symbols:
                try:
                    # Get contract details
                    contract = await execute_with_timeout(
                        self.futures_client.detail,
                        timeout=5,
                        symbol=symbol
                    )
                    
                    print(f"\n{self.log_prefix} MEXC Symbol Information for {symbol}:")
                    print(f"{self.log_prefix} Native Symbol Format: {symbol}")
                    #print(f"Full Response: {contract}")
                    
                    # Try to fetch a ticker to verify symbol works
                    ticker = await self.fetch_tickers(symbol)
                    #print(f"Ticker Test: {ticker}")
                    
                except Exception as e:
                    print(f"{self.log_prefix} Error testing {symbol}: {str(e)}")
                    
            # Test symbol mapping
            test_signals = ["BTCUSDT", "ETHUSDT"]
            print(f"{self.log_prefix} Testing symbol mapping:")
            for symbol in test_signals:
                mapped = self.map_signal_symbol_to_exchange(symbol)
                print(f"{self.log_prefix} Signal symbol: {symbol} -> Exchange symbol: {mapped}")
                
        except Exception as e:
            print(f"{self.log_prefix} Error in symbol format test: {str(e)}")

    def map_signal_symbol_to_exchange(self, signal_symbol: str) -> str:
        """Convert signal symbol format (e.g. BTCUSDT) to exchange format."""
        # MEXC uses underscore separator
        if "USDT" in signal_symbol:
            base = signal_symbol.replace("USDT", "")
            return f"{base}_USDT"
        return signal_symbol

    async def fetch_initial_account_value(self) -> float:
        """Calculate total account value from balance and initial margin of positions."""
        try:
            # Get available balance
            balance = await self.fetch_balance("USDT")
            available_balance = float(balance) if balance else 0.0
            print(f"{self.log_prefix} Available Balance: {available_balance} USDT")
            
            # Get positions directly - MEXC provides im (current margin)
            positions = await self.fetch_all_open_positions()
            position_margin = 0.0
            if positions and "data" in positions:
                for pos in positions["data"]:
                    position_margin += float(pos["im"])  # Current margin value
            print(f"{self.log_prefix} Position Initial Margin: {position_margin} USDT")
            
            total_value = available_balance + position_margin
            print(f"{self.log_prefix} MEXC Initial Account Value: {total_value} USDT")
            return total_value
            
        except Exception as e:
            print(f"{self.log_prefix} Error calculating initial account value: {str(e)}")
            return 0.0


async def main():
    
    # Start a time
    start_time = datetime.datetime.now()
    
    from core.utils.execute_timed import execute_with_timeout
    
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
    #await mexc.reconcile_position(
    #    symbol="BTC_USDT",   # Symbol to adjust
    #    size=-0.001,  # Desired position size (positive for long, negative for short, zero to close)
    #    leverage=3,         # Desired leverage (only applies to new positions and averaged for existing ones)
    #    margin_mode="isolated"  # 1:isolated 2:cross
    #)    

    # Close the position
    # close_order = await mexc.close_position(symbol="BTC_USDT")
    # print(close_order)
    
    # orders = await mexc.fetch_open_orders(symbol="BTC_USDT")          # Fetch open orders
    # print(orders)
    
    # #await mexc.fetch_open_positions(symbol="BTC_USDT")       # Fetch open positions
    # positions = await mexc.fetch_and_map_positions(symbol="BTC_USDT")
    # #print(positions)
    
    # Test symbol formats
    # await mexc.test_symbol_formats()
    
    # Test total account value calculation
    print(f"{mexc.log_prefix} Testing total account value calculation:")
    total_value = await mexc.fetch_initial_account_value()
    print(f"{mexc.log_prefix} Final Total Account Value: {total_value} USDT")
    
    # Test fetching max order quantity
    print(f"\n{mexc.log_prefix} Testing symbol details and max order quantity:")
    try:
        symbol = "BTC_USDT"
        lot_size, min_size, tick_size, contract_value, max_size = await mexc.get_symbol_details(symbol)
        print(f"{mexc.log_prefix} Symbol: {symbol}")
        print(f"{mexc.log_prefix} Lot Size (contractSize): {lot_size}")
        print(f"{mexc.log_prefix} Min Order Qty (minVol): {min_size}")
        print(f"{mexc.log_prefix} Max Order Qty (maxVol): {max_size}")
        print(f"{mexc.log_prefix} Tick Size (priceUnit): {tick_size}")
        print(f"{mexc.log_prefix} Contract Value: {contract_value}")
        
        # Get full contract details
        response = await execute_with_timeout(
            mexc.futures_client.detail,
            timeout=5,
            symbol=symbol
        )
        if response.get("success", False):
            contract = response["data"]
            print(f"\n{mexc.log_prefix} Full contract details for {symbol}:")
            for key in ["maxVol", "minVol", "contractSize", "priceUnit", "maxLeverage"]:
                if key in contract:
                    print(f"{mexc.log_prefix} {key}: {contract[key]}")
    except Exception as e:
        print(f"{mexc.log_prefix} Error testing symbol details: {str(e)}")
    
    # Test order chunking demonstration (commented out to avoid actual trading)
    """
    print(f"\n{mexc.log_prefix} Testing order chunking with large order:")
    try:
        # This would test chunking if the order exceeds max_size
        result = await mexc.open_market_position(
            symbol="BTC_USDT",
            side=1,  # 1 for buy/long
            size=1000,  # Large size to test chunking
            leverage=5,
            margin_mode="isolated"
        )
        print(f"{mexc.log_prefix} Order result: {result}")
    except Exception as e:
        print(f"{mexc.log_prefix} Error testing order chunking: {str(e)}")
    """
    
    # End time
    end_time = datetime.datetime.now()
    print(f"{mexc.log_prefix} Time taken: {end_time - start_time}")


if __name__ == "__main__":
    asyncio.run(main())
