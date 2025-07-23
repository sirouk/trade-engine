#!/usr/bin/env python3
"""
Check if Bybit is configured for CCXT
"""

import sys
import os
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Check if CCXT is installed
try:
    import ccxt
    print("✅ CCXT is installed")
    print(f"   Version: {ccxt.__version__}")
    print(f"   Bybit supported: {'bybit' in ccxt.exchanges}")
except ImportError:
    print("❌ CCXT is not installed!")
    print("   Install with: pip install 'ccxt[async]'")
    sys.exit(1)

# Check credentials
try:
    from config.credentials import load_credentials, CREDENTIALS_FILE
    
    if os.path.exists(CREDENTIALS_FILE):
        print(f"\n✅ Credentials file found: {CREDENTIALS_FILE}")
        
        # Load and check
        creds = load_credentials(CREDENTIALS_FILE)
        
        # Check native Bybit credentials
        if creds.bybit and creds.bybit.api_key:
            print("\n📌 Native Bybit credentials found:")
            print(f"   API Key: {creds.bybit.api_key[:8]}...")
            print(f"   Leverage Override: {creds.bybit.leverage_override}")
        
        # Check CCXT credentials
        if creds.ccxt and creds.ccxt.exchange_name:
            print(f"\n📌 CCXT credentials found:")
            print(f"   Exchange: {creds.ccxt.exchange_name}")
            print(f"   API Key: {creds.ccxt.api_key[:8] if creds.ccxt.api_key else 'Not set'}...")
            print(f"   Enabled: {creds.ccxt.enabled}")
            
            if creds.ccxt.exchange_name.lower() == 'bybit':
                print("\n✅ Bybit is configured for CCXT!")
                print("   You can use the CCXT processor.")
            else:
                print(f"\n⚠️  CCXT is configured for {creds.ccxt.exchange_name}, not Bybit")
                print("   To use Bybit with CCXT, run: python config/credentials.py")
                print("   And configure Bybit as the CCXT exchange.")
        else:
            print("\n⚠️  No CCXT exchange configured")
            print("   To use Bybit with CCXT processor:")
            print("   1. Run: python config/credentials.py")
            print("   2. Choose to configure a CCXT exchange")
            print("   3. Enter 'bybit' as the exchange name")
            print("   4. Enter your Bybit API credentials")
            
            if creds.bybit and creds.bybit.api_key:
                print("\n💡 TIP: You already have Bybit credentials in the native section.")
                print("   You can use the same API key and secret for CCXT.")
    else:
        print(f"\n❌ No credentials file found at {CREDENTIALS_FILE}")
        print("   Run: python config/credentials.py")
        
except Exception as e:
    print(f"\n❌ Error checking credentials: {str(e)}")

print("\n" + "="*60)
print("Next Steps:")
print("="*60)
print("1. If CCXT Bybit is not configured, run: python config/credentials.py")
print("2. Once configured, run: python tests/test_bybit_ccxt_live.py")
print("3. Or use the native Bybit processor if you prefer") 