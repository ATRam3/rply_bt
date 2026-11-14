"""
Quiz answer userbot (final)
---------------------------
* Prints EVERY post made in the quiz channel (text, photo, video...).
* Replies ONLY to image posts of the channel; the answer goes to the discussion group.
* Reads the question (OCR, Gemini backup), looks up REAL candles (MT5 live, or mt5_prices.json),
  and posts the number.
* NEVER guesses: if the candle data does not cover the week asked, it refuses and tells you why.
* Detects other copies of itself (same account) and warns loudly.

Test without Telegram:   python bot_final.py --test path/to/quiz.png
"""
import asyncio
import json
import logging
import os
import random
import re
import socket
import sys
import time
from collections import OrderedDict
from io import BytesIO

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bot")
logging.getLogger("pyrogram").setLevel(logging.WARNING)

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.errors import FloodWait, ChannelPrivate, PeerIdInvalid
from PIL import Image, ImageFilter, ImageOps, ImageStat
import pandas as pd

try:
    import google.genai as genai
except ImportError:
    genai = None

# ── MT5 (Windows only) ───────────────────────────────────────────────────
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
    print("✅ MT5: Available (Windows)")
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None
    print("⚠️ MT5: Not available (using mt5_prices.json)")

# ── OCR ──────────────────────────────────────────────────────────────────
OCR_AVAILABLE = False
try:
    import pytesseract
    if os.name == "nt":
        for _p in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            r"C:\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.exists(_p):
                pytesseract.pytesseract.tesseract_cmd = _p
                break
    pytesseract.get_tesseract_version()
    OCR_AVAILABLE = True
    print("✅ OCR Mode: Enabled")
except Exception as _e:
    print(f"⚠️ OCR Mode: Disabled ({_e})")


# ── Config ───────────────────────────────────────────────────────────────
def _env_int(name: str) -> int:
    v = os.getenv(name)
    if not v:
        sys.exit(f"❌ Missing {name} in .env")
    return int(v.strip())


API_ID = _env_int("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TARGET_CHANNEL = _env_int("TARGET_CHANNEL")   # quiz channel (we READ it)
TARGET_CHAT = _env_int("TARGET_CHAT")         # discussion group (we ANSWER there)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
USE_GEMINI_FALLBACK = os.getenv("USE_GEMINI_FALLBACK", "1") == "1"
HYPE_ENABLED = os.getenv("HYPE_ENABLED", "0") == "1"
SHOW_GROUP_MESSAGES = os.getenv("SHOW_GROUP_MESSAGES", "0") == "1"
client_ai = genai.Client(api_key=GEMINI_API_KEY) if (genai and GEMINI_API_KEY) else None

MAX_POST_AGE = 180
POLL_INTERVAL = 1.5
MT5_CACHE_TTL = 5
STALE_DAYS = 4
SESSION_WINDOW = 1800     # a session active in the last 30 min counts as "running"

app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH, sleep_threshold=20)

# ── State ────────────────────────────────────────────────────────────────
_mt5_initialized = False
_symbol_cache: dict[str, tuple[float, dict]] = {}
_json_frames: dict[str, tuple[pd.DataFrame, int]] = {}
_json_meta = {"generated_at": None, "mtime": None}

_SEEN_MAX = 1000
_seen: "OrderedDict[tuple, float]" = OrderedDict()


def _claim(key: tuple) -> bool:
    """True the first time a key is seen, False afterwards."""
    if key in _seen:
        return False
    _seen[key] = time.time()
    while len(_seen) > _SEEN_MAX:
        _seen.popitem(last=False)
    return True


