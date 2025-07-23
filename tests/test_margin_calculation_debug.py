#!/usr/bin/env python3
"""
Debug script to understand margin calculation differences between positionBalance and positionIM
"""

import asyncio
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from account_processors.bybit_processor import ByBit


async def debug_margin_calculations():
    """Debug margin calculations from Bybit positions."""
    print("="*80)
    print("MARGIN CALCULATION DEBUG")
    print("="*80)
    
    # Initialize processor
    native_processor = ByBit()
    
    # Get all positions
    print("\nFetching all positions with detailed margin info...")
    positions = await native_processor.fetch_all_open_positions()
    
    if positions and "result" in positions:
        for pos in positions["result"]["list"]:
            if float(pos.get('size', 0)) > 0:
                symbol = pos['symbol']
                size = float(pos['size'])
                avg_price = float(pos['avgPrice'])
                leverage = float(pos['leverage'])
                
                # Different margin values from Bybit
                position_im = float(pos.get('positionIM', 0))
                position_balance = float(pos.get('positionBalance', 0))
                position_mm = float(pos.get('positionMM', 0))
                position_value = float(pos.get('positionValue', 0))
                
                # Calculate theoretical margin
                calculated_margin = position_value / leverage
                
                # Unrealized PnL and cumulative realized PnL
                unrealized_pnl = float(pos.get('unrealisedPnl', 0))
                cum_realized_pnl = float(pos.get('cumRealisedPnl', 0))
                cur_realized_pnl = float(pos.get('curRealisedPnl', 0))
                
                print(f"\n{'='*60}")
                print(f"Symbol: {symbol}")
                print(f"  Size: {size}")
                print(f"  Avg Price: ${avg_price}")
                print(f"  Leverage: {leverage}x")
                print(f"  Position Value: ${position_value:.2f}")
                
                print(f"\nMargin Values:")
                print(f"  positionIM (Initial Margin): ${position_im:.2f}")
                print(f"  positionBalance: ${position_balance:.2f}")
                print(f"  positionMM (Maintenance Margin): ${position_mm:.2f}")
                print(f"  Calculated (value/leverage): ${calculated_margin:.2f}")
                
                print(f"\nDifferences:")
                print(f"  positionBalance - positionIM: ${position_balance - position_im:.2f}")
                print(f"  positionBalance - calculated: ${position_balance - calculated_margin:.2f}")
                print(f"  positionIM - calculated: ${position_im - calculated_margin:.2f}")
                
                print(f"\nPnL Info:")
                print(f"  Unrealized PnL: ${unrealized_pnl:.2f}")
                print(f"  Cumulative Realized PnL: ${cum_realized_pnl:.2f}")
                print(f"  Current Realized PnL: ${cur_realized_pnl:.2f}")
                
                # Check if the difference is related to fees/funding
                balance_im_diff = position_balance - position_im
                if abs(balance_im_diff) > 0.01:
                    print(f"\n⚠️  Position Balance includes ${balance_im_diff:.2f} in fees/funding")
    else:
        print("No positions found")


async def main():
    """Main function"""
    print("Margin Calculation Debug Test")
    print("This will show the difference between positionBalance and positionIM")
    print("=" * 80)
    
    await debug_margin_calculations()


if __name__ == "__main__":
    asyncio.run(main()) 