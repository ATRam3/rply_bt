"""
Test proper calendar week calculation
Today is Saturday Oct 24, 2026
"""
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta

def get_week_ranges(df):
    """
    Calculate proper calendar weeks based on today's date
    Trading week: Sunday to Saturday
    """
    today = datetime.now()
    today_date = today.date()
    
    # Get the most recent Saturday (end of last complete week)
    # If today is Saturday, last complete week ended yesterday (Friday) 
    # Actually for trading: if today is Saturday, this week is still ongoing
    
    days_since_sunday = (today.weekday() + 1) % 7  # Sunday = 0
    
    # This week start (most recent Sunday)
    this_week_start = today - timedelta(days=days_since_sunday)
    
    # Last week (previous Sunday to Saturday)
    last_week_end = this_week_start - timedelta(days=1)  # Saturday before this week's Sunday
    last_week_start = last_week_end - timedelta(days=6)   # Previous Sunday
    
    return {
        'this_week_start': this_week_start.date(),
        'last_week_start': last_week_start.date(),
        'last_week_end': last_week_end.date()
    }


if not mt5.initialize():
    print('MT5 failed')
    exit(1)

mt5.symbol_select('GBPJPYm', True)
rates = mt5.copy_rates_from_pos('GBPJPYm', mt5.TIMEFRAME_D1, 0, 21)

df = pd.DataFrame(rates)
df['time'] = pd.to_datetime(df['time'], unit='s')
df['date'] = df['time'].dt.date

print(f"TODAY: {datetime.now().strftime('%Y-%m-%d %A')}")
print('='*80)

weeks = get_week_ranges(df)
print(f"\nCALENDAR WEEK RANGES (Trading Week = Sunday to Saturday):")
print(f"  THIS WEEK starts:  {weeks['this_week_start']} (Sunday)")
print(f"  LAST WEEK:         {weeks['last_week_start']} (Sunday) to {weeks['last_week_end']} (Saturday)")

print('\n' + '='*80)
print('ALL DATA WITH WEEK LABELS:')
print('='*80)

for _, row in df.iterrows():
    date = row['date']
    if date >= weeks['this_week_start']:
        label = "← THIS WEEK"
    elif weeks['last_week_start'] <= date <= weeks['last_week_end']:
        label = "← LAST WEEK"
    else:
        label = "← OLDER"
    
    print(f"{row['time'].strftime('%Y-%m-%d %A'):25} | "
          f"Low: {row['low']:8.2f} | High: {row['high']:8.2f}  {label}")

# Calculate by calendar week
this_week_df = df[df['date'] >= weeks['this_week_start']]
last_week_df = df[(df['date'] >= weeks['last_week_start']) & (df['date'] <= weeks['last_week_end'])]

print('\n' + '='*80)
print('CORRECT WEEKLY CALCULATIONS:')
print('='*80)

if len(last_week_df) > 0:
    print(f"\nLAST WEEK ({weeks['last_week_start']} to {weeks['last_week_end']}):")
    print(f"  Days included: {len(last_week_df)}")
    print(f"  Lowest:  {last_week_df['low'].min():.2f}")
    print(f"  Highest: {last_week_df['high'].max():.2f}")

if len(this_week_df) > 0:
    print(f"\nTHIS WEEK (from {weeks['this_week_start']} onwards):")
    print(f"  Days included: {len(this_week_df)}")
    print(f"  Lowest:  {this_week_df['low'].min():.2f}")
    print(f"  Highest: {this_week_df['high'].max():.2f}")

mt5.shutdown()
