from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP
from typing import Any, Literal

QuantizeRounding = Literal["nearest", "down", "up", "half_even", "half_up"]

_ROUNDING_MAP: dict[str, str] = {
    # "nearest" uses banker's rounding to match Python's `round()` on exact ties.
    "nearest": ROUND_HALF_EVEN,
    "half_even": ROUND_HALF_EVEN,
    "half_up": ROUND_HALF_UP,
    # Decimal ROUND_DOWN means "towards 0" (good default for reduce-only / diffs).
    "down": ROUND_DOWN,
    # Decimal ROUND_UP means "away from 0".
    "up": ROUND_UP,
}


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        raise TypeError("value cannot be None")
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, (int, float)):
        # `str(float)` in Python 3 is a shortest-roundtrip repr (good for Decimal parsing).
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(f"Unsupported numeric type: {type(value).__name__}")


def _step_quantum(step: Decimal) -> Decimal:
    step = abs(step)
    # Normalize so a step like "0.0100" doesn't force extra decimals.
    exponent = step.normalize().as_tuple().exponent
    return Decimal(1).scaleb(exponent)


def _quantize_decimal_to_step(value: Decimal, step: Decimal, *, rounding: QuantizeRounding) -> Decimal:
    if step == 0:
        return value
    if value == 0:
        return Decimal("0")

    rounding_mode = _ROUNDING_MAP.get(rounding)
    if rounding_mode is None:
        raise ValueError(f"Unsupported rounding mode: {rounding}")

    sign = -1 if value < 0 else 1
    value_abs = abs(value)
    step_abs = abs(step)

    steps = (value_abs / step_abs).to_integral_value(rounding=rounding_mode)
    snapped = (steps * step_abs) * sign

    # Clamp representation to the step's decimal exponent to avoid float noise and to handle
    # steps expressed as scientific notation (e.g. 1e-05).
    quantum = _step_quantum(step_abs)
    try:
        snapped = snapped.quantize(quantum)
    except Exception:
        snapped = snapped.normalize()

    return snapped


def quantize_to_step(value: Any, step: Any, *, rounding: QuantizeRounding = "nearest") -> float:
    """
    Snap `value` to a multiple of `step`.

    `rounding`:
    - "nearest": nearest step using banker's rounding (half-even) on exact ties
    - "down": towards 0 (safer for reduce-only / diffs)
    - "up": away from 0
    """
    if step in (None, 0, 0.0):
        return float(value)

    step_d = _to_decimal(step)
    if step_d <= 0:
        return float(value)

    value_d = _to_decimal(value)
    snapped = _quantize_decimal_to_step(value_d, step_d, rounding=rounding)
    snapped_f = float(snapped)
    # Avoid `-0.0`
    return 0.0 if snapped_f == 0.0 else snapped_f


def sanitize_lots(
    lots: Any,
    lot_size: Any,
    min_lots: Any | None = None,
    *,
    allow_below_min_to_zero: bool = False,
    rounding: QuantizeRounding = "nearest",
) -> float:
    """
    Snap order size to lot size step, optionally zeroing sizes below `min_lots`.

    - `allow_below_min_to_zero=True` is intended for diffs/reduce-only adjustments where the exchange
      rejects values below `min_lots`. In that case we treat the adjustment as a no-op (0).
    """
    lots_d = _to_decimal(lots)
    if lots_d == 0:
        return 0.0

    if lot_size not in (None, 0, 0.0):
        step_d = _to_decimal(lot_size)
        if step_d > 0:
            lots_d = _quantize_decimal_to_step(lots_d, step_d, rounding=rounding)

    if min_lots is not None and allow_below_min_to_zero:
        min_d = _to_decimal(min_lots)
        if min_d > 0 and abs(lots_d) < min_d:
            return 0.0

    lots_f = float(lots_d)
    return 0.0 if lots_f == 0.0 else lots_f


def round_to_tick_size(value: Any, tick_size: Any) -> float:
    """Backwards-compatible helper for prices (rounds towards 0)."""
    return quantize_to_step(value, tick_size, rounding="down")


def calculate_lots(size: Any, contract_value: Any) -> Decimal:
    """Calculate lots/contracts based on desired base-asset qty and contract value."""
    size_d = _to_decimal(size)
    contract_d = _to_decimal(contract_value)
    if contract_d == 0:
        raise ValueError("contract_value must be non-zero")
    return size_d / contract_d


