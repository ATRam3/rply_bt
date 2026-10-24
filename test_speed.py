"""
Quick speed test for the optimized bot
"""
import time
import MetaTrader5 as mt5
from io import BytesIO
from PIL import Image
import os
from dotenv import load_dotenv

load_dotenv()

# Test cache warming
print("="*80)
print("SPEED TEST - Optimized Bot")
print("="*80)

# 1. Test MT5 cache
print("\n1. Testing MT5 Cache Speed...")
if mt5.initialize():
    mt5.symbol_select("XAUUSDm", True)
    
    t0 = time.time()
    rates = mt5.copy_rates_from_pos("XAUUSDm", mt5.TIMEFRAME_D1, 0, 14)
    t1 = time.time()
    
    print(f"   ✅ MT5 fetch: {(t1-t0)*1000:.0f}ms")
    
    # Warm cache
    cache = {}
    for sym in ["XAUUSDm", "GBPJPYm", "EURUSDm", "BTCUSDm", "GBPUSDm"]:
        mt5.symbol_select(sym, True)
        t0 = time.time()
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 14)
        cache[sym] = rates
        print(f"   ✅ Cached {sym}: {(time.time()-t0)*1000:.0f}ms")
    
    mt5.shutdown()
else:
    print("   ❌ MT5 not available")

# 2. Test image processing
print("\n2. Testing Image Processing...")
try:
    # Create a dummy test image
    img = Image.new('RGB', (1920, 1080), color='white')
    img_bytes = BytesIO()
    img.save(img_bytes, format='JPEG', quality=85)
    img_bytes.seek(0)
    
    t0 = time.time()
    test_img = Image.open(img_bytes)
    # Resize test
    w, h = test_img.size
    max_side = 768
    if max(w, h) > max_side:
        ratio = max_side / max(w, h)
        test_img = test_img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    t1 = time.time()
    
    print(f"   ✅ Image resize: {(t1-t0)*1000:.0f}ms")
except Exception as e:
    print(f"   ❌ Error: {e}")

# 3. Estimate total time
print("\n" + "="*80)
print("ESTIMATED PERFORMANCE:")
print("="*80)
print("  Download image:     1.5 - 2.5s  (Telegram)")
print("  MT5 data lookup:    0.01 - 0.05s (cached)")
print("  Gemini API call:    2.0 - 3.5s  (one call with gemini-2.0-flash-exp)")
print("  Send reply:         0.3 - 0.5s  (Telegram)")
print("  " + "-"*60)
print("  TOTAL EXPECTED:     3.8 - 6.5s  ✅")
print("="*80)

print("\n💡 TIPS TO GET UNDER 3 SECONDS:")
print("  1. Use faster internet connection")
print("  2. Host bot on cloud server closer to Google servers")
print("  3. Use OCR for ticker extraction (see SPEED_OPTIMIZATION.md)")
print("  4. Hardcode ticker if 90%+ questions are same symbol")
print("="*80)
