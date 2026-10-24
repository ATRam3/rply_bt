"""
ULTRA-FAST VERSION - Target: 2-3 seconds
Uses aggressive optimizations
"""
import asyncio
import sys
import os
import re
import time
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

from io import BytesIO
from pyrogram import Client, filters
from pyrogram.types import Message
import google.genai as genai
from PIL import Image
import MetaTrader5 as mt5
import pandas as pd

# Load credentials
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TARGET_CHAT = int(os.getenv("TARGET_CHAT"))

client_ai = genai.Client(api_key=GEMINI_API_KEY)
app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH)

_mt5_initialized = False
_symbol_cache = {}
_CACHE_TTL = 300  # 5 minutes cache

# Minimal symbol map - only most common
COMMON_TICKERS = {
    "GOLD": "XAUUSDm", "XAUUSD": "XAUUSDm",
    "GBPJPY": "GBPJPYm",
    "EURUSD": "EURUSDm",
    "BTCUSD": "BTCUSDm", "BTC": "BTCUSDm",
    "GBPUSD": "GBPUSDm",
}


def ensure_mt5():
    global _mt5_initialized
    if not _mt5_initialized:
        _mt5_initialized = mt5.initialize()
    return _mt5_initialized


def _fetch_mt5_symbol(mt5_symbol: str) -> str | None:
    """Optimized fetch with trading week calculation"""
    mt5.symbol_select(mt5_symbol, True)
    rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_D1, 0, 14)
    
    if rates is None or len(rates) == 0:
        return None
    
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['day_of_week'] = df['time'].dt.dayofweek
    
    # Quick calculations
    all_low = df['low'].min()
    all_high = df['high'].max()
    latest = df['close'].iloc[-1]
    
    # Trading weeks (Mon-Fri only)
    weekdays = df[df['day_of_week'] <= 4]
    this_week = weekdays.tail(5)
    last_week = weekdays.iloc[-10:-5] if len(weekdays) >= 10 else weekdays.iloc[:5]
    
    return (
        f"[{mt5_symbol}] Period: {all_low:.2f} to {all_high:.2f}\n"
        f"Latest: {latest:.2f}\n"
        f"This Week ({this_week['time'].iloc[0].strftime('%m-%d')} to {this_week['time'].iloc[-1].strftime('%m-%d')}): "
        f"Low={this_week['low'].min():.2f}, High={this_week['high'].max():.2f}\n"
        f"Last Week ({last_week['time'].iloc[0].strftime('%m-%d')} to {last_week['time'].iloc[-1].strftime('%m-%d')}): "
        f"Low={last_week['low'].min():.2f}, High={last_week['high'].max():.2f}"
    )


def get_market_data(ticker: str) -> str | None:
    """Cached market data fetch"""
    try:
        mt5_symbol = COMMON_TICKERS.get(ticker.upper(), ticker + "m")
        
        # Check cache
        if mt5_symbol in _symbol_cache:
            cached_time, data = _symbol_cache[mt5_symbol]
            if time.time() - cached_time < _CACHE_TTL:
                return data
        
        if not ensure_mt5():
            return None
        
        data = _fetch_mt5_symbol(mt5_symbol)
        if data:
            _symbol_cache[mt5_symbol] = (time.time(), data)
        return data
    except:
        return None


def solve_ultra_fast(photo_bytes: BytesIO) -> str:
    """ULTRA-FAST: Assume ticker is one of top 3, send all data"""
    try:
        photo_bytes.seek(0)
        img = Image.open(photo_bytes)
        
        # Aggressive resize for speed
        w, h = img.size
        if max(w, h) > 640:
            ratio = 640 / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        
        t0 = time.time()
        
        # Get top 3 ticker data (covers 80% of questions)
        data_parts = []
        for ticker in ["XAUUSD", "GBPJPY", "EURUSD"]:
            data = get_market_data(ticker)
            if data:
                data_parts.append(data)
        
        combined_data = "\n\n".join(data_parts)
        
        # Minimal prompt for speed
        prompt = (
            f"Price data:\n{combined_data}\n\n"
            "Find the answer from the image. Reply with ONLY the number or short answer. "
            "For 'last week' use Last Week values. For 'this week' use This Week values."
        )
        
        # Use fastest available model
        response = client_ai.models.generate_content(
            model='gemini-3.5-flash',
            contents=[prompt, img]
        )
        
        answer = response.text.strip()
        # Quick clean
        for prefix in ["The answer is ", "Answer: "]:
            if answer.startswith(prefix):
                answer = answer[len(prefix):]
        
        print(f"⚡ Answered in {time.time()-t0:.1f}s")
        return answer.strip()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


@app.on_message(filters.chat(TARGET_CHAT) & filters.photo)
async def handle_post(client: Client, message: Message):
    t = time.time()
    print(f"\n⚡ Post #{message.id}")
    
    try:
        # Fast download with timeout
        photo = await asyncio.wait_for(
            client.download_media(message, in_memory=True),
            timeout=4.0
        )
        print(f"📥 {time.time()-t:.1f}s")
        
        answer = await asyncio.to_thread(solve_ultra_fast, photo)
        
        if answer:
            await client.send_message(
                chat_id=message.chat.id,
                text=answer,
                reply_to_message_id=message.id
            )
            print(f"🚀 TOTAL: {time.time()-t:.1f}s")
    except asyncio.TimeoutError:
        print("❌ Timeout")
    except Exception as e:
        print(f"❌ {e}")


if __name__ == "__main__":
    print("🚀 ULTRA-FAST MODE")
    if mt5.initialize():
        _mt5_initialized = True
        print("✅ MT5 ready")
        # Pre-warm top 3 only
        for sym in ["XAUUSDm", "GBPJPYm", "EURUSDm"]:
            data = _fetch_mt5_symbol(sym)
            if data:
                _symbol_cache[sym] = (time.time(), data)
        print(f"✅ Cached {len(_symbol_cache)} symbols")
    
    print(f"🎯 Listening on {TARGET_CHAT}")
    app.run()
    mt5.shutdown()