# ── Symbol map ───────────────────────────────────────────────────────────
SYMBOL_MAP = {
    "GOLD": "XAUUSDm", "XAUUSD": "XAUUSDm",
    "SILVER": "XAGUSDm", "XAGUSD": "XAGUSDm",
    "USOIL": "USOILm", "OIL": "USOILm", "CRUDE": "USOILm", "WTI": "USOILm",
    "UKOIL": "UKOILm", "BRENT": "UKOILm",
    "BTCUSD": "BTCUSDm", "BTC": "BTCUSDm", "BITCOIN": "BTCUSDm",
    "ETHUSD": "ETHUSDm", "ETH": "ETHUSDm", "ETHEREUM": "ETHUSDm",
    "LTCUSD": "LTCUSDm", "LTC": "LTCUSDm", "LITECOIN": "LTCUSDm",
    "XRPUSD": "XRPUSDm", "XRP": "XRPUSDm", "RIPPLE": "XRPUSDm",
    "EURUSD": "EURUSDm", "GBPUSD": "GBPUSDm", "USDJPY": "USDJPYm",
    "USDCHF": "USDCHFm", "AUDUSD": "AUDUSDm", "USDCAD": "USDCADm",
    "NZDUSD": "NZDUSDm",
    "EURJPY": "EURJPYm", "GBPJPY": "GBPJPYm", "EURGBP": "EURGBPm",
    "AUDJPY": "AUDJPYm", "GBPCHF": "GBPCHFm", "EURCHF": "EURCHFm",
    "EURAUD": "EURAUDm", "GBPAUD": "GBPAUDm", "AUDCAD": "AUDCADm",
    "CADJPY": "CADJPYm", "CHFJPY": "CHFJPYm", "NZDJPY": "NZDJPYm",
    "GBPCAD": "GBPCADm", "EURNZD": "EURNZDm", "EURCAD": "EURCADm",
    "AUDNZD": "AUDNZDm", "AUDCHF": "AUDCHFm", "CADCHF": "CADCHFm",
    "NZDCAD": "NZDCADm", "NZDCHF": "NZDCHFm", "GBPNZD": "GBPNZDm",
    "US30": "US30m", "DJ30": "US30m", "DOW": "US30m", "DOWJONES": "US30m", "DOWINDUSTRIAL": "US30m",
    "US500": "US500m", "SP500": "US500m", "SPX": "US500m", "SPX500": "US500m", "SANDP": "US500m",
    "USTEC": "USTECm", "NAS100": "USTECm", "NASDAQ": "USTECm", "NASDAQ100": "USTECm", "NSDQ": "USTECm",
    "USTECH100": "USTECm", "TECH100": "USTECm",
    "US2000": "US2000m", "RUSSELL2000": "US2000m", "RUSSELL": "US2000m",
    "DE30": "DE30m", "DAX": "DE30m", "DAX30": "DE30m", "GERMANY30": "DE30m", "GERMAN30": "DE30m",
    "DE40": "DE40m", "DAX40": "DE40m", "GERMANY40": "DE40m", "GERMAN40": "DE40m",
    "UK100": "UK100m", "FTSE": "UK100m", "FTSE100": "UK100m",
    "FR40": "FR40m", "CAC": "FR40m", "CAC40": "FR40m", "FRANCE40": "FR40m", "FRENCH40": "FR40m",
    "ES35": "ES35m", "IBEX": "ES35m", "IBEX35": "ES35m", "SPAIN35": "ES35m", "SPANISH35": "ES35m",
    "IT40": "IT40m", "FTSEMIB": "IT40m", "ITALY40": "IT40m", "ITALIAN40": "IT40m",
    "EU50": "EU50m", "EUROSTOXX": "EU50m", "EUROSTOXX50": "EU50m", "STOXX50": "EU50m",
    "JP225": "JP225m", "NIKKEI": "JP225m", "NIKKEI225": "JP225m", "JAPAN225": "JP225m", "JPN225": "JP225m",
    "HK50": "HK50m", "HANGSENG": "HK50m", "HANGSENG50": "HK50m", "HONGKONG50": "HK50m", "HSI": "HK50m",
    "CN50": "CN50m", "CHINA50": "CN50m", "CHINAA50": "CN50m",
    "AU200": "AU200m", "ASX200": "AU200m", "AUSTRALIA200": "AU200m", "AUSSIE200": "AU200m",
}
CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "XAU", "XAG"}


# ═════════════════════════════════════════════════════════════════════════
# MARKET DATA  (strict: never guesses)
# ═════════════════════════════════════════════════════════════════════════

def _infer_digits(series) -> int:
    best = 0
    for v in series:
        s = f"{float(v):.8f}".rstrip("0")
        best = max(best, len(s.split(".")[1]) if "." in s else 0)
    return min(best, 6)


