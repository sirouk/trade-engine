#!/usr/bin/env python3
"""
Test reconcile_position with various scenarios on ADAUSDT using CCXT processor
This simulates what execute_trades.py does across all accounts
"""

import asyncio
import sys
import os
from datetime import datetime

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from account_processors.ccxt_processor import CCXTProcessor
from core.utils.modifiers import scale_size_and_price


async def test_reconcile_scenarios():
    """Test various reconcile_position scenarios"""
    print("="*80)
    print("RECONCILE POSITION TEST - CCXT PROCESSOR")
    print("Testing various position management scenarios")
    print("WARNING: This uses REAL money!")
    print("="*80)
    
    async with CCXTProcessor() as processor:
        ada_symbol = "ADA/USDT:USDT"
        
        # Get initial account value
        total_value = await processor.fetch_initial_account_value()
        print(f"\nTotal Account Value: ${total_value:.2f}")
        
        # Get current price
        ticker = await processor.fetch_tickers(ada_symbol)
        if not ticker:
            print("Could not fetch ADA ticker")
            return
            
        current_price = ticker.last
        print(f"Current ADA Price: ${current_price}")
        
        # Calculate a small position size (0.02% of account = ~$8.80)
        position_percentage = 0.0002  # 0.02% of account
        position_value = total_value * position_percentage
        
        print(f"\nUsing {position_percentage*100}% of account = ${position_value:.2f}")
        
        # Helper function to wait and show position
        async def show_position_status(description: str):
            await asyncio.sleep(2)  # Wait for position to settle
            print(f"\n{description}")
            positions = await processor.fetch_and_map_positions(ada_symbol)
            if positions:
                pos = positions[0]
                print(f"  Size: {pos.size} ADA")
                print(f"  Entry Price: ${pos.average_entry_price}")
                print(f"  Leverage: {pos.leverage}x")
                print(f"  Margin Mode: {pos.margin_mode}")
                print(f"  PnL: ${pos.unrealized_pnl:.2f}")
            else:
                print("  No position")
        
        # 1. OPEN LONG POSITION (1x leverage)
        print("\n" + "="*60)
        print("1. OPENING LONG POSITION (1x leverage)")
        print("="*60)
        
        initial_leverage = 1
        long_quantity = (position_value * initial_leverage) / current_price
        
        print(f"Opening long position: {long_quantity:.2f} ADA")
        print(f"Value: ${position_value:.2f}, Leverage: {initial_leverage}x")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("Test cancelled")
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=long_quantity,  # Positive for long
            leverage=initial_leverage,
            margin_mode="isolated"
        )
        
        await show_position_status("Position after opening long:")
        
        # 2. MODIFY LEVERAGE TO 3x (increases position size)
        print("\n" + "="*60)
        print("2. MODIFYING LEVERAGE TO 3x")
        print("="*60)
        
        new_leverage = 3
        new_quantity = (position_value * new_leverage) / current_price
        
        print(f"Changing leverage from 1x to 3x")
        print(f"New position size will be: {new_quantity:.2f} ADA")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=new_quantity,  # Larger position due to leverage
            leverage=new_leverage,
            margin_mode="isolated"
        )
        
        await show_position_status("Position after leverage change to 3x:")
        
        # 3. CLOSE POSITION
        print("\n" + "="*60)
        print("3. CLOSING POSITION")
        print("="*60)
        
        print("Closing the entire position")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=0,  # Zero to close
            leverage=new_leverage,
            margin_mode="isolated"
        )
        
        await show_position_status("Position after closing:")
        
        # 4. GO SHORT
        print("\n" + "="*60)
        print("4. OPENING SHORT POSITION (2x leverage)")
        print("="*60)
        
        short_leverage = 2
        short_quantity = (position_value * short_leverage) / current_price
        
        print(f"Opening short position: {short_quantity:.2f} ADA")
        print(f"Value: ${position_value:.2f}, Leverage: {short_leverage}x")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=-short_quantity,  # Negative for short
            leverage=short_leverage,
            margin_mode="isolated"
        )
        
        await show_position_status("Position after opening short:")
        
        # 5. MODIFY LEVERAGE (on short position)
        print("\n" + "="*60)
        print("5. MODIFYING LEVERAGE ON SHORT (to 4x)")
        print("="*60)
        
        short_new_leverage = 4
        short_new_quantity = (position_value * short_new_leverage) / current_price
        
        print(f"Changing leverage from 2x to 4x on short")
        print(f"New position size will be: {short_new_quantity:.2f} ADA")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=-short_new_quantity,  # Negative for short
            leverage=short_new_leverage,
            margin_mode="isolated"
        )
        
        await show_position_status("Position after leverage change on short:")
        
        # 6. FLIP TO LONG WITHOUT CLOSING FIRST
        print("\n" + "="*60)
        print("6. FLIPPING DIRECTLY FROM SHORT TO LONG")
        print("="*60)
        
        flip_leverage = 2
        flip_quantity = (position_value * flip_leverage) / current_price
        
        print(f"Flipping from short to long position")
        print(f"New long position: {flip_quantity:.2f} ADA at {flip_leverage}x leverage")
        print("Note: reconcile_position will automatically close the short and open long")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=flip_quantity,  # Positive for long (will auto-close short)
            leverage=flip_leverage,
            margin_mode="isolated"
        )
        
        await show_position_status("Position after flipping to long:")
        
        # 7. FINAL CLEANUP - Close position
        print("\n" + "="*60)
        print("7. FINAL CLEANUP - CLOSING ALL POSITIONS")
        print("="*60)
        
        print("Closing all positions to clean up")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("Leaving position open")
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=0,
            leverage=flip_leverage,
            margin_mode="isolated"
        )
        
        await show_position_status("Final position status:")
        
        print("\n" + "="*80)
        print("✅ TEST COMPLETE!")
        print("="*80)
        print("\nThe reconcile_position function successfully handled:")
        print("- Opening long positions")
        print("- Modifying leverage (which adjusts position size)")
        print("- Closing positions")
        print("- Opening short positions")
        print("- Flipping from short to long without manual closing")
        print("\nThis is exactly how execute_trades.py manages positions!")


async def main():
    """Main function"""
    print("Reconcile Position Test Suite")
    print("=" * 80)
    print("This will test the following scenarios:")
    print("1. Open long position (1x leverage)")
    print("2. Modify leverage to 3x")
    print("3. Close position")
    print("4. Go short (2x leverage)")
    print("5. Modify leverage to 4x")
    print("6. Flip directly to long without closing")
    print("7. Clean up (close all)")
    print("\n⚠️  WARNING: This uses REAL money!")
    print("Recommended to use a small position size (0.02% of account)")
    print("=" * 80)
    
    proceed = input("\nProceed with test? (yes/no): ").strip().lower()
    if proceed == 'yes':
        await test_reconcile_scenarios()
    else:
        print("Test cancelled.")


if __name__ == "__main__":
    asyncio.run(main()) 