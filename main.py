import telebot
from telebot import types
import subprocess
import os
import sys
import time
import threading
import shutil
from datetime import datetime, timedelta
from flask import Flask, request
import json

# --- FLASK APP FOR RENDER ---
app = Flask(__name__)

# --- CONFIGURATION ---
API_TOKEN = '8648889248:AAHfjrwpF9tDkLMoYQDHO_3nZB1pt4UJoGs'
ADMIN_USERNAME = '@mgzan201'
ADMIN_CHAT_ID = "7592705124"

# Get Render URL from environment
RENDER_URL = os.environ.get('RENDER_URL', 'https://vortexa-bot.onrender.com')

bot = telebot.TeleBot(API_TOKEN)

# --- DIRECTORY SETUP ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST_DIR = os.path.join(BASE_DIR, "hosted_bots")
if not os.path.exists(HOST_DIR):
    os.makedirs(HOST_DIR)

# Save data file
DATA_FILE = os.path.join(BASE_DIR, "bot_data.json")

# --- GLOBAL TRACKERS ---
running_processes = {}
start_times = {}
file_names = {}
user_selected_slot = {}
registered_users = set()
user_usernames = {}
user_time_balance = {}
referred_tracker = set()
pro_users = set()

# --- LOAD/SAVE DATA FUNCTIONS ---
def load_data():
    global registered_users, user_usernames, user_time_balance, pro_users, referred_tracker
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                registered_users = set(data.get('registered_users', []))
                user_usernames = data.get('user_usernames', {})
                pro_users = set(data.get('pro_users', []))
                referred_tracker = set(data.get('referred_tracker', []))
                # Convert time strings back to datetime
                time_balance_data = data.get('user_time_balance', {})
                for uid, time_str in time_balance_data.items():
                    if time_str:
                        user_time_balance[uid] = datetime.fromisoformat(time_str)
                print(f"✅ Data loaded: {len(registered_users)} users")
        except Exception as e:
            print(f"Error loading data: {e}")

