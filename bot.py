import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
import google.genai as genai
from PIL import Image

# 1. YOUR CREDENTIALS
API_ID = TELEGRAM_API_ID_VALUE                          # Replace with your Telegram API ID
API_HASH = "TELEGRAM_API_HASH_VALUE"            # Replace with your Telegram API Hash
GEMINI_API_KEY = "GEMINI_KEY_VALUE"# Replace with your Gemini API Key

# 2. TARGET CHANNEL
TARGET_CHAT = -1002385736403                  # Your channel username or ID

# Initialize Google GenAI Client
client_ai = genai.Client(api_key=GEMINI_API_KEY)

# Initialize Telegram Userbot Session
app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH)

from google.genai import types

def solve_question_image(image_path: str) -> str:
    """Sends the image to Gemini and allows it to search the web for live/real-time answers."""
    try:
        img = Image.open(image_path)
        prompt = (
            "Analyze this image. It contains a question about financial markets or real-time data. "
            "Search the web if necessary to find the precise, correct answer. "
            "Provide ONLY the direct answer clearly and concisely IN EXNESS CHART."
        )
        
        # Enable Google Search tool so Gemini can look up live market data
        response = client_ai.models.generate_content(
            model='gemini-3.8-flash',
            contents=[prompt, img],
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}]
            )
        )
        return response.text.strip()
    except Exception as e:
        return f"Error analyzing image: {e}"
@app.on_message(filters.chat(TARGET_CHAT) & (filters.photo | filters.text))
async def handle_incoming_post(client: Client, message: Message):
    print(f"\n⚡ [NEW POST DETECTED - ID: {message.id}] Processing...")

    file_path = None  
    answer = ""

    # Process photo or text
    if message.photo:
        print("📸 Downloading photo...")
        file_path = await message.download()
        try:
            print("🔍 [SOLVING] Sending image to Gemini...")
            answer = solve_question_image(file_path)
            print(f"✅ [ANSWER GENERATED]: {answer}")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

    elif message.text:
        print(f"📝 Text Question Detected: {message.text[:50]}...")
        try:
            response = client_ai.models.generate_content(
                model='gemini-3.8-flash',
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
        print("⚠️ Skipped posting due to API rate limit error.")

if __name__ == "__main__":
    print(f"🤖 Userbot listening on {TARGET_CHAT} for comments...")
    app.run()