def _build_keys(df: pd.DataFrame, digits: int, now: pd.Timestamp | None = None) -> dict:
    """
    'This week' = Mon-Fri of the CURRENT calendar week; 'last week' = the week before.
    A week with no candles gives None (NOT a fallback to some other period).
    """
    df = df.sort_values("time").reset_index(drop=True).copy()
    df["time"] = pd.to_datetime(df["time"])
    df["dow"] = df["time"].dt.dayofweek
    now = now if now is not None else pd.Timestamp.now()

    weekdays = df[df["dow"] <= 4]
    this_monday = (now - pd.Timedelta(days=now.dayofweek)).normalize()
    last_monday = this_monday - pd.Timedelta(days=7)

    def week_of(monday):
        return weekdays[(weekdays["time"] >= monday) & (weekdays["time"] < monday + pd.Timedelta(days=5))]

    this_week, last_week = week_of(this_monday), week_of(last_monday)

    def lo(x):
        return float(x["low"].min()) if len(x) else None

    def hi(x):
        return float(x["high"].max()) if len(x) else None

    return {
        "digits": digits,
        "now": now,
        "period_low": float(df["low"].min()),
        "period_high": float(df["high"].max()),
        "latest_close": float(df["close"].iloc[-1]),
        "this_week_low": lo(this_week),
        "this_week_high": hi(this_week),
        "last_week_low": lo(last_week),
        "last_week_high": hi(last_week),
        "this_count": len(this_week),
        "last_count": len(last_week),
        "this_monday": this_monday,
        "last_monday": last_monday,
        "last_candle": df["time"].iloc[-1],
        "source": "?",
    }


def _answer_from_data(data: dict, question_type: str) -> tuple[str | None, str]:
    """Returns (answer or None, explanation). Refuses when the data cannot be trusted."""
    now = data["now"]
    weekend = now.dayofweek >= 5
    tm, lm = data["this_monday"], data["last_monday"]
    info = (f"{question_type} | source={data['source']} | last candle {data['last_candle'].date()} | "
            f"this week {tm.date()}..{(tm + pd.Timedelta(days=4)).date()} ({data['this_count']} candles) | "
            f"last week {lm.date()}..{(lm + pd.Timedelta(days=4)).date()} ({data['last_count']} candles)")

    if question_type.startswith("THIS_WEEK"):
        if data["this_count"] == 0:
            return None, f"🛑 REFUSING: no candles for the current week — data is STALE. {info}"
        if weekend and data["this_count"] < 4:
            return None, f"🛑 REFUSING: only {data['this_count']} candles this week on a weekend — data incomplete. {info}"
    elif question_type.startswith("LAST_WEEK"):
        if data["last_count"] < 3:
            return None, f"🛑 REFUSING: only {data['last_count']} candles for last week — data incomplete/stale. {info}"

    value = data.get(question_type.lower())
    if value is None:
        return None, f"🛑 REFUSING: no value for {question_type}. {info}"
    return f"{value:.{data['digits']}f}", info


# ── JSON fallback ────────────────────────────────────────────────────────
def load_json_prices() -> bool:
    json_file = "mt5_prices.json"
    if not os.path.exists(json_file):
        return False
    try:
        with open(json_file, "r") as f:
            data = json.load(f)
        frames = {}
        for entry in data.get("prices", []):
            if entry.get("timeframe") != "D1" or not entry.get("bars"):
                continue
            df = pd.DataFrame(
                [{"time": pd.to_datetime(b["time"]), "open": b["open"], "high": b["high"],
                  "low": b["low"], "close": b["close"]} for b in entry["bars"]]
            )
            sym = entry["symbol"]
            mt5_symbol = sym if sym.endswith("m") else sym + "m"
            digits = entry.get("digits")
            if digits is None:
                digits = _infer_digits(pd.concat([df["low"], df["high"], df["close"]]))
            frames[mt5_symbol] = (df, int(digits))

        _json_frames.clear()
        _json_frames.update(frames)
        _json_meta["generated_at"] = data.get("generated_at", "unknown")
        _json_meta["mtime"] = os.path.getmtime(json_file)
        _symbol_cache.clear()
        print(f"📦 Loaded {json_file}: {len(frames)} symbols (generated {_json_meta['generated_at']})")
        return bool(frames)
    except Exception as e:
        print(f"❌ Failed to load JSON: {e}")
        return False


