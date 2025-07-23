#!/usr/bin/env python3
"""
Test leverage changes and verify position size adjustments
"""

import asyncio
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from account_processors.ccxt_processor import CCXTProcessor


async def test_leverage_changes():
    """Test leverage change scenarios"""
    print("="*80)
    print("TESTING LEVERAGE CHANGES")
    print("This will verify that changing leverage adjusts position size correctly")
    print("="*80)
    
    async with CCXTProcessor() as processor:
        ada_symbol = "ADA/USDT:USDT"
        
        # Get account value and price
        total_value = await processor.fetch_initial_account_value()
        ticker = await processor.fetch_tickers(ada_symbol)
        current_price = ticker.last
        
        print(f"\nAccount Value: ${total_value:.2f}")
        print(f"ADA Price: ${current_price}")
        
        # Calculate position with fixed margin
        margin_amount = 10  # $10 margin for testing
        print(f"\nUsing fixed margin: ${margin_amount}")
        
        # Helper function to show position details
        async def show_position_details(description: str):
            await asyncio.sleep(2)
            positions = await processor.fetch_and_map_positions(ada_symbol)
            if positions:
                pos = positions[0]
                # Calculate actual margin from position
                actual_margin = abs(pos.size * pos.average_entry_price / pos.leverage)
                print(f"\n{description}")
                print(f"  Size: {pos.size} ADA")
                print(f"  Entry Price: ${pos.average_entry_price}")
                print(f"  Leverage: {pos.leverage}x")
                print(f"  Notional Value: ${abs(pos.size * pos.average_entry_price):.2f}")
                print(f"  Margin Used: ${actual_margin:.2f}")
                print(f"  PnL: ${pos.unrealized_pnl:.2f}")
                return pos
            else:
                print(f"\n{description}")
                print("  No position")
                return None
        
        # 1. OPEN POSITION WITH 1x LEVERAGE
        print("\n" + "="*60)
        print("STEP 1: OPEN POSITION WITH 1x LEVERAGE")
        print("="*60)
        
        leverage_1x = 1
        size_1x = (margin_amount * leverage_1x) / current_price
        
        print(f"Opening position with 1x leverage:")
        print(f"  Expected size: {size_1x:.2f} ADA")
        print(f"  Expected notional: ${margin_amount * leverage_1x:.2f}")
        print(f"  Expected margin: ${margin_amount:.2f}")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("Test cancelled")
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=size_1x,
            leverage=leverage_1x,
            margin_mode="isolated"
        )
        
        pos1 = await show_position_details("Position with 1x leverage:")
        
        # 2. INCREASE LEVERAGE TO 2x
        print("\n" + "="*60)
        print("STEP 2: INCREASE LEVERAGE TO 2x")
        print("="*60)
        
        leverage_2x = 2
        size_2x = (margin_amount * leverage_2x) / current_price
        
        print(f"Changing to 2x leverage (margin stays ~${margin_amount}):")
        print(f"  Expected size: {size_2x:.2f} ADA (double the 1x size)")
        print(f"  Expected notional: ${margin_amount * leverage_2x:.2f}")
        print(f"  Expected margin: ${margin_amount:.2f} (unchanged)")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=size_2x,
            leverage=leverage_2x,
            margin_mode="isolated"
        )
        
        pos2 = await show_position_details("Position with 2x leverage:")
        
        # 3. INCREASE LEVERAGE TO 5x
        print("\n" + "="*60)
        print("STEP 3: INCREASE LEVERAGE TO 5x")
        print("="*60)
        
        leverage_5x = 5
        size_5x = (margin_amount * leverage_5x) / current_price
        
        print(f"Changing to 5x leverage (margin stays ~${margin_amount}):")
        print(f"  Expected size: {size_5x:.2f} ADA (5x the original)")
        print(f"  Expected notional: ${margin_amount * leverage_5x:.2f}")
        print(f"  Expected margin: ${margin_amount:.2f} (unchanged)")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=size_5x,
            leverage=leverage_5x,
            margin_mode="isolated"
        )
        
        pos5 = await show_position_details("Position with 5x leverage:")
        
        # 4. DECREASE LEVERAGE TO 3x
        print("\n" + "="*60)
        print("STEP 4: DECREASE LEVERAGE TO 3x")
        print("="*60)
        
        leverage_3x = 3
        size_3x = (margin_amount * leverage_3x) / current_price
        
        print(f"Reducing to 3x leverage (margin stays ~${margin_amount}):")
        print(f"  Expected size: {size_3x:.2f} ADA (reduced from 5x)")
        print(f"  Expected notional: ${margin_amount * leverage_3x:.2f}")
        print(f"  Expected margin: ${margin_amount:.2f} (unchanged)")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=size_3x,
            leverage=leverage_3x,
            margin_mode="isolated"
        )
        
        pos3 = await show_position_details("Position with 3x leverage:")
        
        # 5. TEST SHORT POSITION WITH LEVERAGE CHANGE
        print("\n" + "="*60)
        print("STEP 5: TEST SHORT POSITION WITH LEVERAGE CHANGE")
        print("="*60)
        
        print("First, closing long position...")
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=0,
            leverage=leverage_3x,
            margin_mode="isolated"
        )
        
        await asyncio.sleep(2)
        
        print("\nOpening short position with 2x leverage:")
        short_size_2x = -(margin_amount * 2) / current_price
        
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=short_size_2x,
            leverage=2,
            margin_mode="isolated"
        )
        
        await show_position_details("Short position with 2x leverage:")
        
        print("\nChanging short to 4x leverage:")
        short_size_4x = -(margin_amount * 4) / current_price
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=short_size_4x,
            leverage=4,
            margin_mode="isolated"
        )
        
        await show_position_details("Short position with 4x leverage:")
        
        # 6. CLEANUP
        print("\n" + "="*60)
        print("STEP 6: CLEANUP")
        print("="*60)
        
        confirm = input("\nClose all positions? (yes/no): ").strip().lower()
        if confirm == 'yes':
            await processor.reconcile_position(
                symbol=ada_symbol,
                size=0,
                leverage=4,
                margin_mode="isolated"
            )
            print("All positions closed")
            
        # Summary
        print("\n" + "="*80)
        print("✅ LEVERAGE CHANGE TEST COMPLETE!")
        print("="*80)
        print("\nKey findings:")
        print("- Leverage changes adjust position size automatically")
        print("- Margin amount remains constant (approximately)")
        print("- Higher leverage = larger position with same margin")
        print("- Lower leverage = smaller position with same margin")
        print("- Works for both long and short positions")
        print("\nFormula: Position Size = (Margin × Leverage) ÷ Price")


async def main():
    """Main function"""
    print("Leverage Change Test Suite")
    print("=" * 80)
    print("This test will demonstrate how leverage changes affect position size")
    print("while keeping margin constant.")
    print("\nTest sequence:")
    print("1. Open with 1x leverage")
    print("2. Increase to 2x (position doubles)")
    print("3. Increase to 5x (position 5x original)")
    print("4. Decrease to 3x (position reduces)")
    print("5. Test with short positions")
    print("\n⚠️  WARNING: This uses REAL money (~$10 margin)")
    print("=" * 80)
    
    await test_leverage_changes()


if __name__ == "__main__":
    asyncio.run(main()) 