"""
Test NASDAQ "This Week High" calculation
"""
import sys
import os
os.environ['TELEGRAM_API_ID'] = '1234567'
os.environ['TELEGRAM_API_HASH'] = 'test'
os.environ['GEMINI_API_KEY'] = 'test'
os.environ['TARGET_CHANNEL'] = '-1002044038089'
os.environ['TARGET_CHAT'] = '-1002050095432'

import pandas as pd
import MetaTrader5 as mt5
import json

print("=" * 70)
print("TEST: NASDAQ This Week High Calculation")
print("=" * 70)

# Load JSON data
with open('mt5_prices.json', 'r') as f:
    data = json.load(f)

# Find NASDAQ (USTECm)
nasdaq_data = None
for price_entry in data['prices']:
    if price_entry['symbol'] in ['USTEC', 'USTECm']:
        nasdaq_data = price_entry
        break

if not nasdaq_data:
    print("❌ NASDAQ not found in JSON")
    sys.exit(1)

print(f"\nSymbol: {nasdaq_data['symbol']}")
print(f"Bars: {len(nasdaq_data['bars'])}")

# Build dataframe
df_data = []
for bar in nasdaq_data['bars']:
    df_data.append({
        'time': pd.to_datetime(bar['time']),
        'open': bar['open'],
        'high': bar['high'],
        'low': bar['low'],
        'close': bar['close']
    })

df = pd.DataFrame(df_data)
df['day_of_week'] = df['time'].dt.dayofweek

# Calculate THIS WEEK using the FIXED logic
today = pd.Timestamp.now()
days_since_monday = today.dayofweek
this_monday = today - pd.Timedelta(days=days_since_monday)
this_monday = this_monday.normalize()
last_monday = this_monday - pd.Timedelta(days=7)

print(f"\nToday: {today.strftime('%Y-%m-%d %A')}")
print(f"This Monday: {this_monday.strftime('%Y-%m-%d')}")
print(f"Last Monday: {last_monday.strftime('%Y-%m-%d')}")

# Filter for THIS WEEK (Mon-Fri)
this_week = df[
    (df['time'] >= this_monday) & 
    (df['time'] < this_monday + pd.Timedelta(days=5)) &
    (df['day_of_week'] <= 4)
]

# Filter for LAST WEEK (Mon-Fri)
last_week = df[
    (df['time'] >= last_monday) & 
    (df['time'] < last_monday + pd.Timedelta(days=5)) &
    (df['day_of_week'] <= 4)
]

print("\n" + "=" * 70)
print("THIS WEEK Data (Nov 9-13):")
print("=" * 70)
for _, row in this_week.iterrows():
    print(f"  {row['time'].strftime('%Y-%m-%d %A')}: High={row['high']:.2f}, Low={row['low']:.2f}")

this_week_high = this_week['high'].max() if len(this_week) > 0 else 0
this_week_low = this_week['low'].min() if len(this_week) > 0 else 0

print("\n" + "=" * 70)
print("LAST WEEK Data (Nov 2-6):")
print("=" * 70)
for _, row in last_week.iterrows():
    print(f"  {row['time'].strftime('%Y-%m-%d %A')}: High={row['high']:.2f}, Low={row['low']:.2f}")

last_week_high = last_week['high'].max() if len(last_week) > 0 else 0
last_week_low = last_week['low'].min() if len(last_week) > 0 else 0

print("\n" + "=" * 70)
print("NASDAQ ANSWER KEY:")
print("=" * 70)
print(f"📊 THIS WEEK (Nov 9-13) HIGH: {this_week_high:.2f} ← CORRECT ANSWER")
print(f"📊 THIS WEEK (Nov 9-13) LOW:  {this_week_low:.2f}")
print(f"📊 LAST WEEK (Nov 2-6) HIGH:  {last_week_high:.2f}")
print(f"📊 LAST WEEK (Nov 2-6) LOW:   {last_week_low:.2f}")
print("=" * 70)

print("\n✅ If the bot answered something different, it means:")
print("   1. Multiple bot instances were running (different calculations)")
print("   2. The bot used OLD code with wrong week logic")
print("   3. The bot used MT5 live data instead of JSON (different values)")
