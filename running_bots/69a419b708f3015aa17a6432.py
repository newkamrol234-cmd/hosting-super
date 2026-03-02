import telebot
from telebot import types
import json
import os
import sys
import time
import pandas as pd
import random
import string
import pymongo
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import re
import threading
from datetime import datetime
import requests
import base64
import pyotp

# ==============================
# উইন্ডোজের জন্য ইউনিকোড (বাংলা/ইমোজি) প্রিন্ট ফিক্স
# ==============================
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# ==============================
# কনফিগাৰেচন (ছেটিংছ)
# ==============================
BOT_TOKEN = "8265829664:AAG7pI2W8OqX7RKzVb3we6aL4XhiduUOKrM"
ADMIN_ID = 6412225513
BOT_USERNAME = "EasyIncomeXBot"
EXCHANGE_RATE = 125.0 # 1 USD = 125 BDT
WITHDRAW_CHANNEL_ID = -1003567568487
TASK_PROOF_CHANNEL_ID = -1003586046562
COIN_TASK_GROUP_ID = -1003692155746
TARGET_CHANNEL_ID = -1003054357489
TARGET_CHANNEL_LINK = "https://t.me/+M58mXHCJb_4wMTY1"

# --- মংগোডিবি কনফিগাৰেচন ---
MONGO_URI = "mongodb+srv://kamrolha725_db_user:aass1122@cluster0.wkybonq.mongodb.net/?appName=Cluster0"
DB_NAME = "easy_income_x_bot_db"

bot = telebot.TeleBot(BOT_TOKEN)

client = None
db = None
users_col = None
settings_col = None
requests_col = None
submissions_col = None
sold_gmails_col = None
hotmails_col = None

def init_mongodb():
    global client, db, users_col, settings_col, requests_col, submissions_col, sold_gmails_col, hotmails_col
    try:
        print("🔄 মঙ্গোডিবি কানেক্ট হচ্ছে...")
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        print("✅ মঙ্গোডিবি সফলভাবে কানেক্ট হয়েছে!")
        
        db = client[DB_NAME]
        users_col = db['users']
        settings_col = db['settings']
        requests_col = db['task_requests']
        submissions_col = db['user_submissions']
        sold_gmails_col = db['sold_gmails']
        hotmails_col = db['hotmails']
        return True
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        print(f"❌ মঙ্গোডিবি কানেকশন ফেইলড: {e}")
        return False

if not init_mongodb():
    print("⚠️ বট ডাটাবেস ছাড়াই চলছে। কিছু ফিচার কাজ নাও করতে পারে।")

# অস্থায়ী সংৰক্ষণ (ৰেম)
withdraw_temp = {}
admin_temp = {} 
active_tasks = {} 
coin_task_temp = {}
task_rate_limits = {}
menu_state = {}
insta_push_temp = {}

# ==============================
# ইনষ্টা জেনেৰেটৰ সহায়ক
# ==============================
def generate_insta_creds():
    names = ["bulu", "kulu", "mulu", "tulu", "julu", "rulu", "pulu", "nulu"]
    mid = ["_mud", "_rud", "_tud", "_kud", "_lud"]
    end = string.ascii_lowercase + string.digits
    
    part1 = random.choice(names)
    part2 = random.choice(mid)
    part3 = ''.join(random.choices(end, k=5))
    
    username = f"{part1}{part2}{part3}"
    chars = string.ascii_letters + string.digits
    password = ''.join(random.choices(chars, k=10))
    return username, password

def generate_fb_names():
    first_names = ["Emma", "Liam", "Olivia", "Noah", "Ava", "Oliver", "Isabella", "Elijah", "Sophia", "James", "Mia", "William", "Amelia", "Benjamin", "Harper", "Lucas"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson"]
    return random.choice(first_names), random.choice(last_names)

def fetch_hotmail_code_graph(refresh_token, client_id):
    try:
        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        token_data = {
            "client_id": client_id,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": "https://graph.microsoft.com/.default"
        }
        token_res = requests.post(token_url, data=token_data, timeout=15)
        
        if token_res.status_code != 200:
            return f"❌ টোকেন এরর ({token_res.status_code})"
            
        access_token = token_res.json().get("access_token")
        if not access_token:
            return "❌ এক্সেস টোকেন পাওয়া যায়নি"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        mail_url = "https://graph.microsoft.com/v1.0/me/messages?$top=5&$select=subject,bodyPreview&$orderby=receivedDateTime desc"
        mail_res = requests.get(mail_url, headers=headers, timeout=15)
        
        if mail_res.status_code != 200:
            try:
                err_msg = mail_res.json().get('error', {}).get('message', 'Unknown Error')
            except:
                err_msg = mail_res.text[:30]
            return f"❌ মেইলবক্স এক্সেস এরর ({mail_res.status_code}): {err_msg}"
            
        messages = mail_res.json().get("value", [])
        if not messages:
            return "⏳ এখনও কোনো মেইল আসেনি"
        
        for msg in messages:
            subject = msg.get("subject", "")
            body = msg.get("bodyPreview", "")
            text_to_search = subject + " " + body
            
            match = re.search(r'\b\d{5,8}\b', text_to_search)
            if match:
                return match.group(0)
                
        return "⏳ মেইল এসেছে কিন্তু কোড পাওয়া যায়নি"
    except Exception as e:
        return f"❌ API এরর: {str(e)[:20]}"

# ==============================
# ডাটাবেছ ফাংচনসমূহ
# ==============================

def get_settings():
    defaults = {
        "min_bkash": 100.0,
        "min_rocket": 100.0,
        "task_price": 0.7000, 
        "insta_cookies_price": 0.0280, 
        "insta_html_file_id": None, 
        "gmail_task_price": 0.1200, 
        "join_task_price": 0.0100, 
        "gmail_task_enabled": True, 
        "min_coin_sell": 1000,
        "niva_price_per_1k": 0.0400,
        "ns_price_per_1k": 0.1200,
        "niva_coin_enabled": True,
        "ns_coin_enabled": True,
        "instagram_task_enabled": True,
        "insta_2fa_enabled": True,      
        "insta_cookies_enabled": True,  
        "instagram_push_url": "http://43.135.182.151/api/api/v1/webhook/nRlmI2-8T7x2DAWe1hWxi97qGA1FcCxrNcyCtLTO_Cw/account-push",
        "tutorial_insta_2fa": "https://t.me/Gmailsellincom/385",
        "tutorial_insta_cookies": "https://t.me/Gmailsellincom/385",
        "tutorial_niva": "https://t.me/Gmailsellincom/337",
        "tutorial_ns": "https://t.me/Gmailsellincom/339",
        "fixed_insta_2fa_password": "",
        "fixed_insta_cookies_password": "",
        "fixed_fb_password": "",
        "fb_task_enabled": True
    }
    if settings_col is None: return defaults
    try:
        data = settings_col.find_one({"_id": "config"})
        if not data:
            defaults["_id"] = "config"
            settings_col.insert_one(defaults)
            return defaults
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
        return data
    except Exception as e:
        print(f"DB Error (get_settings): {e}")
        return defaults

def update_settings(data):
    if settings_col is None: return
    try:
        settings_col.update_one({"_id": "config"}, {"$set": data}, upsert=True)
    except Exception as e:
        print(f"DB Error (save_settings): {e}")

def get_user(user_id):
    if users_col is None: return None
    try:
        return users_col.find_one({"_id": str(user_id)})
    except Exception as e:
        print(f"DB Error (get_user): {e}")
        return None

def update_user(user_id, data):
    if users_col is None: return
    try:
        users_col.update_one({"_id": str(user_id)}, {"$set": data}, upsert=True)
    except Exception as e:
        print(f"DB Error (update_user): {e}")

def get_all_users_count():
    if users_col is None: return 0
    return users_col.count_documents({})

def log_task_request(user_id, account_data, task_type="gmail"):
    if requests_col is None: return
    task_id = os.urandom(8).hex()
    req_data = {
        "task_id": task_id,
        "user_id": user_id,
        "task_type": task_type,
        "account_data": account_data,
        "timestamp": time.time(),
        "status": "Submitted"
    }
    requests_col.insert_one(req_data)

def get_pending_requests():
    if requests_col is None: return []
    return list(requests_col.find({"status": "Submitted"}))

def clear_requests_db():
    if requests_col is None: return
    requests_col.delete_many({})

def log_user_submission(user_id, accounts):
    if submissions_col is None: return
    sub_data = {
        "user_id": user_id,
        "timestamp": time.time(),
        "count": len(accounts),
        "accounts": accounts
    }
    submissions_col.insert_one(sub_data)

def get_all_submissions():
    if submissions_col is None: return []
    return list(submissions_col.find())

def clear_submissions_db():
    if submissions_col is None: return
    submissions_col.delete_many({})

def log_sold_gmails(accounts):
    if sold_gmails_col is None: return
    batch_id = os.urandom(4).hex()
    data = {
        "batch_id": batch_id,
        "timestamp": time.time(),
        "count": len(accounts),
        "accounts": accounts
    }
    sold_gmails_col.insert_one(data)
    return batch_id

def get_all_sold_batches():
    if sold_gmails_col is None: return []
    return list(sold_gmails_col.find().sort("timestamp", 1))

def clear_sold_gmails_db():
    if sold_gmails_col is None: return
    sold_gmails_col.delete_many({})

# ==============================
# পটভূমিৰ কামসমূহ
# ==============================
def auto_cancel_monitor():
    while True:
        try:
            current_time = time.time()
            for chat_id, task_data in list(active_tasks.items()):
                start_time = task_data.get('start_time')
                if start_time and (current_time - start_time > 1200): # 20 mins
                    if chat_id in active_tasks:
                        del active_tasks[chat_id]
                        try:
                            bot.send_message(
                                chat_id, 
                                "⏰ **টাস্কের সময় শেষ**\n\nআপনার টাস্কটি স্বয়ংক্রিয়ভাবে বাতিল করা হয়েছে।", 
                                parse_mode="Markdown",
                                reply_markup=main_menu(chat_id)
                            )
                        except Exception: pass
        except Exception as e:
            print(f"Auto-Cancel Error: {e}")
        time.sleep(60)

def auto_ref_milestone_monitor():
    while True:
        try:
            if users_col is not None:
                pending_users = users_col.find({"referral_withdraw_pending": {"$gt": 0}, "ref_5k_notified": {"$ne": True}})
                for u in pending_users:
                    uid = u["_id"]
                    pipeline = [
                        {"$match": {"referred_by": str(uid)}},
                        {"$group": {
                            "_id": None,
                            "tot_bal": {"$sum": "$balance"},
                            "tot_with": {"$sum": "$total_withdrawn"},
                            "tot_pend": {"$sum": "$pending_withdraw"}
                        }}
                    ]
                    res = list(users_col.aggregate(pipeline))
                    if res:
                        team_inc = res[0].get("tot_bal", 0) + res[0].get("tot_with", 0) + res[0].get("tot_pend", 0)
                        if team_inc >= 5000:
                            last_w = u.get("last_ref_withdraw", {})
                            msg = (
                                f"🎉 <b>REFERRAL TARGET 5000 BDT COMPLETED</b> 🎉\n\n"
                                f"👤 User ID: <code>{uid}</code>\n"
                                f"📈 টিম ইনকাম: {team_inc:.2f} BDT\n\n"
                                f"এই ইউজারের ৫০০০ টাকা রেফার টার্গেট পূরণ হয়েছে। ওনার পেন্ডিং উইথড্রটি পেমেন্ট করে দিন:\n"
                                f"💰 Amount: {u.get('referral_withdraw_pending', 0)} BDT\n"
                                f"💳 Method: {last_w.get('method', 'Unknown')}\n"
                                f"📝 Account: <code>{last_w.get('account', 'Unknown')}</code>"
                            )
                            try:
                                bot.send_message(WITHDRAW_CHANNEL_ID, msg, parse_mode="HTML")
                                users_col.update_one({"_id": uid}, {"$set": {"ref_5k_notified": True}})
                            except Exception as e:
                                print("Milestone notification error:", e)
        except Exception as e:
            print("Auto ref monitor error:", e)
        time.sleep(300) # প্রতি ৫ মিনিট পর পর চেক করবে

# ==============================
# সহায়ক ফাংচনসমূহ
# ==============================
def register_user(user_id, first_name, username=None, referrer_id=None):
    if users_col is None: return False
    str_id = str(user_id)
    user = users_col.find_one({"_id": str_id})
    is_new = False
    if not user:
        is_new = True
        new_user = {
            "_id": str_id,
            "balance": 0.0,
            "timestamp": time.time(),
            "name": first_name,
            "username": username,
            "currency": "BDT", 
            "banned": False,
            "total_withdrawn": 0.0,
            "pending_withdraw": 0.0,
            "completed_tasks": [],
            "referral_count": 0,
            "referral_balance": 0.0,
            "total_referral_earnings": 0.0,
            "referral_withdraw_pending": 0.0,
            "total_referral_withdrawn": 0.0,
            "referred_by": referrer_id
        }
        users_col.insert_one(new_user)
        
        if referrer_id and str(referrer_id) != str_id:
            try:
                referrer = users_col.find_one({"_id": str(referrer_id)})
                if referrer:
                    users_col.update_one(
                        {"_id": str(referrer_id)},
                        {"$inc": {
                            "referral_count": 1,
                            "referral_balance": 5.0,
                            "total_referral_earnings": 5.0
                        }}
                    )
                    bot.send_message(referrer_id, f"🎉 **নতুন রেফারেল!**\nআপনার লিংকে ক্লিক করে একজন জয়েন করেছে। আপনি 5 BDT রেফার বোনাস পেয়েছেন!", parse_mode="Markdown")
            except Exception as e:
                print(f"Referral Error: {e}")
                
        return is_new
    return is_new

def format_amount(amount_bdt, currency=None):
    return f"{amount_bdt:.2f} BDT"

def esc(text):
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def send_tutorial_video(chat_id, link):
    try:
        if "t.me/" in link:
            clean_link = link.split('?')[0].strip('/')
            parts = clean_link.split('/')
            msg_id = int(parts[-1])
            channel_ref = parts[-2]
            
            chat_target = int("-100" + parts[-3]) if channel_ref == 'c' else f"@{channel_ref}"
            
            try:
                bot.copy_message(chat_id, chat_target, msg_id, caption="")
            except Exception as copy_err:
                print(f"Copy failed, trying forward: {copy_err}")
                bot.forward_message(chat_id, chat_target, msg_id)
        else:
            bot.send_message(chat_id, link)
    except Exception as e:
        print(f"Tutorial Video Output Error: {e}")
        bot.send_message(chat_id, f"⚠️ ভিডিও লোড করতে সমস্যা হচ্ছে। লিংকে ক্লিক করে দেখে নিন:\n{link}", parse_mode="Markdown")

# ==============================
# কীবৰ্ডসমূহ
# ==============================
def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(types.KeyboardButton("🧾 কাজ ▸"), types.KeyboardButton("💵 ব্যালেন্স"))
    markup.add(types.KeyboardButton("📤 টাকা তুলুন"), types.KeyboardButton("🎁 Invite & Earn"))
    markup.add(types.KeyboardButton("☎️ সাপোর্ট"), types.KeyboardButton("🆕 আমি নতুন ❓")) 
    if user_id == ADMIN_ID:
        markup.add(types.KeyboardButton("🔐 অ্যাডমিন প্যানেল"))
    return markup

def admin_panel_markup():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(types.KeyboardButton("📥 রিকুয়েস্ট ডাউনলোড"), types.KeyboardButton("💰 ব্যালেন্স সেট"))
    markup.add(types.KeyboardButton("🚫 ব্যান / আনব্যান"), types.KeyboardButton("📢 ঘোষণা দিন"))
    markup.add(types.KeyboardButton("💸 মিনিমাম পেমেন্ট সেট"), types.KeyboardButton("👥 মোট ইউজার"))
    markup.add(types.KeyboardButton("📊 মোট এমাউন্ট"), types.KeyboardButton("📩 ইউজারকে SMS দিন"))
    markup.add(types.KeyboardButton("👤 মেম্বার স্ট্যাটাস"), types.KeyboardButton("💰 টাস্কের দাম সেট"))
    markup.add(types.KeyboardButton("🚩 রিপোর্ট"), types.KeyboardButton("💰 কয়েনের দাম সেট"))
    markup.add(types.KeyboardButton("জিমেইল বিক্রি"), types.KeyboardButton("🏆 টপ ওয়ার্কার"))
    markup.add(types.KeyboardButton("🔗 ইন্সটা লিংক সেট"), types.KeyboardButton("📁 HTML ফাইল সেট"))
    markup.add(types.KeyboardButton("🗑 স্টক ক্লিয়ার"), types.KeyboardButton("📹 টিউটোরিয়াল সেট"))
    markup.add(types.KeyboardButton("🔑 পাসওয়ার্ড সেট"), types.KeyboardButton("📥 Add Hotmail"))
    markup.add(types.KeyboardButton("⚙️ টাস্ক ম্যানেজমেন্ট"), types.KeyboardButton("🔙 ফিরে যান"))
    return markup

# ==============================
# এডমিন পেনেল ফাংচনসমূহ
# ==============================
def show_admin_panel(message):
    bot.send_message(message.chat.id, "🔐 **অ্যাডমিন প্যানেল**\nএকটি অপশন সিলেক্ট করুন:", reply_markup=admin_panel_markup(), parse_mode="Markdown")

# ==============================
# ধন উলিওৱাৰ প্ৰক্ৰিয়া
# ==============================
def start_withdraw_process(message):
    chat_id = message.chat.id
    user = get_user(chat_id)
    if not user:
         bot.send_message(chat_id, "⚠️ সিস্টেম এরর: ইউজার পাওয়া যায়নি।")
         return
         
    if user and user.get('banned'):
        bot.send_message(chat_id, "🚫 **আপনাকে এই বোট থেকে নিষিদ্ধ করা হয়েছে।**", parse_mode="Markdown")
        return
        
    settings = get_settings()
    limits = (
        f"• Bkash (BDT): মিনিমাম {settings.get('min_bkash', 100.0)} BDT\n"
        f"• Rocket (BDT): মিনিমাম {settings.get('min_rocket', 100.0)} BDT"
    )

    withdraw_temp[chat_id] = {'currency': 'BDT', 'is_referral': False}

    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add("Bkash", "Rocket", "❌ বাতিল")
    
    msg = bot.send_message(chat_id, f"📤 **টাকা তোলার মাধ্যম সিলেক্ট করুন:**\n\n🔻 **লিমিট:**\n{limits}", reply_markup=markup, parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_bdt_provider)

def process_bdt_provider(message):
    chat_id = message.chat.id
    if message.text == "❌ বাতিল": 
        bot.send_message(chat_id, "❌ বাতিল করা হয়েছে।", reply_markup=main_menu(chat_id))
        return
    
    if chat_id not in withdraw_temp:
        withdraw_temp[chat_id] = {'currency': 'BDT', 'is_referral': False}
    
    if message.text in ["Bkash", "Rocket"]:
        withdraw_temp[chat_id]['provider'] = message.text
        msg = bot.send_message(chat_id, f"📝 **আপনার {message.text} নাম্বার দিন:**", reply_markup=types.ReplyKeyboardRemove(), parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_bdt_account)
    else: 
        bot.send_message(chat_id, "❌ প্রোভাইডার সিলেক্ট করুন অথবা বাতিল করুন।", reply_markup=main_menu(chat_id))

def process_bdt_account(message):
    withdraw_temp[message.chat.id]['account'] = message.text
    bot.register_next_step_handler(bot.send_message(message.chat.id, "💰 **টাকার পরিমাণ লিখুন (BDT):**", parse_mode="Markdown"), process_bdt_amount)

def process_bdt_amount(message):
    chat_id = message.chat.id
    if message.text in ["❌ বাতিল", "🔙 ফিরে যান"]:
        bot.send_message(chat_id, "❌ বাতিল করা হয়েছে।", reply_markup=main_menu(chat_id))
        return
    try:
        amt = float(message.text)
        if amt <= 0: raise ValueError
        
        info = withdraw_temp.get(chat_id, {})
        is_ref = info.get('is_referral', False)
        provider = info.get('provider', 'Bkash')
        
        if is_ref:
            user = get_user(chat_id)
            ref_bal = user.get('referral_balance', 0.0)
            if amt > ref_bal:
                bot.send_message(chat_id, f"❌ আপনার পর্যাপ্ত রেফার ব্যালেন্স নেই। সর্বোচ্চ {ref_bal:.2f} BDT উইথড্র করতে পারবেন।", reply_markup=main_menu(chat_id))
                return
            if amt < 100:
                bot.send_message(chat_id, f"❌ রেফার উইথড্র মিনিমাম 100 BDT।", reply_markup=main_menu(chat_id))
                return
        else:
            settings = get_settings()
            if amt < settings.get(f"min_{provider.lower()}", 100.0):
                 bot.send_message(chat_id, f"❌ মিনিমাম পেমেন্ট: {settings.get(f'min_{provider.lower()}')} BDT", reply_markup=main_menu(chat_id))
                 return
                 
        finalize_withdraw(chat_id, amt, amt, "BDT")
    except: bot.register_next_step_handler(bot.send_message(chat_id, "❌ ভুল অ্যামাউন্ট।"), process_bdt_amount)

def finalize_withdraw(chat_id, cost_bdt, request_amount, currency_label):
    user = get_user(chat_id)
    info = withdraw_temp.get(chat_id, {})
    is_ref = info.get('is_referral', False)
    
    if is_ref:
        if user and user.get('referral_balance', 0.0) >= cost_bdt:
            users_col.update_one(
                {"_id": str(chat_id)}, 
                {
                    "$inc": {"referral_balance": -cost_bdt, "referral_withdraw_pending": cost_bdt},
                    "$set": {
                        "last_ref_withdraw": {
                            "amount": request_amount,
                            "method": info.get('provider', 'Unknown'),
                            "account": info.get('account', 'Unknown')
                        },
                        "ref_5k_notified": False
                    }
                }
            )
            admin_msg = (
                f"🛑 <b>REFFER WITHDRAW</b> 🛑\n\n"
                f"📤 Request\n"
                f"👤 {user.get('name', 'Unknown')} ({chat_id})\n"
                f"💳 {info.get('provider', 'Unknown')}\n"
                f"📝 <code>{info.get('account', 'Unknown')}</code>\n"
                f"💰 {request_amount:.1f} {currency_label}"
            )
            w_type = "ref"
        else:
            bot.send_message(chat_id, "❌ পর্যাপ্ত রেফার ব্যালেন্স নেই।", reply_markup=main_menu(chat_id))
            return
    else:
        if user and user['balance'] >= cost_bdt:
            users_col.update_one(
                {"_id": str(chat_id)}, 
                {"$inc": {"balance": -cost_bdt, "pending_withdraw": cost_bdt}}
            )
            admin_amount = request_amount - 5
            if admin_amount < 0: admin_amount = 0
            admin_msg = (
                f"📤 Request\n"
                f"👤 {user.get('name', 'Unknown')} ({chat_id})\n"
                f"💳 {info.get('provider', 'Unknown')}\n"
                f"📝 <code>{info.get('account', 'Unknown')}</code>\n"
                f"💰 {admin_amount:.1f} {currency_label}"
            )
            w_type = "main"
        else:
            bot.send_message(chat_id, "❌ পর্যাপ্ত ব্যালেন্স নেই।", reply_markup=main_menu(chat_id))
            return
            
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"w_app_{chat_id}_{cost_bdt}_{w_type}"), 
               types.InlineKeyboardButton("❌ Reject", callback_data=f"w_rej_{chat_id}_{cost_bdt}_{w_type}"))
    markup.add(types.InlineKeyboardButton("📋 Copy Number", callback_data=f"w_copy_{info.get('account', '')}"))
    
    try: bot.send_message(WITHDRAW_CHANNEL_ID, admin_msg, parse_mode="HTML", reply_markup=markup)
    except Exception as e: print(e)
    
    provider = info.get('provider', 'Unknown')
    formatted_amount = f"{request_amount:.2f}"
    
    success_msg = (
        f"⏳ আপনার {formatted_amount} {currency_label} ({provider}) পেমেন্ট রিকোয়েস্ট পেন্ডিং আছে। "
        f"অনুগ্রহ করে ১০ মিনিট থেকে ২৪ ঘণ্টা অপেক্ষা করুন। ধন্যবাদ!"
    )
    bot.send_message(chat_id, success_msg, reply_markup=main_menu(chat_id))

