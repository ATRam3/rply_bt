import os
import asyncio
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
TARGET_CHAT = -1002385736403               

# Initialize Google GenAI Client
client_ai = genai.Client(api_key=GEMINI_API_KEY)

# Initialize Telegram Userbot Session
app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH)

def get_market_data_answer(ticker_symbol: str) -> str:
    """Fetches exact daily candles instantly using the persistent MT5 connection."""
    try:
        clean_symbol = ticker_symbol.strip().upper().replace("/", "").replace("=", "").replace("-", "").replace(" ", "")
        
        # Map common names to Exness specific .m tickers
        if clean_symbol in ["GOLD", "XAUUSD"]:
            mt5_symbol = "XAUUSDm"
        elif clean_symbol in ["SILVER", "XAGUSD"]:
            mt5_symbol = "XAGUSDm"
        elif clean_symbol in ["BTCUSD", "BTC"]:
            mt5_symbol = "BTCUSDm"
        elif clean_symbol in ["ETHUSD", "ETH"]:
            mt5_symbol = "ETHUSDm"
        else:
            mt5_symbol = clean_symbol if clean_symbol.endswith("M") else clean_symbol + "m"

        # Ensure MT5 is active
        if not mt5.terminal_info():
            mt5.initialize()

        mt5.symbol_select(mt5_symbol, True)
        
        # Request the last 14 daily bars
        rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_D1, 0, 14)

        if rates is not None and len(rates) > 0:
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            
            price_records = []
            for _, row in df.iterrows():
                date_str = row['time'].strftime('%Y-%m-%d')
                price_records.append(f"Date: {date_str} | Low: {row['low']:.3f} | High: {row['high']:.3f} | Close: {row['close']:.3f}")

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
    """Processes image from memory, fetches MT5 data, and queries Gemini rapidly."""
    try:
        img = Image.open(photo_bytes)
        
        # Step 1: Extract question and ticker from image
        extract_prompt = (
            "Analyze this trading quiz image. "
            "1. Identify the asset symbol/ticker being asked about (e.g., EURUSD, XAUUSD, BTCUSD). "
            "2. Identify the exact question text. "
            "Output strictly in this format: TICKER: <symbol> | QUESTION: <question text>"
        )
        query_response = client_ai.models.generate_content(
            model='gemini-3.5-flash',
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

        # Step 2: Fetch exact live data from local Exness MT5 app instantly
        market_context = get_market_data_answer(ticker_symbol)
        
        # Step 3: Solve using text
        if market_context:
            final_prompt = (
                f"Official Exness Terminal Data:\n{market_context}\n\n"
                f"Question: {question_text}\n\n"
                "Based strictly on this official Exness terminal data, what is the exact numerical answer to the question? "
                "Provide ONLY the final short number or answer (e.g., 4073.195), with zero explanation or text."
            )
        else:
            final_prompt = (
                f"Question: {question_text}\n"
                "Provide ONLY the correct, direct answer clearly and concisely."
            )

        response = client_ai.models.generate_content(
            model='gemini-3.5-flash',
            contents=[final_prompt]
        )
        return response.text.strip()
        
    except Exception as e:
        return f"Error analyzing image: {e}"

@app.on_message(filters.chat(TARGET_CHAT) & (filters.photo | filters.text))
async def handle_incoming_post(client: Client, message: Message):
    print(f"\n⚡ [NEW POST DETECTED - ID: {message.id}] Processing...")

    answer = ""

    # Process photo entirely in memory (No disk write/delete delay)
    if message.photo:
        print("📸 Downloading photo to RAM...")
        try:
            photo_file = await client.download_media(message, in_memory=True)
            print("🔍 [SOLVING] Processing image and instant Exness data...")
            # Run image solving in a separate thread to keep event loop fully responsive
            answer = await asyncio.to_thread(solve_question_image, photo_file)
            print(f"✅ [ANSWER GENERATED]: {answer}")
        except Exception as e:
            print(f"❌ Error handling photo: {e}")

    # Process text
    elif message.text:
        print(f"📝 Text Question Detected: {message.text[:50]}...")
        try:
            response = client_ai.models.generate_content(
                model='gemini-3.5-flash',
                contents=[f"Provide ONLY the direct answer to this question: {message.text}"]
            )
            answer = response.text.strip()
            print(f"✅ [ANSWER GENERATED]: {answer}")
        except Exception as e:
            print(f"Error: {e}")

    # Send comment instantly into the discussion thread
    if answer and "RESOURCE_EXHAUSTED" not in answer:
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
        print("⚠️ Skipped posting due to API rate limit or error.")

if __name__ == "__main__":
    print("🤖 Initializing MT5 connection...")
    if mt5.initialize():
        print("✅ MT5 Connected Successfully!")
    else:
        print(f"⚠️ MT5 Init Warning: {mt5.last_error()}")

    print(f"🤖 Userbot listening on {TARGET_CHAT} with high-speed performance config...")
    app.run()
    
    # Clean shutdown on exit
    mt5.shutdown()