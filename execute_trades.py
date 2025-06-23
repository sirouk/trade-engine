import ujson
import time
from typing import Dict, List, Tuple
import logging
from datetime import datetime
from collections import defaultdict
import asyncio
import os

from signal_processors.tradingview_processor import TradingViewProcessor
from signal_processors.bittensor_processor import BittensorProcessor

from account_processors.bybit_processor import ByBit
from account_processors.blofin_processor import BloFin
from account_processors.kucoin_processor import KuCoin
from account_processors.mexc_processor import MEXC

from core.signal_manager import SignalManager


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %I:%M:%S %p'
)
logger = logging.getLogger(__name__)

class TradeExecutor:
    sleep_time = 0.5
    ASSET_MAPPING_CONFIG = "asset_mapping_config.json"
    
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

        # Track last time we checked asset mapping config
        self._last_asset_mapping_check = 0

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

    def _should_reload_asset_mapping(self) -> bool:
        """Check if we should reload asset mapping configuration."""
        try:
            current_time = os.path.getmtime(self.ASSET_MAPPING_CONFIG)
            if current_time > self._last_asset_mapping_check:
                self._last_asset_mapping_check = current_time
                return True
        except OSError:
            # If file doesn't exist or can't be accessed, don't reload
            pass
        return False

    def _reload_asset_mappings(self):
        """Reload asset mappings in signal processors."""
        if hasattr(self.bittensor_processor, 'reload_asset_mapping'):
            self.bittensor_processor.reload_asset_mapping()
        if hasattr(self.tradingview_processor, 'reload_asset_mapping'):
            self.tradingview_processor.reload_asset_mapping()
        
    async def get_signals(self) -> Dict:
        """Fetch and combine signals from all sources."""
        try:
            # Check if asset mappings need to be reloaded
            if self._should_reload_asset_mapping():
                logger.info("Asset mapping configuration changed, reloading...")
                self._reload_asset_mappings()

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
            # Update weight config by calling the _load_weight_config
            self._load_weight_config()
            
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
                # Update cache after setting all positions to zero
                await self.signal_manager.confirm_execution(account.exchange_name, True)
                return True, None  # Return True since we successfully set positions to zero
                
            # Get total account value (including positions)
            total_value = await account.fetch_initial_account_value()
            if not total_value:
                logger.warning(f"No account value found for {account.exchange_name}")
                # Still update cache even with zero balance
                await self.signal_manager.confirm_execution(account.exchange_name, True)
                return False, None

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

                # Calculate position value in USDT (this will be our margin)
                position_value = total_value * depth  # depth is already weighted (0.0145)

                # Calculate raw quantity based on leverage
                leverage = symbol_config.get('leverage', 1)
                notional_value = position_value * leverage  # Total position value including leverage
                quantity = notional_value / price  # Convert to asset quantity

                # Preserve the sign from the depth value
                #if depth < 0:
                #    quantity = -quantity

                logger.info(f"Account Value: {total_value}, Depth: {depth}, "
                           f"Position Value: {position_value}, Leverage: {leverage}, "
                           f"Notional Value: {notional_value}, Quantity: {quantity}")

                # Get symbol details to log the precision/lot requirements
                symbol_details = await account.get_symbol_details(exchange_symbol)
                lot_size, min_size, tick_size, contract_value, max_size = symbol_details  # Unpack the tuple
                
                logger.info(f"{exchange_symbol}: depth={depth}, "
                          f"position_value={position_value}, raw_quantity={quantity}")
                logger.info(f"Symbol {exchange_symbol} -> "
                          f"Lot Size: {lot_size}, "
                          f"Min Size: {min_size}, "
                          f"Tick Size: {tick_size}, "
                          f"Contract Value: {contract_value}, "
                          f"Max Size: {max_size}")

                # Let reconcile_position handle the quantity precision
                await account.reconcile_position(
                    symbol=exchange_symbol,
                    size=quantity,
                    leverage=leverage,
                    margin_mode="isolated"
                )

            # Update cache after successful execution
            await self.signal_manager.confirm_execution(account.exchange_name, True)
            
            logger.info(f"Updated cache for {account.exchange_name}")
            return True, None

        except Exception as e:
            error_msg = f"Error processing {account.exchange_name}: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    async def execute(self):
        """Execute trades based on signal changes."""
        try:
            updates = self.signal_manager.check_for_updates(self.accounts)
            #logger.info(f"Checking for updates: {updates}")
            
            # If no updates needed, skip execution
            if not any(updates.values()):
                return True
                
            # Get signals that need to be executed
            signals = self.signal_manager._temp_depths
            
            # Process all accounts concurrently
            tasks: List[asyncio.Task] = []
            for account in self.accounts:
                task = asyncio.create_task(
                    self.process_account(account, signals)
                )
                tasks.append(task)
            
            # Wait for all account processing to complete
            results: List[Tuple[bool, str]] = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results and confirm executions
            all_successful = True
            for account, result in zip(self.accounts, results):
                if isinstance(result, Exception):
                    logger.error(f"Error processing {account.exchange_name}: {str(result)}")
                    all_successful = False
                    continue
                    
                success, error = result
                if success:
                    await self.signal_manager.confirm_execution(account.exchange_name, True)
                else:
                    logger.error(f"Error processing {account.exchange_name}: {error}")
                    all_successful = False
            
            return all_successful
            
        except Exception as e:
            logger.error(f"Error in execute: {str(e)}")
            return False



async def main():
    executor = TradeExecutor()
    logger.info(f"Starting execution cycle at {datetime.now()}")
    while True:
        try:
            
            # Execute trades
            await executor.execute()
            logger.info(f"Execution complete, waiting {executor.sleep_time} seconds for next cycle...")
            time.sleep(executor.sleep_time)
            
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")
            time.sleep(5)
        
        
if __name__ == "__main__":
    asyncio.run(main()) 