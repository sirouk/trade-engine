import os
from datetime import datetime
import asyncio
import numpy as np
from math import sqrt
from signal_processors.bittensor_processor import BittensorProcessor
import logging

logger = logging.getLogger(__name__)

class MinerRankingConfig:
    # Filtering thresholds
    MIN_TRADES = 10                    # Minimum number of trades required
    MAX_DRAWDOWN_THRESHOLD = -0.5      # Maximum allowed drawdown (-0.5 = -50%)
    MIN_PROFITABLE_RATE = 0.6          # Minimum rate of profitable trades (60%)
    MIN_TOTAL_RETURN = 0.0             # Minimum total return (0 = breakeven)
    
    # Scoring weights
    DRAWDOWN_EXPONENT = 6              # Exponent for drawdown penalty
    SHARPE_EXPONENT = 2                # Exponent for Sharpe ratio
    PROFITABLE_RATE_EXPONENT = 5       # Exponent for profitable trade rate
    POSITION_COUNT_DIVISOR = 5         # Divisor for position count bonus (1/5 = max 20% bonus)
    
    # Asset filtering
    MIN_TRADES_PER_ASSET = 0           # Minimum trades required per asset
    MAX_TRADE_AGE_DAYS = 14            # Maximum age of latest trade in days # was: float('inf')

