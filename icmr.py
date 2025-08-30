from flask import Flask, request, jsonify
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
import re
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
import threading

# ------------------ CONFIGURATION ------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

api_id = 26973152
api_hash = '3359532bba54756f12424148064e3e4d'
session_string = ""  # <- fill this after first login (optional)
group_username = '@freeicmr'
bot_token = '8454361876:AAH_fRlPZICNBkPOptJX1EwIJ4gbZKLyzYk'

app = Flask(__name__)
loop = asyncio.get_event_loop()

# Use StringSession if available
if session_string:
    client = TelegramClient(StringSession(session_string), api_id, api_hash, loop=loop)
else:
    client = TelegramClient('bot_session', api_id, api_hash, loop=loop)

bot = TelegramClient('bot_session_bot', api_id, api_hash, loop=loop)

# ------------------ DATABASE ------------------
db_lock = threading.Lock()

def get_db_connection():
    return sqlite3.connect('api_keys.db', timeout=10, check_same_thread=False)

def vacuum_db():
    """Clean up database to release locks and reduce size."""
    with db_lock:
        conn = get_db_connection()
        conn.execute('VACUUM')
        conn.close()

# ------------------ TELETHON MAIN ------------------
async def main():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telethon client not authorized. Run interactively once.")
    group_entity = await client.get_entity(group_username)
    await client.send_message(group_entity, "/start")
    await asyncio.sleep(2)
    logging.info(f"Sent /start to {group_username}")

    await bot.start(bot_token=bot_token)

    admin_id = (await client.get_me()).id

    # Initialize database
    with db_lock:
        conn = get_db_connection()
        conn.execute('''CREATE TABLE IF NOT EXISTS api_keys (
            key TEXT PRIMARY KEY,
            expires_at TEXT,
            remaining_requests INTEGER,
            blocked INTEGER DEFAULT 0
        )''')
        conn.commit()
        conn.close()

    # ----------- BOT COMMANDS -----------
    @bot.on(events.NewMessage(pattern=r'/genapikey (\d+) (\d+)'))
    async def gen_apikey(event):
        if event.sender_id != admin_id:
            return
        duration_days, max_requests = map(int, event.raw_text.split()[1:])
        key = str(uuid.uuid4())
        now = datetime.now()
        expires = now + timedelta(days=duration_days)
        with db_lock:
            conn = get_db_connection()
            conn.execute('INSERT INTO api_keys (key, expires_at, remaining_requests) VALUES (?, ?, ?)',
                         (key, expires.isoformat(), max_requests))
            conn.commit()
            conn.close()
        vacuum_db()
        await event.reply(f'Generated API key: {key}\nExpires: {expires}\nRequests: {max_requests}')

    @bot.on(events.NewMessage(pattern=r'/blockapikey (.+)'))
    async def block_apikey(event):
        if event.sender_id != admin_id:
            return
        key = event.raw_text.split()[1]
        with db_lock:
            conn = get_db_connection()
            conn.execute('UPDATE api_keys SET blocked=1 WHERE key=?', (key,))
            conn.commit()
            conn.close()
        vacuum_db()
        await event.reply(f'Blocked API key: {key}')

    @bot.on(events.NewMessage(pattern='/users'))
    async def list_users(event):
        if event.sender_id != admin_id:
            return
        with db_lock:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('SELECT key, expires_at, remaining_requests, blocked FROM api_keys')
            rows = cur.fetchall()
            conn.close()
        msg = 'API Keys:\n'
        for row in rows:
            msg += f'Key: {row[0]}, Expires: {row[1]}, Remaining: {row[2]}, Blocked: {bool(row[3])}\n'
        await event.reply(msg)

    await asyncio.gather(client.run_until_disconnected(), bot.run_until_disconnected())

# ------------------ SEARCH FUNCTION ------------------
async def perform_search(command: str, user_input: str) -> dict:
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
        sent_message = await client.send_message(group_entity, f"/{command} {user_input}")
        sent_msg_id = sent_message.id
        try:
            await asyncio.wait_for(final_response_received.wait(), timeout=30)
        except asyncio.TimeoutError:
            return {"status": "error", "message": "No response received (timeout)."}

        if final_response:
            translated_text = final_response
            try:
                response_data = json.loads(translated_text)
                if isinstance(response_data, list):
                    for record in response_data:
                        if isinstance(record, dict):
                            for k in list(record.keys()):
                                if k.replace('"', '').lower() == "by" and record[k] == "TeamIntelX":
                                    record.pop(k, None)
                    return response_data
            except json.JSONDecodeError:
                pass

            response_data = []
            blocks = re.split(r'\n\s*\n+', translated_text.strip())
            for block in blocks:
                lines = block.split('\n')
                record = {}
                for line in lines:
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip().strip('"').strip("'").lower().replace(' ', '_').replace('father\'s_name', 'father_name')
                        value = value.strip().strip('"').strip("'").strip(',')
                        record[key] = value
                if record:
                    if 'id' in record:
                        try:
                            record['id'] = int(record['id'])
                        except ValueError:
                            pass
                    response_data.append(record)

            if response_data:
                for record in response_data:
                    for k in list(record.keys()):
                        if k.replace('"', '').lower() == "by" and record[k] == "TeamIntelX":
                            record.pop(k, None)
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

# ------------------ FLASK ROUTE ------------------
@app.route("/", methods=["GET"])
def root():
    api_key = request.args.get('api_key')
    ip = request.remote_addr

    if not api_key:
        asyncio.run_coroutine_threadsafe(client.send_message('me', f'Missing API key from IP: {ip}'), loop)
        return jsonify({"error": "Please provide api_key"})

    with db_lock:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT expires_at, remaining_requests, blocked FROM api_keys WHERE key=?', (api_key,))
        row = cur.fetchone()

    if not row:
        conn.close()
        asyncio.run_coroutine_threadsafe(client.send_message('me', f'Invalid API key: {api_key} from IP: {ip}'), loop)
        return jsonify({"error": "Invalid API key"})

    expires = datetime.fromisoformat(row[0])
    remaining = row[1]
    blocked = bool(row[2])

    if blocked:
        conn.close()
        asyncio.run_coroutine_threadsafe(client.send_message('me', f'Blocked API key: {api_key} from IP: {ip}'), loop)
        return jsonify({"error": "Invalid API key"})

    if datetime.now() > expires:
        conn.close()
        asyncio.run_coroutine_threadsafe(client.send_message('me', f'Expired API key: {api_key} from IP: {ip}'), loop)
        return jsonify({"error": "API key expired"})

    if remaining <= 0:
        conn.close()
        asyncio.run_coroutine_threadsafe(client.send_message('me', f'No requests left for API key: {api_key} from IP: {ip}'), loop)
        return jsonify({"error": "No requests left"})

    # Decrement remaining requests
    with db_lock:
        cur.execute('UPDATE api_keys SET remaining_requests = remaining_requests - 1 WHERE key=?', (api_key,))
        conn.commit()
        conn.close()
    vacuum_db()

    params = request.args.copy()
    params.pop('api_key', None)
    if not params:
        return jsonify({"error": "Please provide a query parameter like ?num=9685748596 or ?vehicle=DL10AB1234"})
    if len(params) > 1:
        return jsonify({"error": "Please provide only one query parameter."})
    command, value = next(iter(params.items()))

    future = asyncio.run_coroutine_threadsafe(perform_search(command, value), loop)
    result = future.result()
    return jsonify(result)

# ------------------ ENTRY POINT ------------------
if __name__ == "__main__":
    flask_thread = threading.Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 8000, 'threaded': True})
    flask_thread.start()
    loop.run_until_complete(main())