import os
from datetime import datetime
import asyncio
import numpy as np
from math import sqrt, log1p, prod
from signal_processors.bittensor_processor import BittensorProcessor
import logging

logger = logging.getLogger(__name__)

def filter_positions_by_assets(data, asset_list):
    """Filter positions to include only those with specified assets."""
    filtered_data = {}
    for miner, details in data.items():
        
        if details["thirty_day_returns"] <= 0:
            continue
        
        if details["all_time_returns"] <= 0:
            continue
        
        # count the number of profitable trades for assets that match our asset_list
        profitable_trades = 0
        total_trades = 0
        asset_trades = {}
        latest_trade = 0
        for position in details["positions"]:
            if position["trade_pair"][0] not in asset_list:
                continue
            
            asset_trades[position["trade_pair"][0]] = asset_trades.get(position["trade_pair"][0], 0) + 1
            
            if position["is_closed_position"]:
                return_at_close = position["return_at_close"] - 1
                if return_at_close > 0:
                    profitable_trades += 1
                latest_trade = max(latest_trade, position["close_ms"])
                total_trades += 1
        
        # if there are less than 20 trades for any asset in the asset_list, skip this miner
        for asset in asset_list:
            if asset_trades.get(asset, 0) < 20:
                continue
        
        if total_trades == 0 or profitable_trades / total_trades <= 0.90:
            continue
        
        # if the latest trade was more than 15 days ago, skip this miner
        if latest_trade < datetime.now().timestamp() * 1000 - 15 * 24 * 60 * 60 * 1000:
            continue
        
        filtered_positions = [
            pos for pos in details["positions"]
            if pos["trade_pair"][0] in asset_list
        ]
        if filtered_positions:
            filtered_data[miner] = {**details, "positions": filtered_positions}
    return filtered_data

def normalize_metric(name, value, min_value, max_value):
    """Normalize a metric to a 0-1 scale."""
    if max_value - min_value == 0:
        return 0
    normalized = (value - min_value) / (max_value - min_value)
    #print(f"Normalizing '{name}', Value: {value}, Min: {min_value}, Max: {max_value}, Normalized: {normalized}")
    return normalized

def calculate_sharpe_ratio(position_returns):
    """Calculate the Sharpe Ratio for a series of returns."""
    if len(position_returns) < 2:
        return 0  # Not enough data to calculate Sharpe Ratio
    returns = np.array(position_returns)
    mean_return = np.mean(returns)
    std_return = np.std(returns)
    return mean_return / std_return if std_return != 0 else 0

def calculate_max_drawdown_from_orders(orders):
    """
    Calculate max drawdown for a position considering leverage and price changes across orders,
    accounting for both long and short positions.
    """
    cumulative_leverage = 0  # Cumulative leverage
    weighted_sum_price = 0  # Sum of leverage-weighted prices for averaging
    max_drawdown = 0  # Track the maximum drawdown
    current_price = None

    for order in orders:
        if not isinstance(order, dict):
            raise ValueError("Each order must be a dictionary")

        price = order.get("price", 0)
        leverage = order.get("leverage", 0)

        if leverage == 0 or price == 0:
            continue  # Skip invalid or zero-leverage orders

        # Update cumulative leverage and average price
        cumulative_leverage += leverage
        if cumulative_leverage == 0:
            continue
        weighted_sum_price += leverage * price
        average_price = weighted_sum_price / cumulative_leverage

        # Update current price for drawdown calculation
        current_price = price

        # Calculate the drawdown relative to the average entry price
        if cumulative_leverage > 0:  # Long position
            drawdown = (current_price - average_price) / average_price
        else:  # Short position
            drawdown = (average_price - current_price) / average_price

        max_drawdown = min(max_drawdown, drawdown)  # Track the deepest drawdown

    return max_drawdown

def calculate_max_drawdown_from_positions(positions):
    """Calculate the largest max drawdown from all positions."""
    max_drawdown = 0
    for position in positions:
        orders = position.get("orders", [])
        drawdown = calculate_max_drawdown_from_orders(orders)
        max_drawdown = min(max_drawdown, drawdown)  # Looking for the lowest value
    return max_drawdown

