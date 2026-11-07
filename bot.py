import asyncio
import sys
import os
import re
import time
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

# Suppress Pyrogram's "Peer id invalid" warnings - these are harmless background errors
logging.getLogger("pyrogram").setLevel(logging.ERROR)

# Fix Windows terminal encoding so emojis in print() never crash
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Load credentials from .env file
load_dotenv()

from io import BytesIO
from pyrogram import Client, filters
from pyrogram.types import Message
import google.genai as genai
from PIL import Image
import pandas as pd

# Try to import MT5 (only works on Windows)
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
    print("✅ MT5: Available (Windows)")
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None
    print("⚠️ MT5: Not available (Linux/Mac - using JSON fallback)")

# OCR for fast text extraction
try:
    import pytesseract
    # Auto-detect Tesseract on Windows
    import os
    if os.name == 'nt':  # Windows
        possible_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'C:\Tesseract-OCR\tesseract.exe'
        ]
        for path in possible_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                break
    OCR_AVAILABLE = True
    print("✅ OCR Mode: Enabled (pytesseract)")
except ImportError:
    OCR_AVAILABLE = False
    print("⚠️ OCR Mode: Disabled (pytesseract not installed)")

# 1. CREDENTIALS (loaded from .env)
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 2. TARGET CHANNELS (loaded from .env)
TARGET_CHANNEL = int(os.getenv("TARGET_CHANNEL").strip())  # Main quiz channel
TARGET_CHAT = int(os.getenv("TARGET_CHAT").strip())  # Discussion group

# Initialize Google GenAI Client
client_ai = genai.Client(api_key=GEMINI_API_KEY)

# Initialize Telegram Userbot Session
app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH)

# ── MT5 State ──
_mt5_initialized = False

# ── Pre-warmed symbol cache: mt5_symbol -> (timestamp, data_string) ──
_symbol_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 120  # 2 minutes — daily candles barely change


# ── Expanded Exness symbol map (includes common aliases for indices) ──
SYMBOL_MAP = {
    "GOLD": "XAUUSDm", "XAUUSD": "XAUUSDm",
    "SILVER": "XAGUSDm", "XAGUSD": "XAGUSDm",
    "BTCUSD": "BTCUSDm", "BTC": "BTCUSDm", "BITCOIN": "BTCUSDm",
    "ETHUSD": "ETHUSDm", "ETH": "ETHUSDm", "ETHEREUM": "ETHUSDm",
    "EURUSD": "EURUSDm", "GBPUSD": "GBPUSDm",
    "USDJPY": "USDJPYm", "GBPJPY": "GBPJPYm",
    "EURJPY": "EURJPYm", "AUDUSD": "AUDUSDm",
    "USDCAD": "USDCADm", "USDCHF": "USDCHFm",
    "NZDUSD": "NZDUSDm", "EURGBP": "EURGBPm",
    "EURAUD": "EURAUDm", "GBPAUD": "GBPAUDm",
    "AUDCAD": "AUDCADm", "AUDJPY": "AUDJPYm",
    "CADJPY": "CADJPYm", "CHFJPY": "CHFJPYm",
    "NZDJPY": "NZDJPYm", "GBPCAD": "GBPCADm",
    "GBPCHF": "GBPCHFm", "EURNZD": "EURNZDm",
    "EURCHF": "EURCHFm", "EURCAD": "EURCADm",
    "AUDNZD": "AUDNZDm", "AUDCHF": "AUDCHFm",
    "CADCHF": "CADCHFm", "NZDCAD": "NZDCADm",
    "NZDCHF": "NZDCHFm", "GBPNZD": "GBPNZDm",
    # Indices — many aliases because Gemini says "S&P 500" or "Dow Jones"
    "US30": "US30m", "DJ30": "US30m", "DOW": "US30m", "DOWJONES": "US30m",
    "US500": "US500m", "SP500": "US500m", "SPX": "US500m", "SPX500": "US500m",
    "USTEC": "USTECm", "NAS100": "USTECm", "NASDAQ": "USTECm", "NASDAQ100": "USTECm", "NSDQ": "USTECm", "USTECH100": "USTECm",
    "DE30": "DE30m", "DAX": "DE30m", "DE40": "DE40m",
    "UK100": "UK100m", "FTSE": "UK100m",
    "JP225": "JP225m", "NIKKEI": "JP225m",
    "FR40": "FR40m", "HK50": "HK50m",
}

