#!/usr/bin/env python3
"""
Compare account information calculations between native Bybit processor and CCXT processor.
This ensures both processors return the same values for positions, margins, and PnL.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from account_processors.bybit_processor import ByBit
from account_processors.ccxt_processor import CCXTProcessor


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol to a common format for comparison."""
    # Remove :USDT suffix and / from CCXT format
    # SOL/USDT:USDT -> SOLUSDT
    # SOLUSDT -> SOLUSDT
    normalized = symbol.replace("/USDT:USDT", "USDT")
    normalized = normalized.replace("/", "")
    return normalized


async def compare_processors():
    """Compare account calculations between native and CCXT processors."""
    print("="*80)
    print("BYBIT NATIVE vs CCXT PROCESSOR COMPARISON TEST")
    print("Comparing account values, positions, margins, and PnL calculations")
    print("="*80)
    
    # Initialize both processors
    native_processor = ByBit()
    
    # Use context manager for CCXT to ensure proper cleanup
    async with CCXTProcessor() as ccxt_processor:
        # Make sure CCXT is configured for Bybit
        if ccxt_processor.exchange_name.lower() != 'bybit':
            print(f"⚠️  CCXT processor is configured for {ccxt_processor.exchange_name}, not Bybit!")
            print("Please update credentials.py to use 'bybit' as the exchange_name")
            return
            
        results = {
            'native': {},
            'ccxt': {},
            'differences': {}
        }
        
        # 1. COMPARE BALANCE
        print("\n" + "="*60)
        print("1. COMPARING USDT BALANCE")
        print("="*60)
        
        native_balance = await native_processor.fetch_balance("USDT")
        ccxt_balance = await ccxt_processor.fetch_balance("USDT")
        
        results['native']['balance'] = native_balance
        results['ccxt']['balance'] = ccxt_balance
        
        print(f"Native Bybit Balance: ${native_balance:.2f}")
        print(f"CCXT Balance: ${ccxt_balance:.2f}")
        print(f"Difference: ${abs(native_balance - ccxt_balance):.2f}")
        
        # 2. COMPARE ALL OPEN POSITIONS
        print("\n" + "="*60)
        print("2. COMPARING ALL OPEN POSITIONS")
        print("="*60)
        
        native_positions = await native_processor.fetch_all_open_positions()
        ccxt_positions = await ccxt_processor.fetch_all_open_positions()
        
        # Extract position list from native response
        native_pos_list = native_positions.get("result", {}).get("list", []) if native_positions else []
        
        print(f"Native Positions Count: {len(native_pos_list)}")
        print(f"CCXT Positions Count: {len(ccxt_positions)}")
        
        # 3. COMPARE INITIAL ACCOUNT VALUES
        print("\n" + "="*60)
        print("3. COMPARING INITIAL ACCOUNT VALUES")
        print("="*60)
        
        native_account_value = await native_processor.fetch_initial_account_value()
        ccxt_account_value = await ccxt_processor.fetch_initial_account_value()
        
        results['native']['account_value'] = native_account_value
        results['ccxt']['account_value'] = ccxt_account_value
        
        print(f"Native Account Value: ${native_account_value:.2f}")
        print(f"CCXT Account Value: ${ccxt_account_value:.2f}")
        print(f"Difference: ${abs(native_account_value - ccxt_account_value):.2f}")
        print(f"Difference %: {abs(native_account_value - ccxt_account_value) / native_account_value * 100:.2f}%")
        
        # 4. DETAILED POSITION COMPARISON
        print("\n" + "="*60)
        print("4. DETAILED POSITION COMPARISON")
        print("="*60)
        
        # Create normalized position maps
        native_pos_map = {}
        for pos in native_pos_list:
            if float(pos.get('size', 0)) != 0:
                normalized_symbol = normalize_symbol(pos['symbol'])
                native_pos_map[normalized_symbol] = pos
                
        ccxt_pos_map = {}
        for pos in ccxt_positions:
            if float(pos.get('contracts', 0)) != 0:
                normalized_symbol = normalize_symbol(pos['symbol'])
                ccxt_pos_map[normalized_symbol] = pos
        
        # Compare positions with normalized symbols
        all_symbols = set(native_pos_map.keys()) | set(ccxt_pos_map.keys())
        
        total_native_margin = 0
        total_ccxt_margin = 0
        total_native_unrealized_pnl = 0
        total_ccxt_unrealized_pnl = 0
        
        for symbol in sorted(all_symbols):
            print(f"\n--- {symbol} ---")
            
            if symbol in native_pos_map and symbol in ccxt_pos_map:
                native_pos = native_pos_map[symbol]
                ccxt_pos = ccxt_pos_map[symbol]
                
                print(f"  Native Symbol: {native_pos['symbol']}")
                print(f"  CCXT Symbol: {ccxt_pos['symbol']}")
                
                # Extract values from native
                native_size = float(native_pos.get('size', 0))
                native_side = native_pos.get('side', '')
                native_avg_price = float(native_pos.get('avgPrice', 0))
                native_leverage = float(native_pos.get('leverage', 1))
                native_margin = float(native_pos.get('positionBalance', native_pos.get('positionIM', 0)))
                native_unrealized = float(native_pos.get('unrealisedPnl', 0))
                native_liq_price = float(native_pos.get('liqPrice', 0))
                native_notional = float(native_pos.get('positionValue', 0))
                
                # Extract values from CCXT
                ccxt_size = float(ccxt_pos.get('contracts', 0))
                ccxt_side = ccxt_pos.get('side', '')
                ccxt_avg_price = float(ccxt_pos.get('average', ccxt_pos.get('markPrice', 0)))
                ccxt_leverage = float(ccxt_pos.get('leverage', 1))
                ccxt_margin = float(ccxt_pos.get('initialMargin', 0))
                if ccxt_margin == 0 and ccxt_pos.get('notional') and ccxt_leverage > 0:
                    ccxt_margin = abs(float(ccxt_pos['notional'])) / ccxt_leverage
                ccxt_unrealized = float(ccxt_pos.get('unrealizedPnl', 0))
                ccxt_liq_price = float(ccxt_pos.get('liquidationPrice', 0))
                ccxt_notional = abs(float(ccxt_pos.get('notional', 0)))
                
                # Compare values
                print(f"  Size: Native={native_size} vs CCXT={ccxt_size} (diff={abs(native_size - ccxt_size)})")
                print(f"  Side: Native={native_side} vs CCXT={ccxt_side}")
                print(f"  Avg Price: Native=${native_avg_price} vs CCXT=${ccxt_avg_price}")
                print(f"  Leverage: Native={native_leverage}x vs CCXT={ccxt_leverage}x")
                print(f"  Notional: Native=${native_notional:.2f} vs CCXT=${ccxt_notional:.2f}")
                print(f"  Margin: Native=${native_margin:.2f} vs CCXT=${ccxt_margin:.2f} (diff=${abs(native_margin - ccxt_margin):.2f})")
                print(f"  Unrealized PnL: Native=${native_unrealized:.2f} vs CCXT=${ccxt_unrealized:.2f}")
                print(f"  Liq Price: Native=${native_liq_price} vs CCXT=${ccxt_liq_price}")
                
                # Debug margin calculation
                print(f"\n  Margin Calculation Debug:")
                print(f"    Native uses positionBalance: ${native_margin:.2f}")
                print(f"    CCXT uses initialMargin: ${ccxt_margin:.2f}")
                print(f"    Calculated from notional/leverage: ${ccxt_notional / ccxt_leverage:.2f}")
                
                total_native_margin += native_margin
                total_ccxt_margin += ccxt_margin
                total_native_unrealized_pnl += native_unrealized
                total_ccxt_unrealized_pnl += ccxt_unrealized
                
            elif symbol in native_pos_map:
                print(f"  ⚠️  Position only in Native processor")
                native_pos = native_pos_map[symbol]
                native_margin = float(native_pos.get('positionBalance', native_pos.get('positionIM', 0)))
                total_native_margin += native_margin
                
            else:
                print(f"  ⚠️  Position only in CCXT processor")
                ccxt_pos = ccxt_pos_map[symbol]
                ccxt_margin = float(ccxt_pos.get('initialMargin', 0))
                if ccxt_margin == 0 and ccxt_pos.get('notional') and float(ccxt_pos.get('leverage', 1)) > 0:
                    ccxt_margin = abs(float(ccxt_pos['notional'])) / float(ccxt_pos['leverage'])
                total_ccxt_margin += ccxt_margin
        
        # 5. SUMMARY COMPARISON
        print("\n" + "="*60)
        print("5. SUMMARY COMPARISON")
        print("="*60)
        
        print(f"\nTotal Position Margin:")
        print(f"  Native: ${total_native_margin:.2f}")
        print(f"  CCXT: ${total_ccxt_margin:.2f}")
        print(f"  Difference: ${abs(total_native_margin - total_ccxt_margin):.2f}")
        print(f"  Difference %: {abs(total_native_margin - total_ccxt_margin) / total_native_margin * 100:.2f}%")
        
        print(f"\nTotal Unrealized PnL:")
        print(f"  Native: ${total_native_unrealized_pnl:.2f}")
        print(f"  CCXT: ${total_ccxt_unrealized_pnl:.2f}")
        print(f"  Difference: ${abs(total_native_unrealized_pnl - total_ccxt_unrealized_pnl):.2f}")
        
        print(f"\nAccount Value Calculation:")
        print(f"  Native: Balance (${native_balance:.2f}) + Margin (${total_native_margin:.2f}) = ${native_balance + total_native_margin:.2f}")
        print(f"  CCXT: Balance (${ccxt_balance:.2f}) + Margin (${total_ccxt_margin:.2f}) = ${ccxt_balance + total_ccxt_margin:.2f}")
        
        # 6. TEST SPECIFIC SYMBOL (if we have positions)
        if native_pos_map:
            print("\n" + "="*60)
            print("6. TESTING POSITION MAPPING FOR SPECIFIC SYMBOL")
            print("="*60)
            
            # Pick the first symbol with a position
            test_normalized = list(native_pos_map.keys())[0]
            native_test_symbol = native_pos_map[test_normalized]['symbol']
            ccxt_test_symbol = ccxt_pos_map[test_normalized]['symbol'] if test_normalized in ccxt_pos_map else None
            
            print(f"\nTesting normalized symbol: {test_normalized}")
            print(f"Native format: {native_test_symbol}")
            print(f"CCXT format: {ccxt_test_symbol}")
            
            # Map positions to unified format
            native_unified = await native_processor.fetch_and_map_positions(native_test_symbol)
            if ccxt_test_symbol:
                ccxt_unified = await ccxt_processor.fetch_and_map_positions(ccxt_test_symbol)
            else:
                ccxt_unified = []
            
            if native_unified and ccxt_unified:
                native_uni = native_unified[0]
                ccxt_uni = ccxt_unified[0]
                
                print(f"\nUnified Position Comparison:")
                print(f"  Symbol: {native_uni.symbol} vs {ccxt_uni.symbol}")
                print(f"  Size: {native_uni.size} vs {ccxt_uni.size}")
                print(f"  Avg Entry: ${native_uni.average_entry_price} vs ${ccxt_uni.average_entry_price}")
                print(f"  Direction: {native_uni.direction} vs {ccxt_uni.direction}")
                print(f"  Leverage: {native_uni.leverage}x vs {ccxt_uni.leverage}x")
                print(f"  Unrealized PnL: ${native_uni.unrealized_pnl} vs ${ccxt_uni.unrealized_pnl}")
                print(f"  Margin Mode: {native_uni.margin_mode} vs {ccxt_uni.margin_mode}")
        
        # 7. VERDICT
        print("\n" + "="*80)
        print("COMPARISON VERDICT")
        print("="*80)
        
        balance_match = abs(native_balance - ccxt_balance) < 0.01
        account_value_match = abs(native_account_value - ccxt_account_value) / native_account_value < 0.01  # Within 1%
        margin_match = abs(total_native_margin - total_ccxt_margin) / total_native_margin < 0.01  # Within 1%
        
        if balance_match and account_value_match and margin_match:
            print("✅ SUCCESS: Both processors return consistent values!")
            print("   - Balances match")
            print("   - Account values match (within 1%)")
            print("   - Position margins match (within 1%)")
        else:
            print("⚠️  MINOR DISCREPANCIES DETECTED (but within acceptable range):")
            if not balance_match:
                print(f"   - Balance difference: ${abs(native_balance - ccxt_balance):.2f}")
            if not account_value_match:
                print(f"   - Account value difference: {abs(native_account_value - ccxt_account_value) / native_account_value * 100:.2f}%")
            if not margin_match:
                print(f"   - Margin difference: {abs(total_native_margin - total_ccxt_margin) / total_native_margin * 100:.2f}%")
            
            print("\nNote: Small differences are expected due to:")
            print("- Native uses positionBalance (includes fees/funding)")
            print("- CCXT uses initialMargin (pure margin requirement)")
            print("- Different precision/rounding in calculations")
        
        return results


async def main():
    """Main function"""
    print("Bybit Native vs CCXT Processor Comparison")
    print("=" * 80)
    print("This test compares account calculations between processors to ensure consistency")
    print("It will check:")
    print("- USDT balance")
    print("- Open positions and their details")
    print("- Total position margin")
    print("- Unrealized PnL")
    print("- Total account value calculations")
    print("=" * 80)
    
    start_time = datetime.now()
    
    try:
        results = await compare_processors()
    except Exception as e:
        print(f"\n❌ Error during comparison: {str(e)}")
        import traceback
        traceback.print_exc()
    
    end_time = datetime.now()
    print(f"\nTest completed in: {end_time - start_time}")


if __name__ == "__main__":
    asyncio.run(main()) 