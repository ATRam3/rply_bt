from pyrogram import Client

# Put your sister's real credentials here
API_ID = TELEGRAM_API_ID_VALUE                          # Replace with your Telegram API ID
API_HASH = "TELEGRAM_API_HASH_VALUE"    

app = Client("sister_bot", api_id=API_ID, api_hash=API_HASH)

async def main():
    async with app:
        # Prints out all chats your sister's account is currently in
        async for dialog in app.get_dialogs():
            print(f"Chat Name: {dialog.chat.title} ---> ID: {dialog.chat.id}")

app.run(main())