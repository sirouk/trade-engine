import asyncio
import datetime
from pybit.unified_trading import HTTP # https://github.com/bybit-exchange/pybit/
from config.credentials import load_bybit_credentials
from core.utils.modifiers import round_to_tick_size, calculate_lots
from core.unified_position import UnifiedPosition
from core.unified_ticker import UnifiedTicker


class ByBit:
    def __init__(self):
        
        self.exchange_name = "ByBit"
            
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

    async def fetch_balance(self, instrument="USDT"):
        try:
            balance = self.bybit_client.get_wallet_balance(accountType="UNIFIED", settleCoin=self.SETTLE_COIN, coin=instrument)
            # {'retCode': 0, 'retMsg': 'OK', 'result': {'list': [{'totalEquity': '0.10204189', 'accountIMRate': '0', 'totalMarginBalance': '0.09302213', 'totalInitialMargin': '0', 'accountType': 'UNIFIED', 'totalAvailableBalance': '0.09302213', 'accountMMRate': '0', 'totalPerpUPL': '0', 'totalWalletBalance': '0.09302213', 'accountLTV': '0', 'totalMaintenanceMargin': '0', 'coin': [{'availableToBorrow': '', 'bonus': '0', 'accruedInterest': '0', 'availableToWithdraw': '0.09304419', 'totalOrderIM': '0', 'equity': '0.09304419', 'totalPositionMM': '0', 'usdValue': '0.09302213', 'unrealisedPnl': '0', 'collateralSwitch': True, 'spotHedgingQty': '0', 'borrowAmount': '0.000000000000000000', 'totalPositionIM': '0', 'walletBalance': '0.09304419', 'cumRealisedPnl': '-10924.04925374', 'locked': '0', 'marginCollateral': True, 'coin': 'USDT'}]}]}, 'retExtInfo': {}, 'time': 1728795935267}
            
            # get coin balance available to trade
            balance = balance["result"]["list"][0]["coin"][0]["availableToWithdraw"]
            print(f"Account Balance for {instrument}: {balance}")
            return balance
        except Exception as e:
            print(f"Error fetching balance: {str(e)}")
            
    # fetch all open positions
    async def fetch_all_open_positions(self):
        try:
            positions = self.bybit_client.get_positions(category="linear", settleCoin=self.SETTLE_COIN)
            #print(f"All Open Positions: {positions}")
            return positions
        except Exception as e:
            print(f"Error fetching all open positions: {str(e)}")

    async def fetch_open_positions(self, symbol):
        try:
            positions = self.bybit_client.get_positions(category="linear", settleCoin=self.SETTLE_COIN, symbol=symbol)
            print(f"Open Positions: {positions}")
            return positions
        except Exception as e:
            print(f"Error fetching open positions: {str(e)}")

    async def fetch_open_orders(self, symbol):
        try:
            orders = self.bybit_client.get_open_orders(category="linear", settleCoin=self.SETTLE_COIN, symbol=symbol)
            print(f"Open Orders: {orders}")
            return orders
        except Exception as e:
            print(f"Error fetching open orders: {str(e)}")
            
    async def get_account_margin_mode(self) -> str:
        """Fetch the account info to determine the margin mode for UTA2.0."""
        results = self.bybit_client.get_account_info()
        account = results.get("result", {})
        if "marginMode" in account:
            bybit_margin_mode = account.get("marginMode")
            return self.margin_mode_map.get(bybit_margin_mode, bybit_margin_mode)
        raise ValueError("Margin mode not found for account")

    async def fetch_and_map_positions(self, symbol: str, fetch_margin_mode: bool = False) -> list:
        """Fetch open positions from Bybit and convert them to UnifiedPosition objects."""
        try:
            response = self.bybit_client.get_positions(category="linear", settleCoin=self.SETTLE_COIN, symbol=symbol)
            # print(response)
            # quit()
            positions = response.get("result", {}).get("list", [])
            #print(positions)
            
            # Determine margin mode if tradeMode is ambiguous
            margin_mode = None
            if fetch_margin_mode and positions and positions[0].get("tradeMode") == 0 and float(positions[0].get("size")) != 0:
                print("Unified Account where trade mode is ambiguous, or we are really cross margin. Fetching account margin mode to be sure.")
                margin_mode = await self.get_account_margin_mode()

            unified_positions = [
                self.map_bybit_position_to_unified(pos, margin_mode)
                for pos in positions
                if float(pos.get("size", 0)) > 0
            ]

            for unified_position in unified_positions:
                print(f"Unified Position: {unified_position}")

            return unified_positions
        except Exception as e:
            print(f"Error mapping Bybit positions: {str(e)}")
            return []
    
    def map_bybit_position_to_unified(self, position: dict, margin_mode: str = None) -> UnifiedPosition:
        """Convert a Bybit position response into a UnifiedPosition object."""
        size = abs(float(position.get("size", 0)))
        direction = "long" if position.get("side", "").lower() == "buy" else "short"
        # adjust size for short positions
        if direction == "short":
            size = -size

        # Use provided margin mode if available, otherwise derive from tradeMode
        margin_mode = margin_mode or ("isolated" if position.get("tradeMode") == 1 else "cross")
        
        # User inverse mapping to convert margin mode to unified format
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
            tickers = self.bybit_client.get_tickers(category="linear", symbol=symbol)
            ticker_data = tickers["result"]["list"][0]  # Assuming the first entry is the relevant ticker
            
            print(f"Ticker: {ticker_data}")
            return UnifiedTicker(
                symbol=symbol,
                bid=float(ticker_data.get("bid1Price", 0)),
                ask=float(ticker_data.get("ask1Price", 0)),
                last=float(ticker_data.get("lastPrice", 0)),
                volume=float(ticker_data.get("volume24h", 0)),
                exchange=self.exchange_name
            )
        except Exception as e:
            print(f"Error fetching tickers from Bybit: {str(e)}")

    async def get_symbol_details(self, symbol: str):
        """Fetch instrument details including tick size, lot size, min size, and contract value."""
        instruments = self.bybit_client.get_instruments_info(category="linear", symbol=symbol)

        for instrument in instruments["result"]["list"]:
            if instrument["symbol"] == symbol:
                #print(f"Instrument: {instrument}")
                lot_size = float(instrument["lotSizeFilter"]["qtyStep"])
                min_size = float(instrument["lotSizeFilter"]["minOrderQty"])
                tick_size = float(instrument["priceFilter"]["tickSize"])
                contract_value = float(lot_size / min_size)  # Optional fallback

                return lot_size, min_size, tick_size, contract_value
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
        
        # Calculate number of decimal places from lot_size
        decimal_places = len(str(lot_size).split('.')[-1]) if '.' in str(lot_size) else 0
        # Round to the nearest lot size using the correct decimal places
        size_in_lots = round(size_in_lots / lot_size) * lot_size
        # Format to avoid floating point precision issues
        size_in_lots = float(f"%.{decimal_places}f" % size_in_lots)
        print(f"Size after rounding to lot size: {size_in_lots}")

        # Step 3: Round the price to the nearest tick size
        print(f"Price before: {price}")
        price = round_to_tick_size(price, tick_size)
        print(f"Price after tick rounding: {price}")

        return size_in_lots, price, lot_size

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
            
            # Fetch and scale the size and price
            lots, price, _ = await self.scale_size_and_price(symbol, size, price)
            print(f"Ordering {lots} lots @ {price}")
            #quit()
            
            # set leverage and margin mode    
            try:
                self.bybit_client.set_margin_mode(
                    setMarginMode=bybit_margin_mode,
                )   
            except Exception as e:
                print(f"Margin Mode unchanged: {str(e)}")
            
            try:     
                self.bybit_client.set_leverage(
                    symbol=symbol, 
                    category=category,                
                    buyLeverage=str(leverage), 
                    sellLeverage=str(leverage),
                )
            except Exception as e:
                print(f"Leverage unchanged: {str(e)}")
            
            order = self.bybit_client.place_order(
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
            print(f"Limit Order Placed: {order}")
            # Limit Order Placed: {'retCode': 0, 'retMsg': 'OK', 'result': {'orderId': '2c9eee09-b90e-47eb-ace0-d82c6cdc7bfa', 'orderLinkId': '20241014022046505544'}, 'retExtInfo': {}, 'time': 1728872447805}
            # Controlling 0.001 of BTC $62,957.00 is expected to be 62.957 USDT
            # Actual Margin Used: 12.6185 USDT @ 5x 
            return order
            
        except Exception as e:
            print(f"Error placing limit order: {str(e)}")

    async def open_market_position(self, symbol: str, side: str, size: float, leverage: int, margin_mode: str, scale_lot_size: bool = True, adjust_leverage: bool = True, adjust_margin_mode: bool = True):
        """Open a position with a market order."""
        try:
            client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
            lots = (await self.scale_size_and_price(symbol, size, price=0))[0] if scale_lot_size else size
            print(f"Processing {lots} lots of {symbol} with a {side} order.")

            if adjust_margin_mode:
                bybit_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
                try:
                    self.bybit_client.set_margin_mode(
                        setMarginMode=bybit_margin_mode
                    )
                except Exception as e:
                    print(f"Margin Mode unchanged: {str(e)}")
            
            if adjust_leverage:
                try:
                    self.bybit_client.set_leverage(
                        symbol=symbol, 
                        category="linear", 
                        buyLeverage=str(leverage), 
                        sellLeverage=str(leverage),
                    )
                except Exception as e:
                    print(f"Leverage unchanged: {str(e)}")

            order = self.bybit_client.place_order(
                category="linear",
                symbol=symbol,
                side=side.capitalize(),
                qty=lots,
                order_type="Market",
                isLeverage=1,
                orderLinkId=client_oid,
                positionIdx=0,
            )
            print(f"Market Order Placed: {order}")
            return order
        except Exception as e:
            print(f"Error placing market order: {str(e)}")

    async def close_position(self, symbol: str):
        """Close the position for a specific symbol."""
        try:
            # Fetch open positions to determine the side to close
            positions = await self.fetch_open_positions(symbol)
            if not positions["result"]["list"]:
                print(f"No open position found for {symbol}.")
                return None

            position = positions["result"]["list"][0]
            side = "Sell" if position["side"].lower() == "buy" else "Buy"
            size = float(position["size"])
            leverage = float(position["leverage"])
            margin_mode = "isolated" if position["tradeMode"] == 1 else "cross"

            print(f"Closing {size} lots of {symbol} with market order.")

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
            print(f"Position Closed: {order}")
            return order

        except Exception as e:
            print(f"Error closing position: {str(e)}")

    async def reconcile_position(self, symbol: str, size: float, leverage: int, margin_mode: str):
        """
        Reconcile the current position with the target size, leverage, and margin mode.
        If the position flips from long to short or vice versa, the current position is closed first.
        """
        try:
            # Fetch current positions for the given symbol
            unified_positions = await self.fetch_and_map_positions(symbol, fetch_margin_mode=size != 0)
            current_position = unified_positions[0] if unified_positions else None

            # Scale the target size to match exchange requirements
            if size != 0:
                size, _, lot_size = await self.scale_size_and_price(symbol, size, price=0)  # No price needed for market orders

            # Initialize current state variables
            current_size = current_position.size if current_position else 0
            current_margin_mode = current_position.margin_mode if current_position else None
            current_leverage = current_position.leverage if current_position else None
            
            # Determine if the position is flipping (long to short or vice versa)
            if (current_size > 0 and size < 0) or (current_size < 0 and size > 0):
                print(f"Flipping position from {current_size} to {size}. Closing current position first.")
                await self.close_position(symbol)  # Close the current position
                current_size = 0  # Reset current size to 0 after closure
                
            # Adjust margin mode and leverage if necessary, and the position exists
            if current_size != 0 and size != 0:
                if current_margin_mode != margin_mode:
                    print(f"Adjusting margin mode to {margin_mode}.")
                    bybit_margin_mode = self.margin_mode_map.get(margin_mode, margin_mode)
                    try:
                        self.bybit_client.set_margin_mode(setMarginMode=bybit_margin_mode)
                    except Exception as e:
                        print(f"Failed to adjust margin mode: {str(e)}")

                if current_leverage != leverage:
                    print(f"Adjusting leverage to {leverage}.")
                    try:
                        self.bybit_client.set_leverage(
                            symbol=symbol,
                            category="linear",
                            buyLeverage=str(leverage),
                            sellLeverage=str(leverage)
                        )
                    except Exception as e:
                        print(f"Failed to adjust leverage: {str(e)}")

            # Calculate the size difference after potential closure
            size_diff = size - current_size
            
            # Format size_diff using lot_size precision
            decimal_places = len(str(lot_size).split('.')[-1]) if '.' in str(lot_size) else 0
            size_diff = float(f"%.{decimal_places}f" % size_diff)
            
            print(f"Current size: {current_size}, Target size: {size}, Size difference: {size_diff}")

            # If the target size is already reached, no action is needed
            if size_diff == 0:
                print(f"Position for {symbol} is already at the target size.")
                return

            # Determine the side (buy/sell) for the adjustment order
            side = "Buy" if size_diff > 0 else "Sell"
            size_diff = abs(size_diff)  # Use absolute value for the order size

            print(f"Placing a {side} order to adjust position by {size_diff}.")
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
            print(f"Error reconciling position: {str(e)}")

    async def test_symbol_formats(self):
        """Test function to dump symbol information for mapping."""
        try:
            # Test common symbols
            test_symbols = ["BTCUSDT", "ETHUSDT"]
            
            for symbol in test_symbols:
                try:
                    # Get instrument info
                    instrument = self.bybit_client.get_instruments_info(
                        category="linear",
                        symbol=symbol
                    )
                    
                    print(f"\nBybit Symbol Information for {symbol}:")
                    print(f"Native Symbol Format: {symbol}")
                    #print(f"Full Response: {instrument}")
                    
                    # Try to fetch a ticker to verify symbol works
                    ticker = await self.fetch_tickers(symbol)
                    #print(f"Ticker Test: {ticker}")
                    
                except Exception as e:
                    print(f"Error testing {symbol}: {str(e)}")
                    
            # Add to test_symbol_formats() in each processor
            test_symbols = ["BTCUSDT", "ETHUSDT"]
            print("\nTesting symbol mapping:")
            for symbol in test_symbols:
                mapped = self.map_signal_symbol_to_exchange(symbol)
                print(f"Signal symbol: {symbol} -> Exchange symbol: {mapped}")
                    
        except Exception as e:
            print(f"Error in symbol format test: {str(e)}")

    def map_signal_symbol_to_exchange(self, signal_symbol: str) -> str:
        """Convert signal symbol format (e.g. BTCUSDT) to exchange format."""
        # Bybit uses the same format as our signals, no conversion needed
        return signal_symbol

    async def fetch_total_account_value(self) -> float:
        """Calculate total account value from balance and initial margin of positions."""
        try:
            # Get available balance
            balance = await self.fetch_balance("USDT")
            available_balance = float(balance) if balance else 0.0
            print(f"Available Balance: {available_balance} USDT")
            
            # Get positions directly - Bybit provides positionIM (initial margin)
            positions = await self.fetch_all_open_positions()
            position_margin = 0.0
            if positions and "result" in positions:
                for pos in positions["result"]["list"]:
                    position_margin += float(pos["positionIM"])  # Direct initial margin value
            print(f"Position Initial Margin: {position_margin} USDT")
            
            total_value = available_balance + position_margin
            print(f"ByBit Total Account Value: {total_value} USDT")
            return total_value
            
        except Exception as e:
            print(f"Error calculating total account value: {str(e)}")
            return 0.0


async def main():   
    # Start a time
    start_time = datetime.datetime.now()
    
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
    
    # Test total account value calculation
    print("\nTesting total account value calculation:")
    total_value = await bybit.fetch_total_account_value()
    print(f"Final Total Account Value: {total_value} USDT")
    
    # End time
    end_time = datetime.datetime.now()
    print(f"Time taken: {end_time - start_time}")
    
if __name__ == "__main__":
    asyncio.run(main())
