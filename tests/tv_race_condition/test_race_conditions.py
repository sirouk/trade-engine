#!/usr/bin/env python3
"""Comprehensive test for TradingView race condition handling.

This script:
1. Creates test signal files with various race conditions
2. Processes them using the actual TradingViewProcessor
3. Analyzes real production signal files (read-only)
4. Demonstrates how the processor handles race conditions
"""

import os
import sys
import shutil
from datetime import datetime, timedelta
import glob

# Add project root directory to path to import the processor
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from signal_processors.tradingview_processor import TradingViewProcessor

class RaceConditionTester:
    def __init__(self):
        self.test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_signals')
        self.project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
        
    def setup_test_environment(self):
        """Create test directory and signal files."""
        # Clean up any existing test directory
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        print("=" * 80)
        print("CREATING TEST SIGNAL FILES")
        print("=" * 80)
        
        # Test file 1: Out-of-order race conditions
        test_file1 = os.path.join(self.test_dir, "trade_requests_2025-06-10.log")
        with open(test_file1, 'w') as f:
            f.write('# Test Case 1: Position followed by flat (wrong order - needs reordering)\n')
            f.write('2025-06-10 10:00:00.100000 {"symbol": "ETHUSDT", "direction": "short", "action": "sell", "leverage": "3", "size": "-100/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0"}\n')
            f.write('2025-06-10 10:00:00.200000 {"symbol": "ETHUSDT", "direction": "flat", "action": "sell", "leverage": "3", "size": "0/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0"}\n')
            
            f.write('\n# Test Case 2: Another out-of-order within 2 seconds\n')
            f.write('2025-06-10 11:30:00.000000 {"symbol": "BTCUSDT", "direction": "long", "action": "buy", "leverage": "5", "size": "75/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0"}\n')
            f.write('2025-06-10 11:30:01.500000 {"symbol": "BTCUSDT", "direction": "flat", "action": "sell", "leverage": "5", "size": "0/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0"}\n')
        
        # Test file 2: Correct order but close timing
        test_file2 = os.path.join(self.test_dir, "trade_requests_2025-06-11.log")
        with open(test_file2, 'w') as f:
            f.write('# Test Case 3: Flat followed by position (correct order)\n')
            f.write('2025-06-11 09:00:00.000000 {"symbol": "ETHUSDT", "direction": "flat", "action": "sell", "leverage": "3", "size": "0/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0"}\n')
            f.write('2025-06-11 09:00:00.400000 {"symbol": "ETHUSDT", "direction": "long", "action": "buy", "leverage": "3", "size": "50/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0"}\n')
            
            f.write('\n# Test Case 4: Another correct order within 3 seconds\n')
            f.write('2025-06-11 14:20:00.000000 {"symbol": "SOLUSDT", "direction": "flat", "action": "sell", "leverage": "2", "size": "0/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0"}\n')
            f.write('2025-06-11 14:20:03.000000 {"symbol": "SOLUSDT", "direction": "short", "action": "sell", "leverage": "2", "size": "-60/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0"}\n')
        
        # Test file 3: No race conditions (normal operation)
        test_file3 = os.path.join(self.test_dir, "trade_requests_2025-06-12.log")
        with open(test_file3, 'w') as f:
            f.write('# Test Case 5: Signals far apart (no race condition)\n')
            f.write('2025-06-12 08:00:00.000000 {"symbol": "ADAUSDT", "direction": "long", "action": "buy", "leverage": "1", "size": "100/100", "priority": "medium", "takeprofit": "0.0", "trailstop": "0.0"}\n')
            f.write('2025-06-12 12:00:00.000000 {"symbol": "ADAUSDT", "direction": "flat", "action": "sell", "leverage": "1", "size": "0/100", "priority": "medium", "takeprofit": "0.0", "trailstop": "0.0"}\n')
            
            f.write('\n# Test Case 6: Direct position change (no flat between)\n')
            f.write('2025-06-12 15:00:00.000000 {"symbol": "DOTUSDT", "direction": "long", "action": "buy", "leverage": "3", "size": "50/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0"}\n')
            f.write('2025-06-12 15:00:02.000000 {"symbol": "DOTUSDT", "direction": "short", "action": "sell", "leverage": "3", "size": "-50/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0"}\n')
        
        print(f"\nCreated test files in: {self.test_dir}")
        print(f"  - trade_requests_2025-06-10.log (2 out-of-order race conditions)")
        print(f"  - trade_requests_2025-06-11.log (2 correct order race conditions)")
        print(f"  - trade_requests_2025-06-12.log (no race conditions)")
        
    def process_test_signals(self):
        """Process test signals using the actual TradingViewProcessor."""
        print("\n" + "=" * 80)
        print("PROCESSING TEST SIGNALS")
        print("=" * 80)
        
        # Create a processor instance
        processor = TradingViewProcessor()
        processor.verbose = True
        
        # Temporarily change the signals directory to our test directory
        original_dir = processor.RAW_SIGNALS_DIR
        processor.RAW_SIGNALS_DIR = self.test_dir
        
        try:
            # Process the test signals
            signals = processor.fetch_signals()
            
            print("\n" + "=" * 80)
            print("PROCESSED TEST RESULTS")
            print("=" * 80)
            
            for symbol, signal_data in sorted(signals.items()):
                print(f"\n{symbol}:")
                print(f"  Direction: {'LONG' if signal_data['depth'] > 0 else 'SHORT' if signal_data['depth'] < 0 else 'FLAT'}")
                print(f"  Depth: {signal_data['depth']}")
                print(f"  Timestamp: {signal_data['timestamp']}")
                print(f"  Audit:")
                print(f"    Original Timestamp: {signal_data['audit']['original_timestamp']}")
                print(f"    Adjusted: {signal_data['audit']['adjusted']}")
                if signal_data['audit'].get('adjustment_reason'):
                    print(f"    Adjustment Reason: {signal_data['audit']['adjustment_reason']}")
        finally:
            # Restore original directory
            processor.RAW_SIGNALS_DIR = original_dir
    
    def analyze_production_signals(self):
        """Analyze real production signals without modifying them."""
        print("\n" + "=" * 80)
        print("ANALYZING PRODUCTION SIGNALS (READ-ONLY)")
        print("=" * 80)
        
        # Get production signal files
        prod_dir = os.path.join(self.project_root, "raw_signals", "tradingview")
        signal_files = sorted(glob.glob(os.path.join(prod_dir, "trade_requests_*.log")))
        
        # Only analyze recent files (last 30 days)
        cutoff_date = datetime.now() - timedelta(days=30)
        recent_files = []
        
        for file_path in signal_files:
            try:
                filename = os.path.basename(file_path)
                date_str = filename.replace("trade_requests_", "").replace(".log", "")
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                if file_date >= cutoff_date:
                    recent_files.append(file_path)
            except ValueError:
                continue
        
        print(f"\nFound {len(recent_files)} recent production files (last 30 days)")
        
        # Analyze for race conditions
        race_conditions = []
        total_signals = 0
        
        for file_path in recent_files:
            signals_in_file = []
            
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    try:
                        parts = line.split(' ', 2)
                        if len(parts) == 3:
                            date, time, json_str = parts
                            timestamp = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M:%S.%f")
                            
                            # Simple parsing for direction and symbol
                            if '"direction":' in json_str and '"symbol":' in json_str:
                                import ujson
                                data = json.loads(json_str)
                                signals_in_file.append({
                                    'timestamp': timestamp,
                                    'symbol': data.get('symbol', ''),
                                    'direction': data.get('direction', ''),
                                    'file': os.path.basename(file_path)
                                })
                                total_signals += 1
                    except:
                        continue
            
            # Check for race conditions in this file
            for i in range(len(signals_in_file) - 1):
                current = signals_in_file[i]
                next_sig = signals_in_file[i + 1]
                
                if current['symbol'] == next_sig['symbol']:
                    time_diff = next_sig['timestamp'] - current['timestamp']
                    
                    if time_diff <= timedelta(seconds=5):
                        # Check for position transition patterns
                        if (current['direction'] in ['long', 'short'] and 
                            next_sig['direction'] == 'flat'):
                            race_conditions.append({
                                'type': 'out_of_order',
                                'symbol': current['symbol'],
                                'pattern': f"{current['direction']} → flat",
                                'time_diff': time_diff.total_seconds(),
                                'file': current['file'],
                                'timestamp': current['timestamp']
                            })
                        elif (current['direction'] == 'flat' and 
                              next_sig['direction'] in ['long', 'short']):
                            race_conditions.append({
                                'type': 'correct_order',
                                'symbol': current['symbol'],
                                'pattern': f"flat → {next_sig['direction']}",
                                'time_diff': time_diff.total_seconds(),
                                'file': current['file'],
                                'timestamp': current['timestamp']
                            })
        
        print(f"Total signals analyzed: {total_signals}")
        print(f"Race conditions found: {len(race_conditions)}")
        
        if race_conditions:
            print("\nRace Conditions Summary:")
            out_of_order = [rc for rc in race_conditions if rc['type'] == 'out_of_order']
            correct_order = [rc for rc in race_conditions if rc['type'] == 'correct_order']
            
            if out_of_order:
                print(f"\n  OUT OF ORDER (would need reordering): {len(out_of_order)}")
                for rc in out_of_order[:3]:  # Show first 3
                    print(f"    - {rc['symbol']} {rc['pattern']} ({rc['time_diff']:.3f}s) in {rc['file']}")
                if len(out_of_order) > 3:
                    print(f"    ... and {len(out_of_order) - 3} more")
            
            if correct_order:
                print(f"\n  CORRECT ORDER (timestamp adjustment only): {len(correct_order)}")
                for rc in correct_order[:3]:  # Show first 3
                    print(f"    - {rc['symbol']} {rc['pattern']} ({rc['time_diff']:.3f}s) in {rc['file']}")
                if len(correct_order) > 3:
                    print(f"    ... and {len(correct_order) - 3} more")
        else:
            print("\nNo race conditions found in recent production files.")
    
    def cleanup(self):
        """Clean up test directory."""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
            print(f"\nCleaned up test directory: {self.test_dir}")
    
    def run(self):
        """Run the complete test suite."""
        try:
            # Create test environment
            self.setup_test_environment()
            
            # Process test signals
            self.process_test_signals()
            
            # Analyze production signals
            self.analyze_production_signals()
            
        finally:
            # Always clean up
            self.cleanup()

def main():
    print("=" * 80)
    print("TradingView Race Condition Handler Test")
    print("=" * 80)
    print("\nThis test will:")
    print("1. Create test signal files with known race conditions")
    print("2. Process them using the actual TradingViewProcessor")
    print("3. Analyze real production signals (read-only)")
    print("4. Demonstrate how race conditions are handled")
    
    tester = RaceConditionTester()
    tester.run()

if __name__ == "__main__":
    main() 