def save_data():
    try:
        # Convert datetime to string for JSON
        time_balance_data = {}
        for uid, time_obj in user_time_balance.items():
            time_balance_data[uid] = time_obj.isoformat() if time_obj else None
        
        data = {
            'registered_users': list(registered_users),
            'user_usernames': user_usernames,
            'user_time_balance': time_balance_data,
            'pro_users': list(pro_users),
            'referred_tracker': list(referred_tracker)
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ Data saved: {len(registered_users)} users")
    except Exception as e:
        print(f"Error saving data: {e}")

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return {
        'status': 'running',
        'bot_name': 'Vortexa Ultimate Cloud Bot',
        'version': '12.0',
        'active_users': len(registered_users),
        'total_bots': sum(len(procs) for procs in running_processes.values()),
        'timestamp': datetime.now().isoformat()
    }, 200

@app.route('/health')
def health():
    return {'status': 'healthy'}, 200

@app.route(f'/webhook/{API_TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    return 'Bad Request', 400

# --- HELPER FUNCTIONS ---
def count_active_bots(uid):
    if uid not in running_processes:
        return 0
    return sum(1 for pid in running_processes[uid].values() if pid.poll() is None)

def has_remaining_time(uid):
    if uid == ADMIN_CHAT_ID or uid in pro_users:
        return True
    if uid not in user_time_balance:
        return False
    return datetime.now() < user_time_balance[uid]

def get_time_balance_string(uid):
    if uid == ADMIN_CHAT_ID:
        return "♾️ Unlimited (Administrator Free)"
    if uid in pro_users:
        return "💎 Unlimited (VIP PRO Mode)"
    if uid not in user_time_balance or datetime.now() >= user_time_balance[uid]:
        return "❌ 0m (No Time Left - Please invite friends!)"
    diff = user_time_balance[uid] - datetime.now()
    days = diff.days
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60
    return f"⏳ {days}d {hours}h {minutes}m remaining"

def add_time_to_user(uid, minutes):
    if uid in pro_users or uid == ADMIN_CHAT_ID:
        return
    if uid not in user_time_balance or user_time_balance[uid] < datetime.now():
        user_time_balance[uid] = datetime.now() + timedelta(minutes=minutes)
    else:
        user_time_balance[uid] += timedelta(minutes=minutes)
    save_data()

# --- UI COMPONENTS ---
def get_dashboard_markup(uid):
    markup = types.InlineKeyboardMarkup(row_width=3)
    
    slots_btns = []
    for i in range(1, 4):
        slot_str = str(i)
        is_running = False
        if uid in running_processes and slot_str in running_processes[uid]:
            if running_processes[uid][slot_str].poll() is None:
                is_running = True
        
        status_dot = "🟢" if is_running else "⚪"
        slots_btns.append(types.InlineKeyboardButton(f"{status_dot} Slot {i}", callback_data=f"select_slot_{i}"))
    
    markup.add(*slots_btns)
    
    current_slot = user_selected_slot.get(uid, "1")
    is_current_running = False
    if uid in running_processes and current_slot in running_processes[uid]:
        if running_processes[uid][current_slot].poll() is None:
            is_current_running = True
            
    has_file = os.path.exists(os.path.join(HOST_DIR, uid, current_slot, "main.py"))
    
    deploy_btn = types.InlineKeyboardButton(f"📤 Deploy to Slot {current_slot}", callback_data=f"deploy_{current_slot}")
    
    if is_current_running:
        action_btn = types.InlineKeyboardButton(f"🛑 Stop Slot {current_slot}", callback_data=f"stop_{current_slot}")
    else:
        action_btn = types.InlineKeyboardButton(f"🚀 Launch Slot {current_slot}", callback_data=f"launch_{current_slot}") if has_file else None

    if action_btn:
        markup.add(deploy_btn, action_btn)
    else:
        markup.add(deploy_btn)

    markup.add(
        types.InlineKeyboardButton(f"📋 Logs (Slot {current_slot})", callback_data=f"logs_{current_slot}"),
        types.InlineKeyboardButton("🔄 Refresh Data", callback_data="refresh")
    )
    
    markup.add(types.InlineKeyboardButton("🛠 Official Support", url=f"https://t.me/{ADMIN_USERNAME.replace('@', '')}"))
    return markup

def get_reply_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    markup.add('🖥 Dashboard', '🚀 Deploy Bot', '📊 Server Status')
    markup.add('📁 My Projects', '🔗 Get Invite Link', '🆘 Help Desk')
    return markup

# --- CORE FUNCTIONS ---
def launch_bot(uid, slot):
    if not has_remaining_time(uid):
        return "NO_TIME"
        
    path = os.path.join(HOST_DIR, uid, slot, "main.py")
    log_path = os.path.join(HOST_DIR, uid, slot, "bot.log")
    
    if not os.path.exists(path):
        return "NO_FILE"
    
    try:
        # Stop existing bot if running
        if uid in running_processes and slot in running_processes[uid]:
            if running_processes[uid][slot].poll() is None:
                running_processes[uid][slot].terminate()
                time.sleep(1)
                if running_processes[uid][slot].poll() is None:
                    running_processes[uid][slot].kill()
        
        # Ensure log directory exists
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        
        # Open log file
        log_file = open(log_path, "a")
        log_file.write(f"\n--- Bot Started at {datetime.now()} ---\n")
        log_file.flush()
        
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        process = subprocess.Popen(
            [sys.executable, path],
            stdout=log_file,
            stderr=log_file,
            text=True,
            env=env
        )
        
        if uid not in running_processes:
            running_processes[uid] = {}
        if uid not in start_times:
            start_times[uid] = {}
            
        running_processes[uid][slot] = process
        start_times[uid][slot] = time.time()
        
        return "SUCCESS"
    except Exception as e:
        print(f"Launch error: {e}")
        return "ERROR"

# --- TELEGRAM BOT HANDLERS ---
@bot.message_handler(commands=['start'])
def dashboard(message):
    uid = str(message.chat.id)
    username = message.from_user.username if message.from_user.username else "No_Username"
    
    # Register user
    if uid not in registered_users:
        registered_users.add(uid)
        user_usernames[uid] = f"@{username}"
        save_data()
    
    # Check for referral
    msg_text = message.text
    if len(msg_text.split()) > 1 and msg_text.split()[1].startswith("ref_"):
        referrer_id = msg_text.split()[1].replace("ref_", "")
        
        if referrer_id != uid and uid not in referred_tracker:
            referred_tracker.add(uid)
            add_time_to_user(referrer_id, 30)
            save_data()
            
            try:
                bot.send_message(
                    referrer_id,
                    f"🎉 **New Referral Alert!**\nUser @{username} joined using your link!\n🎁 You earned **+30 minutes** of runtime!"
                )
            except Exception as e:
                print(f"Error sending referral message: {e}")

    # Initialize user slot if not exists
    if uid not in user_selected_slot:
        user_selected_slot[uid] = "1"
        
    current_slot = user_selected_slot[uid]
    
    # Check if bot is running
    is_live = False
    if uid in running_processes and current_slot in running_processes[uid]:
        if running_processes[uid][current_slot].poll() is None:
            is_live = True
            
    status_icon = "🟢 ACTIVE" if is_live else "🔴 OFFLINE"
    
    current_file = "No active project"
    if uid in file_names and current_slot in file_names[uid]:
        current_file = file_names[uid][current_slot]
    
    uptime = "0s"
    if is_live and uid in start_times and current_slot in start_times[uid]:
        diff = int(time.time() - start_times[uid][current_slot])
        days = diff // 86400
        hours = (diff % 86400) // 3600
        minutes = (diff % 3600) // 60
        seconds = diff % 60
        uptime = f"{days}d {hours}h {minutes}m {seconds}s"

    active_count = count_active_bots(uid)
    time_left_str = get_time_balance_string(uid)

    dashboard_ui = (
        f"💠 **VORTEXA ULTIMATE CLOUD v12.0** 💠\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 **Welcome Back, {message.from_user.first_name}!**\n"
        f"🆔 **Client ID:** `{uid}`\n"
        f"🎯 **Selected Workspace:** `Slot {current_slot}`\n"
        f"💰 **Runtime Balance:**\n`{time_left_str}`\n\n"
        f"🚀 **LIVE INSTANCE STATUS**\n"
        f"┣ Project: `📄 {current_file}`\n"
        f"┣ Status: {status_icon}\n"
        f"┣ Uptime: `{uptime}`\n"
        f"┗ Total Running Bots: `{active_count} / 3` 🔥\n\n"
        f"🖥 **SERVER ALLOCATION**\n"
        f"┣ Node: `Asia-Yangon-MZ1` 🇲🇲\n"
        f"┣ RAM Usage: `[■■■□□□□□□□] 30%`\n"
        f"┗ CPU Load: `[■□□□□□□□□□] 10%`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
    )
    
    bot.send_message(message.chat.id, dashboard_ui, reply_markup=get_reply_keyboard(), parse_mode='Markdown')
    bot.send_message(message.chat.id, f"🕹 **System Controller (Managing Slot {current_slot}):**", reply_markup=get_dashboard_markup(uid))

# --- ADMIN COMMANDS ---
@bot.message_handler(commands=['promeb'])
def admin_promeb(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ You are not authorized!")
        return
        
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Usage: /promeb <user_chat_id>")
        return
        
    target_uid = parts[1]
    pro_users.add(target_uid)
    registered_users.add(target_uid)
    save_data()
    
    uname = user_usernames.get(target_uid, "Unknown User")
    bot.send_message(ADMIN_CHAT_ID, f"✅ **PRO Upgrade Success!**\nUser {target_uid} ({uname}) is now VIP PRO!")
    
    try:
        bot.send_message(target_uid, "🎉 **Congratulations!**\nYou have been upgraded to **Unlimited VIP PRO** status!")
    except Exception:
        pass

@bot.message_handler(commands=['promebdele'])
def admin_promebdele(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ You are not authorized!")
        return
        
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Usage: /promebdele <user_chat_id>")
        return
        
    target_uid = parts[1]
    if target_uid in pro_users:
        pro_users.remove(target_uid)
        save_data()
        bot.send_message(ADMIN_CHAT_ID, f"❌ **PRO Removed from {target_uid}**")

@bot.message_handler(commands=['userlist'])
def admin_userlist(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ You are not authorized!")
        return
    
    if not registered_users:
        bot.send_message(ADMIN_CHAT_ID, "No users registered yet.")
        return
        
    user_list = "📊 **Registered Users:**\n━━━━━━━━━━━━━━━━\n"
    for idx, uid in enumerate(sorted(registered_users), 1):
        uname = user_usernames.get(uid, "@Unknown")
        status = "👑 OWNER" if uid == ADMIN_CHAT_ID else "💎 VIP" if uid in pro_users else "👤 USER"
        user_list += f"{idx}. {uname} - {status}\n   ID: `{uid}`\n\n"
        
        if len(user_list) > 3500:
            bot.send_message(ADMIN_CHAT_ID, user_list, parse_mode='Markdown')
            user_list = ""
    
    if user_list:
        bot.send_message(ADMIN_CHAT_ID, user_list, parse_mode='Markdown')

@bot.message_handler(commands=['allmessage'])
def admin_broadcast(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ You are not authorized!")
        return
        
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Usage: /allmessage <message>")
        return
        
    broadcast_text = parts[1]
    success = 0
    
    for uid in registered_users:
        try:
            bot.send_message(uid, f"📢 **ANNOUNCEMENT FROM ADMIN**\n\n{broadcast_text}")
            success += 1
            time.sleep(0.05)
        except:
            pass
    
    bot.send_message(ADMIN_CHAT_ID, f"✅ Broadcast sent to {success} users!")

# --- CALLBACK HANDLERS ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    uid = str(call.message.chat.id)
    
    if call.data.startswith("select_slot_"):
        slot = call.data.split("_")[-1]
        user_selected_slot[uid] = slot
        bot.answer_callback_query(call.id, f"Switched to Slot {slot}")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        dashboard(call.message)
        return

    current_slot = user_selected_slot.get(uid, "1")
    
    if call.data.startswith("stop_"):
        slot = call.data.split("_")[-1]
        if uid in running_processes and slot in running_processes[uid]:
            if running_processes[uid][slot].poll() is None:
                running_processes[uid][slot].terminate()
                time.sleep(1)
                if running_processes[uid][slot].poll() is None:
                    running_processes[uid][slot].kill()
            bot.send_message(call.message.chat.id, f"🛑 **Slot {slot} Stopped!**")
            dashboard(call.message)
            
    elif call.data.startswith("launch_"):
        slot = call.data.split("_")[-1]
        result = launch_bot(uid, slot)
        if result == "SUCCESS":
            bot.answer_callback_query(call.id, f"🚀 Launching Slot {slot}...")
            dashboard(call.message)
        elif result == "NO_TIME":
            bot.answer_callback_query(call.id, "❌ No time remaining!", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ Launch failed!")
            
    elif call.data == "refresh":
        bot.answer_callback_query(call.id, "Refreshing...")
        dashboard(call.message)
        
    elif call.data.startswith("deploy_"):
        slot = call.data.split("_")[-1]
        user_selected_slot[uid] = slot
        bot.send_message(call.message.chat.id, f"📤 **Send your Python (.py) file for Slot {slot}**")
        
    elif call.data.startswith("logs_"):
        slot = call.data.split("_")[-1]
        log_path = os.path.join(HOST_DIR, uid, slot, "bot.log")
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-30:]
                logs = "".join(lines) if lines else "Log file is empty."
            bot.send_message(call.message.chat.id, f"📋 **Logs for Slot {slot}:**\n```\n{logs}\n```", parse_mode='Markdown')
        else:
            bot.send_message(call.message.chat.id, f"❌ No logs found for Slot {slot}")

# --- TEXT HANDLERS ---
@bot.message_handler(content_types=['document'])
def handle_file(message):
    if message.document.file_name.endswith('.py'):
        uid = str(message.chat.id)
        
        if not has_remaining_time(uid):
            bot.reply_to(message, "❌ No runtime remaining! Invite friends to get more time.")
            return
            
        if uid not in user_selected_slot:
            user_selected_slot[uid] = "1"
        current_slot = user_selected_slot[uid]
        
        if uid not in file_names:
            file_names[uid] = {}
        file_names[uid][current_slot] = message.document.file_name
        
        status_msg = bot.reply_to(message, f"⚙️ Deploying to Slot {current_slot}...")
        
        # Download file
        file_info = bot.get_file(message.document.file_id)
        data = bot.download_file(file_info.file_path)
        
        # Save file
        slot_dir = os.path.join(HOST_DIR, uid, current_slot)
        os.makedirs(slot_dir, exist_ok=True)
        
        path = os.path.join(slot_dir, "main.py")
        with open(path, 'wb') as f:
            f.write(data)
        
        # Launch bot
        result = launch_bot(uid, current_slot)
        if result == "SUCCESS":
            bot.edit_message_text(f"✅ **Deployed to Slot {current_slot}!**\nBot is now running.", message.chat.id, status_msg.message_id)
        else:
            bot.edit_message_text(f"❌ **Deployment failed!** Check your code.", message.chat.id, status_msg.message_id)

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    uid = str(message.chat.id)
    
    if uid not in user_selected_slot:
        user_selected_slot[uid] = "1"
    current_slot = user_selected_slot[uid]
    
    if message.text == '🖥 Dashboard':
        dashboard(message)
    elif message.text == '🚀 Deploy Bot':
        bot.send_message(message.chat.id, f"📤 Send your Python file for Slot {current_slot}")
    elif message.text == '📊 Server Status':
        active = sum(1 for u in running_processes for s in running_processes[u] if running_processes[u][s].poll() is None)
        bot.send_message(message.chat.id, f"📊 **Server Status**\n━━━━━━━━━━━━\n✅ Status: Online\n🤖 Active Bots: {active}\n👥 Users: {len(registered_users)}")
    elif message.text == '📁 My Projects':
        status_text = "📂 **Your Projects:**\n━━━━━━━━━━━━\n"
        for i in range(1, 4):
            slot = str(i)
            name = file_names.get(uid, {}).get(slot, "Empty")
            is_running = uid in running_processes and slot in running_processes[uid] and running_processes[uid][slot].poll() is None
            status = "🟢 Running" if is_running else "🔴 Stopped"
            status_text += f"Slot {i}: {name}\nStatus: {status}\n\n"
        bot.send_message(message.chat.id, status_text)
    elif message.text == '🔗 Get Invite Link':
        bot_info = bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
        bot.send_message(message.chat.id, f"🔗 **Your Invite Link:**\n{link}\n\n🎁 Get 30 minutes per referral!")
    elif message.text == '🆘 Help Desk':
        bot.send_message(message.chat.id, f"🆘 **Support**\nContact: {ADMIN_USERNAME}\n\nCommands:\n/start - Main menu\n/promeb - Admin only\n/userlist - Admin only")

# --- TIME ENFORCER THREAD ---
def time_enforcer():
    while True:
        try:
            current_time = datetime.now()
            for uid in list(running_processes.keys()):
                if uid == ADMIN_CHAT_ID or uid in pro_users:
                    continue
                    
                if uid in user_time_balance and current_time >= user_time_balance[uid]:
                    for slot in list(running_processes[uid].keys()):
                        if running_processes[uid][slot].poll() is None:
                            running_processes[uid][slot].terminate()
                            try:
                                bot.send_message(int(uid), f"⚠️ Your runtime has expired! Bot in Slot {slot} has been stopped.")
                            except:
                                pass
                    del running_processes[uid]
        except Exception as e:
            print(f"Time enforcer error: {e}")
        time.sleep(30)

# --- DATA SAVE THREAD ---
def auto_save():
    while True:
        time.sleep(60)  # Save every minute
        save_data()

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    print("=" * 50)
    print("🚀 VORTEXA ULTIMATE CLOUD v12.0")
    print("=" * 50)
    
    # Load existing data
    load_data()
    
    # Start background threads
    t1 = threading.Thread(target=time_enforcer, daemon=True)
    t1.start()
    
    t2 = threading.Thread(target=auto_save, daemon=True)
    t2.start()
    
    # Get port for Render
    port = int(os.environ.get('PORT', 8080))
    
    # Check if running on Render
    if os.environ.get('RENDER'):
        print(f"✅ Running on Render - Port: {port}")
        print(f"📍 Webhook URL: {RENDER_URL}/webhook/{API_TOKEN}")
        
        # Setup webhook
        bot.remove_webhook()
        time.sleep(1)
        
        webhook_url = f"{RENDER_URL}/webhook/{API_TOKEN}"
        result = bot.set_webhook(url=webhook_url)
        
        if result:
            print("✅ Webhook set successfully!")
        else:
            print("❌ Webhook setup failed!")
        
        # Start Flask app
        app.run(host='0.0.0.0', port=port)
    else:
        # Local development with polling
        print("✅ Running locally - Polling mode")
        bot.remove_webhook()
        print("🤖 Bot is polling for updates...")
        bot.infinity_polling(timeout=30, long_polling_timeout=30)