def scale_size_and_price(
    symbol: str,
    size: float,
    price: float,
    lot_size: float,
    min_lots: float,
    tick_size: float,
    contract_value: float,
):
    """
    Scale base-asset `size` into exchange "lots/contracts" and snap both size and price to the
    exchange's lot/tick increments.
    """
    _ = symbol  # kept for call-site compatibility

    price_out = round_to_tick_size(price, tick_size)

    if size == 0:
        return 0.0, price_out, lot_size

    lots_d = calculate_lots(size, contract_value)

    # Enforce minimum tradable size (keeps previous behavior: non-zero orders are bumped to min).
    if min_lots not in (None, 0, 0.0):
        min_d = _to_decimal(min_lots)
        if min_d > 0 and abs(lots_d) < min_d:
            lots_d = min_d.copy_sign(lots_d)

    if lot_size not in (None, 0, 0.0):
        step_d = _to_decimal(lot_size)
        if step_d > 0:
            lots_d = _quantize_decimal_to_step(lots_d, step_d, rounding="nearest")

    lots_f = float(lots_d)
    lots_f = 0.0 if lots_f == 0.0 else lots_f
    return lots_f, price_out, lot_size


# ============================================================================
# CCXT Precision / Step Derivation Helpers
# ============================================================================
# CCXT exposes precision inconsistently: sometimes as decimal places (int),
# sometimes as step sizes. These helpers convert safely without magnitude
# heuristics that can misinterpret valid steps.
# ============================================================================


def _to_decimal_optional(value: Any) -> Decimal | None:
    """Convert value to Decimal, returning None on failure."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def ccxt_precision_to_step(value: Any) -> Decimal | None:
    """
    Convert CCXT precision value to a step size (Decimal).

    CCXT markets expose precision inconsistently:
      - int decimal places (e.g., 4 means step=0.0001)
      - float step size (e.g., 0.0001)
      - string representations of either

    This function converts safely and *never* guesses based on magnitude.

    Rules:
      - int >= 0 => step = 10^-int
      - Decimal that is an integer value (e.g., 4 or 4.0) => treat as decimal places
      - Decimal between 0 and 1 => treat as step directly
      - Otherwise => None

    Examples:
      >>> ccxt_precision_to_step(4)
      Decimal('0.0001')
      >>> ccxt_precision_to_step(0.0001)
      Decimal('0.0001')
      >>> ccxt_precision_to_step("1e-05")
      Decimal('1E-5')
    """
    if value is None:
        return None

    # ints are unambiguous: decimal places
    if isinstance(value, int):
        if value < 0:
            return None
        return Decimal(1) / (Decimal(10) ** Decimal(value))

    d = _to_decimal_optional(value)
    if d is None:
        return None

    # If it's an integer-valued decimal (like 4 or 4.0), treat as decimal places
    if d == d.to_integral_value():
        places = int(d)
        if places < 0:
            return None
        return Decimal(1) / (Decimal(10) ** Decimal(places))

    # Otherwise, if it's between 0 and 1, treat as step directly
    if Decimal(0) < d < Decimal(1):
        return d

    return None


def get_ccxt_market_steps(market: dict[str, Any]) -> tuple[Decimal | None, Decimal | None]:
    """
    Extract price and amount steps from a CCXT market dict safely.

    Returns (price_step, amount_step) where either may be None if not derivable.

    Uses precision fields first, then falls back to limits.min if present and
    looks like a valid step (0 < min < 1).
    """
    precision = market.get("precision") or {}

    price_step = ccxt_precision_to_step(precision.get("price"))
    amount_step = ccxt_precision_to_step(precision.get("amount"))

    # Fallback: sometimes exchanges expose explicit steps in 'limits'
    limits = market.get("limits") or {}
    amount_limits = limits.get("amount") or {}
    price_limits = limits.get("price") or {}

    # Use min as a "step-like" fallback only if it is a clean fractional step
    if amount_step is None:
        d = _to_decimal_optional(amount_limits.get("min"))
        if d is not None and Decimal(0) < d < Decimal(1):
            amount_step = d

    if price_step is None:
        d = _to_decimal_optional(price_limits.get("min"))
        if d is not None and Decimal(0) < d < Decimal(1):
            price_step = d

    return price_step, amount_step
