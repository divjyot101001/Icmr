from flask import Flask, request, jsonify
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, UserNotParticipantError, ChannelPrivateError, ChatAdminRequiredError
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.sessions import StringSession
import re
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
import threading
from deep_translator import GoogleTranslator
import aiohttp
import brotli

# ------------------ CONFIGURATION ------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

api_id = 26973152
api_hash = '3359532bba54756f12424148064e3e4d'
session_string = "your_user_session_string_here"  # Paste your user session string here to fix the bot restriction error
group_username = '@wvizgseisbxuodebwydoxn'
sherlok_username = '@Sherlok7777bot'
paradox_username = '@paradoxbomber_bot'
bot_token = '8454361876:AAH_fRlPZICNBkPOptJX1EwIJ4gbZKLyzYk'
new_bot_token = '8497305791:AAG-2EI9lcufYDu7H5ELeh0D3zQ39xyNEjA'  # Add your new bot token here
channel_link = 'https://t.me/+TBXF1J0KQQ82Yzll'

app = Flask(__name__)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Use StringSession if available
if session_string:
    client = TelegramClient(StringSession(session_string), api_id, api_hash, loop=loop)
else:
    client = TelegramClient('user_session', api_id, api_hash, loop=loop)  # Changed to 'user_session' to avoid confusion