def _maybe_reload_json():
    """After a `git pull` the new file is picked up automatically — no restart needed."""
    try:
        m = os.path.getmtime("mt5_prices.json")
        if _json_meta["mtime"] is not None and m != _json_meta["mtime"]:
            print("🔁 mt5_prices.json changed — reloading")
            load_json_prices()
    except OSError:
        pass


# ── MT5 ──────────────────────────────────────────────────────────────────
def ensure_mt5(force_retry: bool = False) -> bool:
    global _mt5_initialized
    if not MT5_AVAILABLE:
        return False
    if force_retry:
        _mt5_initialized = False
    if not _mt5_initialized:
        _mt5_initialized = bool(mt5.initialize())
    return _mt5_initialized


def _fetch_mt5_symbol(mt5_symbol: str) -> dict | None:
    mt5.symbol_select(mt5_symbol, True)
    rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_D1, 0, 30)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    info = mt5.symbol_info(mt5_symbol)
    data = _build_keys(df, info.digits if info else 5)
    data["source"] = "MT5 live"
    return data


def _resolve_symbol(ticker: str) -> str:
    clean = re.sub(r"[^A-Z0-9]", "", ticker.upper())
    if clean in SYMBOL_MAP:
        return SYMBOL_MAP[clean]
    return clean[:-1] + "m" if clean.endswith("M") else clean + "m"


def get_market_data(ticker: str) -> dict | None:
    try:
        mt5_symbol = _resolve_symbol(ticker)
        cached = _symbol_cache.get(mt5_symbol)
        if cached and (time.time() - cached[0]) < MT5_CACHE_TTL:
            return cached[1]

        data = None
        if MT5_AVAILABLE:
            if ensure_mt5() or ensure_mt5(force_retry=True):
                data = _fetch_mt5_symbol(mt5_symbol)
                if data:
                    _symbol_cache[mt5_symbol] = (time.time(), data)
                else:
                    print(f"⚠️ '{mt5_symbol}' not in Market Watch — trying JSON")
            else:
                print("⚠️ MT5 unavailable — trying JSON")

        if data is None and mt5_symbol in _json_frames:
            df, digits = _json_frames[mt5_symbol]
            data = _build_keys(df, digits)
            data["source"] = f"JSON generated {_json_meta['generated_at']}"

        if data is None:
            print(f"❌ No data for {mt5_symbol} (not in MT5 or JSON)")
            return None
        data["symbol"] = mt5_symbol
        return data
    except Exception as e:
        print(f"❌ Error fetching {ticker}: {e}")
        return None


def _pre_warm_cache():
    if not ensure_mt5():
        return
    for sym in ["XAUUSDm", "GBPJPYm", "EURUSDm", "BTCUSDm", "GBPUSDm", "USDJPYm",
                "EURJPYm", "AUDUSDm", "USDCADm", "USDCHFm", "US30m", "US500m",
                "USTECm", "GBPCHFm", "NZDUSDm", "DE40m", "UK100m", "FR40m", "XAGUSDm"]:
        if mt5.symbol_select(sym, True):
            print(f"  ✅ Selected {sym}")


def _lookup(ticker: str, qtype: str) -> str | None:
    data = get_market_data(ticker)
    if not data:
        return None
    answer, info = _answer_from_data(data, qtype)
    print(f"{'🧮' if answer else ''} {data.get('symbol', ticker)} → {answer} | {info}")
    return answer


# ═════════════════════════════════════════════════════════════════════════
# QUESTION PARSING
# ═════════════════════════════════════════════════════════════════════════

_INDEX_RE = re.compile(r"(US|DE|UK|FR|ES|IT|EU|JP|HK|CN|AU)\d{2,4}")


