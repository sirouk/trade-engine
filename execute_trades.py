import json
import time
from typing import Dict
import logging
from datetime import datetime
from collections import defaultdict
import asyncio

from signal_processors.tradingview_processor import fetch_tradingview_signals
from signal_processors.bittensor_processor import fetch_bittensor_signal
from account_processors.bybit_processor import ByBit
from account_processors.blofin_processor import BloFin
from account_processors.kucoin_processor import KuCoin
from account_processors.mexc_processor import MEXC

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ExchangeLogger:
    def __init__(self, exchange_name: str, base_logger):
        self.exchange_name = exchange_name
        self.base_logger = base_logger
        
        # Create handler and formatter if none exist
        if not base_logger.handlers:
            handler = logging.StreamHandler()
            self.base_logger.addHandler(handler)
            
        # Store original formatter
        self.original_formatter = self.base_logger.handlers[0].formatter or logging.Formatter('%(message)s')
        
        # Create new formatter that includes exchange name
        self.exchange_formatter = logging.Formatter(
            f'%(asctime)s - %(levelname)s - [{exchange_name}] %(message)s'
        )
        
        # Store original print and logging functions
        self.original_print = print
        self.original_logger = None
        self.handlers = self.base_logger.handlers  # Add this to make ExchangeLogger look like a logger
        
    def __enter__(self):
        """Set up the logger context"""
        global print, logger
        self.original_logger = logger
        logger = self
        
        # Override print to include exchange name
        def exchange_print(*args, **kwargs):
            msg = " ".join(str(arg) for arg in args)
            # Don't prefix separator lines
            if msg.strip() and not all(c == '=' for c in msg.strip()):
                self.info(msg)
            else:
                self.original_print(msg)
        self.original_print_func = print
        print = exchange_print
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Restore original logging and print"""
        global print, logger
        logger = self.original_logger
        print = self.original_print_func

    def _log(self, level: str, msg: str):
        """Internal method to handle logging with formatter swap."""
        handler = self.base_logger.handlers[0]
        handler.setFormatter(self.exchange_formatter)
        # Don't prefix separator lines
        if msg.strip() and not all(c == '=' for c in msg.strip()):
            getattr(self.base_logger, level)(msg)
        else:
            handler.setFormatter(self.original_formatter)
            getattr(self.base_logger, level)(msg)
        handler.setFormatter(self.original_formatter)

    def info(self, msg: str):
        self._log('info', msg)

    def error(self, msg: str):
        self._log('error', msg)

    def warning(self, msg: str):
        self._log('warning', msg)

class TradeExecutor:
    def __init__(self):
        # Initialize exchange accounts
        self.accounts = [
            ByBit(),
            BloFin(),
            KuCoin(),
            MEXC()
        ]
        
        # Create a global logger for non-account-specific logs
        self.global_logger = ExchangeLogger("Global", logger)
        
        # Load signal weight configuration
        try:
            with open('signal_weight_config.json', 'r') as f:
                self.weight_config = json.load(f)
        except FileNotFoundError:
            logger.error("signal_weight_config.json not found")
            raise

    async def get_signals(self) -> Dict:
        """Fetch and combine signals from all sources."""
        with self.global_logger:  # Use global logger for signal processing
            try:
                tv_signals = fetch_tradingview_signals()
                bt_signals = await fetch_bittensor_signal(top_miners=5)
                
                logger.info(f"TradingView signals: {tv_signals}")
                logger.info(f"Bittensor signals: {bt_signals}")
                
                # Combine signals using weights from config
                combined_signals = {}
                
                for symbol_config in self.weight_config:
                    try:
                        symbol = symbol_config['symbol']
                        tv_weight = next((s['weight'] for s in symbol_config['sources'] 
                                    if s['source'] == 'tradingview'), 0)
                        bt_weight = next((s['weight'] for s in symbol_config['sources'] 
                                    if s['source'] == 'bittensor'), 0)
                        
                        # Extract depth from TradingView signal structure
                        tv_depth = float(tv_signals.get(symbol, {}).get('depth', 0)) if isinstance(tv_signals.get(symbol), dict) else 0
                        bt_depth = 0  # Temporarily set to 0 while bittensor is not working
                        
                        total_weight = tv_weight + bt_weight
                        if total_weight > 0:
                            weighted_depth = ((tv_depth * tv_weight) + (bt_depth * bt_weight)) / total_weight
                            combined_signals[symbol] = weighted_depth
                            logger.info(f"Processed {symbol}: TV depth={tv_depth}, TV weight={tv_weight}, "
                                      f"Combined depth={weighted_depth}")
                            
                    except Exception as e:
                        logger.error(f"Error processing signal for {symbol}: {str(e)}")
                        continue
                
                logger.info(f"Combined signals: {combined_signals}")
                return combined_signals
                
            except Exception as e:
                logger.error(f"Error fetching signals: {str(e)}")
                return {}

    async def process_account(self, account, signals: Dict):
        """Process signals for a specific account."""
        try:
            # Skip disabled accounts
            if not account.enabled:
                logger.info(f"Skipping disabled account: {account.exchange_name}")
                return True, None  # Return success but do nothing
                
            # Get total account value (including positions)
            total_value = await account.fetch_total_account_value()
            if not total_value:
                logger.warning(f"No account value found for {account.exchange_name}")
                return False, "No account value found"

            logger.info(f"Processing {account.exchange_name} with total value: {total_value}")

            for symbol_config in self.weight_config:
                signal_symbol = symbol_config['symbol']
                depth = signals.get(signal_symbol, 0)
                
                # NO: All depth signals are processed
                #if abs(depth) < 0.01:  # Ignore very small signals
                #    continue

                # Map to exchange symbol format
                exchange_symbol = account.map_signal_symbol_to_exchange(signal_symbol)
                
                # Get current market price
                ticker = await account.fetch_tickers(exchange_symbol)
                if not ticker:
                    logger.error(f"Could not get price for {exchange_symbol}")
                    continue
                
                price = ticker.last  # Use last price from ticker

                # Calculate position value in USDT
                position_value = total_value * depth
                
                # Calculate raw quantity
                quantity = abs(position_value) / price
                if depth < 0:
                    quantity = -quantity

                # Get symbol details to log the precision/lot requirements
                symbol_details = await account.get_symbol_details(exchange_symbol)
                lot_size, min_size, tick_size, contract_value = symbol_details  # Unpack the tuple
                
                logger.info(f"{exchange_symbol}: depth={depth}, "
                          f"position_value={position_value}, raw_quantity={quantity}")
                logger.info(f"Symbol {exchange_symbol} -> "
                          f"Lot Size: {lot_size}, "
                          f"Min Size: {min_size}, "
                          f"Tick Size: {tick_size}, "
                          f"Contract Value: {contract_value}")

                # Let reconcile_position handle the quantity precision
                await account.reconcile_position(
                    symbol=exchange_symbol,
                    size=quantity,  # Pass raw quantity, let exchange-specific logic handle precision
                    leverage=symbol_config.get('leverage', 1),
                    margin_mode="isolated"
                )

            return True, None

        except Exception as e:
            error_msg = f"Error processing {account.exchange_name}: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    async def process_account_with_prefix(self, account, signals: Dict):
        """Wrapper that adds exchange prefix to all logging output."""
        exchange_logger = ExchangeLogger(account.exchange_name, logger)
        
        with exchange_logger:
            return await self.process_account(account, signals)

    async def execute(self):
        """Execute trades based on signals."""
        with self.global_logger:  # Use global logger for main execution flow
            try:
                signals = await self.get_signals()
                
                # Create tasks with prefixed logging
                tasks = []
                for account in self.accounts:
                    print(f"\n{'='*50}")
                    task = asyncio.create_task(
                        self.process_account_with_prefix(account, signals)
                    )
                    tasks.append(task)
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Process results
                for account, result in zip(self.accounts, results):
                    if isinstance(result, Exception):
                        logger.error(f"{account.exchange_name}: Failed with exception: {str(result)}")
                    else:
                        success, error = result
                        if not success:
                            logger.error(f"{account.exchange_name}: Failed: {error}")
                    
                logger.info("\nExecution Summary")
                return True
                
            except Exception as e:
                logger.error(f"Error in execution: {str(e)}")
                return False

async def calculate_trade_amounts(accounts, signals):
    """Calculate trade amounts based on account values and signal weights."""
    try:
        # Get total account values using new methods
        account_values = {}
        for account in accounts:
            total_value = await account.fetch_total_account_value()
            account_values[account.exchange_name] = total_value
            
        print("\nAccount Values:")
        for exchange, value in account_values.items():
            print(f"{exchange}: {value:.2f} USDT")
            
        # Calculate aggregate depths and leverages by asset
        asset_depths = defaultdict(float)
        asset_leverages = defaultdict(list)
        
        for signal in signals:
            symbol = signal.symbol
            base_asset = symbol.replace("USDT", "")
            depth = signal.weight * 100  # Convert weight to percentage
            leverage = signal.leverage
            
            asset_depths[base_asset] += depth
            if leverage not in asset_leverages[base_asset]:
                asset_leverages[base_asset].append(leverage)
                
        # Print summary of depths and leverages
        print("\nExpected Position Summary:")
        for asset, depth in asset_depths.items():
            print(f"\n{asset}:")
            print(f"  Total Depth: {depth:.1f}%")
            print(f"  Leverage(s): {asset_leverages[asset]}")

        # Calculate trade amounts for each account and signal
        trade_amounts = {}
        for account in accounts:
            exchange_value = account_values[account.exchange_name]
            signal_amounts = {}
            
            for signal in signals:
                # Calculate amount based on account value and signal weight
                amount = exchange_value * signal.weight
                signal_amounts[signal.symbol] = amount
                
            trade_amounts[account.exchange_name] = signal_amounts
            
        return trade_amounts
        
    except Exception as e:
        print(f"Error calculating trade amounts: {str(e)}")
        return None

async def execute_trades(accounts, signals):
    """Execute trades across all accounts based on signals."""
    try:
        # Calculate trade amounts
        trade_amounts = await calculate_trade_amounts(accounts, signals)
        if not trade_amounts:
            return False
            
        print("\nTrade Execution Plan:")
        for exchange, amounts in trade_amounts.items():
            print(f"\n{exchange}:")
            for symbol, amount in amounts.items():
                print(f"  {symbol}: {amount:.2f} USDT")
        
        # Execute trades for each account
        for account in accounts:
            exchange_amounts = trade_amounts[account.exchange_name]
            
            for signal in signals:
                amount = exchange_amounts[signal.symbol]
                
                # Skip if amount is too small
                # TODO: there are exchange specific minimum trade sizes
                #if amount < 5:  # Minimum trade size
                #    print(f"Skipping {signal.symbol} on {account.exchange_name} - amount too small: {amount:.2f} USDT")
                #    continue
                    
                try:
                    # Reconcile position with calculated amount
                    await account.reconcile_position(
                        symbol=signal.symbol,
                        size=signal.size,
                        leverage=signal.leverage,
                        margin_mode=signal.margin_mode
                    )
                except Exception as e:
                    print(f"Error executing trade on {account.exchange_name} for {signal.symbol}: {str(e)}")
                    continue
                    
        return True
        
    except Exception as e:
        print(f"Error executing trades: {str(e)}")
        return False

async def main():
    executor = TradeExecutor()
    while True:
        with executor.global_logger:  # Use global logger for main loop
            try:
                now = datetime.now()
                logger.info(f"Starting execution cycle at {now}")
                
                # Execute trades
                await executor.execute()
                
                # Wait for next cycle
                logger.info("Execution complete, waiting for next cycle...")
                
            except Exception as e:
                logger.error(f"Error in main loop: {str(e)}")
                time.sleep(60)  # Wait a minute before retrying on error

if __name__ == "__main__":
    asyncio.run(main()) 