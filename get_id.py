import os
from dotenv import load_dotenv
from pyrogram import Client

load_dotenv()
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

app = Client("sister_bot", api_id=API_ID, api_hash=API_HASH)

async def main():
    search = input("🔍 Enter channel name or @username to search: ").strip().lower()

    async with app:
        # Try direct username lookup first (fast)
        if search.startswith("@") or not search.startswith("-"):
            try:
                chat = await app.get_chat(search.lstrip("@"))
                print(f"\n✅ Found: {chat.title or chat.first_name}")
                print(f"   ID: {chat.id}")
                return
            except Exception:
                pass  # Fall back to dialog search below

        # Search through all dialogs by name
        print("🔎 Searching your dialogs...")
        matches = []
        async for dialog in app.get_dialogs():
            name = dialog.chat.title or dialog.chat.first_name or ""
            if search in name.lower():
                matches.append((name, dialog.chat.id))

        if matches:
            print(f"\n✅ Found {len(matches)} match(es):\n")
            for name, chat_id in matches:
                print(f"   📌 {name}  -->  ID: {chat_id}")
        else:
            print(f"\n⚠️ No chats found matching '{search}'.")

app.run(main())