def get_trade_consistency_score(miner):
    """Calculate consistency based on the standard deviation of trade intervals."""
    positions = sorted(miner['positions'], key=lambda pos: pos['open_ms'])
    if len(positions) < 2:
        return 0  # Insufficient data

    intervals = [
        positions[i]['open_ms'] - positions[i - 1]['close_ms']
        for i in range(1, len(positions))
    ]
    
    # Calculate the standard deviation and mean of intervals
    mean_interval = sum(intervals) / len(intervals)
    std_interval = sqrt(sum((x - mean_interval) ** 2 for x in intervals) / len(intervals))
    
    # Normalize the score by comparing std_interval with mean_interval
    return 1 - (std_interval / mean_interval if mean_interval != 0 else 0)

def get_position_count_score(n_positions, max_positions):
    """Calculate position count score using logarithmic scaling."""
    return np.log1p(n_positions) / np.log1p(max_positions)

def calculate_miner_scores(data):
    # Collect all metrics for normalization
    all_time_returns_list = []
    thirty_day_returns_list = []
    percentage_profitable_list = []
    asset_returns_list = []
    sharpe_ratios = []
    max_drawdowns = []
    consistency_scores = []
    position_counts = []

    # Precompute max active days for experience score
    active_days_list = []
    for miner in data.values():
        if miner['positions']:
            first_trade = min(position['open_ms'] for position in miner['positions'])
            last_trade = max(
                position['close_ms'] if position['is_closed_position'] else datetime.now().timestamp() * 1000
                for position in miner['positions']
            )
            active_days = (last_trade - first_trade) / (1000 * 60 * 60 * 24)
            active_days_list.append(active_days)
        else:
            active_days_list.append(0)
    max_active_days = max(active_days_list, default=1)

    # Calculate additional metrics for each miner
    for idx, miner in enumerate(data.values()):
        #hotkey = list(data.keys())[idx]
        
        position_returns = []
        profitable_trades = 0
        total_trades = 0
        asset_returns = 0.0

        # Calculate the miner's maximum drawdown from positions
        miner_max_drawdown = calculate_max_drawdown_from_positions(miner["positions"]) + 1
        # get the hotkey of the miner
        #print(f"Miner {hotkey} max drawdown: {miner_max_drawdown}")

        for position in miner["positions"]:
            # Determine profitability for each position
            if position["is_closed_position"]:
                return_at_close = position["return_at_close"] - 1
                position_returns.append(return_at_close)
                asset_returns += return_at_close
                if return_at_close > 0:
                    profitable_trades += 1
            else:
                current_return = position["current_return"] - 1
                position_returns.append(current_return)
                asset_returns += current_return
                if current_return > 0:
                    profitable_trades += 1
            total_trades += 1

        # Collect metrics for normalization
        if position_returns:
            all_time_returns_list.append(miner["all_time_returns"] - 1)
            thirty_day_returns_list.append(miner["thirty_day_returns"] - 1)
            percentage_profitable_list.append(profitable_trades / total_trades if total_trades > 0 else 0)
            asset_returns_list.append(asset_returns)
            sharpe_ratios.append(calculate_sharpe_ratio(position_returns))
            max_drawdowns.append(miner_max_drawdown)  # Use the miner's maximum drawdown
            position_counts.append(total_trades)
            consistency_scores.append(get_trade_consistency_score(miner))
        else:
            # Append neutral/default values for miners without relevant positions
            all_time_returns_list.append(0)
            thirty_day_returns_list.append(0)
            percentage_profitable_list.append(0)
            asset_returns_list.append(0)
            sharpe_ratios.append(0)
            max_drawdowns.append(0)
            position_counts.append(0)
            consistency_scores.append(0)

    # Normalize metrics
    normalized_metrics = []
    for idx, miner in enumerate(data.values()):
        total_score = 0
        if miner["positions"]:  # Only calculate scores if there are relevant positions
            max_drawdown = normalize_metric(
                "max_drawdown", max_drawdowns[idx], min(max_drawdowns), max(max_drawdowns)
            )
            thirty_day_returns = normalize_metric(
                "thirty_day_returns", thirty_day_returns_list[idx], min(thirty_day_returns_list), max(thirty_day_returns_list)
            )
            sharpe_ratio = normalize_metric(
                "sharpe_ratio", sharpe_ratios[idx], min(sharpe_ratios), max(sharpe_ratios)
            )
            percentage_profitable = normalize_metric(
                "percentage_profitable", percentage_profitable_list[idx], min(percentage_profitable_list), max(percentage_profitable_list)
            )
            asset_returns = normalize_metric(
                "asset_returns", asset_returns_list[idx], min(asset_returns_list), max(asset_returns_list)
            )
            consistency_score = normalize_metric(
                "consistency_score", consistency_scores[idx], min(consistency_scores), max(consistency_scores)
            )
            position_count_score = get_position_count_score(
                position_counts[idx], max(position_counts)
            )

            total_score = (
                max_drawdown**5 +
                sharpe_ratio**3 +
                thirty_day_returns**3 +
                asset_returns**2 +
                percentage_profitable**2 +
                position_count_score**2 +
                consistency_score**2
            )

        normalized_metrics.append({
            "hotkey": list(data.keys())[idx],
            "total_score": float(total_score),
            "max_drawdown": float(max_drawdown),
            "sharpe_ratio": float(sharpe_ratio),
            "thirty_day_returns": float(thirty_day_returns),
            "asset_returns": float(asset_returns),
            "percentage_profitable": float(percentage_profitable),
            "position_count_score": float(position_count_score),
            "consistency_score": float(consistency_score),
        })

    # Rank miners by total score
    return sorted(normalized_metrics, key=lambda x: x["total_score"], reverse=True)

