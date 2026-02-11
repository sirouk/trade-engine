import asyncio
import datetime
from blofin import BloFinClient  # https://github.com/nomeida/blofin-python
from config.credentials import load_blofin_credentials
from core.utils.modifiers import scale_size_and_price
from core.unified_position import UnifiedPosition
from core.unified_ticker import UnifiedTicker
from core.utils.execute_timed import execute_with_timeout


class BloFin:
    # BloFin uses PEPE-USDT while some upstream signals normalize to 1000PEPEUSDT.
    SIGNAL_SYMBOL_OVERRIDES = {
        "1000PEPEUSDT": "PEPE-USDT",
    }

    def __init__(self):
        self.exchange_name = "BloFin"
        self.enabled = True

        self.credentials = load_blofin_credentials()
        self.copy_trading = bool(getattr(self.credentials.blofin, "copy_trading", False))
        self.account_type = "copy_trading" if self.copy_trading else "futures"

        # Initialize the BloFin client
        self.blofin_client = BloFinClient(
            api_key=self.credentials.blofin.api_key,
            api_secret=self.credentials.blofin.api_secret,
            passphrase=self.credentials.blofin.api_passphrase,
        )

        self.margin_mode_map = {  # unusued as they are not needed
            "isolated": "isolated",
            "cross": "cross",
        }

        self.inverse_margin_mode_map = {
            v: k for k, v in self.margin_mode_map.items()
        }  # unusued as they are not needed

        self.leverage_override = self.credentials.blofin.leverage_override

        # Add logger prefix
        self.log_prefix = f"[{self.exchange_name}]"
        print(
            f"{self.log_prefix} Using {'copy trading' if self.copy_trading else 'futures'} trading endpoints."
        )

        # Route trading endpoints based on account mode.
        self._get_positions_api = (
            self.blofin_client.trading.get_positions_ct
            if self.copy_trading
            else self.blofin_client.trading.get_positions
        )
        self._get_active_orders_api = (
            self.blofin_client.trading.get_active_orders_ct
            if self.copy_trading
            else self.blofin_client.trading.get_active_orders
        )
        self._place_order_api = (
            self.blofin_client.trading.place_order_ct
            if self.copy_trading
            else self.blofin_client.trading.place_order
        )
        self._set_leverage_api = (
            self.blofin_client.trading.set_leverage_ct
            if self.copy_trading
            else self.blofin_client.trading.set_leverage
        )
        self._close_positions_api = (
            self.blofin_client.trading.close_positions_ct
            if self.copy_trading
            else self.blofin_client.trading.close_positions
        )

    async def _close_positions(
        self,
        symbol: str,
        margin_mode: str,
        position_side: str,
        client_order_id: str,
        size: float | None = None,
        close_type: str = "pnl",
    ):
        kwargs = {
            "inst_id": symbol,
            "margin_mode": margin_mode,
            "position_side": position_side,
            "client_order_id": client_order_id,
        }

        if self.copy_trading:
            kwargs["close_type"] = close_type
            if size is not None:
                kwargs["size"] = size

        return await execute_with_timeout(
            self._close_positions_api,
            timeout=5,
            **kwargs,
        )

    async def fetch_balance(self, instrument="USDT"):
        try:
            balance = await execute_with_timeout(
                self.blofin_client.account.get_balance,
                timeout=5,
                account_type=self.account_type,
                currency=instrument,
            )
            # {'code': '0', 'msg': 'success', 'data': [{'currency': 'USDT', 'balance': '0.000000000000000000', 'available': '0.000000000000000000', 'frozen': '0.000000000000000000', 'bonus': '0.000000000000000000'}]}

            # get coin balance available to trade
            balance = balance["data"][0]["available"]
            print(f"{self.log_prefix} Account Balance for {instrument}: {balance}")
            return balance
        except Exception as e:
            print(f"{self.log_prefix} Error fetching balance: {str(e)}")

    # fetch all open positions
    async def fetch_all_open_positions(self):
        try:
            positions = await execute_with_timeout(
                self._get_positions_api, timeout=5
            )
            return positions
        except Exception as e:
            print(f"{self.log_prefix} Error fetching all open positions: {str(e)}")

    async def fetch_open_positions(self, symbol):
        try:
            positions = await execute_with_timeout(
                self._get_positions_api, timeout=5, inst_id=symbol
            )
            print(f"{self.log_prefix} Open Positions: {positions}")
            return positions
        except Exception as e:
            print(f"{self.log_prefix} Error fetching open positions: {str(e)}")

    async def fetch_open_orders(self, symbol):
        try:
            orders = await execute_with_timeout(
                self._get_active_orders_api,
                timeout=5,
                inst_id=symbol,
            )
            print(f"{self.log_prefix} Open Orders: {orders}")
            return orders
        except Exception as e:
            print(f"{self.log_prefix} Error fetching open orders: {str(e)}")

    async def fetch_and_map_positions(self, symbol: str):
        """Fetch open positions from BloFin and convert them to UnifiedPosition objects."""
        try:
            response = await execute_with_timeout(
                self._get_positions_api, timeout=5, inst_id=symbol
            )
            positions = response.get("data", [])
            # print(positions)
            # quit()

            # Convert to UnifiedPosition objects
            unified_positions = [
                self.map_blofin_position_to_unified(pos)
                for pos in positions
                if float(pos.get("positions", 0)) != 0
            ]

            for unified_position in unified_positions:
                print(f"{self.log_prefix} Unified Position: {unified_position}")

            return unified_positions
        except Exception as e:
            print(f"{self.log_prefix} Error mapping BloFin positions: {str(e)}")
            return []

    def map_blofin_position_to_unified(self, position: dict) -> UnifiedPosition:
        """Convert a BloFin position response into a UnifiedPosition object."""
        size = abs(
            float(position.get("positions", 0))
        )  # Handle both long and short positions
        direction = "long" if float(position.get("positions", 0)) > 0 else "short"
        # adjust size for short positions
        if direction == "short":
            size = -size

        # Use provided margin mode if available, otherwise derive from tradeMode
        margin_mode = position.get("marginMode")
        if margin_mode is None:
            raise ValueError("Margin mode not found in position data.")

        return UnifiedPosition(
            symbol=position["instId"],
            size=size,
            average_entry_price=float(position.get("averagePrice", 0)),
            leverage=float(position.get("leverage", 1)),
            direction=direction,
            unrealized_pnl=float(position.get("unrealizedPnl", 0)),
            margin_mode=margin_mode,
            exchange=self.exchange_name,
        )

    async def fetch_tickers(self, symbol):
        try:
            tickers = await execute_with_timeout(
                self.blofin_client.public.get_tickers, timeout=5, inst_id=symbol
            )
            ticker_data = self._extract_ticker_data(tickers)

            # Fallback for symbols normalized with 1000 prefix when BloFin expects spot-style base.
            if ticker_data is None:
                fallback_symbol = self._fallback_symbol(symbol)
                if fallback_symbol and fallback_symbol != symbol:
                    print(
                        f"{self.log_prefix} No ticker data for {symbol}, retrying with {fallback_symbol}."
                    )
                    tickers = await execute_with_timeout(
                        self.blofin_client.public.get_tickers,
                        timeout=5,
                        inst_id=fallback_symbol,
                    )
                    ticker_data = self._extract_ticker_data(tickers)
                    symbol = fallback_symbol

            if ticker_data is None:
                print(f"{self.log_prefix} No ticker data returned for {symbol}: {tickers}")
                return None

            print(f"{self.log_prefix} Ticker: {ticker_data}")
            return UnifiedTicker(
                symbol=symbol,
                bid=float(ticker_data.get("bidPrice", 0)),
                ask=float(ticker_data.get("askPrice", 0)),
                last=float(ticker_data.get("last", 0)),
                volume=float(ticker_data.get("volCurrency24h", 0)),
                exchange=self.exchange_name,
            )
        except Exception as e:
            print(f"{self.log_prefix} Error fetching tickers from Blofin: {str(e)}")

    def _extract_ticker_data(self, tickers: dict):
        if not isinstance(tickers, dict):
            return None
        data = tickers.get("data")
        if not isinstance(data, list) or not data:
            return None
        return data[0]

    def _fallback_symbol(self, symbol: str) -> str | None:
        if symbol.startswith("1000") and symbol.endswith("-USDT"):
            return symbol[4:]
        return None

    async def get_symbol_details(self, symbol: str):
        """Fetch instrument details including tick size, lot size, and max size."""
        try:
            instruments = await execute_with_timeout(
                self.blofin_client.public.get_instruments,  # get_instruments_ct is not needed as it is the same as get_instruments
                timeout=5,
                inst_type="SWAP",
            )
            for instrument in instruments["data"]:
                if instrument["instId"] == symbol:
                    # print(f"Symbol: {symbol} -> {instrument}")
                    lot_size = float(instrument["lotSize"])
                    min_size = float(instrument["minSize"])
                    tick_size = float(instrument["tickSize"])
                    contract_value = float(instrument["contractValue"])
                    # BloFin uses maxMarketSize for market orders and maxLimitSize for limit orders
                    max_market_size = float(instrument.get("maxMarketSize", 1000000))
                    max_limit_size = float(
                        instrument.get("maxLimitSize", max_market_size)
                    )
                    # Use the market order limit as it's more restrictive
                    max_size = max_market_size

                    print(
                        f"{self.log_prefix} Symbol {symbol} -> Lot Size: {lot_size}, Min Size: {min_size}, Tick Size: {tick_size}, Contract Value: {contract_value}"
                    )
                    print(
                        f"{self.log_prefix} Max Limit Size: {max_limit_size}, Max Market Size: {max_market_size}"
                    )
                    return lot_size, min_size, tick_size, contract_value, max_size
            raise ValueError(f"Symbol {symbol} not found.")
        except Exception as e:
            print(f"{self.log_prefix} Error fetching symbol details: {str(e)}")
            return None

    async def _place_limit_order_test(
        self,
    ):
        """Place a limit order on BloFin."""
        try:
            # Test limit order
            # https://docs.blofin.com/index.html#place-order
            # NOTE: margin mode is able to be switched here in the API
            symbol = "BTC-USDT"
            side = "buy"
            position_side = "net"  # net for one-way, long/short for hedge mode
            price = 62850
            size = 0.003  # in quantity of symbol
            leverage = 3
            order_type = "ioc"  # market: market order, limit: limit order, post_only: Post-only order, fok: Fill-or-kill order, ioc: Immediate-or-cancel order
            # time_in_force is implied in order_type
            margin_mode = "isolated"  # isolated, cross
            client_order_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

            # Fetch symbol details (e.g., contract value, lot size, tick size)
            (
                lot_size,
                min_lots,
                tick_size,
                contract_value,
                max_size,
            ) = await self.get_symbol_details(symbol)

            # Fetch and scale the size and price
            lots, price, _ = scale_size_and_price(
                symbol, size, 0, lot_size, min_lots, tick_size, contract_value
            )
            print(f"Ordering {lots} lots @ {price}")
            # quit()

            order = await execute_with_timeout(
                self._place_order_api,
                timeout=5,
                inst_id=symbol,
                side=side.lower(),
                position_side=position_side,
                price=price,
                size=lots,
                leverage=leverage,
                order_type=order_type,
                margin_mode=margin_mode,
                clientOrderId=client_order_id,
            )
            print(f"{self.log_prefix} Limit Order Placed: {order}")
            # Limit Order Placed: {'code': '0', 'msg': '', 'data': [{'orderId': '1000012973229', 'clientOrderId': '20241014022135830998', 'msg': 'success', 'code': '0'}]}
        except Exception as e:
            print(f"{self.log_prefix} Error placing limit order: {str(e)}")

    async def open_market_position(
        self,
        symbol: str,
        side: str,
        size: float,
        leverage: int,
        margin_mode: str,
        scale_lot_size: bool = True,
    ):
        """Open a position with a market order on BloFin."""
        try:
            # Fetch symbol details (e.g., contract value, lot size, tick size)
            (
                lot_size,
                min_lots,
                tick_size,
                contract_value,
                max_size,
            ) = await self.get_symbol_details(symbol)

            # Fetch and scale the size
            lots = (
                (
                    scale_size_and_price(
                        symbol, size, 0, lot_size, min_lots, tick_size, contract_value
                    )
                )[0]
                if scale_lot_size
                else size
            )
            print(
                f"{self.log_prefix} Processing {lots} lots of {symbol} with market order"
            )

            # Check if order size exceeds maximum order quantity
            if lots > max_size:
                print(
                    f"{self.log_prefix} Order size {lots} exceeds max order qty {max_size}. Splitting into chunks."
                )

                # Calculate number of full chunks and remainder
                num_full_chunks = int(lots // max_size)
                remainder = lots % max_size

                # Round remainder to lot size precision
                decimal_places = (
                    len(str(lot_size).rsplit(".", maxsplit=1)[-1])
                    if "." in str(lot_size)
                    else 0
                )
                remainder = float(f"%.{decimal_places}f" % remainder)

                orders = []
                total_executed = 0

                # Place full-sized chunks
                for i in range(num_full_chunks):
                    chunk_size = max_size
                    print(
                        f"{self.log_prefix} Placing chunk {i + 1}/{num_full_chunks + (1 if remainder > 0 else 0)}: {chunk_size} lots"
                    )

                    client_order_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

                    # Place the market order
                    order = await execute_with_timeout(
                        self._place_order_api,
                        timeout=5,
                        inst_id=symbol,
                        side=side.lower(),
                        position_side="net",
                        price=0,
                        size=chunk_size,
                        leverage=leverage,
                        order_type="market",
                        margin_mode=margin_mode,
                        clientOrderId=client_order_id,
                    )
                    orders.append(order)
                    total_executed += chunk_size
                    print(f"{self.log_prefix} Chunk order placed: {order}")

                    # Small delay between orders to avoid rate limiting
                    await asyncio.sleep(0.1)

                # Place remainder if exists
                if remainder > 0:
                    print(f"{self.log_prefix} Placing final chunk: {remainder} lots")
                    client_order_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

                    # Place the market order
                    order = await execute_with_timeout(
                        self._place_order_api,
                        timeout=5,
                        inst_id=symbol,
                        side=side.lower(),
                        position_side="net",
                        price=0,
                        size=remainder,
                        leverage=leverage,
                        order_type="market",
                        margin_mode=margin_mode,
                        clientOrderId=client_order_id,
                    )
                    orders.append(order)
                    total_executed += remainder
                    print(f"{self.log_prefix} Final chunk order placed: {order}")

                print(
                    f"{self.log_prefix} Successfully executed {total_executed} lots across {len(orders)} orders"
                )
                return orders  # Return list of orders

            else:
                # Order size is within limits, proceed normally
                client_order_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

                # Place the market order
                order = await execute_with_timeout(
                    self._place_order_api,
                    timeout=5,
                    inst_id=symbol,
                    side=side.lower(),
                    position_side="net",  # Adjust based on your account mode (e.g., 'net', 'long', 'short')
                    price=0,  # required for market orders
                    size=lots,
                    leverage=leverage,
                    order_type="market",  # Market order type
                    margin_mode=margin_mode,
                    clientOrderId=client_order_id,
                )
                print(f"{self.log_prefix} Market Order Placed: {order}")
                return order

        except Exception as e:
            print(f"{self.log_prefix} Error placing market order: {str(e)}")

    async def close_position(self, symbol: str):
        """Close the position for a specific symbol on BloFin."""
        try:
            # Fetch open positions for the specified symbol
            response = await self.fetch_open_positions(symbol)
            positions = response.get("data", [])

            if not positions:
                print(f"{self.log_prefix} No open position found for {symbol}.")
                return None

            # Extract the position details
            position = positions[0]
            size = float(position["positions"])  # Use the 'positions' value directly

            # Determine the side based on the position size
            side = "Sell" if size > 0 else "Buy"  # Long -> Sell, Short -> Buy
            size = abs(size)  # Negate size by using its absolute value
            print(
                f"{self.log_prefix} Closing {size} lots of {symbol} with a market order."
            )

            # Place a market order in the opposite direction to close the position
            client_order_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
            order = await self._close_positions(
                symbol=symbol,
                margin_mode=position["marginMode"],  # Use the same margin mode
                position_side=position["positionSide"],  # Ensure the same position mode
                client_order_id=client_order_id,
                size=size,
            )

            print(f"{self.log_prefix} Position Closed: {order}")
            return order

        except Exception as e:
            print(f"{self.log_prefix} Error closing position: {str(e)}")

    async def reconcile_position(
        self, symbol: str, size: float, leverage: int, margin_mode: str
    ):
        """
        Reconcile the current position with the target size, leverage, and margin mode.
        """
        try:
            # Use leverage override if set
            if self.leverage_override > 0:
                print(
                    f"{self.log_prefix} Using exchange-specific leverage override: {self.leverage_override}"
                )
                leverage = self.leverage_override

            unified_positions = await self.fetch_and_map_positions(symbol)
            current_position = unified_positions[0] if unified_positions else None

            # Fetch symbol details (e.g., contract value, lot size, tick size)
            (
                lot_size,
                min_lots,
                tick_size,
                contract_value,
                max_size,
            ) = await self.get_symbol_details(symbol)

            # if size != 0:
            # Always scale as we need lot_size
            size, _, lot_size = scale_size_and_price(
                symbol, size, 0, lot_size, min_lots, tick_size, contract_value
            )  # No price for market orders

            # Initialize position state variables
            current_size = current_position.size if current_position else 0
            current_margin_mode = (
                current_position.margin_mode if current_position else None
            )
            current_leverage = current_position.leverage if current_position else None

            # Handle position flips (long to short or vice versa)
            if (current_size > 0 and size < 0) or (current_size < 0 and size > 0):
                print(
                    f"{self.log_prefix} Flipping position from {current_size} to {size}. Closing current position."
                )
                await self.close_position(symbol)
                current_size = 0
            # Handle position size reduction
            elif current_size != 0 and abs(size) < abs(current_size):
                reduction_size = abs(current_size) - abs(size)
                print(
                    f"{self.log_prefix} Reducing position size from {current_size} to {size} (reduction: {reduction_size})"
                )

                # Determine side for reduction (opposite of current position)
                side = "sell" if current_size > 0 else "buy"

                if self.copy_trading:
                    client_order_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
                    await self._close_positions(
                        symbol=symbol,
                        margin_mode=current_margin_mode,
                        position_side="net",
                        client_order_id=client_order_id,
                        size=reduction_size,
                    )
                else:
                    # Standard futures endpoint does not support partial size on close_positions.
                    # Reduce by sending the opposite market order in net mode.
                    await self.open_market_position(
                        symbol=symbol,
                        side=side,
                        size=reduction_size,
                        leverage=leverage,
                        margin_mode=current_margin_mode or margin_mode,
                        scale_lot_size=False,
                    )
                current_size = size

            # Check for margin mode or leverage changes
            if current_size != 0 and size != 0:
                # Since Blofin does not support changing margin mode or leverage on existing positions, we need to close the position first
                if current_margin_mode != margin_mode:
                    print(
                        f"{self.log_prefix} Margin mode change detected. Closing current position to adjust margin mode from {current_margin_mode} to {margin_mode}."
                    )
                    await self.close_position(symbol)
                    current_size = 0

                    # no need to change margin mode here, as new position will be opened with the desired margin mode

            # if leverage is different, or we are opening a new position, and not closing a position
            if current_leverage != leverage and abs(size) > 0:
                print(
                    f"{self.log_prefix} Adjusting leverage to {leverage} for {symbol} and position margin mode to {margin_mode}."
                )
                try:
                    await execute_with_timeout(
                        self._set_leverage_api,
                        timeout=5,
                        inst_id=symbol,
                        leverage=leverage,
                        margin_mode=margin_mode,
                        position_side="net",
                    )
                except Exception as e:
                    print(f"{self.log_prefix} Failed to adjust leverage: {str(e)}")

            # Calculate the remaining size difference after any position closure
            # Format to required decimal places and convert back to float
            decimal_places = (
                len(str(lot_size).rsplit(".", maxsplit=1)[-1])
                if "." in str(lot_size)
                else 0
            )
            size_diff = float(f"%.{decimal_places}f" % (size - current_size))

            # Tolerance logic to prevent unnecessary trades:
            # 1. If closing position (target=0): only skip if already below tradable minimum (current < min_lots)
            # 2. If opening position (current=0): always proceed
            # 3. If both non-zero: use tolerance (lot_size or 0.1% of position) to avoid tiny adjustments
            if size == 0:
                # Closing position: only skip if current size is strictly below min tradable lot.
                # If size equals min_lots, it is still a real open position and must be closed.
                if abs(current_size) < min_lots:
                    print(
                        f"{self.log_prefix} Position for {symbol} is already effectively closed (size={abs(current_size):.6f} < min={min_lots})."
                    )
                    return
                # Otherwise, always close (size_diff ensures we proceed)
            elif abs(current_size) == 0:
                # Opening position: always proceed
                pass
            else:
                # Both non-zero: use tolerance to avoid unnecessary trades
                # Tolerance = max(lot_size, 0.1% of smaller position value)
                position_tolerance = max(
                    lot_size, min(abs(current_size), abs(size)) * 0.001
                )

                if abs(size_diff) < position_tolerance:
                    print(
                        f"{self.log_prefix} Position for {symbol} is already at target size (current={current_size:.6f}, target={size:.6f}, diff={size_diff:.6f}, tolerance={position_tolerance:.6f})."
                    )
                    return

            print(
                f"{self.log_prefix} Adjusting position: current={current_size:.6f}, target={size:.6f}, diff={size_diff:.6f}"
            )

            # Determine the side of the new order (buy/sell)
            side = "Buy" if size_diff > 0 else "Sell"
            size_diff = abs(size_diff)  # Work with absolute size for the order

            print(
                f"{self.log_prefix} Placing a {side} order to adjust position by {size_diff}."
            )
            await self.open_market_position(
                symbol=symbol,
                side=side.lower(),
                size=size_diff,
                leverage=leverage,
                margin_mode=margin_mode,
                scale_lot_size=False,  # Preserving the scale_lot_size parameter
            )
        except Exception as e:
            print(f"{self.log_prefix} Error reconciling position: {str(e)}")

    async def test_symbol_formats(self):
        """Test function to dump symbol information for mapping."""
        try:
            # Test common symbols
            test_symbols = ["BTC-USDT", "ETH-USDT"]

            for symbol in test_symbols:
                try:
                    # Get instrument info
                    instrument = await execute_with_timeout(
                        self.blofin_client.public.get_instruments,  # get_instruments_ct is not needed as it is the same as get_instruments
                        timeout=5,
                        inst_type="SWAP",
                    )

                    print(
                        f"\n{self.log_prefix} BloFin Symbol Information for {symbol}:"
                    )
                    print(f"{self.log_prefix} Native Symbol Format: {symbol}")
                    # print(f"Full Response: {instrument}")

                    # Try to fetch a ticker to verify symbol works
                    ticker = await self.fetch_tickers(symbol)
                    # print(f"Ticker Test: {ticker}")

                except Exception as e:
                    print(f"{self.log_prefix} Error testing {symbol}: {str(e)}")

            # Test symbol mapping
            test_signals = ["BTCUSDT", "ETHUSDT"]
            print("\n{self.log_prefix} Testing symbol mapping:")
            for symbol in test_signals:
                mapped = self.map_signal_symbol_to_exchange(symbol)
                print(
                    f"{self.log_prefix} Signal symbol: {symbol} -> Exchange symbol: {mapped}"
                )

        except Exception as e:
            print(f"{self.log_prefix} Error in symbol format test: {str(e)}")

    def map_signal_symbol_to_exchange(self, signal_symbol: str) -> str:
        """Convert signal symbol format (e.g. BTCUSDT) to exchange format."""
        if signal_symbol in self.SIGNAL_SYMBOL_OVERRIDES:
            return self.SIGNAL_SYMBOL_OVERRIDES[signal_symbol]

        # BloFin uses hyphen separator
        # Extract base and quote from BTCUSDT format
        if "USDT" in signal_symbol:
            base = signal_symbol.replace("USDT", "")
            return f"{base}-USDT"
        return signal_symbol

    async def fetch_initial_account_value(self) -> float:
        """Calculate total account value from balance and initial margin of positions."""
        try:
            # Get available balance
            balance = await self.fetch_balance("USDT")
            available_balance = float(balance) if balance else 0.0
            print(f"{self.log_prefix} Available Balance: {available_balance} USDT")

            # Get positions directly - BloFin provides margin directly
            positions = await self.fetch_all_open_positions()
            position_margin = 0.0
            if positions and "data" in positions:
                for pos in positions["data"]:
                    position_margin += float(pos["margin"])  # Direct margin value
            print(f"{self.log_prefix} Position Initial Margin: {position_margin} USDT")

            total_value = available_balance + position_margin
            print(f"{self.log_prefix} BloFin Initial Account Value: {total_value} USDT")
            return total_value

        except Exception as e:
            print(
                f"{self.log_prefix} Error calculating initial account value: {str(e)}"
            )
            return 0.0


async def main():
    # Start a time
    start_time = datetime.datetime.now()

    from core.utils.execute_timed import execute_with_timeout

    blofin = BloFin()

    # balance = await blofin.fetch_balance(instrument="USDT")      # Fetch futures balance
    # print(balance)

    # initial_account_value = await blofin.fetch_initial_account_value()
    # print(f"Initial Account Value: {initial_account_value} USDT")

    # tickers = await blofin.fetch_tickers(symbol="BTC-USDT")  # Fetch market tickers
    # print(tickers)

    # order_results = await blofin._place_limit_order_test()
    # print(order_results)

    # order_results = await blofin.open_market_position(
    #     symbol="BTC-USDT",
    #     side="sell",
    #     size=0.002,
    #     leverage=5,
    #     margin_mode="isolated",
    # )
    # print(order_results)

    # import time
    # time.sleep(5)

    # Example usage of reconcile_position to adjust position to the desired size, leverage, and margin type
    # await blofin.reconcile_position(
    #    symbol="BTC-USDT",   # Symbol to adjust
    #    size=0.001,  # Desired position size (positive for long, negative for short, zero to close)
    #    leverage=3,         # Desired leverage
    #    margin_mode="isolated"  # Desired margin mode
    # )

    # close_result = await blofin.close_position(symbol="BTC-USDT")
    # print(close_result)

    # orders = await blofin.fetch_open_orders(symbol="BTC-USDT")          # Fetch open orders
    # print(orders)

    # #await blofin.fetch_open_positions(symbol="BTC-USDT")       # Fetch open positions
    # positions = await blofin.fetch_and_map_positions(symbol="BTC-USDT")
    # #print(positions)

    # print("\nTesting total account value calculation:")
    # total_value = await blofin.fetch_initial_account_value()
    # print(f"Final Total Account Value: {total_value} USDT")

    # Test all open positions
    # print("\nTesting all open positions:")
    # positions = await blofin.fetch_all_open_positions()
    # positions is a dictionary
    # for key, value in positions.items():
    #    if "data" in key:
    #        for pos in value:
    #            print(f"")
    #            for dkey, dvalue in pos.items():
    #                print(f"Field: {dkey}, Value: {dvalue}")
    # print(f"All Open Positions: {positions}")

    # Test total account value calculation
    print("\nTesting total account value calculation:")
    total_value = await blofin.fetch_initial_account_value()
    print(f"{blofin.log_prefix} Final Total Account Value: {total_value} USDT")

    # Test fetching max order quantity
    print(f"\n{blofin.log_prefix} Testing symbol details and max order quantity:")
    try:
        symbol = "BTC-USDT"
        (
            lot_size,
            min_size,
            tick_size,
            contract_value,
            max_size,
        ) = await blofin.get_symbol_details(symbol)
        print(f"{blofin.log_prefix} Symbol: {symbol}")
        print(f"{blofin.log_prefix} Lot Size: {lot_size}")
        print(f"{blofin.log_prefix} Min Size: {min_size}")
        print(f"{blofin.log_prefix} Max Size: {max_size}")
        print(f"{blofin.log_prefix} Tick Size: {tick_size}")
        print(f"{blofin.log_prefix} Contract Value: {contract_value}")

        # Get full instrument details
        instruments = await execute_with_timeout(
            blofin.blofin_client.public.get_instruments, timeout=5, inst_type="SWAP"
        )
        for inst in instruments["data"]:
            if inst["instId"] == symbol:
                print(f"\n{blofin.log_prefix} Full instrument details for {symbol}:")
                for key in [
                    "maxSize",
                    "minSize",
                    "lotSize",
                    "tickSize",
                    "contractValue",
                    "maxLeverage",
                ]:
                    if key in inst:
                        print(f"{blofin.log_prefix} {key}: {inst[key]}")
                break
    except Exception as e:
        print(f"{blofin.log_prefix} Error testing symbol details: {str(e)}")

    # Test order chunking demonstration (commented out to avoid actual trading)
    """
    print(f"\n{blofin.log_prefix} Testing order chunking with large order:")
    try:
        # This would test chunking if the order exceeds max_size
        result = await blofin.open_market_position(
            symbol="BTC-USDT",
            side="buy",
            size=1000,  # Large size to test chunking
            leverage=5,
            margin_mode="isolated"
        )
        print(f"{blofin.log_prefix} Order result: {result}")
    except Exception as e:
        print(f"{blofin.log_prefix} Error testing order chunking: {str(e)}")
    """

    # End time
    end_time = datetime.datetime.now()
    print(f"{blofin.log_prefix} Time taken: {end_time - start_time}")


if __name__ == "__main__":
    asyncio.run(main())