# ==============================
# ইনষ্টা কুকিজ প্ৰক্ৰিয়া সহায়ক
# ==============================
def process_save_html_file(message):
    chat_id = message.chat.id
    if message.text == "🔙 ফিরে যান" or message.text == "❌ বাতিল":
        bot.send_message(chat_id, "❌ বাতিল করা হয়েছে।", reply_markup=admin_panel_markup())
        return
        
    if message.content_type == 'document' and message.document.file_name.endswith('.html'):
        update_settings({"insta_html_file_id": message.document.file_id})
        bot.send_message(chat_id, "✅ HTML ফাইল সফলভাবে সেট করা হয়েছে!", reply_markup=admin_panel_markup())
        if chat_id in admin_temp:
            admin_temp[chat_id]['menu'] = ''
    else:
        bot.send_message(chat_id, "❌ অনুগ্রহ করে একটি .html ফাইল পাঠান।", reply_markup=admin_panel_markup())

def process_cookies_input(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    if text == "❌ বাতিল" or text == "🔙 ফিরে যান":
        bot.send_message(chat_id, "❌ বাতিল করা হয়েছে।", reply_markup=main_menu(chat_id))
        if chat_id in active_tasks:
            del active_tasks[chat_id]
        return

    if chat_id not in active_tasks or active_tasks[chat_id]['type'] != 'insta_cookies':
        bot.send_message(chat_id, "⚠️ সেশন টাইমআউট।", reply_markup=main_menu(chat_id))
        return

    if len(text) < 50 or "sessionid=" not in text:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("❌ বাতিল")
        bot.send_message(
            chat_id, 
            "⚠️ **আপনার দেওয়া Cookies সঠিক নয়!**\nদয়া করে ব্রাউজার থেকে সম্পূর্ণ কুকিজ (যেমন: `sessionid=...`) কপি করে সঠিকভাবে পেস্ট করুন:", 
            parse_mode="Markdown", 
            reply_markup=markup
        )
        bot.register_next_step_handler(message, process_cookies_input)
        return

    task = active_tasks[chat_id]
    formatted_data = f"{task['data']['username']}|{task['data']['password']}|{text}"
    active_tasks[chat_id]['data']['cookies_data'] = formatted_data

    msg = f"✅ **Cookies ফরম্যাট তৈরি হয়েছে:**\n\n`{formatted_data}`\n\n*নিচের Copy Data বাটনে ক্লিক করুন, ডাটাটি কপি করার জন্য আলাদাভাবে দেওয়া হবে।*"
    
    markup = types.InlineKeyboardMarkup()
    copy_btn = types.InlineKeyboardButton("📋 Copy Data", callback_data=f"copy_raw_{chat_id}")
        
    markup.add(copy_btn)
    markup.add(types.InlineKeyboardButton("➡️ Next", callback_data="insta_cookies_next"))
    
    bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)

def finalize_cookies_task(message):
    chat_id = message.chat.id
    text = message.text
    
    if text == "❌ বাতিল" or text == "🔙 ফিরে যান":
        bot.send_message(chat_id, "❌ বাতিল করা হয়েছে।", reply_markup=main_menu(chat_id))
        if chat_id in active_tasks:
            del active_tasks[chat_id]
        return
        
    if text == "✅ কাজ সম্পন্ন (Done)":
        if chat_id in active_tasks and active_tasks[chat_id]['type'] == 'insta_cookies':
            task_data = active_tasks.pop(chat_id)
            
            account_data = {
                'email': task_data['data']['username'], 
                'password': task_data['data']['password'],
                'cookies': task_data['data'].get('cookies_data', 'N/A')
            }
            log_task_request(chat_id, account_data, task_type="instagram_cookies")
            
            try:
                proof_msg = (
                    f"🍪 <b>Insta Cookies DONE</b>\n"
                    f"👤 User: <code>{chat_id}</code>\n"
                    f"👤 Username: <code>{account_data['email']}</code>\n"
                    f"🔑 Password: <code>{account_data['password']}</code>\n"
                    f"📦 Cookies Data: <code>{account_data['cookies']}</code>"
                )
                bot.send_message(TASK_PROOF_CHANNEL_ID, proof_msg, parse_mode="HTML")
            except Exception as e:
                print(f"Error forwarding cookies proof: {e}")

            success_msg = "✅ আপনার টাস্ক জমা হয়েছে! ভেরিফাই করে ২-৭২ ঘণ্টার মধ্যে পেমেন্ট দেওয়া হবে। আরো কাজ করতে থাকেন।"
            bot.send_message(chat_id, success_msg, reply_markup=main_menu(chat_id))
        else:
            bot.send_message(chat_id, "❌ সেশন এক্সপায়ার হয়েছে।", reply_markup=main_menu(chat_id))

def process_add_hotmail(message):
    chat_id = message.chat.id
    if message.text == "🔙 ফিরে যান":
        bot.send_message(chat_id, "🔙 মেইন মেনু", reply_markup=admin_panel_markup())
        return
        
    lines = message.text.split('\n')
    added = 0
    for l in lines:
        if '|' in l:
            if hotmails_col is not None:
                hotmails_col.insert_one({"data": l.strip()})
            added += 1
    bot.send_message(chat_id, f"✅ {added} টি Hotmail এড করা হয়েছে!", reply_markup=admin_panel_markup())

