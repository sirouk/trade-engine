import os
from datetime import datetime
import asyncio
import numpy as np
from math import sqrt
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
        #for asset in asset_list:
        #    if asset_trades.get(asset, 0) < 20:
        #        continue
        
        #if total_trades == 0 or profitable_trades / total_trades <= 0.90:
        #    continue
        
        # if the latest trade was more than 15 days ago, skip this miner
        #if latest_trade < datetime.now().timestamp() * 1000 - 15 * 24 * 60 * 60 * 1000:
        #    continue
        
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
    
    The drawdown is calculated as a percentage of the total account value, considering:
    1. The amount of account utilized (leverage)
    2. The price movement relative to the average entry price
    3. Sequential impact of adding to positions
    
    Returns a negative value representing the maximum drawdown percentage.
    """
    cumulative_leverage = 0  # Cumulative leverage (represents account utilization)
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
        # and multiply by account utilization (cumulative_leverage)
        if cumulative_leverage > 0:  # Long position
            price_drawdown = (current_price - average_price) / average_price
            account_drawdown = price_drawdown * abs(cumulative_leverage)
        else:  # Short position
            price_drawdown = (average_price - current_price) / average_price
            account_drawdown = price_drawdown * abs(cumulative_leverage)

        # Store as negative value since it's a drawdown
        max_drawdown = min(max_drawdown, -abs(account_drawdown))  # Track the deepest drawdown

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

def normalize_to_percentile(values, reverse=False):
    """
    Normalize values to percentile ranks (0-1), where 1.0 is the best performer.
    If reverse=True, lower values are considered better.
    """
    if not values:
        return []
    
    # Sort values and assign ranks
    sorted_with_idx = sorted(enumerate(values), key=lambda x: x[1], reverse=not reverse)
    n = len(sorted_with_idx)
    
    # Create percentile ranks (1.0 for best performer)
    ranks = [0] * n
    for rank, (idx, _) in enumerate(sorted_with_idx):
        ranks[idx] = 1.0 - (rank / (n - 1) if n > 1 else 0)
    
    return ranks

def calculate_miner_scores(data):
    """
    Calculate scores for each miner based on their trading performance.
    Only considers trades for the specified assets in the filtered data.
    """
    metrics_data = []
    
    for hotkey, miner in data.items():
        if not miner['positions']:
            continue
            
        position_returns = []
        profitable_trades = 0
        total_trades = 0
        
        # Calculate max drawdown from filtered positions
        max_drawdown = calculate_max_drawdown_from_positions(miner['positions'])
        
        # Process each position for returns and profitability
        for position in miner['positions']:
            if position['is_closed_position']:
                return_at_close = position['return_at_close'] - 1  # Convert to percentage
                position_returns.append(return_at_close)
                if return_at_close > 0:
                    profitable_trades += 1
            else:
                current_return = position['current_return'] - 1  # Convert to percentage
                position_returns.append(current_return)
                if current_return > 0:
                    profitable_trades += 1
            total_trades += 1
        
        if total_trades == 0:
            continue
            
        # Calculate metrics
        percentage_profitable = profitable_trades / total_trades
        sharpe_ratio = calculate_sharpe_ratio(position_returns)
        consistency_score = get_trade_consistency_score(miner)
        position_count = total_trades
        total_return = sum(position_returns)  # Total return as percentage
        
        metrics_data.append({
            'hotkey': hotkey,
            'metrics': {
                'max_drawdown': max_drawdown,  # Already as percentage
                'sharpe_ratio': sharpe_ratio,
                'total_return': total_return,  # As percentage
                'percentage_profitable': percentage_profitable,
                'position_count': position_count,
                'consistency_score': consistency_score
            }
        })
    
    if not metrics_data:
        return []
    
    # Collect values for percentile ranking
    all_metrics = [m['metrics'] for m in metrics_data]
    sharpe_ratios = [m['sharpe_ratio'] for m in all_metrics]
    profitable_percentages = [m['percentage_profitable'] for m in all_metrics]
    position_counts = [m['position_count'] for m in all_metrics]
    consistency_scores = [m['consistency_score'] for m in all_metrics]
    
    # Calculate percentile ranks
    sharpe_percentiles = normalize_to_percentile(sharpe_ratios)
    profitable_percentiles = normalize_to_percentile(profitable_percentages)
    position_count_percentiles = normalize_to_percentile(position_counts)
    consistency_percentiles = normalize_to_percentile(consistency_scores)
    
    # Create normalized scores
    normalized_metrics = []
    for idx, miner_data in enumerate(metrics_data):
        metrics = miner_data['metrics']
        
        # Convert drawdown to positive score (e.g., -0.15 → 0.85)
        drawdown_score = 1.0 + metrics['max_drawdown']
        
        # Convert total return to absolute value (e.g., 0.15 → 1.15)
        return_score = 1.0 + metrics['total_return']
        
        normalized = {
            'hotkey': miner_data['hotkey'],
            'max_drawdown': float(drawdown_score),
            'total_return': float(return_score),
            'sharpe_ratio': float(sharpe_percentiles[idx]),
            'percentage_profitable': float(profitable_percentiles[idx]),
            'position_count': float(position_count_percentiles[idx]),
            'consistency_score': float(consistency_percentiles[idx])
        }
        
        # Calculate total score with weighted components
        normalized['total_score'] = float(
            normalized['max_drawdown']**5 +
            normalized['sharpe_ratio']**3 +
            normalized['total_return']**2 +
            normalized['percentage_profitable']**2 +
            normalized['position_count']**2 +
            normalized['consistency_score']**2
        )
        
        normalized_metrics.append(normalized)
    
    return sorted(normalized_metrics, key=lambda x: x['total_score'], reverse=True)

# make a function that stores the number of keys to a cache file in the same directory as where the fetch_bittensor_signals() stores the data
def store_key_count(current_key_count, path):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(str(current_key_count))
        
# now make a function that fetches the number of keys from the cache file
def fetch_key_count(path):
    
    # if the file does not exist return a -9
    if not os.path.exists(path):
        return -1
    with open(path, 'r', encoding='utf-8') as f:
        return int(f.read())
    
def calculate_asset_metrics(positions, asset):
    """Calculate metrics for a specific asset from positions."""
    asset_positions = [p for p in positions if p["trade_pair"][0] == asset]
    
    if not asset_positions:
        return None
        
    total_trades = len(asset_positions)
    total_return = sum(
        (p["return_at_close"] - 1) if p["is_closed_position"] 
        else (p["current_return"] - 1) 
        for p in asset_positions
    )
    
    # Calculate average entries per position
    total_entries = sum(len(p.get("orders", [])) for p in asset_positions)
    avg_entries = total_entries / total_trades if total_trades > 0 else 0
    
    # Calculate max drawdown for this asset's positions
    max_drawdown = calculate_max_drawdown_from_positions(asset_positions)
    
    return {
        "total_trades": total_trades,
        "total_return": total_return,
        "avg_entries": avg_entries,
        "max_drawdown": max_drawdown
    }

def format_miner_results(ranked_miners, positions_data, assets_to_trade):
    """Format miner results in a clean, readable way."""
    formatted_results = []
    
    for miner in ranked_miners:
        hotkey = miner['hotkey']
        scores = {
            'total_score': miner['total_score'],
            'sharpe_ratio': miner['sharpe_ratio'],
            'percentage_profitable': miner['percentage_profitable'],
            'consistency_score': miner['consistency_score']
        }
        
        # Get per-asset metrics
        asset_metrics = {}
        for asset in assets_to_trade:
            metrics = calculate_asset_metrics(
                [p for p in positions_data[hotkey]['positions'] if p["trade_pair"][0] == asset],
                asset
            )
            if metrics:
                asset_metrics[asset] = metrics
        
        formatted_results.append({
            'hotkey': hotkey,
            'scores': scores,
            'asset_metrics': asset_metrics
        })
    
    return formatted_results

def display_ranked_miners(formatted_results):
    """Display the formatted results in a clean, readable way."""
    for rank, result in enumerate(formatted_results, 1):  # Start counting from 1
        print("\n" + "="*80)
        print(f"Rank #{rank} - Miner: {result['hotkey']}")
        print("-"*80)
        
        # Display overall scores
        scores = result['scores']
        print("Overall Scores:")
        print(f"  Total Score: {scores['total_score']:.4f}")
        print(f"  Sharpe Ratio Rank: {scores['sharpe_ratio']:.4f}")
        print(f"  Profitable Trade %: {scores['percentage_profitable']:.4f}")
        print(f"  Consistency Score: {scores['consistency_score']:.4f}")
        
        # Display per-asset metrics
        print("\nPer-Asset Metrics:")
        for asset, metrics in result['asset_metrics'].items():
            print(f"\n  {asset}:")
            print(f"    Trades: {metrics['total_trades']}")
            print(f"    Max Drawdown: {(1 + metrics['max_drawdown'])*100:.2f}%")
            print(f"    Avg Entries/Position: {metrics['avg_entries']:.2f}")
            print(f"    Total Return: {(1 + metrics['total_return'])*100:.2f}%")

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
    
    # Format and display results
    formatted_results = format_miner_results(ranked_miners, positions_data, assets_to_trade)
    display_ranked_miners(formatted_results)
    
    return rankings, ranked_miners

def rank_miners(positions_data, assets_to_trade=None):
    """
    Rank miners by their total score and return a dictionary of hotkeys to ranks.
    """
    # Filter by assets
    if assets_to_trade:
        positions_data = filter_positions_by_assets(positions_data, assets_to_trade)
    
    # Calculate scores and sort miners
    ranked_miners = calculate_miner_scores(positions_data)
    #print(ranked_miners)
    #quit()

    # Build a dictionary mapping hotkeys to ranks
    rankings = {miner['hotkey']: rank + 1 for rank, miner in enumerate(ranked_miners)}

    return rankings, ranked_miners  # Return both the ranking and detailed scores    


if __name__ == '__main__':
    assets_to_trade = ["BTCUSD", "ETHUSD"]  # Specify the assets you want to include
    rankings, ranked_miners = asyncio.run(get_ranked_miners(assets_to_trade))
    if rankings is None:
        print("Failed to get rankings")
        exit(1)
    
    #print(ranked_miners)