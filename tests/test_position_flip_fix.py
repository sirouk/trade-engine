#!/usr/bin/env python3
"""
Test to verify the position flip fix works correctly
"""

import asyncio
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from account_processors.ccxt_processor import CCXTProcessor


async def test_position_flip_fix():
    """Test the fixed position flip logic"""
    print("="*80)
    print("TESTING POSITION FLIP FIX")
    print("This will verify that flipping from short to long works correctly")
    print("="*80)
    
    async with CCXTProcessor() as processor:
        ada_symbol = "ADA/USDT:USDT"
        
        # Get account value and price
        total_value = await processor.fetch_initial_account_value()
        ticker = await processor.fetch_tickers(ada_symbol)
        current_price = ticker.last
        
        print(f"\nAccount Value: ${total_value:.2f}")
        print(f"ADA Price: ${current_price}")
        
        # Use tiny position for testing
        position_value = total_value * 0.0001  # 0.01% of account
        
        # 1. First establish a short position
        print("\n" + "="*60)
        print("STEP 1: ESTABLISHING SHORT POSITION")
        print("="*60)
        
        short_size = 20  # 20 ADA short
        print(f"Opening short position: {short_size} ADA")
        
        confirm = input("\nProceed with test? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("Test cancelled")
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=-short_size,
            leverage=2,
            margin_mode="isolated"
        )
        
        await asyncio.sleep(2)
        
        # Check position
        positions = await processor.fetch_and_map_positions(ada_symbol)
        if positions:
            pos = positions[0]
            print(f"\nCurrent position: {pos.size} ADA @ ${pos.average_entry_price}")
        
        # 2. Now flip directly to long
        print("\n" + "="*60)
        print("STEP 2: FLIPPING TO LONG POSITION")
        print("="*60)
        
        long_size = 10  # 10 ADA long
        print(f"Flipping to long position: {long_size} ADA")
        print("With the fix, this should:")
        print("1. Detect that close_position fails")
        print("2. Calculate flip amount: |-20| + |10| = 30 ADA buy order")
        print("3. Result in +10 ADA long position")
        
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            return
            
        await processor.reconcile_position(
            symbol=ada_symbol,
            size=long_size,
            leverage=2,
            margin_mode="isolated"
        )
        
        await asyncio.sleep(2)
        
        # Check final position
        positions = await processor.fetch_and_map_positions(ada_symbol)
        if positions:
            pos = positions[0]
            print(f"\nFinal position: {pos.size} ADA @ ${pos.average_entry_price}")
            
            if pos.size == long_size:
                print("\n✅ SUCCESS! Position flip worked correctly!")
                print(f"Position is now {pos.size} ADA long as expected")
            else:
                print(f"\n❌ ISSUE: Expected {long_size} ADA but got {pos.size} ADA")
        else:
            print("\n❌ No position found")
        
        # 3. Clean up
        print("\n" + "="*60)
        print("STEP 3: CLEANING UP")
        print("="*60)
        
        confirm = input("\nClose position? (yes/no): ").strip().lower()
        if confirm == 'yes':
            await processor.reconcile_position(
                symbol=ada_symbol,
                size=0,
                leverage=2,
                margin_mode="isolated"
            )
            print("Position closed")


async def main():
    """Main function"""
    print("Position Flip Fix Test")
    print("=" * 80)
    print("This test will:")
    print("1. Open a -20 ADA short position")
    print("2. Flip directly to +10 ADA long")
    print("3. Verify the fix handles the flip correctly")
    print("\n⚠️  WARNING: This uses REAL money (tiny amounts)")
    print("=" * 80)
    
    await test_position_flip_fix()


if __name__ == "__main__":
    asyncio.run(main()) 