# Reverse lookup: "XAUUSDm" -> "XAUUSD" (for display)
_MT5_TO_TICKER = {}
for _k, _v in SYMBOL_MAP.items():
    if _v not in _MT5_TO_TICKER:
        _MT5_TO_TICKER[_v] = _k

# ── JSON Price Data (for Codespaces/Linux where MT5 doesn't work) ──
_json_prices = {}

def load_json_prices():
    """Load pre-generated prices from mt5_prices.json (for cloud deployment)"""
    global _json_prices
    json_file = "mt5_prices.json"
    
    if not os.path.exists(json_file):
        return False
    
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        print(f"📦 Loading prices from {json_file}")
        print(f"   Generated: {data.get('generated_at', 'unknown')}")
        
        # Build cache from JSON data
        for price_entry in data.get('prices', []):
            symbol = price_entry['symbol']
            timeframe = price_entry['timeframe']
            bars = price_entry['bars']
            
            # Only load D1 timeframe (daily) data
            if timeframe != 'D1':
                continue
            
            # Convert to pandas DataFrame (same format as MT5)
            df_data = []
            for bar in bars:
                df_data.append({
                    'time': pd.to_datetime(bar['time']),
                    'open': bar['open'],
                    'high': bar['high'],
                    'low': bar['low'],
                    'close': bar['close']
                })
            
            df = pd.DataFrame(df_data)
            df['day_of_week'] = df['time'].dt.dayofweek
            
            # Calculate answer key (same logic as _fetch_mt5_symbol)
            period_low = df['low'].min()
            period_high = df['high'].max()
            latest_close = df['close'].iloc[-1]
            
            weekdays = df[df['day_of_week'] <= 4]
            this_week = weekdays.tail(5) if len(weekdays) >= 5 else weekdays
            last_week = weekdays.iloc[-10:-5] if len(weekdays) >= 10 else pd.DataFrame()
            
            this_week_low = this_week['low'].min() if len(this_week) > 0 else period_low
            this_week_high = this_week['high'].max() if len(this_week) > 0 else period_high
            last_week_low = last_week['low'].min() if len(last_week) > 0 else period_low
            last_week_high = last_week['high'].max() if len(last_week) > 0 else period_high
            
            # Store formatted data
            mt5_symbol = symbol + "m" if not symbol.endswith("m") else symbol
            formatted_data = (
                f"[{mt5_symbol}] From JSON file:\n"
                f"\n>>> ANSWER KEY <<<\n"
                f"Entire Period Lowest: {period_low}\n"
                f"Entire Period Highest: {period_high}\n"
                f"Latest Close: {latest_close}\n"
                f"This Week (Mon-Fri) Lowest: {this_week_low}\n"
                f"This Week (Mon-Fri) Highest: {this_week_high}\n"
                f"Last Week (Mon-Fri) Lowest: {last_week_low}\n"
                f"Last Week (Mon-Fri) Highest: {last_week_high}"
            )
            
            _json_prices[mt5_symbol] = formatted_data
        
        print(f"   ✅ Loaded {len(_json_prices)} symbols from JSON")
        return True
    
    except Exception as e:
        print(f"   ❌ Failed to load JSON: {e}")
        return False


def ensure_mt5(force_retry: bool = False) -> bool:
    """Returns True if MT5 is ready. If force_retry, resets cached state."""
    global _mt5_initialized
    
    # If MT5 is not available (Linux/Mac), return False
    if not MT5_AVAILABLE:
        return False
    
    if force_retry:
        _mt5_initialized = False
    if not _mt5_initialized:
        _mt5_initialized = mt5.initialize()
    return _mt5_initialized