def _find_ticker(text: str) -> str | None:
    tokens = re.sub(r"[^A-Z0-9]+", " ", text.upper()).split()
    for i, tok in enumerate(tokens):
        if len(tok) >= 3 and tok in SYMBOL_MAP:
            return tok
        for n in (2, 3):                       # 'XAU USD', 'S&P 500'
            if i + n <= len(tokens):
                joined = "".join(tokens[i:i + n])
                if len(joined) >= 4 and joined in SYMBOL_MAP:
                    return joined
        if re.fullmatch(r"[A-Z]{6}", tok) and tok[:3] in CURRENCIES and tok[3:] in CURRENCIES and tok[:3] != tok[3:]:
            return tok
        if _INDEX_RE.fullmatch(tok):
            return tok
    return None


def _parse_question_type(text: str) -> str | None:
    t = " ".join(text.lower().split())

    def pos(pattern):
        m = re.search(pattern, t)
        return m.start() if m else None

    this_pos = pos(r"\b(this|current)\s*week")
    last_pos = pos(r"\b(last|previous|past)\s*week")
    hi = pos(r"\b(highest|high|maximum|max|peak)\b")
    lo = pos(r"\b(lowest|low|minimum|min)\b")
    cl = pos(r"\b(close|closing|closed)\b")

    if hi is None and lo is None:
        return "LATEST_CLOSE" if cl is not None else None

    side = "HIGH" if (lo is None or (hi is not None and hi < lo)) else "LOW"
    week = "LAST" if (last_pos is not None and (this_pos is None or last_pos < this_pos)) else "THIS"
    return f"{week}_WEEK_{side}"


# ═════════════════════════════════════════════════════════════════════════
# OCR + GEMINI
# ═════════════════════════════════════════════════════════════════════════

def _prep_for_ocr(img: Image.Image, binarize: bool) -> Image.Image:
    g = img.convert("L")
    if g.width < 1000:
        f = 1000 / g.width
        g = g.resize((int(g.width * f), int(g.height * f)), Image.LANCZOS)
    elif g.width > 1800:
        f = 1800 / g.width
        g = g.resize((int(g.width * f), int(g.height * f)), Image.LANCZOS)
    g = ImageOps.autocontrast(g)
    if ImageStat.Stat(g).mean[0] < 110:      # dark card -> invert (Tesseract wants dark-on-light)
        g = ImageOps.invert(g)
    if binarize:
        g = g.filter(ImageFilter.SHARPEN).point(lambda x: 255 if x > 140 else 0)
    return g


def solve_with_ocr(img: Image.Image) -> str | None:
    t0 = time.time()
    all_text, ticker, qtype = [], None, None

    for binarize, psm in [(False, 6), (True, 6), (False, 11), (True, 3)]:
        try:
            text = pytesseract.image_to_string(_prep_for_ocr(img, binarize), config=f"--psm {psm}").strip()
        except Exception as e:
            logger.warning(f"OCR pass failed (psm {psm}): {e}")
            continue
        if not text:
            continue
        all_text.append(text)
        ticker, qtype = _find_ticker(text), _parse_question_type(text)
        if ticker and qtype:
            break

    if not (ticker and qtype) and all_text:
        merged = "\n".join(all_text)
        ticker = ticker or _find_ticker(merged)
        qtype = qtype or _parse_question_type(merged)

    print("📝 OCR text:\n" + ("\n".join(all_text)[:600] or "(nothing read)"))
    print(f"⏱️  OCR {time.time()-t0:.2f}s | ticker={ticker} | type={qtype}")
    if not ticker or not qtype:
        return None
    return _lookup(ticker, qtype)


def solve_with_gemini(img: Image.Image) -> str | None:
    if not client_ai:
        return None
    try:
        small = img.copy()
        small.thumbnail((768, 768))
        prompt = (
            "This is a trading quiz image. Reply ONLY in the format SYMBOL|TYPE.\n"
            "SYMBOL: the instrument ticker (e.g. XAUUSD, GBPJPY, NASDAQ).\n"
            "TYPE: one of THIS_WEEK_LOW, THIS_WEEK_HIGH, LAST_WEEK_LOW, LAST_WEEK_HIGH, "
            "PERIOD_LOW, PERIOD_HIGH, LATEST_CLOSE.\nExample: GBPJPY|LAST_WEEK_LOW"
        )
        resp = client_ai.models.generate_content(model=GEMINI_MODEL, contents=[prompt, small])
        result = (resp.text or "").strip().upper()
        print(f"🔎 Gemini: {result}")
        if "|" not in result:
            return None
        symbol, qtype = [p.strip() for p in result.split("|", 1)]
        return _lookup(symbol, qtype)
    except Exception as e:
        print(f"❌ Gemini error: {e}")
        return None


