import asyncio
import datetime
from kucoin_futures.client import UserData, Trade, Market # https://github.com/Kucoin/kucoin-futures-python-sdk
from config.credentials import load_kucoin_credentials
from core.utils.modifiers import scale_size_and_price
from core.unified_position import UnifiedPosition
from core.unified_ticker import UnifiedTicker
from core.utils.execute_timed import execute_with_timeout


class KuCoin:
    def __init__(self):
        self.exchange_name = "KuCoin"
        self.enabled = False
        self.leverage_tolerance = 0.10
        
        # KuCoin Rate Limits: Conservative limit for futures API
        self.MAX_CONCURRENT_SYMBOL_REQUESTS = 5
        
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

        self.leverage_override = self.credentials.kucoin.leverage_override
        
        # Add logger prefix
        self.log_prefix = f"[{self.exchange_name}]"

    async def fetch_balance(self, instrument="USDT"):
        """Fetch futures account balance."""
        try:
            balance = await execute_with_timeout(
                self.user_client.get_account_overview,
                timeout=5,
                currency=instrument
            )
            # {'accountEquity': 0.58268157, 'unrealisedPNL': 0.0, 'marginBalance': 0.58268157, 'positionMargin': 0.0, 'orderMargin': 0.0, 'frozenFunds': 0.0, 'availableBalance': 0.58268157, 'currency': 'USDT'}
            
            # get coin balance available to trade
            balance = balance.get("availableBalance", 0)
            print(f"{self.log_prefix} Account Balance for {instrument}: {balance}")
            return balance
        except Exception as e:
            print(f"{self.log_prefix} Error fetching balance: {str(e)}")
        
    # fetch all open positions
    async def fetch_all_open_positions(self):
        try:
            positions = await execute_with_timeout(
                self.trade_client.get_all_position,
                timeout=5
            )
            return positions
        except Exception as e:
            print(f"{self.log_prefix} Error fetching all open positions: {str(e)}")

    async def fetch_open_positions(self, symbol):
        """Fetch open futures positions."""
        try:
            positions = await execute_with_timeout(
                self.trade_client.get_position_details,
                timeout=5,
                symbol=symbol
            )
            print(f"{self.log_prefix} Open Positions: {positions}")
            return positions
        except Exception as e:
            print(f"{self.log_prefix} Error fetching open positions: {str(e)}")

    async def fetch_open_orders(self, symbol):
        """Fetch open futures orders."""
        try:
            orders = await execute_with_timeout(
                self.trade_client.get_open_order_details,
                timeout=5,
                symbol=symbol
            )
            print(f"{self.log_prefix} Open Orders: {orders}")
            return orders
        except Exception as e:
            print(f"{self.log_prefix} Error fetching open orders: {str(e)}")

    async def fetch_and_map_positions(self, symbol: str):
        """Fetch and map KuCoin positions to UnifiedPosition."""
        try:
            positions = await execute_with_timeout(
                self.trade_client.get_position_details,
                timeout=5,
                symbol=symbol
            )

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
            #contract = self.market_client.get_contract_detail(symbol=symbol)
            
            print(f"{self.log_prefix} Ticker: {tickers}")
            return UnifiedTicker(
                symbol=symbol,
                bid=float(tickers["bestBidPrice"]),
                ask=float(tickers["bestAskPrice"]),
                last=float(tickers["lastTradePrice"]),
                volume=float(tickers["volume24h"]),
                exchange=self.exchange_name
            )
        except Exception as e:
            print(f"{self.log_prefix} Error fetching tickers: {str(e)}")

    async def get_symbol_details(self, symbol: str):
        """Fetch instrument details including tick size, lot size, max size, and contract value."""
        # Fetch the instrument details from the market client
        instrument = self.market_client.get_contract_detail(symbol)

        # Check if the response contains the desired symbol
        if instrument["symbol"] == symbol:
            lot_size = float(instrument["lotSize"])      # Use lotSize instead of multiplier
            min_lots = float(instrument["lotSize"])      # Minimum order size in lots
            tick_size = float(instrument["tickSize"])    # Tick size for price
            contract_value = float(instrument["multiplier"])  # Contract value/multiplier
            # KuCoin uses maxOrderQty for maximum order quantity
            max_size = float(instrument.get("maxOrderQty", 1000000))  # Default to large number if not specified

            return lot_size, min_lots, tick_size, contract_value, max_size
        raise ValueError(f"Symbol {symbol} not found.")
    
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
            
            # Fetch symbol details (e.g., contract value, lot size, tick size)
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(symbol)

            # Fetch and scale the size and price
            lots, price, _ = scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value)
            print(f"{self.log_prefix} Ordering {lots} lots @ {price}")
            #quit()
            
            # set margin mode    
            try:
                await execute_with_timeout(
                    self.trade_client.modify_margin_mode,
                    timeout=5,
                    symbol=symbol,
                    marginMode=kucoin_margin_mode,
                )
            except Exception as e:
                print(f"{self.log_prefix} Margin Mode unchanged: {str(e)}")
            
            #create_limit_order(self, symbol, side, lever, size, price, clientOid='', **kwargs):
            order_id = await execute_with_timeout(
                self.trade_client.create_limit_order,
                timeout=5,
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
            print(f"{self.log_prefix} Limit Order Placed: {order_id}")
        except Exception as e:
            print(f"{self.log_prefix} Error placing limit order: {str(e)}")

    async def open_market_position(self, symbol: str, side: str, size: float, leverage: int, margin_mode: str, scale_lot_size: bool = True, adjust_margin_mode: bool = True):
        """Open a position with a market order on KuCoin Futures."""
        try:
            print(f"{self.log_prefix} Opening a {side} position for {size} lots of {symbol} with {leverage}x leverage.")
            
            # Fetch symbol details (e.g., contract value, lot size, tick size)
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(symbol)

            # If the size is already in lot size, don't scale it
            lots = (scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value))[0] if scale_lot_size else size
            print(f"{self.log_prefix} Processing {lots} lots of {symbol} with a {side} order")
            
            kucoin_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
            
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
                    
                    # Only adjust margin mode on first chunk
                    if i == 0 and adjust_margin_mode:
                        print(f"{self.log_prefix} Adjusting account margin mode to {kucoin_margin_mode}.")
                        try:
                            await execute_with_timeout(
                                self.trade_client.modify_margin_mode,
                                timeout=5,
                                symbol=symbol,
                                marginMode=kucoin_margin_mode,
                            )
                        except Exception as e:
                            print(f"{self.log_prefix} Margin Mode unchanged: {str(e)}")
                    
                    # Place the market order with size in contracts
                    order = await execute_with_timeout(
                        self.trade_client.create_market_order,
                        timeout=5,
                        symbol=symbol,
                        side=side.lower(),
                        size=chunk_size,
                        lever=leverage,
                        marginMode=kucoin_margin_mode,
                        clientOid=client_oid
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
                    
                    # Only adjust margin mode if this is the first (and only) chunk
                    if num_full_chunks == 0 and adjust_margin_mode:
                        print(f"{self.log_prefix} Adjusting account margin mode to {kucoin_margin_mode}.")
                        try:
                            await execute_with_timeout(
                                self.trade_client.modify_margin_mode,
                                timeout=5,
                                symbol=symbol,
                                marginMode=kucoin_margin_mode,
                            )
                        except Exception as e:
                            print(f"{self.log_prefix} Margin Mode unchanged: {str(e)}")
                    
                    # Place the market order with size in contracts
                    order = await execute_with_timeout(
                        self.trade_client.create_market_order,
                        timeout=5,
                        symbol=symbol,
                        side=side.lower(),
                        size=remainder,
                        lever=leverage,
                        marginMode=kucoin_margin_mode,
                        clientOid=client_oid
                    )
                    orders.append(order)
                    total_executed += remainder
                    print(f"{self.log_prefix} Final chunk order placed: {order}")
                
                print(f"{self.log_prefix} Successfully executed {total_executed} lots across {len(orders)} orders")
                return orders  # Return list of orders
            
            else:
                # Order size is within limits, proceed normally
                client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
                
                if adjust_margin_mode:
                    print(f"{self.log_prefix} Adjusting account margin mode to {kucoin_margin_mode}.")
                    try:
                        await execute_with_timeout(
                            self.trade_client.modify_margin_mode,
                            timeout=5,
                            symbol=symbol,
                            marginMode=kucoin_margin_mode,
                        )
                    except Exception as e:
                        print(f"{self.log_prefix} Margin Mode unchanged: {str(e)}")
                        
                print(f"{self.log_prefix} Placing a market order for {lots} lots of {symbol} with {kucoin_margin_mode} margin mode and {leverage}x leverage.")
                
                # Place the market order with size in contracts
                order = await execute_with_timeout(
                    self.trade_client.create_market_order,
                    timeout=5,
                    symbol=symbol,
                    side=side.lower(),
                    size=lots,  # KuCoin expects size in contracts, already handled by scale_size_and_price
                    lever=leverage,
                    marginMode=kucoin_margin_mode,
                    clientOid=client_oid
                )
                print(f"{self.log_prefix} Market Order Placed: {order}")
                return order

        except Exception as e:
            print(f"{self.log_prefix} Error placing market order: {str(e)}")

    async def close_position(self, symbol: str):
        """Close the open position for a specific symbol on KuCoin Futures."""
        try:
            # Fetch open positions
            position = await self.fetch_open_positions(symbol)
            if not position:
                print(f"{self.log_prefix} No open position found for {symbol}.")
                return None

            # Extract position details
            size = abs(float(position["currentQty"]))  # Use absolute size for closing
            side = "sell" if float(position["currentQty"]) > 0 else "buy"  # Reverse side to close

            print(f"{self.log_prefix} Closing {size} lots of {symbol} with market order.")

            # Place the market order to close the position
            close_order = await self.open_market_position(
                symbol=symbol,
                side=side.lower(),
                size=size,
                leverage=int(position["leverage"]),
                margin_mode=position["marginMode"], # this is kucoin margin mode
                scale_lot_size=False,
            )
            print(f"{self.log_prefix} Position Closed: {close_order}")
            return close_order

        except Exception as e:
            print(f"{self.log_prefix} Error closing position: {str(e)}")
            
    async def reconcile_position(self, symbol: str, size: float, leverage: int, margin_mode: str):
        """
        Reconcile the current position with the target size, leverage, and margin mode.
        """
        try:
            print(f"{self.log_prefix} Reconciling KuCoin position with initial leverage: {leverage}")
            print(f"{self.log_prefix} Current leverage override setting: {self.leverage_override}")
            
            # Use leverage override if set
            if self.leverage_override > 0:
                print(f"{self.log_prefix} Using exchange-specific leverage override: {self.leverage_override}")
                leverage = self.leverage_override
            
            
            unified_positions = await self.fetch_and_map_positions(symbol)
            current_position = unified_positions[0] if unified_positions else None
            
            # Fetch symbol details (e.g., contract value, lot size, tick size)
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(symbol)

            # Scale the target size to match exchange requirements
            #if size != 0:
            # Always scale as we need lot_size
            size, _, lot_size = scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value)

            # Initialize position state variables
            current_size = current_position.size if current_position else 0
            current_margin_mode = current_position.margin_mode if current_position else None
            current_leverage = current_position.leverage if current_position else None

            # Determine if we need to close the current position before opening a new one
            if (current_size > 0 and size < 0) or (current_size < 0 and size > 0):
                print(f"{self.log_prefix} Flipping position from {current_size} to {size}. Closing current position first.")
                await self.close_position(symbol)  # Close the current position
                current_size = 0 # Update current size to 0 after closing the position

            # Check for margin mode or leverage changes
            if current_size != 0 and size != 0:
                if current_margin_mode != margin_mode:
                    print(f"{self.log_prefix} Margin mode change needed: {current_margin_mode} → {margin_mode}")
                    print(f"{self.log_prefix} Closing position to modify margin mode")
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
            if current_leverage > 0 and abs(current_leverage - leverage) > self.leverage_tolerance * leverage and current_size != 0 and abs(size) > 0:
                print(f"{self.log_prefix} Leverage change needed: {current_leverage} → {leverage}")
                print(f"{self.log_prefix} KuCoin does not allow adjustment for leverage on an open position.")
                print(f"{self.log_prefix} Closing position to modify leverage")
                await self.close_position(symbol)  # Close the current position
                current_size = 0 # Update current size to 0 after closing the position

            # Calculate size difference with proper precision
            decimal_places = len(str(lot_size).rsplit('.', maxsplit=1)[-1]) if '.' in str(lot_size) else 0
            size_diff = float(f"%.{decimal_places}f" % (size - current_size))
            
            # Tolerance logic to prevent unnecessary trades:
            # 1. If closing position (target=0): only skip if already effectively zero (current <= min_lots)
            # 2. If opening position (current=0): always proceed
            # 3. If both non-zero: use tolerance (lot_size or 0.1% of position) to avoid tiny adjustments
            if size == 0:
                # Closing position: only skip if current is already effectively zero
                if abs(current_size) <= min_lots:
                    print(f"{self.log_prefix} Position for {symbol} is already effectively closed (size={abs(current_size):.6f} <= min={min_lots}).")
                    return
                # Otherwise, always close (size_diff ensures we proceed)
            elif abs(current_size) == 0:
                # Opening position: always proceed
                pass
            else:
                # Both non-zero: use tolerance to avoid unnecessary trades
                # Tolerance = max(lot_size, 0.1% of smaller position value)
                position_tolerance = max(lot_size, min(abs(current_size), abs(size)) * 0.001)
                
                if abs(size_diff) <= position_tolerance:
                    print(f"{self.log_prefix} Position for {symbol} is already at target size (current={current_size:.6f}, target={size:.6f}, diff={size_diff:.6f}, tolerance={position_tolerance:.6f}).")
                    return
            
            print(f"{self.log_prefix} Adjusting position: current={current_size:.6f}, target={size:.6f}, diff={size_diff:.6f}")

            # Determine the side of the new order (buy/sell)
            side = "Buy" if size_diff > 0 else "Sell"
            size_diff = abs(size_diff)  # Work with absolute size for the order

            print(f"{self.log_prefix} Placing a {side} order with {leverage}x leverage to adjust position by {size_diff}.")
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
            print(f"{self.log_prefix} Error reconciling position: {str(e)}")

    async def test_symbol_formats(self):
        """Test function to dump symbol information for mapping."""
        try:
            # Test common symbols
            test_symbols = ["XBTUSDTM", "ETHUSDTM"]
            
            for symbol in test_symbols:
                try:
                    # Get contract details
                    contract = await execute_with_timeout(
                        self.market_client.get_contract_detail,
                        timeout=5,
                        symbol=symbol
                    )
                    
                    print(f"{self.log_prefix} KuCoin Symbol Information for {symbol}:")
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
        # KuCoin uses XBTUSDTM for BTC and adds M suffix for others
        if "USDT" in signal_symbol:
            base = signal_symbol.replace("USDT", "")
            # Special case for BTC
            if base == "BTC":
                return "XBTUSDTM"
            return f"{base}USDTM"
        return signal_symbol

    async def fetch_initial_account_value(self) -> float:
        """Calculate total account value from balance and initial margin of positions."""
        try:
            # First check if account is enabled
            if not self.enabled:
                return 0.0
            
            # Get available balance
            balance = await self.fetch_balance("USDT")
            available_balance = float(balance) if balance else 0.0
            print(f"{self.log_prefix} Available Balance: {available_balance} USDT")
            
            # Get positions directly - KuCoin provides posInit (initial margin)
            positions = await self.fetch_all_open_positions()
            position_margin = 0.0
            
            # Handle both empty positions and zero balance cases
            if positions:
                if isinstance(positions, list):
                    for pos in positions:
                        position_margin += float(pos["posInit"])  # Direct initial margin value
                elif isinstance(positions, dict) and "data" in positions:
                    for pos in positions["data"]:
                        position_margin += float(pos["posInit"])
            
            print(f"{self.log_prefix} Position Initial Margin: {position_margin} USDT")
            
            total_value = available_balance + position_margin
            if total_value == 0:
                print(f"{self.log_prefix} Warning: Account has zero total value")
            print(f"{self.log_prefix} Initial Account Value: {total_value} USDT")
            return total_value
            
        except Exception as e:
            print(f"{self.log_prefix} Error calculating initial account value: {str(e)}")
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
    print(f"{kucoin.log_prefix} Testing total account value calculation:")
    total_value = await kucoin.fetch_initial_account_value()
    print(f"{kucoin.log_prefix} Final Total Account Value: {total_value} USDT")
    
    # Test fetching max order quantity for BTC
    print(f"\n{kucoin.log_prefix} Testing symbol details and max order quantity:")
    try:
        symbol = "XBTUSDTM"
        lot_size, min_size, tick_size, contract_value, max_size = await kucoin.get_symbol_details(symbol)
        print(f"{kucoin.log_prefix} Symbol: {symbol}")
        print(f"{kucoin.log_prefix} Lot Size: {lot_size}")
        print(f"{kucoin.log_prefix} Min Order Qty: {min_size}")
        print(f"{kucoin.log_prefix} Max Order Qty: {max_size}")
        print(f"{kucoin.log_prefix} Tick Size: {tick_size}")
        print(f"{kucoin.log_prefix} Contract Value: {contract_value}")
        
        # Get full contract details
        contract = kucoin.market_client.get_contract_detail(symbol)
        print(f"\n{kucoin.log_prefix} Full contract details for {symbol}:")
        for key in ["maxOrderQty", "maxPrice", "lotSize", "tickSize", "multiplier", "maxRiskLimit", "minRiskLimit"]:
            if key in contract:
                print(f"{kucoin.log_prefix} {key}: {contract[key]}")
    except Exception as e:
        print(f"{kucoin.log_prefix} Error testing symbol details: {str(e)}")
    
    # Test order chunking demonstration (commented out to avoid actual trading)
    """
    print(f"\n{kucoin.log_prefix} Testing order chunking with large order:")
    try:
        # This would test chunking if the order exceeds max_size
        result = await kucoin.open_market_position(
            symbol="XBTUSDTM",
            side="buy",
            size=1000,  # Large size to test chunking
            leverage=5,
            margin_mode="isolated"
        )
        print(f"{kucoin.log_prefix} Order result: {result}")
    except Exception as e:
        print(f"{kucoin.log_prefix} Error testing order chunking: {str(e)}")
    """
    
    # End time
    end_time = datetime.datetime.now()
    print(f"{kucoin.log_prefix} Time taken: {end_time - start_time}")
    
if __name__ == "__main__":
    asyncio.run(main())
