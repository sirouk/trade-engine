import asyncio
import datetime
from pybit.unified_trading import HTTP # https://github.com/bybit-exchange/pybit/
from config.credentials import load_bybit_credentials
from core.utils.modifiers import scale_size_and_price
from core.unified_position import UnifiedPosition
from core.unified_ticker import UnifiedTicker
from core.utils.execute_timed import execute_with_timeout


class ByBit:
    def __init__(self):
        
        self.exchange_name = "ByBit"
        self.enabled = True
            
        # Load Bybit API key and secret from your credentials file
        self.credentials = load_bybit_credentials()

        self.TESTNET = False  # Change to False for production
        self.SETTLE_COIN = "USDT"

        # Initialize the Bybit client
        self.bybit_client = HTTP(
            api_key=self.credentials.bybit.api_key,
            api_secret=self.credentials.bybit.api_secret,
            testnet=self.TESTNET
        )
        
        self.margin_mode_map = {
            "isolated": "ISOLATED_MARGIN",
            "cross": "REGULAR_MARGIN"
        }

        self.inverse_margin_mode_map = {v: k for k, v in self.margin_mode_map.items()}
        
        self.leverage_override = self.credentials.bybit.leverage_override

        # Add logger prefix
        self.log_prefix = f"[{self.exchange_name}]"

    async def fetch_balance(self, instrument="USDT"):
        try:
            balance = await execute_with_timeout(
                self.bybit_client.get_wallet_balance,
                timeout=5,
                accountType="UNIFIED",
                settleCoin=self.SETTLE_COIN,
                coin=instrument
            )
            # {'retCode': 0, 'retMsg': 'OK', 'result': {'list': [{'totalEquity': '12533.29873097', 'accountIMRate': '', 'totalMarginBalance': '', 'totalInitialMargin': '', 'accountType': 'UNIFIED', 'totalAvailableBalance': '', 'accountMMRate': '', 'totalPerpUPL': '0', 'totalWalletBalance': '12533.29873097', 'accountLTV': '', 'totalMaintenanceMargin': '', 'coin': [{'availableToBorrow': '', 'bonus': '0', 'accruedInterest': '0', 'availableToWithdraw': '', 'totalOrderIM': '0', 'equity': '12534.90748258', 'totalPositionMM': '0', 'usdValue': '12533.29047951', 'unrealisedPnl': '0', 'collateralSwitch': True, 'spotHedgingQty': '0', 'borrowAmount': '0', 'totalPositionIM': '0', 'walletBalance': '12534.90748258', 'cumRealisedPnl': '0', 'locked': '0', 'marginCollateral': True, 'coin': 'USDT'}]}]}, 'retExtInfo': {}, 'time': 1737052109973}
            
            # print response
            # print(f"Balance Response: {balance}")
            # quit()
            
            # get coin balance available to trade
            #balance = balance["result"]["list"][0]["coin"][0]["walletBalance"]
            coin_data = balance["result"]["list"][0]["coin"][0]
            wallet_balance = float(coin_data["walletBalance"])
            position_im = float(coin_data["totalPositionIM"])
            
            # Available Balance = Wallet Balance - Initial Margin
            available_balance = wallet_balance - position_im
            
            print(f"{self.log_prefix} Available Balance for {instrument}: {available_balance}")
            return available_balance
            
        except Exception as e:
            print(f"{self.log_prefix} Error fetching balance: {str(e)}")
            
    # fetch all open positions
    async def fetch_all_open_positions(self):
        try:
            positions = await execute_with_timeout(
                self.bybit_client.get_positions,
                timeout=5,
                category="linear",
                settleCoin=self.SETTLE_COIN
            )
            #print(f"All Open Positions: {positions}")
            return positions
        except Exception as e:
            print(f"{self.log_prefix} Error fetching all open positions: {str(e)}")

    async def fetch_open_positions(self, symbol):
        try:
            positions = await execute_with_timeout(
                self.bybit_client.get_positions,
                timeout=5,
                category="linear",
                symbol=symbol
            )
            print(f"{self.log_prefix} Open Positions: {positions}")
            return positions
        except Exception as e:
            print(f"{self.log_prefix} Error fetching open positions: {str(e)}")

    async def fetch_open_orders(self, symbol):
        try:
            orders = await execute_with_timeout(
                self.bybit_client.get_open_orders,
                timeout=5,
                category="linear",
                settleCoin=self.SETTLE_COIN,
                symbol=symbol
            )
            print(f"{self.log_prefix} Open Orders: {orders}")
            return orders
        except Exception as e:
            print(f"{self.log_prefix} Error fetching open orders: {str(e)}")
            
    async def get_account_margin_mode(self) -> str:
        """Fetch the account info to determine the margin mode for UTA2.0."""
        results = await execute_with_timeout(
            self.bybit_client.get_account_info,
            timeout=5
        )
        account = results.get("result", {})
        if "marginMode" in account:
            bybit_margin_mode = account.get("marginMode")
            return self.margin_mode_map.get(bybit_margin_mode, bybit_margin_mode)
        raise ValueError("Margin mode not found for account")

    async def fetch_and_map_positions(self, symbol: str, fetch_margin_mode: bool = False) -> list:
        """Fetch open positions from Bybit and convert them to UnifiedPosition objects."""
        try:
            response = await execute_with_timeout(
                self.bybit_client.get_positions,
                timeout=5,
                category="linear",
                settleCoin=self.SETTLE_COIN,
                symbol=symbol
            )
            # print(response)
            # quit()
            positions = response.get("result", {}).get("list", [])
            #print(positions)
            
            # For UTA accounts, tradeMode 0 means "follow account default"
            # We need to fetch the account margin mode to determine the actual mode
            account_margin_mode = None
            for pos in positions:
                if float(pos.get("size", 0)) > 0 and pos.get("tradeMode") == 0:
                    # Only fetch once if we have positions with tradeMode 0
                    if account_margin_mode is None:
                        try:
                            account_margin_mode = await self.get_account_margin_mode()
                            print(f"{self.log_prefix} Account margin mode for tradeMode 0: {account_margin_mode}")
                        except Exception as e:
                            print(f"{self.log_prefix} Could not fetch account margin mode: {e}")
                    break

            unified_positions = [
                self.map_bybit_position_to_unified(pos, account_margin_mode)
                for pos in positions
                if float(pos.get("size", 0)) > 0
            ]

            for unified_position in unified_positions:
                print(f"{self.log_prefix} Unified Position: {unified_position}")

            return unified_positions
        except Exception as e:
            print(f"{self.log_prefix} Error mapping Bybit positions: {str(e)}")
            return []
    
    def map_bybit_position_to_unified(self, position: dict, account_margin_mode: str = None) -> UnifiedPosition:
        """Convert a Bybit position response into a UnifiedPosition object."""
        size = abs(float(position.get("size", 0)))
        direction = "long" if position.get("side", "").lower() == "buy" else "short"
        # adjust size for short positions
        if direction == "short":
            size = -size

        # Determine margin mode
        trade_mode = position.get("tradeMode")
        if trade_mode == 1:
            # Explicitly isolated
            margin_mode = "isolated"
        elif trade_mode == 0 and account_margin_mode:
            # Use account default margin mode
            margin_mode = account_margin_mode
        else:
            # Fallback - assume isolated for safety
            margin_mode = "isolated"
        
        # Convert to unified format using inverse mapping
        margin_mode = self.inverse_margin_mode_map.get(margin_mode, margin_mode)

        return UnifiedPosition(
            symbol=position["symbol"],
            size=size,
            average_entry_price=float(position.get("avgPrice", 0)),
            leverage=float(position.get("leverage", 1)),
            direction=direction,
            unrealized_pnl=float(position.get("unrealisedPnl", 0)),
            margin_mode=margin_mode,
            exchange=self.exchange_name,
        )
        
    async def fetch_tickers(self, symbol):
        try:
            tickers = await execute_with_timeout(
                self.bybit_client.get_tickers,
                timeout=5,
                category="linear",
                symbol=symbol
            )
            ticker_data = tickers["result"]["list"][0]  # Assuming the first entry is the relevant ticker
            
            print(f"{self.log_prefix} Ticker: {ticker_data}")
            return UnifiedTicker(
                symbol=symbol,
                bid=float(ticker_data.get("bid1Price", 0)),
                ask=float(ticker_data.get("ask1Price", 0)),
                last=float(ticker_data.get("lastPrice", 0)),
                volume=float(ticker_data.get("volume24h", 0)),
                exchange=self.exchange_name
            )
        except Exception as e:
            print(f"{self.log_prefix} Error fetching tickers from Bybit: {str(e)}")

    async def get_symbol_details(self, symbol: str):
        """Fetch instrument details including tick size, lot size, min size, max size, and contract value."""
        instruments = await execute_with_timeout(
            self.bybit_client.get_instruments_info,
            timeout=5,
            category="linear",
            symbol=symbol,
        )

        for instrument in instruments["result"]["list"]:
            if instrument["symbol"] == symbol:
                #print(f"Instrument: {instrument}")
                lot_size = float(instrument["lotSizeFilter"]["qtyStep"])
                min_size = float(instrument["lotSizeFilter"]["minOrderQty"])
                max_size = float(instrument["lotSizeFilter"]["maxOrderQty"])
                tick_size = float(instrument["priceFilter"]["tickSize"])
                contract_value = float(lot_size / min_size)  # Optional fallback

                return lot_size, min_size, tick_size, contract_value, max_size
        raise ValueError(f"Symbol {symbol} not found.")

    async def _place_limit_order_test(self,):
        """Place a limit order on Bybit."""
        try:
            
            # Test limit order
            # https://bybit-exchange.github.io/docs/v5/order/create-order
            # NOTE: make sure margin type is set to isolated
            # NOTE: leverage must be set separately
            # TODO: size_in_settle_coin = price * size * leverage
            category="linear"
            symbol="BTCUSDT"
            side="Buy"
            price=62699
            size=0.003 # in quantity of symbol
            leverage=3
            isLeverage=1 # 1:leveraged 2: not leveraged
            order_type="Limit"
            time_in_force="IOC"
            bybit_margin_mode='ISOLATED_MARGIN' # ISOLATED_MARGIN, REGULAR_MARGIN(i.e. Cross margin), PORTFOLIO_MARGIN
            reduce_only=False
            close_on_trigger=False
            client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
            
            # Fetch symbol details (e.g., contract value, lot size, tick size)
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(symbol)
            
            # Fetch and scale the size and price
            lots, price, _ = scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value)
            print(f"{self.log_prefix} Ordering {lots} lots @ {price}")
            #quit()
            
            # set leverage and margin mode    
            try:
                await execute_with_timeout(
                    self.bybit_client.set_margin_mode,
                    timeout=5,
                    setMarginMode=bybit_margin_mode,
                )   
            except Exception as e:
                print(f"{self.log_prefix} Margin Mode unchanged: {str(e)}")
            
            try:     
                await execute_with_timeout(
                    self.bybit_client.set_leverage,
                    timeout=5,
                    symbol=symbol, 
                    category=category,                
                    buyLeverage=str(leverage), 
                    sellLeverage=str(leverage),
                )
            except Exception as e:
                print(f"{self.log_prefix} Leverage unchanged: {str(e)}")
            
            order = await execute_with_timeout(
                self.bybit_client.place_order,
                timeout=5,
                category=category,
                symbol=symbol,
                side=side.capitalize(),
                price=price,
                qty=lots,
                isLeverage=isLeverage,
                order_type=order_type,
                time_in_force=time_in_force, # GTC, IOC, FOK, PostOnly (use IOK)
                reduce_only=reduce_only,
                close_on_trigger=close_on_trigger,
                orderLinkId=client_oid,
                positionIdx=0, # one-way mode
            )
            print(f"{self.log_prefix} Limit Order Placed: {order}")
            # Limit Order Placed: {'retCode': 0, 'retMsg': 'OK', 'result': {'orderId': '2c9eee09-b90e-47eb-ace0-d82c6cdc7bfa', 'orderLinkId': '20241014022046505544'}, 'retExtInfo': {}, 'time': 1728872447805}
            # Controlling 0.001 of BTC $62,957.00 is expected to be 62.957 USDT
            # Actual Margin Used: 12.6185 USDT @ 5x 
            return order
            
        except Exception as e:
            print(f"{self.log_prefix} Error placing limit order: {str(e)}")

    async def open_market_position(self, symbol: str, side: str, size: float, leverage: int, margin_mode: str, scale_lot_size: bool = True, adjust_leverage: bool = True, adjust_margin_mode: bool = True):
        """Open a position with a market order."""
        try:
            
            # Fetch symbol details (e.g., contract value, lot size, tick size)
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(symbol)
            
            # Get the specific market order max size from instrument info
            instrument = await execute_with_timeout(
                self.bybit_client.get_instruments_info,
                timeout=5,
                category="linear",
                symbol=symbol,
            )
            max_market_order_qty = float(instrument["result"]["list"][0]["lotSizeFilter"].get("maxMktOrderQty", max_size))
            
            lots = (scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value))[0] if scale_lot_size else size
            print(f"{self.log_prefix} Processing {lots} lots of {symbol} with a {side} order.")
            
            # Check if order size exceeds maximum market order quantity
            if lots > max_market_order_qty:
                print(f"{self.log_prefix} Order size {lots} exceeds max market order qty {max_market_order_qty}. Splitting into chunks.")
                
                # Calculate number of full chunks and remainder
                num_full_chunks = int(lots // max_market_order_qty)
                remainder = lots % max_market_order_qty
                
                # Round remainder to lot size precision
                decimal_places = len(str(lot_size).rsplit('.', maxsplit=1)[-1]) if '.' in str(lot_size) else 0
                remainder = float(f"%.{decimal_places}f" % remainder)
                
                orders = []
                total_executed = 0
                
                # Place full-sized chunks
                for i in range(num_full_chunks):
                    chunk_size = max_market_order_qty
                    print(f"{self.log_prefix} Placing chunk {i+1}/{num_full_chunks + (1 if remainder > 0 else 0)}: {chunk_size} lots")
                    
                    client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
                    
                    # Only adjust margin mode and leverage on first chunk
                    if i == 0:
                        if adjust_margin_mode:
                            bybit_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
                            try:
                                await execute_with_timeout(
                                    self.bybit_client.set_margin_mode,
                                    timeout=5,
                                    setMarginMode=bybit_margin_mode,
                                )
                            except Exception as e:
                                print(f"{self.log_prefix} Margin Mode unchanged: {str(e)}")
                        
                        if adjust_leverage:
                            try:
                                await execute_with_timeout(
                                    self.bybit_client.set_leverage,
                                    timeout=5,
                                    symbol=symbol, 
                                    category="linear", 
                                    buyLeverage=str(leverage), 
                                    sellLeverage=str(leverage),
                                )
                            except Exception as e:
                                print(f"{self.log_prefix} Leverage unchanged: {str(e)}")
                    
                    order = await execute_with_timeout(
                        self.bybit_client.place_order,
                        timeout=5,
                        category="linear",
                        symbol=symbol,
                        side=side.capitalize(),
                        qty=chunk_size,
                        order_type="Market",
                        isLeverage=1,
                        orderLinkId=client_oid,
                        positionIdx=0
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
                    
                    # Only adjust settings if this is the first (and only) chunk
                    if num_full_chunks == 0:
                        if adjust_margin_mode:
                            bybit_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
                            try:
                                await execute_with_timeout(
                                    self.bybit_client.set_margin_mode,
                                    timeout=5,
                                    setMarginMode=bybit_margin_mode,
                                )
                            except Exception as e:
                                print(f"{self.log_prefix} Margin Mode unchanged: {str(e)}")
                        
                        if adjust_leverage:
                            try:
                                await execute_with_timeout(
                                    self.bybit_client.set_leverage,
                                    timeout=5,
                                    symbol=symbol, 
                                    category="linear", 
                                    buyLeverage=str(leverage), 
                                    sellLeverage=str(leverage),
                                )
                            except Exception as e:
                                print(f"{self.log_prefix} Leverage unchanged: {str(e)}")
                    
                    order = await execute_with_timeout(
                        self.bybit_client.place_order,
                        timeout=5,
                        category="linear",
                        symbol=symbol,
                        side=side.capitalize(),
                        qty=remainder,
                        order_type="Market",
                        isLeverage=1,
                        orderLinkId=client_oid,
                        positionIdx=0
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
                    bybit_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
                    try:
                        await execute_with_timeout(
                            self.bybit_client.set_margin_mode,
                            timeout=5,
                            setMarginMode=bybit_margin_mode,
                        )
                    except Exception as e:
                        print(f"{self.log_prefix} Margin Mode unchanged: {str(e)}")
                
                if adjust_leverage:
                    try:
                        await execute_with_timeout(
                            self.bybit_client.set_leverage,
                            timeout=5,
                            symbol=symbol, 
                            category="linear", 
                            buyLeverage=str(leverage), 
                            sellLeverage=str(leverage),
                        )
                    except Exception as e:
                        print(f"{self.log_prefix} Leverage unchanged: {str(e)}")

                order = await execute_with_timeout(
                    self.bybit_client.place_order,
                    timeout=5,
                    category="linear",
                    symbol=symbol,
                    side=side.capitalize(),
                    qty=lots,
                    order_type="Market",
                    isLeverage=1,
                    orderLinkId=client_oid,
                    positionIdx=0
                )
                print(f"{self.log_prefix} Market Order Placed: {order}")
                return order
        except Exception as e:
            print(f"{self.log_prefix} Error placing market order: {str(e)}")

    async def close_position(self, symbol: str):
        """Close the position for a specific symbol."""
        try:
            # Fetch open positions to determine the side to close
            positions = await self.fetch_open_positions(symbol)
            if not positions["result"]["list"]:
                print(f"{self.log_prefix} No open position found for {symbol}.")
                return None

            position = positions["result"]["list"][0]
            side = "Sell" if position["side"].lower() == "buy" else "Buy"
            size = float(position["size"])
            leverage = float(position["leverage"])
            margin_mode = "isolated" if position["tradeMode"] == 1 else "cross"

            print(f"{self.log_prefix} Closing {size} lots of {symbol} with market order.")

            # Place a market order in the opposite direction to close the position
            order = await self.open_market_position(
                symbol=symbol, 
                side=side.capitalize(), 
                size=size, 
                leverage=leverage, 
                margin_mode=margin_mode, 
                scale_lot_size=False,
                adjust_leverage=False,
                adjust_margin_mode=False,
            )
            print(f"{self.log_prefix} Position Closed: {order}")
            return order

        except Exception as e:
            print(f"{self.log_prefix} Error closing position: {str(e)}")

    async def reconcile_position(self, symbol: str, size: float, leverage: int, margin_mode: str):
        """
        Reconcile the current position with the target size, leverage, and margin mode.
        If the position flips from long to short or vice versa, the current position is closed first.
        """
        try:
            # Use leverage override if set
            if self.leverage_override > 0:
                print(f"{self.log_prefix} Using exchange-specific leverage override: {self.leverage_override}")
                leverage = self.leverage_override
                
            # Fetch current positions for the given symbol
            unified_positions = await self.fetch_and_map_positions(symbol, fetch_margin_mode=size != 0)
            current_position = unified_positions[0] if unified_positions else None
            
            # Fetch symbol details (e.g., contract value, lot size, tick size)
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(symbol)

            # Scale the target size to match exchange requirements
            #if size != 0:
            # Always scale as we need lot_size
            size, _, lot_size = scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value)  # No price needed for market orders

            # Initialize current state variables
            current_size = current_position.size if current_position else 0
            current_margin_mode = current_position.margin_mode if current_position else None
            current_leverage = current_position.leverage if current_position else None
            
            # Determine if the position is flipping (long to short or vice versa)
            if (current_size > 0 and size < 0) or (current_size < 0 and size > 0):
                print(f"{self.log_prefix} Flipping position from {current_size} to {size}. Closing current position first.")
                await self.close_position(symbol)  # Close the current position
                current_size = 0  # Reset current size to 0 after closure
                
            # Adjust margin mode and leverage if necessary, and the position exists
            if current_size != 0 and size != 0:
                if current_margin_mode != margin_mode:
                    print(f"{self.log_prefix} Adjusting margin mode to {margin_mode}.")
                    bybit_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
                    try:
                        await execute_with_timeout(
                            self.bybit_client.set_margin_mode,
                            timeout=5,
                            setMarginMode=bybit_margin_mode,
                        )
                    except Exception as e:
                        print(f"{self.log_prefix} Failed to adjust margin mode: {str(e)}")

            if current_leverage != leverage and abs(size) > 0:
                print(f"{self.log_prefix} Adjusting leverage to {leverage}.")
                try:
                    await execute_with_timeout(
                        self.bybit_client.set_leverage,
                        timeout=5,
                        symbol=symbol,
                        category="linear",
                        buyLeverage=str(leverage),
                        sellLeverage=str(leverage)
                    )
                except Exception as e:
                    print(f"{self.log_prefix} Failed to adjust leverage: {str(e)}")

            # Calculate the size difference after potential closure
            decimal_places = len(str(lot_size).rsplit('.', maxsplit=1)[-1]) if '.' in str(lot_size) else 0
            size_diff = float(f"%.{decimal_places}f" % (size - current_size))
            
            print(f"{self.log_prefix} Current size: {current_size}, Target size: {size}, Size difference: {size_diff}")

            # If the target size is already reached, no action is needed
            if size_diff == 0:
                print(f"{self.log_prefix} Position for {symbol} is already at the target size.")
                return

            # Determine the side (buy/sell) for the adjustment order
            side = "Buy" if size_diff > 0 else "Sell"
            size_diff = abs(size_diff)  # Use absolute value for the order size

            print(f"{self.log_prefix} Placing a {side} order to adjust position by {size_diff}.")
            await self.open_market_position(
                symbol=symbol,
                side=side.capitalize(),
                size=size_diff,
                leverage=leverage,
                margin_mode=margin_mode,
                scale_lot_size=False,
                adjust_leverage=size != 0,
                adjust_margin_mode=size != 0,
            )
        except Exception as e:
            print(f"{self.log_prefix} Error reconciling position: {str(e)}")

    async def test_symbol_formats(self):
        """Test function to dump symbol information for mapping."""
        try:
            # Test common symbols
            test_symbols = ["BTCUSDT", "ETHUSDT"]
            
            for symbol in test_symbols:
                try:
                    # Get instrument info
                    instrument = await execute_with_timeout(
                        self.bybit_client.get_instruments_info,
                        timeout=5,
                        category="linear",
                        symbol=symbol,
                    )
                    
                    print(f"{self.log_prefix} Bybit Symbol Information for {symbol}:")
                    print(f"{self.log_prefix} Native Symbol Format: {symbol}")
                    #print(f"Full Response: {instrument}")
                    
                    # Try to fetch a ticker to verify symbol works
                    ticker = await self.fetch_tickers(symbol)
                    #print(f"Ticker Test: {ticker}")
                    
                except Exception as e:
                    print(f"{self.log_prefix} Error testing {symbol}: {str(e)}")
                    
            # Add to test_symbol_formats() in each processor
            test_symbols = ["BTCUSDT", "ETHUSDT"]
            print(f"{self.log_prefix} Testing symbol mapping:")
            for symbol in test_symbols:
                mapped = self.map_signal_symbol_to_exchange(symbol)
                print(f"{self.log_prefix} Signal symbol: {symbol} -> Exchange symbol: {mapped}")
                    
        except Exception as e:
            print(f"{self.log_prefix} Error in symbol format test: {str(e)}")

    def map_signal_symbol_to_exchange(self, signal_symbol: str) -> str:
        """Convert signal symbol format (e.g. BTCUSDT) to exchange format."""
        # Bybit uses the same format as our signals, no conversion needed
        return signal_symbol

    async def fetch_initial_account_value(self) -> float:
        """Calculate total account value from balance and initial margin of positions."""
        try:
            # Get available balance
            balance = await self.fetch_balance("USDT")
            available_balance = float(balance) if balance else 0.0
            print(f"{self.log_prefix} Available Balance: {available_balance} USDT")
            
            # Get positions directly - Bybit provides positionIM (initial margin)
            positions = await self.fetch_all_open_positions()
            position_margin = 0.0
            if positions and "result" in positions:
                for pos in positions["result"]["list"]:
                    # print(f"Position: {pos}")
                    # quit()
                    #position_margin += float(pos["positionIM"])  # Direct initial margin value
                    position_margin += float(pos["positionBalance"])  # Direct initial margin value
            print(f"{self.log_prefix} Position Initial Margin: {position_margin} USDT")
            
            total_value = available_balance + position_margin
            print(f"{self.log_prefix} ByBit Initial Account Value: {total_value} USDT")
            return total_value
            
        except Exception as e:
            print(f"{self.log_prefix} Error calculating initial account value: {str(e)}")
            return 0.0


async def main():   
    # Start a time
    start_time = datetime.datetime.now()
    
    from core.utils.execute_timed import execute_with_timeout
    
    bybit = ByBit()
    
    # balance = await bybit.fetch_balance(instrument="USDT")      # Fetch futures balance
    # print(balance)
    
    # tickers = await bybit.fetch_tickers(symbol="BTCUSDT")  # Fetch market tickers
    # print(tickers)
    
    # order_results = await bybit._place_limit_order_test()
    # print(order_results)
    
    # order_results = await bybit.open_market_position(
    #     symbol="BTCUSDT", 
    #     side="Sell", 
    #     size=0.002, 
    #     leverage=5,
    #     margin_mode="isolated",
    # )
    # print(order_results)
    
    # import time
    # time.sleep(5)
    
    
    # Example usage of reconcile_position to adjust position to the desired size, leverage, and margin type
    #await bybit.reconcile_position(
    #    symbol="BTCUSDT",   # Symbol to adjust
    #    size=0,  # Desired position size (positive for long, negative for short, zero to close)
    #    leverage=5,         # Desired leverage
    #    margin_mode="isolated"  # Desired margin mode
    #)
    
    # close_result = await bybit.close_position(symbol="BTCUSDT")
    # print(close_result)
    
    # orders = await bybit.fetch_open_orders(symbol="BTCUSDT")          # Fetch open orders
    # print(orders)

    #await bybit.fetch_open_positions(symbol="BTC-USDT")       # Fetch open positions
    #positions = await bybit.fetch_and_map_positions(symbol="BTCUSDT")
    #print(positions)
    
    # Test symbol formats
    # await bybit.test_symbol_formats()
    
    # Test initial account value calculation
    print(f"{bybit.log_prefix} Testing initial account value calculation:")
    initial_value = await bybit.fetch_initial_account_value()
    print(f"{bybit.log_prefix} Final Initial Account Value: {initial_value} USDT")
    
    # Test order chunking with a large TAO order (commented out to avoid actual trading)
    # Uncomment the following to test order chunking:
    """
    print(f"\n{bybit.log_prefix} Testing order chunking with large TAO order:")
    try:
        # This would try to buy 150 TAO, which exceeds the 60 TAO market order limit
        # It should automatically split into 3 orders: 60 + 60 + 30
        result = await bybit.open_market_position(
            symbol="TAOUSDT",
            side="Buy",
            size=150,  # This exceeds the 60 TAO market order limit
            leverage=5,
            margin_mode="isolated"
        )
        print(f"{bybit.log_prefix} Order result: {result}")
    except Exception as e:
        print(f"{bybit.log_prefix} Error testing order chunking: {str(e)}")
    """
    
    # Test TAO/USDT symbol details to check max order quantity
    print(f"\n{bybit.log_prefix} Testing TAO/USDT symbol details:")
    try:
        symbol = "TAOUSDT"
        lot_size, min_size, tick_size, contract_value, max_size = await bybit.get_symbol_details(symbol)
        print(f"{bybit.log_prefix} Symbol: {symbol}")
        print(f"{bybit.log_prefix} Lot Size (qtyStep): {lot_size}")
        print(f"{bybit.log_prefix} Min Order Qty: {min_size}")
        print(f"{bybit.log_prefix} Max Order Qty: {max_size}")
        print(f"{bybit.log_prefix} Tick Size: {tick_size}")
        print(f"{bybit.log_prefix} Contract Value: {contract_value}")
        
        # Also get full instrument info for more details
        instrument = await execute_with_timeout(
            bybit.bybit_client.get_instruments_info,
            timeout=5,
            category="linear",
            symbol=symbol,
        )
        print(f"\n{bybit.log_prefix} Full instrument details for {symbol}:")
        for key, value in instrument["result"]["list"][0].items():
            if "Filter" in key:
                print(f"{bybit.log_prefix} {key}: {value}")
    except Exception as e:
        print(f"{bybit.log_prefix} Error testing TAO/USDT: {str(e)}")
        # Try alternative symbols that might be for TAO
        alternative_symbols = ["TAOUSUSDT", "TAO-USDT", "TAOPERP"]
        print(f"{bybit.log_prefix} Trying alternative symbols...")
        for alt_symbol in alternative_symbols:
            try:
                lot_size, min_size, tick_size, contract_value, max_size = await bybit.get_symbol_details(alt_symbol)
                print(f"{bybit.log_prefix} Found working symbol: {alt_symbol}")
                print(f"{bybit.log_prefix} Max Order Qty: {max_size}")
                break
            except:
                continue
    
    # End time
    end_time = datetime.datetime.now()
    print(f"Time taken: {end_time - start_time}")
    
if __name__ == "__main__":
    asyncio.run(main())
