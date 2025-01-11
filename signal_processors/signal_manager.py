import json
import os
from datetime import datetime
from typing import Dict, Set

from signal_processors.tradingview_processor import TradingViewProcessor
from signal_processors.bittensor_processor import BittensorProcessor

class SignalManager:
    CACHE_FILE = "signal_source_cache.json"
    CONFIG_FILE = "signal_weight_config.json"
    
    # Map source names to their processor classes
    PROCESSOR_MAP = {
        'tradingview': TradingViewProcessor,
        'bittensor': BittensorProcessor
    }
    
    def __init__(self):
        self.processors = {}
        self.cache = self._load_cache()
        self._initialize_processors()
    
    def _load_cache(self) -> Dict:
        """Load the cache of last processed times."""
        try:
            with open(self.CACHE_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def _save_cache(self):
        """Save the current cache to disk."""
        with open(self.CACHE_FILE, 'w') as f:
            json.dump(self.cache, f, indent=4)
    
    def _load_config(self) -> Set[str]:
        """Load config and return set of unique enabled sources."""
        try:
            with open(self.CONFIG_FILE, 'r') as f:
                config = json.load(f)
            
            # Get unique sources with non-zero weights
            enabled_sources = set()
            for symbol_config in config:
                for source in symbol_config['sources']:
                    if source['weight'] > 0:
                        enabled_sources.add(source['source'])
            
            return enabled_sources
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading config: {e}")
            return set()
    
    def _initialize_processors(self):
        """Initialize processor instances for enabled sources."""
        enabled_sources = self._load_config()
        
        for source in enabled_sources:
            if source in self.PROCESSOR_MAP:
                self.processors[source] = self.PROCESSOR_MAP[source](enabled=True)
    
    def check_for_updates(self) -> Dict[str, bool]:
        """Check each processor's RAW_SIGNALS_DIR for new files."""
        updates = {}
        
        for source, processor in self.processors.items():
            if not processor.enabled:
                continue
                
            if os.path.exists(processor.RAW_SIGNALS_DIR):
                try:
                    files = [f for f in os.listdir(processor.RAW_SIGNALS_DIR) 
                            if os.path.isfile(os.path.join(processor.RAW_SIGNALS_DIR, f))]
                    
                    if not files:
                        continue
                        
                    last_mod = max(
                        os.path.getmtime(os.path.join(processor.RAW_SIGNALS_DIR, f))
                        for f in files
                    )
                    
                    if last_mod > self.cache.get(source, 0):
                        updates[source] = True
                        self.cache[source] = last_mod
                        
                except Exception as e:
                    print(f"Error checking {source} directory: {e}")
                    continue
        
        self._save_cache()
        return updates 