def _fetch_mt5_symbol(mt5_symbol: str) -> str | None:
    """Raw MT5 fetch for a single symbol. Returns formatted string or None."""
    mt5.symbol_select(mt5_symbol, True)
    rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_D1, 0, 14)

    if rates is None or len(rates) == 0:
        return None

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['day_of_week'] = df['time'].dt.dayofweek  # Monday=0, Friday=4

    # Use full clear labels so Gemini can reliably identify Open/Low/High/Close
    price_records = [
        f"{row['time'].strftime('%Y-%m-%d')} | Open: {row['open']} | Low: {row['low']} | High: {row['high']} | Close: {row['close']}"
        for _, row in df.iterrows()
    ]
    period_low = df['low'].min()
    period_high = df['high'].max()
    latest_close = df['close'].iloc[-1]
    
    # Trading weeks (Monday=0 to Friday=4 only)
    weekdays = df[df['day_of_week'] <= 4]
    this_week = weekdays.tail(5) if len(weekdays) >= 5 else weekdays
    last_week = weekdays.iloc[-10:-5] if len(weekdays) >= 10 else pd.DataFrame()
    
    this_week_low = this_week['low'].min() if len(this_week) > 0 else period_low
    this_week_high = this_week['high'].max() if len(this_week) > 0 else period_high
    
    last_week_low = last_week['low'].min() if len(last_week) > 0 else period_low
    last_week_high = last_week['high'].max() if len(last_week) > 0 else period_high

    return (
        f"[{mt5_symbol}] Last 14 daily candles:\n" +
        "\n".join(price_records) +
        f"\n\n>>> ANSWER KEY <<<\n"
        f"Entire Period Lowest: {period_low}\n"
        f"Entire Period Highest: {period_high}\n"
        f"Latest Close: {latest_close}\n"
        f"This Week (Mon-Fri) Lowest: {this_week_low}\n"
        f"This Week (Mon-Fri) Highest: {this_week_high}\n"
        f"Last Week (Mon-Fri) Lowest: {last_week_low}\n"
        f"Last Week (Mon-Fri) Highest: {last_week_high}"
    )


def get_market_data(ticker_symbol: str) -> str | None:
    """Fetch daily candles for a ticker. Uses cache, auto-retries MT5 on failure."""
    try:
        clean = ticker_symbol.strip().upper().replace("/", "").replace("=", "").replace("-", "").replace(" ", "")
        mt5_symbol = SYMBOL_MAP.get(clean, clean if clean.endswith("M") else clean + "m")

        # Check memory cache first
        cached = _symbol_cache.get(mt5_symbol)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]

        # Try MT5 first (if available)
        if MT5_AVAILABLE:
            if not ensure_mt5():
                # One retry in case connection went stale
                if not ensure_mt5(force_retry=True):
                    print(f"⚠️ MT5 unavailable, checking JSON fallback...")
                    # Fall through to JSON check below
            else:
                data = _fetch_mt5_symbol(mt5_symbol)
                if data:
                    _symbol_cache[mt5_symbol] = (time.time(), data)
                    return data
                else:
                    print(f"⚠️ Symbol '{mt5_symbol}' not in Market Watch.")
        
        # Try JSON fallback (for Codespaces/Linux)
        if mt5_symbol in _json_prices:
            print(f"📦 Using JSON data for {mt5_symbol}")
            data = _json_prices[mt5_symbol]
            _symbol_cache[mt5_symbol] = (time.time(), data)
            return data
        
        print(f"❌ No data available for {mt5_symbol} (not in MT5 or JSON)")
        
    except Exception as e:
        print(f"❌ Error fetching {ticker_symbol}: {e}")
    return None


def _pre_warm_cache():
    """Pre-fetch popular symbols at startup so first requests hit cache."""
    if not ensure_mt5():
        return
    for sym in ["XAUUSDm", "GBPJPYm", "EURUSDm", "BTCUSDm", "GBPUSDm", "USDJPYm",
                 "EURJPYm", "AUDUSDm", "USDCADm", "USDCHFm",
                 "US30m", "US500m", "USTECm", "GBPCHFm", "NZDUSDm"]:
        data = _fetch_mt5_symbol(sym)
        if data:
            _symbol_cache[sym] = (time.time(), data)
            print(f"  ✅ Cached {sym}")


def _resize_image(img: Image.Image, max_side: int = 768) -> Image.Image:
    """Downsample large images so Gemini upload is faster. Quality stays fine for text."""
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    ratio = max_side / max(w, h)
    return img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)


