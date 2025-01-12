import json
import logging
import os
from typing import Dict, List, Set
import importlib
import inspect

logger = logging.getLogger(__name__)

class SignalManager:
    CACHE_FILE = "account_asset_depths.json"
    CONFIG_FILE = "signal_weight_config.json"
    SIGNAL_PROCESSORS_DIR = "signal_processors"
    ACCOUNT_PROCESSORS_DIR = "account_processors"
    
    def __init__(self):
        self.signal_processors = {}  # {source_name: processor_instance}
        self.account_processors = {}  # {account_name: processor_instance}
        self.account_asset_depths = {}  # {account_name: {asset: depth}}
        self.config = self._load_config()
        self.previous_signals = {}  # Track previous raw signals
        self._temp_depths = {}  # Initialize temp depths
        self._load_cache()
        self._initialize_processors()
        self.processors = self.signal_processors  # For compatibility with existing code
    
    def _load_config(self) -> dict:
        """Load signal weight configuration."""
        try:
            with open(self.CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}
    
    def _load_cache(self):
        """Load cached account-asset depths."""
        try:
            with open(self.CACHE_FILE, 'r') as f:
                self.account_asset_depths = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.account_asset_depths = {}
    
    def _save_cache(self):
        """Save account-asset depths to cache."""
        with open(self.CACHE_FILE, 'w') as f:
            json.dump(self.account_asset_depths, f, indent=4)
    
    def _initialize_processors(self):
        """Initialize signal and account processors."""
        # Get unique signal sources from config
        signal_sources = {
            source['source'] 
            for symbol in self.config 
            for source in symbol['sources']
        }
        
        # Load signal processors
        for source in signal_sources:
            try:
                module = importlib.import_module(f"signal_processors.{source}_processor")
                for name, cls in inspect.getmembers(module, inspect.isclass):
                    if name.lower().startswith(source):
                        self.signal_processors[source] = cls()
                        break
            except Exception as e:
                logger.error(f"Error loading signal processor {source}: {e}")
        
        # Load account processors
        for filename in os.listdir(self.ACCOUNT_PROCESSORS_DIR):
            if filename.endswith('_processor.py'):
                try:
                    module_name = filename[:-3]  # Remove .py
                    module = importlib.import_module(f"account_processors.{module_name}")
                    for name, cls in inspect.getmembers(module, inspect.isclass):
                        if name in ['ByBit', 'KuCoin', 'BloFin', 'MEXC']:
                            processor = cls()
                            self.account_processors[processor.exchange_name] = processor
                except Exception as e:
                    logger.error(f"Error loading account processor from {filename}: {e}")
    
    def check_for_updates(self, accounts=None) -> Dict[str, bool]:
        """Check for updates and calculate new depths."""
        updates = {}
        new_depths = {}
        current_signals = {}
        has_updates = False
        
        # Reload config each time to catch changes
        self.config = self._load_config()
        
        logger.info("\n=== Signal Source Depths ===")
        # If no accounts provided, use all known account processors
        accounts_to_check = accounts if accounts is not None else self.account_processors.values()
        
        # Track all accounts that exist in either current accounts or cache
        all_account_names = set(acc.exchange_name for acc in accounts_to_check) | set(self.account_asset_depths.keys())
        
        # Initialize new_depths with all configured symbols for each account
        for account_name in all_account_names:
            # Get account object if it exists
            account = next((acc for acc in accounts_to_check if acc.exchange_name == account_name), None)
            is_enabled = account.enabled if account else False
            
            new_depths[account_name] = {
                symbol_config['symbol']: 0  # Initialize all symbols to zero
                for symbol_config in self.config
            }
            
            # If account exists in cache but is not in current accounts or is disabled,
            # check if we need to zero out any non-zero positions
            if account_name in self.account_asset_depths and not is_enabled:
                cached_depths = self.account_asset_depths[account_name]
                if any(abs(depth) > 1e-10 for depth in cached_depths.values()):
                    logger.info(f"Account {account_name} needs zeroing due to disabled state")
                    has_updates = True
        
        # Compare raw signals first
        for source, processor in self.signal_processors.items():
            if processor.enabled:
                signals = processor.fetch_signals()
                prev_signals = self.previous_signals.get(source, {})
                
                # Check if raw signals changed
                if signals != prev_signals:
                    has_updates = True
                    updates[source] = True
                
                current_signals[source] = signals
                self.previous_signals[source] = signals
            else:
                logger.info(f"Source {source} is disabled, using zero depths")
                current_signals[source] = {}
        
        logger.info("\n=== Weighted Asset Depths ===")
        # Calculate weighted depths for each asset
        asset_depths = {}  # {asset: weighted_depth}
        for symbol_config in self.config:
            symbol = symbol_config['symbol']
            total_weight = 0
            weighted_sum = 0
            
            logger.info(f"\n{symbol} weights:")
            for source_config in symbol_config['sources']:
                source = source_config['source']
                weight = source_config['weight']
                
                if weight > 0:
                    signals = current_signals.get(source, {})
                    depth = float(signals.get(symbol, {}).get('depth', 0)) \
                        if isinstance(signals.get(symbol), dict) else 0
                    # weight (e.g. 0.30) defines max account allocation for margin
                    # depth (e.g. 0.0235) defines what portion of that allocation to use
                    weighted_sum += depth * weight
                    total_weight += weight
                    logger.info(f"  {source}: depth={depth}, weight={weight}")
            
            if total_weight > 0:
                # Final depth represents margin allocation relative to account value
                asset_depths[symbol] = weighted_sum / total_weight
                logger.info(f"  Combined depth: {asset_depths[symbol]}")
        
        logger.info("\n=== Account Asset Depths ===")
        # Check each account for changes
        has_updates = False
        for account_name in all_account_names:
            account = next((acc for acc in accounts_to_check if acc.exchange_name == account_name), None)
            is_enabled = account.enabled if account else False
            current_depths = self.account_asset_depths.get(account_name, {})
            
            logger.info(f"\n{account_name} depths:")
            for asset, new_depth in asset_depths.items():
                current_depth = current_depths.get(asset, 0)
                target_depth = new_depth if is_enabled else 0
                
                logger.info(f"  {asset}: current={current_depth}, target={target_depth}")
                if abs(current_depth - target_depth) > 1e-10:
                    has_updates = True
                    new_depths[account_name][asset] = target_depth
                    # Mark all sources for this asset as needing updates
                    for source_config in next(
                        sc['sources'] for sc in self.config if sc['symbol'] == asset
                    ):
                        if source_config['weight'] > 0:
                            updates[source_config['source']] = True
        
        if has_updates:
            self._temp_depths = new_depths
            logger.info(f"Updates needed: {new_depths}")
        else:
            self._temp_depths = self.account_asset_depths  # Use current depths if no updates
            logger.info("No depth changes detected")
        
        return updates
    
    def confirm_execution(self, account_name: str, success: bool):
        """Confirm successful execution for an account and update its cache."""
        if success and hasattr(self, '_temp_depths'):
            if account_name in self._temp_depths:
                self.account_asset_depths[account_name] = self._temp_depths[account_name]
                self._save_cache()
                logger.info(f"Updated cache for {account_name}") 