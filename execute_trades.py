import json
import time
from typing import Dict, List
import logging
from datetime import datetime

from signal_processors.tradingview_processor import fetch_tradingview_signals, CORE_ASSET_MAPPING as TV_ASSET_MAPPING
from signal_processors.bittensor_processor import fetch_bittensor_signal, CORE_ASSET_MAPPING as BT_ASSET_MAPPING
from account_processors.bybit_processor import ByBit
from account_processors.blofin_processor import BloFin
from account_processors.kucoin_processor import KuCoin
from account_processors.mexc_processor import MEXC

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TradeExecutor:
    def __init__(self):
        # Initialize exchange accounts
        self.accounts = [
            ByBit(),
            BloFin(),
            KuCoin(),
            MEXC()
        ]
        
        # Load signal weight configuration
        try:
            with open('signal_weight_config.json', 'r') as f:
                self.weight_config = json.load(f)
        except FileNotFoundError:
            logger.error("signal_weight_config.json not found in root directory")
            raise
        except json.JSONDecodeError:
            logger.error("signal_weight_config.json contains invalid JSON")
            raise
        
        # Create lookup dictionary for easier access
        self.weight_lookup = {
            item['symbol']: {
                source['source']: {
                    'weight': source['weight'],
                    'leverage': item['leverage']
                }
                for source in item['sources']
            }
            for item in self.weight_config
        }

    async def get_signals(self):
        """Fetch signals from all sources."""
        tv_signals = fetch_tradingview_signals()
        bt_signals = await fetch_bittensor_signal(top_miners=5)
        return tv_signals, bt_signals

    def get_weighted_signal(self, symbol: str, tv_signal: float, bt_signal: float) -> float:
        """Combine signals using configured weights"""
        config = self.weight_lookup.get(symbol, {})
        
        total_signal = 0
        if 'tradingview' in config:
            total_signal += tv_signal * config['tradingview']['weight']
        if 'bittensor' in config:
            total_signal += bt_signal * config['bittensor']['weight']
            
        return total_signal

    def calculate_position_size(self, balance: float, price: float, signal: float, 
                              symbol: str) -> float:
        """Calculate the position size based on signal and configuration"""
        config = self.weight_lookup.get(symbol, {})
        
        # Get maximum leverage from either source (they should be the same)
        leverage = max(
            config.get('tradingview', {}).get('leverage', 1),
            config.get('bittensor', {}).get('leverage', 1)
        )
        
        # Calculate total weight for this symbol
        total_weight = sum(
            source.get('weight', 0) 
            for source in config.values()
        )
        
        # Calculate position size
        position_value = balance * total_weight * leverage
        position_size = (position_value / price) * signal
        
        return position_size

    async def execute(self):
        """Main execution loop"""
        try:
            # Get latest signals
            tv_signals, bt_signals = await self.get_signals()
            
            # Track successful and failed accounts
            failed_accounts = []
            successful_accounts = []
            
            # Process each account directly from self.accounts
            for account in self.accounts:
                try:
                    logger.info(f"\n{'='*50}\nProcessing {account.exchange_name} account\n{'='*50}")
                    
                    # Fetch balance with error handling
                    try:
                        balance = await account.fetch_balance()
                        if balance is None:
                            logger.warning(f"{account.exchange_name}: Unable to fetch balance")
                            failed_accounts.append((account.exchange_name, "Balance fetch returned None"))
                            continue
                        logger.info(f"{account.exchange_name}: Successfully fetched balance: {balance}")
                    except Exception as e:
                        logger.error(f"{account.exchange_name}: Balance fetch failed - {str(e)}")
                        failed_accounts.append((account.exchange_name, f"Balance fetch error: {str(e)}"))
                        continue
                    
                    # Track successful operations for this account
                    account_success = True
                    
                    for symbol in self.weight_lookup:
                        try:
                            # Get current price with error handling
                            tickers = await account.fetch_tickers(symbol=symbol)
                            if not tickers:
                                logger.warning(f"{account.exchange_name}: No ticker data for {symbol}")
                                account_success = False
                                continue
                            price = float(tickers.last)
                            logger.info(f"{account.exchange_name}: {symbol} current price: {price}")
                            
                            # Process signals and calculate position
                            weighted_signal = self.get_weighted_signal(
                                symbol,
                                tv_signals.get(symbol, 0),
                                bt_signals.get(symbol, 0)
                            )
                            
                            target_size = self.calculate_position_size(
                                balance, price, weighted_signal, symbol
                            )
                            
                            logger.info(
                                f"{account.exchange_name}: {symbol} - "
                                f"Signal: {weighted_signal:.2f}, Target Size: {target_size:.4f}"
                            )
                            
                            # Execute position reconciliation
                            await account.reconcile_position(
                                symbol=symbol,
                                size=target_size,
                                leverage=self.weight_lookup[symbol]['tradingview']['leverage'],
                                margin_mode="isolated"
                            )
                            logger.info(f"{account.exchange_name}: Successfully reconciled position for {symbol}")
                            
                        except Exception as e:
                            logger.error(f"{account.exchange_name}: Error processing {symbol} - {str(e)}")
                            account_success = False
                        
                        # Small delay between operations
                        time.sleep(1)
                    
                    if account_success:
                        successful_accounts.append(account.exchange_name)
                    
                except Exception as e:
                    logger.error(f"Failed to process {account.exchange_name}: {str(e)}")
                    failed_accounts.append((account.exchange_name, str(e)))
            
            # Summary logging
            logger.info("\n" + "="*50 + "\nExecution Summary\n" + "="*50)
            if successful_accounts:
                logger.info(f"Successfully processed accounts: {', '.join(successful_accounts)}")
            if failed_accounts:
                logger.warning("Failed accounts:")
                for account, error in failed_accounts:
                    logger.warning(f"  {account}: {error}")
                
        except Exception as e:
            logger.error(f"Critical error during execution: {str(e)}")
            raise

async def main():
    executor = TradeExecutor()
    while True:
        try:
            now = datetime.now()
            logger.info(f"Starting execution cycle at {now}")
            
            # Execute trades
            await executor.execute()
            
            # Wait for next cycle (5 minutes)
            logger.info("Execution complete, waiting for next cycle...")
            time.sleep(300)
            
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")
            time.sleep(60)  # Wait a minute before retrying on error

if __name__ == "__main__":
    import asyncio
    asyncio.run(main()) 