def solve_question_image(photo_bytes: BytesIO) -> str | None:
    photo_bytes.seek(0)
    img = Image.open(photo_bytes)
    img.load()
    answer = solve_with_ocr(img) if OCR_AVAILABLE else None
    if answer is None and USE_GEMINI_FALLBACK:
        answer = solve_with_gemini(img)
    return answer


# ═════════════════════════════════════════════════════════════════════════
# DUPLICATE GUARD ACROSS COPIES (other PC / Codespaces / old script, same account)
# ═════════════════════════════════════════════════════════════════════════

_NUM_RE = re.compile(r"^-?\d[\d.,]*$")


async def _own_numeric_posts(client: Client, since_ts: float) -> list[tuple[int, str]]:
    """Answers (numbers) that THIS ACCOUNT already posted in the group since `since_ts`."""
    found = []
    try:
        async for m in client.get_chat_history(TARGET_CHAT, limit=20):
            if m.date and m.date.timestamp() < since_ts:
                break
            txt = (m.text or "").strip()
            if getattr(m, "outgoing", False) and _NUM_RE.match(txt):
                found.append((m.id, txt))
    except Exception as e:
        logger.warning(f"duplicate-guard history read failed: {e}")
    return found


async def _audit_after(client: Client, since_ts: float, mine: str):
    await asyncio.sleep(4)
    posts = await _own_numeric_posts(client, since_ts)
    if len(posts) > 1:
        texts = ", ".join(t for _, t in posts)
        print(f"🚨 DUPLICATES: this account posted {len(posts)} answers for this quiz: [{texts}] "
              f"(mine was {mine}). ANOTHER COPY OF THE BOT IS RUNNING — stop it!")


async def _warn_other_sessions(client: Client):
    """Lists other sessions of this account that use the same API ID and were active recently."""
    try:
        from pyrogram.raw.functions.account import GetAuthorizations
        res = await client.invoke(GetAuthorizations())
        now = time.time()
        others = []
        for a in res.authorizations:
            if getattr(a, "current", False) or getattr(a, "api_id", None) != API_ID:
                continue
            if now - getattr(a, "date_active", 0) > SESSION_WINDOW:
                continue
            ago = int((now - a.date_active) / 60)
            others.append(f"{a.device_model} / {a.platform} / ip {a.ip} ({a.country}) — active {ago} min ago")
        if others:
            print("🚨 OTHER COPIES OF THIS BOT MAY BE RUNNING (same API ID, same account):")
            for o in others:
                print(f"     • {o}")
            print("   Stop them (old terminals, Codespaces, other PC) or you will get double answers.\n")
        else:
            print("✅ No other recent session found for this API ID")
    except Exception as e:
        logger.warning(f"session check skipped: {e}")


# ═════════════════════════════════════════════════════════════════════════
# CHANNEL POST HANDLING
# ═════════════════════════════════════════════════════════════════════════

def _post_kind(m: Message) -> str:
    if m.photo:
        return "📸 PHOTO"
    if m.video:
        return "🎬 VIDEO"
    if m.document:
        return "📄 DOCUMENT"
    if m.poll:
        return "📊 POLL"
    if m.sticker:
        return "🏷️ STICKER"
    if m.animation:
        return "🎞️ GIF"
    if m.audio or m.voice:
        return "🎵 AUDIO"
    if m.text:
        return "💬 TEXT"
    return f"📎 {m.media.name if m.media else 'OTHER'}"


def _is_image(m: Message) -> bool:
    if m.photo:
        return True
    return bool(m.document and (m.document.mime_type or "").startswith("image/"))


