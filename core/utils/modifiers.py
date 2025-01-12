from decimal import Decimal, ROUND_DOWN

def round_to_tick_size(value, tick_size):
    """Round value to the nearest tick size with correct precision handling."""
    if isinstance(value, float):
        value_decimal = Decimal(str(value))
    else:
        value_decimal = value  # Keep as Decimal if already Decimal
    tick_size_decimal = Decimal(str(tick_size))
    
    # Round down to nearest tick size
    rounded_value = (value_decimal // tick_size_decimal) * tick_size_decimal
    return float(rounded_value)  # Only convert to float at final step

def calculate_lots(size, contract_value):
    """Calculate the number of lots based on desired qty and contract value."""
    if isinstance(size, float):
        size_decimal = Decimal(str(size))
    else:
        size_decimal = size
        
    if isinstance(contract_value, float):
        contract_value_decimal = Decimal(str(contract_value))
    else:
        contract_value_decimal = contract_value
        
    lots = size_decimal / contract_value_decimal
    return lots  # Return Decimal to maintain precision