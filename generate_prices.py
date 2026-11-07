"""
Friday Night Price Generator
Run this script every Friday night to generate price data for Saturday's quiz.
"""

import MetaTrader5 as mt5
import pandas as pd
import json
from datetime import datetime, timedelta
import os

def init_mt5():
    """Initialize MT5 connection"""
    if not mt5.initialize():
        print(f"MT5 initialization failed: {mt5.last_error()}")
        return False
    print("MT5 initialized successfully")
    return True

def get_price_data(symbol, timeframe_str):
    """Fetch OHLC data for a symbol"""
    timeframe_map = {
        'H4': mt5.TIMEFRAME_H4,
        'H1': mt5.TIMEFRAME_H1,
        'D1': mt5.TIMEFRAME_D1,
        'W1': mt5.TIMEFRAME_W1,
        'M1': mt5.TIMEFRAME_M1,
        'MN1': mt5.TIMEFRAME_MN1
    }
    
    timeframe = timeframe_map.get(timeframe_str)
    if not timeframe:
        return None
    
    # Get 14 bars (14 days for D1) to match bot's data window
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 14)
    
    if rates is None or len(rates) == 0:
        return None
    
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    return {
        'symbol': symbol.replace('m', ''),  # Remove 'm' suffix for storage
        'timeframe': timeframe_str,
        'bars': [
            {
                'time': row['time'].isoformat(),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close'])
            }
            for _, row in df.iterrows()
        ]
    }

def generate_all_prices():
    """Generate price data for all supported symbols and timeframes"""
    # Use Exness symbol names (add 'm' suffix)
    symbols = [
        'EURUSDm', 'GBPUSDm', 'USDJPYm', 'USDCHFm', 'AUDUSDm', 'USDCADm', 'NZDUSDm',
        'EURJPYm', 'GBPJPYm', 'EURGBPm', 'AUDJPYm', 'GBPCHFm',
        'XAUUSDm',  # Gold
        'USOILm',   # Oil
        'US30m', 'US500m', 'USTECm',  # Indices
        'BTCUSDm', 'ETHUSDm'  # Crypto (if available)
    ]
    
    # We only need D1 (daily) for quiz questions
    timeframes = ['D1']
    
    if not init_mt5():
        return None
    
    data = {
        'generated_at': datetime.now().isoformat(),
        'prices': []
    }
    
    for symbol in symbols:
        # Enable symbol in Market Watch
        mt5.symbol_select(symbol, True)
        
        print(f"Fetching {symbol}...")
        for timeframe in timeframes:
            price_data = get_price_data(symbol, timeframe)
            if price_data:
                data['prices'].append(price_data)
            else:
                print(f"  ⚠️ Could not fetch {symbol} {timeframe} (might not be available)")
    
    mt5.shutdown()
    return data

def main():
    """Main execution"""
    print("=" * 60)
    print("Friday Night Price Generator")
    print("=" * 60)
    print(f"Current time: {datetime.now()}")
    print()
    
    data = generate_all_prices()
    
    if not data:
        print("\n❌ Failed to generate price data")
        return
    
    # Save to JSON file
    output_file = 'mt5_prices.json'
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print()
    print("=" * 60)
    print(f"✅ Price data saved to {output_file}")
    print(f"   Total records: {len(data['prices'])}")
    print(f"   Generated at: {data['generated_at']}")
    print()
    print("Next steps:")
    print("1. Commit this file to GitHub:")
    print("   git add mt5_prices.json")
    print("   git commit -m 'Update prices for Saturday quiz'")
    print("   git push")
    print()
    print("2. Your Codespaces bot will use this data on Saturday")
    print("=" * 60)

if __name__ == "__main__":
    main()
