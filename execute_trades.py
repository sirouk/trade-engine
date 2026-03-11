import ujson as json
import time
from typing import Dict, List, Tuple
import logging
from datetime import datetime
import asyncio
import os

from signal_processors.tradingview_processor import TradingViewProcessor
from signal_processors.bittensor_processor import BittensorProcessor

from account_processors.bybit_processor import ByBit
from account_processors.blofin_processor import BloFin
from account_processors.kucoin_processor import KuCoin
from account_processors.mexc_processor import MEXC
from account_processors.ccxt_processor import CCXTProcessor
from account_processors.hyperliquid_processor import HyperliquidProcessor

from core.signal_manager import SignalManager
from config.credentials import load_ccxt_credentials
from core.utils.disabled_account_guard import DisabledAccountGuard


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %I:%M:%S %p'
)
logger = logging.getLogger(__name__)

class TradeExecutor:
    sleep_time = 0.5
    ASSET_MAPPING_CONFIG = "asset_mapping_config.json"
    FAILURE_RETRY_BASE_SECONDS = 5
    FAILURE_RETRY_MAX_SECONDS = 60
    DISABLED_ACCOUNT_QUARANTINE_AFTER_FAILURES = 4
    
    # Note: Rate limiting is now per-exchange (set in each account processor's __init__)
    # Each exchange has its own MAX_CONCURRENT_SYMBOL_REQUESTS based on their API limits
    # Default fallback if account doesn't specify
    DEFAULT_MAX_CONCURRENT_SYMBOL_REQUESTS = 10

    @staticmethod
    def _normalize_account_key(value: str) -> str:
        """Normalize account key values for case-insensitive matching."""
        return str(value or "").strip().lower()

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
        if TradeExecutor._normalize_account_key(label) == TradeExecutor._normalize_account_key(exchange):
            return exchange
        return f"{exchange}::{label}"

    @staticmethod
    def _get_account_key(account) -> str:
        """Resolve the account key used for per-account depth/cache routing."""
        return TradeExecutor._compose_account_key(
            getattr(account, "exchange_name", ""),
            getattr(account, "account_name", None),
        )

    @staticmethod
    def _scoped_keys_for_exchange(candidates: Dict, exchange_name: str):
        """Return scoped keys for the given exchange in candidate order."""
        exchange = TradeExecutor._normalize_account_key(exchange_name)
        if not exchange:
            return []

        scoped = []
        for candidate in candidates.keys():
            candidate_str = str(candidate)
            if "::" not in candidate_str:
                continue
            candidate_exchange = candidate_str.partition("::")[0]
            if TradeExecutor._normalize_account_key(candidate_exchange) == exchange:
                scoped.append(candidate)
        return scoped

    def _resolve_account_key(self, mapping: Dict, account_name: str):
        """Resolve a mapping key by exact match first, then case-insensitive match."""
        if not isinstance(mapping, dict):
            return None
        if account_name in mapping:
            return account_name

        canonical = self._normalize_account_key(account_name)
        if not account_name:
            return None
        for key in mapping.keys():
            if self._normalize_account_key(key) == canonical:
                return key

        if "::" in str(account_name):
            account_exchange = self._normalize_account_key(str(account_name).partition("::")[0])
            _, _, account_label = str(account_name).partition("::")
            account_label = self._normalize_account_key(account_label)
            scoped_keys = self._scoped_keys_for_exchange(mapping, account_exchange)

            # Prefer exact exchange-scoped key match.
            for key in scoped_keys:
                _, _, key_label = str(key).partition("::")
                if self._normalize_account_key(key_label) == account_label:
                    return key

            # If there is exactly one scoped key for this exchange, use it.
            # If there are multiple, do not guess to avoid account collisions.
            if len(scoped_keys) == 1:
                return scoped_keys[0]
            if len(scoped_keys) > 1:
                return None

            # Legacy compatibility: support raw exchange-only key when no scoped keys exist.
            for key in mapping.keys():
                if self._normalize_account_key(key) == account_exchange and "::" not in str(key):
                    return key

            # Older mixed formats keyed by account label only.
            for key in mapping.keys():
                if self._normalize_account_key(key) == account_label and "::" not in str(key):
                    return key
            return None

        account_exchange = self._normalize_account_key(account_name)
        scoped_keys = self._scoped_keys_for_exchange(mapping, account_exchange)

        # A single scoped key can be treated as exchange-level target when resolving
        # legacy exchange-only names.
        if len(scoped_keys) == 1:
            return scoped_keys[0]

        # Multiple scoped keys are ambiguous; preserve legacy exchange-only cache key
        # if available, otherwise avoid aliasing.
        if len(scoped_keys) > 1:
            for key in mapping.keys():
                if self._normalize_account_key(key) == account_exchange and "::" not in str(key):
                    return key
            return None
        return None

    def _get_account_depths(self, mapping: Dict, account_name: str) -> Dict:
        """Get account depth map with case-insensitive key resolution."""
        resolved = self._resolve_account_key(mapping, account_name)
        if resolved is None:
            return {}
        account_depths = mapping.get(resolved, {})
        return account_depths if isinstance(account_depths, dict) else {}
    
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
        
        # Performance optimization: Cache for symbol details that rarely change
        # Instance-level caches to avoid shared state between instances
        self._symbol_details_cache = {}
        self._cache_ttl = 3600  # Cache for 1 hour (symbol details rarely change)
        self._cache_timestamp = {}

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
        
        # Resolve which legacy single-account processors should be loaded.
        # If an exchange already has enabled CCXT rows configured, prefer CCXT account lanes
        # so every configured account is handled independently and signal routing stays per-account.
        ccxt_exchange_names_enabled: set[str] = set()

        try:
            ccxt_credentials = load_ccxt_credentials()
            if ccxt_credentials.ccxt_list:
                ccxt_exchange_names_enabled = {
                    (cred.exchange_name or "").strip().lower()
                    for cred in ccxt_credentials.ccxt_list
                    if cred.enabled and cred.exchange_name
                }
        except ValueError:
            ccxt_credentials = None
            ccxt_exchange_names_enabled = set()

        self.accounts = []
        if "bybit" not in ccxt_exchange_names_enabled:
            self.accounts.append(ByBit())
        if "blofin" not in ccxt_exchange_names_enabled:
            self.accounts.append(BloFin())
        if "kucoin" not in ccxt_exchange_names_enabled:
            self.accounts.append(KuCoin())
        if "mexc" not in ccxt_exchange_names_enabled:
            self.accounts.append(MEXC())

        # Track retry pacing for accounts that repeatedly fail to execute updates.
        self._account_retry_state = {}
        self._disabled_account_guard = DisabledAccountGuard(
            base_delay_seconds=self.FAILURE_RETRY_BASE_SECONDS,
            max_delay_seconds=self.FAILURE_RETRY_MAX_SECONDS,
            quarantine_after_failures=self.DISABLED_ACCOUNT_QUARANTINE_AFTER_FAILURES,
        )
        self._next_cycle_sleep = None
        
        # Add CCXT exchanges if configured
        if ccxt_credentials and ccxt_credentials.ccxt_list:
            for ccxt_cred in ccxt_credentials.ccxt_list:
                if ccxt_cred.enabled:
                    account_key = self._compose_account_key(
                        ccxt_cred.exchange_name,
                        ccxt_cred.account_name,
                    )
                    if ccxt_cred.exchange_name.lower() == "hyperliquid":
                        account_processor = HyperliquidProcessor(ccxt_credentials=ccxt_cred)
                        self.accounts.append(account_processor)
                        logger.info(f"Added Hyperliquid account: {account_key} ({ccxt_cred.exchange_name})")
                    else:
                        ccxt_processor = CCXTProcessor(ccxt_credentials=ccxt_cred)
                        self.accounts.append(ccxt_processor)
                        logger.info(f"Added CCXT account: {account_key} ({ccxt_cred.exchange_name})")
        elif ccxt_credentials is None:
            # No CCXT exchanges configured
            logger.info("No CCXT exchanges configured")

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
    
    async def _get_cached_symbol_details(self, account, exchange_symbol: str):
        """
        Get symbol details with caching to reduce redundant API calls.
        Symbol details (lot size, tick size, etc.) rarely change, so we cache them for 1 hour.
        This reduces API calls by ~19 per exchange per cycle.
        """
        cache_key = f"{self._get_account_key(account)}:{exchange_symbol}"
        current_time = time.time()
        
        # Check if we have a valid cached entry
        if cache_key in self._symbol_details_cache:
            cache_age = current_time - self._cache_timestamp.get(cache_key, 0)
            if cache_age < self._cache_ttl:
                return self._symbol_details_cache[cache_key]
        
        # Cache miss or expired - fetch from exchange
        details = await account.get_symbol_details(exchange_symbol)
        self._symbol_details_cache[cache_key] = details
        self._cache_timestamp[cache_key] = current_time
        
        return details

    def _get_retry_state(self, account_key: str) -> dict:
        """Get or initialize retry state for an account key."""
        normalized_key = self._normalize_account_key(account_key)
        return self._account_retry_state.setdefault(
            normalized_key,
            {"failures": 0},
        )

    def _record_account_success(self, account_key: str):
        """Reset account failure count after a successful execution."""
        state = self._get_retry_state(account_key)
        state["failures"] = 0

    def _record_account_failure(self, account_key: str, error_msg: str | None = None):
        """
        Record account failure count with exponential delay metadata for logging.

        Accounts are still retried each cycle; delay is informational only.
        """
        state = self._get_retry_state(account_key)
        state["failures"] += 1
        delay = self.FAILURE_RETRY_BASE_SECONDS * (2 ** min(state["failures"] - 1, 10))
        if delay > self.FAILURE_RETRY_MAX_SECONDS:
            delay = self.FAILURE_RETRY_MAX_SECONDS
        if error_msg:
            logger.warning(
                f"{account_key}: execution failed, retry in {delay:.1f}s (failures={state['failures']})"
            )

    @staticmethod
    def _is_auth_or_permission_error(error_msg: str | None) -> bool:
        msg = str(error_msg or "").strip().lower()
        if not msg:
            return False
        auth_tokens = (
            "api key",
            "invalid key",
            "invalid api",
            "unauthorized",
            "not authorized",
            "permission",
            "forbidden",
            "signature",
            "auth",
            "authentication",
            "access denied",
            "permission denied",
        )
        return any(token in msg for token in auth_tokens)

    @staticmethod
    def _error_signature(error_msg: str | None) -> str:
        return " ".join(str(error_msg or "").strip().split()).lower()[:256]

    def _can_attempt_disabled_account(self, account_key: str) -> bool:
        can_attempt, retry_in = self._disabled_account_guard.can_attempt(account_key)
        if can_attempt:
            return True

        state = self._disabled_account_guard.state(account_key)
        should_log, suppressed = self._disabled_account_guard.should_log_skip(account_key)
        if should_log:
            if state.quarantined:
                suppressed_note = (
                    f" ({suppressed} suppressed skips)"
                    if suppressed > 0
                    else ""
                )
                logger.warning(
                    f"{account_key}: disabled account is quarantined after auth failures; "
                    f"skipping close-only API attempts{suppressed_note}"
                )
            else:
                suppressed_note = (
                    f" ({suppressed} suppressed skips)"
                    if suppressed > 0
                    else ""
                )
                logger.warning(
                    f"{account_key}: disabled account close-only retry cooling down for "
                    f"{retry_in:.1f}s{suppressed_note}"
                )
        return False

    def _record_disabled_account_success(self, account_key: str):
        self._disabled_account_guard.record_success(account_key)

    def _record_disabled_account_auth_failure(self, account_key: str, error_msg: str):
        quarantined, retry_in, failures = self._disabled_account_guard.record_auth_failure(
            account_key,
            error_signature=self._error_signature(error_msg),
        )
        if quarantined:
            logger.warning(
                f"{account_key}: disabled account entered in-memory quarantine after "
                f"{failures} auth failures"
            )
            return
        logger.warning(
            f"{account_key}: disabled account auth failure (failures={failures}); "
            f"retrying close-only flow in {retry_in:.1f}s"
        )
        
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
    
    async def _process_symbol(self, account, symbol_config: dict, signals: Dict, total_value: float):
        """
        Process a single symbol for an account.
        Extracted as a separate method to enable parallel processing of symbols.
        
        This maintains all the original logic but allows symbols to be processed concurrently.
        """
        try:
            account_key = self._get_account_key(account)
            signal_symbol = symbol_config['symbol']
            account_signals = self._get_account_depths(signals, account_key)
            depth = account_signals.get(signal_symbol, 0)
            
            # Map to exchange symbol format
            exchange_symbol = account.map_signal_symbol_to_exchange(signal_symbol)
            
            # Get current market price
            ticker = await account.fetch_tickers(exchange_symbol)
            if not ticker:
                logger.error(f"Could not get price for {exchange_symbol}")
                return False

            price = ticker.last  # Use last price from ticker

            # Calculate position value in USDT (this will be our margin)
            position_value = total_value * depth  # depth is already weighted

            # Calculate raw quantity based on leverage
            leverage = self.signal_manager.get_target_leverage(
                account_name=account_key,
                symbol=signal_symbol,
                fallback=symbol_config.get('leverage', 1),
            )
            notional_value = position_value * leverage  # Total position value including leverage
            quantity = notional_value / price  # Convert to asset quantity

            logger.info(f"Account Value: {total_value}, Depth: {depth}, "
                       f"Position Value: {position_value}, Leverage: {leverage}, "
                       f"Notional Value: {notional_value}, Quantity: {quantity}")

            # Use cached symbol details to reduce API calls
            symbol_details = await self._get_cached_symbol_details(account, exchange_symbol)
            lot_size, min_size, tick_size, contract_value, max_size = symbol_details
            
            logger.info(f"{exchange_symbol}: depth={depth}, "
                      f"position_value={position_value}, raw_quantity={quantity}")
            logger.info(f"Symbol {exchange_symbol} -> "
                      f"Lot Size: {lot_size}, "
                      f"Min Size: {min_size}, "
                      f"Tick Size: {tick_size}, "
                      f"Contract Value: {contract_value}, "
                      f"Max Size: {max_size}")

            # Let reconcile_position handle the quantity precision
            reconcile_result = await account.reconcile_position(
                symbol=exchange_symbol,
                size=quantity,
                leverage=leverage,
                margin_mode="isolated"
            )
            if reconcile_result is False:
                logger.warning(f"{account_key} reconcile_position reported failure for {exchange_symbol}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing {symbol_config.get('symbol', 'unknown')} on {account_key}: {str(e)}")
            return False

    async def process_account(self, account, signals: Dict):
        """
        Process signals for a specific account with PARALLEL symbol processing.
        
        OPTIMIZATION: Symbols are now processed concurrently instead of sequentially.
        This reduces processing time per exchange from ~6-8s to ~2-3s.
        
        All original logic is preserved including:
        - Disabled account handling (only processes if positions need closing)
        - Error handling per symbol
        - Cache confirmation
        """
        account_start_time = time.time()
        
        try:
            account_key = self._get_account_key(account)
            changed_symbols = self.signal_manager.get_changed_symbols(account_key)

            # No-op if this account has no depth changes in this cycle.
            if not changed_symbols:
                logger.info(f"{account_key}: no symbol changes this cycle")
                return True, None

            # Skip disabled accounts unless they have positions that need closing
            if not account.enabled:
                # Check if account has any non-zero positions in cache
                has_open_positions = False
                account_depths = {}
                try:
                    with open('account_asset_depths.json', 'r') as f:
                        depths_cache = json.load(f)
                        account_depths = self._get_account_depths(depths_cache, account_key)
                        has_open_positions = any(float(depth) != 0 for depth in account_depths.values())
                except (FileNotFoundError, json.JSONDecodeError, KeyError):
                    # If cache doesn't exist or is invalid, err on the side of caution and process
                    has_open_positions = True
                
                if not has_open_positions:
                    logger.info(f"Skipping disabled account {account_key}: no open positions")
                    return True, None

                open_symbols = sorted(
                    symbol
                    for symbol, depth in account_depths.items()
                    if float(depth) != 0
                )
                if not open_symbols:
                    logger.info(f"Skipping disabled account {account_key}: no open positions")
                    return True, None

                if not self._can_attempt_disabled_account(account_key):
                    return False, (
                        f"{account_key} disabled-close skipped due to retry cooldown or quarantine"
                    )

                logger.info(
                    f"Processing disabled account {account_key}: closing "
                    f"{len(open_symbols)} open positions: {', '.join(open_symbols)}"
                )

                symbol_config_by_symbol = {
                    config['symbol']: config
                    for config in self.weight_config
                }
                failed_errors: list[str] = []
                auth_error: str | None = None

                # Disabled accounts are intentionally processed sequentially so per-call
                # error context stays deterministic and we do not burst dead credentials.
                for signal_symbol in open_symbols:
                    symbol_config = symbol_config_by_symbol.get(signal_symbol, {})
                    exchange_symbol = account.map_signal_symbol_to_exchange(signal_symbol)
                    leverage_fallback = symbol_config.get('leverage', 1)
                    if hasattr(account, "last_reconcile_error"):
                        account.last_reconcile_error = None

                    try:
                        reconcile_result = await account.reconcile_position(
                            symbol=exchange_symbol,
                            size=0,
                            leverage=self.signal_manager.get_target_leverage(
                                account_name=account_key,
                                symbol=signal_symbol,
                                fallback=leverage_fallback,
                            ),
                            margin_mode="isolated"
                        )
                        if reconcile_result is True:
                            continue
                        error_msg = getattr(account, "last_reconcile_error", None)
                    except Exception as e:
                        reconcile_result = False
                        error_msg = str(e)

                    if reconcile_result is False:
                        error_msg = error_msg or (
                            f"{account_key} reconcile_position returned False for {exchange_symbol}"
                        )
                        failed_errors.append(error_msg)
                        if auth_error is None and self._is_auth_or_permission_error(error_msg):
                            auth_error = error_msg
                            break

                account_success = not failed_errors
                if account_success:
                    self._record_disabled_account_success(account_key)
                    await self.signal_manager.confirm_execution(account_key, True)
                    logger.info(f"{account_key}: disabled account positions closed successfully")
                    return True, None

                if auth_error:
                    self._record_disabled_account_auth_failure(account_key, auth_error)
                logger.warning(
                    f"{account_key}: disabled account close had {len(failed_errors)} failures"
                )
                return False, f"{account_key} had disabled-close failures"
                
            # Get total account value (including positions)
            total_value = await account.fetch_initial_account_value()
            if total_value is None:
                logger.warning(f"No account value found for {account_key} (account value fetch failed)")
                # Do NOT confirm cache on API failures; keep updates pending so we retry next cycle.
                await self.signal_manager.confirm_execution(account_key, False)
                return False, f"No account value found for {account_key}"

            if float(total_value) == 0.0:
                logger.info(f"{account_key}: account value is 0.0; skipping execution")
                await self.signal_manager.confirm_execution(account_key, True)
                return True, None

            logger.info(f"Processing {account_key} with total value: {total_value}")

            # Filter to only process changed symbols
            symbols_to_process = [
                config for config in self.weight_config 
                if config['symbol'] in changed_symbols
            ]
            logger.info(f"{account_key} processing {len(symbols_to_process)} changed symbols: {', '.join(changed_symbols)}")

            # *** OPTIMIZATION: Process symbols in parallel with rate limiting ***
            # Use exchange-specific limit or fallback to default
            max_concurrent = getattr(account, 'MAX_CONCURRENT_SYMBOL_REQUESTS', self.DEFAULT_MAX_CONCURRENT_SYMBOL_REQUESTS)
            semaphore = asyncio.Semaphore(max_concurrent)
            logger.info(f"{account_key} rate limit: {max_concurrent} concurrent requests")
            
            async def process_with_semaphore(symbol_config):
                """Wrapper to limit concurrent API calls per exchange."""
                async with semaphore:
                    return await self._process_symbol(account, symbol_config, signals, total_value)
            
            # Create tasks for only the symbols we need to process
            tasks = [
                asyncio.create_task(process_with_semaphore(config))
                for config in symbols_to_process
            ]
            
            # Wait for all symbols to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Check for errors (but don't fail the entire account)
            errors = [r for r in results if isinstance(r, Exception)]
            failed = [r for r in results if r is False]
            
            if errors:
                logger.warning(f"{account_key}: {len(errors)} symbols raised exceptions")
            if failed:
                logger.warning(f"{account_key}: {len(failed)} symbols failed processing")

            # Only confirm cache if everything succeeded; otherwise we'll keep seeing updates
            # and retry instead of falsely "accepting" the new target depths.
            account_success = (not errors) and (not failed)
            if account_success:
                await self.signal_manager.confirm_execution(account_key, True)
            else:
                await self.signal_manager.confirm_execution(account_key, False)
            
            elapsed = time.time() - account_start_time
            logger.info(f"Updated cache for {account_key} (completed in {elapsed:.2f}s)")
            if account_success:
                return True, None
            return False, f"{account_key} had symbol failures (exceptions={len(errors)}, failed={len(failed)})"

        except Exception as e:
            account_key = self._get_account_key(account)
            error_msg = f"Error processing {account_key}: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    async def execute(self):
        """
        Execute trades based on signal changes with performance monitoring.
        
        OPTIMIZATION: Added timing metrics to track performance improvements.
        """
        cycle_start_time = time.time()
        
        try:
            # Load weight config ONCE before processing accounts (prevents race condition)
            self._load_weight_config()
            
            self.signal_manager.check_for_updates(self.accounts)

            account_updates = {
                self._get_account_key(account): self.signal_manager.get_changed_symbols(
                    self._get_account_key(account)
                )
                for account in self.accounts
            }
            self._next_cycle_sleep = None
            
            # If no updates needed, skip execution.
            if not any((changed for changed in account_updates.values() if changed)):
                self._next_cycle_sleep = None
                return True
                
            # Get signals that need to be executed
            signals = self.signal_manager._temp_depths

            # Default to fast-cycle polling unless no lanes are runnable this round.
            self._next_cycle_sleep = self.sleep_time

            logger.info("=" * 60)
            logger.info(
                f"Starting execution cycle with {sum(1 for v in account_updates.values() if v)} accounts with depth changes"
            )
            
            # Process all accounts concurrently
            tasks: List[Tuple[str, asyncio.Task]] = []
            for account in self.accounts:
                account_key = self._get_account_key(account)
                if not account_updates.get(account_key):
                    continue
                task = asyncio.create_task(
                    self.process_account(account, signals)
                )
                tasks.append((account_key, task))
            
            # Wait for all account processing to complete
            results: List[Tuple[bool, str]] = await asyncio.gather(
                *[task for _, task in tasks],
                return_exceptions=True,
            )
            
            # Process results
            all_successful = True
            failed_account_keys: List[str] = []
            for (account_key, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    logger.error(f"Error processing {account_key}: {str(result)}")
                    all_successful = False
                    self._record_account_failure(account_key, str(result))
                    failed_account_keys.append(account_key)
                    continue
                    
                success, error = result
                if not success:
                    logger.error(f"Error processing {account_key}: {error}")
                    all_successful = False
                    self._record_account_failure(account_key, error)
                    failed_account_keys.append(account_key)
                else:
                    self._record_account_success(account_key)
                # Note: Cache confirmation already done in process_account() line 306

            if failed_account_keys:
                logger.info(
                    "Execution cycle had failures for "
                    f"{', '.join(sorted(set(failed_account_keys)))}. "
                    "Accounts remain eligible for retry on the next cycle."
                )

            # Log cycle timing
            cycle_duration = time.time() - cycle_start_time
            logger.info(f"Execution cycle completed in {cycle_duration:.2f}s")
            logger.info("=" * 60)
            
            return all_successful
            
        except Exception as e:
            logger.error(f"Error in execute: {str(e)}")
            return False



async def main():
    executor = TradeExecutor()
    logger.info(f"Starting OPTIMIZED trade execution engine at {datetime.now()}")
    logger.info("Optimizations enabled:")
    logger.info("  - Parallel symbol processing within each exchange")
    logger.info("  - Symbol details caching (1 hour TTL)")
    logger.info("  - Non-blocking asyncio sleep")
    logger.info("  - Per-exchange rate limiting with semaphores")
    logger.info(f"  - Default concurrent requests: {executor.DEFAULT_MAX_CONCURRENT_SYMBOL_REQUESTS}")
    
    # Log each account's specific rate limit
    for account in executor.accounts:
        limit = getattr(account, 'MAX_CONCURRENT_SYMBOL_REQUESTS', executor.DEFAULT_MAX_CONCURRENT_SYMBOL_REQUESTS)
        logger.info(f"  - {executor._get_account_key(account)}: {limit} concurrent requests/cycle")
    
    while True:
        try:
            # Execute trades
            await executor.execute()
            sleep_interval = executor._next_cycle_sleep
            if sleep_interval is None or sleep_interval < executor.sleep_time:
                sleep_interval = executor.sleep_time
            executor._next_cycle_sleep = None
            logger.info(f"Execution complete, waiting {sleep_interval} seconds for next cycle...")
            
            # OPTIMIZATION: Use asyncio.sleep instead of time.sleep
            # This allows the event loop to process other tasks (like TradingView signals)
            await asyncio.sleep(sleep_interval)
            
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")
            await asyncio.sleep(5)
        
        
if __name__ == "__main__":
    asyncio.run(main()) 