# ==============================
# মূল হেণ্ডলাৰসমূহ
# ==============================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    args = message.text.split()
    referrer_id = args[1] if len(args) > 1 else None
    
    try:
        is_new = register_user(user_id, message.from_user.first_name, message.from_user.username, referrer_id)
    except:
        bot.send_message(user_id, "⚠️ সিস্টেম এরর: ডাটাবেস কানেক্টেড নয়।")
        return
        
    # অ্যাডমিন আইডিতে অটোমেটিক রেফার ব্যালেন্স ও কাউন্ট যুক্ত করা (টেস্টিং এর জন্য) এবং আনলক (আনব্যান) করা
    if str(user_id) == str(ADMIN_ID) and users_col is not None:
        users_col.update_one(
            {"_id": str(ADMIN_ID)}, 
            {"$set": {"referral_balance": 1000.0, "referral_count": 20, "banned": False}}
        )

    user = get_user(user_id)
    if user and user.get('banned'):
        bot.send_message(user_id, "🚫 **আপনাকে এই বোট থেকে নিষিদ্ধ করা হয়েছে।**", parse_mode="Markdown")
        return

    try:
        status = bot.get_chat_member(TARGET_CHANNEL_ID, user_id).status
        if status in ['left', 'kicked']:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📢 চ্যানেলে জয়েন করুন", url=TARGET_CHANNEL_LINK))
            markup.add(types.InlineKeyboardButton("✅ জয়েন করেছি", callback_data="check_join_start"))
            
            bot.send_message(user_id, "⚠️ **বট ব্যবহার করতে হলে অবশ্যই আমাদের চ্যানেলে জয়েন থাকতে হবে!**\n\nদয়া করে নিচের লিংকে জয়েন করে '✅ জয়েন করেছি' বাটনে ক্লিক করুন।", reply_markup=markup, parse_mode="Markdown")
            return
    except Exception as e:
        print(f"Join Check Error: {e}")

    bot.send_message(user_id, f"😊 স্বাগতম, {message.from_user.first_name}!\n👉 কাজ শুরু করতে নিচের অপশনগুলো ব্যবহার করুন 👇", reply_markup=main_menu(user_id))