async def handle_channel_post(client: Client, message: Message, source: str):
    """Called by BOTH the push handler and the poller; the first to see a post wins."""
    if not _claim(("post", message.id)):
        print(f"   ⚠️ [{source}] SKIP #{message.id} - already processed by another handler")
        return

    preview = (message.text or message.caption or "").replace("\n", " ")[:80]
    print(f"\n📨 [{source}] CHANNEL POST #{message.id} | {_post_kind(message)} | {preview}")

    if not _is_image(message):
        print("   ↳ not an image — no reply")
        return

    post_ts = message.date.timestamp() if message.date else time.time() - 5
    if time.time() - post_ts > MAX_POST_AGE:
        print("   ↳ image is too old — no reply")
        return

    t_start = time.time()
    answer = None
    try:
        photo = await client.download_media(message, in_memory=True)
        answer = await asyncio.to_thread(solve_question_image, photo)
        if answer:
            print(f"   ✅ Calculated answer: {answer}")
    except Exception as e:
        print(f"❌ Image handling error: {e}")

    if not answer:
        print("   ↳ no trustworthy answer — nothing posted")
        return

    # Cross-copy guard: did this account (another copy) already answer this quiz?
    await asyncio.sleep(random.uniform(0.15, 0.6))
    existing = await _own_numeric_posts(client, post_ts - 3)
    if existing:
        texts = [t for _, t in existing]
        if answer in texts:
            print(f"   ↳ another copy already posted the same answer {answer} — skipping")
            return
        print(f"🚨 CONFLICT: another copy of this account posted {texts} but I computed {answer}. "
              f"Posting mine too — and you must stop the other copy!")

    try:
        await client.send_message(TARGET_CHAT, answer)
        print(f"🚀 POSTED {answer} to group in {time.time()-t_start:.1f}s")
        asyncio.create_task(_audit_after(client, post_ts - 3, answer))
    except FloodWait as fw:
        await asyncio.sleep(fw.value)
        try:
            await client.send_message(TARGET_CHAT, answer)
            print(f"🚀 POSTED {answer} (after FloodWait)")
        except Exception as e2:
            print(f"❌ Failed after FloodWait: {e2}")
    except Exception as e:
        print(f"❌ Failed to post to group: {e}")


@app.on_message(filters.chat(TARGET_CHANNEL), group=0)
async def on_channel_message(client: Client, message: Message):
    await handle_channel_post(client, message, "PUSH")


@app.on_message(filters.chat(TARGET_CHAT), group=1)
async def on_group_message(client: Client, message: Message):
    if SHOW_GROUP_MESSAGES:
        who = (message.from_user.first_name if message.from_user
               else message.sender_chat.title if message.sender_chat else "?")
        preview = (message.text or message.caption or "").replace("\n", " ")[:60]
        print(f"   💬 [GROUP] #{message.id} {_post_kind(message)} from {who}: {preview}")


HYPE_MESSAGES = ["Let's gooo! 🔥", "LET'S GO! 💪", "Ready! Let's goooo! 🚀", "ተዘጋጅቻለሁ! 🔥"]
HYPE_KEYWORDS = ["ተዘጋጁ", "ይቀርባል", "quiz time", "get ready"]
_last_hype = 0.0


@app.on_message(filters.chat(TARGET_CHANNEL) & filters.text, group=2)
async def hype_handler(client: Client, message: Message):
    global _last_hype
    if not HYPE_ENABLED:
        return
    low = (message.text or "").lower()
    if not any(k in low for k in HYPE_KEYWORDS):
        return
    if time.time() - _last_hype < 600 or not _claim(("hype", message.id)):
        return
    _last_hype = time.time()
    await asyncio.sleep(random.uniform(2, 4))
    try:
        await client.send_message(TARGET_CHAT, random.choice(HYPE_MESSAGES))
    except Exception as e:
        print(f"❌ Hype error: {e}")


# ═════════════════════════════════════════════════════════════════════════
# POLLING SAFETY NET + KEEP ONLINE
# ═════════════════════════════════════════════════════════════════════════

async def _poll_channel(client: Client):
    logger.info("🔄 Polling safety net started")
    last_seen: int | None = None
    delay = POLL_INTERVAL

    while True:
        try:
            _maybe_reload_json()
            new = []
            async for msg in client.get_chat_history(TARGET_CHANNEL, limit=5):
                if last_seen is not None and msg.id <= last_seen:
                    break
                new.append(msg)

            if last_seen is None:
                last_seen = new[0].id if new else 0
                for m in new:
                    _claim(("post", m.id))          # seed only; never answer old posts
                logger.info(f"🔄 Poll seeded at #{last_seen}")
            else:
                for msg in reversed(new):
                    last_seen = max(last_seen, msg.id)
                    await handle_channel_post(client, msg, "POLL")
            delay = POLL_INTERVAL
        except FloodWait as fw:
            await asyncio.sleep(fw.value + 1)
            continue
        except Exception as e:
            logger.warning(f"🔄 Poll error: {e} — retry in {delay:.0f}s")
            delay = min(delay * 2, 30)
        await asyncio.sleep(delay)