def _clean_answer(raw: str) -> str:
    """Strip markdown formatting and filler from Gemini response."""
    text = raw.strip()
    # Remove markdown bold/italic
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'_+', '', text)
    # Remove common filler prefixes
    for filler in ["The answer is ", "Answer: ", "answer: ", "Result: "]:
        if text.lower().startswith(filler.lower()):
            text = text[len(filler):]
    return text.strip()


def _extract_ticker_from_text(text: str) -> str | None:
    """Try to find a known ticker in Gemini's response using pattern matching."""
    # Strip everything except letters and digits for matching
    clean = text.upper()
    for ch in "/&. ,'\"#()":
        clean = clean.replace(ch, "")
    # Try exact known tickers first (longest first to match NASDAQ100 before NAS100)
    known = sorted(SYMBOL_MAP.keys(), key=len, reverse=True)
    for ticker in known:
        if ticker in clean:
            return ticker
    # Fallback: 6-letter uppercase block that looks like a forex pair
    match = re.search(r'[A-Z]{6}', clean)
    if match:
        return match.group(0)
    # Fallback: alphanumeric block like US500, US30
    match = re.search(r'[A-Z]{2}\d{2,3}', clean)
    if match:
        return match.group(0)
    return None


def solve_question_image(photo_bytes: BytesIO) -> str:
    """Choose OCR or Gemini based on availability and settings"""
    if OCR_AVAILABLE:
        return solve_question_with_ocr(photo_bytes)
    else:
        # OCR not available - must use Gemini
        return solve_question_with_gemini(photo_bytes)


def solve_question_with_ocr(photo_bytes: BytesIO) -> str:
    """NUCLEAR OPTION: Use OCR instead of Gemini - 10x faster!"""
    try:
        t0 = time.time()
        
        photo_bytes.seek(0)
        img = Image.open(photo_bytes)
        
        # Enhance image for better OCR
        img = img.convert('L')  # Convert to grayscale
        img = _resize_image(img, max_side=1024)  # Higher res for OCR
        
        print(f"⏱️  Image prep: {time.time()-t0:.2f}s")
        
        # Extract text using OCR (FAST: 0.1-0.3s)
        t_ocr = time.time()
        text = pytesseract.image_to_string(img, config='--psm 6').upper()
        print(f"⏱️  OCR extract: {time.time()-t_ocr:.2f}s")
        print(f"📝 Extracted text: {text[:200]}...")  # Show first 200 chars
        
        # Parse ticker from text
        ticker = None
        
        # Normalize text for better matching (remove slashes, spaces, special chars)
        normalized_text = text.replace("/", "").replace("-", "").replace(" ", "")
        
        for known_ticker in ["XAUUSD", "GOLD", "GBPJPY", "GBPUSD", "EURUSD", "USDJPY", 
                            "BTCUSD", "BITCOIN", "EURJPY", "AUDUSD", "USDCAD", "NZDUSD",
                            "USDCHF", "GBPCHF", "NASDAQ", "US500", "US30", "XAGUSD", 
                            "SILVER", "USOIL", "OIL", "CRUDE"]:
            if known_ticker in normalized_text:
                ticker = known_ticker
                break
        
        if not ticker:
            print("⚠️ No ticker found in OCR text - skipping (no Gemini fallback)")
            return None  # Skip instead of falling back to Gemini
        
        print(f"🎯 Ticker found: {ticker}")
        
        # Determine question type from text
        question_type = None
        # Remove newlines and extra spaces for better matching
        text_normalized = " ".join(text.lower().split())
        
        if ("this week" in text_normalized or "current week" in text_normalized or "thisweek" in text_normalized):
            if ("highest" in text_normalized or "high" in text_normalized or "maximum" in text_normalized):
                question_type = "THIS_WEEK_HIGH"
            elif ("lowest" in text_normalized or "low" in text_normalized or "minimum" in text_normalized):
                question_type = "THIS_WEEK_LOW"
        elif ("last week" in text_normalized or "previous week" in text_normalized or "lastweek" in text_normalized):
            if ("highest" in text_normalized or "high" in text_normalized or "maximum" in text_normalized):
                question_type = "LAST_WEEK_HIGH"
            elif ("lowest" in text_normalized or "low" in text_normalized or "minimum" in text_normalized):
                question_type = "LAST_WEEK_LOW"
        elif ("close" in text_normalized or "closing" in text_normalized):
            question_type = "LATEST_CLOSE"
        
        if not question_type:
            print("⚠️ Question type unclear - skipping (no Gemini fallback)")
            return None  # Skip instead of falling back to Gemini
        
        print(f"❓ Question type: {question_type}")
        
        # Fetch data for this ticker only
        t_fetch = time.time()
        data = get_market_data(ticker)
        if not data:
            return None
        print(f"⏱️  MT5 fetch: {time.time()-t_fetch:.2f}s")
        
        # Parse answer from data
        lines = data.split('\n')
        answer = None
        
        for line in lines:
            line = line.strip()
            if question_type == "THIS_WEEK_LOW" and "This Week" in line and "Lowest" in line:
                answer = line.split(':')[-1].strip()
            elif question_type == "THIS_WEEK_HIGH" and "This Week" in line and "Highest" in line:
                answer = line.split(':')[-1].strip()
            elif question_type == "LAST_WEEK_LOW" and "Last Week" in line and "Lowest" in line:
                answer = line.split(':')[-1].strip()
            elif question_type == "LAST_WEEK_HIGH" and "Last Week" in line and "Highest" in line:
                answer = line.split(':')[-1].strip()
            elif question_type == "LATEST_CLOSE" and "Latest Close:" in line:
                answer = line.split(':')[-1].strip()
        
        if answer:
            total_time = time.time() - t0
            print(f"⚡ OCR TOTAL TIME: {total_time:.2f}s | Answer: {answer}")
            return answer
        else:
            print("⚠️ Answer not found - skipping (no Gemini fallback)")
            return None  # Skip instead of falling back to Gemini
            
    except Exception as e:
        print(f"❌ OCR error: {e} - skipping (no Gemini fallback)")
        return None  # Skip instead of falling back to Gemini


