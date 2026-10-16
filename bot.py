import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
import google.genai as genai
from PIL import Image
import MetaTrader5 as mt5
import pandas as pd

# 1. YOUR CREDENTIALS
API_ID = TELEGRAM_API_ID_VALUE                          # Your Telegram API ID
API_HASH = "TELEGRAM_API_HASH_VALUE" # Your Telegram API Hash
GEMINI_API_KEY = "GEMINI_KEY_VALUE" # Your Gemini API Key

# 2. TARGET CHANNEL
TARGET_CHAT = -1002385736403               # Your target chat numeric ID

# Initialize Google GenAI Client
client_ai = genai.Client(api_key=GEMINI_API_KEY)

# Initialize Telegram Userbot Session
app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH)

def get_market_data_answer(ticker_symbol: str) -> str:
    """Fetches exact spot market data directly from the logged-in Exness MT5 Terminal using the .m suffix."""
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
            # Automatically append 'm' suffix for standard forex pairs if not already present
            if not clean_symbol.endswith("M"):
                mt5_symbol = clean_symbol + "m"
            else:
                mt5_symbol = clean_symbol

        # Initialize MT5 session
        if not mt5.initialize():
            print(f"❌ MT5 initialization failed: {mt5.last_error()}")
            return None

        # Make sure symbol is selected in Market Watch
        mt5.symbol_select(mt5_symbol, True)
        
        # Request 7 Daily bars directly from Exness
        rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_D1, 0, 7)
        mt5.shutdown() # Close connection after reading

        if rates is not None and len(rates) > 0:
            df = pd.DataFrame(rates)
            lowest_price = df['low'].min()
            highest_price = df['high'].max()
            current_price = df['close'].iloc[-1]

            print(f"📊 [EXNESS DIRECT FEED] {mt5_symbol} | Low: {lowest_price:.3f}")
            return (
                f"Official Exness Terminal Data for {mt5_symbol}:\n"
                f"- Lowest price this week: {lowest_price:.3f}\n"
                f"- Highest price this week: {highest_price:.3f}\n"
                f"- Current price: {current_price:.3f}"
            )
        else:
            print(f"⚠️ Symbol '{mt5_symbol}' not found in Exness Market Watch.")
    except Exception as e:
        print(f"❌ MT5 Fetch Error for {ticker_symbol}: {e}")
    return None

def solve_question_image(image_path: str) -> str:
    """Extracts ticker & question from image, pulls exact Exness prices, and solves it."""
    try:
        img = Image.open(image_path)
        
        # Step 1: Extract question and ticker from image
        extract_prompt = (
            "Analyze this trading quiz image. "
            "1. Identify the asset symbol/ticker being asked about (e.g., EURUSD, XAUUSD, BTCUSD, GBPUSD). "
            "2. Identify the exact question text. "
            "Output strictly in this format: TICKER: <symbol> | QUESTION: <question text>"
        )
        query_response = client_ai.models.generate_content(
            model='gemini-3.5-flash',
            contents=[extract_prompt, img]
        )
        extracted_text = query_response.text.strip()
        print(f"🔎 [EXTRACTED DATA]: {extracted_text}")
        
        ticker_symbol = "XAUUSD" # default fallback
        question_text = extracted_text
        
        if "|" in extracted_text:
            parts = extracted_text.split("|")
            for part in parts:
                if "TICKER:" in part:
                    ticker_symbol = part.replace("TICKER:", "").strip()
                elif "QUESTION:" in part:
                    question_text = part.replace("QUESTION:", "").strip()

        # Step 2: Fetch exact live data from local Exness MT5 app
        market_context = get_market_data_answer(ticker_symbol)
        
        # Step 3: Solve using text ONLY (passing exact Exness numbers + question)
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

    file_path = None 
    answer = ""

    # Process photo
    if message.photo:
        print("📸 Downloading photo...")
        file_path = await message.download()
        try:
            print("🔍 [SOLVING] Processing image and local Exness terminal feeds...")
            answer = solve_question_image(file_path)
            print(f"✅ [ANSWER GENERATED]: {answer}")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

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

    # Send comment specifically into the discussion thread
    if answer and "RESOURCE_EXHAUSTED" not in answer:
        try:
            await client.send_message(
                chat_id=message.chat.id,
                text=answer,
                reply_to_message_id=message.id
            )
            print("🚀 [COMMENT PLACED INSIDE 'LEAVE A COMMENT' PANEL!]")
        except Exception as e:
            print(f"❌ Error sending comment: {e}")
    else:
        print("⚠️ Skipped posting due to API rate limit or error.")

if __name__ == "__main__":
    print(f"🤖 Userbot listening on {TARGET_CHAT} with direct Exness MT5 bridge...")
    app.run()