async def _keep_online(client: Client):
    from pyrogram.raw.functions.account import UpdateStatus
    while True:
        try:
            await client.invoke(UpdateStatus(offline=False))
        except FloodWait as fw:
            await asyncio.sleep(fw.value)
        except Exception as e:
            logger.warning(f"🟢 keep_online error: {e}")
        await asyncio.sleep(240)


# ═════════════════════════════════════════════════════════════════════════
# STARTUP / MAIN
# ═════════════════════════════════════════════════════════════════════════

async def _startup_checks(client: Client):
    print("\n🔍 STARTUP CHECKS")
    found = {TARGET_CHANNEL: False, TARGET_CHAT: False}
    try:
        async for dialog in client.get_dialogs():
            if dialog.chat.id in found:
                found[dialog.chat.id] = True
                print(f"   ✅ Found: {dialog.chat.title} ({dialog.chat.id})")
    except Exception as e:
        print(f"   ❌ Error loading dialogs: {e}")

    for chat_id, ok in found.items():
        if ok:
            continue
        try:
            ch = await client.get_chat(chat_id)
            print(f"   ✅ Resolved: {ch.title}")
        except ChannelPrivate:
            sys.exit(f"❌ {chat_id} is private and this account is not a member — join it in the Telegram app.")
        except PeerIdInvalid:
            sys.exit(f"❌ {chat_id}: peer id invalid — check the ID in .env.")
        except Exception as e:
            sys.exit(f"❌ Cannot resolve {chat_id}: {e}")

    me = await client.get_me()
    print(f"👤 Logged in as: {me.first_name} (@{me.username or 'no-username'})")
    await _warn_other_sessions(client)
    print(f"✅ Watching channel {TARGET_CHANNEL} | answering images in group {TARGET_CHAT}")
    print(f"   Hype: {'ON' if HYPE_ENABLED else 'OFF'} | Gemini fallback: "
          f"{'ON' if (USE_GEMINI_FALLBACK and client_ai) else 'OFF'} | "
          f"Data: {'MT5 live' if MT5_AVAILABLE else 'JSON ' + str(_json_meta['generated_at'])}\n")


def _single_instance_lock():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 47831))
    except OSError:
        sys.exit("❌ Another copy of this bot is already running on this machine. Close it first.")
    return s


async def main():
    json_loaded = load_json_prices()

    if MT5_AVAILABLE:
        if ensure_mt5():
            print("✅ MT5 Connected!")
            _pre_warm_cache()
        else:
            print(f"⚠️ MT5 not ready: {mt5.last_error()}")
            if not json_loaded:
                sys.exit("❌ No MT5 and no JSON data available!")
    elif not json_loaded:
        sys.exit("❌ No mt5_prices.json — run price_generator.py on the MT5 PC first.")

    await app.start()
    await _startup_checks(app)
    
    # Warn about other active sessions
    print("\n🔍 Checking for other bot sessions...")
    await _warn_other_sessions(app)

    tasks = [asyncio.create_task(_poll_channel(app)), asyncio.create_task(_keep_online(app))]
    print("🤖 Bot is running. Press Ctrl+C to stop.\n")
    try:
        await idle()
    finally:
        for t in tasks:
            t.cancel()
        await app.stop()
        if MT5_AVAILABLE and _mt5_initialized:
            mt5.shutdown()
        print("👋 Bot stopped.")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--test":
        load_json_prices()
        if MT5_AVAILABLE:
            ensure_mt5()
        with open(sys.argv[2], "rb") as fh:
            print("\n➡️ ANSWER:", solve_question_image(BytesIO(fh.read())))
        sys.exit(0)

    _lock = _single_instance_lock()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bye!")