import MetaTrader5 as mt5
import pandas as pd

if not mt5.initialize():
    print(f"❌ MT5 Initialization failed: {mt5.last_error()}")
    quit()

# Use the exact symbol name found for your account
symbol = "XAUUSDm"
mt5.symbol_select(symbol, True)

# Fetch the last 7 daily candles
rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 7)

if rates is not None and len(rates) > 0:
    df = pd.DataFrame(rates)
    lowest_price = df['low'].min()
    highest_price = df['high'].max()
    current_price = df['close'].iloc[-1]
    
    print(f"✅ SUCCESS! Exness Data for {symbol}:")
    print(f"- Lowest price this week: {lowest_price:.3f}")
    print(f"- Highest price this week: {highest_price:.3f}")
    print(f"- Current price: {current_price:.3f}")
else:
    print(f"⚠️ Could not retrieve rates for {symbol}.")

mt5.shutdown()