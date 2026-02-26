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
    LEVERAGE_CACHE_FILE = "account_asset_leverages.json"
    CONFIG_FILE = "signal_weight_config.json"
    ASSET_MAPPING_CONFIG = "asset_mapping_config.json"
    SIGNAL_PROCESSORS_DIR = "signal_processors"
    ACCOUNT_PROCESSORS_DIR = "account_processors"

    @staticmethod
    def _canonical_account_name(account_name: str) -> str:
        """Normalize account names for case-insensitive matching."""
        return str(account_name).strip().lower()

    @staticmethod
    def _compose_account_key(exchange_name, account_name=None):
        """
        Build a stable account key that stays unique across duplicate exchange entries.

        - Default behavior keeps legacy keys (exchange_name) when account label matches
          the exchange label.
        - For explicit multi-account setups, include account label as a suffix.
        """
        exchange = str(exchange_name or "").strip()
        label = str(account_name or "").strip()
        if not exchange and not label:
            return ""
        if not label:
            label = exchange
        if not exchange:
            return label
        if SignalManager._canonical_account_name(label) == SignalManager._canonical_account_name(exchange):
            return exchange
        return f"{exchange}::{label}"

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

    @staticmethod
    def _merge_leverage_maps(base: Dict, incoming: Dict) -> Dict:
        """Merge per-symbol leverage maps, preferring valid incoming values."""
        merged = dict(base or {})
        if not isinstance(incoming, dict):
            return merged

        for symbol, value in incoming.items():
            try:
                leverage_val = float(value)
                if leverage_val > 0:
                    merged[symbol] = leverage_val
            except (TypeError, ValueError):
                continue
        return merged

    @staticmethod
    def _parse_positive_leverage(value, fallback: float | None = None) -> float | None:
        """Parse leverage as positive float, otherwise return fallback."""
        try:
            leverage = float(value)
        except (TypeError, ValueError):
            return fallback
        if leverage <= 0:
            return fallback
        return leverage

    @staticmethod
    def _resolve_account_name(account) -> str:
        """Resolve an account key from processor metadata."""
        if not account:
            return ""
        return str(getattr(account, "account_name", None) or getattr(account, "exchange_name", ""))

    @staticmethod
    def _scoped_keys_for_exchange(candidates: Dict, exchange_name: str):
        """Return scoped keys for the given exchange in candidate order."""
        exchange = SignalManager._canonical_account_name(exchange_name)
        if not exchange:
            return []

        scoped = []
        for candidate in candidates.keys():
            candidate_str = str(candidate)
            if "::" not in candidate_str:
                continue
            candidate_exchange = candidate_str.partition("::")[0]
            if SignalManager._canonical_account_name(candidate_exchange) == exchange:
                scoped.append(candidate)
        return scoped
    
    def __init__(self):
        self.signal_processors = {}  # {source_name: processor_instance}
        self.account_processors = {}  # {account_name: processor_instance}
        self.account_asset_depths = {}  # {account_name: {asset: depth}}
        self.account_asset_leverages = {}  # {account_name: {asset: leverage}}
        self.config = self._load_config()
        self.previous_signals = {}  # Track previous raw signals
        self._temp_depths = {}  # Initialize temp depths
        self._temp_leverages = {}  # Initialize temp leverage targets
        self._changed_symbols = {}  # Track which symbols changed per account: {account_name: [symbol, ...]}
        self._initialize_processors()
        self.processors = self.signal_processors  # For compatibility with existing code
        self._last_asset_mapping_check = 0  # Track last time we checked asset mapping config
        # Add lock for cache operations
        self._cache_lock = asyncio.Lock()
        self._pending_updates = {}  # Track pending cache updates by account
        self.account_asset_depths = self._load_cache()
        self.account_asset_leverages = self._load_leverage_cache()
    
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

    def _load_leverage_cache(self):
        """Load cached account-asset leverage targets."""
        try:
            with open(self.LEVERAGE_CACHE_FILE, 'r') as f:
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

    async def _save_leverage_cache(self):
        """Save account-asset leverage targets to cache."""
        try:
            with open(self.LEVERAGE_CACHE_FILE, 'w') as f:
                json.dump(self.account_asset_leverages, f, indent=4)
                os.fsync(f.fileno())
        except Exception as e:
            logger.error(f"Error saving leverage cache: {str(e)}")
    
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

        if not account_name:
            return None

        canonical = self._canonical_account_name(account_name)
        for key in candidates.keys():
            if self._canonical_account_name(key) == canonical:
                return key

        # Prefer explicit exchange-scoped keys (`exchange::label`) for duplicate accounts.
        if "::" in str(account_name):
            account_exchange = self._canonical_account_name(str(account_name).partition("::")[0])
            _, _, account_label = str(account_name).partition("::")
            account_label = self._canonical_account_name(account_label)
            scoped_keys = self._scoped_keys_for_exchange(candidates, account_exchange)

            # Exact scoped label match for this exchange.
            for key in scoped_keys:
                _, _, candidate_label = str(key).partition("::")
                if self._canonical_account_name(candidate_label) == account_label:
                    return key

            # If ambiguous scoped matching exists for this exchange, do not auto-map to a
            # different label. If there is only one scoped key, map to it.
            if len(scoped_keys) == 1:
                return scoped_keys[0]

            if len(scoped_keys) > 1:
                return None

            # Legacy compatibility:
            # if a running account key is "exchange::label" and cache currently
            # uses only "exchange", resolve to the exchange-only cache key.
            if len(scoped_keys) == 0:
                for key in candidates.keys():
                    if self._canonical_account_name(key) == account_exchange and "::" not in str(key):
                        return key

            # Older mixed formats keyed only by account label.
            if len(scoped_keys) == 0:
                for key in candidates.keys():
                    if self._canonical_account_name(key) == account_label and "::" not in str(key):
                        return key

            return None

        account_exchange = self._canonical_account_name(account_name)
        scoped_keys = self._scoped_keys_for_exchange(candidates, account_exchange)

        # A single scoped key can be treated as the exchange-level target when
        # resolving legacy exchange-only keys.
        if len(scoped_keys) == 1:
            return scoped_keys[0]

        # If multiple scoped keys exist, avoid aliasing to prevent collisions.
        if len(scoped_keys) > 1:
            for key in candidates.keys():
                if self._canonical_account_name(key) == account_exchange and "::" not in str(key):
                    return key
            return None

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
        new_leverages = {}
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
            exchange_name = getattr(account, "exchange_name", "")
            account_name = self._resolve_account_name(account)
            account_key = self._compose_account_key(exchange_name, account_name)
            canonical = self._canonical_account_name(account_key)
            existing = account_by_canonical.get(canonical)
            # Prefer enabled account if both canonical names appear.
            if existing is None or (not getattr(existing, "enabled", False) and getattr(account, "enabled", False)):
                account_by_canonical[canonical] = account

        # Build exchange->accounts index for legacy cache key recovery.
        exchange_to_canonical_accounts = {}
        for canonical in account_by_canonical.keys():
            exchange = canonical.split("::", 1)[0]
            exchange_to_canonical_accounts.setdefault(exchange, []).append(canonical)

        # Canonicalize/merge cache keys to avoid duplicates like "BloFin" vs "blofin".
        cache_by_canonical = {}
        leverage_cache_by_canonical = {}
        cache_aliases = {}
        for raw_name, raw_depths in (self.account_asset_depths or {}).items():
            raw_name_str = str(raw_name)
            canonical = self._canonical_account_name(raw_name_str)

            # If cache still uses legacy exchange-only keys (for example Hyperliquid),
            # map it to the active account key for that exchange to avoid phantom
            # updates when migrating to labeled duplicate accounts.
            if "::" not in raw_name_str:
                exchange = self._canonical_account_name(raw_name_str)
                exchange_accounts = exchange_to_canonical_accounts.get(exchange, [])
                if len(exchange_accounts) == 1:
                    canonical = exchange_accounts[0]
                elif len(exchange_accounts) > 1:
                    # Keep legacy keys untouched when an exchange now has multiple
                    # scoped accounts to avoid cross-account contamination.
                    cache_aliases.setdefault(canonical, set()).add(raw_name)
                    cache_by_canonical[canonical] = self._merge_depth_maps(
                        cache_by_canonical.get(canonical, {}),
                        raw_depths if isinstance(raw_depths, dict) else {},
                    )
                    leverage_cache_by_canonical[canonical] = self._merge_leverage_maps(
                        leverage_cache_by_canonical.get(canonical, {}),
                        (self.account_asset_leverages or {}).get(raw_name, {}),
                    )
                    continue

            cache_aliases.setdefault(canonical, set()).add(raw_name)
            cache_by_canonical[canonical] = self._merge_depth_maps(
                cache_by_canonical.get(canonical, {}),
                raw_depths if isinstance(raw_depths, dict) else {},
            )
            leverage_cache_by_canonical[canonical] = self._merge_leverage_maps(
                leverage_cache_by_canonical.get(canonical, {}),
                (self.account_asset_leverages or {}).get(raw_name, {}),
            )

        all_canonical_accounts = (
            set(account_by_canonical.keys())
            | set(cache_by_canonical.keys())
            | set(leverage_cache_by_canonical.keys())
        )

        # Map canonical names back to runtime/display keys.
        display_by_canonical = {}
        canonical_by_display = {}
        for canonical in all_canonical_accounts:
            account = account_by_canonical.get(canonical)
            if account is not None:
                exchange_name = getattr(account, "exchange_name", "")
                account_name = self._resolve_account_name(account)
                display = self._compose_account_key(exchange_name, account_name)
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
            new_leverages[account_name] = dict(leverage_cache_by_canonical.get(canonical, {}))

            # Only initialize missing symbols
            for symbol_config in self.config:
                symbol = symbol_config['symbol']
                if symbol not in new_depths[account_name]:
                    new_depths[account_name][symbol] = 0
                if symbol not in new_leverages[account_name]:
                    default_leverage = self._parse_positive_leverage(
                        symbol_config.get("leverage", 1),
                        fallback=1.0,
                    )
                    new_leverages[account_name][symbol] = float(default_leverage or 1.0)
        
        # Compare raw signals first
        for source, processor in self.signal_processors.items():
            if processor.enabled:
                signals = processor.fetch_signals()
                prev_signals = self.previous_signals.get(source, {})
                
                #logger.info(f"Current signals for {source}: {signals}")
                #logger.info(f"Previous signals for {source}: {prev_signals}")
                
                # Compare only symbols present in config and mark source updates.
                for symbol_config in self.config:
                    symbol = symbol_config['symbol']
                    if symbol not in signals:
                        continue

                    curr_signal = signals.get(symbol, {})
                    prev_signal = prev_signals.get(symbol, {})

                    curr_lev = self._parse_positive_leverage(
                        curr_signal.get("leverage"),
                        fallback=None,
                    )
                    prev_lev = self._parse_positive_leverage(
                        prev_signal.get("leverage"),
                        fallback=None,
                    )

                    # Consider source updated on depth, timestamp, or leverage change.
                    if (
                        curr_signal.get('depth', 0) != prev_signal.get('depth', 0)
                        or curr_signal.get('timestamp') != prev_signal.get('timestamp')
                        or curr_lev != prev_lev
                    ):
                        updates[source] = True

                current_signals[source] = signals
                self.previous_signals[source] = signals
            else:
                logger.info(f"Source {source} is disabled, using zero depths")
                current_signals[source] = {}
        
        #logger.info("\n=== Weighted Asset Depths ===")
        # Calculate weighted depths and leverage targets for each asset.
        asset_depths = {}  # {asset: weighted_depth}
        asset_leverages = {}  # {asset: weighted_target_leverage}
        for symbol_config in self.config:
            symbol = symbol_config['symbol']
            weighted_sum = 0
            weighted_abs_depth_for_leverage = 0.0
            weighted_leverage_sum = 0.0
            base_leverage = self._parse_positive_leverage(
                symbol_config.get("leverage", 1),
                fallback=1.0,
            )
            
            #logger.info(f"\n{symbol} weights:")
            for source_config in symbol_config['sources']:
                source = source_config['source']
                try:
                    weight = float(source_config['weight'])
                except (TypeError, ValueError):
                    continue
                
                if weight > 0:
                    signals = current_signals.get(source, {})
                    signal_data = signals.get(symbol, {}) if isinstance(signals, dict) else {}
                    depth = (
                        float(signal_data.get('depth', 0))
                        if isinstance(signal_data, dict)
                        else 0.0
                    )
                    # weight (e.g. 0.30) defines max account allocation of entire account value
                    # depth (e.g. 0.0235) defines what portion of that allocation to use
                    weighted_sum += depth * weight
                    abs_weighted_depth = abs(depth) * weight

                    src_lev = self._parse_positive_leverage(
                        signal_data.get("leverage") if isinstance(signal_data, dict) else None,
                        fallback=None,
                    )
                    if src_lev is not None and abs_weighted_depth > 0.0:
                        weighted_leverage_sum += src_lev * abs_weighted_depth
                        weighted_abs_depth_for_leverage += abs_weighted_depth
                    #logger.info(f"  {source}: depth={depth}, weight={weight}")

            # Final depth represents margin allocation relative to account value.
            asset_depths[symbol] = weighted_sum

            # If sources provide leverage (TradingView webhook), blend by absolute
            # weighted depth contribution. Otherwise fall back to config leverage.
            if weighted_abs_depth_for_leverage > 0.0:
                effective_leverage = weighted_leverage_sum / weighted_abs_depth_for_leverage
            else:
                effective_leverage = float(base_leverage or 1.0)
            asset_leverages[symbol] = max(1.0, float(effective_leverage))
            #logger.info(f"  Combined depth/leverage: {asset_depths[symbol]} @ {asset_leverages[symbol]}x")
        
        #logger.info("\n=== Account Asset Depths ===")
        # Check each account for changes and track which symbols changed
        #has_updates = False
        self._changed_symbols = {}  # Reset changed symbols tracker
        
        for account_name, canonical in canonical_by_display.items():
            account = account_by_canonical.get(canonical)
            is_enabled = account.enabled if account else False
            current_depths = cache_by_canonical.get(canonical, {})
            current_leverages = leverage_cache_by_canonical.get(canonical, {})
            self._changed_symbols[account_name] = []  # Initialize list for this account
            
            for asset, new_depth in asset_depths.items():
                symbol_config = next((sc for sc in self.config if sc['symbol'] == asset), None)
                default_cfg_leverage = self._parse_positive_leverage(
                    symbol_config.get("leverage", 1) if symbol_config else 1,
                    fallback=1.0,
                )

                current_depth = current_depths.get(asset, 0)
                target_depth = new_depth if is_enabled else 0
                current_leverage = self._parse_positive_leverage(
                    current_leverages.get(asset),
                    fallback=float(default_cfg_leverage or 1.0),
                )
                target_leverage = self._parse_positive_leverage(
                    asset_leverages.get(asset),
                    fallback=float(default_cfg_leverage or 1.0),
                )
                # Disabled lanes should close depth to zero, but avoid leverage-only churn.
                if not is_enabled:
                    target_leverage = current_leverage
                new_leverages[account_name][asset] = float(target_leverage or 1.0)
                
                # Round both depths for comparison
                current_depth = float(current_depth)
                target_depth = float(target_depth)
                
                # Add tolerance threshold to avoid unnecessary updates from floating point differences
                # Only update if change is significant (> 0.0001 or > 0.1% of larger value)
                depth_diff = abs(target_depth - current_depth)
                depth_tolerance = max(0.0001, max(abs(current_depth), abs(target_depth)) * 0.001)
                leverage_changed = abs(float(target_leverage) - float(current_leverage)) > 1e-9
                
                if depth_diff > depth_tolerance or leverage_changed:
                    if depth_diff > depth_tolerance:
                        logger.info(
                            f"Depth change detected for {account_name} on {asset}: "
                            f"current={current_depth}, target={target_depth}, diff={depth_diff:.6f}"
                        )
                    if leverage_changed:
                        logger.info(
                            f"Leverage change detected for {account_name} on {asset}: "
                            f"current={float(current_leverage):.4f}, target={float(target_leverage):.4f}"
                        )
                    has_updates = True
                    new_depths[account_name][asset] = target_depth
                    if asset not in self._changed_symbols[account_name]:
                        self._changed_symbols[account_name].append(asset)  # Track this symbol changed
                    # Mark all sources for this asset as needing updates
                    # Find symbol config for this asset - use default empty list if not found
                    if symbol_config:
                        for source_config in symbol_config.get('sources', []):
                            updates[source_config['source']] = True
                    else:
                        logger.warning(f"Symbol {asset} not found in config, cannot mark sources for update")
        
        if has_updates:
            self._temp_depths = new_depths
            self._temp_leverages = new_leverages
            logger.info(f"Updates needed: {new_depths}")
        else:
            # Keep canonicalized/normalized keys even when unchanged.
            self._temp_depths = new_depths
            self._temp_leverages = new_leverages
            #logger.info("No depth changes detected")
        
        return updates
    
    def get_changed_symbols(self, account_name: str) -> List[str]:
        """Get list of symbols that changed for a specific account."""
        resolved = self._resolve_account_key(account_name, self._changed_symbols)
        if resolved is None:
            return []
        return self._changed_symbols.get(resolved, [])

    def get_target_leverage(self, account_name: str, symbol: str, fallback: float = 1.0) -> int:
        """Return target leverage for account/symbol from latest weighted signals."""
        resolved = self._resolve_account_key(account_name, self._temp_leverages)
        if resolved is None:
            return max(1, int(round(float(fallback or 1.0))))
        account_map = self._temp_leverages.get(resolved, {})
        leverage = self._parse_positive_leverage(
            account_map.get(symbol),
            fallback=float(fallback or 1.0),
        )
        return max(1, int(round(float(leverage or 1.0))))
    
    async def confirm_execution(self, account_name: str, success: bool):
        """Confirm successful execution for an account and update its cache."""
        try:
            if success and hasattr(self, '_temp_depths'):
                resolved_name = self._resolve_account_key(account_name, self._temp_depths)
                if resolved_name is not None:
                    async with self._cache_lock:
                        current_cache = self._load_cache()
                        current_leverage_cache = self._load_leverage_cache()
                        canonical = self._canonical_account_name(resolved_name)

                        # Remove stale legacy exchange-only aliases after migration to
                        # exchange::label keys.
                        if "::" in resolved_name:
                            resolved_exchange = self._canonical_account_name(
                                str(resolved_name).partition("::")[0]
                            )
                            for key in list(current_cache.keys()):
                                key_name = self._canonical_account_name(key)
                                if "::" not in key_name and self._canonical_account_name(key_name) == resolved_exchange:
                                    current_cache.pop(key, None)
                                    current_leverage_cache.pop(key, None)

                        # Remove stale aliases for same account key (e.g., BloFin vs blofin).
                        for key in list(current_cache.keys()):
                            if self._canonical_account_name(key) == canonical:
                                current_cache.pop(key, None)
                                current_leverage_cache.pop(key, None)
                        current_cache[resolved_name] = self._temp_depths[resolved_name]
                        current_leverage_cache[resolved_name] = self._temp_leverages.get(
                            resolved_name,
                            {},
                        )
                        self.account_asset_depths = current_cache
                        self.account_asset_leverages = current_leverage_cache
                        await self._save_cache()
                        await self._save_leverage_cache()
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
            current_leverage_cache = self._load_leverage_cache()
            canonical = self._canonical_account_name(resolved_name)
            for key in list(current_cache.keys()):
                if self._canonical_account_name(key) == canonical:
                    current_cache.pop(key, None)
                    current_leverage_cache.pop(key, None)

            if "::" in resolved_name:
                resolved_exchange = self._canonical_account_name(str(resolved_name).partition("::")[0])
                for key in list(current_cache.keys()):
                    key_name = self._canonical_account_name(key)
                    if "::" not in key_name and key_name == resolved_exchange:
                        current_cache.pop(key, None)
                        current_leverage_cache.pop(key, None)

            current_cache[resolved_name] = self._temp_depths[resolved_name]
            current_leverage_cache[resolved_name] = self._temp_leverages.get(
                resolved_name,
                {},
            )
            self.account_asset_depths = current_cache
            self.account_asset_leverages = current_leverage_cache
            await self._save_cache()
            await self._save_leverage_cache()
            logger.info(f"Updated cache for {resolved_name}")