class MinerRanking:
    def __init__(self, config=None):
        self.config = config or MinerRankingConfig()
        self.processor = BittensorProcessor(enabled=True)
        self.miner_count_cache_filename = "miner_count_cache.txt"
        self.miner_count_cache_path = os.path.join(BittensorProcessor.RAW_SIGNALS_DIR, self.miner_count_cache_filename)
    
    def filter_positions_by_assets(self, data, asset_list):
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
            
            # Check minimum trades per asset if configured
            if self.config.MIN_TRADES_PER_ASSET > 0:
                skip = False
                for asset in asset_list:
                    if asset_trades.get(asset, 0) < self.config.MIN_TRADES_PER_ASSET:
                        skip = True
                        break
                if skip:
                    continue
            
            # Check trade age if configured
            if self.config.MAX_TRADE_AGE_DAYS < float('inf'):
                if latest_trade < datetime.now().timestamp() * 1000 - self.config.MAX_TRADE_AGE_DAYS * 24 * 60 * 60 * 1000:
                    continue
            
            filtered_positions = [
                pos for pos in details["positions"]
                if pos["trade_pair"][0] in asset_list
            ]
            if filtered_positions:
                filtered_data[miner] = {**details, "positions": filtered_positions}
        return filtered_data

    def calculate_miner_scores(self, data):
        """Calculate scores for each miner based on their trading performance."""
        metrics_data = []
        
        for hotkey, miner in data.items():
            if not miner['positions']:
                continue
                
            position_returns = []
            profitable_trades = 0
            total_trades = 0
            
            # Calculate max drawdown from filtered positions
            max_drawdown = self.calculate_max_drawdown_from_positions(miner['positions'])
            
            # Skip miners with extreme drawdowns
            if max_drawdown < self.config.MAX_DRAWDOWN_THRESHOLD:
                continue
            
            # Process each position for returns and profitability
            for position in miner['positions']:
                if position['is_closed_position']:
                    return_at_close = position['return_at_close'] - 1
                    position_returns.append(return_at_close)
                    if return_at_close > 0:
                        profitable_trades += 1
                else:
                    current_return = position['current_return'] - 1
                    position_returns.append(current_return)
                    if current_return > 0:
                        profitable_trades += 1
                total_trades += 1
            
            # Apply minimum trade requirement
            if total_trades < self.config.MIN_TRADES:
                continue
                
            percentage_profitable = profitable_trades / total_trades
            if percentage_profitable < self.config.MIN_PROFITABLE_RATE:
                continue
                
            # Calculate metrics
            sharpe_ratio = self.calculate_sharpe_ratio(position_returns)
            consistency_score = self.get_trade_consistency_score(miner)
            position_count = total_trades
            total_return = sum(position_returns)
            
            # Skip if below minimum return
            if total_return <= self.config.MIN_TOTAL_RETURN:
                continue
            
            metrics_data.append({
                'hotkey': hotkey,
                'metrics': {
                    'max_drawdown': max_drawdown,
                    'sharpe_ratio': sharpe_ratio,
                    'total_return': total_return,
                    'percentage_profitable': percentage_profitable,
                    'position_count': position_count,
                    'consistency_score': consistency_score
                }
            })
        
        if not metrics_data:
            return []
        
        # Calculate percentile ranks for metrics that should be normalized
        all_metrics = [m['metrics'] for m in metrics_data]
        sharpe_percentiles = self.normalize_to_percentile([m['sharpe_ratio'] for m in all_metrics])
        position_count_percentiles = self.normalize_to_percentile([m['position_count'] for m in all_metrics])
        consistency_percentiles = self.normalize_to_percentile([m['consistency_score'] for m in all_metrics])
        
        # Create normalized scores
        normalized_metrics = []
        for idx, miner_data in enumerate(metrics_data):
            metrics = miner_data['metrics']
            
            # Convert drawdown to positive score and apply penalty
            drawdown_score = 1.0 + metrics['max_drawdown']
            drawdown_score = drawdown_score ** 2
            
            # Convert total return to absolute value
            return_score = 1.0 + metrics['total_return']
            
            # Calculate position count bonus
            position_count_bonus = np.log1p(metrics['position_count']) / self.config.POSITION_COUNT_DIVISOR
            
            normalized = {
                'hotkey': miner_data['hotkey'],
                'max_drawdown': float(drawdown_score),
                'total_return': float(return_score),
                'sharpe_ratio': float(sharpe_percentiles[idx]),
                'percentage_profitable': float(metrics['percentage_profitable']),  # Use actual percentage instead of percentile
                'position_count': float(position_count_percentiles[idx]),
                'consistency_score': float(consistency_percentiles[idx])
            }
            
            # Calculate total score with configured weights
            # For percentage_profitable, we'll use the actual percentage (as decimal) for scoring
            normalized['total_score'] = float(
                normalized['max_drawdown']**self.config.DRAWDOWN_EXPONENT +
                normalized['sharpe_ratio']**self.config.SHARPE_EXPONENT +
                normalized['total_return'] +
                normalized['percentage_profitable']**self.config.PROFITABLE_RATE_EXPONENT +
                normalized['position_count'] * position_count_bonus +
                normalized['consistency_score']
            )
            
            normalized_metrics.append(normalized)
        
        return sorted(normalized_metrics, key=lambda x: x['total_score'], reverse=True)

    def rank_miners(self, positions_data, assets_to_trade=None):
        """Rank miners by their total score."""
        # Filter by assets
        if assets_to_trade:
            positions_data = self.filter_positions_by_assets(positions_data, assets_to_trade)
        
        # Calculate scores and sort miners
        ranked_miners = self.calculate_miner_scores(positions_data)
        
        # Build rankings dictionary
        rankings = {miner['hotkey']: rank + 1 for rank, miner in enumerate(ranked_miners)}
        
        return rankings, ranked_miners

    def normalize_metric(self, name, value, min_value, max_value):
        """Normalize a metric to a 0-1 scale."""
        if max_value - min_value == 0:
            return 0
        normalized = (value - min_value) / (max_value - min_value)
        return normalized

    def calculate_sharpe_ratio(self, position_returns):
        """Calculate the Sharpe Ratio for a series of returns."""
        if len(position_returns) < 2:
            return 0
        returns = np.array(position_returns)
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        return mean_return / std_return if std_return != 0 else 0

    def calculate_max_drawdown_from_orders(self, orders):
        """Calculate max drawdown for a position considering leverage and price changes."""
        cumulative_leverage = 0
        weighted_sum_price = 0
        max_drawdown = 0
        current_price = None

        for order in orders:
            if not isinstance(order, dict):
                raise ValueError("Each order must be a dictionary")

            price = order.get("price", 0)
            leverage = order.get("leverage", 0)

            if leverage == 0 or price == 0:
                continue

            cumulative_leverage += leverage
            if cumulative_leverage == 0:
                continue
            
            weighted_sum_price += leverage * price
            average_price = weighted_sum_price / cumulative_leverage
            current_price = price

            if cumulative_leverage > 0:  # Long position
                price_drawdown = (current_price - average_price) / average_price
                account_drawdown = price_drawdown * abs(cumulative_leverage)
            else:  # Short position
                price_drawdown = (average_price - current_price) / average_price
                account_drawdown = price_drawdown * abs(cumulative_leverage)

            max_drawdown = min(max_drawdown, -abs(account_drawdown))

        return max_drawdown

    def calculate_max_drawdown_from_positions(self, positions):
        """Calculate the largest max drawdown from all positions."""
        max_drawdown = 0
        for position in positions:
            orders = position.get("orders", [])
            drawdown = self.calculate_max_drawdown_from_orders(orders)
            max_drawdown = min(max_drawdown, drawdown)
        return max_drawdown

    def get_trade_consistency_score(self, miner):
        """Calculate consistency based on the standard deviation of trade intervals."""
        positions = sorted(miner['positions'], key=lambda pos: pos['open_ms'])
        if len(positions) < 2:
            return 0

        intervals = [
            positions[i]['open_ms'] - positions[i - 1]['close_ms']
            for i in range(1, len(positions))
        ]
        
        mean_interval = sum(intervals) / len(intervals)
        std_interval = sqrt(sum((x - mean_interval) ** 2 for x in intervals) / len(intervals))
        
        return 1 - (std_interval / mean_interval if mean_interval != 0 else 0)

    def get_position_count_score(self, n_positions, max_positions):
        """Calculate position count score using logarithmic scaling."""
        return np.log1p(n_positions) / np.log1p(max_positions)

    def normalize_to_percentile(self, values, reverse=False):
        """Normalize values to percentile ranks (0-1)."""
        if not values:
            return []
        
        sorted_with_idx = sorted(enumerate(values), key=lambda x: x[1], reverse=not reverse)
        n = len(sorted_with_idx)
        
        ranks = [0] * n
        for rank, (idx, _) in enumerate(sorted_with_idx):
            ranks[idx] = 1.0 - (rank / (n - 1) if n > 1 else 0)
        
        return ranks

    def calculate_asset_metrics(self, positions, asset):
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
        
        total_entries = sum(len(p.get("orders", [])) for p in asset_positions)
        avg_entries = total_entries / total_trades if total_trades > 0 else 0
        
        max_drawdown = self.calculate_max_drawdown_from_positions(asset_positions)
        
        return {
            "total_trades": total_trades,
            "total_return": total_return,
            "avg_entries": avg_entries,
            "max_drawdown": max_drawdown
        }

    def format_miner_results(self, ranked_miners, positions_data, assets_to_trade):
        """Format miner results in a clean, readable way."""
        formatted_results = []
        
        for miner in ranked_miners:
            hotkey = miner['hotkey']
            scores = {
                'total_score': miner['total_score'],
                'sharpe_ratio': miner['sharpe_ratio'],
                'percentage_profitable': miner['percentage_profitable'] * 100,  # Convert to percentage
                'consistency_score': miner['consistency_score']
            }
            
            asset_metrics = {}
            for asset in assets_to_trade:
                positions = [p for p in positions_data[hotkey]['positions'] if p["trade_pair"][0] == asset]
                metrics = self.calculate_asset_metrics(positions, asset)
                if metrics:
                    # Calculate per-asset profitable trade percentage
                    profitable_trades = sum(
                        1 for p in positions 
                        if (p["is_closed_position"] and p["return_at_close"] > 1) or 
                           (not p["is_closed_position"] and p["current_return"] > 1)
                    )
                    metrics["profitable_percentage"] = (profitable_trades / len(positions)) * 100 if positions else 0
                    asset_metrics[asset] = metrics
            
            formatted_results.append({
                'hotkey': hotkey,
                'scores': scores,
                'asset_metrics': asset_metrics
            })
        
        return formatted_results

    def display_ranked_miners(self, formatted_results):
        """Display the formatted results in a clean, readable way."""
        for rank, result in enumerate(formatted_results, 1):
            print("\n" + "="*80)
            print(f"Rank #{rank} - Miner: {result['hotkey']}")
            print("-"*80)
            
            scores = result['scores']
            print("Overall Scores:")
            print(f"  Total Score: {scores['total_score']:.4f}")
            print(f"  Sharpe Ratio Rank: {scores['sharpe_ratio']:.4f}")
            print(f"  Trade Profitability: {scores['percentage_profitable']:.2f}%")
            print(f"  Consistency Score: {scores['consistency_score']:.4f}")
            
            print("\nPer-Asset Metrics:")
            for asset, metrics in result['asset_metrics'].items():
                print(f"\n  {asset}:")
                print(f"    Trades: {metrics['total_trades']}")
                print(f"    Profitable: {metrics['profitable_percentage']:.2f}%")
                print(f"    Max Drawdown: {(1 + metrics['max_drawdown'])*100:.2f}%")
                print(f"    Avg Entries/Position: {metrics['avg_entries']:.2f}")
                print(f"    Total Return: {(1 + metrics['total_return'])*100:.2f}%")

    def store_key_count(self, current_key_count):
        """Store the number of keys to a cache file."""
        with open(self.miner_count_cache_path, 'w', encoding='utf-8') as f:
            f.write(str(current_key_count))
        
    def fetch_key_count(self):
        """Fetch the number of keys from the cache file."""
        if not os.path.exists(self.miner_count_cache_path):
            return -1
        with open(self.miner_count_cache_path, 'r', encoding='utf-8') as f:
            return int(f.read())

    async def get_ranked_miners(self, assets_to_trade=None):
        """Fetch and rank miners."""
        positions_data = await self.processor._fetch_raw_signals()
        if positions_data is None:
            logger.error("Failed to fetch miner data")
            return None, None
        
        # Check key count
        previous_key_count = self.fetch_key_count()
        current_key_count = len(positions_data)
        if previous_key_count >= 0 and (current_key_count <= 50 or abs(current_key_count - previous_key_count) > 10):
            raise ValueError("The number of keys fetched is not within the expected tolerance.")
        self.store_key_count(current_key_count)
        
        # Calculate rankings
        rankings, ranked_miners = self.rank_miners(positions_data, assets_to_trade)
        
        # Format and display results
        formatted_results = self.format_miner_results(ranked_miners, positions_data, assets_to_trade)
        self.display_ranked_miners(formatted_results)
        
        return rankings, ranked_miners

if __name__ == '__main__':
    # Use the keys from CORE_ASSET_MAPPING
    assets_to_trade = list(BittensorProcessor.CORE_ASSET_MAPPING.keys())  # ["BTCUSD", "ETHUSD", "ADAUSD"]
    ranker = MinerRanking()
    rankings, ranked_miners = asyncio.run(ranker.get_ranked_miners(assets_to_trade))
    if rankings is None:
        print("Failed to get rankings")
        exit(1)