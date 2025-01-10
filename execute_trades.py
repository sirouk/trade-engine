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

    def calculate_position_size(self, balance: float, price: float, signal: float, 
                              symbol: str) -> float:
        """Calculate the position size based on signal and configuration"""
        try:
            # Find symbol config
            symbol_config = next(
                (item for item in self.weight_config if item['symbol'] == symbol),
                None
            )
            
            if not symbol_config:
                logger.warning(f"No configuration found for symbol {symbol}")
                return 0.0
                
            # Get leverage directly from symbol config
            leverage = float(symbol_config['leverage'])
            
            # Calculate total weight from all sources for this symbol
            total_weight = sum(
                source['weight'] for source in symbol_config['sources']
            )
            
            # Calculate position size
            position_value = balance * total_weight * leverage
            position_size = (position_value / price) * signal
            
            return position_size
            
        except (TypeError, ValueError, KeyError) as e:
            logger.error(f"Error calculating position size for {symbol}: {str(e)}")
            return 0.0

    async def process_account(self, account, tv_signals, bt_signals):
        """Process a single account"""
        try:
            # Fetch balance and ensure it's a float
            balance = await account.fetch_balance()
            try:
                balance = float(balance) if balance is not None else 0
            except (ValueError, TypeError):
                logger.warning(f"{account.exchange_name}: Could not convert balance to float: {balance}")
                return False, "Invalid balance format"

            if balance <= 0:
                logger.warning(f"{account.exchange_name}: Invalid balance: {balance}")
                return False, "Invalid balance"
            
            logger.info(f"{account.exchange_name}: Successfully fetched balance: {balance}")
            
            success = True
            # Process each symbol
            for symbol in self.weight_lookup:
                try:
                    # Get exchange-specific symbol format
                    exchange_symbol = self.get_exchange_symbol(symbol, account.exchange_name)
                    if exchange_symbol is None:
                        logger.warning(f"{account.exchange_name}: Unsupported symbol {symbol}")
                        continue
                    
                    # Fetch ticker with retry
                    price = await self.get_ticker_price(account, exchange_symbol)
                    if not price:
                        logger.warning(f"{account.exchange_name}: Could not fetch valid ticker for {symbol}")
                        success = False
                        continue

                    logger.info(f"{account.exchange_name}: {symbol} current price: {price}")
                    
                    # Get signals - handle both dict and float formats
                    tv_signal = tv_signals.get(symbol)
                    bt_signal = bt_signals.get(symbol)
                    
                    weighted_signal = self.get_weighted_signal(symbol, tv_signal, bt_signal)
                    
                    if weighted_signal == 0:
                        logger.info(f"{account.exchange_name}: No valid signals for {symbol}, skipping")
                        continue
                    
                    target_size = self.calculate_position_size(
                        balance, price, weighted_signal, symbol
                    )
                    
                    # Round the target size according to exchange rules
                    target_size = self.round_size_to_exchange_rules(
                        account, exchange_symbol, target_size
                    )
                    
                    if target_size is None:
                        logger.warning(f"{account.exchange_name}: Invalid target size for {symbol}")
                        continue
                    
                    logger.info(
                        f"{account.exchange_name}: {symbol} - "
                        f"Signal: {weighted_signal:.4f}, Target Size: {target_size:.6f}"
                    )
                    
                    if abs(target_size) > 0:
                        try:
                            # Get leverage directly from symbol config
                            symbol_config = next(
                                (item for item in self.weight_config if item['symbol'] == symbol),
                                None
                            )
                            if not symbol_config:
                                raise ValueError(f"No configuration found for {symbol}")
                                
                            leverage = symbol_config['leverage']
                            
                            await account.reconcile_position(
                                symbol=exchange_symbol,
                                size=target_size,
                                leverage=leverage,
                                margin_mode="isolated"
                            )
                            logger.info(f"{account.exchange_name}: Position reconciled for {symbol}")
                        except Exception as e:
                            logger.error(f"{account.exchange_name}: Error reconciling position for {symbol}: {str(e)}")
                            success = False
                    
                except Exception as e:
                    logger.error(f"{account.exchange_name}: Error processing {symbol} - {str(e)}")
                    success = False
                
                time.sleep(1)
            
            return success, None
            
        except Exception as e:
            return False, str(e)

    def get_exchange_symbol(self, symbol: str, exchange: str) -> str | None:
        """
        Convert standard symbol to exchange-specific format.
        Returns None if the symbol is not supported for the given exchange.
        """
        try:
            # Validate input
            if not symbol or not exchange:
                logger.warning(f"Invalid input - symbol: {symbol}, exchange: {exchange}")
                return None

            # Standardize inputs
            symbol = symbol.upper()
            exchange = exchange.upper()

            # Define exchange-specific symbol mappings
            exchange_mappings = {
                'MEXC': {
                    'BTCUSDT': 'BTC_USDT',
                    'ETHUSDT': 'ETH_USDT',
                    # Add other supported pairs as needed
                },
                'KUCOIN': {
                    'BTCUSDT': 'BTC-USDT',
                    'ETHUSDT': 'ETH-USDT',
                    # Add other supported pairs as needed
                },
                'BLOFIN': {
                    'BTCUSDT': 'btcusdt',
                    'ETHUSDT': 'ethusdt',
                    # Add other supported pairs as needed
                },
                'BYBIT': {
                    'BTCUSDT': 'BTCUSDT',
                    'ETHUSDT': 'ETHUSDT',
                    # Add other supported pairs as needed
                }
            }

            # Check if exchange is supported
            if exchange not in exchange_mappings:
                logger.warning(f"Unsupported exchange: {exchange}")
                return None

            # Check if symbol is supported for this exchange
            if symbol not in exchange_mappings[exchange]:
                logger.warning(f"Unsupported symbol {symbol} for exchange {exchange}")
                return None

            converted_symbol = exchange_mappings[exchange][symbol]
            logger.debug(f"Converted {symbol} to {converted_symbol} for {exchange}")
            return converted_symbol

        except Exception as e:
            logger.error(f"Error converting symbol {symbol} for exchange {exchange}: {str(e)}")
            return None

    async def get_ticker_price(self, account, symbol: str) -> float:
        """Fetch ticker price with retries and proper error handling"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                tickers = await account.fetch_tickers(symbol=symbol)
                
                # Handle different ticker response formats
                if hasattr(tickers, 'last') and tickers.last:
                    return float(tickers.last)
                elif isinstance(tickers, dict):
                    # MEXC format
                    if account.exchange_name == 'MEXC' and 'lastPrice' in tickers:
                        return float(tickers['lastPrice'])
                    # ByBit format
                    elif 'lastPrice' in tickers:
                        return float(tickers['lastPrice'])
                    # KuCoin format
                    elif 'price' in tickers:
                        return float(tickers['price'])
                    # Other exchange formats
                    elif symbol in tickers and isinstance(tickers[symbol], dict):
                        for price_key in ['last', 'lastPrice', 'price']:
                            if price_key in tickers[symbol]:
                                return float(tickers[symbol][price_key])
                    
                logger.warning(f"{account.exchange_name}: Invalid ticker format for {symbol}: {tickers}")
                
            except Exception as e:
                logger.warning(f"Error fetching tickers from {account.exchange_name}: {str(e)}")
                if attempt == max_retries - 1:
                    break
                time.sleep(1)
        
        return None

    def round_size_to_exchange_rules(self, account, symbol: str, size: float) -> float:
        """Round size according to exchange-specific rules"""
        try:
            # Get exchange-specific lot size and minimum size
            if account.exchange_name == 'ByBit':
                if symbol == 'BTCUSDT':
                    lot_size = 0.001
                    min_size = 0.001
                    max_size = 100.0
                else:  # ETHUSDT
                    lot_size = 0.01
                    min_size = 0.01
                    max_size = 1000.0
            elif account.exchange_name == 'MEXC':
                if 'BTC_USDT' in symbol:
                    lot_size = 0.001
                    min_size = 0.001
                    max_size = 100.0
                else:  # ETH_USDT
                    lot_size = 0.01
                    min_size = 0.01
                    max_size = 1000.0
            elif account.exchange_name == 'KuCoin':
                if 'BTC-USDT' in symbol:
                    lot_size = 0.001
                    min_size = 0.001
                    max_size = 100.0
                else:  # ETH-USDT
                    lot_size = 0.01
                    min_size = 0.01
                    max_size = 1000.0
            else:
                # Default values for other exchanges
                lot_size = 0.001
                min_size = 0.001
                max_size = 100.0

            # Handle zero or None input
            if size is None or size == 0:
                return 0.0

            # Round to lot size precision
            size_in_lots = round(size / lot_size)
            rounded_size = size_in_lots * lot_size
            
            # Apply min/max constraints
            if abs(rounded_size) < min_size:
                # If close to min size, round up to min size
                if abs(size) >= min_size / 2:
                    return min_size if size > 0 else -min_size
                # If too small, return 0.0 instead of None
                return 0.0
            
            # Cap at max size
            if abs(rounded_size) > max_size:
                return max_size if rounded_size > 0 else -max_size
            
            return rounded_size
            
        except Exception as e:
            logger.error(f"Error rounding size for {account.exchange_name}: {str(e)}")
            # Return 0.0 instead of None on error
            return 0.0

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