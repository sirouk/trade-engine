"""
Generic CCXT account processor that can work with any CCXT-supported exchange.
Requires: pip install "ccxt[async]"

LIMITATIONS:
- CCXT's unified API may not accurately report all exchange-specific features
- Margin mode detection may be incorrect for some exchanges
- For production use with specific exchanges, consider using native processors when available

For maximum accuracy with specific exchanges, use their native processors:
- Check if a native processor is available for your exchange
- Native processors can provide more accurate data for exchange-specific features
"""
import asyncio
import datetime
import ccxt.async_support as ccxt  # pip install "ccxt[async]"
from config.credentials import load_ccxt_credentials
from core.utils.modifiers import scale_size_and_price
from core.unified_position import UnifiedPosition
from core.unified_ticker import UnifiedTicker
from core.utils.execute_timed import execute_with_timeout
from config.credentials import CCXTCredentials


class CCXTProcessor:
    def __init__(self, ccxt_credentials: CCXTCredentials = None, exchange_name: str = None):
        """
        Initialize CCXT processor for any supported exchange.
        Pass either ccxt_credentials object or exchange_name (which loads from credentials file).
        """
        if ccxt_credentials:
            # Use provided credentials
            self.credentials = ccxt_credentials
            self.exchange_name = ccxt_credentials.exchange_name
        else:
            # Load credentials from file
            all_credentials = load_ccxt_credentials()
            
            # If exchange_name provided, find matching credentials
            if exchange_name:
                for cred in all_credentials.ccxt_list:
                    if cred.exchange_name == exchange_name:
                        self.credentials = cred
                        break
                else:
                    raise ValueError(f"No credentials found for exchange: {exchange_name}")
            else:
                # Use first available
                self.credentials = all_credentials.ccxt_list[0]
            
            self.exchange_name = self.credentials.exchange_name
        
        if not self.exchange_name:
            raise ValueError("No exchange name provided or found in credentials")
        
        # Validate and get exchange class
        exchange_class = self.get_exchange_class(self.exchange_name)
        
        self.enabled = self.credentials.enabled
        
        # Generic CCXT exchanges: Conservative default rate limiting
        # Individual exchanges may have different limits - adjust as needed
        self.MAX_CONCURRENT_SYMBOL_REQUESTS = 5
        
        # Initialize CCXT client
        config = {
            'apiKey': self.credentials.api_key,
            'secret': self.credentials.api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # Use perpetual futures
                'defaultMarginMode': 'isolated',  # Default to isolated margin
            }
        }
        
        # Add copy trading support if enabled
        if self.credentials.copy_trading:
            config['options']['accountType'] = 'copy_trading'  # Use copy trading account
        
        # Add passphrase if provided
        if self.credentials.api_passphrase:
            config['password'] = self.credentials.api_passphrase
            
        self.exchange = exchange_class(config)
        
        self.margin_mode_map = {
            "isolated": "isolated",
            "cross": "cross"
        }
        
        self.inverse_margin_mode_map = {v: k for k, v in self.margin_mode_map.items()}
        
        self.leverage_override = self.credentials.leverage_override

        # Add logger prefix
        self.log_prefix = f"[{self.exchange_name.upper()}]"

    @staticmethod
    def get_exchange_class(exchange_name: str):
        """Get CCXT exchange class by name and validate it exists."""
        try:
            # Convert to lowercase as CCXT uses lowercase names
            exchange_id = exchange_name.lower()
            
            # Check if exchange exists in CCXT
            if exchange_id not in ccxt.exchanges:
                raise ValueError(f"Exchange '{exchange_name}' is not supported by CCXT. "
                               f"Supported exchanges: {', '.join(sorted(ccxt.exchanges))}")
            
            # Get the exchange class
            exchange_class = getattr(ccxt, exchange_id)
            return exchange_class
        except AttributeError:
            raise ValueError(f"Failed to load exchange class for '{exchange_name}'")

    @staticmethod
    def list_supported_exchanges():
        """Return a list of all CCXT-supported exchanges."""
        return sorted(ccxt.exchanges)

    @staticmethod
    def validate_exchange_name(exchange_name: str) -> bool:
        """Check if an exchange name is valid."""
        return exchange_name.lower() in ccxt.exchanges

    async def fetch_balance(self, instrument="USDT"):
        try:
            balance = await execute_with_timeout(
                self.exchange.fetch_balance,
                timeout=5,
                params={'type': 'swap'}  # Fetch futures balance
            )
            
            # CCXT returns balance in a standardized format
            # balance['USDT'] = {'free': x, 'used': y, 'total': z}
            if instrument in balance:
                available = balance[instrument]['free']
                return available
            else:
                return 0
        except Exception as e:
            return 0
            
    async def fetch_all_open_positions(self):
        try:
            # Special handling for BloFin copy trading accounts
            params = {'type': 'swap'}
            if self.credentials.copy_trading and self.exchange_name.lower() == 'blofin':
                params['accountType'] = 'copy_trading'
                
            positions = await execute_with_timeout(
                self.exchange.fetch_positions,
                timeout=5,
                symbols=None,  # Fetch all positions
                params=params
            )
            return positions
        except Exception as e:
            return []
    
    async def fetch_open_positions(self, symbol):
        try:
            # Special handling for BloFin copy trading accounts
            params = {'type': 'swap'}
            if self.credentials.copy_trading and self.exchange_name.lower() == 'blofin':
                params['accountType'] = 'copy_trading'
                
            positions = await execute_with_timeout(
                self.exchange.fetch_positions,
                timeout=5,
                symbols=[symbol],
                params=params
            )
            return positions
        except Exception as e:
            return []

    async def fetch_open_orders(self, symbol):
        try:
            orders = await execute_with_timeout(
                self.exchange.fetch_open_orders,
                timeout=5,
                symbol=symbol,
                params={'type': 'swap'}
            )
            return orders
        except Exception as e:
            return []

    async def fetch_and_map_positions(self, symbol: str):
        """Fetch open positions and convert them to UnifiedPosition objects."""
        try:
            positions = await self.fetch_open_positions(symbol)
            
            # Convert to UnifiedPosition objects
            unified_positions = [
                self.map_ccxt_position_to_unified(pos) 
                for pos in positions 
                if float(pos.get('contracts', 0)) != 0
            ]

            return unified_positions
        except Exception as e:
            return []

    def map_ccxt_position_to_unified(self, position: dict) -> UnifiedPosition:
        """Convert a CCXT position response into a UnifiedPosition object."""
        # CCXT standardized position format
        contracts = float(position.get('contracts', 0))
        side = position.get('side', 'long')
        
        # Adjust size for short positions
        size = contracts if side == 'long' else -contracts
        
        # Try to get more accurate data from raw exchange response if available
        info = position.get('info', {})
        
        # Get average entry price from CCXT's standardized fields
        # Some exchanges provide 'average' as entry price, others use different fields
        avg_entry_price = float(position.get('average', 0))
        if avg_entry_price == 0:
            # If no average, try other possible fields
            avg_entry_price = float(position.get('entryPrice', position.get('markPrice', 0)))
        
        # Get leverage from CCXT's standardized field
        leverage = float(position.get('leverage', 1))
            
        # Get unrealized PnL from CCXT's standardized field
        unrealized_pnl = float(position.get('unrealizedPnl', 0))
        
        # Get margin mode from CCXT's standardized response
        # Note: CCXT may not always correctly interpret margin modes for all exchanges.
        # Some exchanges' accounts may report incorrect margin modes through CCXT.
        # For accurate margin mode detection, use exchange-specific processors.
        margin_mode = position.get('marginMode') or 'isolated'  # Use 'or' instead of default param
        
        # Map margin mode using inverse mapping
        margin_mode = self.inverse_margin_mode_map.get(margin_mode, margin_mode)
            
        return UnifiedPosition(
            symbol=position['symbol'],
            size=size,
            average_entry_price=avg_entry_price,
            leverage=leverage,
            direction=side,
            unrealized_pnl=unrealized_pnl,
            margin_mode=margin_mode,
            exchange=self.exchange_name,
        )
        
    async def fetch_tickers(self, symbol):
        try:
            ticker = await execute_with_timeout(
                self.exchange.fetch_ticker,
                timeout=5,
                symbol=symbol
            )
            
            return UnifiedTicker(
                symbol=symbol,
                bid=float(ticker.get('bid', 0)),
                ask=float(ticker.get('ask', 0)),
                last=float(ticker.get('last', 0)),
                volume=float(ticker.get('baseVolume', 0)),  # CCXT uses baseVolume
                exchange=self.exchange_name
            )
        except Exception as e:
            return None

    async def get_symbol_details(self, symbol: str):
        """Fetch instrument details including tick size, lot size, and max size."""
        try:
            await self.exchange.load_markets()
            
            if symbol not in self.exchange.markets:
                raise ValueError(f"Symbol {symbol} not found.")
                
            market = self.exchange.markets[symbol]
            
            # CCXT standardized market info
            lot_size = float(market['precision']['amount']) if 'precision' in market else 1
            min_size = float(market['limits']['amount']['min']) if 'limits' in market else lot_size
            tick_size = float(market['precision']['price']) if 'precision' in market else 0.01
            contract_value = float(market.get('contractSize', 1))
            max_size = float(market['limits']['amount']['max']) if 'limits' in market and market['limits']['amount']['max'] else 1000000
            
            return lot_size, min_size, tick_size, contract_value, max_size
        except Exception as e:
            return None

    async def open_market_position(self, symbol: str, side: str, size: float, leverage: int, margin_mode: str, scale_lot_size: bool = True):
        """Open a position with a market order."""
        try:
            # Fetch symbol details
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(symbol)

            # Scale the size if needed
            lots = (scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value))[0] if scale_lot_size else size
            
            # Set leverage before placing order
            try:
                await execute_with_timeout(
                    self.exchange.set_leverage,
                    timeout=5,
                    leverage=leverage,
                    symbol=symbol,
                    params={'marginMode': margin_mode}
                )
            except Exception as e:
                pass
            
            # Check if order size exceeds maximum
            if lots > max_size:
                
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
                    
                    order = await execute_with_timeout(
                        self.exchange.create_market_order,
                        timeout=5,
                        symbol=symbol,
                        side=side.lower(),
                        amount=chunk_size,
                        params={
                            'type': 'swap',
                            'marginMode': margin_mode,
                            'leverage': leverage
                        }
                    )
                    orders.append(order)
                    total_executed += chunk_size
                    
                    # Small delay between orders
                    await asyncio.sleep(0.1)
                
                # Place remainder if exists
                if remainder > 0:
                    
                    order = await execute_with_timeout(
                        self.exchange.create_market_order,
                        timeout=5,
                        symbol=symbol,
                        side=side.lower(),
                        amount=remainder,
                        params={
                            'type': 'swap',
                            'marginMode': margin_mode,
                            'leverage': leverage
                        }
                    )
                    orders.append(order)
                    total_executed += remainder
                
                return orders
            
            else:
                # Order size is within limits
                order = await execute_with_timeout(
                    self.exchange.create_market_order,
                    timeout=5,
                    symbol=symbol,
                    side=side.lower(),
                    amount=lots,
                    params={
                        'type': 'swap',
                        'marginMode': margin_mode,
                        'leverage': leverage
                    }
                )
                return order

        except Exception as e:
            return None

    async def close_position(self, symbol: str):
        """Close the position for a specific symbol."""
        try:
            # Fetch current position
            positions = await self.fetch_open_positions(symbol)
            if not positions:
                return None

            position = positions[0]
            contracts = float(position.get('contracts', 0))
            if contracts == 0:
                return None

            # CCXT provides a close_position method for some exchanges
            # If not available, place a market order in the opposite direction
            side = position.get('side', 'long')
            close_side = 'sell' if side == 'long' else 'buy'
            
            # Try using close_position if available
            if hasattr(self.exchange, 'close_position'):
                order = await execute_with_timeout(
                    self.exchange.close_position,
                    timeout=5,
                    symbol=symbol,
                    params={'type': 'swap'}
                )
            else:
                # Place opposite market order
                order = await execute_with_timeout(
                    self.exchange.create_market_order,
                    timeout=5,
                    symbol=symbol,
                    side=close_side,
                    amount=abs(contracts),
                    params={
                        'type': 'swap',
                        'reduce_only': True
                    }
                )

            return order
            
        except Exception as e:
            return None
            
    async def reconcile_position(self, symbol: str, size: float, leverage: int, margin_mode: str):
        """
        Reconcile the current position with the target size, leverage, and margin mode.
        """
        try:
            # Use leverage override if set
            if self.leverage_override > 0:
                leverage = self.leverage_override
                
            unified_positions = await self.fetch_and_map_positions(symbol)
            current_position = unified_positions[0] if unified_positions else None
            
            # Fetch symbol details
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(symbol)

            # Scale target size
            size, _, lot_size = scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value)

            # Initialize position state variables
            current_size = current_position.size if current_position else 0
            current_margin_mode = current_position.margin_mode if current_position else None
            current_leverage = current_position.leverage if current_position else None

            # Handle position flips
            if (current_size > 0 and size < 0) or (current_size < 0 and size > 0):
                close_result = await self.close_position(symbol)
                
                # Only set current_size to 0 if close was successful
                if close_result is not None:
                    current_size = 0
                else:
                    # If close_position failed, we need to manually flip
                    
                    # Calculate total contracts needed to flip
                    # From current_size to target size needs abs(current_size) + abs(size) contracts
                    flip_amount = abs(current_size) + abs(size)
                    
                    # Determine side: if going from long to short or short to long
                    flip_side = "sell" if current_size > 0 else "buy"
                    
                    # Place the flip order
                    order = await self.open_market_position(
                        symbol=symbol,
                        side=flip_side.lower(),
                        size=flip_amount,
                        leverage=leverage,
                        margin_mode=margin_mode,
                        scale_lot_size=False
                    )
                    
                    if order:
                        return  # Position flip is complete
                    else:
                        return
            # Handle position size reduction
            elif current_size != 0 and abs(size) < abs(current_size):
                reduction_size = abs(current_size) - abs(size)
                
                # Determine side for reduction
                side = "sell" if current_size > 0 else "buy"
                
                # Place reduce-only order
                await execute_with_timeout(
                    self.exchange.create_market_order,
                    timeout=5,
                    symbol=symbol,
                    side=side,
                    amount=reduction_size,
                    params={
                        'type': 'swap',
                        'reduce_only': True
                    }
                )
                current_size = size
            
            # Check for margin mode or leverage changes
            if current_size != 0 and size != 0:
                # Some exchanges might require closing position to change margin mode
                if current_margin_mode != margin_mode:
                    try:
                        await execute_with_timeout(
                            self.exchange.set_margin_mode,
                            timeout=5,
                            marginMode=margin_mode,
                            symbol=symbol
                        )
                    except Exception as e:
                        await self.close_position(symbol)
                        current_size = 0

            # Adjust leverage if needed
            if current_leverage != leverage and abs(size) > 0:
                try:
                    await execute_with_timeout(
                        self.exchange.set_leverage,
                        timeout=5,
                        leverage=leverage,
                        symbol=symbol,
                        params={'marginMode': margin_mode}
                    )
                except Exception as e:
                    pass

            # Calculate remaining size difference
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
                    return

            # Determine the side of the new order
            side = "buy" if size_diff > 0 else "sell"
            size_diff = abs(size_diff)

            await self.open_market_position(
                symbol=symbol,
                side=side.lower(),
                size=size_diff,
                leverage=leverage,
                margin_mode=margin_mode,
                scale_lot_size=False
            )
        except Exception as e:
            return

    async def test_symbol_formats(self):
        """Test function to dump symbol information for mapping."""
        try:
            # Load markets first
            await self.exchange.load_markets()
            
            # Test common symbols
            test_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
            
            for symbol in test_symbols:
                try:
                    if symbol in self.exchange.markets:
                        market = self.exchange.markets[symbol]
                    
                    # Try to fetch a ticker to verify symbol works
                    ticker = await self.fetch_tickers(symbol)
                    
                except Exception as e:
                    pass
                    
            # Test symbol mapping
            test_signals = ["BTCUSDT", "ETHUSDT"]
            for symbol in test_signals:
                mapped = self.map_signal_symbol_to_exchange(symbol)
                
        except Exception as e:
            pass

    def map_signal_symbol_to_exchange(self, signal_symbol: str) -> str:
        """Convert signal symbol format (e.g. BTCUSDT) to exchange format."""
        # CCXT uses a standardized format for perpetual futures: BASE/QUOTE:SETTLE
        # For USDT perpetuals, it's typically BTC/USDT:USDT
        if "USDT" in signal_symbol:
            base = signal_symbol.replace("USDT", "")
            return f"{base}/USDT:USDT"
        return signal_symbol

    async def fetch_initial_account_value(self) -> float:
        """Calculate total account value from balance and initial margin of positions."""
        try:
            # Get available balance
            balance = await self.fetch_balance("USDT")
            available_balance = float(balance) if balance else 0.0
            
            # Get all positions and calculate total margin
            positions = await self.fetch_all_open_positions()
            position_margin = 0.0
            
            for pos in positions:
                # Use CCXT's standardized fields for margin calculation
                # CCXT provides initialMargin or we can calculate from notional/leverage
                initial_margin = pos.get('initialMargin')
                notional = pos.get('notional')
                leverage = pos.get('leverage')

                if initial_margin not in (None, ""):
                    position_margin += float(initial_margin)
                elif (
                    notional not in (None, "")
                    and leverage not in (None, "")
                    and float(leverage) > 0
                ):
                    # Initial margin = notional / leverage
                    position_margin += abs(float(notional)) / float(leverage)
                else:
                    # Some exchanges (including BloFin via CCXT) expose margin only in raw info.
                    info_margin = (pos.get('info') or {}).get('margin')
                    if info_margin not in (None, ""):
                        position_margin += float(info_margin)
            
            total_value = available_balance + position_margin
            return total_value
            
        except Exception as e:
            return 0.0

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close exchange connection."""
        await self.exchange.close()


async def main():
    """Example usage of the generic CCXT processor"""
    # Start a time
    start_time = datetime.datetime.now()
    
    try:
        # List all supported exchanges
        print("Supported CCXT exchanges:")
        exchanges = CCXTProcessor.list_supported_exchanges()
        print(f"Total: {len(exchanges)} exchanges")
        print(f"Examples: {', '.join(exchanges[:10])}...")
        
        # Create processor (will use exchange from credentials)
        async with CCXTProcessor() as processor:
            print(f"\nUsing exchange: {processor.exchange_name}")
            
            # Test balance fetching
            balance = await processor.fetch_balance(instrument="USDT")
            print(f"Balance: {balance}")
            
            # Test initial account value
            initial_value = await processor.fetch_initial_account_value()
            print(f"Initial Account Value: {initial_value} USDT")
            
            # Test symbol formats
            await processor.test_symbol_formats()
            
    except Exception as e:
        print(f"Error: {str(e)}")
    
    # End time
    end_time = datetime.datetime.now()
    print(f"\nTime taken: {end_time - start_time}")

if __name__ == "__main__":
    asyncio.run(main()) 
