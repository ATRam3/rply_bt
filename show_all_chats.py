"""
Show all your Telegram chats to find the right ID
"""
import asyncio
from pyrogram import Client
from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH)

async def show_chats():
    await app.start()
    
    print("\n" + "="*60)
    print("📋 YOUR TELEGRAM CHATS")
    print("="*60)
    
    count = 0
    async for dialog in app.get_dialogs():
        chat = dialog.chat
        
        # Only show groups and channels with "eyuel" or "fx" in name
        if chat.title and ("eyuel" in chat.title.lower() or "fx" in chat.title.lower() or "trading" in chat.title.lower()):
            print(f"\n✅ {chat.title}")
            print(f"   ID: {chat.id}")
            print(f"   Type: {chat.type}")
            if chat.username:
                print(f"   Username: @{chat.username}")
            count += 1
    
    print("\n" + "="*60)
    print(f"Found {count} Eyuel/FX related chats")
    print("="*60)
    
    await app.stop()

if __name__ == "__main__":
    app.run(show_chats())
