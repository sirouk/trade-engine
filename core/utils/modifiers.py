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

def scale_size_and_price(symbol: str, size: float, price: float, lot_size: float, min_lots: float, tick_size: float, contract_value: float):
 
    print(f"Symbol {symbol} -> Lot Size: {lot_size}, Min Size: {min_lots}, Tick Size: {tick_size}, Contract Value: {contract_value}")
    
    # Step 3: Round the price to the nearest tick size
    print(f"Price before: {price}")
    price = round_to_tick_size(price, tick_size)
    print(f"Price after tick rounding: {price}")
    
    # if size is 0, set size_in_lots to 0
    if size == 0:
        size_in_lots = 0
        return size_in_lots, price, lot_size

    # Calculate lots - keep everything as float until final output
    size_in_lots = float(size / contract_value)
    print(f"Size in lots: {size_in_lots}")

    # Ensure minimum size
    sign = -1 if size_in_lots < 0 else 1
    size_in_lots = max(abs(size_in_lots), min_lots) * sign
    print(f"Size after checking min: {size_in_lots}")
    
    # Round to lot size precision
    decimal_places = len(str(lot_size).rsplit('.', maxsplit=1)[-1]) if '.' in str(lot_size) else 0
    size_in_lots = float(f"%.{decimal_places}f" % (round(size_in_lots / lot_size) * lot_size))
    print(f"Size after rounding to lot size: {size_in_lots}")

    return size_in_lots, price, lot_size