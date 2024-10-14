from decimal import Decimal, ROUND_DOWN

def round_to_tick_size(value, tick_size):
    """Round value to the nearest tick size with correct precision handling."""
    tick_size_decimal = Decimal(str(tick_size))
    value_decimal = Decimal(str(value))

    # Round down to nearest tick size
    rounded_value = (value_decimal // tick_size_decimal) * tick_size_decimal
    return float(rounded_value)

def calculate_lots(size, contract_value):
    """Calculate the number of lots based on desired qty and contract value."""
    lots = Decimal(str(size)) / Decimal(str(contract_value))
    return float(lots)