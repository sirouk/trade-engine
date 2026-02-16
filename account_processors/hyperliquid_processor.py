"""
Hyperliquid account processor.

Built on top of CCXTProcessor to share common exchange plumbing while handling
Hyperliquid-specific wallet/private-key context, symbol formatting, and request
parameters.
"""
import asyncio
import datetime
from typing import Optional

from account_processors.ccxt_processor import CCXTProcessor
from config.credentials import CCXTCredentials, load_ccxt_credentials
from core.unified_position import UnifiedPosition
from core.unified_ticker import UnifiedTicker
from core.utils.execute_timed import execute_with_timeout
from core.utils.modifiers import scale_size_and_price, sanitize_lots


class HyperliquidProcessor(CCXTProcessor):
    """
    Hyperliquid futures processor using CCXT for low-level exchange operations.
    """

    SETTLE_COIN = "USDC"
    SIGNAL_SYMBOL_OVERRIDES = {
        "BONKUSDT": "KBONKUSDT",
        "1000BONKUSDT": "KBONKUSDT",
        "PEPEUSDT": "KPEPEUSDT",
        "1000PEPEUSDT": "KPEPEUSDT",
    }

    def __init__(
        self,
        ccxt_credentials: CCXTCredentials = None,
        exchange_name: str = "hyperliquid",
        main_wallet: Optional[str] = None,
        agent_wallet: Optional[str] = None,
        private_key: Optional[str] = None,
        exchange_enabled: bool = True,
    ):
        # Build or resolve credentials explicitly for Hyperliquid.
        if ccxt_credentials is None:
            if main_wallet and private_key:
                ccxt_credentials = CCXTCredentials(
                    exchange_name=exchange_name,
                    api_key=main_wallet,
                    api_secret=private_key,
                    api_passphrase=agent_wallet or "",
                    leverage_override=0,
                    enabled=exchange_enabled,
                    copy_trading=False,
                )
            else:
                all_credentials = load_ccxt_credentials()
                if not all_credentials.ccxt_list:
                    raise ValueError("No CCXT exchange configured. Add Hyperliquid to CCXT credentials first.")

                match = None
                for cred in all_credentials.ccxt_list:
                    if cred.exchange_name.lower() == exchange_name.lower():
                        match = cred
                        break

                if match is None:
                    raise ValueError(f"No CCXT credentials found for exchange '{exchange_name}'.")

                ccxt_credentials = match

        super().__init__(ccxt_credentials=ccxt_credentials)

        # Normalize identity for clarity in logs and execution.
        self.exchange_name = "Hyperliquid"
        self.account_name = (getattr(self.credentials, "account_name", "") or self.exchange_name).strip() or self.exchange_name
        if str(self.account_name).strip().lower() == str(self.exchange_name).strip().lower():
            self.log_prefix = f"[{self.exchange_name}]"
        else:
            self.log_prefix = f"[{self.exchange_name}:{self.account_name}]"

        # Hyperliquid enforces a minimum order notional (commonly $10). Keep this at the
        # account-level so each wallet can override if needed.
        configured_min_notional = float(getattr(self.credentials, "min_order_notional_usd", 0.0) or 0.0)
        self.min_order_notional_usd = configured_min_notional if configured_min_notional > 0 else 10.0

        # Conservative request concurrency for perps routing + signing operations.
        self.MAX_CONCURRENT_SYMBOL_REQUESTS = 3

        # Hyperliquid credential semantics:
        # - ccxt_credentials.api_key: main wallet address
        # - ccxt_credentials.api_secret: private key
        # - ccxt_credentials.api_passphrase: agent wallet address (optional)
        self.main_wallet = self._normalize_wallet_address(self.credentials.api_key)
        self.agent_wallet = self._normalize_wallet_address(
            getattr(self.credentials, "api_passphrase", "") or agent_wallet
        )

        # CCXT Hyperliquid expects walletAddress/privateKey on exchange instance.
        self.exchange.walletAddress = self.main_wallet
        self.exchange.privateKey = self.credentials.api_secret
        self.exchange.options["walletAddress"] = self.main_wallet
        self.exchange.options.setdefault("defaultSlippage", "0.05")
        self.exchange.options["builderFee"] = False
        self.exchange.options["approvedBuilderFee"] = False
        self.exchange.options.setdefault("defaultMarginMode", "isolated")

        # Keep the user context explicit on the exchange object as well.
        self.exchange.params = getattr(self.exchange, "params", {}) or {}
        self.exchange.params["user"] = self.main_wallet

        # Keep margin mode map local to avoid dependency on unknown exchange enums.
        self.margin_mode_map = {
            "isolated": "isolated",
            "cross": "cross",
        }
        self.inverse_margin_mode_map = {v: k for k, v in self.margin_mode_map.items()}
        self._market_symbols_loaded = False
        self._resolved_symbol_cache = {}

    def _normalize_wallet_address(self, address: Optional[str]) -> str:
        """
        Normalize a wallet address for Hyperliquid endpoint consistency.
        """
        if not address:
            return ""
        normalized = address.strip()
        if normalized.startswith("0X"):
            normalized = "0x" + normalized[2:]
        if normalized.startswith("0x"):
            return "0x" + normalized[2:].lower()
        return normalized.lower()

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _is_builder_fee_not_approved_error(self, error: Exception) -> bool:
        """
        Detect builder fee authorization failures returned by Hyperliquid.
        """
        message = str(error).lower()
        return (
            "builder fee has not been approved" in message
            or "max builder fee" in message
            or "builder not approved" in message
        )

    async def _estimate_order_notional(
        self,
        symbol: str,
        size: float,
        contract_value: float,
    ) -> float:
        if self.min_order_notional_usd <= 0 or not size:
            return 0.0
        price = await self._get_market_reference_price(symbol)
        if not price:
            return 0.0
        if contract_value is None:
            contract_value = 1.0
        return abs(float(size)) * float(price) * float(contract_value)

    async def _get_market_reference_price(self, symbol: str) -> float | None:
        """
        Hyperliquid requires a market price for market orders.
        """
        try:
            resolved_symbol = await self._resolve_symbol(symbol)
        except Exception:
            resolved_symbol = symbol

        candidates = [resolved_symbol]
        last_error = None

        for candidate in candidates:
            market = self.exchange.markets.get(candidate) if self.exchange.markets else None
            if isinstance(market, dict):
                raw_mark_px = market.get("info", {}).get("markPx")
                try:
                    price = self._safe_float(raw_mark_px)
                    if price > 0:
                        return price
                except Exception:
                    pass

            try:
                ticker = await execute_with_timeout(
                    self.exchange.fetch_ticker,
                    timeout=30,
                    symbol=candidate,
                )

                for field in ("last", "close", "markPrice", "indexPrice"):
                    price = self._safe_float(ticker.get(field), 0.0)
                    if price > 0:
                        return price
            except Exception as e:
                last_error = e
        if last_error:
            print(
                f"{self.log_prefix} Could not resolve market order price for {symbol}. "
                f"Candidates={candidates}, last_error={str(last_error)}"
            )
        return None

    def _normalize_signal_symbol(self, signal_symbol: str) -> str:
        """
        Normalize signal symbols to a Hyperliquid-compatible unified format.
        """
        if not signal_symbol:
            return signal_symbol

        symbol = self.SIGNAL_SYMBOL_OVERRIDES.get(signal_symbol, signal_symbol)
        symbol = symbol.strip()

        if "/" not in symbol:
            if symbol.endswith("USDT"):
                base = symbol[:-4]
                if not base:
                    return symbol
                return f"{base}/{self.SETTLE_COIN}:{self.SETTLE_COIN}"
            return symbol

        base, _, settle = symbol.partition("/")
        if not base:
            return symbol

        quote, _, _ = settle.partition(":")
        if quote == self.SETTLE_COIN:
            return f"{base}/{self.SETTLE_COIN}:{self.SETTLE_COIN}"
        if quote == "USDT":
            return f"{base}/{self.SETTLE_COIN}:{self.SETTLE_COIN}"

        return symbol

    def _build_user_params(
        self,
        additional: Optional[dict] = None,
        include_sub_account: bool = False,
        require_user: bool = True,
    ) -> dict:
        """
        Build request params with user/sub-account context.

        Keep sub-account usage opt-in to avoid injecting invalid vault context into
        read endpoints and to allow fallback behavior for accounts that do not have
        a registered Hyperliquid vault.
        """
        params = {}
        if require_user and self.main_wallet:
            params["user"] = self.main_wallet
        if include_sub_account and self.agent_wallet:
            params["subAccountAddress"] = self.agent_wallet
        if additional:
            params.update(additional)
        return params

    def _strip_sub_account_params(self, params: Optional[dict]) -> dict:
        """
        Remove vault/sub-account parameters so reads/requests can safely fallback
        to direct main-wallet authentication.
        """
        if not isinstance(params, dict):
            return {}
        return {
            key: value
            for key, value in params.items()
            if key not in {"subAccountAddress", "vaultAddress"}
        }

    def _is_vault_not_registered_error(self, error: Exception) -> bool:
        """
        Identify errors that indicate sub-account/vault routing is invalid.
        """
        message = str(error)
        return (
            "vault not registered" in message.lower()
            or "user or api wallet" in message.lower()
        )

    async def _execute_with_vault_fallback(self, fn, timeout: int, **kwargs):
        """
        Execute an exchange call and retry once without vault/sub-account context
        when Hyperliquid reports the vault is not registered.
        """
        try:
            return await execute_with_timeout(fn, timeout=timeout, **kwargs)
        except Exception as error:
            if self._is_builder_fee_not_approved_error(error):
                self.exchange.options["builderFee"] = False
                self.exchange.options["approvedBuilderFee"] = False
                print(f"{self.log_prefix} Retrying without builder fee after approval error: {error}")
                return await execute_with_timeout(fn, timeout=timeout, **kwargs)

            if not self._is_vault_not_registered_error(error):
                raise

            fallback_params = self._strip_sub_account_params(kwargs.get("params"))
            if fallback_params == kwargs.get("params"):
                raise

            fallback_kwargs = dict(kwargs)
            fallback_kwargs["params"] = fallback_params
            print(f"{self.log_prefix} Retrying without sub-account after vault lookup failure: {error}")
            return await execute_with_timeout(fn, timeout=timeout, **fallback_kwargs)

    def _symbol_candidates(self, symbol: str) -> list[str]:
        """
        Generate potential Hyperliquid symbol variants for robust resolution.
        """
        symbol = self._normalize_signal_symbol(symbol)
        if not symbol:
            return [symbol]
        if "/" not in symbol:
            return [symbol]

        candidates = [symbol]

        def _add_candidate(candidate: str):
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        if ":" in symbol:
            base_symbol = symbol.split(":", 1)[0]
            _add_candidate(base_symbol)
            return candidates

        base, _, settle = symbol.rpartition("/")
        if settle:
            _add_candidate(f"{base}/{settle}:{settle}")

        stripped_base = base[4:] if base.startswith("1000") and len(base) > 4 else None
        if stripped_base:
            _add_candidate(f"{stripped_base}/{self.SETTLE_COIN}:{self.SETTLE_COIN}")
            _add_candidate(f"{stripped_base}/{self.SETTLE_COIN}")

        # canonical fallback for USD/USDC-like symbols
        if f"{self.SETTLE_COIN}" == settle:
            _add_candidate(f"{base}/{self.SETTLE_COIN}:{self.SETTLE_COIN}")

        return candidates

    async def _resolve_symbol(self, symbol: str) -> str:
        """
        Resolve a candidate symbol into a format that CCXT Hyperliquid accepts.
        """
        if not symbol:
            return symbol

        cached = self._resolved_symbol_cache.get(symbol)
        if cached is not None:
            return cached

        candidates = self._symbol_candidates(symbol)
        if not self._market_symbols_loaded:
            try:
                await self.exchange.load_markets()
                self._market_symbols_loaded = True
            except Exception:
                self._resolved_symbol_cache[symbol] = candidates[0]
                return candidates[0]

        for candidate in candidates:
            if candidate in self.exchange.markets:
                self._resolved_symbol_cache[symbol] = candidate
                if symbol != candidate:
                    self._resolved_symbol_cache[candidate] = candidate
                return candidate

        self._resolved_symbol_cache[symbol] = candidates[0]
        return candidates[0]

    async def fetch_balance(self, instrument="USDC"):
        """
        Fetch wallet balance with explicit user context.
        """
        try:
            balance = await execute_with_timeout(
                self.exchange.fetch_balance,
                timeout=15,
                params=self._build_user_params(),
            )

            if isinstance(balance, dict) and instrument in balance:
                instrument_balance = balance[instrument]
                if isinstance(instrument_balance, dict):
                    if "free" in instrument_balance and instrument_balance["free"] is not None:
                        return instrument_balance["free"]
                    return instrument_balance.get("total", 0.0)

            return 0.0
        except Exception as e:
            print(f"{self.log_prefix} Error fetching balance: {str(e)}")
            return None

    async def fetch_all_open_positions(self):
        """
        Fetch all open positions for the configured wallets.
        """
        try:
            return await self._execute_with_vault_fallback(
                self.exchange.fetch_positions,
                timeout=20,
                symbols=None,
                params=self._build_user_params(),
            )
        except Exception as e:
            print(f"{self.log_prefix} Error fetching all open positions: {str(e)}")
            return []

    async def fetch_open_positions(self, symbol):
        """
        Fetch open futures positions for a specific symbol.
        """
        try:
            resolved_symbol = await self._resolve_symbol(symbol)
            return await self._execute_with_vault_fallback(
                self.exchange.fetch_positions,
                timeout=20,
                symbols=[resolved_symbol],
                params=self._build_user_params(),
            )
        except Exception as e:
            print(f"{self.log_prefix} Error fetching open positions: {str(e)}")
            return []

    async def fetch_open_orders(self, symbol):
        """
        Fetch open orders for a specific symbol.
        """
        try:
            resolved_symbol = await self._resolve_symbol(symbol)
            return await execute_with_timeout(
                self.exchange.fetch_open_orders,
                timeout=15,
                symbol=resolved_symbol,
                params=self._build_user_params(),
            )
        except Exception as e:
            print(f"{self.log_prefix} Error fetching open orders: {str(e)}")
            return []

    async def fetch_and_map_positions(self, symbol: str):
        """
        Fetch open positions and map them to UnifiedPosition objects.
        """
        try:
            positions = await self.fetch_open_positions(symbol)
            unified_positions = [
                self.map_hyperliquid_position_to_unified(position)
                for position in positions
                if float(position.get("contracts", position.get("size", 0))) != 0
            ]
            for unified_position in unified_positions:
                print(f"{self.log_prefix} Unified Position: {unified_position}")
            return unified_positions
        except Exception as e:
            print(f"{self.log_prefix} Error mapping Hyperliquid positions: {str(e)}")
            return []

    def map_hyperliquid_position_to_unified(self, position: dict) -> UnifiedPosition:
        """
        Convert a Hyperliquid position response into a UnifiedPosition object.
        """
        contracts = float(position.get("contracts", position.get("size", 0)))
        side = position.get("side", "long")
        if side not in ("long", "short"):
            side = "long" if contracts >= 0 else "short"

        size = contracts if side == "long" else -contracts
        average_entry_price = float(position.get("average", 0) or position.get("entryPrice", 0))
        leverage = float(position.get("leverage", 1))
        unrealized_pnl = float(position.get("unrealizedPnl", 0))
        margin_mode = position.get("marginMode", "isolated")

        return UnifiedPosition(
            symbol=position.get("symbol"),
            size=size,
            average_entry_price=average_entry_price,
            leverage=leverage,
            direction="long" if size > 0 else "short",
            unrealized_pnl=unrealized_pnl,
            margin_mode=self.inverse_margin_mode_map.get(margin_mode, margin_mode),
            exchange=self.exchange_name,
        )

    async def fetch_tickers(self, symbol):
        """
        Fetch unified ticker for a symbol.
        """
        try:
            resolved_symbol = await self._resolve_symbol(symbol)
            resolved_symbols = [resolved_symbol]
            last_error = None
            ticker = None

            for candidate in resolved_symbols:
                market = self.exchange.markets.get(candidate) if self.exchange.markets else None
                if isinstance(market, dict):
                    info = market.get("info", {})
                    mark_px = self._safe_float(info.get("markPx"))
                    if mark_px > 0:
                        ticker = {
                            "markPrice": mark_px,
                            "last": mark_px,
                            "bid": mark_px,
                            "ask": mark_px,
                            "quoteVolume": 0,
                            "baseVolume": 0,
                        }
                        break

                try:
                    ticker = await execute_with_timeout(
                        self.exchange.fetch_ticker,
                        timeout=30,
                        symbol=candidate,
                    )
                    if candidate != symbol:
                        self._resolved_symbol_cache[symbol] = candidate
                    break
                except Exception as e:
                    last_error = e

            if not ticker:
                print(
                    f"{self.log_prefix} Could not fetch ticker for {symbol}. "
                    f"Candidates={resolved_symbols}, last_error={str(last_error)}"
                )
                return None

            last_price = (
                ticker.get("last")
                or ticker.get("close")
                or ticker.get("markPrice")
                or ticker.get("indexPrice")
                or 0
            )
            if last_price in (None, ""):
                last_price = ticker.get("close") or 0
            if last_price in (None, ""):
                last_price = 0

            return UnifiedTicker(
                symbol=symbol,
                bid=self._safe_float(ticker.get("bid", 0)),
                ask=self._safe_float(ticker.get("ask", 0)),
                last=self._safe_float(last_price, 0),
                volume=self._safe_float(
                    ticker.get("quoteVolume", ticker.get("baseVolume", 0)),
                    0,
                ),
                exchange=self.exchange_name,
            )
        except Exception as e:
            print(f"{self.log_prefix} Error fetching tickers: {str(e)}")
            return None

    async def get_symbol_details(self, symbol: str):
        """
        Resolve symbol variants and return instrument constraints.
        """
        resolved_symbol = await self._resolve_symbol(symbol)
        return await super().get_symbol_details(resolved_symbol)

    async def open_market_position(
        self,
        symbol: str,
        side: str,
        size: float,
        leverage: int,
        margin_mode: str,
        scale_lot_size: bool = True,
        adjust_leverage: bool = True,
        adjust_margin_mode: bool = True,
        reduce_only: bool = False,
    ):
        """
        Open/adjust a market position.
        """
        try:
            resolved_symbol = await self._resolve_symbol(symbol)
            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(resolved_symbol)

            lots = (
                scale_size_and_price(symbol, size, 0, lot_size, min_lots, tick_size, contract_value)[0]
                if scale_lot_size
                else size
            )
            lots = sanitize_lots(
                lots,
                lot_size,
                min_lots,
                allow_below_min_to_zero=not scale_lot_size,
                rounding="nearest" if scale_lot_size else "down",
            )
            if lots == 0:
                return None

            order_price = await self._get_market_reference_price(resolved_symbol)
            if not order_price:
                print(f"{self.log_prefix} No reference price for {resolved_symbol}; skipping market order.")
                return None

            order_price = self.exchange.price_to_precision(resolved_symbol, order_price)
            if not order_price:
                print(f"{self.log_prefix} No valid reference price precision for {resolved_symbol}; skipping market order.")
                return None

            default_slippage = self.exchange.options.get("defaultSlippage", "0.05")
            if default_slippage is None:
                default_slippage = "0.05"
            if isinstance(default_slippage, (int, float)):
                default_slippage = str(default_slippage)

            order_params = self._build_user_params(
                {
                    "marginMode": margin_mode,
                    "leverage": leverage,
                    "reduceOnly": reduce_only,
                    "slippage": default_slippage,
                },
            )

            if adjust_leverage:
                try:
                    await execute_with_timeout(
                        self.exchange.set_leverage,
                        timeout=5,
                        leverage=leverage,
                        symbol=resolved_symbol,
                        params={"marginMode": margin_mode},
                    )
                except Exception:
                    pass

            max_chunk = sanitize_lots(
                max_size,
                lot_size,
                min_lots,
                rounding="down",
            )
            if max_chunk <= 0:
                return None

            if lots > max_chunk:
                num_full_chunks = int(lots // max_chunk)
                remainder = lots - (num_full_chunks * max_chunk)
                if remainder < 0:
                    remainder = 0.0
                remainder = sanitize_lots(
                    remainder,
                    lot_size,
                    min_lots,
                    allow_below_min_to_zero=True,
                    rounding="down",
                )

                orders = []
                for _ in range(num_full_chunks):
                    order = await self._execute_with_vault_fallback(
                        self.exchange.create_market_order,
                        timeout=20,
                        symbol=resolved_symbol,
                        side=side.lower(),
                        amount=max_chunk,
                        price=order_price,
                        params=order_params,
                    )
                    orders.append(order)
                    await asyncio.sleep(0.1)

                if remainder > 0:
                    order = await self._execute_with_vault_fallback(
                        self.exchange.create_market_order,
                        timeout=20,
                        symbol=resolved_symbol,
                        side=side.lower(),
                        amount=remainder,
                        price=order_price,
                        params=order_params,
                    )
                    orders.append(order)

                return orders

            order = await self._execute_with_vault_fallback(
                self.exchange.create_market_order,
                timeout=20,
                symbol=resolved_symbol,
                side=side.lower(),
                amount=lots,
                price=order_price,
                params=order_params,
            )
            return order
        except Exception as e:
            print(f"{self.log_prefix} Error placing market order for {resolved_symbol}: {str(e)}")
            return None

    async def close_position(self, symbol: str):
        """
        Close a specific symbol position.
        """
        try:
            positions = await self.fetch_open_positions(symbol)
            if not positions:
                print(f"{self.log_prefix} No open position found for {symbol}.")
                return None

            unified_positions = [
                self.map_hyperliquid_position_to_unified(pos)
                for pos in positions
                if float(pos.get("contracts", pos.get("size", 0))) != 0
            ]

            if not unified_positions:
                print(f"{self.log_prefix} No mapped position found for {symbol}.")
                return None

            position = unified_positions[0]
            side = "sell" if position.size > 0 else "buy"
            size = abs(position.size)
            leverage = int(position.leverage) if position.leverage else 1
            margin_mode = position.margin_mode or "isolated"

            return await self.open_market_position(
                symbol=symbol,
                side=side,
                size=size,
                leverage=leverage,
                margin_mode=margin_mode,
                reduce_only=True,
                scale_lot_size=False,
            )
        except Exception as e:
            print(f"{self.log_prefix} Error closing position: {str(e)}")
            return None

    async def reconcile_position(self, symbol: str, size: float, leverage: int, margin_mode: str):
        """
        Reconcile the current position with target size/leverage/margin mode.
        """
        try:
            if self.leverage_override > 0:
                leverage = self.leverage_override

            resolved_symbol = await self._resolve_symbol(symbol)
            unified_positions = await self.fetch_and_map_positions(symbol)
            current_position = unified_positions[0] if unified_positions else None

            lot_size, min_lots, tick_size, contract_value, max_size = await self.get_symbol_details(resolved_symbol)

            size, _, lot_size = scale_size_and_price(
                symbol,
                size,
                0,
                lot_size,
                min_lots,
                tick_size,
                contract_value,
            )

            current_size = current_position.size if current_position else 0
            current_margin_mode = current_position.margin_mode if current_position else None
            current_leverage = current_position.leverage if current_position else None

            if (current_size > 0 and size < 0) or (current_size < 0 and size > 0):
                close_result = await self.close_position(symbol)
                if close_result is None:
                    close_side = "sell" if current_size > 0 else "buy"
                    flip_amount = abs(current_size) + abs(size)
                    await self.open_market_position(
                        symbol=symbol,
                        side=close_side,
                        size=flip_amount,
                        leverage=leverage,
                        margin_mode=margin_mode,
                        scale_lot_size=False,
                    )
                current_size = 0

            if current_size != 0 and size != 0 and current_margin_mode != margin_mode:
                try:
                    await execute_with_timeout(
                        self.exchange.set_margin_mode,
                        timeout=5,
                        marginMode=margin_mode,
                        symbol=resolved_symbol,
                        params=self._build_user_params(),
                    )
                except Exception:
                    await self.close_position(symbol)
                    current_size = 0

            if current_leverage != leverage and abs(size) > 0:
                try:
                    await execute_with_timeout(
                        self.exchange.set_leverage,
                        timeout=5,
                        leverage=leverage,
                        symbol=resolved_symbol,
                        params=self._build_user_params({"marginMode": margin_mode}),
                    )
                except Exception:
                    pass

            size_diff = sanitize_lots(
                size - current_size,
                lot_size,
                min_lots,
                allow_below_min_to_zero=True,
                rounding="down",
            )

            if size == 0:
                if abs(current_size) < min_lots:
                    return
            elif abs(current_size) == 0:
                pass
            else:
                position_tolerance = max(lot_size, min(abs(current_size), abs(size)) * 0.001)
                if abs(size_diff) < position_tolerance:
                    return

            side = "buy" if size_diff > 0 else "sell"
            size_diff = abs(size_diff)
            if size_diff <= 0:
                return

            if await self._is_tiny_order_update(
                symbol,
                size_diff,
                contract_value,
            ):
                print(
                    f"{self.log_prefix} Skipping {symbol}: adjust-size notional is below minimum "
                    f"{self.min_order_notional_usd:.4f} (size_diff={size_diff}, contract_value={contract_value})."
                )
                return

            await self.open_market_position(
                symbol=symbol,
                side=side,
                size=size_diff,
                leverage=leverage,
                margin_mode=margin_mode,
                scale_lot_size=False,
            )
        except Exception as e:
            print(f"{self.log_prefix} Error reconciling position: {str(e)}")
            return

    def map_signal_symbol_to_exchange(self, signal_symbol: str) -> str:
        """
        Convert signal symbol format (e.g., BTCUSDT) to Hyperliquid format.
        """
        return self._normalize_signal_symbol(signal_symbol)

    async def fetch_initial_account_value(self) -> float | None:
        """
        Calculate total account value = available USDC + active initial margin.
        """
        try:
            balance = await self.fetch_balance(self.SETTLE_COIN)
            if balance is None:
                return None
            available_balance = float(balance)

            positions = await self.fetch_all_open_positions()
            if positions is None:
                return None

            position_margin = 0.0
            for pos in positions:
                initial_margin = pos.get("initialMargin")
                if initial_margin not in (None, ""):
                    position_margin += float(initial_margin)
                    continue

                notional = pos.get("notional")
                leverage = pos.get("leverage")
                if (
                    notional not in (None, "")
                    and leverage not in (None, "")
                    and float(leverage) > 0
                ):
                    position_margin += abs(float(notional)) / float(leverage)
                    continue

                info_margin = (pos.get("info") or {}).get("imf") or (pos.get("info") or {}).get("margin")
                if info_margin not in (None, ""):
                    position_margin += float(info_margin)

            return available_balance + position_margin
        except Exception as e:
            print(f"{self.log_prefix} Error calculating initial account value: {str(e)}")
            return None

    async def test_symbol_formats(self):
        """
        Optional helper for symbol mapping diagnostics.
        """
        try:
            test_symbols = ["BTCUSDT", "ETHUSDT"]
            for symbol in test_symbols:
                mapped = self.map_signal_symbol_to_exchange(symbol)
                print(f"{self.log_prefix} Signal symbol: {symbol} -> Exchange symbol: {mapped}")
        except Exception as e:
            print(f"{self.log_prefix} Error in symbol format test: {str(e)}")

    async def test_balance_and_positions(self):
        """
        Lightweight smoke test: fetch balance and initial account value.
        """
        try:
            balance = await self.fetch_balance(self.SETTLE_COIN)
            account_value = await self.fetch_initial_account_value()
            print(f"{self.log_prefix} {self.SETTLE_COIN} Balance: {balance}")
            print(f"{self.log_prefix} Initial Account Value: {account_value}")
        except Exception as e:
            print(f"{self.log_prefix} Error in smoke test: {str(e)}")


async def main():
    start_time = datetime.datetime.now()
    processor = HyperliquidProcessor(
        exchange_name="hyperliquid",
    )
    await processor.test_balance_and_positions()
    await processor.test_symbol_formats()
    await processor.__aexit__(None, None, None)
    end_time = datetime.datetime.now()
    print(f"{processor.log_prefix} Test runtime: {end_time - start_time}")


if __name__ == "__main__":
    asyncio.run(main())
