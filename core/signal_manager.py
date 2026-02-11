import ujson as json
import logging
import os
from typing import Dict, List
import importlib
import inspect
import asyncio

logger = logging.getLogger(__name__)

class SignalManager:
    CACHE_FILE = "account_asset_depths.json"
    CONFIG_FILE = "signal_weight_config.json"
    ASSET_MAPPING_CONFIG = "asset_mapping_config.json"
    SIGNAL_PROCESSORS_DIR = "signal_processors"
    ACCOUNT_PROCESSORS_DIR = "account_processors"

    @staticmethod
    def _canonical_account_name(account_name: str) -> str:
        """Normalize account names for case-insensitive matching."""
        return str(account_name).strip().lower()

    @staticmethod
    def _merge_depth_maps(base: Dict, incoming: Dict) -> Dict:
        """
        Merge per-symbol depth maps.
        If a symbol exists in both maps, keep the entry with larger absolute depth.
        """
        merged = dict(base or {})
        if not isinstance(incoming, dict):
            return merged

        for symbol, value in incoming.items():
            if symbol not in merged:
                merged[symbol] = value
                continue
            try:
                if abs(float(value)) > abs(float(merged[symbol])):
                    merged[symbol] = value
            except (TypeError, ValueError):
                merged[symbol] = value
        return merged
    
    def __init__(self):
        self.signal_processors = {}  # {source_name: processor_instance}
        self.account_processors = {}  # {account_name: processor_instance}
        self.account_asset_depths = {}  # {account_name: {asset: depth}}
        self.config = self._load_config()
        self.previous_signals = {}  # Track previous raw signals
        self._temp_depths = {}  # Initialize temp depths
        self._changed_symbols = {}  # Track which symbols changed per account: {account_name: [symbol, ...]}
        self._initialize_processors()
        self.processors = self.signal_processors  # For compatibility with existing code
        self._last_asset_mapping_check = 0  # Track last time we checked asset mapping config
        # Add lock for cache operations
        self._cache_lock = asyncio.Lock()
        self._pending_updates = {}  # Track pending cache updates by account
        self.account_asset_depths = self._load_cache()
    
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
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    async def _save_cache(self):
        """Save account-asset depths to cache."""
        try:
            with open(self.CACHE_FILE, 'w') as f:
                json.dump(self.account_asset_depths, f, indent=4)
                # Force sync to filesystem
                os.fsync(f.fileno())
        except Exception as e:
            logger.error(f"Error saving cache: {str(e)}")
    
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

    def _resolve_account_key(self, account_name: str, candidates: Dict | None = None) -> str | None:
        """
        Resolve account key with case-insensitive matching.
        Returns the exact key present in `candidates`, if found.
        """
        if candidates is None:
            candidates = self._temp_depths if hasattr(self, "_temp_depths") else {}

        if account_name in candidates:
            return account_name

        canonical = self._canonical_account_name(account_name)
        for key in candidates.keys():
            if self._canonical_account_name(key) == canonical:
                return key
        return None
    
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
        """Reload asset mappings in all signal processors."""
        for processor in self.signal_processors.values():
            if hasattr(processor, 'reload_asset_mapping'):
                processor.reload_asset_mapping()
    
    def check_for_updates(self, accounts=None) -> Dict[str, bool]:
        """Check for updates and calculate new depths."""
        # Check if asset mappings need to be reloaded
        if self._should_reload_asset_mapping():
            logger.info("Asset mapping configuration changed, reloading...")
            self._reload_asset_mappings()

        updates = {}
        new_depths = {}
        current_signals = {}
        has_updates = False
        
        # Reload config each time to catch changes
        self.config = self._load_config()
        
        #logger.info("\n=== Signal Source Depths ===")
        # If no accounts provided, use all known account processors
        accounts_to_check = list(accounts) if accounts is not None else list(self.account_processors.values())

        # Build canonical account registry from active processors.
        account_by_canonical = {}
        for account in accounts_to_check:
            canonical = self._canonical_account_name(account.exchange_name)
            existing = account_by_canonical.get(canonical)
            # Prefer enabled account if both canonical names appear.
            if existing is None or (not getattr(existing, "enabled", False) and getattr(account, "enabled", False)):
                account_by_canonical[canonical] = account

        # Canonicalize/merge cache keys to avoid duplicates like "BloFin" vs "blofin".
        cache_by_canonical = {}
        cache_aliases = {}
        for raw_name, raw_depths in (self.account_asset_depths or {}).items():
            canonical = self._canonical_account_name(raw_name)
            cache_aliases.setdefault(canonical, set()).add(raw_name)
            cache_by_canonical[canonical] = self._merge_depth_maps(
                cache_by_canonical.get(canonical, {}),
                raw_depths if isinstance(raw_depths, dict) else {},
            )

        all_canonical_accounts = set(account_by_canonical.keys()) | set(cache_by_canonical.keys())

        # Map canonical names back to runtime/display keys.
        display_by_canonical = {}
        canonical_by_display = {}
        for canonical in all_canonical_accounts:
            account = account_by_canonical.get(canonical)
            if account is not None:
                display = account.exchange_name
            else:
                # Keep an existing cache alias when no active processor exists.
                aliases = sorted(cache_aliases.get(canonical, {canonical}))
                display = aliases[0]
            display_by_canonical[canonical] = display
            canonical_by_display[display] = canonical

        # Track aliases for cache cleanup during confirmation.
        self._account_aliases = {}
        for canonical, display in display_by_canonical.items():
            aliases = set(cache_aliases.get(canonical, set()))
            aliases.add(display)
            self._account_aliases[display] = aliases

        # Initialize with current depths (canonicalized) instead of zeros.
        for account_name, canonical in canonical_by_display.items():
            account = account_by_canonical.get(canonical)
            is_enabled = account.enabled if account else False
            _ = is_enabled  # Explicitly retained for readability symmetry.

            new_depths[account_name] = dict(cache_by_canonical.get(canonical, {}))

            # Only initialize missing symbols
            for symbol_config in self.config:
                symbol = symbol_config['symbol']
                if symbol not in new_depths[account_name]:
                    new_depths[account_name][symbol] = 0
        
        # Compare raw signals first
        for source, processor in self.signal_processors.items():
            if processor.enabled:
                signals = processor.fetch_signals()
                prev_signals = self.previous_signals.get(source, {})
                
                #logger.info(f"Current signals for {source}: {signals}")
                #logger.info(f"Previous signals for {source}: {prev_signals}")
                
                # Make sure signal.leverage is set for all signals according to self.config
                source_has_updates = False
                for symbol_config in self.config:
                    symbol = symbol_config['symbol']
                    leverage = symbol_config['leverage']
                    
                    # Only process symbols we care about from config
                    if symbol in signals:
                        signals[symbol]['leverage'] = leverage
                        
                        # Compare only relevant fields for this symbol
                        curr_signal = signals.get(symbol, {})
                        prev_signal = prev_signals.get(symbol, {})
                        
                        # Only consider it an update if depth or timestamp changed
                        if (curr_signal.get('depth', 0) != prev_signal.get('depth', 0) or
                            curr_signal.get('timestamp') != prev_signal.get('timestamp')):
                            source_has_updates = True
                            updates[source] = True
                
                current_signals[source] = signals
                self.previous_signals[source] = signals
            else:
                logger.info(f"Source {source} is disabled, using zero depths")
                current_signals[source] = {}
        
        #logger.info("\n=== Weighted Asset Depths ===")
        # Calculate weighted depths for each asset
        asset_depths = {}  # {asset: weighted_depth}
        for symbol_config in self.config:
            symbol = symbol_config['symbol']
            total_weight = 0
            weighted_sum = 0
            
            #logger.info(f"\n{symbol} weights:")
            for source_config in symbol_config['sources']:
                source = source_config['source']
                weight = source_config['weight']
                
                if weight > 0:
                    signals = current_signals.get(source, {})
                    depth = float(signals.get(symbol, {}).get('depth', 0)) \
                        if isinstance(signals.get(symbol), dict) else 0
                    # weight (e.g. 0.30) defines max account allocation of entire account value
                    # depth (e.g. 0.0235) defines what portion of that allocation to use
                    weighted_sum += depth * weight
                    total_weight += weight
                    #logger.info(f"  {source}: depth={depth}, weight={weight}")
            
            if total_weight > 0:
                # Final depth represents margin allocation relative to account value
                #asset_depths[symbol] = weighted_sum / total_weight
                asset_depths[symbol] = weighted_sum
                #logger.info(f"  Combined depth: {asset_depths[symbol]}")
        
        #logger.info("\n=== Account Asset Depths ===")
        # Check each account for changes and track which symbols changed
        #has_updates = False
        self._changed_symbols = {}  # Reset changed symbols tracker
        
        for account_name, canonical in canonical_by_display.items():
            account = account_by_canonical.get(canonical)
            is_enabled = account.enabled if account else False
            current_depths = cache_by_canonical.get(canonical, {})
            self._changed_symbols[account_name] = []  # Initialize list for this account
            
            for asset, new_depth in asset_depths.items():
                current_depth = current_depths.get(asset, 0)
                target_depth = new_depth if is_enabled else 0
                
                # Round both depths for comparison
                current_depth = float(current_depth)
                target_depth = float(target_depth)
                
                # Add tolerance threshold to avoid unnecessary updates from floating point differences
                # Only update if change is significant (> 0.0001 or > 0.1% of larger value)
                depth_diff = abs(target_depth - current_depth)
                depth_tolerance = max(0.0001, max(abs(current_depth), abs(target_depth)) * 0.001)
                
                if depth_diff > depth_tolerance:
                    logger.info(f"Depth change detected for {account_name} on {asset}: current={current_depth}, target={target_depth}, diff={depth_diff:.6f}")
                    has_updates = True
                    new_depths[account_name][asset] = target_depth
                    self._changed_symbols[account_name].append(asset)  # Track this symbol changed
                    # Mark all sources for this asset as needing updates
                    # Find symbol config for this asset - use default empty list if not found
                    symbol_config = next(
                        (sc for sc in self.config if sc['symbol'] == asset),
                        None
                    )
                    if symbol_config:
                        for source_config in symbol_config.get('sources', []):
                            updates[source_config['source']] = True
                    else:
                        logger.warning(f"Symbol {asset} not found in config, cannot mark sources for update")
        
        if has_updates:
            self._temp_depths = new_depths
            logger.info(f"Updates needed: {new_depths}")
        else:
            # Keep canonicalized/normalized keys even when unchanged.
            self._temp_depths = new_depths
            #logger.info("No depth changes detected")
        
        return updates
    
    def get_changed_symbols(self, account_name: str) -> List[str]:
        """Get list of symbols that changed for a specific account."""
        resolved = self._resolve_account_key(account_name, self._changed_symbols)
        if resolved is None:
            return []
        return self._changed_symbols.get(resolved, [])
    
    async def confirm_execution(self, account_name: str, success: bool):
        """Confirm successful execution for an account and update its cache."""
        try:
            if success and hasattr(self, '_temp_depths'):
                resolved_name = self._resolve_account_key(account_name, self._temp_depths)
                if resolved_name is not None:
                    async with self._cache_lock:
                        current_cache = self._load_cache()
                        canonical = self._canonical_account_name(resolved_name)
                        # Remove stale aliases for same account key (e.g., BloFin vs blofin).
                        for key in list(current_cache.keys()):
                            if self._canonical_account_name(key) == canonical:
                                current_cache.pop(key, None)
                        current_cache[resolved_name] = self._temp_depths[resolved_name]
                        self.account_asset_depths = current_cache
                        await self._save_cache()
                        logger.info(f"Updated cache for {resolved_name}")
        except Exception as e:
            logger.error(f"Error updating cache for {account_name}: {str(e)}")

    async def _update_cache(self, account_name: str):
        """Handle the actual cache update with locking."""
        async with self._cache_lock:
            resolved_name = self._resolve_account_key(account_name, self._temp_depths)
            if resolved_name is None:
                return

            if resolved_name not in self.previous_signals:
                self.previous_signals[resolved_name] = {}

            current_cache = self._load_cache()
            canonical = self._canonical_account_name(resolved_name)
            for key in list(current_cache.keys()):
                if self._canonical_account_name(key) == canonical:
                    current_cache.pop(key, None)
            current_cache[resolved_name] = self._temp_depths[resolved_name]
            self.account_asset_depths = current_cache
            await self._save_cache()
            logger.info(f"Updated cache for {resolved_name}")
