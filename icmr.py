from flask import Flask, request, jsonify
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from deep_translator import GoogleTranslator
import re
import json

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Telegram API credentials
api_id = 26973152
api_hash = '3359532bba54756f12424148064e3e4d'
session_name = 'bot_session'
group_username = '@freeicmr'

app = Flask(__name__)
client = TelegramClient(session_name, api_id, api_hash)
loop = asyncio.get_event_loop()

# Initialize the Telegram client and start the bot
async def init_client():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telethon client not authorized. Run interactively once.")
    group_entity = await client.get_entity(group_username)
    await client.send_message(group_entity, "/start")
    await asyncio.sleep(2)
    logging.info(f"Sent /start to {group_username}")

# Perform search on the bot
async def perform_search(user_input: str) -> dict:
    final_response = None
    final_response_received = asyncio.Event()
    group_entity = await client.get_entity(group_username)
    sent_msg_id = None

    async def handler(event):
        nonlocal final_response
        if event.message.reply_to_msg_id == sent_msg_id:
            msg_lower = event.message.message.lower()
            if "searching" not in msg_lower and "please wait" not in msg_lower:
                final_response = event.message.message
                final_response_received.set()

    async def edit_handler(event):
        nonlocal final_response
        if event.message.reply_to_msg_id == sent_msg_id:
            msg_lower = event.message.message.lower()
            if "searching" not in msg_lower and "please wait" not in msg_lower:
                final_response = event.message.message
                final_response_received.set()

    client.add_event_handler(handler, events.NewMessage(chats=group_entity))
    client.add_event_handler(edit_handler, events.MessageEdited(chats=group_entity))

    try:
        sent_message = await client.send_message(group_entity, f"/num {user_input}")
        sent_msg_id = sent_message.id
        try:
            await asyncio.wait_for(final_response_received.wait(), timeout=30)
        except asyncio.TimeoutError:
            return {"status": "error", "message": "No response received (timeout)."}

        if final_response:
            translated_text = final_response  # Assume English, no translation needed
            # Try to parse as JSON first
            try:
                response_data = json.loads(translated_text)
                if isinstance(response_data, list):
                    return response_data
            except json.JSONDecodeError:
                pass

            # If not JSON, parse as key-value blocks
            response_data = []
            blocks = re.split(r'\n\s*\n+', translated_text.strip())
            for block in blocks:
                lines = block.split('\n')
                record = {}
                for line in lines:
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip().lower().replace(' ', '_').replace('father\'s_name', 'father_name')  # Normalize keys
                        value = value.strip().strip('"')
                        record[key] = value
                if record:
                    # Convert id to int if possible
                    if 'id' in record:
                        try:
                            record['id'] = int(record['id'])
                        except ValueError:
                            pass
                    response_data.append(record)
            if response_data:
                return response_data
            else:
                return {"status": "error", "message": "Failed to parse response."}
        else:
            return {"status": "error", "message": "No response received."}

    except FloodWaitError as e:
        return {"status": "error", "message": f"Flood wait error: Wait {e.seconds} seconds."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        client.remove_event_handler(handler)
        client.remove_event_handler(edit_handler)

# Flask route to query the bot
@app.route("/", methods=["GET"])
def root():
    num = request.args.get("num")
    if not num:
        return jsonify({"error": "Please provide ?num=9685748596"})
    result = loop.run_until_complete(perform_search(num))
    return jsonify(result)

# Run the Flask server
if __name__ == "__main__":
    loop.run_until_complete(init_client())
    app.run(host="0.0.0.0", port=8000)