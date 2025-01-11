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
        try:
            tv_signals = fetch_tradingview_signals()
            # Convert TV signals to dictionary if it's not already
            tv_signals_dict = {}
            if isinstance(tv_signals, list):
                for signal in tv_signals:
                    if isinstance(signal, dict):
                        depth = signal.get('depth', 0.0)
                        # Handle depth being a dictionary or direct value
                        if isinstance(depth, dict):
                            depth = depth.get('value', 0.0)
                        elif isinstance(depth, (int, float)):
                            depth = float(depth)
                        tv_signals_dict[signal['symbol']] = depth
            elif isinstance(tv_signals, dict):
                # If signals are already a dict, extract depth values
                for symbol, signal in tv_signals.items():
                    if isinstance(signal, dict):
                        depth = signal.get('depth', 0.0)
                        if isinstance(depth, (int, float)):
                            tv_signals_dict[symbol] = float(depth)
                        elif isinstance(depth, dict):
                            tv_signals_dict[symbol] = float(depth.get('value', 0.0))
                    elif isinstance(signal, (int, float)):
                        tv_signals_dict[symbol] = float(signal)
            
            bt_signals = await fetch_bittensor_signal(top_miners=5)
            # Convert BT signals to dictionary if it's not already
            bt_signals_dict = {}
            if isinstance(bt_signals, list):
                for signal in bt_signals:
                    if isinstance(signal, dict):
                        depth = signal.get('depth', 0.0)
                        if isinstance(depth, (int, float)):
                            bt_signals_dict[signal['symbol']] = float(depth)
                        elif isinstance(depth, dict):
                            bt_signals_dict[signal['symbol']] = float(depth.get('value', 0.0))
            elif isinstance(bt_signals, dict):
                for symbol, signal in bt_signals.items():
                    if isinstance(signal, dict):
                        depth = signal.get('depth', 0.0)
                        if isinstance(depth, (int, float)):
                            bt_signals_dict[symbol] = float(depth)
                        elif isinstance(depth, dict):
                            bt_signals_dict[symbol] = float(depth.get('value', 0.0))
                    elif isinstance(signal, (int, float)):
                        bt_signals_dict[symbol] = float(signal)
            
            # Fixed logging statements to show correct signal sources
            logger.info("Raw signals:")
            logger.info(f"  TradingView: {tv_signals}")
            logger.info(f"  Bittensor: {bt_signals}")
            logger.info("Processed signals:")
            logger.info(f"  TradingView: {tv_signals_dict}")
            logger.info(f"  Bittensor: {bt_signals_dict}")
            
            return tv_signals_dict, bt_signals_dict
            
        except Exception as e:
            logger.error(f"Error fetching signals: {str(e)}")
            return {}, {}

    def get_weighted_signal(self, symbol: str, tv_signal: float, bt_signal: float) -> float:
        """Combine signals using configured weights"""
        config = self.weight_lookup.get(symbol, {})
        
        total_signal = 0
        total_weight = 0
        
        try:
            # Process TradingView signal
            if 'tradingview' in config:
                # Handle signal being either float or dict
                tv_value = (float(tv_signal['depth']) if isinstance(tv_signal, dict) 
                          else float(tv_signal) if tv_signal is not None 
                          else 0.0)
                weight = float(config['tradingview']['weight'])
                total_signal += tv_value * weight
                total_weight += weight
            
            # Process Bittensor signal
            if 'bittensor' in config:
                # Handle signal being either float or dict
                bt_value = (float(bt_signal['depth']) if isinstance(bt_signal, dict)
                          else float(bt_signal) if bt_signal is not None
                          else 0.0)
                weight = float(config['bittensor']['weight'])
                total_signal += bt_value * weight
                total_weight += weight
            
        except (TypeError, ValueError, KeyError) as e:
            logger.error(f"Error processing signals for {symbol}: {str(e)}")
            return 0.0
            
        # Normalize if we have any valid signals
        return total_signal / total_weight if total_weight > 0 else 0.0

    def calculate_position_size(self, signal: float, balance: float, leverage: int) -> float:
        """Calculate position size based on signal strength and account balance."""
        # Signal is between -1 and 1, representing percentage of account to use
        account_portion = abs(signal)
        position_size = balance * account_portion * leverage
        
        # Preserve the direction from the signal
        if signal < 0:
            position_size = -position_size
            
        return position_size

    async def process_account(self, account, tv_signals: Dict, bt_signals: Dict):
        """Process signals for a specific account."""
        try:
            # Get account balance
            balance = await account.fetch_balance()
            if not balance:
                logger.warning(f"No balance found for {account.exchange_name}")
                return False, "No balance found"

            logger.info(f"Processing {account.exchange_name} with balance: {balance}")

            # Process each symbol in the weight config
            for symbol_config in self.weight_config:
                signal_symbol = symbol_config['symbol']  # e.g., "BTCUSDT"
                
                # Map the signal symbol to exchange-specific format
                exchange_symbol = account.map_signal_symbol_to_exchange(signal_symbol)
                logger.info(f"Processing {signal_symbol} (Exchange format: {exchange_symbol})")

                # Get signals for this symbol
                tv_signal = tv_signals.get(signal_symbol, 0)
                bt_signal = bt_signals.get(signal_symbol, 0)

                # Calculate weighted signal
                weighted_signal = self.get_weighted_signal(signal_symbol, tv_signal, bt_signal)
                logger.info(f"Weighted signal for {signal_symbol}: {weighted_signal}")

                if weighted_signal == 0:
                    logger.info(f"No significant signal for {signal_symbol}, skipping")
                    continue

                # Calculate position size based on balance and leverage
                leverage = symbol_config.get('leverage', 1)
                size = self.calculate_position_size(weighted_signal, balance, leverage)
                logger.info(f"Calculated size: {size}")

                # Reconcile position
                await account.reconcile_position(
                    symbol=exchange_symbol,
                    size=size,
                    leverage=leverage,
                    margin_mode="isolated"  # Default to isolated margin
                )

            return True, None

        except Exception as e:
            error_msg = f"Error processing {account.exchange_name}: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    async def execute(self):
        """Main execution loop"""
        try:
            # Get latest signals
            tv_signals, bt_signals = await self.get_signals()
            
            results = []
            for account in self.accounts:
                logger.info(f"\n{'='*50}\nProcessing {account.exchange_name} account\n{'='*50}")
                success, error = await self.process_account(account, tv_signals, bt_signals)
                results.append((account.exchange_name, success, error))
            
            # Log summary
            logger.info("\n" + "="*50 + "\nExecution Summary\n" + "="*50)
            
            successful = [name for name, success, _ in results if success]
            failed = [(name, error) for name, success, error in results if not success]
            
            if successful:
                logger.info(f"Successfully processed accounts: {', '.join(successful)}")
            if failed:
                logger.warning("Failed accounts:")
                for name, error in failed:
                    logger.warning(f"  {name}: {error}")
                    
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