"""
Generate mt5_prices.json with this week's data (Nov 9-13, 2026)
Stores 5 trading days (Mon-Fri) + weekly high/low for each pair
"""

import MetaTrader5 as mt5
import pandas as pd
import json
from datetime import datetime, timedelta

# All trading pairs from the bot
PAIRS = [
    # Commodities
    "XAUUSDm", "XAGUSDm", "USOILm", "UKOILm",
    
    # Crypto
    "BTCUSDm", "ETHUSDm", "LTCUSDm", "XRPUSDm",
    
    # Major Forex
    "EURUSDm", "GBPUSDm", "USDJPYm", "USDCHFm", 
    "AUDUSDm", "USDCADm", "NZDUSDm",
    
    # Cross Forex
    "EURJPYm", "GBPJPYm", "EURGBPm", "AUDJPYm", 
    "GBPCHFm", "EURCHFm", "EURAUDm", "GBPAUDm", 
    "AUDCADm", "CADJPYm", "CHFJPYm", "NZDJPYm",
    "GBPCADm", "EURNZDm", "EURCADm", "AUDNZDm", 
    "AUDCHFm", "CADCHFm", "NZDCADm", "NZDCHFm", 
    "GBPNZDm",
    
    # US Indices
    "US30m", "US500m", "USTECm", "US2000m",
    
    # European Indices
    "DE30m", "DE40m", "UK100m", "FR40m", 
    "ES35m", "IT40m", "EU50m",
    
    # Asian Indices
    "JP225m", "HK50m", "CN50m", "AU200m"
]

def get_week_data(symbol, start_date, end_date):
    """Fetch daily data for the week (Nov 9-13, 2026)"""
    try:
        # Select symbol in Market Watch
        mt5.symbol_select(symbol, True)
        
        # Fetch daily bars from the specific date range
        # We'll get a few extra days to ensure we capture the full week
        rates = mt5.copy_rates_range(
            symbol, 
            mt5.TIMEFRAME_D1,
            start_date,
            end_date + timedelta(days=1)  # Include end date
        )
        
        if rates is None or len(rates) == 0:
            print(f"  ❌ No data for {symbol}")
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df['day_of_week'] = df['time'].dt.dayofweek  # 0=Monday, 4=Friday
        
        # Filter to only weekdays (Mon-Fri)
        df = df[df['day_of_week'] <= 4].copy()
        
        # Filter to exact date range (Nov 9-13, 2026)
        df = df[(df['time'].dt.date >= start_date.date()) & 
                (df['time'].dt.date <= end_date.date())]
        
        if len(df) == 0:
            print(f"  ❌ No weekday data in range for {symbol}")
            return None
        
        # Calculate weekly high and low
        week_high = float(df['high'].max())
        week_low = float(df['low'].min())
        
        # Build bar data
        bars = []
        for _, row in df.iterrows():
            bars.append({
                'time': row['time'].strftime('%Y-%m-%d'),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close'])
            })
        
        return {
            'symbol': symbol.replace('m', ''),  # Remove 'm' suffix for cleaner name
            'timeframe': 'D1',
            'week_start': start_date.strftime('%Y-%m-%d'),
            'week_end': end_date.strftime('%Y-%m-%d'),
            'week_high': week_high,
            'week_low': week_low,
            'bars': bars
        }
        
    except Exception as e:
        print(f"  ❌ Error with {symbol}: {e}")
        return None


def main():
    print("=" * 60)
    print("GENERATING MT5 WEEK PRICES (Nov 9-13, 2026)")
    print("=" * 60)
    
    # Initialize MT5
    if not mt5.initialize():
        print("❌ MT5 initialization failed!")
        return
    
    print(f"✅ MT5 initialized: {mt5.version()}")
    
    # Define the week: Nov 9 (Mon) to Nov 13 (Fri), 2026
    start_date = datetime(2026, 11, 9)
    end_date = datetime(2026, 11, 13)
    
    print(f"\n📅 Week: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"📊 Processing {len(PAIRS)} trading pairs...\n")
    
    # Collect data for all pairs
    prices = []
    success_count = 0
    
    for i, symbol in enumerate(PAIRS, 1):
        print(f"[{i}/{len(PAIRS)}] {symbol}...", end=" ")
        
        data = get_week_data(symbol, start_date, end_date)
        if data:
            prices.append(data)
            success_count += 1
            print(f"✅ {len(data['bars'])} days | High: {data['week_high']} | Low: {data['week_low']}")
        
    # Build final JSON structure
    output = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'week_start': start_date.strftime('%Y-%m-%d'),
        'week_end': end_date.strftime('%Y-%m-%d'),
        'description': 'MT5 trading data for week of Nov 9-13, 2026 (Mon-Fri)',
        'total_pairs': success_count,
        'prices': prices
    }
    
    # Save to JSON file
    output_file = 'mt5_prices.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print("\n" + "=" * 60)
    print(f"✅ SUCCESS: {success_count}/{len(PAIRS)} pairs saved to {output_file}")
    print("=" * 60)
    
    # Show sample of first pair
    if prices:
        sample = prices[0]
        print(f"\n📋 Sample ({sample['symbol']}):")
        print(f"   Week High: {sample['week_high']}")
        print(f"   Week Low:  {sample['week_low']}")
        print(f"   Days: {len(sample['bars'])}")
        for bar in sample['bars']:
            print(f"      {bar['time']}: O={bar['open']} H={bar['high']} L={bar['low']} C={bar['close']}")
    
    mt5.shutdown()


if __name__ == '__main__':
    main()