bot = TelegramClient('bot_session_bot', api_id, api_hash, loop=loop)
new_bot = TelegramClient('new_bot_session', api_id, api_hash, loop=loop)

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
        raise RuntimeError("Telethon client not authorized. Run interactively once to login as user and get session string.")
    
    group_entity = await client.get_entity(group_username)
    await client.send_message(group_entity, "/start")
    await asyncio.sleep(2)
    logging.info(f"Sent /start to {group_username}")
    
    sherlok_entity = await client.get_entity(sherlok_username)
    await client.send_message(sherlok_entity, "/start")
    await asyncio.sleep(2)
    logging.info(f"Sent /start to {sherlok_username}")
    
    paradox_entity = await client.get_entity(paradox_username)
    await client.send_message(paradox_entity, "/start")
    await asyncio.sleep(2)
    logging.info(f"Sent /start to {paradox_username}")
    
    await bot.start(bot_token=bot_token)
    await new_bot.start(bot_token=new_bot_token)

    admin_id = (await client.get_me()).id

    # Get channel entity using CheckChatInviteRequest to handle private channel
    channel_hash = channel_link.split('+')[1]
    invite = await client(CheckChatInviteRequest(hash=channel_hash))
    if hasattr(invite, 'chat'):
        channel_entity = invite.chat
    else:
        raise RuntimeError("User not joined to the channel. Join the channel with your user account first: " + channel_link)

    # Initialize database
    with db_lock:
        conn = get_db_connection()
        conn.execute('''CREATE TABLE IF NOT EXISTS api_keys (
            key TEXT PRIMARY KEY,
            expires_at TEXT,
            remaining_requests INTEGER,
            blocked INTEGER DEFAULT 0
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )''')
        conn.commit()
        conn.close()

    async def is_member(user_id):
        try:
            await client(GetParticipantRequest(channel=channel_entity, participant=user_id))
            return True
        except (UserNotParticipantError, ChannelPrivateError, ChatAdminRequiredError):
            return False

    async def check_membership(event):
        if await is_member(event.sender_id):
            return True
        await event.reply(f"🔒 Please join our channel first to use the bot:\n{channel_link}\n\nAfter joining, send /start again. ✅")
        return False

    # ----------- BOT COMMANDS (ADMIN BOT) -----------
    @bot.on(events.NewMessage(pattern=r'/genapikey (\d+) (\d+)'))
    async def gen_apikey(event):
        if event.sender_id != admin_id:
            return
        duration_days, max_requests = map(int, event.raw_text.split()[1:])
        key = uuid.uuid4().hex[:16]
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

    @bot.on(events.NewMessage(pattern=r'/broadcast (.+)'))
    async def broadcast_handler(event):
        if event.sender_id != admin_id:
            return
        message = event.raw_text.split(maxsplit=1)[1]
        with db_lock:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('SELECT user_id FROM users')
            users = [row[0] for row in cur.fetchall()]
            conn.close()
        if not users:
            await event.reply("❌ No users to broadcast to.")
            return
        results = await asyncio.gather(*[new_bot.send_message(user_id, f"📢 Broadcast: {message}") for user_id in users], return_exceptions=True)
        sent = sum(1 for r in results if not isinstance(r, Exception))
        failed = len(users) - sent
        await event.reply(f"✅ Broadcast sent to {sent} users, failed: {failed}")

    # ----------- NEW BOT COMMANDS (USER BOT) -----------
    commands_list = """
🚀 Available commands:

🔍 /num <number> - Search by number (e.g., /num 9685748596)
🔍 /numv2 <number> - Search by number v2
🆔 /aadhar <aadhar> - Search by Aadhar (e.g., /aadhar 123456789012)
🚗 /vehicle <vehicle> - Search by vehicle (e.g., /vehicle HR26EV0001)
🏷️ /fastag <fastag> - Search by fastag
👤 /userv2 <username> - Search by username (e.g., /userv2 @hello)
👨‍👩‍👧 /fam <fam id> - Search by fam (e.g., /fam rohit@fam)
💳 /upibomb <upi id> - Validate UPI ID (e.g., /upibomb rohit@fam)
💣 /bomb <10 digits number> - Send SMS verification (e.g., /bomb 9685748596)
/help - Show this list
    """

    @new_bot.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        if not await is_member(event.sender_id):
            await event.reply(f"🔒 Please join our channel first to use the bot:\n{channel_link}\n\nAfter joining, send /start again. ✅")
            return
        await event.reply("🚀 Welcome to the Advanced Search Bot! ✅\n\nUse /help for available commands.")
        await event.reply(commands_list)
        with db_lock:
            conn = get_db_connection()
            conn.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (event.sender_id,))
            conn.commit()
            conn.close()

    @new_bot.on(events.NewMessage(pattern='/help'))
    async def help_handler(event):
        if not await check_membership(event):
            return
        await event.reply(commands_list)

    async def send_examples(event):
        await event.reply("❌ Please provide the required input!\n\nExamples:\n/num 9685748596\n/vehicle HR26EV0001\n/userv2 @hello\n/aadhar 123456789012\n/bomb 9685748596\n/upibomb rohit@fam\n/fam rohit@fam")

    @new_bot.on(events.NewMessage(pattern=r'/num'))
    async def num_handler(event):
        if not await check_membership(event):
            return
        if len(event.raw_text.split()) < 2:
            await send_examples(event)
            return
        searching_msg = await event.reply("🔍 Searching... Please wait. ⏳")
        try:
            user_input = event.raw_text.split(maxsplit=1)[1]
            result = await perform_search('num', user_input)
            if result.get('status') == 'error':
                await searching_msg.edit(f"❌ {result['message']}")
            else:
                data = result if isinstance(result, list) else result.get('data', {})
                formatted = f"✅ Results found:\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"
                await searching_msg.edit(formatted)
        except Exception as e:
            await searching_msg.edit(f"❌ An error occurred: {str(e)}")

    @new_bot.on(events.NewMessage(pattern=r'/numv2'))
    async def numv2_handler(event):
        if not await check_membership(event):
            return
        if len(event.raw_text.split()) < 2:
            await send_examples(event)
            return
        searching_msg = await event.reply("🔍 Searching... Please wait. ⏳")
        try:
            user_input = event.raw_text.split(maxsplit=1)[1]
            result = await perform_numv2_search(user_input)
            if result.get('status') == 'error':
                await searching_msg.edit(f"❌ {result['message']}")
            else:
                data = result.get('data', {})
                if data:
                    formatted = f"✅ Results found:\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"
                    await searching_msg.edit(formatted)
                else:
                    await searching_msg.edit("✅ Search completed. No data found.")
        except Exception as e:
            await searching_msg.edit(f"❌ An error occurred: {str(e)}")

    @new_bot.on(events.NewMessage(pattern=r'/aadhar'))
    async def aadhar_handler(event):
        if not await check_membership(event):
            return
        if len(event.raw_text.split()) < 2:
            await send_examples(event)
            return
        searching_msg = await event.reply("🔍 Searching... Please wait. ⏳")
        try:
            user_input = event.raw_text.split(maxsplit=1)[1]
            result = await perform_search('aadhar', user_input)
            if result.get('status') == 'error':
                await searching_msg.edit(f"❌ {result['message']}")
            else:
                data = result if isinstance(result, list) else result.get('data', {})
                formatted = f"✅ Results found:\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"
                await searching_msg.edit(formatted)
        except Exception as e:
            await searching_msg.edit(f"❌ An error occurred: {str(e)}")

    @new_bot.on(events.NewMessage(pattern=r'/vehicle'))
    async def vehicle_handler(event):
        if not await check_membership(event):
            return
        if len(event.raw_text.split()) < 2:
            await send_examples(event)
            return
        searching_msg = await event.reply("🔍 Searching... Please wait. ⏳")
        try:
            user_input = event.raw_text.split(maxsplit=1)[1]
            result = await perform_search('vehicle', user_input)
            if result.get('status') == 'error':
                await searching_msg.edit(f"❌ {result['message']}")
            else:
                data = result if isinstance(result, list) else result.get('data', {})
                formatted = f"✅ Results found:\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"
                await searching_msg.edit(formatted)
        except Exception as e:
            await searching_msg.edit(f"❌ An error occurred: {str(e)}")

    @new_bot.on(events.NewMessage(pattern=r'/vnum'))
    async def vnum_handler(event):
        if not await check_membership(event):
            return
        if len(event.raw_text.split()) < 2:
            await send_examples(event)
            return
        searching_msg = await event.reply("🔍 Searching... Please wait. ⏳")
        try:
            user_input = event.raw_text.split(maxsplit=1)[1]
            result = await perform_search('vnum', user_input)
            if result.get('status') == 'error':
                await searching_msg.edit(f"❌ {result['message']}")
            else:
                data = result if isinstance(result, list) else result.get('data', {})
                formatted = f"✅ Results found:\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"
                await searching_msg.edit(formatted)
        except Exception as e:
            await searching_msg.edit(f"❌ An error occurred: {str(e)}")

    @new_bot.on(events.NewMessage(pattern=r'/fastag'))
    async def fastag_handler(event):
        if not await check_membership(event):
            return
        if len(event.raw_text.split()) < 2:
            await send_examples(event)
            return
        searching_msg = await event.reply("🔍 Searching... Please wait. ⏳")
        try:
            user_input = event.raw_text.split(maxsplit=1)[1]
            result = await perform_search('fastag', user_input)
            if result.get('status') == 'error':
                await searching_msg.edit(f"❌ {result['message']}")
            else:
                data = result if isinstance(result, list) else result.get('data', {})
                formatted = f"✅ Results found:\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"
                await searching_msg.edit(formatted)
        except Exception as e:
            await searching_msg.edit(f"❌ An error occurred: {str(e)}")

    @new_bot.on(events.NewMessage(pattern=r'/userv2'))
    async def username_handler(event):
        if not await check_membership(event):
            return
        if event.is_group:
            await event.reply("❌ This command can only be used in personal chat (limited requests). 👤")
            return
        if len(event.raw_text.split()) < 2:
            await send_examples(event)
            return
        searching_msg = await event.reply("🔍 Searching... Please wait. ⏳")
        try:
            user_input = event.raw_text.split(maxsplit=1)[1]
            result = await perform_username_search(user_input)
            if result.get('status') == 'error':
                await searching_msg.edit(f"❌ {result['message']}")
            else:
                data = result
                formatted = f"✅ User Search Results:\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"
                await searching_msg.edit(formatted)
        except Exception as e:
            await searching_msg.edit(f"❌ An error occurred: {str(e)}")

    @new_bot.on(events.NewMessage(pattern=r'/fam'))
    async def fam_handler(event):
        if not await check_membership(event):
            return
        if len(event.raw_text.split()) < 2:
            await send_examples(event)
            return
        searching_msg = await event.reply("🔍 Searching... Please wait. ⏳")
        try:
            user_input = event.raw_text.split(maxsplit=1)[1]
            result = await perform_fam_search(user_input)
            if result.get('status') == 'error':
                await searching_msg.edit(f"❌ {result['message']}")
            else:
                if 'data' in result or isinstance(result, dict):
                    data = result.get('data', result)
                    formatted = f"✅ Results found:\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"
                    await searching_msg.edit(formatted)
                else:
                    await searching_msg.edit(f"✅ {result.get('message', 'Done')} 👍")
        except Exception as e:
            await searching_msg.edit(f"❌ An error occurred: {str(e)}")

    @new_bot.on(events.NewMessage(pattern=r'/upibomb'))
    async def upibomb_handler(event):
        if not await check_membership(event):
            return
        if len(event.raw_text.split()) < 2:
            await send_examples(event)
            return
        searching_msg = await event.reply("🔍 Validating UPI... Please wait. ⏳")
        try:
            user_input = event.raw_text.split(maxsplit=1)[1]
            result = await perform_upi_validation(user_input)
            if result.get('status') == 'error':
                await searching_msg.edit(f"❌ {result['message']}")
            else:
                await searching_msg.edit("✅ UPI BOMBING DONE SUCCESSFULLY 👍🏻")
        except Exception as e:
            await searching_msg.edit(f"❌ An error occurred: {str(e)}")

    @new_bot.on(events.NewMessage(pattern=r'/bomb'))
    async def bomb_handler(event):
        if not await check_membership(event):
            return
        if len(event.raw_text.split()) < 2:
            await send_examples(event)
            return
        searching_msg = await event.reply("💣 Sending SMS verifications... Please wait. ⏳")
        try:
            user_input = event.raw_text.split(maxsplit=1)[1]
            results = await asyncio.gather(
                perform_sms_verify(user_input),
                perform_paradox_sms_verify(user_input)
            )
            if all(r['status'] == 'success' for r in results):
                await searching_msg.edit("✅ HARD SMS+CALL+WP BOMBING DONE SUCCESSFULLY 👍🏻")
            else:
                errors = [r['message'] for r in results if r['status'] != 'success']
                await searching_msg.edit(f"❌ Errors: {' '.join(errors)}")
        except Exception as e:
            await searching_msg.edit(f"❌ An error occurred: {str(e)}")

    await asyncio.gather(client.run_until_disconnected(), bot.run_until_disconnected(), new_bot.run_until_disconnected())