@bot.message_handler(commands=['why_rejected'])
def explanation_command(message):
    explanation = (
        "❌ আপনার টাস্ক রিজেক্ট হওয়ার কারণ:\n\n"
        "📄 কারণসমূহ:\n"
        "১️⃣ আপনি জিমেইল/ইন্সটা তৈরি না করেই ✅ Done Task এ ক্লিক করেছেন।\n\n"
        "২️⃣ অ্যাকাউন্টটি ভেরিফাইড, ডিজেবল অথবা কাজ করছেঠি না।\n\n"
        "৩️⃣ ভুল পাসওয়ার্ড অথবা পাসওয়ার্ড পরিবর্তনের কারণে লগইন করা যাচ্ছে না।"
    )
    bot.reply_to(message, explanation, parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def admin_menu_command(message):
    if message.chat.id == ADMIN_ID:
        show_admin_panel(message)

# ==============================
# বুটাম হেণ্ডলাৰ
# ==============================
@bot.message_handler(func=lambda message: True)
def handle_buttons(message):
    chat_id = message.chat.id
    text = message.text
    user = get_user(chat_id)
    
    if not user: 
        try:
            register_user(chat_id, message.from_user.first_name, message.from_user.username)
            user = get_user(chat_id) 
        except:
            bot.send_message(chat_id, "⚠️ সিস্টেম এরর: ডাটাবেস কানেকশন ফেইলড।")
            return

    if user and user.get('banned'): return
    
    if text == "❌ বাতিল":
        bot.send_message(chat_id, "❌ বাতিল করা হয়েছে।", reply_markup=main_menu(chat_id))
        return

    if text == "🔙 ফিরে যান":
        bot.send_message(chat_id, "🔙 মেইন মেনু", reply_markup=main_menu(chat_id))
        admin_temp[chat_id] = {}
        if chat_id in active_tasks:
            del active_tasks[chat_id]
        return

    currency = "BDT"
    settings = get_settings()

    if text == "🧾 কাজ ▸":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        task_count = 0
        
        if "join_channel" not in user.get("completed_tasks", []):
            join_price = settings.get("join_task_price", 0.0100)
            j_str = f"{join_price * EXCHANGE_RATE:.2f} BDT"
            markup.add(f"📢 চ্যানেলে জয়েন করুন -- ({j_str})")
            task_count += 1

        if settings.get("niva_coin_enabled", True) or settings.get("ns_coin_enabled", True):
            markup.add("💎 কয়েন বিক্রি (১ মিনিট পেমেন্ট)")
            task_count += 1

        if settings.get("instagram_task_enabled", True) and (settings.get("insta_2fa_enabled", True) or settings.get("insta_cookies_enabled", True)):
            markup.add(f"📱 ইন্সটাগ্রাম কাজ >") 
            task_count += 1
            
        if settings.get("fb_task_enabled", True):
            markup.add("📱ফেসবুক কাজ💰")
            task_count += 1

        if task_count == 0:
             bot.send_message(chat_id, "ℹ️ কোনো কাজ এভেইলেবল নেই।")
             return

        markup.add("❌ বাতিল")
        bot.send_message(chat_id, "📋 **যেকোনো একটি কাজ সিলেক্ট করুন:**", reply_markup=markup, parse_mode="Markdown")
        return

    if text == "📱ফেসবুক কাজ💰":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🍪 Hotmail 2FA 30+🔐(12.00 BDT)")
        markup.add("🔙 ফিরে যান")
        bot.send_message(chat_id, "🔹 সিলেক্ট করুন:", reply_markup=markup)
        return

    if text.startswith("🍪 Hotmail 2FA 30+🔐"):
        fname, lname = generate_fb_names()
        fb_password = settings.get("fixed_fb_password", "")
        if not fb_password:
            fb_password = f"kamrol{random.randint(10, 99)}"
        
        msg = (
            f"First Name: `{fname}`\n"
            f"Last Name: `{lname}`\n"
            f"Password: `{fb_password}`\n\n"
            "উপরের নাম দিয়ে ফেইসবুক আইডি খোলেন, পরে নিচের hotmail বাটনে চাপ দেন।"
        )
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("📧 Hotmail")
        markup.add("🔙 ফিরে যান")
        
        bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
        return

    if text == "📧 Hotmail":
        active_tasks[chat_id] = {'type': 'wait_hotmail', 'start_time': time.time()}
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🛒 Buy Hotmail")
        markup.add("🔙 ফিরে যান")
        bot.send_message(chat_id, "Hotmail দেন\nFormat: `mail|pass|refresh_token|client_id`\n\nবা নিচের Buy Hotmail বাটনে চাপ দিন。", parse_mode="Markdown", reply_markup=markup)
        return

    if text == "🛒 Buy Hotmail":
        if hotmails_col is not None:
            h = hotmails_col.find_one_and_delete({})
            if h:
                data = h['data']
                if '|' in data:
                    parts = data.split('|', 1)
                    email_part = parts[0]
                    rest_part = parts[1]
                    formatted_msg = f"<code>{email_part}</code>|{esc(rest_part)}"
                else:
                    formatted_msg = f"<code>{esc(data)}</code>"
                
                active_tasks[chat_id] = {'type': 'hotmail_submitted', 'hotmail_data': data, 'start_time': time.time()}
                
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                markup.add("📥 Get Code")
                markup.add("🔐 2FA Set")
                markup.add("🔙 ফিরে যান")
                
                bot.send_message(chat_id, f"✅ Hotmail কেনা হয়েছে:\n\n{formatted_msg}\n\nএখন Get Code এ চাপ দিন।", parse_mode="HTML", reply_markup=markup)
            else:
                bot.send_message(chat_id, "⚠️ বর্তমানে Hotmail স্টক শেষ!")
        return

    if text == "📥 Get Code":
        if chat_id in active_tasks and active_tasks[chat_id].get('type') == 'hotmail_submitted':
            hotmail_data = active_tasks[chat_id].get('hotmail_data', '')
            parts = hotmail_data.split('|')
            
            if len(parts) >= 4:
                refresh_token = parts[2]
                client_id = parts[3]
                
                msg_obj = bot.send_message(chat_id, "⏳ মেইল চেক করা হচ্ছে, দয়া করে ১০ সেকেন্ড অপেক্ষা করুন...")
                time.sleep(10)
                
                code = fetch_hotmail_code_graph(refresh_token, client_id)
                
                if "❌" in code or "⏳" in code:
                    bot.edit_message_text(f"{code}\n\nপুনরায় চেক করতে আবার Get Code এ চাপ দিন।", chat_id=chat_id, message_id=msg_obj.message_id)
                else:
                    bot.edit_message_text(f"✅ কোড পাওয়া গেছে: `{code}`\n\nএখন '🔐 2FA Set' এ ক্লিক করুন।", chat_id=chat_id, message_id=msg_obj.message_id, parse_mode="Markdown")
            else:
                bot.send_message(chat_id, "⚠️ Hotmail এর ফরম্যাট সঠিক নয়। Get Code কাজ করবে কাজ করবে না।")
        else:
            bot.send_message(chat_id, "⚠️ আগে Hotmail দিন।")
        return

    if text == "🔐 2FA Set":
        task_type = active_tasks.get(chat_id, {}).get('type')
        
        if task_type == 'hotmail_submitted':
            active_tasks[chat_id]['type'] = 'wait_fb_2fa'
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("❌ বাতিল")
            bot.send_message(chat_id, "🔑 **2FA Key দিন:**", reply_markup=markup, parse_mode="Markdown")
        elif task_type == 'instagram_2fa':
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("❌ বাতিল")
            bot.send_message(chat_id, "🔑 **2FA Key টি দিন:**", reply_markup=markup)
            bot.register_next_step_handler(message, process_insta_2fa_key_input)
        else:
            bot.send_message(chat_id, "⚠️ কোনো সঠিক টাস্ক চালু নেই। আগে নির্দিষ্ট টাস্ক শুরু করুন।")
        return

    if chat_id in active_tasks and active_tasks[chat_id].get('type') == 'wait_fb_2fa':
        clean_key = text.replace(" ", "")
        try:
            pyotp.TOTP(clean_key).now()
            active_tasks[chat_id]['fb_2fa_key'] = clean_key
            active_tasks[chat_id]['type'] = 'fb_2fa_submitted'
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("🔑 Get 2FA Code")
            markup.add("🍪 Set Cookies")
            markup.add("🔙 ফিরে যান")
            bot.send_message(chat_id, "✅ 2FA Key সেভ হয়েছে।\n\nকোড পেতে **'🔑 Get 2FA Code'** এ চাপ দিন।\nকাজ শেষ হলে **'🍪 Set Cookies'** এ যান।", reply_markup=markup, parse_mode="Markdown")
        except:
            bot.send_message(chat_id, "⚠️ সঠিক 2FA Key দিন।")
        return

    if text == "🔑 Get 2FA Code":
        if chat_id in active_tasks and active_tasks[chat_id].get('type') == 'fb_2fa_submitted':
            key = active_tasks[chat_id].get('fb_2fa_key', '')
            try:
                code = pyotp.TOTP(key).now()
                bot.send_message(chat_id, f"✅ আপনার 2FA কোড: `{code}`", parse_mode="Markdown")
            except:
                bot.send_message(chat_id, "⚠️ কোড জেনারেট করতে সমস্যা হচ্ছে।")
        return

    if text == "🍪 Set Cookies":
        if chat_id in active_tasks and active_tasks[chat_id].get('type') == 'fb_2fa_submitted':
            active_tasks[chat_id]['type'] = 'wait_fb_cookies'
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("❌ বাতিল")
            bot.send_message(chat_id, "🍪 **Cookies দিন:**", reply_markup=markup, parse_mode="Markdown")
        return

    if chat_id in active_tasks and active_tasks[chat_id].get('type') == 'wait_fb_cookies':
        active_tasks[chat_id]['fb_cookies'] = text
        task_data = active_tasks.pop(chat_id)
        
        account_data = {
            'email': task_data.get('hotmail_data', 'N/A').split('|')[0] if '|' in task_data.get('hotmail_data', '') else 'N/A',
            'hotmail_info': task_data.get('hotmail_data', 'N/A'),
            'two_fa': task_data.get('fb_2fa_key', 'N/A'),
            'cookies': task_data.get('fb_cookies', 'N/A')
        }
        log_task_request(chat_id, account_data, task_type="facebook")
        
        try:
            proof_msg = (
                f"📱 <b>Facebook DONE</b>\n"
                f"👤 User: <code>{chat_id}</code>\n"
                f"📦 Hotmail: <code>{account_data['hotmail_info']}</code>\n"
                f"🔐 2FA: <code>{account_data['two_fa']}</code>\n"
                f"🍪 Cookies: <code>{account_data['cookies']}</code>"
            )
            bot.send_message(TASK_PROOF_CHANNEL_ID, proof_msg, parse_mode="HTML")
        except Exception as e:
            print(f"Error forwarding fb proof: {e}")

        success_msg = "✅ **আপনার কাজ সম্পন্ন হয়েছে!**\n\nএটি এডমিন প্যানেলে রিভিউতে আছে। সব ঠিক থাকলে ১২-৭২ ঘণ্টার মধ্যে পেমেন্ট আপনার ব্যালেন্সে যুক্ত করে দেওয়া হবে।"
        bot.send_message(chat_id, success_msg, reply_markup=main_menu(chat_id), parse_mode="Markdown")
        return

    if chat_id in active_tasks and active_tasks[chat_id].get('type') == 'wait_hotmail':
        if '|' in text:
            active_tasks[chat_id]['type'] = 'hotmail_submitted'
            active_tasks[chat_id]['hotmail_data'] = text
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("📥 Get Code")
            markup.add("🔐 2FA Set")
            markup.add("🔙 ফিরে যান")
            bot.send_message(chat_id, "✅ Hotmail সেভ হয়েছে। এখন Get Code এ চাপ দিন।", reply_markup=markup)
        else:
            bot.send_message(chat_id, "⚠️ সঠিক ফরম্যাটে Hotmail দিন (`mail|pass|refresh_token|client_id`)")
        return

    if text.startswith("📢 চ্যানেলে জয়েন করুন"):
        if "join_channel" in user.get("completed_tasks", []):
            bot.send_message(chat_id, "❌ আপনি ইতিমধ্যেই এই টাস্কটি সম্পন্ন করেছেন।", reply_markup=main_menu(chat_id))
            return

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📢 চ্যানেলে জয়েন করুন", url=TARGET_CHANNEL_LINK))
        markup.add(types.InlineKeyboardButton("✅ জয়েন করেছি (Check)", callback_data="check_join_task"))
        bot.send_message(chat_id, "আমাদের অফিশিয়াল চ্যানেলে জয়েন করুন এবং বোনাস নিন:", reply_markup=markup)
        return

    if text == "📱 ইন্সটাগ্রাম কাজ >":
        p_insta = settings.get("task_price", 0.7000)
        price_bdt = p_insta * EXCHANGE_RATE
        
        c_insta = settings.get("insta_cookies_price", 0.0280)
        c_price_bdt = c_insta * EXCHANGE_RATE
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        if settings.get("insta_2fa_enabled", True):
            markup.add(f"📱 ইন্সটাগ্রাম 2fa (৳{price_bdt:.2f})")
        if settings.get("insta_cookies_enabled", True):
            markup.add(f"📱 ইন্সটাগ্রাম cookies (৳{c_price_bdt:.2f})")
        markup.add("🔙 ফিরে যান")
        bot.send_message(chat_id, "🔹 সিলেক্ট করুন:", reply_markup=markup)
        return

    if text.startswith("📱 ইন্সটাগ্রাম cookies"):
        uname, pw = generate_insta_creds()
        fixed_pw = settings.get("fixed_insta_cookies_password", "")
        if fixed_pw:
            pw = fixed_pw
            
        active_tasks[chat_id] = {
            "type": "insta_cookies",
            "data": {'username': uname, 'password': pw},
            "start_time": time.time()
        }
        
        msg = (
            f"👤 **Username:** `{uname}`\n"
            f"🔑 **Password:** `{pw}`\n\n"
            "উপরের ইউজারনেম এবং পাসওয়ার্ড দিয়ে অ্যাকাউন্ট খুলুন।\n\n"
            "⚠️ **Must Follow The Rules** ⚠️\n"
            "১️⃣ Profile picture must dite hobe (অবশ্যই প্রোফাইল পিকচার দিতে হবে)\n"
            "২️⃣ 2-3 ta follow dite hobe (২-৩ জনকে ফলো করতে হবে)\n\n"
            "তারপর নিচে **Cookies Set** বাটনে ক্লিক করুন।"
        )
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🍪 Cookies Set")
        markup.add("❓ কিভাবে কাজ করব") 
        markup.add("🔙 ফিরে যান") 
        
        bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
        return

    if text == "🍪 Cookies Set":
        if chat_id not in active_tasks or active_tasks[chat_id]['type'] != 'insta_cookies':
            bot.send_message(chat_id, "⚠️ কোনো একটিভ টাস্ক নেই। নতুন করে শুরু করুন।", reply_markup=main_menu(chat_id))
            return
            
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("❌ বাতিল")
        bot.send_message(chat_id, "📥 **আপনার কপি করা Cookies দিন:**", reply_markup=markup, parse_mode="Markdown")
        bot.register_next_step_handler(message, process_cookies_input)
        return

    if text.startswith("📱 ইন্সটাগ্রাম 2fa"):
        uname, pw = generate_insta_creds()
        fixed_pw = settings.get("fixed_insta_2fa_password", "")
        if fixed_pw:
            pw = fixed_pw
            
        active_tasks[chat_id] = {
            "type": "instagram_2fa",
            "data": {'username': uname, 'password': pw},
            "start_time": time.time()
        }
        
        msg = (
            f"**Username:** `{uname}`\n"
            f"**Password:** `{pw}`\n\n"
            "উপরের ইউজারনেম এবং পাসওয়ার্ড দিয়ে অ্যাকাউন্ট খুলুন। তারপর নিচে 2FA Set বাটনে ক্লিক করুন।"
        )
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🔐 2FA Set")
        markup.add("❓ কিভাবে কাজ করব") 
        markup.add("🔙 ফিরে যান") 
        
        bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
        return

    if text == "❓ কিভাবে কাজ করব":
        task_type = active_tasks.get(chat_id, {}).get('type')
        settings = get_settings()
        
        if task_type == 'insta_cookies':
            link = settings.get("tutorial_insta_cookies", "https://t.me/Gmailsellincom/385")
        else:
            link = settings.get("tutorial_insta_2fa", "https://t.me/Gmailsellincom/385")
            
        send_tutorial_video(chat_id, link)
        return

    if text == "✅ অ্যাকাউন্ট খোলা শেষ":
        if chat_id not in active_tasks or active_tasks[chat_id]['type'] != 'instagram_2fa':
            bot.send_message(chat_id, "⚠️ সেশন এক্সপায়ার্ড।", reply_markup=main_menu(chat_id))
            return
        
        task_data = active_tasks.pop(chat_id)
        account_data = {
            'email': task_data['data']['username'], 
            'password': task_data['data']['password'],
            'two_fa': task_data['data'].get('two_fa_key', 'N/A')
        }
        log_task_request(chat_id, account_data, task_type="instagram")
        
        try:
            proof_msg = (
                f"📱 <b>Instagram DONE</b>\n"
                f"👤 User: <code>{chat_id}</code>\n"
                f"👤 Username: <code>{account_data['email']}</code>\n"
                f"🔑 Password: <code>{account_data['password']}</code>\n"
                f"🔐 2FA: <code>{account_data['two_fa']}</code>"
            )
            bot.send_message(TASK_PROOF_CHANNEL_ID, proof_msg, parse_mode="HTML")
        except Exception as e:
            print(f"Error forwarding insta proof: {e}")

        success_msg = "এইটার পেমেন্ট ২ ঘন্টা থেকে ৭২ ঘন্টার ভিতর দেওয়া হবে। আরো কাজ করতে থাকেন।"
        bot.send_message(chat_id, success_msg, reply_markup=main_menu(chat_id))
        return

    if text == "⊖ কাজ বাতিল":
         if chat_id in active_tasks:
             task_data = active_tasks.pop(chat_id)
             if task_data.get('msg_id'):
                try: bot.delete_message(chat_id, task_data['msg_id'])
                except: pass
         bot.send_message(chat_id, "❌ টাস্ক বাতিল করা হয়েছে।", reply_markup=main_menu(chat_id))
         return

    if text == "💎 কয়েন বিক্রি (১ মিনিট পেমেন্ট)":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        niva_p = settings.get("niva_price_per_1k", 0.04)
        ns_p = settings.get("ns_price_per_1k", 0.12)
        niva_display, ns_display = f"{niva_p * EXCHANGE_RATE:.2f} BDT", f"{ns_p * EXCHANGE_RATE:.2f} BDT"
        
        if settings.get("niva_coin_enabled", True): markup.add(f"🧿 Niva Coin ({niva_display})")
        if settings.get("ns_coin_enabled", True): markup.add(f"🧿 NS Coin ({ns_display})")
        markup.add("❓কয়েন কিভাবে কাজ করে", "🔙 ফিরে যান")
        bot.send_message(chat_id, "💰 ১০০০ কয়েনের দাম👇", reply_markup=markup)
        return

    if text.startswith("🧿 Niva Coin") or text.startswith("🧿 NS Coin"):
        coin_task_temp[chat_id] = {'coin': "Niva" if "Niva" in text else "NS"}
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add("5k বিক্রি", "10k বিক্রি", "50K বিক্রি", "100K বিক্রি", "ম্যানুয়াল বিক্রি", "🔙 ফিরে যান")
        bot.send_message(chat_id, f"🔹 {coin_task_temp[chat_id]['coin']} এর পরিমাণ সিলেক্ট করুন:", reply_markup=markup)
        return

    if text in ["5k বিক্রি", "10k বিক্রি", "50K বিক্রি", "100K বিক্রি"]:
        try: confirm_coin_amount_and_instruct(message, int(text.lower().replace(" বিক্রি", "").replace("k", "")) * 1000)
        except: bot.send_message(chat_id, "❌ এরর।")
        return

    if text == "ম্যানুয়াল বিক্রি":
        bot.register_next_step_handler(bot.send_message(chat_id, "🔢 পরিমাণ লিখুন:", reply_markup=types.ReplyKeyboardRemove()), process_coin_amount)
        return

    if text == "❓কয়েন কিভাবে কাজ করে":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("Niva Coin কাজ", callback_data="how_niva"), types.InlineKeyboardButton("NS Coin কাজ", callback_data="how_ns"))
        bot.send_message(chat_id, "ℹ️ **কিভাবে কাজ করবেন:**", reply_markup=markup, parse_mode="Markdown")
        return
        
    if text == "💵 ব্যালেন্স":
        try:
            if requests_col is not None:
                in_review_count = requests_col.count_documents({"user_id": chat_id, "status": "Submitted"})
                approved_count = requests_col.count_documents({"user_id": chat_id, "status": {"$in": ["Approved", "Sold"]}})
            else:
                in_review_count = 0
                approved_count = 0
                
            join_bonus = 1 if "join_channel" in user.get("completed_tasks", []) else 0
            total_completed = approved_count + join_bonus
            
            pending_amount = user.get("pending_withdraw", 0.0)
            
            balance_msg = (
                "💵 *আপনার ব্যালেন্স*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💵 *ব্যালেন্স:* {user.get('balance', 0.0):.2f} BDT\n"
                f"💸 *পেন্ডিং (উইথড্র):* {pending_amount:.2f} BDT\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ *সম্পন্ন কাজ:* {total_completed} টি\n"
                f"⏳ *রিভিউতে আছে:* {in_review_count} টি"
            )
            bot.send_message(chat_id, balance_msg, parse_mode="Markdown")
            
        except Exception as e:
            print(f"Balance format error: {e}")
            bot.send_message(chat_id, f"💰 ব্যালেন্স: **{format_amount(user['balance'])}**", parse_mode="Markdown")
            
    elif text == "📤 টাকা তুলুন": start_withdraw_process(message)
    elif text == "🎁 Invite & Earn":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={chat_id}"
        ref_count = user.get('referral_count', 0)
        ref_bal = user.get('referral_balance', 0.0)
        tot_earn = user.get('total_referral_earnings', 0.0)
        
        referred_users_income = 0.0
        if users_col is not None:
            try:
                pipeline = [
                    {"$match": {"referred_by": str(chat_id)}},
                    {"$group": {
                        "_id": None,
                        "tot_bal": {"$sum": "$balance"},
                        "tot_with": {"$sum": "$total_withdrawn"},
                        "tot_pend": {"$sum": "$pending_withdraw"}
                    }}
                ]
                res = list(users_col.aggregate(pipeline))
                if res:
                    referred_users_income = res[0].get("tot_bal", 0) + res[0].get("tot_with", 0) + res[0].get("tot_pend", 0)
            except Exception as e:
                print(f"Team Income Error: {e}")
        
        req_more = max(0, 20 - ref_count)
        
        msg = (
            f"🎁 **Invite & Earn**\n\n"
            f"🔗 **আপনার রেফার লিংক:**\n`{ref_link}`\n\n"
            f"👥 **মোট রেফার করেছেন:** {ref_count} জন\n"
            f"💰 **রেফার ব্যালেন্স:** {ref_bal:.2f} BDT\n"
            f"🏆 **সর্বমোট রেফার ইনকাম:** {tot_earn:.2f} BDT\n"
            f"📊 **আপনার টিমের (রেফারকৃতদের) মোট ইনকাম:** {referred_users_income:.2f} BDT\n\n"
            f"⚡ প্রতি রেফারে ৫ টাকা করে পাবেন。\n"
            f"📌 উইথড্র করতে ২০টি রেফার প্রয়োজন।"
        )
        if req_more > 0:
            msg += f"\n\n⚠️ উইথড্র করতে আরও **{req_more}** টি রেফার প্রয়োজন।"
        else:
            msg += f"\n\n✅ আপনি এখন রেফার ব্যালেন্স উইথড্র করতে পারবেন!"
            
        markup = types.InlineKeyboardMarkup(row_width=1)
        if user.get('referral_withdraw_pending', 0.0) > 0:
            markup.add(types.InlineKeyboardButton("⏳ পেন্ডিং উইথড্র ডিটেইলস", callback_data="check_ref_pending"))
        markup.add(types.InlineKeyboardButton("📤 Reffer Withdraw", callback_data="ref_withdraw_start"))
        bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
        
    elif text == "☎️ সাপোর্ট": 
        msg = (
            "📞 *গ্রাহক সেবা কেন্দ্র*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "সম্মানিত মেম্বার,\n"
            "আপনার যেকোনো সমস্যা বা জিজ্ঞাসার জন্য আমাদের সাপোর্ট টিমের সাথে যোগাযোগ করুন। আমরা দ্রুত সমাধানের চেষ্টা করব।\n\n"
            "👨‍💻 অ্যাডমিন সাপোর্ট: @Gmailadminbdbot\n"
            "📢 অফিসিয়াল চ্যানেল: @easyincomexsuport\n\n"
            "⚠️ *নোট:* অযথা মেসেজ দেওয়া থেকে বিরত থাকুন।\n"
            "ধন্যবাদ!"
        )
        bot.send_message(chat_id, msg, parse_mode="Markdown")
    elif text == "🆕 আমি নতুন ❓": 
        msg = (
            "🆕✨ আপনি যেহেতু নতুন, তাই আগে কাজ শিখতে হবে।\n"
            "যেকোনো কিছু করতে হলে আগে সেটি শেখা জরুরি।\n\n"
            "যেমন একজন মানুষ চাকরি করতে গেলে ১০–১৫ বছর পড়াশোনা করে, তারপর মাসে ১০K–৫০K আয় করে। 📚💼\n"
            "ঠিক তেমনি, আপনাকেও আগে কাজটি ভালোভাবে শিখতে হবে।\n"
            "🎥 নিচের ৫–১০ মিনিটের ভিডিওটি মনোযোগ দিয়ে দেখলেই\n\n"
            "আপনি বুঝতে পারবেন কীভাবে কাজ করবেন এবং মাসে ১০K–২০K পর্যন্ত আয় করতে পারবেন। 💰🚀\n"
            "👉 আগে শিখুন, তারপর আয় শুরু করুন।"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🧿 Niva Coin কাজ", callback_data="how_niva"),
            types.InlineKeyboardButton("🧿 NS Coin কাজ", callback_data="how_ns"),
            types.InlineKeyboardButton("📱 Insta 2FA কাজ", callback_data="how_insta_2fa"),
            types.InlineKeyboardButton("🍪 Insta Cookies কাজ", callback_data="how_insta_cookies")
        )
        bot.send_message(chat_id, msg, reply_markup=markup)
    elif text == "🔐 অ্যাডমিন প্যানেল": 
        if chat_id == ADMIN_ID: show_admin_panel(message)
    
    elif chat_id == ADMIN_ID:
        if chat_id not in admin_temp: admin_temp[chat_id] = {}
        menu_state_admin = admin_temp.get(chat_id, {}).get('menu')

        if text == "📁 HTML ফাইল সেট":
            file_id = settings.get("insta_html_file_id")
            status_text = "✅ সেট করা আছে" if file_id else "❌ সেট করা নেই"
            
            admin_temp[chat_id]['menu'] = 'html_file_manage'
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("🆕 নতুন ফাইল আপলোড", "🗑 বর্তমান ফাইল মুছুন")
            markup.add("🔙 ফিরে যান")
            bot.send_message(chat_id, f"📁 **HTML ফাইল স্ট্যাটাস:** {status_text}\n\nনতুন ফাইল অ্যাড করতে বা আগেরটি মুছতে নিচের অপশন ব্যবহার করুন:", reply_markup=markup, parse_mode="Markdown")

        elif text == "🆕 নতুন ফাইল আপলোড" and admin_temp.get(chat_id, {}).get('menu') == 'html_file_manage':
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("🔙 ফিরে যান")
            bot.send_message(chat_id, "📂 **নতুন HTML ফাইলটি আপলোড করুন:**", reply_markup=markup, parse_mode="Markdown")
            bot.register_next_step_handler(message, process_save_html_file)

        elif text == "🗑 বর্তমান ফাইল মুছুন" and admin_temp.get(chat_id, {}).get('menu') == 'html_file_manage':
            update_settings({"insta_html_file_id": None})
            bot.send_message(chat_id, "✅ বর্তমান HTML ফাইলটি মুছে ফেলা হয়েছে!", reply_markup=admin_panel_markup())
            admin_temp[chat_id]['menu'] = ''

        elif text == "📹 টিউটোরিয়াল সেট":
            admin_temp[chat_id] = {'menu': 'tutorial_set_menu'}
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            markup.add("🔗 2FA টিউটোরিয়াল", "🔗 Cookies টিউটোরিয়াল")
            markup.add("🔗 Niva টিউটোরিয়াল", "🔗 NS টিউটোরিয়াল")
            markup.add("🔙 ফিরে যান")
            bot.send_message(chat_id, "🎥 **কোন কাজের টিউটোরিয়াল লিংক সেট করবেন?**", reply_markup=markup, parse_mode="Markdown")

        elif text in ["🔗 2FA টিউটোরিয়াল", "🔗 Cookies টিউটোরিয়াল", "🔗 Niva টিউটোরিয়াল", "🔗 NS টিউটোরিয়াল"] and admin_temp.get(chat_id, {}).get('menu') == 'tutorial_set_menu':
            if text == "🔗 2FA টিউটোরিয়াল": key = "tutorial_insta_2fa"
            elif text == "🔗 Cookies টিউটোরিয়াল": key = "tutorial_insta_cookies"
            elif text == "🔗 Niva টিউটোরিয়াল": key = "tutorial_niva"
            elif text == "🔗 NS টিউটোরিয়াল": key = "tutorial_ns"
            
            bot.register_next_step_handler(
                bot.send_message(chat_id, f"🔗 {text} এর জন্য নতুন লিংকটি দিন (ভিডিও বা পোস্ট লিংক):", reply_markup=types.ReplyKeyboardRemove()), 
                lambda m: process_set_tutorial_link(m, key)
            )

        elif text == "⚙️ টাস্ক ম্যানেজমেন্ট":
            admin_temp[chat_id] = {'menu': 'task_mgmt'}
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            markup.add("📱 ইন্সটা টাস্ক", "💎 কয়েন টাস্ক")
            markup.add("📱 ফেসবুক টাস্ক", "🔙 ফিরে যান")
            bot.send_message(chat_id, "⚙️ টাস্ক ম্যানেজমেন্ট", reply_markup=markup)
            
        elif text == "📱 ইন্সটা টাস্ক":
             admin_temp[chat_id]['menu'] = 'insta_task_manage_type'
             markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
             markup.add("🔐 2FA", "🍪 Cookies")
             markup.add("🔙 ফিরে যান")
             bot.send_message(chat_id, "📱 **কোন টাস্কটি ম্যানেজ করবেন?**", reply_markup=markup, parse_mode="Markdown")

        elif text == "📧 জিমেইল টাস্ক":
             s = get_settings()
             status = "ON" if s.get("gmail_task_enabled", True) else "OFF"
             admin_temp[chat_id]['target_task'] = 'gmail'
             bot.send_message(chat_id, f"Gmail Task: {status}", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("চালু করুন", "বন্ধ করুন", "🔙 ফিরে যান"))

        elif text == "📱 ফেসবুক টাস্ক":
             s = get_settings()
             status = "ON" if s.get("fb_task_enabled", True) else "OFF"
             admin_temp[chat_id]['target_task'] = 'facebook'
             bot.send_message(chat_id, f"Facebook Task: {status}", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("চালু করুন", "বন্ধ করুন", "🔙 ফিরে যান"))

        elif text == "💎 কয়েন টাস্ক":
             admin_temp[chat_id]['target_task'] = 'coin'
             bot.send_message(chat_id, "কয়েন সিলেক্ট করুন:", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("Niva Coin", "NS Coin", "🔙 ফিরে যান"))

        elif text == "Niva Coin":
             if admin_temp.get(chat_id, {}).get('menu') == 'set_coin_price_menu':
                 bot.register_next_step_handler(bot.send_message(chat_id, "নতুন Niva Coin প্রাইস (প্রতি 1k - BDT):"), lambda m: process_set_specific_coin_price(m, "niva_price_per_1k"))
             else:
                 s = get_settings()
                 status = "ON" if s.get("niva_coin_enabled", True) else "OFF"
                 admin_temp[chat_id]['target_task'] = 'niva'
                 bot.send_message(chat_id, f"Niva Coin Task: {status}", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("চালু করুন", "বন্ধ করুন", "🔙 ফিরে যান"))

        elif text == "NS Coin":
             if admin_temp.get(chat_id, {}).get('menu') == 'set_coin_price_menu':
                 bot.register_next_step_handler(bot.send_message(chat_id, "নতুন NS Coin প্রাইস (প্রতি 1k - BDT):"), lambda m: process_set_specific_coin_price(m, "ns_price_per_1k"))
             else:
                 s = get_settings()
                 status = "ON" if s.get("ns_coin_enabled", True) else "OFF"
                 admin_temp[chat_id]['target_task'] = 'ns'
                 bot.send_message(chat_id, f"NS Coin Task: {status}", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("চালু করুন", "বন্ধ করুন", "🔙 ফিরে যান"))
        
        elif text == "📦 স্টক":
             bot.send_message(chat_id, f"📦 স্টক: {sold_gmails_col.count_documents({})}\n📝 পেন্ডিং: {requests_col.count_documents({'status': 'Submitted'})}")
        elif text == "🗑 স্টক ক্লিয়ার":
             clear_sold_gmails_db()
             bot.send_message(chat_id, "✅ স্টক ক্লিয়ার হয়েছে!")

        elif text == "📥 Add Hotmail":
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("🔙 ফিরে যান")
            msg = bot.send_message(chat_id, "📥 **Hotmail লিস্ট দিন:**\n(প্রতি লাইনে একটি করে `mail|pass|refresh_token|client_id`)", reply_markup=markup, parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_add_hotmail)

        elif text == "🔑 পাসওয়ার্ড সেট":
            admin_temp[chat_id] = {'menu': 'password_set_menu'}
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            markup.add("📱 Insta 2FA পাসওয়ার্ড", "🍪 Insta Cookies পাসওয়ার্ড")
            markup.add("📱 Facebook পাসওয়ার্ড", "🔙 ফিরে যান")
            bot.send_message(chat_id, "🔑 **কোন টাস্কের পাসওয়ার্ড সেট করবেন?**", reply_markup=markup, parse_mode="Markdown")

        elif text in ["📱 Insta 2FA পাসওয়ার্ড", "🍪 Insta Cookies পাসওয়ার্ড", "📱 Facebook পাসওয়ার্ড"] and admin_temp.get(chat_id, {}).get('menu') == 'password_set_menu':
            if text == "📱 Insta 2FA পাসওয়ার্ড":
                key = "fixed_insta_2fa_password"
            elif text == "🍪 Insta Cookies পাসওয়ার্ড":
                key = "fixed_insta_cookies_password"
            else:
                key = "fixed_fb_password"
            
            admin_temp[chat_id]['password_key'] = key
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("❌ রিমুভ (Random)", "🔙 ফিরে যান")
            bot.send_message(chat_id, f"🔑 {text} এর জন্য নতুন ফিক্সড পাসওয়ার্ড দিন:\n\n(আগের মতো Random পাসওয়ার্ড চাইলে '❌ রিমুভ (Random)' এ ক্লিক করুন)", reply_markup=markup)
            bot.register_next_step_handler(message, process_set_fixed_password)

        elif text == "💰 টাস্কের দাম সেট":
            admin_temp[chat_id] = {'menu': 'set_task_price_menu'}
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("📱 Instagram 2FA", "🍪 Insta Cookies")
            markup.add("📧 Gmail", "🔙 ফিরে যান")
            bot.send_message(chat_id, "টাস্ক সিলেক্ট করুন:", reply_markup=markup)
        
        elif text in ["📱 Instagram 2FA", "🍪 Insta Cookies", "📧 Gmail"]:
            menu = admin_temp.get(chat_id, {}).get('menu')
            if menu == 'set_task_price_menu':
                if text == "📱 Instagram 2FA": key = "task_price"
                elif text == "🍪 Insta Cookies": key = "insta_cookies_price"
                else: key = "gmail_task_price"
                
                bot.register_next_step_handler(bot.send_message(chat_id, f"নতুন {text} প্রাইস (BDT):"), lambda m: process_set_specific_coin_price(m, key))

        elif text == "💰 কয়েনের দাম সেট":
             admin_temp[chat_id] = {'menu': 'set_coin_price_menu'}
             bot.send_message(chat_id, "কয়েন সিলেক্ট করুন:", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("Niva Coin", "NS Coin", "🔙 ফিরে যান"))

        elif text in ["চালু করুন", "বন্ধ করুন"]:
            target = admin_temp.get(chat_id, {}).get('target_task')
            if target:
                val = (text == "চালু করুন")
                if target == 'instagram': update_settings({"instagram_task_enabled": val})
                elif target == 'insta_2fa': update_settings({"insta_2fa_enabled": val})
                elif target == 'insta_cookies': update_settings({"insta_cookies_enabled": val})
                elif target == 'gmail': update_settings({"gmail_task_enabled": val})
                elif target == 'facebook': update_settings({"fb_task_enabled": val})
                elif target == 'niva': update_settings({"niva_coin_enabled": val})
                elif target == 'ns': update_settings({"ns_coin_enabled": val})
                
                bot.send_message(chat_id, f"✅ {target.capitalize()} এখন {text}।", reply_markup=admin_panel_markup())

        elif text == "🔗 ইন্সটা লিংক সেট":
            bot.register_next_step_handler(bot.send_message(chat_id, "🔗 নতুন ইন্সটাগ্রাম পুশ URL দিন:"), process_set_insta_link)

        elif text == "📥 রিকুয়েস্ট ডাউনলোড":
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("📋 টাস্ক লগস", "🗑 হিস্ট্রি ক্লিয়ার")
            markup.add("🔙 ফিরে যান")
            bot.send_message(chat_id, "📂 **ডাউনলোড ডাটা:**", reply_markup=markup)
            admin_temp[chat_id]['menu'] = 'download_menu'

        elif text == "📋 টাস্ক লগস":
            reqs = get_pending_requests()
            sold_batches = get_all_sold_batches()
            active_sold_emails = set()
            if requests_col is not None:
                cursor = requests_col.find({"status": "Sold"}, {"account_data.email": 1})
                for doc in cursor:
                    email = doc.get('account_data', {}).get('email')
                    if email:
                        active_sold_emails.add(email.strip().lower())

            if not reqs and not sold_batches:
                bot.send_message(chat_id, "⚠️ কোনো ডাটা নেই।")
            else:
                gmail_rows = []
                insta_rows = []
                insta_cookies_rows = []
                fb_rows = []
                sold_rows = []
                for r in reqs:
                    acc = r.get("account_data", {})
                    if r.get("task_type") == "gmail":
                        gmail_rows.append({
                            "User ID": r.get("user_id"),
                            "Email": acc.get("email"),
                            "Password": acc.get("password"),
                            "First Name": acc.get("firstname", "N/A"),
                            "Time": time.strftime('%Y-%m-%d %H:%M', time.localtime(r.get("timestamp")))
                        })
                    elif r.get("task_type") == "instagram":
                         insta_rows.append({
                            "User ID": r.get("user_id"),
                            "Email": acc.get("email"),
                            "Password": acc.get("password"),
                            "2FA Key": acc.get("two_fa", "N/A"),
                        })
                    elif r.get("task_type") == "instagram_cookies":
                         insta_cookies_rows.append({
                            "User ID": r.get("user_id"),
                            "Email": acc.get("email"),
                            "Password": acc.get("password"),
                            "Cookies Data": acc.get("cookies", "N/A"),
                        })
                    elif r.get("task_type") == "facebook":
                         fb_rows.append({
                            "User ID": r.get("user_id"),
                            "Email": acc.get("email"),
                            "Hotmail Data": acc.get("hotmail_info", "N/A"),
                            "2FA Key": acc.get("two_fa", "N/A"),
                            "Cookies Data": acc.get("cookies", "N/A"),
                            "Time": time.strftime('%Y-%m-%d %H:%M', time.localtime(r.get("timestamp")))
                        })
                
                ordinals = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth"]
                for index, batch in enumerate(sold_batches):
                    b_id = batch.get('batch_id')
                    ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(batch.get('timestamp')))
                    batch_label = ordinals[index] if index < len(ordinals) else f"{index + 1}th"
                    for acc in batch.get('accounts', []):
                        email = acc.get('email')
                        if email and email.strip().lower() in active_sold_emails:
                            sold_rows.append({
                                "Batch ID": b_id,
                                "Upload Time": ts,
                                "Email": email,
                                "Password": acc.get('password'),
                                "Upload Batch": batch_label
                            })

                filename = "tasks.xlsx"
                with pd.ExcelWriter(filename) as writer:
                    if gmail_rows: pd.DataFrame(gmail_rows).to_excel(writer, sheet_name='Gmail Pending', index=False)
                    if insta_rows: pd.DataFrame(insta_rows).to_excel(writer, sheet_name='Instagram 2FA Pending', index=False)
                    if insta_cookies_rows: pd.DataFrame(insta_cookies_rows).to_excel(writer, sheet_name='Insta Cookies Pending', index=False)
                    if fb_rows: pd.DataFrame(fb_rows).to_excel(writer, sheet_name='Facebook Pending', index=False)
                    if sold_rows: pd.DataFrame(sold_rows).to_excel(writer, sheet_name='Sold Gmails', index=False)
                
                with open(filename, "rb") as f: bot.send_document(chat_id, f, caption="📋 ডাটা এক্সপোর্ট")
                os.remove(filename)

        elif text == "🗑 হিস্ট্রি ক্লিয়ার":
             markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
             markup.add("✅ হ্যাঁ", "❌ না")
             bot.send_message(chat_id, "⚠️ **সব লগ ডিলিট করবেন (Sold Gmails সহ)?**", reply_markup=markup, parse_mode="Markdown")
             admin_temp[chat_id]['menu'] = 'confirm_clear_history'

        elif text == "✅ হ্যাঁ":
            if admin_temp.get(chat_id, {}).get('menu') == 'confirm_clear_history':
                clear_requests_db()
                clear_submissions_db()
                clear_sold_gmails_db() 
                bot.send_message(chat_id, "✅ হিস্ট্রি এবং Sold লগ ক্লিয়ার হয়েছে!", reply_markup=admin_panel_markup())
                admin_temp[chat_id] = {}

        elif text == "❌ না":
            bot.send_message(chat_id, "❌ বাতিল করা হয়েছে।", reply_markup=admin_panel_markup())
            admin_temp[chat_id] = {}

        elif text == "📢 ঘোষণা দিন":
            msg = bot.send_message(chat_id, "📢 **ঘোষণা লিখুন:**", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_announcement_broadcast)
        
        elif text == "🏆 টপ ওয়ার্কার":
            send_top_workers(chat_id, 0)

        elif text == "জিমেইল বিক্রি":
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("🔙 ফিরে যান")
            msg = bot.send_message(chat_id, "📤 **জিমেইল বিক্রি:**\nলিস্ট (email password) অথবা XLSX ফাইল পাঠান।", reply_markup=markup, parse_mode="Markdown")
            bot.register_next_step_handler(message, process_sell_gmail_input)

        elif text == "🚩 রিপোর্ট":
            admin_temp[chat_id] = {'menu': 'report_select'}
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("📧 Gmail", "📱 Instagram")
            markup.add("📱 Facebook", "🔙 ফিরে যান")
            bot.send_message(chat_id, "🚩 **রিপোর্টের টাস্ক টাইপ সিলেক্ট করুন:**", reply_markup=markup, parse_mode="Markdown")

        elif text in ["📧 Gmail", "📱 Instagram", "📱 Facebook"] and admin_temp.get(chat_id, {}).get('menu') == 'report_select':
            if text == "📱 Instagram":
                admin_temp[chat_id]['menu'] = 'report_insta_type'
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
                markup.add("🔐 2FA", "🍪 Cookies")
                markup.add("🔙 ফিরে যান")
                bot.send_message(chat_id, "📱 **Instagram এর কোন কাজের রিপোর্ট দেবেন?**", reply_markup=markup, parse_mode="Markdown")
            elif text == "📱 Facebook":
                admin_temp[chat_id]['report_task_type'] = 'facebook'
                admin_temp[chat_id]['menu'] = 'report_action'
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
                markup.add("✅ রিপোর্ট এক্সেপ্ট করুন", "❌ রিপোর্ট রিজেক্ট করুন")
                markup.add("🔙 ফিরে যান")
                bot.send_message(chat_id, f"🚩 **{text} Report:** একশন সিলেক্ট করুন:", reply_markup=markup)
            else:
                admin_temp[chat_id]['report_task_type'] = 'gmail'
                admin_temp[chat_id]['menu'] = 'report_action'
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
                markup.add("✅ রিপোর্ট এক্সেপ্ট করুন", "❌ রিপোর্ট রিজেক্ট করুন")
                markup.add("🔙 ফিরে যান")
                bot.send_message(chat_id, f"🚩 **{text} Report:** একশন সিলেক্ট করুন:", reply_markup=markup)

        elif text in ["🔐 2FA", "🍪 Cookies"]:
            menu = admin_temp.get(chat_id, {}).get('menu')
            if menu == 'report_insta_type':
                admin_temp[chat_id]['report_task_type'] = 'instagram' if text == "🔐 2FA" else 'instagram_cookies'
                admin_temp[chat_id]['menu'] = 'report_action'
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
                markup.add("✅ রিপোর্ট এক্সেপ্ট করুন", "❌ রিপোর্ট রিজেক্ট করুন")
                markup.add("🔙 ফিরে যান")
                bot.send_message(chat_id, f"🚩 **Insta {text} Report:** একশন সিলেক্ট করুন:", reply_markup=markup)
            elif menu == 'insta_task_manage_type':
                s = get_settings()
                if text == "🔐 2FA":
                    status = "ON" if s.get("insta_2fa_enabled", True) else "OFF"
                    admin_temp[chat_id]['target_task'] = 'insta_2fa'
                else:
                    status = "ON" if s.get("insta_cookies_enabled", True) else "OFF"
                    admin_temp[chat_id]['target_task'] = 'insta_cookies'
                bot.send_message(chat_id, f"Insta {text} Task: {status}", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("চালু করুন", "বন্ধ করুন", "🔙 ফিরে যান"))

        elif text == "✅ রিপোর্ট এক্সেপ্ট করুন":
             if admin_temp.get(chat_id, {}).get('menu') == 'report_action':
                 task_type = admin_temp[chat_id].get('report_task_type')
                 bot.send_message(chat_id, f"📝 **Bulk Approve ({task_type}):** লিস্ট বা এক্সেল ফাইল দিন।")
                 bot.register_next_step_handler(message, process_report_accept)

        elif text == "❌ রিপোর্ট রিজেক্ট করুন":
             if admin_temp.get(chat_id, {}).get('menu') == 'report_action':
                 task_type = admin_temp[chat_id].get('report_task_type')
                 bot.send_message(chat_id, f"📝 **Bulk Reject ({task_type}):** লিস্ট বা এক্সেল ফাইল দিন।")
                 bot.register_next_step_handler(message, process_report_reject)

        elif text == "💰 ব্যালেন্স সেট":
            admin_temp[chat_id] = {'action': 'balance_manage'}
            bot.register_next_step_handler(bot.send_message(chat_id, "ইউজার আইডি দিন:"), process_admin_userid)

        elif text == "🚫 ব্যান / আনব্যান":
            admin_temp[chat_id] = {'action': 'ban_toggle'}
            bot.register_next_step_handler(bot.send_message(chat_id, "ইউজার আইডি দিন:"), process_admin_userid)

        elif text == "📊 মোট এমাউন্ট":
            pipeline = [{"$group": {"_id": None, "total_balance": {"$sum": "$balance"}, "total_withdrawn": {"$sum": "$total_withdrawn"}, "total_pending_withdraw": {"$sum": "$pending_withdraw"}}}]
            res = list(users_col.aggregate(pipeline))
            tb = res[0]['total_balance'] if res else 0
            tw = res[0]['total_withdrawn'] if res else 0
            tpw = res[0].get('total_pending_withdraw', 0) if res else 0
            bot.send_message(chat_id, f"💰 ইউজার ব্যালেন্স: {tb:.2f}\n📉 উইথড্র হয়েছে: {tw:.2f}\n⏳ পেন্ডিং উইথড্র: {tpw:.2f}")

        elif text == "📩 ইউজারকে SMS দিন":
            admin_temp[chat_id] = {'action': 'send_sms_id'}
            bot.register_next_step_handler(bot.send_message(chat_id, "ইউজার আইডি দিন:"), process_admin_userid)

        elif text == "👤 মেম্বার স্ট্যাটাস":
            admin_temp[chat_id] = {'action': 'info'}
            bot.register_next_step_handler(bot.send_message(chat_id, "ইউজার আইডি দিন:"), process_admin_userid)
            
        elif text == "💸 মিনিমাম পেমেন্ট সেট":
             markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
             markup.add("Bkash", "Rocket", "Cancel")
             bot.send_message(chat_id, "🔧 মেথড সিলেক্ট করুন:", reply_markup=markup)
             bot.register_next_step_handler(message, process_min_withdraw_method_select)

        elif text == "👥 মোট ইউজার": 
            cnt = get_all_users_count()
            bot.send_message(chat_id, f"ইউজার সংখ্যা: {cnt}")

        elif text == "📉 মিনিমাম কয়েন সেল":
            bot.send_message(chat_id, "📉 মিনিমাম কয়েন সেল লিমিট লিখুন:", reply_markup=types.ReplyKeyboardRemove())
            bot.register_next_step_handler(message, process_set_min_coin)

