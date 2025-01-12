import json
import time
from typing import Dict
import logging
from datetime import datetime
from collections import defaultdict
import asyncio

from signal_processors.tradingview_processor import TradingViewProcessor
from signal_processors.bittensor_processor import BittensorProcessor
from account_processors.bybit_processor import ByBit
from account_processors.blofin_processor import BloFin
from account_processors.kucoin_processor import KuCoin
from account_processors.mexc_processor import MEXC
from core.signal_manager import SignalManager

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
    def _load_weight_config(self) -> bool:
        """Load signal weight configuration from file. Returns True if successful."""
        try:
            with open('signal_weight_config.json', 'r') as f:
                self.weight_config = json.load(f)
            return True
        except FileNotFoundError:
            logger.error("signal_weight_config.json not found")
            return False
        except json.JSONDecodeError:
            logger.error("signal_weight_config.json is malformed")
            return False

    def __init__(self):
        # Initial load of weight config
        if not self._load_weight_config():
            raise RuntimeError("Failed to load initial weight configuration")

        # Initialize signal manager
        self.signal_manager = SignalManager()

        # Initialize processors with enabled state based on non-zero weights
        self.bittensor_processor = BittensorProcessor(
            enabled=any(any(s['weight'] > 0 for s in symbol['sources'] 
                          if s['source'] == 'bittensor') 
                       for symbol in self.weight_config)
        )
        self.tradingview_processor = TradingViewProcessor(
            enabled=any(any(s['weight'] > 0 for s in symbol['sources'] 
                          if s['source'] == 'tradingview') 
                       for symbol in self.weight_config)
        )
        
        # Initialize exchange accounts
        self.accounts = [
            ByBit(),
            BloFin(),
            KuCoin(),
            MEXC()
        ]
        
        # Create a global logger for non-account-specific logs
        self.global_logger = ExchangeLogger("Global", logger)
        
    async def get_signals(self) -> Dict:
        """Fetch and combine signals from all sources."""
        with self.global_logger:
            try:
                # Check for updates in signal sources
                updates = self.signal_manager.check_for_updates(self.accounts)
                logger.info(f"Checking for updates: {updates}")
                
                # Get the new depths that need to be applied
                if hasattr(self.signal_manager, '_temp_depths'):
                    return self.signal_manager._temp_depths
                    
                logger.info("No depth changes detected")
                return {}
                
            except Exception as e:
                logger.error(f"Error fetching signals: {str(e)}")
                return {}

    async def process_account(self, account, signals: Dict):
        """Process signals for a specific account."""
        try:
            # Skip disabled accounts but still process with zero depths
            if not account.enabled:
                logger.info(f"Skipping disabled account: {account.exchange_name}")
                # Process all symbols with zero depth
                for symbol_config in self.weight_config:
                    signal_symbol = symbol_config['symbol']
                    exchange_symbol = account.map_signal_symbol_to_exchange(signal_symbol)
                    await account.reconcile_position(
                        symbol=exchange_symbol,
                        size=0,
                        leverage=symbol_config.get('leverage', 1),
                        margin_mode="isolated"
                    )
                return True, None
                
            # Get total account value (including positions)
            total_value = await account.fetch_total_account_value()
            if not total_value:
                logger.warning(f"No account value found for {account.exchange_name}")
                return False, "No account value found"

            logger.info(f"Processing {account.exchange_name} with total value: {total_value}")

            for symbol_config in self.weight_config:
                signal_symbol = symbol_config['symbol']
                depth = signals.get(account.exchange_name, {}).get(signal_symbol, 0)  # Get account-specific depth
                
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
        """Execute trades based on signal changes."""
        try:
            # Check for updates
            updates = self.signal_manager.check_for_updates(self.accounts)
            logger.info(f"Checking for updates: {updates}")
            
            # If no updates needed, skip execution
            if not any(updates.values()):
                logger.info("No signal changes detected, skipping execution")
                return True
                
            # Get signals that need to be executed
            signals = self.signal_manager._temp_depths
            
            # Process each account
            for account in self.accounts:
                success, error = await self.process_account_with_prefix(account, signals)
                if success:
                    self.signal_manager.confirm_execution(account.exchange_name, True)
                else:
                    logger.error(f"Error processing {account.exchange_name}: {error}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error in execute: {str(e)}")
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
        with executor.global_logger:
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
            
            time.sleep(1)

if __name__ == "__main__":
    asyncio.run(main()) 