# ------------------ SEARCH FUNCTION FOR FREEICMR ------------------
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
        return {"status": "error", "message": "Wait 10 seconds before making another request"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        client.remove_event_handler(handler)
        client.remove_event_handler(edit_handler)

# ------------------ SEARCH FUNCTION FOR SHERLOK ------------------
async def perform_username_search(user_input: str) -> dict:
    telegram_selected = False
    final_response = None
    final_response_received = asyncio.Event()
    bot_entity = await client.get_entity(sherlok_username)

    async def handler(event):
        nonlocal telegram_selected, final_response
        if event.message.reply_markup and not telegram_selected:
            for row in event.message.reply_markup.rows:
                for button in row.buttons:
                    if button.text.lower() == 'telegram':
                        telegram_selected = True
                        await event.message.click(text=button.text)
                        break
                if telegram_selected:
                    break
        elif telegram_selected and not event.message.reply_markup:
            msg_lower = event.message.message.lower()
            if "идёт поиск" not in msg_lower and "подождите" not in msg_lower:
                final_response = event.message.message
                final_response_received.set()

    async def edit_handler(event):
        nonlocal final_response
        if telegram_selected:
            msg_lower = event.message.message.lower()
            if "идёт поиск" not in msg_lower and "подождите" not in msg_lower:
                final_response = event.message.message
                final_response_received.set()

    client.add_event_handler(handler, events.NewMessage(from_users=bot_entity))
    client.add_event_handler(edit_handler, events.MessageEdited(from_users=bot_entity))

    try:
        await client.send_message(bot_entity, user_input)
        try:
            await asyncio.wait_for(final_response_received.wait(), timeout=30)
        except asyncio.TimeoutError:
            return {"status": "error", "message": "No response received (timeout)."}

        if final_response:
            try:
                translated_text = GoogleTranslator(source='auto', target='en').translate(final_response)
            except Exception as e:
                translated_text = final_response
                logging.error(f"Translation error: {str(e)}")

            # Extract phone number
            phone_match = re.search(r'Phone:\s*([0-9]+)', translated_text)
            phone_number = phone_match.group(1) if phone_match else None

            # Extract Telegram ID
            id_match = re.search(r'ID:\s*([0-9]+)', translated_text)
            telegram_id = id_match.group(1) if id_match else None

            # Extract history changes
            history_matches = re.findall(r'(\d{2}/\d{2}/\d{4})\s*→\s*(.*)', translated_text)
            history = [{"date": h[0], "details": h[1]} for h in history_matches]

            response_data = {
                "status": "success",
                "title": "Telegram User Search Result",
                "phone_number": phone_number,
                "telegram_id": telegram_id,
                "history_changes": history
            }
            return response_data
        else:
            return {"status": "error", "message": "No response received."}

    except FloodWaitError as e:
        return {"status": "error", "message": "Wait 10 seconds before making another request"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        client.remove_event_handler(handler)
        client.remove_event_handler(edit_handler)

# ------------------ SEARCH FUNCTION FOR NUMV2 ------------------
async def perform_numv2_search(mobile: str) -> dict:
    url = "https://paiduserweb.onrender.com/search-mobile"
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "sec-ch-ua-platform": "Android",
                "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
                "sec-ch-ua": '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
                "content-type": "application/json",
                "sec-ch-ua-mobile": "?1",
                "accept": "*/*",
                "origin": "https://paiduserweb.onrender.com",
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "referer": "https://paiduserweb.onrender.com/",
                "accept-encoding": "gzip, deflate, br, zstd",
                "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
                "priority": "u=1, i"
            }
            data = {"mobile": mobile}
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    content = await response.read()
                    encoding = response.headers.get('content-encoding')
                    if encoding == 'br':
                        try:
                            content = brotli.decompress(content)
                        except Exception as e:
                            return {"status": "error", "message": f"Brotli decompression failed: {str(e)}"}
                    try:
                        result = json.loads(content.decode('utf-8'))
                        return {"status": "success", "data": result}
                    except json.JSONDecodeError:
                        return {"status": "success", "message": content.decode('utf-8')}
                else:
                    return {"status": "error", "message": f"HTTP {response.status}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ SEARCH FUNCTION FOR FAM ------------------
async def perform_fam_search(user_input: str) -> dict:
    url = f"https://revolutionary-cowboy-attacks-usr.trycloudflare.com/?upi={user_input}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    try:
                        return await response.json()
                    except aiohttp.ContentTypeError:
                        text = await response.text()
                        return {"status": "success", "message": text}
                else:
                    return {"status": "error", "message": f"HTTP {response.status}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ UPI VALIDATION FUNCTION ------------------
async def perform_upi_validation(upi_id: str) -> dict:
    encoded_upi = upi_id.replace('@', '%40')
    url = f"https://mr-ags.fun/Bomb/upibomb.php?upi={encoded_upi}&submit=api+Now"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return {"status": "success", "message": "UPI BOMBING DONE SUCCESSFULLY ✅ 👍🏻"}
                else:
                    return {"status": "error", "message": f"HTTP {response.status}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ SMS VERIFY FUNCTION (HTTP) ------------------
async def perform_sms_verify(number: str) -> dict:
    url = f"https://unitedcamps.in/Bomber/?number={number}&key=JERRY"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return {"status": "success", "message": "SMS VERIFICATION SENT SUCCESSFULLY ✅👍🏻"}
                else:
                    return {"status": "error", "message": f"HTTP {response.status}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ SMS VERIFY FUNCTION (PARADOX BOT) ------------------
async def perform_paradox_sms_verify(user_input: str) -> dict:
    final_response = None
    final_response_received = asyncio.Event()
    bot_entity = await client.get_entity(paradox_username)

    async def handler(event):
        nonlocal final_response
        msg_lower = event.message.message.lower()
        if "searching" not in msg_lower and "please wait" not in msg_lower:
            final_response = event.message.message
            final_response_received.set()

    client.add_event_handler(handler, events.NewMessage(from_users=bot_entity))

    try:
        await client.send_message(bot_entity, f"/bomb {user_input}")
        try:
            await asyncio.wait_for(final_response_received.wait(), timeout=30)
        except asyncio.TimeoutError:
            return {"status": "error", "message": "No response received (timeout)."}

        if final_response:
            return {"status": "success", "message": "SMS VERIFICATION SENT SUCCESSFULLY ✅👍🏻"}
        else:
            return {"status": "error", "message": "No response received."}

    except FloodWaitError as e:
        return {"status": "error", "message": "Wait 10 seconds before making another request"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        client.remove_event_handler(handler)

# ------------------ FLASK ROUTE ------------------
@app.route("/", methods=["GET"])
def root():
    api_key = request.args.get('api_key')
    if not api_key:
        return jsonify({"error": "Please provide api_key"})
    
    with db_lock:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT expires_at, remaining_requests, blocked FROM api_keys WHERE key=?', (api_key,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Invalid API key"})
        expires_at, remaining_requests, blocked = row
        if blocked == 1:
            conn.close()
            return jsonify({"error": "API key blocked"})
        try:
            expires = datetime.fromisoformat(expires_at)
            if expires < datetime.now():
                conn.close()
                return jsonify({"error": "API key expired"})
        except ValueError:
            conn.close()
            return jsonify({"error": "Invalid API key"})
        if remaining_requests <= 0:
            conn.close()
            return jsonify({"error": "No requests remaining"})
        cur.execute('UPDATE api_keys SET remaining_requests = remaining_requests - 1 WHERE key=?', (api_key,))
        conn.commit()
        conn.close()
    vacuum_db()

    params = request.args.copy()
    params.pop('api_key', None)
    if not params:
        return jsonify({"error": "Please provide a query parameter like ?num=9685748596 or ?vehicle=DL10AB1234 or ?username=@hello or ?fam=rohit@fam or ?upibomb=hello@ptyes or ?bomb=9685748596"})
    if len(params) > 1:
        return jsonify({"error": "Please provide only one query parameter."})
    command, value = next(iter(params.items()))

    if command == 'username':
        future = asyncio.run_coroutine_threadsafe(perform_username_search(value), loop)
        result = future.result()
    elif command == 'fam':
        future = asyncio.run_coroutine_threadsafe(perform_fam_search(value), loop)
        result = future.result()
    elif command == 'upibomb':
        future = asyncio.run_coroutine_threadsafe(perform_upi_validation(value), loop)
        result = future.result()
    elif command == 'bomb':
        future1 = asyncio.run_coroutine_threadsafe(perform_sms_verify(value), loop)
        future2 = asyncio.run_coroutine_threadsafe(perform_paradox_sms_verify(value), loop)
        result1 = future1.result()
        result2 = future2.result()
        if result1['status'] == 'success' and result2['status'] == 'success':
            result = {"status": "success", "message": "HARD SMS+CALL+WP BOMBING DONE SUCCESSFULLY ✅👍🏻"}
        else:
            errors = []
            if result1['status'] != 'success':
                errors.append(result1['message'])
            if result2['status'] != 'success':
                errors.append(result2['message'])
            result = {"status": "error", "message": " ".join(errors)}
    elif command == 'numv2':
        future = asyncio.run_coroutine_threadsafe(perform_numv2_search(value), loop)
        result = future.result()
    else:
        future = asyncio.run_coroutine_threadsafe(perform_search(command, value), loop)
        result = future.result()
    return jsonify(result)

# ------------------ ENTRY POINT ------------------
if __name__ == "__main__":
    flask_thread = threading.Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 8000, 'threaded': True})
    flask_thread.start()
    loop.run_until_complete(main())