# ==============================
# টিউটোরিয়াল লিংক সেট ফাংশন
# ==============================
def process_set_tutorial_link(message, key):
    if message.text in ["❌ বাতিল", "🔙 ফিরে যান"]:
        bot.send_message(message.chat.id, "❌ বাতিল করা হয়েছে।", reply_markup=admin_panel_markup())
        return
    update_settings({key: message.text.strip()})
    bot.send_message(message.chat.id, f"✅ টিউটোরিয়াল লিংক সফলভাবে সেট করা হয়েছে!\nলিংক: {message.text.strip()}", reply_markup=admin_panel_markup())
    if message.chat.id in admin_temp:
        admin_temp[message.chat.id]['menu'] = ''

def process_set_fixed_password(message):
    chat_id = message.chat.id
    text = message.text.strip()
    if text == "🔙 ফিরে যান":
        bot.send_message(chat_id, "❌ বাতিল করা হয়েছে।", reply_markup=admin_panel_markup())
        return
    
    key = admin_temp.get(chat_id, {}).get('password_key')
    if not key:
        bot.send_message(chat_id, "⚠️ এরর। আবার চেষ্টা করুন।", reply_markup=admin_panel_markup())
        return
        
    if text == "❌ রিমুভ (Random)":
        update_settings({key: ""})
        bot.send_message(chat_id, "✅ ফিক্সড পাসওয়ার্ড রিমুভ করা হয়েছে! এখন থেকে Random পাসওয়ার্ড জেনারেট হবে।", reply_markup=admin_panel_markup())
    else:
        update_settings({key: text})
        bot.send_message(chat_id, f"✅ নতুন ফিক্সড পাসওয়ার্ড সেট করা হয়েছে:\n`{text}`", reply_markup=admin_panel_markup(), parse_mode="Markdown")

