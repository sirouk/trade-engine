import os
from datetime import datetime
import asyncio
import numpy as np
from math import sqrt, log1p, prod
from signal_processors.bittensor_processor import fetch_bittensor_signals, load_bittensor_credentials

def normalize_metric(name, value, min_value, max_value):
    """Normalize a metric to a 0-1 scale."""
    if max_value - min_value == 0:
        return 0
    normalized = (value - min_value) / (max_value - min_value)
    print(f"Normalizing '{name}', Value: {value}, Min: {min_value}, Max: {max_value}, Normalized: {normalized}")
    return normalized

def calculate_sharpe_ratio(position_returns):
    """Calculate the Sharpe Ratio for a series of returns."""
    if len(position_returns) < 2:
        return 0  # Not enough data to calculate Sharpe Ratio
    returns = np.array(position_returns)
    mean_return = np.mean(returns)
    std_return = np.std(returns)
    return mean_return / std_return if std_return != 0 else 0

def calculate_max_drawdown(position_returns):
    """Calculate the maximum drawdown from a series of cumulative returns."""
    cumulative_returns = np.cumprod(1 + np.array(position_returns))
    drawdowns = cumulative_returns / np.maximum.accumulate(cumulative_returns) - 1
    return np.min(drawdowns)

def get_miner_experience_score(miner, max_active_days):
    """Calculate experience score based on active trading days."""
    if not miner['positions']:
        return 0
    first_trade = min(position['open_ms'] for position in miner['positions'])
    last_trade = max(position['close_ms'] if position['is_closed_position'] else datetime.now().timestamp() * 1000 for position in miner['positions'])
    active_days = (last_trade - first_trade) / (1000 * 60 * 60 * 24)
    return active_days / max_active_days if max_active_days != 0 else 0

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
    all_time_returns_list = [miner['all_time_returns'] for miner in data.values()]

    thirty_day_returns_list = [miner['thirty_day_returns']-1 for miner in data.values()]
    # for key, miner in data.items():
    #     if key == '5HYRAnpjhcT45f6udFAbfJXwUmqqeaNvte4sTjuQvDxTaQB3':
    #         profitability = miner.get('thirty_day_returns', 'Not available')  # Use 'get' to avoid KeyError if 'profitability' doesn't exist
    #         print(profitability)
    #         quit()

            
    profitability_list = [miner['percentage_profitable'] for miner in data.values()]
    sharpe_ratios = []
    max_drawdowns = []
    experience_scores = []
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

        # Prepare returns for risk-adjusted calculations
        position_returns = []
        for position in miner['positions']:
            if position['is_closed_position']:
                # Convert return_at_close to percentage return
                position_returns.append(position['return_at_close'] - 1)
            else:
                # Use current return for open positions
                position_returns.append(position['current_return'] - 1)

        # Calculate Sharpe Ratio
        sharpe_ratio = calculate_sharpe_ratio(position_returns)
        sharpe_ratios.append(sharpe_ratio)

        # Calculate Max Drawdown
        max_drawdown = calculate_max_drawdown(position_returns)
        max_drawdowns.append(max_drawdown)

        # Experience Score
        experience_score = active_days_list[idx] / max_active_days if max_active_days != 0 else 0
        experience_scores.append(experience_score)

        # Trade Consistency Score
        consistency_score = get_trade_consistency_score(miner)
        consistency_scores.append(consistency_score)

        # Position Count
        position_counts.append(len(miner['positions']))


    # Normalize metrics
    normalized_metrics = []
    for idx, miner in enumerate(data.values()):
        all_time_returns = normalize_metric(
            'all_time_returns', miner['all_time_returns'], min(all_time_returns_list), max(all_time_returns_list)
        )
        thirty_day_returns = normalize_metric(
            'thirty_day_returns', miner['thirty_day_returns']-1, min(thirty_day_returns_list), max(thirty_day_returns_list)
        )
        profitability = normalize_metric(
            'profitability', miner['percentage_profitable'], min(profitability_list), max(profitability_list)
        )
        sharpe_ratio = normalize_metric(
            'sharpe_ratio', sharpe_ratios[idx], min(sharpe_ratios), max(sharpe_ratios)
        )
        # Since lower max drawdown is better, we invert and normalize it
        max_drawdown = normalize_metric(
            'max_drawdown', max_drawdowns[idx], min(max_drawdowns), max(max_drawdowns)
        )
        consistency_score = normalize_metric(
            'consistency_score', consistency_scores[idx], min(consistency_scores), max(consistency_scores)
        )
        position_count_score = get_position_count_score(
            len(miner['positions']), max(position_counts)
        )
        experience_score = experience_scores[idx]**2

        # # Weighted score calculation with adjusted weights
        # total_score = (
        #     0.20 * max_drawdown +  # Since lower drawdown is better
        #     0.20 * thirty_day_returns +
        #     0.15 * sharpe_ratio +
        #     0.15 * consistency_score +
        #     0.15 * profitability +
        #     0.05 * experience_score +
        #     0.05 * all_time_returns +
        #     0.05 * position_count_score            
        # )
        
        total_score = (
            all_time_returns
            *
            thirty_day_returns**5
            *
            profitability**3
            *
            sharpe_ratio**2
            *
            max_drawdown**4
            *
            consistency_score**3
            *
            position_count_score**2 
            *
            experience_score**3
        )
        
        normalized_metrics.append({
            "hotkey": list(data.keys())[idx],
            "total_score": float(total_score),
            "profitability": float(profitability),
            "thirty_day_returns": float(thirty_day_returns),
            "all_time_returns": float(all_time_returns),
            "max_drawdown": float(max_drawdown),
            "experience_score": float(experience_score),
            "consistency_score": float(consistency_score),
            "sharpe_ratio": float(sharpe_ratio),
            "position_count_score": float(position_count_score),
            "n_positions": len(miner['positions'])
        })

    # Rank miners by total score
    return sorted(normalized_metrics, key=lambda x: x['total_score'], reverse=True)

async def get_ranked_signals():
    credentials = load_bittensor_credentials()
    api_key = credentials.bittensor_sn8.api_key
    endpoint = credentials.bittensor_sn8.endpoint

    positions_data = await fetch_bittensor_signals(api_key, endpoint)
    ranked_miners = calculate_miner_scores(positions_data)

    # Display top miners by score
    for miner in ranked_miners[:10]:
        print(miner)

if __name__ == '__main__':
    asyncio.run(get_ranked_signals())