def solve_question_with_gemini(photo_bytes: BytesIO) -> str:
    """Original Gemini-based solver (fallback)"""
    try:
        t0 = time.time()
        
        photo_bytes.seek(0)
        img = Image.open(photo_bytes)
        img = _resize_image(img)
        print(f"⏱️  Image load: {time.time()-t0:.2f}s")

        t_precompute = time.time()
        
        # Get all 16 tickers' data and build answer lookup
        top_tickers = [
            "XAUUSD", "GBPJPY", "GBPUSD", "EURUSD", "USDJPY", "BTCUSD",
            "EURJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF", "GBPCHF",
            "NASDAQ", "US500", "US30", "XAGUSD"
        ]
        
        # Build a complete answer database
        answer_db = []
        for ticker in top_tickers:
            data = get_market_data(ticker)
            if not data:
                continue
                
            # Initialize variables
            this_week_low = this_week_high = last_week_low = last_week_high = None
            period_low = period_high = latest_close = None
            
            # Parse the data to extract key values
            lines = data.split('\n')
            for line in lines:
                line = line.strip()
                if 'This Week' in line and 'Lowest' in line:
                    this_week_low = line.split(':')[-1].strip()
                elif 'This Week' in line and 'Highest' in line:
                    this_week_high = line.split(':')[-1].strip()
                elif 'Last Week' in line and 'Lowest' in line:
                    last_week_low = line.split(':')[-1].strip()
                elif 'Last Week' in line and 'Highest' in line:
                    last_week_high = line.split(':')[-1].strip()
                elif 'Entire Period Lowest:' in line:
                    period_low = line.split(':')[-1].strip()
                elif 'Entire Period Highest:' in line:
                    period_high = line.split(':')[-1].strip()
                elif 'Latest Close:' in line:
                    latest_close = line.split(':')[-1].strip()
            
            # Store all possible answers for this ticker
            answer_db.append({
                'ticker': ticker,
                'this_week_low': this_week_low,
                'this_week_high': this_week_high,
                'last_week_low': last_week_low,
                'last_week_high': last_week_high,
                'period_low': period_low,
                'period_high': period_high,
                'latest_close': latest_close
            })
        
        print(f"📊 Pre-computed answers for {len(answer_db)} tickers")
        print(f"⏱️  Pre-compute: {time.time()-t_precompute:.2f}s")
        
        # Now use Gemini ONLY to identify: ticker + question type
        # OPTIMIZED: Use smaller image (256px) and faster model
        small_img = _resize_image(img.copy(), max_side=256)
        prompt = (
            "Extract info from this trading quiz:\n"
            "1. Which symbol? (e.g. XAUUSD, GBPJPY, NASDAQ)\n"
            "2. What's asked? Reply in format: SYMBOL|TYPE\n"
            "TYPE can be: THIS_WEEK_LOW, THIS_WEEK_HIGH, LAST_WEEK_LOW, LAST_WEEK_HIGH, PERIOD_LOW, PERIOD_HIGH, LATEST_CLOSE\n"
            "Example: GBPJPY|LAST_WEEK_LOW"
        )
        
        t_gemini_start = time.time()
        response = client_ai.models.generate_content(
            model='gemini-1.5-flash',  # FIXED: Use gemini-1.5-flash (not 8b)
            contents=[prompt, small_img]
        )
        gemini_time = time.time() - t_gemini_start
        print(f"⏱️  Gemini API: {gemini_time:.2f}s")
        
        # Parse Gemini response
        result = response.text.strip().upper()
        print(f"🔎 Gemini: {result}")
        
        # Extract ticker and type
        if '|' not in result:
            print(f"⚠️ Gemini response format invalid - skipping")
            return None
            
        ticker_asked, question_type = result.split('|', 1)
        ticker_asked = ticker_asked.strip()
        question_type = question_type.strip()
        
        # Find the answer in our pre-computed database
        for entry in answer_db:
            if entry['ticker'].upper() == ticker_asked or ticker_asked in entry['ticker'].upper():
                    # Map question type to answer
                    answer_map = {
                        'THIS_WEEK_LOW': entry['this_week_low'],
                        'THIS_WEEK_HIGH': entry['this_week_high'],
                        'LAST_WEEK_LOW': entry['last_week_low'],
                        'LAST_WEEK_HIGH': entry['last_week_high'],
                        'PERIOD_LOW': entry['period_low'],
                        'PERIOD_HIGH': entry['period_high'],
                        'LATEST_CLOSE': entry['latest_close']
                    }
                    
                    answer = answer_map.get(question_type, None)
                    if answer:
                        total_time = time.time() - t0
                        print(f"⏱️  Lookup: 0.01s")
                        print(f"⚡ TOTAL TIME: {total_time:.2f}s | Answer: {answer}")
                        return answer
                    else:
                        print(f"⚠️ Question type '{question_type}' not recognized - skipping")
                        return None
        
        # If ticker not in pre-computed list, skip
        print(f"⚠️ Ticker '{ticker_asked}' not in pre-loaded list - skipping")
        return None

    except Exception as e:
        error_str = str(e)
        print(f"❌ solve_question_image error: {error_str}")
        
        # Handle specific API errors
        if "PERMISSION_DENIED" in error_str or "403" in error_str:
            print("🚨 CRITICAL: Your Gemini API key has been denied access!")
            print("   Solutions:")
            print("   1. Get a new API key from: https://aistudio.google.com/apikey")
            print("   2. Check billing status at: https://console.cloud.google.com/billing")
            print("   3. Verify project quotas at: https://console.cloud.google.com/apis/dashboard")
            return None
        
        # If rate limited, return None so we don't post garbage
        if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
            print("⏳ Rate limited — will skip this post.")
            return None
        
        return None