# ==============================
# 2FA ক’ড সৃষ্টি কৰিবলৈ সহায়ক
# ==============================
def process_insta_2fa_key_input(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    if text == "❌ বাতিল" or text == "🔙 ফিরে যান":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🔐 2FA Set")
        markup.add("🔙 ফিরে যান")
        bot.send_message(chat_id, "❌ বাতিল করা হয়েছে।", reply_markup=markup)
        if chat_id in active_tasks:
            del active_tasks[chat_id]
        return

    if chat_id not in active_tasks or active_tasks[chat_id]['type'] != 'instagram_2fa':
        bot.send_message(chat_id, "⚠️ সেশন টাইমআউট।", reply_markup=main_menu(chat_id))
        return

    try:
        clean_key = text.replace(" ", "")
        totp = pyotp.TOTP(clean_key)
        code = totp.now()
        
        active_tasks[chat_id]['data']['two_fa_key'] = text
        
        msg = f"`{code}`\n\nকোডটি কপি করুন। নিচে অ্যাকাউন্ট খোলা শেষ হলে বাটনে চাপ দিন।"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("✅ অ্যাকাউন্ট খোলা শেষ")
        bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
        
    except:
        msg = "⚠️ দয়া করে সঠিক Key দিন অথবা বাতিল করুন।"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("❌ বাতিল")
        bot.send_message(chat_id, msg, reply_markup=markup)
        bot.register_next_step_handler(message, process_insta_2fa_key_input)

def process_set_insta_link(message):
    new_url = message.text.strip()
    if new_url.startswith("http"):
        update_settings({"instagram_push_url": new_url})
        bot.send_message(message.chat.id, "✅ URL আপডেট হয়েছে!", reply_markup=admin_panel_markup())
    else:
        bot.send_message(message.chat.id, "❌ ইনভ্যালিড URL।", reply_markup=admin_panel_markup())

# ==============================
# ঘোষণা সম্প্ৰচাৰ
# ==============================
def process_announcement_broadcast(message):
    admin_id = message.chat.id
    if message.text == "🔙 ফিরে যান":
        bot.send_message(admin_id, "❌ বাতিল করা হয়েছে।", reply_markup=admin_panel_markup())
        return
    users = users_col.find({}, {"_id": 1})
    total = users_col.count_documents({})
    status_msg = bot.send_message(admin_id, f"⏳ **{total} জন ইউজারকে মেসেজ পাঠানো হচ্ছে...**", parse_mode="Markdown")
    
    def run_broadcast():
        success, blocked = 0, 0
        for user in users:
            uid = user["_id"]
            try:
                if message.content_type == 'text': bot.send_message(uid, message.text)
                elif message.content_type == 'photo': bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "")
                success += 1
            except: blocked += 1
            time.sleep(0.05)
        bot.edit_message_text(f"✅ **ব্রডকাস্ট সম্পন্ন**\n👥 পাঠানো হয়েছে: {success}\n🚫 ফেইলড: {blocked}", chat_id=admin_id, message_id=status_msg.message_id, parse_mode="Markdown")
    threading.Thread(target=run_broadcast, daemon=True).start()

# ==============================
# শীৰ্ষক কৰ্মীসকল
# ==============================
def send_top_workers(chat_id, page, message_id=None):
    if users_col is None: return
    limit = 10
    skip = page * limit
    users = list(users_col.find().sort([("balance", -1)]).skip(skip).limit(limit))
    if not users: return

    msg = f"🏆 <b>টপ ওয়ার্কার (পেজ {page+1})</b>\n\n"
    for i, u in enumerate(users):
        rank = skip + i + 1
        name = esc(f"@{u.get('username')}" if u.get('username') else u.get('name', 'Unknown'))
        msg += f"{rank}. {name} --- {u.get('balance', 0.0):.2f} BDT\n"
    
    markup = types.InlineKeyboardMarkup()
    btns = []
    if page > 0: btns.append(types.InlineKeyboardButton("◀️ আগে", callback_data=f"top_page_{page-1}"))
    if users_col.count_documents({}) > skip + limit: btns.append(types.InlineKeyboardButton("পরে ▶️", callback_data=f"top_page_{page+1}"))
    markup.row(*btns)

    if message_id: bot.edit_message_text(msg, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode="HTML")
    else: bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="HTML")

# ==============================
# জিমেইল ইনপুট
# ==============================
def process_sell_gmail_input(message):
    chat_id = message.chat.id
    if message.text == "🔙 ফিরে যান":
        bot.send_message(chat_id, "🔙 মেইন মেনু", reply_markup=admin_panel_markup())
        return

    accounts = []
    if message.content_type == 'document':
        try:
            file_info = bot.get_file(message.document.file_id)
            with open("temp_sell.xlsx", 'wb') as f: f.write(bot.download_file(file_info.file_path))
            df = pd.read_excel("temp_sell.xlsx", header=None)
            for i, r in df.iterrows():
                if not pd.isna(r[0]) and len(r) > 1 and not pd.isna(r[1]):
                    accounts.append({"email": str(r[0]).strip(), "password": str(r[1]).strip()})
            os.remove("temp_sell.xlsx")
        except: pass
    elif message.content_type == 'text':
        for l in message.text.split('\n'):
            parts = l.split()
            if len(parts) >= 2: accounts.append({"email": parts[0].strip(), "password": parts[1].strip()})
    
    if accounts:
        log_sold_gmails(accounts)
        count_updated = 0
        for acc in accounts:
            res = requests_col.update_many({"account_data.email": {"$regex": f"^{re.escape(acc['email'])}$", "$options": "i"}, "status": "Submitted"}, {"$set": {"status": "Sold"}})
            count_updated += res.modified_count
        bot.send_message(chat_id, f"✅ {len(accounts)} টি Sold সেভ হয়েছে। {count_updated} টি টাস্ক আপডেট হয়েছে।", reply_markup=admin_panel_markup())
    else:
        bot.send_message(chat_id, "⚠️ কোনো ভ্যালিড ডাটা নেই।", reply_markup=admin_panel_markup())

