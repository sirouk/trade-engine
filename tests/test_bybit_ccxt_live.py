#!/usr/bin/env python3
"""
Live test script for Bybit using the CCXT processor
WARNING: This uses REAL money - be careful!
"""

import asyncio
import sys
import os
from datetime import datetime

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from account_processors.ccxt_processor import CCXTProcessor


async def test_bybit_live():
    """Test Bybit with live account data"""
    print("="*80)
    print("BYBIT LIVE ACCOUNT TEST - CCXT PROCESSOR")
    print("WARNING: This is using REAL money!")
    print("="*80)
    
    try:
        async with CCXTProcessor() as processor:
            print(f"\n✅ Successfully connected to: {processor.exchange_name}")
            print(f"Enabled: {processor.enabled}")
            
            # 1. Test Balance
            print("\n" + "="*60)
            print("ACCOUNT BALANCE")
            print("="*60)
            
            balance = await processor.fetch_balance("USDT")
            print(f"Available USDT Balance: {balance}")
            
            # Get total account value
            total_value = await processor.fetch_initial_account_value()
            print(f"Total Account Value: ${total_value:.2f}")
            
            # 2. Test All Open Positions
            print("\n" + "="*60)
            print("ALL OPEN POSITIONS")
            print("="*60)
            
            all_positions = await processor.fetch_all_open_positions()
            if all_positions:
                print(f"Found {len(all_positions)} open positions:")
                for pos in all_positions:
                    symbol = pos.get('symbol', 'Unknown')
                    contracts = pos.get('contracts', 0)
                    side = pos.get('side', 'unknown')
                    notional = pos.get('notional', 0)
                    pnl = pos.get('unrealizedPnl', 0)
                    print(f"  {symbol}: {contracts} contracts ({side}), Notional: ${abs(notional):.2f}, PnL: ${pnl:.2f}")
            else:
                print("No open positions found.")
            
            # 3. Test Symbol Mapping
            print("\n" + "="*60)
            print("SYMBOL MAPPING TEST")
            print("="*60)
            
            test_symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]
            for signal_symbol in test_symbols:
                exchange_symbol = processor.map_signal_symbol_to_exchange(signal_symbol)
                print(f"{signal_symbol} -> {exchange_symbol}")
            
            # 4. Test Market Data for ADA
            print("\n" + "="*60)
            print("ADA MARKET DATA")
            print("="*60)
            
            ada_symbol = "ADA/USDT:USDT"
            
            # Get ticker
            ticker = await processor.fetch_tickers(ada_symbol)
            if ticker:
                print(f"ADA Ticker:")
                print(f"  Bid: ${ticker.bid}")
                print(f"  Ask: ${ticker.ask}")
                print(f"  Last: ${ticker.last}")
                print(f"  Volume: {ticker.volume}")
            
            # Get symbol details
            details = await processor.get_symbol_details(ada_symbol)
            if details:
                lot_size, min_size, tick_size, contract_value, max_size = details
                print(f"\nADA Trading Details:")
                print(f"  Lot Size: {lot_size}")
                print(f"  Min Size: {min_size} ADA")
                print(f"  Tick Size: ${tick_size}")
                print(f"  Contract Value: {contract_value}")
                print(f"  Max Size: {max_size} ADA")
                
                # Calculate minimum order value
                min_usd = min_size * ticker.last if ticker else 0
                print(f"  Min Order Value: ${min_usd:.2f}")
            
            # 5. Check existing ADA position
            print("\n" + "="*60)
            print("EXISTING ADA POSITION")
            print("="*60)
            
            ada_positions = await processor.fetch_and_map_positions(ada_symbol)
            if ada_positions:
                for pos in ada_positions:
                    print(f"Current ADA Position:")
                    print(f"  Size: {pos.size} ADA")
                    print(f"  Entry Price: ${pos.average_entry_price}")
                    print(f"  Leverage: {pos.leverage}x")
                    print(f"  PnL: ${pos.unrealized_pnl:.2f}")
                    print(f"  Margin Mode: {pos.margin_mode}")
            else:
                print("No existing ADA position.")
            
            # 6. Test Trade Calculation
            print("\n" + "="*60)
            print("TEST TRADE CALCULATION")
            print("="*60)
            
            # Calculate a small test trade
            test_usd_value = 10  # $10 test trade
            if ticker and details:
                ada_amount = test_usd_value / ticker.last
                print(f"\nTest Trade: ${test_usd_value} worth of ADA")
                print(f"  Raw ADA amount: {ada_amount:.4f}")
                
                # Import the scaling function
                from core.utils.modifiers import scale_size_and_price
                scaled_lots, _, _ = scale_size_and_price(
                    ada_symbol, 
                    ada_amount, 
                    0, 
                    lot_size, 
                    min_size, 
                    tick_size, 
                    contract_value
                )
                
                final_usd = scaled_lots * ticker.last * contract_value
                print(f"  Scaled amount: {scaled_lots} ADA")
                print(f"  Final USD value: ${final_usd:.2f}")
                
                if scaled_lots < min_size:
                    print(f"  ⚠️  Order too small! Minimum is {min_size} ADA (${min_size * ticker.last:.2f})")
            
            # 7. Place Test Trade (with confirmation)
            print("\n" + "="*60)
            print("PLACE TEST TRADE")
            print("="*60)
            
            # Safety check
            if balance < 20:
                print("❌ Insufficient balance for test trade. Need at least $20 USDT.")
                return
            
            print("\nReady to place a test trade:")
            print(f"  Symbol: {ada_symbol}")
            print(f"  Side: BUY (long)")
            print(f"  Size: {scaled_lots if 'scaled_lots' in locals() else 'N/A'} ADA")
            print(f"  Value: ${final_usd:.2f}" if 'final_usd' in locals() else "Value: N/A")
            print(f"  Leverage: 1x")
            print(f"  Margin Mode: isolated")
            
            confirm = input("\n⚠️  Execute this REAL trade? (type 'yes' to confirm): ").strip().lower()
            
            if confirm == 'yes':
                print("\nPlacing order...")
                try:
                    order = await processor.open_market_position(
                        symbol=ada_symbol,
                        side="buy",
                        size=ada_amount if 'ada_amount' in locals() else 10,  # Use calculated amount
                        leverage=1,
                        margin_mode="isolated",
                        scale_lot_size=True  # Let it scale properly
                    )
                    
                    if order:
                        print("\n✅ Order placed successfully!")
                        print(f"Order details: {order}")
                        
                        # Wait a bit and check new position
                        await asyncio.sleep(2)
                        
                        print("\nChecking new position...")
                        new_positions = await processor.fetch_and_map_positions(ada_symbol)
                        if new_positions:
                            for pos in new_positions:
                                print(f"New ADA Position:")
                                print(f"  Size: {pos.size} ADA")
                                print(f"  Entry Price: ${pos.average_entry_price}")
                    else:
                        print("❌ Order failed!")
                        
                except Exception as e:
                    print(f"❌ Error placing order: {str(e)}")
            else:
                print("\n❌ Trade cancelled by user.")
                
    except Exception as e:
        print(f"\n❌ Error during test: {str(e)}")
        import traceback
        traceback.print_exc()


async def main():
    """Main function"""
    print("Bybit Live Test Script")
    print("=" * 80)
    print("This script will:")
    print("1. Connect to your Bybit account")
    print("2. Show account balance and positions")
    print("3. Test ADA market data")
    print("4. Optionally place a small test trade")
    print("\n⚠️  WARNING: This uses REAL money!")
    print("=" * 80)
    
    proceed = input("\nProceed with live test? (yes/no): ").strip().lower()
    if proceed == 'yes':
        await test_bybit_live()
    else:
        print("Test cancelled.")


if __name__ == "__main__":
    asyncio.run(main()) 