# ==========================================
# LISTEN TO BOTH CHANNEL AND CHAT GROUP
# ==========================================

# DEBUG LISTENER: Shows ALL messages from BOTH locations
# group=0 runs FIRST, must call continue_propagation() to let photo handler run
@app.on_message(filters.chat([TARGET_CHANNEL, TARGET_CHAT]), group=0)
async def debug_all_messages(client: Client, message: Message):
    msg_type = "📸 PHOTO" if message.photo else "💬 TEXT" if message.text else "📎 OTHER"
    sender = "?"
    if message.sender_chat:
        sender = f"channel:{message.sender_chat.username or message.sender_chat.title}"
    elif message.from_user:
        sender = f"user:{message.from_user.username or message.from_user.first_name}"
    
    chat_name = "CHANNEL" if message.chat.id == TARGET_CHANNEL else "CHAT_GROUP"
    print(f"[{time.strftime('%H:%M:%S')}] {chat_name} | {msg_type} msg#{message.id} from={sender}")
    
    # ⚡ CRITICAL: Let the photo handler also process this message!
    message.continue_propagation()

# PHOTO HANDLER: Processes images from BOTH channel and chat group
# group=1 runs AFTER debug handler
@app.on_message(filters.chat([TARGET_CHANNEL, TARGET_CHAT]) & filters.photo, group=1)
async def handle_incoming_post(client: Client, message: Message):
    t_start = time.time()
    
    chat_name = "CHANNEL" if message.chat.id == TARGET_CHANNEL else "CHAT_GROUP"
    
    # SAFETY: Only process images from official channel (not random users in chat)
    # If from chat group, only process if forwarded from official channel
    if message.chat.id == TARGET_CHAT:
        # Check if it's forwarded from the official channel or posted by channel
        is_from_official = False
        
        if message.forward_from_chat and message.forward_from_chat.id == TARGET_CHANNEL:
            is_from_official = True
            print(f"\n⚡ [IMAGE forwarded from CHANNEL to CHAT #{message.id}] Processing...")
        elif message.sender_chat and message.sender_chat.id == TARGET_CHANNEL:
            is_from_official = True
            print(f"\n⚡ [IMAGE from linked CHANNEL in CHAT #{message.id}] Processing...")
        else:
            # Random user image in chat - SKIP IT!
            sender = message.from_user.username if message.from_user else "Unknown"
            print(f"⏭️  SKIPPED: Image from random user @{sender} in chat (not official quiz)")
            return
    else:
        # Image directly from channel - always process
        print(f"\n⚡ [IMAGE from CHANNEL #{message.id}] Processing...")

    answer = None
    try:
        photo_file = await client.download_media(message, in_memory=True)
        print(f"📸 Downloaded in {time.time()-t_start:.1f}s")

        # Run blocking Gemini+MT5 work in a thread so Telegram stays responsive
        answer = await asyncio.to_thread(solve_question_image, photo_file)
    except Exception as e:
        print(f"❌ Photo handling error: {e}")

    if not answer:
        print("⚠️ No answer — skipped.")
        return

    # IMPORTANT: Always reply to the CHAT GROUP
    # If image is from channel, post as new message in chat group
    if message.chat.id == TARGET_CHANNEL:
        print(f"📢 Image from CHANNEL - posting answer to CHAT GROUP")
        try:
            await client.send_message(
                chat_id=TARGET_CHAT,
                text=f"{answer}"
            )
            print(f"🚀 [POSTED to CHAT GROUP in {time.time()-t_start:.1f}s total]")
            return
        except Exception as e:
            print(f"❌ Failed to post to chat: {e}")
            return
    
    # If image is from chat group, reply normally
    # Post reply with retry
    for attempt in range(3):
        try:
            await client.send_message(
                chat_id=message.chat.id,
                text=answer,
                reply_to_message_id=message.id
            )
            print(f"🚀 [REPLIED in {time.time()-t_start:.1f}s total]")
            return
        except Exception as e:
            print(f"❌ Send attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                await asyncio.sleep(1)

    print("❌ All send attempts failed.")


if __name__ == "__main__":
    # Try to load JSON prices first (for Codespaces)
    json_loaded = load_json_prices()
    
    # Then try MT5 (Windows only)
    if MT5_AVAILABLE:
        print("🤖 Initializing MT5 connection...")
        if mt5.initialize():
            _mt5_initialized = True
            print("✅ MT5 Connected!")
            print("📊 Pre-warming cache...")
            _pre_warm_cache()
        else:
            print(f"⚠️ MT5 Warning: {mt5.last_error()}")
            if not json_loaded:
                print("❌ CRITICAL: No MT5 and no JSON data available!")
                print("   Run generate_prices.py on Windows to create mt5_prices.json")
                sys.exit(1)
    else:
        print("⚠️ MT5 not available on this platform (Linux/Mac)")
        if not json_loaded:
            print("❌ CRITICAL: No JSON price data found!")
            print("   Run generate_prices.py on Windows, then commit mt5_prices.json to GitHub")
            sys.exit(1)
        print("✅ Using JSON price data for quiz answers")

    print(f"🤖 Listening for images on {TARGET_CHAT}...")
    app.run()

    if MT5_AVAILABLE and _mt5_initialized:
        mt5.shutdown()