# ==============================
# মুদ্ৰাৰ সহায়ক ফাংচন
# ==============================
def confirm_coin_amount_and_instruct(message, amount):
    user_id = message.chat.id
    settings = get_settings()
    if amount < settings.get("min_coin_sell", 1000):
        bot.send_message(user_id, f"⚠️ মিনিমাম {settings.get('min_coin_sell')} কয়েন লাগবে।")
        return
    coin_task_temp[user_id] = {'amount': amount, 'coin': coin_task_temp.get(user_id, {}).get('coin', 'Coin')}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("➡️ Done Next", "🔙 ফিরে যান")
    bot.send_message(user_id, f"📝 `kamrolh1` এ {coin_task_temp[user_id]['coin']} সেন্ড করুন। তারপর Done Next এ ক্লিক করুন।", reply_markup=markup, parse_mode="Markdown")
    bot.register_next_step_handler(message, process_coin_done_next)

def process_coin_amount(message):
    try: confirm_coin_amount_and_instruct(message, int(message.text))
    except: bot.send_message(message.chat.id, "❌ ভুল পরিমাণ।")

def process_coin_done_next(message):
    if message.text == "➡️ Done Next":
        bot.register_next_step_handler(bot.send_message(message.chat.id, "📸 স্ক্রিনশট আপলোড করুন", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("❌ ট্রানজেকশন বাতিল")), process_coin_screenshot)
    else: bot.send_message(message.chat.id, "🔙 বাতিল করা হয়েছে।", reply_markup=main_menu(message.chat.id))

def process_coin_screenshot(message):
    user_id = message.chat.id
    if message.content_type == 'photo' and user_id in coin_task_temp:
        coin_task_temp[user_id]['photo_id'] = message.photo[-1].file_id
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add("Bkash", "Rocket")
        markup.add("❌ বাতিল")
        bot.send_message(user_id, "কোথায় পেমেন্ট নিতে চান? (Bkash বা Rocket)", reply_markup=markup)
        bot.register_next_step_handler(message, process_coin_payment_method)
    else: 
        bot.send_message(user_id, "❌ বাতিল করা হয়েছে বা সঠিক ছবি দেওয়া হয়নি।", reply_markup=main_menu(user_id))

