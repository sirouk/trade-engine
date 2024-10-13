def round_to_tick_size(value, tick_size):
    """Round value to the nearest tick size."""
    precision = len(str(tick_size).split('.')[1])
    return round(value, precision)