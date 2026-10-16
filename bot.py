import asyncio
import sys

# Fix Windows terminal encoding so emoji in print() never crashes
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


from io import BytesIO
from pyrogram import Client, filters
from pyrogram.types import Message
import google.genai as genai
from PIL import Image
import MetaTrader5 as mt5
import pandas as pd

# 1. YOUR CREDENTIALS
API_ID = TELEGRAM_API_ID_VALUE                          
API_HASH = "TELEGRAM_API_HASH_VALUE" 
GEMINI_API_KEY = "GEMINI_KEY_VALUE" 

# 2. TARGET CHANNEL
TARGET_CHAT = -1002044038089           

# Initialize Google GenAI Client
client_ai = genai.Client(api_key=GEMINI_API_KEY)

# Initialize Telegram Userbot Session
app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH)

# Cache MT5 init state — avoids slow terminal_info() check on every message
_mt5_initialized = False

def ensure_mt5() -> bool:
    """Returns True if MT5 is ready, using a cached flag for speed."""
    global _mt5_initialized
    if not _mt5_initialized:
        _mt5_initialized = mt5.initialize()
    return _mt5_initialized

def get_market_data_answer(ticker_symbol: str) -> str:
    """Fetches exact daily candles instantly using the persistent MT5 connection."""
    try:
        clean_symbol = ticker_symbol.strip().upper().replace("/", "").replace("=", "").replace("-", "").replace(" ", "")
        
        # O(1) dict lookup instead of sequential if/elif
        symbol_map = {
            "GOLD": "XAUUSDm", "XAUUSD": "XAUUSDm",
            "SILVER": "XAGUSDm", "XAGUSD": "XAGUSDm",
            "BTCUSD": "BTCUSDm", "BTC": "BTCUSDm",
            "ETHUSD": "ETHUSDm", "ETH": "ETHUSDm",
        }
        mt5_symbol = symbol_map.get(clean_symbol, clean_symbol if clean_symbol.endswith("M") else clean_symbol + "m")

        if not ensure_mt5():
            print("❌ MT5 not available.")
            return None

        mt5.symbol_select(mt5_symbol, True)
        rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_D1, 0, 14)

        if rates is not None and len(rates) > 0:
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')

            price_records = [
                f"Date: {row['time'].strftime('%Y-%m-%d')} | Low: {row['low']:.3f} | High: {row['high']:.3f} | Close: {row['close']:.3f}"
                for _, row in df.iterrows()
            ]
            absolute_low = df['low'].min()
            absolute_high = df['high'].max()

            print(f"📊 [EXNESS INSTANT FEED] {mt5_symbol} fetched successfully.")
            return (
                f"Official Exness Daily Candles for {mt5_symbol} (Last 14 Days):\n" +
                "\n".join(price_records) +
                f"\n\nAbsolute Lowest Price in Period: {absolute_low:.3f}\n"
                f"Absolute Highest Price in Period: {absolute_high:.3f}"
            )
        else:
            print(f"⚠️ Symbol '{mt5_symbol}' not found in Market Watch.")
    except Exception as e:
        print(f"❌ MT5 Fetch Error for {ticker_symbol}: {e}")
    return None

def solve_question_image(photo_bytes: BytesIO) -> str:
    """Processes image from memory, fetches MT5 data, and queries Gemini."""
    try:
        img = Image.open(photo_bytes)
        
        # Step 1: Extract ticker + question from image
        extract_prompt = (
            "Analyze this trading quiz image. "
            "1. Identify the asset symbol/ticker being asked about (e.g., EURUSD, XAUUSD, BTCUSD). "
            "2. Identify the exact question text. "
            "Output strictly in this format: TICKER: <symbol> | QUESTION: <question text>"
        )
        query_response = client_ai.models.generate_content(
            model='gemini-2.5-flash',
            contents=[extract_prompt, img]
        )
        extracted_text = query_response.text.strip()
        print(f"🔎 [EXTRACTED DATA]: {extracted_text}")
        
        ticker_symbol = "XAUUSD"
        question_text = extracted_text
        
        if "|" in extracted_text:
            parts = extracted_text.split("|")
            for part in parts:
                if "TICKER:" in part:
                    ticker_symbol = part.replace("TICKER:", "").strip()
                elif "QUESTION:" in part:
                    question_text = part.replace("QUESTION:", "").strip()

        # Step 2: Fetch live MT5 data (local — nearly instant)
        market_context = get_market_data_answer(ticker_symbol)
        
        # Step 3: Answer the question
        if market_context:
            final_prompt = (
                f"Official Exness Terminal Data:\n{market_context}\n\n"
                f"Question: {question_text}\n\n"
                "Based strictly on this official Exness terminal data, what is the exact numerical answer? "
                "Provide ONLY the final short number or answer (e.g., 4073.195), with zero explanation or text."
            )
        else:
            final_prompt = (
                f"Question: {question_text}\n"
                "Provide ONLY the correct, direct answer clearly and concisely."
            )

        response = client_ai.models.generate_content(
            model='gemini-2.5-flash',
            contents=[final_prompt]
        )
        return response.text.strip()
        
    except Exception as e:
        print(f"❌ Error analyzing image: {e}")
        return None

def solve_question_text(question: str) -> str:
    """Answers a plain text question — runs in a thread to avoid blocking event loop."""
    try:
        response = client_ai.models.generate_content(
            model='gemini-2.5-flash',
            contents=[f"Provide ONLY the direct answer to this question: {question}"]
        )
        return response.text.strip()
    except Exception as e:
        print(f"❌ Error answering text question: {e}")
        return None

@app.on_message(filters.chat(TARGET_CHAT) & (filters.photo | filters.text))
async def handle_incoming_post(client: Client, message: Message):
    print(f"\n⚡ [NEW POST DETECTED - ID: {message.id}] Processing...")

    answer = ""

    if message.photo:
        print("📸 Downloading photo to RAM...")
        try:
            photo_file = await client.download_media(message, in_memory=True)
            print("🔍 [SOLVING] Processing image and instant Exness data...")
            # Run in thread — keeps event loop free for other incoming messages
            answer = await asyncio.to_thread(solve_question_image, photo_file)
            print(f"✅ [ANSWER GENERATED]: {answer}")
        except Exception as e:
            print(f"❌ Error handling photo: {e}")

    elif message.text:
        print(f"📝 Text Question Detected: {message.text[:80]}...")
        try:
            # Run in thread — was previously blocking the event loop
            answer = await asyncio.to_thread(solve_question_text, message.text)
            print(f"✅ [ANSWER GENERATED]: {answer}")
        except Exception as e:
            print(f"Error: {e}")

    # Only post if we have a clean answer — never post errors
    if answer and "RESOURCE_EXHAUSTED" not in answer and not answer.startswith("Error"):
        try:
            await client.send_message(
                chat_id=message.chat.id,
                text=answer,
                reply_to_message_id=message.id
            )
            print("🚀 [COMMENT PLACED INSTANTLY!]")
        except Exception as e:
            print(f"❌ Error sending comment: {e}")
    else:
        print("⚠️ No valid answer — skipped posting.")

if __name__ == "__main__":
    print("🤖 Initializing MT5 connection...")
    if mt5.initialize():
        _mt5_initialized = True
        print("✅ MT5 Connected Successfully!")
    else:
        print(f"⚠️ MT5 Init Warning: {mt5.last_error()}")

    print(f"🤖 Userbot listening on {TARGET_CHAT} with high-speed performance config...")
    app.run()
    
    # Clean shutdown on exit
    mt5.shutdown()