# make a function that stores the number of keys to a cache file in the same directory as where the fetch_bittensor_signals() stores the data
def store_key_count(current_key_count, path):
    with open(path, 'w') as f:
        f.write(str(current_key_count))
        
# now make a function that fetches the number of keys from the cache file
def fetch_key_count(path):
    
    # if the file does not exist return a -9
    if not os.path.exists(path):
        return -1
    with open(path, 'r') as f:
        return int(f.read())
    
async def get_ranked_miners(assets_to_trade=None):
    """
    Fetch ranked miners and display the results along with their ranks.
    """
    processor = BittensorProcessor(enabled=True)
    positions_data = await processor._fetch_raw_signals()
    if positions_data is None:
        logger.error("Failed to fetch miner data")
        return None, None
    
    # establish the key count cache file path
    miner_count_cache_filename = "miner_count_cache.txt"
    miner_count_cache_path = os.path.join(BittensorProcessor.RAW_SIGNALS_DIR, miner_count_cache_filename)
    
    # fetch the previous key count
    previous_key_count = fetch_key_count(miner_count_cache_path)
    # if the current is not within a tolerance of the previous, raise an error
    current_key_count = len(positions_data)
    if previous_key_count >= 0 and (current_key_count <= 50 or abs(current_key_count - previous_key_count) > 10):
        raise ValueError("The number of keys fetched is not within the expected tolerance.")
    # store the current key count
    store_key_count(current_key_count, miner_count_cache_path)
    

    rankings, ranked_miners = rank_miners(positions_data, assets_to_trade)

    # Display the rankings and top miners
    print("Miner Rankings:")
    for hotkey, rank in rankings.items():
        print(f"{rank}: {hotkey}")

    print("\nTop Miners by Score:")
    for miner in ranked_miners[:10]:
        print(miner)

def rank_miners(positions_data, assets_to_trade=None):
    """
    Rank miners by their total score and return a dictionary of hotkeys to ranks.
    """
    # Filter by assets
    if assets_to_trade:
        positions_data = filter_positions_by_assets(positions_data, assets_to_trade)
    
    # Calculate scores and sort miners
    ranked_miners = calculate_miner_scores(positions_data)

    # Build a dictionary mapping hotkeys to ranks
    rankings = {miner['hotkey']: rank + 1 for rank, miner in enumerate(ranked_miners)}

    return rankings, ranked_miners  # Return both the ranking and detailed scores    


if __name__ == '__main__':
    assets_to_trade = ["BTCUSD", "ETHUSD"]  # Specify the assets you want to include
    rankings, ranked_miners = asyncio.run(get_ranked_miners(assets_to_trade))
    if rankings is None:
        print("Failed to get rankings")
        exit(1)
