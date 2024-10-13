from decimal import Decimal, ROUND_DOWN

def round_to_tick_size(value, tick_size):
    """Round value to the nearest tick size with correct precision handling."""
    tick_size_decimal = Decimal(str(tick_size))
    value_decimal = Decimal(str(value))

    # Use quantize to ensure rounding to tick size precision
    rounded_value = (value_decimal // tick_size_decimal) * tick_size_decimal
    return float(rounded_value)