def process_coin_payment_method(message):
    user_id = message.chat.id
    text = message.text
    if text in ["❌ বাতিল", "🔙 ফিরে যান"]:
        bot.send_message(user_id, "❌ বাতিল করা হয়েছে।", reply_markup=main_menu(user_id))
        if user_id in coin_task_temp: del coin_task_temp[user_id]
        return
    
    if text in ["Bkash", "Rocket"]:
        if user_id in coin_task_temp:
            coin_task_temp[user_id]['method'] = text
        bot.send_message(user_id, f"আপনার {text} নাম্বার দিন:", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(message, process_coin_payment_number)
    else:
        bot.send_message(user_id, "দয়া করে সঠিক মাধ্যম নির্বাচন করুন (Bkash/Rocket)।")
        bot.register_next_step_handler(message, process_coin_payment_method)

def process_coin_payment_number(message):
    user_id = message.chat.id
    text = message.text
    if text in ["❌ বাতিল", "🔙 ফিরে যান"]:
        bot.send_message(user_id, "❌ বাতিল করা হয়েছে।", reply_markup=main_menu(user_id))
        if user_id in coin_task_temp: del coin_task_temp[user_id]
        return
    
    if user_id in coin_task_temp:
        task_info = coin_task_temp.pop(user_id)
        number = text
        method = task_info.get('method', 'Unknown')
        coin_type = task_info.get('coin', 'Coin')
        amount = task_info.get('amount', 0)
        photo_id = task_info.get('photo_id')
        
        settings = get_settings()
        rate = settings.get("niva_price_per_1k" if coin_type == "Niva" else "ns_price_per_1k", 0.04)
        bdt = (amount / 1000) * rate * EXCHANGE_RATE
        
        bot.send_message(user_id, "✅ জমা দেওয়া হয়েছে। এডমিন চেক করে সরাসরি পেমেন্ট করে দিবে।", reply_markup=main_menu(user_id))
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ পেমেন্ট করেছি (Approve)", callback_data=f"coin_app_{user_id}"), 
                   types.InlineKeyboardButton("❌ রিজেক্ট", callback_data=f"coin_rej_{user_id}"))
        markup.add(types.InlineKeyboardButton("📋 Copy Number", callback_data=f"w_copy_{number}"))
        
        caption = (
            f"🪙 **Coin Sell Request**\n"
            f"👤 User: `{user_id}`\n"
            f"💰 {coin_type}: {amount}\n"
            f"💵 Payable: {bdt:.2f} BDT\n"
            f"💳 Method: {method}\n"
            f"📝 Number: `{number}`"
        )
        try:
            bot.send_photo(COIN_TASK_GROUP_ID, photo_id, caption=caption, parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            print(e)
            bot.send_message(user_id, "⚠️ এডমিনকে ছবি পাঠাতে সমস্যা হচ্ছে।", reply_markup=main_menu(user_id))

# ==============================
# এডমিনৰ সহায়ক ফাংচন (UPDATE - BUG FIXES)
# ==============================
def process_admin_userid(message):
    target_id = message.text.strip()
    user = get_user(target_id)
    if not user:
        user = users_col.find_one({"username": {"$regex": f"^{re.escape(target_id.lstrip('@'))}$", "$options": "i"}})
        if user: target_id = user["_id"]
    if not user:
        bot.send_message(message.chat.id, "❌ ইউজার পাওয়া যায়নি।")
        return
    
    admin_temp[message.chat.id]['target_id'] = target_id
    action = admin_temp[message.chat.id].get('action')
    
    if action == 'info': 
        referred_users_income = 0.0
        if users_col is not None:
            try:
                pipeline = [
                    {"$match": {"referred_by": str(target_id)}},
                    {"$group": {
                        "_id": None,
                        "tot_bal": {"$sum": "$balance"},
                        "tot_with": {"$sum": "$total_withdrawn"},
                        "tot_pend": {"$sum": "$pending_withdraw"}
                    }}
                ]
                res = list(users_col.aggregate(pipeline))
                if res:
                    referred_users_income = res[0].get("tot_bal", 0) + res[0].get("tot_with", 0) + res[0].get("tot_pend", 0)
            except Exception as e:
                print(f"Team Income Error (Admin Info): {e}")

        total_self_income = user.get('balance', 0.0) + user.get('total_withdrawn', 0.0) + user.get('pending_withdraw', 0.0)

        # BUG FIX: Change Markdown to HTML to avoid parsing error with _ or *
        info_msg = (
            f"👤 <b>ইউজার ইনফরমেশন</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>নাম:</b> {esc(user.get('name', 'Unknown'))}\n"
            f"<b>ইউজারনেম:</b> @{esc(user.get('username', 'N/A'))}\n"
            f"<b>আইডি:</b> <code>{target_id}</code>\n\n"
            f"💰 <b>ব্যালেন্স স্ট্যাটাস:</b>\n"
            f"• মেইন ব্যালেন্স: {user.get('balance', 0.0):.2f} BDT\n"
            f"• মোট উইথড্র: {user.get('total_withdrawn', 0.0):.2f} BDT\n"
            f"• পেন্ডিং উইথড্র: {user.get('pending_withdraw', 0.0):.2f} BDT\n"
            f"• সর্বমোট নিজস্ব ইনকাম: {total_self_income:.2f} BDT\n\n"
            f"👥 <b>রেফারেল স্ট্যাটাস:</b>\n"
            f"• মোট রেফার: {user.get('referral_count', 0)} জন\n"
            f"• বর্তমান রেফার ব্যালেন্স: {user.get('referral_balance', 0.0):.2f} BDT\n"
            f"• মোট রেফার ইনকাম: {user.get('total_referral_earnings', 0.0):.2f} BDT\n"
            f"• টিমের (রেফারকৃতদের) মোট ইনকাম: {referred_users_income:.2f} BDT\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        try:
            bot.send_message(message.chat.id, info_msg, parse_mode="HTML", reply_markup=admin_panel_markup())
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ মেসেজ পাঠাতে সমস্যা হয়েছে: {e}", reply_markup=admin_panel_markup())
        
    elif action == 'ban_toggle':
        new_s = not user.get('banned', False)
        update_user(target_id, {"banned": new_s})
        bot.send_message(message.chat.id, f"ইউজার {'ব্যান' if new_s else 'আনব্যান'} করা হয়েছে", reply_markup=admin_panel_markup())
        
    elif action == 'balance_manage':
        bot.register_next_step_handler(bot.send_message(message.chat.id, "অ্যাকশন (+/- Amount):"), process_admin_amount)
        
    elif action == 'send_sms_id':
        admin_temp[message.chat.id]['sms_target'] = target_id
        bot.register_next_step_handler(bot.send_message(message.chat.id, "📝 ইউজারকে যে মেসেজটি দিতে চান তা লিখুন:"), process_admin_send_sms)

# SMS পাঠানোর জন্য নতুন হেল্পার ফাংশন
def process_admin_send_sms(message):
    target_id = admin_temp[message.chat.id].get('sms_target')
    text = message.text
    if text == "🔙 ফিরে যান" or text == "❌ বাতিল":
        bot.send_message(message.chat.id, "❌ বাতিল করা হয়েছে।", reply_markup=admin_panel_markup())
        return
    try:
        bot.send_message(target_id, f"📩 <b>অ্যাডমিন মেসেজ:</b>\n\n{text}", parse_mode="HTML")
        bot.send_message(message.chat.id, "✅ মেসেজ সফলভাবে পাঠানো হয়েছে!", reply_markup=admin_panel_markup())
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ মেসেজ পাঠানো যায়নি। কারণ: {e}", reply_markup=admin_panel_markup())

def process_admin_amount(message):
    try:
        val = float(message.text)
        users_col.update_one({"_id": admin_temp[message.chat.id]['target_id']}, {"$inc": {"balance": val}})
        bot.send_message(message.chat.id, "✅ সম্পন্ন হয়েছে!", reply_markup=admin_panel_markup())
    except: bot.send_message(message.chat.id, "❌ এরর।")

def process_set_specific_coin_price(message, key):
    try:
        bdt_val = float(message.text)
        usd_val = bdt_val / EXCHANGE_RATE 
        update_settings({key: usd_val})
        bot.send_message(message.chat.id, f"✅ সেট হয়েছে: {bdt_val} BDT", reply_markup=admin_panel_markup())
    except: bot.send_message(message.chat.id, "❌ এরর।")

def process_set_min_coin(message):
    try:
        l = int(message.text)
        update_settings({"min_coin_sell": l})
        bot.send_message(message.chat.id, f"✅ সেট হয়েছে: {l}", reply_markup=admin_panel_markup())
    except: bot.send_message(message.chat.id, "❌ এরর।")

def process_min_withdraw_method_select(message):
    if message.text == "Cancel": return
    admin_temp[message.chat.id]['method'] = message.text
    bot.register_next_step_handler(bot.send_message(message.chat.id, "পরিমাণ লিখুন:", reply_markup=types.ReplyKeyboardRemove()), process_min_withdraw_value)

def process_min_withdraw_value(message):
    try:
        amt = float(message.text)
        update_settings({f"min_{admin_temp[message.chat.id]['method'].lower()}": amt})
        bot.send_message(message.chat.id, "✅ সম্পন্ন হয়েছে!", reply_markup=admin_panel_markup())
    except: bot.send_message(message.chat.id, "❌ এরর।")

def process_report_accept(message):
    items = []
    if message.content_type == 'document':
        try:
            file_info = bot.get_file(message.document.file_id)
            with open("rep.xlsx", 'wb') as f: f.write(bot.download_file(file_info.file_path))
            df = pd.read_excel("rep.xlsx", header=None)
            for i, r in df.iterrows():
                if not pd.isna(r[0]): items.append((str(r[0]).strip(), float(r[1]) if len(r)>1 and not pd.isna(r[1]) else None))
            os.remove("rep.xlsx")
        except: pass
    elif message.content_type == 'text':
        for l in message.text.split('\n'):
            parts = l.split()
            if parts: items.append((parts[0].strip(), float(parts[1]) if len(parts)>1 else None))
    
    if not items: return
    succ, fail = 0, 0
    
    settings = get_settings()
    task_type = admin_temp[message.chat.id].get('report_task_type', 'instagram')
    
    if task_type == 'gmail':
        s_def = settings.get("gmail_task_price", 0.12)
    elif task_type == 'instagram_cookies':
        s_def = settings.get("insta_cookies_price", 0.0280)
    elif task_type == 'facebook':
        s_def = settings.get("task_price", 0.70)
    else:
        s_def = settings.get("task_price", 0.70)

    for login, price in items:
        req = requests_col.find_one({
            "$or": [{"account_data.email": login}, {"account_data.login": login}], 
            "status": {"$in": ["Submitted", "Sold"]},
            "task_type": task_type
        })
        
        if req:
            bdt = (price if price else s_def) * EXCHANGE_RATE
            users_col.update_one({"_id": str(req['user_id'])}, {"$inc": {"balance": bdt}})
            requests_col.update_one({"_id": req["_id"]}, {"$set": {"status": "Approved"}})
            try:
                if task_type == 'instagram':
                    bot.send_message(req['user_id'], f"{login}🟢 (2FA) +{bdt:.2f} BDT")
                elif task_type == 'instagram_cookies':
                    bot.send_message(req['user_id'], f"{login}🟢 (Cookies) +{bdt:.2f} BDT")
                else:
                    bot.send_message(req['user_id'], f"✅ টাস্ক এপ্রুভ হয়েছে ({task_type}): +{bdt:.2f} BDT. Task ID: {req.get('task_id')}")
            except: pass
            succ += 1
        else: fail += 1
    bot.send_message(message.chat.id, f"✅ এপ্রুভ হয়েছে: {succ}\n❌ ফেইলড: {fail}", reply_markup=admin_panel_markup())

def process_report_reject(message):
    items = []
    if message.content_type == 'document':
        try:
            file_info = bot.get_file(message.document.file_id)
            with open("rej.xlsx", 'wb') as f: f.write(bot.download_file(file_info.file_path))
            df = pd.read_excel("rej.xlsx", header=None)
            for i, r in df.iterrows():
                if not pd.isna(r[0]): items.append(str(r[0]).strip())
            os.remove("rej.xlsx")
        except: pass
    elif message.content_type == 'text':
        for l in message.text.split('\n'):
            if l.strip(): items.append(l.strip())
    
    task_type = admin_temp[message.chat.id].get('report_task_type', 'instagram')
    succ, fail = 0, 0
    for login in items:
        req = requests_col.find_one({
            "$or": [{"account_data.email": login}, {"account_data.login": login}], 
            "status": {"$in": ["Submitted", "Sold"]},
            "task_type": task_type
        })
        if req:
            requests_col.update_one({"_id": req["_id"]}, {"$set": {"status": "Rejected"}})
            try:
                if task_type == 'instagram':
                    bot.send_message(req['user_id'], f"{login}🔴 (2FA)")
                elif task_type == 'instagram_cookies':
                    bot.send_message(req['user_id'], f"{login}🔴 (Cookies)")
                else:
                    bot.send_message(req['user_id'], f"❌ রিজেক্টেড: {login}. কারণ জানতে /why_rejected চেক করুন।")
            except: pass
            succ += 1
        else: fail += 1
    bot.send_message(message.chat.id, f"✅ রিজেক্টেড: {succ}\n❌ ফেইলড: {fail}", reply_markup=admin_panel_markup())

# ==============================
# কলবেক হেণ্ডলাৰ
# ==============================
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "ref_withdraw_start":
        user = get_user(call.message.chat.id)
        if not user: return
        
        ref_count = user.get('referral_count', 0)
        if ref_count < 20:
            bot.answer_callback_query(call.id, f"❌ উইথড্র করতে আরও {20 - ref_count} টি রেফার প্রয়োজন!", show_alert=True)
            return
            
        ref_bal = user.get('referral_balance', 0.0)
        if ref_bal < 100:
            bot.answer_callback_query(call.id, "❌ মিনিমাম ১০০ টাকা রেফার ব্যালেন্স হলে উইথড্র করতে পারবেন!", show_alert=True)
            return

        withdraw_temp[call.message.chat.id] = {'currency': 'BDT', 'is_referral': True}
        
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        markup.add("Bkash", "Rocket", "❌ বাতিল")
        
        msg = bot.send_message(call.message.chat.id, f"📤 **রেফার টাকা তোলার মাধ্যম সিলেক্ট করুন:**\n\n💰 আপনার রেফার ব্যালেন্স: {ref_bal:.2f} BDT", reply_markup=markup, parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_bdt_provider)

    elif call.data == "check_ref_pending":
        user = get_user(call.message.chat.id)
        if not user or user.get('referral_withdraw_pending', 0) <= 0:
            bot.answer_callback_query(call.id, "আপনার কোনো পেন্ডিং রেফার উইথড্র নেই।", show_alert=True)
            return
        
        pipeline = [
            {"$match": {"referred_by": str(call.message.chat.id)}},
            {"$group": {
                "_id": None,
                "tot_bal": {"$sum": "$balance"},
                "tot_with": {"$sum": "$total_withdrawn"},
                "tot_pend": {"$sum": "$pending_withdraw"}
            }}
        ]
        res = list(users_col.aggregate(pipeline))
        team_inc = 0
        if res:
            team_inc = res[0].get("tot_bal", 0) + res[0].get("tot_with", 0) + res[0].get("tot_pend", 0)
            
        last_w = user.get("last_ref_withdraw", {})
        amt = last_w.get("amount", user.get("referral_withdraw_pending"))
        acc = last_w.get("account", "অজানা")
        
        remaining = max(0, 5000 - team_inc)
        
        msg = (
            f"⏳ **পেন্ডিং রেফার উইথড্র স্ট্যাটাস**\n\n"
            f"💰 **পরিমাণ:** {amt:.2f} BDT\n"
            f"📝 **নাম্বার:** `{acc}`\n\n"
            f"⚠️ **শর্ত:** আপনি যে রিয়েল অ্যাক্টিভ মেম্বারদের রেফার করেছেন, তা প্রমাণ করতে হবে। "
            f"যাদের রেফার করেছেন, তাদের সবার মিলে মোট ৫০০০ টাকা ইনকাম হলে আপনি আপনার এই টাকা পেয়ে যাবেন।\n\n"
            f"আপনার উইথড্র কমপ্লিট হতে রেফারকারীদের ইনকাম আরও **{remaining:.2f} BDT** করতে হবে "
            f"(ইতিমধ্যে তারা {team_inc:.2f} BDT করেছে)। এরপর আপনার নাম্বারে টাকা দেওয়া হবে।\n\n"
            f"আমাদের নিয়ম মানার জন্য ধন্যবাদ!"
        )
        bot.send_message(call.message.chat.id, msg, parse_mode="Markdown")
        bot.answer_callback_query(call.id)

    elif call.data == "check_join_start":
        try:
            status = bot.get_chat_member(TARGET_CHANNEL_ID, call.message.chat.id).status
            if status in ['creator', 'administrator', 'member']:
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                
                user = get_user(call.message.chat.id)
                if user and "join_channel" not in user.get("completed_tasks", []):
                    rew = get_settings().get("join_task_price", 0.01) * EXCHANGE_RATE
                    users_col.update_one(
                        {"_id": str(call.message.chat.id)}, 
                        {"$inc": {"balance": rew}, "$push": {"completed_tasks": "join_channel"}}
                    )
                    try: bot.send_message(call.message.chat.id, f"🎉 জয়েনিং বোনাস: +{rew:.2f} BDT যুক্ত হয়েছে!")
                    except: pass
                    
                bot.send_message(call.message.chat.id, f"😊 স্বাগতম! আপনি সফলভাবে জয়েন করেছেন।", reply_markup=main_menu(call.message.chat.id))
            else:
                bot.answer_callback_query(call.id, "❌ আপনি এখনো চ্যানেলে জয়েন করেননি!", show_alert=True)
        except Exception as e:
            bot.answer_callback_query(call.id, "⚠️ সমস্যা হচ্ছে, পরে চেষ্টা করুন。", show_alert=True)

    elif call.data == "check_join_task":
        try:
            status = bot.get_chat_member(TARGET_CHANNEL_ID, call.message.chat.id).status
            if status in ['creator', 'administrator', 'member']:
                user = get_user(call.message.chat.id)
                
                if "join_channel" in user.get("completed_tasks", []):
                    bot.answer_callback_query(call.id, "❌ আপনি আগেই বোনাস নিয়েছেন!", show_alert=True)
                    try: bot.delete_message(call.message.chat.id, call.message.message_id)
                    except: pass
                    return
                
                rew = get_settings().get("join_task_price", 0.01) * EXCHANGE_RATE
                users_col.update_one({"_id": str(call.message.chat.id)}, {"$inc": {"balance": rew}, "$push": {"completed_tasks": "join_channel"}})
                bot.edit_message_text(f"🎉 সফল: +{rew:.2f} BDT যুক্ত হয়েছে!", chat_id=call.message.chat.id, message_id=call.message.message_id)
            else: 
                bot.answer_callback_query(call.id, "❌ আপনি এখনো জয়েন করেননি!", show_alert=True)
        except: pass
        
    elif call.data.startswith("top_page_"): send_top_workers(call.message.chat.id, int(call.data.split("_")[2]), call.message.message_id)
    elif call.data == "how_niva":
        link = get_settings().get("tutorial_niva", "https://t.me/Gmailsellincom/337")
        send_tutorial_video(call.message.chat.id, link)
    elif call.data == "how_ns":
        link = get_settings().get("tutorial_ns", "https://t.me/Gmailsellincom/339")
        send_tutorial_video(call.message.chat.id, link)
    elif call.data == "how_insta_2fa":
        link = get_settings().get("tutorial_insta_2fa", "https://t.me/Gmailsellincom/385")
        send_tutorial_video(call.message.chat.id, link)
    elif call.data == "how_insta_cookies":
        link = get_settings().get("tutorial_insta_cookies", "https://t.me/Gmailsellincom/385")
        send_tutorial_video(call.message.chat.id, link)
        
    elif call.data.startswith("copy_raw_"):
        uid = int(call.data.replace("copy_raw_", ""))
        if uid in active_tasks and 'cookies_data' in active_tasks[uid]['data']:
            data = active_tasks[uid]['data']['cookies_data']
            bot.send_message(call.message.chat.id, f"<code>{data}</code>", parse_mode="HTML")
            bot.answer_callback_query(call.id, "নিচের ডেটা পাঠানো হয়েছে, ট্যাপ করে কপি করুন!")
        else:
            bot.answer_callback_query(call.id, "⚠️ সেশন এক্সপায়ার হয়েছে।", show_alert=True)

    elif call.data == "insta_cookies_next":
        settings = get_settings()
        file_id = settings.get("insta_html_file_id")
        
        if file_id:
            try:
                bot.send_document(call.message.chat.id, file_id, caption="📄 এই ফাইলটি ওপেন করে ডেটা সাবমিট করুন।")
            except Exception as e:
                bot.send_message(call.message.chat.id, "⚠️ ফাইল পাঠাতে সমস্যা হচ্ছে। অ্যাডমিনকে জানান।")
                
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("✅ কাজ সম্পন্ন (Done)", "❌ বাতিল")
            bot.send_message(call.message.chat.id, "কাজ শেষ হলে নিচের বাটনে চাপ দিন:", reply_markup=markup)
            bot.register_next_step_handler(call.message, finalize_cookies_task)
        else:
            bot.answer_callback_query(call.id, "⚠️ ফাইল সেট করা নেই। অ্যাডমিনকে জানান।", show_alert=True)

    elif call.data.startswith("coin_"):
        p = call.data.split("_")
        action = p[1]
        user_id_str = p[2]
        
        if action == "app":
            try:
                bot.edit_message_caption(f"{call.message.caption}\n\n✅ পেমেন্ট সম্পন্ন (APPROVED)", chat_id=call.message.chat.id, message_id=call.message.message_id)
            except: pass
            try: 
                bot.send_message(user_id_str, "✅ **Withdraw Successful!**\nআপনার কয়েন বিক্রির পেমেন্ট সম্পন্ন হয়েছে।", parse_mode="Markdown")
            except Exception as e: 
                print(f"Coin Notif Error: {e}")
        elif action == "rej":
            bot.send_message(user_id_str, "❌ **কয়েন সেল রিজেক্ট হয়েছে।** ভেরিফিকেশন ফেইলড বা ভুল তথ্য। সাপোর্টে যোগাযোগ করুন: @Gmailadminbdbot", parse_mode="Markdown")
            try:
                bot.edit_message_caption(f"{call.message.caption}\n\n❌ রিজেক্টেড (REJECTED)", chat_id=call.message.chat.id, message_id=call.message.message_id)
            except: pass
    
    elif call.data.startswith("w_"):
        p = call.data.split("_")
        
        if p[1] == "copy":
            number = call.data.replace("w_copy_", "")
            bot.send_message(call.message.chat.id, f"<code>{number}</code>", parse_mode="HTML")
            bot.answer_callback_query(call.id, "নম্বরটি নিচে পাঠানো হয়েছে, ট্যাপ করে কপি করুন!")
            return
            
        user_id_str = str(p[2])
        amount = float(p[3])
        action = p[1]
        w_type = p[4] if len(p) > 4 else "main"
        
        provider = "Unknown"
        masked_number = "******"
        if call.message and call.message.text:
            try:
                lines = call.message.text.split('\n')
                for line in lines:
                    if '💳' in line:
                        provider = line.replace('💳', '').strip()
                    elif '📝' in line:
                        raw_num = line.replace('📝', '').strip()
                        if len(raw_num) > 4:
                            masked_number = f"{raw_num[:3]}******{raw_num[-2:]}"
                        else:
                            masked_number = raw_num
            except Exception:
                pass
        
        user = get_user(user_id_str)
        if user:
            if w_type == "ref":
                pending_w = user.get("referral_withdraw_pending", 0.0)
                deduct_pending = min(pending_w, amount) 
                
                if action == "app":
                    inc_data = {"referral_withdraw_pending": -deduct_pending}
                    if deduct_pending > 0:
                        inc_data["total_referral_withdrawn"] = deduct_pending
                    
                    users_col.update_one({"_id": user_id_str}, {"$inc": inc_data, "$set": {"ref_5k_notified": False}})
                    
                    success_msg = (
                        f"🚀 Reffer Payment Sent Successfully\n"
                        f"Amount: ৳{amount}\n"
                        f"Method: {provider} ({masked_number})"
                    )
                    bot.send_message(user_id_str, success_msg)
                    bot.edit_message_text(f"✅ অনুমোদিত (APPROVED)", chat_id=call.message.chat.id, message_id=call.message.message_id)
                else: 
                    inc_data = {"referral_balance": amount, "referral_withdraw_pending": -deduct_pending}
                    users_col.update_one({"_id": user_id_str}, {"$inc": inc_data, "$set": {"ref_5k_notified": False}})
                    bot.send_message(user_id_str, "❌ রেফার পেমেন্ট রিজেক্ট হয়েছে। ব্যালেন্স ফেরত দেওয়া হয়েছে।")
                    bot.edit_message_text(f"❌ বাতিল (REJECTED)", chat_id=call.message.chat.id, message_id=call.message.message_id)
            else:
                pending_w = user.get("pending_withdraw", 0.0)
                deduct_pending = min(pending_w, amount) 
                
                if action == "app":
                    inc_data = {"pending_withdraw": -deduct_pending}
                    if deduct_pending > 0:
                        inc_data["total_withdrawn"] = deduct_pending
                    
                    users_col.update_one({"_id": user_id_str}, {"$inc": inc_data})
                    
                    success_msg = (
                        f"🚀 Payment Sent Successfully\n"
                        f"Amount: ৳{amount}\n"
                        f"Method: {provider} ({masked_number})"
                    )
                    bot.send_message(user_id_str, success_msg)
                    bot.edit_message_text(f"✅ অনুমোদিত (APPROVED)", chat_id=call.message.chat.id, message_id=call.message.message_id)
                else: 
                    inc_data = {"balance": amount, "pending_withdraw": -deduct_pending}
                    reverse_withdrawn = amount - deduct_pending
                    if reverse_withdrawn > 0:
                        inc_data["total_withdrawn"] = -reverse_withdrawn
                        
                    users_col.update_one({"_id": user_id_str}, {"$inc": inc_data})
                    bot.send_message(user_id_str, "❌ পেমেন্ট রিজেক্ট হয়েছে। ব্যালেন্স ফেরত দেওয়া হয়েছে।")
                    bot.edit_message_text(f"❌ বাতিল (REJECTED)", chat_id=call.message.chat.id, message_id=call.message.message_id)

threading.Thread(target=auto_cancel_monitor, daemon=True).start()
threading.Thread(target=auto_ref_milestone_monitor, daemon=True).start()
print("🤖 বট চালু হচ্ছে...")
telebot.apihelper.READ_TIMEOUT = 60
bot.infinity_polling(timeout=20)