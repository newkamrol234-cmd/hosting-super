from flask import Flask, request, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
from bson.errors import InvalidId
import urllib.request
import urllib.error
import json
import time
import random
import ssl
import os
import subprocess
import sys
import atexit
import signal

app = Flask(__name__)

# ==========================================
# MONGODB CONNECTION
# ==========================================
MONGO_URI = "mongodb+srv://kamrolha725_db_user:aass1122@cluster0.wkybonq.mongodb.net/?appName=Cluster0"
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["hostbotsuper_db"]
    users_col = db["users"]
    bots_col = db["bots"]
    # Test connection
    client.server_info()
    print("✅ MongoDB Connected Successfully!")
except Exception as e:
    print("❌ MongoDB Connection Failed:", e)

def serialize_doc(doc):
    if doc and '_id' in doc:
        doc['_id'] = str(doc['_id'])
    return doc

# ==========================================
# BOT RUNNER CORE
# ==========================================
BOTS_DIR = "running_bots"
os.makedirs(BOTS_DIR, exist_ok=True)
active_processes = {}

def start_bot(bot_id, code):
    """Starts the bot in a separate background process."""
    stop_bot(bot_id)  # Stop any existing instance first completely
    time.sleep(1.5) # Give OS a moment to release ports/files
    
    # If code is somehow empty, try to fetch it from DB safely
    if not code or not code.strip():
        bot = bots_col.find_one({"_id": ObjectId(bot_id)})
        if bot and bot.get('code'):
            code = bot['code']
            
    script_path = os.path.join(BOTS_DIR, f"{bot_id}.py")
    log_path = os.path.join(BOTS_DIR, f"{bot_id}.log")
    pid_path = os.path.join(BOTS_DIR, f"{bot_id}.pid")
    
    # Write the user code to a physical Python file
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)
        
    # Open log file to capture print statements and errors
    log_file = open(log_path, "w", encoding="utf-8")
    
    try:
        # Added "-u" (unbuffered) flag so Python flushes print statements directly to the log file instantly
        proc = subprocess.Popen(
            [sys.executable, "-u", script_path],
            stdout=log_file,
            stderr=subprocess.STDOUT
        )
        active_processes[bot_id] = {'proc': proc, 'log_file': log_file}
        
        # Securely save the PID to file for cross-thread killing
        with open(pid_path, "w") as f:
            f.write(str(proc.pid))
            
        print(f"✅ Bot {bot_id} started successfully. PID: {proc.pid}")
    except Exception as e:
        print(f"❌ Failed to start bot {bot_id}: {e}")
        log_file.write(f"\n[SYSTEM] ❌ CRITICAL ERROR: Failed to launch process. Details: {str(e)}\n")
        log_file.close()

def stop_bot(bot_id):
    """Stops the running bot process forcefully using PID to prevent duplicate hosts."""
    # 1. Clear from active memory dict
    if bot_id in active_processes:
        proc_info = active_processes[bot_id]
        proc = proc_info['proc']
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except:
            proc.kill()
        try:
            proc_info['log_file'].close()
        except:
            pass
        del active_processes[bot_id]
        
    # 2. Hard Kill via OS using PID file (fixes duplicate hosting bug)
    pid_path = os.path.join(BOTS_DIR, f"{bot_id}.pid")
    if os.path.exists(pid_path):
        try:
            with open(pid_path, "r") as f:
                old_pid = int(f.read().strip())
            
            if sys.platform == 'win32':
                os.system(f"taskkill /F /PID {old_pid} 2>nul")
            else:
                os.kill(old_pid, signal.SIGKILL)
        except Exception:
            pass
        try:
            os.remove(pid_path)
        except:
            pass

    print(f"🛑 Bot {bot_id} stopped cleanly.")

@atexit.register
def cleanup_bots():
    """Ensure all bots stop when the Flask server stops."""
    for bot_id in list(active_processes.keys()):
        stop_bot(bot_id)

def startup_running_bots():
    """Starts bots that were running before the server restarted."""
    try:
        print("🔄 Restoring running bots from database...")
        bots = bots_col.find({"status": "Running"})
        count = 0
        for bot in bots:
            start_bot(str(bot['_id']), bot.get('code', ''))
            count += 1
        print(f"✅ Restored {count} running bots.")
    except Exception as e:
        print(f"❌ Error restoring bots: {e}")

# ==========================================
# BACKEND API ROUTES
# ==========================================
@app.route('/api/signup', methods=['POST'])
def signup():
    try:
        data = request.json
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')

        if users_col.find_one({"username": username}):
            return jsonify({"success": False, "message": "Username already exists!"})
        
        # Grant admin explicitly if username is kamrolh1
        role = 'admin' if username == 'kamrolh1' else 'user'
        
        new_user = {
            "username": username, 
            "email": email, 
            "password": password,
            "role": role,
            "plan": "Free",
            "is_blocked": False,
            "created_at": int(time.time())
        }
        result = users_col.insert_one(new_user)
        new_user['_id'] = str(result.inserted_id)
        
        return jsonify({"success": True, "user": new_user})
    except Exception as e:
        return jsonify({"success": False, "message": f"Database Error: Please check MongoDB connection. Details: {str(e)}"})

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')

        user = users_col.find_one({"username": username, "password": password})
        if user:
            if user.get('is_blocked'):
                return jsonify({"success": False, "message": "Your account has been blocked by Admin."})
            
            # Force admin upgrade for kamrolh1 if missing
            if username == 'kamrolh1' and user.get('role') != 'admin':
                users_col.update_one({"_id": user['_id']}, {"$set": {"role": "admin"}})
                user['role'] = 'admin'

            return jsonify({"success": True, "user": serialize_doc(user)})
        else:
            return jsonify({"success": False, "message": "Invalid Username or Password!"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Database Error: Please check MongoDB connection. Details: {str(e)}"})

@app.route('/api/users/<user_id>/upgrade', methods=['POST'])
def upgrade_plan(user_id):
    try:
        data = request.json
        new_plan = data.get('plan', 'Pro')
        users_col.update_one({"_id": ObjectId(user_id)}, {"$set": {"plan": new_plan}})
        return jsonify({"success": True, "plan": new_plan})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

# --- TELEGRAM TOKEN VERIFICATION ---
@app.route('/api/verify_token', methods=['POST'])
def verify_token():
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({"success": False, "message": "Token is required!"})

    # Sanitize Token
    token = token.replace(" ", "").strip().strip('"').strip("'")
    if token.lower().startswith("bot"):
        token = token[3:]

    try:
        # Check if bot already exists
        if bots_col.find_one({"token": token}):
            return jsonify({"success": False, "message": "This bot token is already deployed! If you lost your account, ask Admin to delete the old project."})
    except Exception as e:
        return jsonify({"success": False, "message": f"DB Error: {str(e)}"})

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            res_data = json.loads(response.read().decode())
            if res_data.get('ok'):
                bot_info = res_data['result']
                return jsonify({
                    "success": True, 
                    "name": bot_info.get('first_name', 'Unknown Bot'),
                    "username": bot_info.get('username', 'unknown')
                })
            else:
                return jsonify({"success": False, "message": "Invalid Bot Token!"})
    except urllib.error.HTTPError as e:
        if e.code == 401 or e.code == 404:
            return jsonify({"success": False, "message": "Invalid Bot Token! Please check your token."})
        else:
            return jsonify({"success": False, "message": f"Telegram API Error ({e.code}). Please check your connection."})
    except urllib.error.URLError as e:
        return jsonify({"success": False, "message": "Network Error: Telegram API is blocked in your network! Turn on VPN."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Connection Failed: {str(e)}"})

# --- Normal User Bot Routes ---
@app.route('/api/bots', methods=['GET'])
def get_bots():
    owner_id = request.args.get('ownerId')
    if not owner_id:
        return jsonify({"success": False, "message": "Owner ID required."})
        
    try:
        # Construct robust query for both String and ObjectId references to fix disappearing bots bug
        query = {"$or": [{"ownerId": owner_id}]}
        try:
            query["$or"].append({"ownerId": ObjectId(owner_id)})
        except InvalidId:
            pass
            
        bots = list(bots_col.find(query))
        bots = bots[::-1]
        
        for bot in bots:
            bot_id_str = str(bot['_id'])
            log_path = os.path.join(BOTS_DIR, f"{bot_id_str}.log")
            
            # Read the real physical log file
            file_logs = []
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        file_logs = f.read().splitlines()[-100:] 
                except:
                    pass
            
            # Merge System Logs from DB with Live Terminal Logs safely
            db_logs = bot.get('logs', [])
            if not isinstance(db_logs, list):
                db_logs = [str(db_logs)]
            bot['logs'] = db_logs + file_logs
        
        return jsonify({"success": True, "bots": [serialize_doc(bot) for bot in bots]})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/bots', methods=['POST'])
def create_bot():
    try:
        bot_data = request.json
        
        # Prevent duplicate deployments completely
        if bots_col.find_one({"token": bot_data.get('token')}):
            return jsonify({"success": False, "message": "Bot is already deployed on the server!"})
            
        result = bots_col.insert_one(bot_data)
        bot_id = str(result.inserted_id)
        bot_data['_id'] = bot_id
        
        if bot_data.get('status') == 'Running':
            start_bot(bot_id, bot_data.get('code', ''))
            
        return jsonify({"success": True, "bot": serialize_doc(bot_data)})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/bots/<bot_id>', methods=['PUT'])
def update_bot(bot_id):
    try:
        update_data = request.json
        if '_id' in update_data: del update_data['_id']
        
        if 'logs' in update_data:
            update_data['logs'] = [l for l in update_data['logs'] if isinstance(l, str) and l.startswith('[SYSTEM]')]
        
        bot = bots_col.find_one({"_id": ObjectId(bot_id)})
        new_code = update_data.get('code', bot.get('code', ''))
        
        bots_col.update_one({"_id": ObjectId(bot_id)}, {"$set": update_data})
        
        if 'status' in update_data:
            if update_data['status'] == 'Running':
                start_bot(bot_id, new_code)
            else:
                stop_bot(bot_id)
                
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/bots/<bot_id>', methods=['DELETE'])
def delete_bot(bot_id):
    try:
        stop_bot(bot_id)
        bots_col.delete_one({"_id": ObjectId(bot_id)})
        
        script_path = os.path.join(BOTS_DIR, f"{bot_id}.py")
        log_path = os.path.join(BOTS_DIR, f"{bot_id}.log")
        pid_path = os.path.join(BOTS_DIR, f"{bot_id}.pid")
        
        if os.path.exists(script_path): os.remove(script_path)
        if os.path.exists(log_path): os.remove(log_path)
        if os.path.exists(pid_path): os.remove(pid_path)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/bots/<bot_id>/install', methods=['POST'])
def install_package(bot_id):
    pkg = request.json.get('package')
    if not pkg: 
        return jsonify({"success": False, "message": "No package specified"})
    
    if pkg.lower() == "telebot":
        pkg = "pyTelegramBotAPI"
        
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "install", pkg], capture_output=True, text=True)
        if result.returncode == 0:
            bots_col.update_one({"_id": ObjectId(bot_id)}, {"$push": {"logs": f"[SYSTEM] 📦 Package installation successful: {pkg}"}})
            return jsonify({"success": True, "output": result.stdout})
        else:
            return jsonify({"success": False, "message": result.stderr})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

# --- SUPER ADMIN ROUTES ---
@app.route('/api/admin/users', methods=['GET'])
def admin_get_users():
    try:
        users = list(users_col.find({}, {"password": 0}))
        for u in users:
            # Check string and ObjectId formats
            u_id = str(u['_id'])
            query = {"$or": [{"ownerId": u_id}]}
            try: query["$or"].append({"ownerId": ObjectId(u_id)})
            except InvalidId: pass
            
            u['bot_count'] = bots_col.count_documents(query)
        return jsonify({"success": True, "users": [serialize_doc(u) for u in users]})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/admin/users/<user_id>', methods=['PUT'])
def admin_update_user(user_id):
    try:
        update_data = request.json
        users_col.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/admin/bots', methods=['GET'])
def admin_get_all_bots():
    try:
        bots = list(bots_col.find())
        for b in bots:
            # Safely fetch owner data
            try:
                owner_id = b.get('ownerId')
                if isinstance(owner_id, str):
                    owner = users_col.find_one({"_id": ObjectId(owner_id)})
                else:
                    owner = users_col.find_one({"_id": owner_id})
                b['owner_username'] = owner['username'] if owner else 'Deleted User'
            except Exception:
                b['owner_username'] = 'Invalid/No Owner'
                
        return jsonify({"success": True, "bots": [serialize_doc(bot) for bot in bots]})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/admin/system', methods=['GET'])
def admin_system_status():
    return jsonify({
        "success": True,
        "nodes": [
            {"name": "Worker-Node-1", "status": "Healthy", "cpu": f"{random.randint(20, 60)}%", "ram": f"{random.randint(2, 6)}GB / 16GB"},
            {"name": "Worker-Node-2", "status": "Healthy", "cpu": f"{random.randint(10, 40)}%", "ram": f"{random.randint(1, 4)}GB / 16GB"}
        ],
        "queue": {
            "pending_builds": random.randint(0, 3),
            "active_workers": len(active_processes)
        }
    })

# ==========================================
# FRONTEND HTML & UI (Served via Python)
# ==========================================
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BotHostBD - Ultra Premium Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background-color: #060913; }
        .hide-scroll::-webkit-scrollbar { display: none; }
        .hide-scroll { -ms-overflow-style: none; scrollbar-width: none; }
        
        .step-circle { width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; transition: all 0.3s ease; z-index: 10;}
        .step-active { background: #3b82f6; color: white; box-shadow: 0 0 15px rgba(59, 130, 246, 0.5); }
        .step-completed { background: #1e293b; color: #94a3b8; border: 1px solid #334155; }
        .step-inactive { background: #111827; color: #475569; border: 1px solid #1f2937; }
        .step-line { position: absolute; top: 20px; left: 0; width: 100%; height: 2px; background: #1e293b; z-index: 0; }
        
        .gradient-btn { background: linear-gradient(to right, #6366f1, #8b5cf6, #d946ef); box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3); transition: all 0.3s; }
        .gradient-btn:hover { box-shadow: 0 6px 20px rgba(139, 92, 246, 0.5); transform: translateY(-1px); }
        
        .editor-scroll::-webkit-scrollbar { width: 6px; height: 6px; }
        .editor-scroll::-webkit-scrollbar-track { background: transparent; }
        .editor-scroll::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 10px; }
        .editor-scroll::-webkit-scrollbar-thumb:hover { background: #334155; }

        .bot-action-btn { transition: all 0.2s; display: flex; flex-direction: row; align-items: center; justify-content: center; gap: 8px; padding: 12px 16px; border-radius: 12px; font-weight: 700; font-size: 14px; border: 1px solid transparent; cursor: pointer; }
        .bot-action-btn:hover { transform: translateY(-2px); }
    </style>
</head>
<body class="text-slate-200 font-sans selection:bg-blue-500/30 overflow-hidden">

    <!-- APP INITIAL LOADER -->
    <div id="app-loader" class="fixed inset-0 z-[200] bg-[#060913] flex flex-col items-center justify-center transition-opacity duration-500">
        <div class="w-24 h-24 bg-indigo-500/20 rounded-full flex items-center justify-center mb-6 animate-pulse shadow-[0_0_30px_rgba(99,102,241,0.3)]">
            <i data-lucide="bot" class="w-12 h-12 text-indigo-400"></i>
        </div>
        <h2 class="text-3xl font-black text-white mb-2 tracking-tight">Botify<span class="text-indigo-400">Host</span></h2>
        <p class="text-slate-400 text-sm font-medium animate-pulse">Initializing secure connection...</p>
    </div>

    <!-- BIG SUCCESS OVERLAY -->
    <div id="big-success-overlay" class="fixed inset-0 z-[100] flex items-center justify-center bg-[#060913]/80 backdrop-blur-md opacity-0 pointer-events-none transition-all duration-500">
        <div class="bg-gradient-to-b from-green-900/40 to-[#0f172a] border border-green-500/50 p-10 rounded-3xl shadow-[0_0_80px_rgba(34,197,94,0.2)] text-center transform scale-75 transition-transform duration-500 max-w-sm w-full" id="big-success-content">
            <div class="w-24 h-24 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-6 border-4 border-green-500 shadow-[0_0_30px_rgba(34,197,94,0.4)]">
                <i data-lucide="check-circle" class="w-12 h-12 text-green-400"></i>
            </div>
            <h2 class="text-3xl font-extrabold text-white mb-2">SUCCESS!</h2>
            <p id="big-success-msg" class="text-green-400 text-sm font-medium">Operation completed successfully.</p>
            <button onclick="document.getElementById('big-success-overlay').classList.add('opacity-0', 'pointer-events-none'); document.getElementById('big-success-content').classList.replace('scale-100', 'scale-75');" class="mt-8 px-8 py-3 w-full bg-green-600 hover:bg-green-500 text-white rounded-xl font-bold transition-colors shadow-lg">Awesome!</button>
        </div>
    </div>

    <!-- LOGIN MODAL CONTAINER (FULL SCREEN HIDDEN BY DEFAULT) -->
    <div id="login-container" class="fixed inset-0 z-50 flex items-center justify-center bg-[#060913] hidden opacity-0 transition-opacity duration-500">
        <div id="login-content" class="w-full max-w-sm bg-[#12182b] border border-slate-800 rounded-3xl p-8 shadow-[0_0_50px_rgba(99,102,241,0.15)] relative transform scale-95 translate-y-4 transition-all duration-300">
            <div class="text-center mb-8">
                <div class="w-16 h-16 bg-indigo-500/10 rounded-2xl flex items-center justify-center mx-auto mb-4 border border-indigo-500/20 text-indigo-400 shadow-inner">
                    <i data-lucide="fingerprint" class="w-8 h-8"></i>
                </div>
                <h2 id="auth-title" class="text-2xl font-black text-white mb-1 tracking-tight">Welcome Back</h2>
                <p class="text-xs text-slate-400">Please sign in to access your dashboard</p>
            </div>
            <form id="auth-form" class="space-y-4" onsubmit="window.handleAuthSubmit(event)">
                <div class="relative"><div class="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-500"><i data-lucide="user" class="w-4 h-4"></i></div><input id="auth-username" type="text" placeholder="Username" class="w-full bg-[#0b101e] border border-slate-700 rounded-xl pl-11 pr-4 py-3.5 text-sm font-medium text-white focus:outline-none focus:border-indigo-500 transition-colors" required></div>
                <div id="email-field" class="relative hidden"><div class="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-500"><i data-lucide="mail" class="w-4 h-4"></i></div><input id="auth-email" type="email" placeholder="Email Address" class="w-full bg-[#0b101e] border border-slate-700 rounded-xl pl-11 pr-4 py-3.5 text-sm font-medium text-white focus:outline-none focus:border-indigo-500 transition-colors"></div>
                <div class="relative"><div class="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-500"><i data-lucide="key" class="w-4 h-4"></i></div><input id="auth-password" type="password" placeholder="Password" class="w-full bg-[#0b101e] border border-slate-700 rounded-xl pl-11 pr-10 py-3.5 text-sm font-medium text-white focus:outline-none focus:border-indigo-500 transition-colors" required minlength="6"></div>
                <button id="auth-submit-btn" type="submit" class="gradient-btn w-full text-white font-bold py-3.5 rounded-xl flex items-center justify-center gap-2 mt-6"><span id="auth-btn-text">Sign In</span> <i data-lucide="arrow-right" class="w-4 h-4"></i></button>
                <div class="text-center pt-5 mt-5 border-t border-slate-800/80"><a href="#" id="auth-switch-link" onclick="window.toggleAuthMode(event)" class="text-xs text-indigo-400 font-bold hover:text-indigo-300 transition-colors">Create an account instead</a></div>
            </form>
        </div>
    </div>

    <!-- MAIN APP CONTAINER -->
    <div id="app-container" class="flex h-screen w-full relative hidden opacity-0 transition-opacity duration-500">
        <!-- Sidebar -->
        <div class="w-64 md:w-72 bg-[#0b101e] border-r border-slate-800/60 flex flex-col hidden md:flex shrink-0 z-20">
            
            <div class="p-6 md:p-8 flex items-center gap-4 border-b border-slate-800/60 relative overflow-hidden">
                <div class="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center shadow-[0_0_15px_rgba(99,102,241,0.4)] shrink-0">
                    <i data-lucide="bot" class="text-white w-6 h-6"></i>
                </div>
                <div>
                    <h1 class="text-xl font-black tracking-tight text-white leading-tight">Botify<span class="text-indigo-400">Host</span></h1>
                    <p class="text-[10px] text-slate-400 uppercase tracking-widest font-semibold mt-0.5">Professional Hosting</p>
                </div>
            </div>

            <!-- Navigation Links -->
            <nav class="flex-1 py-8 px-4 space-y-2 overflow-y-auto hide-scroll">
                
                <button onclick="window.switchView('home')" id="nav-home" class="nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[14px] font-bold transition-all duration-300 bg-gradient-to-r from-indigo-600/20 to-purple-600/5 text-indigo-400">
                    <i data-lucide="layout-dashboard" class="w-5 h-5"></i> Dashboard
                </button>

                <button onclick="window.switchView('create')" id="nav-create" class="nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[14px] font-semibold transition-all duration-300 text-slate-400 hover:bg-slate-800/50 hover:text-white">
                    <i data-lucide="pen-tool" class="w-5 h-5"></i> Create Bot
                </button>
                
                <button onclick="window.switchView('dashboard')" id="nav-dashboard" class="nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[14px] font-semibold transition-all duration-300 text-slate-400 hover:bg-slate-800/50 hover:text-white">
                    <i data-lucide="settings" class="w-5 h-5"></i> Manage Bots
                </button>

                <button onclick="showToast('Files coming soon')" id="nav-files" class="nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[14px] font-semibold transition-all duration-300 text-slate-400 hover:bg-slate-800/50 hover:text-white">
                    <i data-lucide="folder" class="w-5 h-5"></i> Files
                </button>

                <button onclick="window.switchView('pricing')" id="nav-pricing" class="nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[14px] font-semibold transition-all duration-300 text-slate-400 hover:bg-slate-800/50 hover:text-white">
                    <i data-lucide="crown" class="w-5 h-5"></i> Plans
                </button>
                
                <!-- Admin Section -->
                <div id="nav-admin-section" class="hidden">
                    <div class="pt-6 pb-2">
                        <p class="text-[10px] font-black text-rose-500/80 uppercase tracking-widest px-4 flex items-center gap-2">
                            <i data-lucide="shield-alert" class="w-3 h-3"></i> Super Admin
                        </p>
                    </div>
                    <button onclick="window.switchView('superadmin')" id="nav-superadmin" class="nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[14px] font-semibold transition-all duration-300 text-slate-400 hover:bg-rose-500/10 hover:text-rose-400">
                        <i data-lucide="lock" class="w-5 h-5"></i> Admin Panel
                    </button>
                </div>
            </nav>

            <div class="p-6 border-t border-slate-800/60">
                <div class="flex flex-col gap-1 mb-4 px-2">
                    <p id="sidebar-user-name" class="text-sm font-bold text-white truncate group-hover:text-indigo-400 transition-colors">Guest</p>
                    <p id="sidebar-user-role" class="text-[11px] font-medium text-indigo-400">Free Plan</p>
                </div>
                <button onclick="window.handleLogout()" class="text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 transition-colors py-2 px-4 rounded-xl text-xs font-bold flex items-center gap-2 w-full justify-start" title="Logout">
                    <i data-lucide="log-out" class="w-4 h-4"></i> Logout
                </button>
            </div>
        </div>

        <!-- Main Content -->
        <div class="flex-1 flex flex-col overflow-hidden relative w-full bg-[#060913]">
            <header id="main-header" class="h-20 border-b border-slate-800/60 flex items-center justify-between px-6 md:px-10 bg-[#0b101e]/90 backdrop-blur-xl z-10 shrink-0">
                <h2 id="header-title" class="text-lg md:text-xl font-bold text-white tracking-tight">Dashboard</h2>
                <div class="flex items-center gap-4">
                    <button class="w-10 h-10 rounded-full bg-slate-800/50 flex items-center justify-center text-slate-400 hover:text-white transition-colors relative">
                        <i data-lucide="bell" class="w-5 h-5"></i>
                        <span class="absolute top-2 right-2 w-2 h-2 bg-rose-500 rounded-full"></span>
                    </button>
                    <button onclick="window.switchView('create')" class="hidden md:flex items-center gap-2 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500 hover:text-white px-5 py-2.5 rounded-full text-sm font-bold transition-all border border-emerald-500/20">
                        <i data-lucide="plus" class="w-4 h-4"></i> Create Bot
                    </button>
                    <button onclick="window.switchView('pricing')" class="hidden md:flex items-center gap-2 bg-amber-500/10 text-amber-400 hover:bg-amber-500 hover:text-white px-5 py-2.5 rounded-full text-sm font-bold transition-all border border-amber-500/20">
                        <i data-lucide="crown" class="w-4 h-4"></i> Upgrade
                    </button>
                    <button class="md:hidden text-slate-400 hover:text-white"><i data-lucide="menu"></i></button>
                </div>
            </header>

            <main class="flex-1 overflow-y-auto p-6 md:p-10" id="main-content">
                
                <!-- 1. HOME DASHBOARD -->
                <div id="view-home" class="view-section space-y-8 block max-w-6xl mx-auto">
                    <div class="bg-[#12182b] border border-slate-800 rounded-3xl p-8 md:p-10 relative overflow-hidden flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
                        <div class="absolute top-0 right-0 w-[500px] h-[500px] bg-gradient-to-bl from-indigo-600/20 via-purple-600/5 to-transparent rounded-full blur-3xl pointer-events-none -translate-y-1/2 translate-x-1/3"></div>
                        <div class="relative z-10">
                            <h2 class="text-3xl md:text-4xl font-extrabold text-white mb-3">Welcome back, <span id="home-welcome-name" class="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-purple-400">User</span>! 👋</h2>
                            <p class="text-slate-400 font-medium mb-6">Here's what's happening with your bots today</p>
                            <div class="flex items-center gap-3">
                                <span id="home-plan-badge-display" class="bg-amber-500/10 border border-amber-500/20 text-amber-400 px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 shadow-[0_0_10px_rgba(245,158,11,0.1)]">
                                    <i data-lucide="crown" class="w-3.5 h-3.5"></i> Pro Plan
                                </span>
                                <span class="bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5">
                                    <i data-lucide="check-circle-2" class="w-3.5 h-3.5"></i> All Systems Operational
                                </span>
                            </div>
                        </div>
                        <button onclick="window.switchView('create')" class="relative z-10 gradient-btn text-white px-8 py-4 rounded-2xl font-bold text-sm flex items-center gap-2 shadow-lg">
                            <i data-lucide="plus" class="w-5 h-5"></i> Create New Bot
                        </button>
                    </div>

                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div class="bg-[#12182b] border border-slate-800 rounded-3xl p-8 flex flex-col relative overflow-hidden group hover:border-indigo-500/50 transition-colors">
                            <div class="flex justify-between items-start mb-6">
                                <div class="w-12 h-12 bg-indigo-500/10 text-indigo-400 rounded-xl flex items-center justify-center shadow-inner">
                                    <i data-lucide="bot" class="w-6 h-6"></i>
                                </div>
                                <span class="bg-indigo-500/20 text-indigo-400 text-[10px] font-bold px-2 py-1 rounded uppercase tracking-wider">Total</span>
                            </div>
                            <p class="text-slate-400 text-sm font-semibold mb-1">Total Bots</p>
                            <h3 class="text-5xl font-black text-white" id="home-total-bots">0</h3>
                        </div>

                        <div class="bg-[#12182b] border border-slate-800 rounded-3xl p-8 flex flex-col relative overflow-hidden group hover:border-emerald-500/50 transition-colors">
                            <div class="flex justify-between items-start mb-6">
                                <div class="w-12 h-12 bg-emerald-500/10 text-emerald-400 rounded-xl flex items-center justify-center shadow-inner">
                                    <i data-lucide="play" class="w-6 h-6 ml-0.5"></i>
                                </div>
                                <span class="bg-emerald-500/20 text-emerald-400 text-[10px] font-bold px-2 py-1 rounded uppercase tracking-wider">Active</span>
                            </div>
                            <p class="text-slate-400 text-sm font-semibold mb-1">Active Bots</p>
                            <h3 class="text-5xl font-black text-white" id="home-active-bots">0</h3>
                            <p class="text-xs text-emerald-400 mt-4 flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span> Running smoothly</p>
                        </div>
                    </div>

                    <div class="bg-[#12182b] border border-slate-800 rounded-3xl p-8">
                        <div class="flex justify-between items-center mb-6">
                            <h3 class="text-xl font-bold text-white">Your Bots</h3>
                            <button onclick="window.switchView('dashboard')" class="text-sm font-semibold text-slate-400 hover:text-white flex items-center gap-1 transition-colors">
                                Manage All <i data-lucide="arrow-right" class="w-4 h-4"></i>
                            </button>
                        </div>
                        <div id="home-quick-list" class="space-y-3">
                            <!-- Populated by JS -->
                        </div>
                    </div>
                </div>

                <!-- 2. MANAGE BOTS VIEW -->
                <div id="view-dashboard" class="view-section space-y-6 hidden h-full flex-col max-w-7xl mx-auto">
                    <div class="flex flex-col md:flex-row justify-between items-start md:items-end shrink-0 gap-4 mb-2">
                        <div>
                            <h2 class="text-3xl font-extrabold text-white mb-1">Manage Your Bots</h2>
                            <p class="text-sm text-slate-400">Full control and customization of your Telegram bots.</p>
                        </div>
                        <button onclick="window.switchView('create')" class="bg-slate-800 text-white hover:bg-slate-700 px-6 py-2.5 rounded-xl font-bold flex items-center gap-2 transition-all border border-slate-600">
                            <i data-lucide="plus" class="w-5 h-5"></i> Create New Bot
                        </button>
                    </div>

                    <!-- Empty State -->
                    <div id="dashboard-empty-state" class="hidden flex flex-col items-center justify-center flex-1 bg-[#12182b] border border-slate-800 rounded-3xl min-h-[400px]">
                        <div class="w-20 h-20 bg-slate-800/50 rounded-full flex items-center justify-center mb-6 text-slate-500 shadow-inner">
                            <i data-lucide="bot" class="w-10 h-10"></i>
                        </div>
                        <h4 class="text-xl font-bold text-white mb-2">No Bots Found</h4>
                        <p class="text-sm text-slate-400 mb-8 text-center max-w-sm">Deploy your first bot to start managing it here.</p>
                        <button onclick="window.switchView('create')" class="gradient-btn text-white px-8 py-3 rounded-xl font-bold shadow-lg">
                            Deploy First Bot
                        </button>
                    </div>

                    <div id="dashboard-content" class="flex-1 flex flex-col lg:flex-row gap-6 min-h-0 hidden pb-4">
                        <div class="w-full lg:w-[35%] xl:w-[30%] flex flex-col gap-3 overflow-y-auto editor-scroll pr-2" id="dashboard-bot-list"></div>
                        <div class="w-full lg:w-[65%] xl:w-[70%] flex flex-col gap-6 overflow-y-auto editor-scroll relative" id="dashboard-bot-details"></div>
                    </div>
                </div>

                <!-- CREATE BOT WIZARD VIEW -->
                <div id="view-create" class="view-section hidden max-w-4xl mx-auto py-4">
                    <div class="text-center mb-12">
                        <h2 class="text-4xl font-extrabold text-white mb-3">Create Your Bot <span class="text-2xl">🚀</span></h2>
                        <p class="text-slate-400 text-sm">Follow the steps to deploy your bot in minutes</p>
                    </div>

                    <div class="relative flex justify-between items-center max-w-2xl mx-auto mb-12 px-2">
                        <div class="step-line"></div>
                        <div class="flex flex-col items-center gap-2 z-10 w-16">
                            <div id="step-indicator-1" class="step-circle step-active">1</div>
                            <span id="step-text-1" class="text-xs font-bold text-white">Platform</span>
                        </div>
                        <div class="flex flex-col items-center gap-2 z-10 w-16">
                            <div id="step-indicator-2" class="step-circle step-inactive">2</div>
                            <span id="step-text-2" class="text-xs font-medium text-slate-500">Language</span>
                        </div>
                        <div class="flex flex-col items-center gap-2 z-10 w-16">
                            <div id="step-indicator-3" class="step-circle step-inactive">3</div>
                            <span id="step-text-3" class="text-xs font-medium text-slate-500">Source</span>
                        </div>
                        <div class="flex flex-col items-center gap-2 z-10 w-16">
                            <div id="step-indicator-4" class="step-circle step-inactive">4</div>
                            <span id="step-text-4" class="text-xs font-medium text-slate-500">Config</span>
                        </div>
                        <div class="flex flex-col items-center gap-2 z-10 w-16">
                            <div id="step-indicator-5" class="step-circle step-inactive">5</div>
                            <span id="step-text-5" class="text-xs font-medium text-slate-500">Deploy</span>
                        </div>
                    </div>

                    <div class="bg-[#12182b] border border-slate-800 rounded-3xl p-6 md:p-10 shadow-2xl relative overflow-hidden">
                        <div id="wizard-step-1" class="wizard-step block">
                            <h3 class="text-xl font-extrabold text-white mb-6 text-center">Choose Bot Platform</h3>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
                                <div class="border-2 border-indigo-500 bg-indigo-500/5 rounded-2xl p-6 cursor-pointer relative transition-all hover:bg-indigo-500/10">
                                    <div class="absolute top-4 right-4 text-indigo-500"><i data-lucide="check-circle" class="fill-current w-6 h-6"></i></div>
                                    <h4 class="text-lg font-bold text-white mb-2">Telegram Bot</h4>
                                    <p class="text-sm text-slate-400">Create interactive bots for Telegram</p>
                                </div>
                                <div class="border-2 border-slate-800 bg-[#0b101e] rounded-2xl p-6 opacity-60 cursor-not-allowed relative">
                                    <h4 class="text-lg font-bold text-white mb-2">Discord Bot</h4>
                                    <p class="text-sm text-slate-500">Coming Soon</p>
                                </div>
                            </div>
                            <div class="flex justify-end mt-10">
                                <button onclick="window.nextWizard(2)" class="gradient-btn text-white px-8 py-3 rounded-xl font-bold flex items-center gap-2">Next <i data-lucide="arrow-right" class="w-4 h-4"></i></button>
                            </div>
                        </div>

                        <div id="wizard-step-2" class="wizard-step hidden">
                            <h3 class="text-xl font-extrabold text-white mb-6 text-center">Select Language</h3>
                            <div class="grid grid-cols-1 gap-5 max-w-lg mx-auto">
                                <div class="border-2 border-indigo-500 bg-indigo-500/5 rounded-2xl p-6 cursor-pointer relative">
                                    <div class="absolute top-4 right-4 text-indigo-500"><i data-lucide="check-circle" class="fill-current w-6 h-6"></i></div>
                                    <div class="flex items-center gap-4">
                                        <img src="https://upload.wikimedia.org/wikipedia/commons/c/c3/Python-logo-notext.svg" class="w-8 h-8" alt="Python">
                                        <div>
                                            <h4 class="text-lg font-bold text-white">Python</h4>
                                            <p class="text-sm text-slate-400">Powerful & Easy. Supports python-telegram-bot, telebot.</p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="flex justify-between mt-10">
                                <button onclick="window.nextWizard(1)" class="text-slate-400 hover:text-white px-6 py-3 rounded-xl font-bold flex items-center gap-2 transition-colors"><i data-lucide="arrow-left" class="w-4 h-4"></i> Back</button>
                                <button onclick="window.nextWizard(3)" class="gradient-btn text-white px-8 py-3 rounded-xl font-bold flex items-center gap-2">Next <i data-lucide="arrow-right" class="w-4 h-4"></i></button>
                            </div>
                        </div>

                        <div id="wizard-step-3" class="wizard-step hidden">
                            <h3 class="text-xl font-extrabold text-white mb-6 text-center">Choose Source Code</h3>
                            <div class="grid grid-cols-1 gap-5 max-w-lg mx-auto">
                                <div class="border-2 border-indigo-500 bg-indigo-500/5 rounded-2xl p-6 cursor-pointer relative">
                                    <div class="absolute top-4 right-4 text-indigo-500"><i data-lucide="check-circle" class="fill-current w-6 h-6"></i></div>
                                    <h4 class="text-lg font-bold text-white mb-1 flex items-center gap-2"><i data-lucide="file-code-2" class="w-5 h-5 text-indigo-400"></i> Template</h4>
                                    <p class="text-sm text-slate-400">Start with "Create Your First Bot" template</p>
                                </div>
                            </div>
                            <div class="flex justify-between mt-10">
                                <button onclick="window.nextWizard(2)" class="text-slate-400 hover:text-white px-6 py-3 rounded-xl font-bold flex items-center gap-2 transition-colors"><i data-lucide="arrow-left" class="w-4 h-4"></i> Back</button>
                                <button onclick="window.nextWizard(4)" class="gradient-btn text-white px-8 py-3 rounded-xl font-bold flex items-center gap-2">Next <i data-lucide="arrow-right" class="w-4 h-4"></i></button>
                            </div>
                        </div>

                        <div id="wizard-step-4" class="wizard-step hidden">
                            <h3 class="text-xl font-extrabold text-white mb-6 text-center">Bot Configuration</h3>
                            <div class="max-w-lg mx-auto space-y-6">
                                <div class="space-y-2">
                                    <label class="text-sm font-bold text-slate-300 ml-1">Bot Token (from @BotFather)</label>
                                    <input id="wizard-token" type="text" placeholder="e.g. 1234567890:ABCdefGhIJKlmNoPQRsTuvWxyz" class="w-full bg-[#0b101e] border border-slate-700 rounded-xl px-5 py-4 text-white focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 font-mono text-sm shadow-inner transition-all"/>
                                </div>
                                <div class="bg-slate-800/50 p-4 rounded-xl border border-slate-700/50 flex items-start gap-3">
                                    <i data-lucide="lightbulb" class="w-5 h-5 text-amber-400 shrink-0 mt-0.5"></i>
                                    <p class="text-sm text-slate-300 font-medium">Click <span class="text-indigo-400">Verify</span> to fetch bot information from Telegram automatically.</p>
                                </div>
                            </div>
                            <div class="flex justify-between mt-10 max-w-lg mx-auto">
                                <button onclick="window.nextWizard(3)" class="text-slate-400 hover:text-white px-6 py-3 rounded-xl font-bold flex items-center gap-2 transition-colors"><i data-lucide="arrow-left" class="w-4 h-4"></i> Back</button>
                                <button id="wizard-verify-btn" onclick="window.verifyWizardToken()" class="gradient-btn text-white px-8 py-3 rounded-xl font-bold flex items-center gap-2 transition-all">
                                    Verify <i data-lucide="shield-check" class="w-4 h-4"></i>
                                </button>
                            </div>
                        </div>

                        <div id="wizard-step-5" class="wizard-step hidden">
                            <h3 class="text-xl font-extrabold text-white mb-6 text-center">Review & Deploy</h3>
                            <div class="max-w-lg mx-auto bg-[#0b101e] border border-slate-800 rounded-2xl p-6 shadow-inner mb-8">
                                <div class="space-y-4">
                                    <div class="flex justify-between border-b border-slate-800 pb-3">
                                        <span class="text-slate-400 text-sm">Platform</span>
                                        <span class="text-white font-medium text-sm flex items-center gap-1.5"><i data-lucide="bot" class="w-4 h-4 text-indigo-400"></i> Telegram</span>
                                    </div>
                                    <div class="flex justify-between border-b border-slate-800 pb-3">
                                        <span class="text-slate-400 text-sm">Language</span>
                                        <span class="text-white font-medium text-sm flex items-center gap-1.5"><i data-lucide="code" class="w-4 h-4 text-amber-400"></i> Python</span>
                                    </div>
                                    <div class="flex justify-between border-b border-slate-800 pb-3">
                                        <span class="text-slate-400 text-sm">Source Type</span>
                                        <span class="text-white font-medium text-sm">Template: Create Your First Bot</span>
                                    </div>
                                    <div class="flex justify-between items-center pt-1">
                                        <span class="text-slate-400 text-sm">Bot Name</span>
                                        <span id="wizard-review-name" class="text-indigo-400 font-bold text-lg">Fetching...</span>
                                    </div>
                                </div>
                            </div>
                            <div class="flex justify-center mt-6">
                                <button id="wizard-deploy-btn" onclick="window.finalizeDeploy()" class="gradient-btn text-white px-10 py-4 rounded-xl font-bold text-lg flex items-center gap-2 w-full max-w-md justify-center">
                                    <i data-lucide="rocket" class="w-5 h-5"></i> Deploy Now
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- EDITOR VIEW -->
                <div id="view-editor" class="view-section hidden h-full flex flex-col -m-4 md:-m-10">
                    <div class="flex flex-col sm:flex-row justify-between items-center bg-[#12182b] p-4 border-b border-slate-800 gap-4">
                        <div>
                            <h2 class="text-xl font-bold text-white flex items-center gap-2"><i data-lucide="terminal-square" class="text-indigo-500"></i> Code Editor</h2>
                            <p class="text-sm text-slate-400 mt-1">Editing: <span id="editor-bot-name" class="text-indigo-400 font-bold">Bot Name</span></p>
                        </div>
                        <div class="flex flex-wrap gap-2">
                            <button onclick="window.switchView('dashboard')" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-xl text-sm font-medium transition-colors flex items-center gap-2"><i data-lucide="arrow-left" class="w-4 h-4"></i> Back</button>
                            <button onclick="showToast('File upload dialog opened')" class="px-4 py-2 bg-[#0b101e] border border-slate-700 hover:border-indigo-500 text-slate-300 rounded-xl text-sm font-medium transition-colors flex items-center gap-2"><i data-lucide="upload" class="w-4 h-4"></i> Upload File</button>
                            <button id="btn-save-code" onclick="window.saveEditorCode(false)" class="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-bold shadow-[0_0_10px_rgba(79,70,229,0.4)] transition-all flex items-center gap-2"><i data-lucide="save" class="w-4 h-4"></i> Save</button>
                            <button id="btn-save-restart" onclick="window.saveEditorCode(true)" class="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-sm font-bold shadow-[0_0_10px_rgba(16,185,129,0.4)] transition-all flex items-center gap-2"><i data-lucide="refresh-cw" class="w-4 h-4"></i> Save & Restart</button>
                        </div>
                    </div>
                    <div class="flex-1 flex flex-col lg:flex-row bg-[#060913] overflow-hidden">
                        <div class="flex-1 flex flex-col bg-[#0b101e] border-r border-slate-800">
                            <div class="bg-[#12182b] px-4 pt-3 flex border-b border-slate-800">
                                <div class="bg-[#0b101e] px-4 py-2 text-sm font-medium text-indigo-400 border-t-2 border-indigo-500 rounded-t-lg flex items-center gap-2">
                                    <i data-lucide="file-code" class="w-4 h-4"></i> <span id="editor-file-name">main.py</span>
                                </div>
                                <div class="flex-1 flex justify-end items-end pb-2 pr-2 text-xs text-slate-500 font-mono" id="editor-line-count">Lines: 0</div>
                            </div>
                            <textarea id="editor-textarea" class="flex-1 w-full bg-transparent text-emerald-400 font-mono p-5 outline-none resize-none editor-scroll" spellcheck="false" placeholder="Write your Python bot code here..."></textarea>
                        </div>
                        <div class="w-full lg:w-96 flex flex-col bg-[#12182b] overflow-hidden">
                            <div class="flex-1 flex flex-col h-full">
                                <div class="px-4 py-3 border-b border-slate-800 flex justify-between items-center bg-[#0f1423]">
                                    <span class="text-sm font-bold text-white flex items-center gap-2"><i data-lucide="activity" class="w-4 h-4 text-emerald-500"></i> Live Logs</span>
                                    <div class="flex gap-2">
                                        <button onclick="showToast('Errors copied to clipboard')" class="text-slate-400 hover:text-white transition-colors" title="Copy"><i data-lucide="copy" class="w-4 h-4"></i></button>
                                        <button onclick="window.openEditor(window.selectedBotId); showToast('Logs Refreshed')" class="text-slate-400 hover:text-white transition-colors" title="Refresh"><i data-lucide="refresh-cw" class="w-4 h-4"></i></button>
                                    </div>
                                </div>
                                <div id="editor-logs-container" class="flex-1 p-3 font-mono text-xs overflow-y-auto text-slate-400 space-y-1.5 bg-[#0b101e] editor-scroll"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- PRICING VIEW -->
                <div id="view-pricing" class="view-section hidden max-w-6xl mx-auto py-8">
                    <div class="text-center mb-10">
                        <div class="inline-block bg-gradient-to-r from-rose-500 via-fuchsia-500 to-indigo-500 p-[1px] rounded-full mb-4">
                            <span class="block bg-slate-950 px-4 py-1.5 rounded-full text-sm font-bold text-transparent bg-clip-text bg-gradient-to-r from-rose-400 to-indigo-400">🎊 Special Offer 🎉</span>
                        </div>
                        <h2 class="text-3xl md:text-4xl font-extrabold text-white mb-3">Choose Your Plan</h2>
                        <p class="text-slate-400">Start free, upgrade as you grow</p>
                    </div>
                    <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 max-w-4xl mx-auto">
                        <div class="bg-[#12182b] border border-slate-800 rounded-3xl p-8 flex flex-col shadow-lg">
                            <h3 class="text-xl font-bold text-white mb-2">Free</h3>
                            <div class="mb-8"><span class="text-4xl font-black text-white">৳0</span> <span class="text-slate-400 font-medium">/ month</span></div>
                            <button onclick="window.upgradePlan('Free')" class="mt-auto w-full py-4 rounded-xl bg-slate-800 text-white font-bold border border-slate-700">Current Plan</button>
                        </div>
                        <div class="bg-[#12182b] border-2 border-indigo-500 rounded-3xl p-8 flex flex-col shadow-[0_0_30px_rgba(99,102,241,0.15)] relative transform lg:-translate-y-4">
                            <div class="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-indigo-500 text-white px-4 py-1 rounded-full text-xs font-bold tracking-wider shadow-lg">RECOMMENDED</div>
                            <h3 class="text-xl font-bold text-white mb-2">Pro</h3>
                            <div class="mb-8">
                                <div class="text-slate-500 line-through text-sm font-semibold mb-1">৳499</div>
                                <div><span class="text-4xl font-black text-indigo-400">৳199</span> <span class="text-slate-400 font-medium">/ month</span></div>
                            </div>
                            <button id="upgrade-btn-pro" onclick="window.upgradePlan('Pro')" class="mt-auto gradient-btn w-full py-4 rounded-xl text-white font-bold shadow-lg">Upgrade to Pro</button>
                        </div>
                    </div>
                </div>

                <!-- LOGS VIEW -->
                <div id="view-logs" class="view-section hidden h-full flex flex-col space-y-4">
                    <div class="flex items-center justify-between bg-[#12182b] border border-slate-800 p-5 rounded-2xl shadow-sm">
                        <div class="flex items-center gap-4">
                            <button onclick="window.switchView('dashboard')" class="text-slate-400 hover:text-white p-2 hover:bg-slate-800 rounded-xl transition-colors"><i data-lucide="arrow-left" class="w-5 h-5"></i></button>
                            <div>
                                <h3 id="log-bot-name" class="text-xl font-bold text-white leading-tight">Bot Name</h3>
                                <p class="text-xs text-slate-400 font-medium mt-1">Terminal Output</p>
                            </div>
                        </div>
                        <span id="log-bot-status" class="px-4 py-1.5 rounded-xl text-xs font-bold border bg-slate-900 border-slate-700">Status</span>
                    </div>
                    <div id="log-scroll-area" class="flex-1 bg-[#0b101e] border border-slate-800 rounded-2xl font-mono text-xs md:text-sm p-6 overflow-y-auto relative shadow-inner min-h-[400px] editor-scroll">
                        <div class="sticky top-0 right-0 flex justify-end pb-2 mb-4 border-b border-slate-800/80 bg-[#0b101e]/90 backdrop-blur z-10">
                            <button onclick="window.openLogs(window.selectedBotId)" class="mr-4 text-xs font-bold text-indigo-400 hover:text-indigo-300 flex items-center gap-1.5 transition-colors"><i data-lucide="refresh-cw" class="w-4 h-4"></i> Refresh Terminal</button>
                        </div>
                        <div id="log-container" class="space-y-2 leading-relaxed"></div>
                    </div>
                </div>

                <!-- SUPER ADMIN VIEW -->
                <div id="view-superadmin" class="view-section hidden flex flex-col h-full">
                    <div class="mb-6"><h2 class="text-2xl font-black text-white flex items-center gap-2"><i data-lucide="shield-check" class="text-rose-500"></i> Admin Center</h2></div>
                    <div class="flex border-b border-slate-800 mb-6 gap-6">
                        <button onclick="window.switchAdminTab('users')" id="tab-btn-users" class="pb-3 text-sm font-bold transition-colors border-b-2 border-rose-500 text-rose-500">User Management</button>
                        <button onclick="window.switchAdminTab('bots')" id="tab-btn-bots" class="pb-3 text-sm font-bold transition-colors text-slate-500 hover:text-slate-300 border-b-2 border-transparent">All Bots</button>
                    </div>
                    <div id="admin-tab-users" class="admin-tab-content block">
                        <div class="bg-[#12182b] rounded-2xl overflow-hidden shadow-lg border border-slate-800">
                            <table class="w-full text-left text-sm text-slate-300">
                                <thead>
                                    <tr class="bg-slate-900/50"><th class="p-4 font-semibold text-slate-400">User</th><th class="p-4 font-semibold text-slate-400">Role</th><th class="p-4 font-semibold text-slate-400">Bots</th><th class="p-4 font-semibold text-slate-400">Action</th></tr>
                                </thead>
                                <tbody id="admin-users-tbody"></tbody>
                            </table>
                        </div>
                    </div>
                    <div id="admin-tab-bots" class="admin-tab-content hidden">
                        <div class="bg-[#12182b] rounded-2xl overflow-hidden shadow-lg border border-slate-800">
                            <table class="w-full text-left text-sm text-slate-300">
                                <thead>
                                    <tr class="bg-slate-900/50"><th class="p-4 font-semibold text-slate-400">Bot Name</th><th class="p-4 font-semibold text-slate-400">Owner</th><th class="p-4 font-semibold text-slate-400">Status</th><th class="p-4 font-semibold text-slate-400">Action</th></tr>
                                </thead>
                                <tbody id="admin-bots-tbody"></tbody>
                            </table>
                        </div>
                    </div>
                </div>

            </main>
        </div>
    </div>

    <script>
        let currentUser = null;
        let myBots = [];
        let isSignupMode = false;
        let adminData = { users: [], bots: [], system: {} };
        let activeDashboardBotId = null; 
        let wizardData = { token: '', botName: '', botUsername: '' };

        // INITIALIZE APP AND AUTH CHECK
        document.addEventListener('DOMContentLoaded', () => {
            lucide.createIcons();
            const savedUser = localStorage.getItem('botHostUser');
            
            if (savedUser) {
                try {
                    currentUser = JSON.parse(savedUser);
                    
                    // Fake smooth loader for 1s then show App
                    setTimeout(() => {
                        document.getElementById('app-loader').classList.add('opacity-0');
                        setTimeout(() => {
                            document.getElementById('app-loader').classList.add('hidden');
                            const appContainer = document.getElementById('app-container');
                            appContainer.classList.remove('hidden');
                            void appContainer.offsetWidth; // Trigger reflow
                            appContainer.classList.remove('opacity-0');
                            
                            applyUserRoleUI();
                            fetchBotsFromMongo(currentUser._id);
                        }, 500);
                    }, 1000);
                    
                } catch(e) {
                    initiateLoginFlow();
                }
            } else {
                initiateLoginFlow();
            }
        });

        // 3 SECONDS LOADER THEN SHOW LOGIN MODAL
        function initiateLoginFlow() {
            setTimeout(() => {
                document.getElementById('app-loader').classList.add('opacity-0');
                setTimeout(() => {
                    document.getElementById('app-loader').classList.add('hidden');
                    const loginContainer = document.getElementById('login-container');
                    loginContainer.classList.remove('hidden');
                    void loginContainer.offsetWidth; 
                    loginContainer.classList.remove('opacity-0');
                    const loginContent = document.getElementById('login-content');
                    loginContent.classList.replace('scale-95', 'scale-100');
                    loginContent.classList.replace('translate-y-4', 'translate-y-0');
                }, 500);
            }, 3000);
        }

        function showToast(msg, isError = false) {
            const toast = document.createElement('div');
            toast.className = `fixed top-6 right-6 px-5 py-4 rounded-xl shadow-2xl z-[100] text-sm font-bold transition-all duration-300 flex items-center gap-3 border ${isError ? 'bg-[#1a0f14] border-rose-500/30 text-rose-400' : 'bg-[#0f1423] border-indigo-500/30 text-indigo-400'}`;
            toast.innerHTML = `<i data-lucide="${isError ? 'alert-octagon' : 'check-circle'}" class="w-5 h-5"></i> ${msg}`;
            document.body.appendChild(toast);
            lucide.createIcons();
            setTimeout(() => { toast.classList.add('opacity-0', 'translate-x-10'); setTimeout(() => toast.remove(), 300); }, 3000);
        }

        function showBigSuccess(msg) {
            const overlay = document.getElementById('big-success-overlay');
            const content = document.getElementById('big-success-content');
            document.getElementById('big-success-msg').innerText = msg;
            overlay.classList.remove('opacity-0', 'pointer-events-none');
            content.classList.replace('scale-75', 'scale-100');
            lucide.createIcons();
            setTimeout(() => {
                overlay.classList.add('opacity-0', 'pointer-events-none');
                content.classList.replace('scale-100', 'scale-75');
            }, 4000);
        }

        // ---------------- AUTH ----------------
        window.toggleAuthMode = (e) => {
            if(e) e.preventDefault();
            isSignupMode = !isSignupMode;
            document.getElementById('auth-title').innerText = isSignupMode ? "Create Account" : "Welcome Back";
            document.getElementById('auth-btn-text').innerText = isSignupMode ? "Sign Up" : "Sign In";
            document.getElementById('auth-switch-link').innerText = isSignupMode ? "Sign in instead" : "Create an account instead";
            document.getElementById('email-field').classList.toggle('hidden', !isSignupMode);
            document.getElementById('auth-email').required = isSignupMode;
        }

        window.handleAuthSubmit = async (e) => {
            e.preventDefault();
            const btn = document.getElementById('auth-submit-btn');
            const originalHtml = btn.innerHTML;
            btn.disabled = true; btn.innerHTML = `<i data-lucide="loader" class="w-5 h-5 animate-spin"></i>`;
            lucide.createIcons();

            const username = document.getElementById('auth-username').value;
            const password = document.getElementById('auth-password').value;
            const email = document.getElementById('auth-email').value;

            try {
                const endpoint = isSignupMode ? '/api/signup' : '/api/login';
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password, email })
                });
                const data = await response.json();
                btn.innerHTML = originalHtml; btn.disabled = false;

                if (!data.success) return showToast(data.message, true);

                currentUser = data.user;
                localStorage.setItem('botHostUser', JSON.stringify(currentUser));
                
                const loginContainer = document.getElementById('login-container');
                loginContainer.classList.add('opacity-0');
                
                setTimeout(() => {
                    loginContainer.classList.add('hidden');
                    const appContainer = document.getElementById('app-container');
                    appContainer.classList.remove('hidden');
                    void appContainer.offsetWidth;
                    appContainer.classList.remove('opacity-0');
                    
                    applyUserRoleUI();
                    fetchBotsFromMongo(currentUser._id);
                    document.getElementById('auth-form').reset();
                }, 500);

            } catch (err) {
                showToast("Server Connection Error! Network dropped.", true);
                btn.innerHTML = originalHtml; btn.disabled = false;
            }
        }

        window.handleLogout = () => {
            localStorage.removeItem('botHostUser');
            currentUser = null; myBots = []; activeDashboardBotId = null;
            
            const appContainer = document.getElementById('app-container');
            appContainer.classList.add('opacity-0');
            
            setTimeout(() => {
                appContainer.classList.add('hidden');
                const loginContainer = document.getElementById('login-container');
                loginContainer.classList.remove('hidden');
                void loginContainer.offsetWidth;
                loginContainer.classList.remove('opacity-0');
            }, 500);
        }

        function applyUserRoleUI() {
            if(!currentUser) return;
            document.getElementById('sidebar-user-name').innerText = currentUser.username;
            
            // Explicitly force Kamrolh1 admin permissions on frontend
            if(currentUser.role === 'admin' || currentUser.username === 'kamrolh1') {
                document.getElementById('nav-admin-section').classList.remove('hidden');
                document.getElementById('sidebar-user-role').innerHTML = `<span class="text-rose-400 font-bold">SUPER ADMIN</span>`;
            } else {
                document.getElementById('nav-admin-section').classList.add('hidden');
                document.getElementById('sidebar-user-role').innerText = `${currentUser.plan || 'Free'} Plan`;
            }
        }

        // ---------------- VIEW LOGIC ----------------
        window.switchView = (viewName) => {
            document.querySelectorAll('.view-section').forEach(el => el.classList.add('hidden'));
            document.getElementById('view-' + viewName).classList.remove('hidden');
            
            if(viewName === 'create') window.nextWizard(1);
            if(viewName === 'superadmin') window.loadAdminData();
            if(viewName === 'home') renderHomeDashboard();
            if(viewName === 'dashboard') renderDashboard(); 

            const titles = { 
                'home': 'Dashboard',
                'dashboard': 'Manage Bots', 
                'create': 'Create Bot', 
                'logs': 'Terminal Logs', 
                'superadmin': 'Super Admin', 
                'pricing': 'Upgrade Plan' 
            };
            if(titles[viewName]) document.getElementById('header-title').innerText = titles[viewName];

            document.querySelectorAll('.nav-btn').forEach(btn => {
                btn.className = "nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[14px] font-semibold transition-all duration-300 text-slate-400 hover:bg-slate-800/50 hover:text-white";
            });
            
            let activeId = viewName;
            if(viewName === 'editor' || viewName === 'logs') activeId = 'dashboard';
            const activeBtn = document.getElementById('nav-' + activeId);
            
            if(activeBtn) {
                if(activeId === 'superadmin') {
                     activeBtn.className = "nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[14px] font-bold transition-all duration-300 bg-rose-500/10 text-rose-400";
                } else {
                     activeBtn.className = "nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[14px] font-bold transition-all duration-300 bg-gradient-to-r from-indigo-600/20 to-purple-600/5 text-indigo-400";
                }
            }
        }

        // ---------------- FETCH BOTS (FIXED BROWSER CACHE BUG) ----------------
        async function fetchBotsFromMongo(userId) {
            if(!userId) return;
            try {
                // FIXED: Appended a timestamp cache-buster so deployed bots won't disappear on browser refresh
                const response = await fetch(`/api/bots?ownerId=${userId}&_t=${Date.now()}`);
                const data = await response.json();
                if(data.success) { 
                    myBots = data.bots; 
                    
                    if(!document.getElementById('view-home').classList.contains('hidden')) {
                        renderHomeDashboard();
                    } else if (!document.getElementById('view-dashboard').classList.contains('hidden')) {
                        renderDashboard();
                    } else if (!document.getElementById('view-create').classList.contains('hidden') || 
                               !document.getElementById('view-pricing').classList.contains('hidden')) {
                        // Do nothing
                    } else {
                        window.switchView('home');
                    }
                } else {
                    console.error("Failed to load bots:", data.message);
                }
            } catch(e) {
                console.error("Fetch bots network error", e);
            }
        }

        // ---------------- 1. HOME DASHBOARD RENDER ----------------
        function renderHomeDashboard() {
            if(!currentUser) return;
            document.getElementById('home-welcome-name').innerText = currentUser.username;
            document.getElementById('home-plan-badge-display').innerHTML = `<i data-lucide="crown" class="w-3.5 h-3.5"></i> ${currentUser.plan} Plan`;
            
            document.getElementById('home-total-bots').innerText = myBots.length;
            const activeCount = myBots.filter(b => b.status === 'Running').length;
            document.getElementById('home-active-bots').innerText = activeCount;

            const quickList = document.getElementById('home-quick-list');
            if (myBots.length === 0) {
                quickList.innerHTML = `<div class="text-slate-500 text-sm py-4">No bots deployed yet.</div>`;
            } else {
                quickList.innerHTML = myBots.slice(0, 3).map(bot => {
                    const isRunning = bot.status === 'Running';
                    return `
                    <div onclick="window.selectDashboardBot('${bot._id}'); window.switchView('dashboard');" class="bg-[#0b101e] border border-slate-800 rounded-2xl p-4 flex items-center justify-between cursor-pointer hover:border-indigo-500/50 transition-colors group">
                        <div class="flex items-center gap-4">
                            <div class="w-12 h-12 rounded-xl flex items-center justify-center shrink-0 ${isRunning ? 'bg-indigo-500/20 text-indigo-400' : 'bg-slate-800 text-slate-500'}">
                                <i data-lucide="bot" class="w-6 h-6"></i>
                            </div>
                            <div>
                                <h4 class="text-white font-bold text-[15px] mb-0.5 group-hover:text-indigo-400 transition-colors">${bot.name}</h4>
                                <div class="flex items-center gap-2 text-xs font-medium ${isRunning ? 'text-slate-300' : 'text-slate-500'}">
                                    <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full ${isRunning ? 'bg-emerald-500' : 'bg-slate-600'}"></span> ${bot.status}</span>
                                    <span class="text-slate-600">•</span>
                                    <span>@${bot.bot_username}</span>
                                </div>
                            </div>
                        </div>
                        <i data-lucide="chevron-right" class="w-5 h-5 text-slate-600 group-hover:text-indigo-400 transition-colors"></i>
                    </div>
                    `;
                }).join('');
            }
            lucide.createIcons();
        }

        // ---------------- 2. MANAGE BOTS RENDER ----------------
        function renderDashboard() {
            const emptyState = document.getElementById('dashboard-empty-state');
            const contentArea = document.getElementById('dashboard-content');
            const listContainer = document.getElementById('dashboard-bot-list');

            if(myBots.length === 0) {
                emptyState.classList.remove('hidden');
                contentArea.classList.add('hidden');
                return;
            }

            emptyState.classList.add('hidden');
            contentArea.classList.remove('hidden');

            if (!activeDashboardBotId || !myBots.find(b => b._id === activeDashboardBotId)) {
                activeDashboardBotId = myBots[0]._id;
            }

            listContainer.innerHTML = myBots.map(bot => {
                const isActive = bot._id === activeDashboardBotId;
                const isRunning = bot.status === 'Running';
                return `
                    <div onclick="window.selectDashboardBot('${bot._id}')" class="cursor-pointer transition-all duration-500 ease-out p-5 mb-3 rounded-2xl border-2 ${isActive ? 'bg-gradient-to-r from-indigo-900/40 to-[#12182b] border-indigo-500 border-l-4 shadow-[0_0_30px_rgba(99,102,241,0.25)] scale-[1.02] ml-1' : 'bg-[#0b101e] border-slate-800/80 hover:border-indigo-500/50 hover:bg-gradient-to-r hover:from-slate-800/50 hover:to-[#0b101e] hover:shadow-[0_10px_40px_rgba(0,0,0,0.5)] hover:-translate-y-1'} flex items-center justify-between group">
                        <div class="flex items-center gap-5">
                            <div class="w-14 h-14 rounded-2xl flex items-center justify-center shrink-0 ${isRunning ? 'bg-gradient-to-br from-emerald-500 to-teal-600 shadow-[0_0_20px_rgba(16,185,129,0.4)] text-white' : 'bg-slate-800 text-slate-400 shadow-inner'} transition-transform duration-500 group-hover:scale-110">
                                <i data-lucide="bot" class="w-7 h-7"></i>
                            </div>
                            <div class="overflow-hidden flex flex-col justify-center">
                                <h4 class="text-lg font-black text-white mb-1 truncate group-hover:text-indigo-400 transition-colors duration-300 tracking-wide">${bot.name}</h4>
                                <div class="flex items-center gap-2">
                                    <span class="flex items-center gap-2 text-[11px] uppercase tracking-[0.2em] font-extrabold ${isRunning ? 'text-emerald-400' : 'text-slate-500'}">
                                        <span class="relative flex h-2.5 w-2.5">
                                            ${isRunning ? '<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>' : ''}
                                            <span class="relative inline-flex rounded-full h-2.5 w-2.5 ${isRunning ? 'bg-emerald-500' : 'bg-slate-600'}"></span>
                                        </span>
                                        ${bot.status}
                                    </span>
                                </div>
                            </div>
                        </div>
                        <div class="w-10 h-10 rounded-full flex items-center justify-center ${isActive ? 'bg-indigo-500/20 text-indigo-400' : 'bg-slate-800/50 text-slate-500 group-hover:bg-indigo-500/20 group-hover:text-indigo-400 group-hover:shadow-[0_0_15px_rgba(99,102,241,0.3)]'} transition-all duration-300">
                            <i data-lucide="chevron-right" class="w-5 h-5 shrink-0 transition-transform duration-300 group-hover:translate-x-1"></i>
                        </div>
                    </div>
                `;
            }).join('');

            renderBotDetails();
            lucide.createIcons();
        }

        window.selectDashboardBot = (id) => {
            activeDashboardBotId = id;
            renderDashboard(); 
        }

        function renderBotDetails() {
            const container = document.getElementById('dashboard-bot-details');
            const bot = myBots.find(b => b._id === activeDashboardBotId);
            if(!bot) return;

            const isRunning = bot.status === 'Running';

            container.innerHTML = `
                <!-- Bot Header Box -->
                <div class="bg-[#12182b] border border-slate-800 rounded-3xl p-6 md:p-8 relative overflow-hidden">
                    <div class="absolute -right-10 -top-10 w-40 h-40 bg-indigo-500/10 blur-3xl rounded-full"></div>
                    
                    <div class="flex items-center gap-5 mb-8 relative z-10">
                        <div class="w-16 h-16 shrink-0 rounded-2xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center relative shadow-lg text-indigo-400">
                            ${isRunning ? '<div class="absolute -top-1 -right-1 w-4 h-4 bg-emerald-500 rounded-full border-2 border-[#12182b] animate-pulse"></div>' : '<div class="absolute -top-1 -right-1 w-4 h-4 bg-slate-500 rounded-full border-2 border-[#12182b]"></div>'}
                            <i data-lucide="bot" class="w-8 h-8"></i>
                        </div>
                        <div class="overflow-hidden">
                            <h2 class="text-2xl font-black text-white tracking-tight mb-1 truncate">${bot.name}</h2>
                            <div class="flex items-center gap-3 text-sm">
                                <span class="text-slate-400">@${bot.bot_username}</span>
                                <span class="px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider ${isRunning ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 text-slate-400 border border-slate-700'}">${bot.status}</span>
                            </div>
                        </div>
                    </div>

                    <!-- Bot Action Buttons -->
                    <div class="flex flex-wrap gap-3 relative z-10">
                        <button onclick="window.toggleBot('${bot._id}')" class="bot-action-btn ${isRunning ? 'bg-rose-500/10 text-rose-500 hover:bg-rose-500 hover:text-white' : 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500 hover:text-white'}">
                            <i data-lucide="${isRunning ? 'square' : 'play'}" class="w-4 h-4"></i> ${isRunning ? 'Stop' : 'Start'}
                        </button>
                        
                        <button onclick="window.restartBot('${bot._id}')" class="bot-action-btn bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500 hover:text-white" ${!isRunning ? 'style="opacity:0.5; pointer-events:none;"' : ''}>
                            <i data-lucide="refresh-cw" class="w-4 h-4"></i> Restart
                        </button>
                        
                        <button onclick="showToast('Files coming soon')" class="bot-action-btn bg-amber-500/10 text-amber-400 hover:bg-amber-500 hover:text-white">
                            <i data-lucide="folder" class="w-4 h-4"></i> Files
                        </button>
                        
                        <button onclick="window.openEditor('${bot._id}')" class="bot-action-btn bg-purple-500/10 text-purple-400 hover:bg-purple-500 hover:text-white">
                            <i data-lucide="code-2" class="w-4 h-4"></i> Code Editor
                        </button>
                        
                        <button onclick="window.openLogs('${bot._id}')" class="bot-action-btn bg-slate-700/50 text-white hover:bg-slate-700">
                            <i data-lucide="terminal" class="w-4 h-4"></i> View Logs
                        </button>
                        
                        <button onclick="window.deleteBot('${bot._id}')" class="bot-action-btn border border-rose-500/30 text-rose-500 hover:bg-rose-500 hover:text-white ml-auto">
                            <i data-lucide="trash-2" class="w-4 h-4"></i> Delete
                        </button>
                    </div>
                </div>

                <!-- Dependencies & Files Block -->
                <div class="bg-[#12182b] border border-slate-800 rounded-3xl p-6 md:p-8">
                    <h3 class="text-lg font-bold text-white mb-6 flex items-center gap-2"><i data-lucide="package" class="w-5 h-5 text-indigo-400"></i> Dependencies</h3>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <!-- Single Package -->
                        <div class="bg-[#0b101e] border border-slate-700 rounded-2xl p-5">
                            <h4 class="text-sm font-bold text-white mb-3">Install single package</h4>
                            <div class="flex gap-2 mb-2">
                                <input type="text" id="pkg-${bot._id}" placeholder="e.g. aiogram==3.2.0" class="flex-1 bg-[#12182b] border border-slate-600 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:border-indigo-500">
                                <button onclick="window.installPackage('${bot._id}')" class="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-bold rounded-xl transition-colors shrink-0">Install</button>
                            </div>
                            <p class="text-[10px] text-slate-500">Installs directly into the virtual environment for this bot.</p>
                        </div>
                        
                        <!-- Upload Requirements -->
                        <div class="bg-[#0b101e] border border-slate-700 rounded-2xl p-5">
                            <h4 class="text-sm font-bold text-white mb-3">Upload requirements.txt</h4>
                            <div class="flex gap-2 mb-3">
                                <div class="flex-1 bg-[#12182b] border border-slate-600 rounded-xl flex items-center p-1.5 overflow-hidden">
                                     <button class="bg-indigo-600 text-white px-3 py-1.5 rounded-lg text-xs font-bold shrink-0">Choose File</button>
                                     <span class="text-xs text-slate-400 px-3 truncate">No file chosen</span>
                                </div>
                                <button onclick="showToast('Upload coming soon')" class="text-sm font-bold text-white hover:text-indigo-400 px-2">Upload</button>
                            </div>
                            <button onclick="showToast('Feature coming soon')" class="w-full py-2.5 bg-emerald-600/20 text-emerald-500 hover:bg-emerald-600 hover:text-white font-bold rounded-xl text-sm transition-colors mb-2">
                                Install requirements
                            </button>
                            <p class="text-[10px] text-slate-500 text-center">requirements.txt will be stored safely.</p>
                        </div>
                    </div>
                </div>
            `;
        }

        // Toggle Bot Status
        window.toggleBot = async (id) => {
            const bot = myBots.find(b => b._id === id);
            if(!bot) return;
            const isRunning = bot.status === 'Running';
            bot.status = isRunning ? 'Stopped' : 'Running';
            
            if(!bot.logs) bot.logs = [];
            bot.logs.push(bot.status === 'Running' ? '[SYSTEM] ▶️ Bot server has been started and is now online.' : '[SYSTEM] 🛑 Bot server has been stopped and is currently offline.');

            renderDashboard(); 
            
            await fetch('/api/bots/' + id, { 
                method: 'PUT', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify({ status: bot.status, logs: bot.logs, code: bot.code }) 
            });
            await fetchBotsFromMongo(currentUser._id); 
        }

        // Restart Bot 
        window.restartBot = async (id) => {
            const bot = myBots.find(b => b._id === id);
            if(!bot || bot.status !== 'Running') return;
            
            showToast('Restarting server... Please wait.');
            bot.status = 'Stopped';
            if(!bot.logs) bot.logs = [];
            bot.logs.push('[SYSTEM] 🔄 Initiating server restart sequence...');
            
            renderDashboard();
            await fetch('/api/bots/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({status: 'Stopped', logs: bot.logs}) });
            
            setTimeout(async () => {
                bot.status = 'Running';
                bot.logs.push('[SYSTEM] ▶️ Bot server has been restarted and is now online.');
                renderDashboard();
                
                await fetch('/api/bots/' + id, { 
                    method: 'PUT', 
                    headers: { 'Content-Type': 'application/json' }, 
                    body: JSON.stringify({ status: 'Running', logs: bot.logs, code: bot.code }) 
                });
                showToast('Bot Restarted Successfully!');
                await fetchBotsFromMongo(currentUser._id);
            }, 1500); 
        }

        // Delete Bot
        window.deleteBot = async (id) => {
            if(!confirm("Are you sure you want to permanently delete this bot?")) return;
            if(activeDashboardBotId === id) activeDashboardBotId = null;
            myBots = myBots.filter(b => b._id !== id); 
            renderDashboard();
            await fetch('/api/bots/' + id, { method: 'DELETE' });
            fetchBotsFromMongo(currentUser._id);
        }

        // ---------------- PACKAGE INSTALL LOGIC ----------------
        window.installPackage = async (botId) => {
            const pkgInput = document.getElementById(`pkg-${botId}`);
            if(!pkgInput) return;
            const pkg = pkgInput.value.trim();
            if(!pkg) return showToast("Please enter a package name", true);
            
            const btn = pkgInput.nextElementSibling;
            const origHtml = btn.innerHTML;
            btn.innerHTML = `<i data-lucide="loader" class="w-4 h-4 animate-spin"></i>`;
            btn.disabled = true;
            lucide.createIcons();

            showToast(`Installing ${pkg}. This might take a few seconds...`);
            try {
                const res = await fetch(`/api/bots/${botId}/install`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({package: pkg})
                });
                const data = await res.json();
                if(data.success) {
                    showBigSuccess(`${pkg} has been installed successfully!`);
                    pkgInput.value = '';
                } else {
                    showToast(`Failed: ${data.message}`, true);
                }
            } catch(e) {
                showToast("Install error! Check your connection.", true);
            } finally {
                btn.innerHTML = origHtml;
                btn.disabled = false;
                lucide.createIcons();
            }
        };

        // ---------------- EDITOR LOGIC ----------------
        window.openEditor = (id) => {
            window.selectedBotId = id;
            const bot = myBots.find(b => b._id === id);
            if(!bot) return;

            document.getElementById('editor-bot-name').innerText = bot.name;
            
            const textArea = document.getElementById('editor-textarea');
            textArea.value = bot.code || '';
            
            const updateLineCount = () => {
                const lines = textArea.value.split('\\n').length;
                document.getElementById('editor-line-count').innerText = `Lines: ${lines}`;
            };
            textArea.oninput = updateLineCount;
            updateLineCount();

            const logsContainer = document.getElementById('editor-logs-container');
            if(bot.logs && bot.logs.length > 0) {
                logsContainer.innerHTML = bot.logs.slice(-50).map(log => {
                    let color = "text-slate-400";
                    if(log.includes('[ERROR]') || log.includes('Exception') || log.includes('Error') || log.includes('ModuleNotFoundError')) color = "text-rose-400";
                    if(log.includes('[SUCCESS]')) color = "text-emerald-400";
                    if(log.includes('[SYSTEM]')) color = "text-indigo-400";
                    return `<div class="${color} break-words py-0.5">${log}</div>`;
                }).join('');
            } else {
                logsContainer.innerHTML = `<div class="text-center text-slate-600 mt-8"><i data-lucide="coffee" class="w-8 h-8 mx-auto mb-2 opacity-50"></i>No logs available yet</div>`;
            }

            window.switchView('editor');
            lucide.createIcons();
            setTimeout(() => { logsContainer.scrollTop = logsContainer.scrollHeight; }, 100);
        }

        window.saveEditorCode = async (restart = false) => {
            const bot = myBots.find(b => b._id === window.selectedBotId);
            if(!bot) return;
            
            const code = document.getElementById('editor-textarea').value;
            const btn = document.getElementById(restart ? 'btn-save-restart' : 'btn-save-code');
            const originalHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Saving...`;
            lucide.createIcons();

            const updates = { code: code };
            if(!bot.logs) bot.logs = [];
            
            if (restart) {
                updates.status = 'Running';
                bot.logs.push('[SYSTEM] ⚙️ Code modifications saved. Rebuilding environment and restarting bot server...');
            } else {
                bot.logs.push('[SYSTEM] 💾 Code modifications saved securely. (Note: Restart required to apply changes)');
            }
            updates.logs = bot.logs; 

            try {
                const response = await fetch('/api/bots/' + bot._id, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updates)
                });
                const data = await response.json();
                
                if(data.success) {
                    bot.code = code;
                    if(restart) bot.status = 'Running';
                    showToast(restart ? "Saved and Restarted successfully!" : "Code saved.");
                    await fetchBotsFromMongo(currentUser._id);
                }
            } catch (err) {
                showToast("Failed to save code.", true);
            } finally {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
                lucide.createIcons();
                window.openEditor(bot._id);
            }
        }

        // ---------------- WIZARD LOGIC ----------------
        window.nextWizard = (stepNum) => {
            if(stepNum === 1 && currentUser.role !== 'admin') {
                let maxBots = currentUser.plan === 'Pro' ? 2 : (currentUser.plan === 'Enterprise' ? 5 : 0);
                if (myBots.length >= maxBots) {
                    showToast(`${currentUser.plan} limit reached! Upgrade plan.`, true);
                    return window.switchView('pricing');
                }
            }

            if(stepNum < 4) {
                const verifyBtn = document.getElementById('wizard-verify-btn');
                if(verifyBtn) {
                    verifyBtn.removeAttribute('data-skip');
                    verifyBtn.innerHTML = `Verify <i data-lucide="shield-check" class="w-4 h-4"></i>`;
                }
            }

            for(let i=1; i<=5; i++) {
                const el = document.getElementById(`wizard-step-${i}`);
                if(el) { el.classList.add('hidden'); el.classList.remove('block'); }
                
                const ind = document.getElementById(`step-indicator-${i}`);
                const txt = document.getElementById(`step-text-${i}`);
                if(ind && txt) {
                    if(i === stepNum) {
                        ind.className = "step-circle step-active bg-indigo-500 shadow-[0_0_15px_rgba(99,102,241,0.5)] text-white";
                        txt.className = "text-xs font-bold text-white";
                    } else if (i < stepNum) {
                        ind.className = "step-circle step-completed bg-[#12182b] text-indigo-400 border border-slate-700";
                        ind.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path></svg>`;
                        txt.className = "text-xs font-medium text-indigo-400";
                    } else {
                        ind.className = "step-circle step-inactive bg-[#0b101e] text-slate-500 border border-slate-800";
                        ind.innerHTML = i;
                        txt.className = "text-xs font-medium text-slate-500";
                    }
                }
            }
            document.getElementById(`wizard-step-${stepNum}`).classList.remove('hidden');
            document.getElementById(`wizard-step-${stepNum}`).classList.add('block');
        }

        window.verifyWizardToken = async () => {
            const tokenInput = document.getElementById('wizard-token').value.trim();
            if(!tokenInput) return showToast("Token is required!", true);

            const btn = document.getElementById('wizard-verify-btn');
            
            if (btn.getAttribute('data-skip') === 'true') {
                wizardData.token = tokenInput;
                wizardData.botName = "My Telegram Bot";
                wizardData.botUsername = "custom_bot";
                document.getElementById('wizard-review-name').innerText = wizardData.botName;
                
                btn.removeAttribute('data-skip');
                btn.innerHTML = `Verify <i data-lucide="shield-check" class="w-4 h-4"></i>`;
                lucide.createIcons();
                
                window.nextWizard(5);
                return;
            }

            const orig = btn.innerHTML;
            btn.disabled = true; btn.innerHTML = `<i data-lucide="loader" class="w-5 h-5 animate-spin"></i>`;
            lucide.createIcons();

            try {
                const res = await fetch('/api/verify_token', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({token: tokenInput})
                });
                const data = await res.json();
                
                if(!data.success) {
                    showToast(data.message, true);
                    
                    if (data.message.includes("Network Error")) {
                        btn.disabled = false; 
                        btn.innerHTML = `Skip & Deploy <i data-lucide="alert-triangle" class="w-4 h-4"></i>`;
                        btn.setAttribute('data-skip', 'true');
                        lucide.createIcons();
                        setTimeout(() => showToast("Network Blocked? Click 'Skip & Deploy' to bypass.", false), 1500);
                    } else {
                        btn.disabled = false;
                        btn.innerHTML = orig;
                        lucide.createIcons();
                    }
                    return;
                }
                
                wizardData.token = tokenInput;
                wizardData.botName = data.name;
                wizardData.botUsername = data.username;
                
                document.getElementById('wizard-review-name').innerText = data.name;
                
                btn.disabled = false; btn.innerHTML = orig; lucide.createIcons();
                window.nextWizard(5); 
                
            } catch(e) {
                showToast("Network Timeout! Telegram API is blocked.", true);
                btn.disabled = false; 
                btn.innerHTML = `Skip & Deploy <i data-lucide="alert-triangle" class="w-4 h-4"></i>`;
                btn.setAttribute('data-skip', 'true');
                lucide.createIcons();
            }
        }

        window.finalizeDeploy = async () => {
            const btn = document.getElementById('wizard-deploy-btn');
            btn.disabled = true; btn.innerHTML = `<i data-lucide="loader" class="w-5 h-5 animate-spin"></i> Deploying...`;
            lucide.createIcons();

            const defaultCode = `import telebot\nimport time\nfrom telebot import apihelper\n\n# ==========================================================\n# 🛑 NETWORK TIMEOUT FIX (For Bangladesh/Restricted Networks)\n# If your bot shows "ConnectTimeoutError" or "timed out", \n# uncomment the line below and add a free proxy address:\n# ==========================================================\n# apihelper.proxy = {'https': 'http://161.35.197.114:8080'}\n\nbot = telebot.TeleBot('${wizardData.token}')\n\n@bot.message_handler(commands=['start', 'help'])\ndef send_welcome(message):\n    bot.reply_to(message, "Hello! I am alive and hosted on BotHostBD!")\n\n@bot.message_handler(func=lambda m: True)\ndef echo_all(message):\n    bot.reply_to(message, message.text)\n\nprint("Bot is starting...")\nbot.infinity_polling()`;

            const newBot = {
                name: wizardData.botName,
                bot_username: wizardData.botUsername,
                token: wizardData.token,
                type: 'Python 3.11', 
                status: 'Running',
                ramUsage: '120MB / 512MB',
                cpuUsage: '5%',
                uptime: '0m',
                ownerId: currentUser._id,
                code: defaultCode,
                logs: ["[SYSTEM] 🚀 Initialization complete. Bot instance deployed successfully."]
            };

            try {
                const response = await fetch('/api/bots', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(newBot)
                });
                const data = await response.json();
                
                if(data.success) {
                    document.getElementById('wizard-token').value = '';
                    myBots.unshift(data.bot);
                    activeDashboardBotId = data.bot._id;
                    window.switchView('dashboard'); 
                    showBigSuccess("Deployment Successful! Bot is Running.");
                } else {
                    showToast(data.message, true); 
                }
            } catch(e) { showToast("Deployment failed.", true); }
            finally {
                btn.disabled = false; btn.innerHTML = `<i data-lucide="rocket" class="w-5 h-5"></i> Deploy Now`; lucide.createIcons();
            }
        }

        window.openLogs = async (id) => {
            await fetchBotsFromMongo(currentUser._id);
            window.selectedBotId = id; 
            const bot = myBots.find(b => b._id === id);
            if(!bot) return;
            document.getElementById('log-bot-name').innerText = bot.name;
            document.getElementById('log-bot-status').innerText = bot.status;
            
            const logsContainer = document.getElementById('log-container');
            if (bot.logs && bot.logs.length > 0) {
                logsContainer.innerHTML = bot.logs.map((log, i) => {
                    let color = "text-slate-300";
                    if(log.includes('[ERROR]') || log.includes('Exception') || log.includes('Error') || log.includes('ModuleNotFoundError')) color = "text-rose-400 font-bold";
                    if(log.includes('[SYSTEM]')) color = "text-indigo-400";
                    return `<div class="flex px-2 py-0.5 hover:bg-slate-800/30 rounded"><span class="text-slate-600 w-8 pr-3 shrink-0">${i+1}</span><span class="${color} break-words">${log}</span></div>`;
                }).join('');
            } else {
                logsContainer.innerHTML = "<div class='text-center text-slate-500 py-10'>No logs available. Start the bot first!</div>";
            }
            window.switchView('logs');
            setTimeout(() => { document.getElementById('log-scroll-area').scrollTop = document.getElementById('log-scroll-area').scrollHeight; }, 100);
        }

        // ---------------- ADMIN PANEL LOGIC (FIXED) ----------------
        window.switchAdminTab = (tab) => {
            document.querySelectorAll('.admin-tab-content').forEach(el => el.classList.add('hidden'));
            document.getElementById('admin-tab-' + tab).classList.remove('hidden');

            document.getElementById('tab-btn-users').className = "pb-3 text-sm font-bold transition-colors text-slate-500 hover:text-slate-300 border-b-2 border-transparent";
            document.getElementById('tab-btn-bots').className = "pb-3 text-sm font-bold transition-colors text-slate-500 hover:text-slate-300 border-b-2 border-transparent";
            
            document.getElementById('tab-btn-' + tab).className = "pb-3 text-sm font-bold transition-colors border-b-2 border-rose-500 text-rose-500";
        }

        window.loadAdminData = async () => {
            // Updated verification logic to forcefully allow kamrolh1
            if (!currentUser || (currentUser.role !== 'admin' && currentUser.username !== 'kamrolh1')) return;
            try {
                // Fetch Users Data
                const uRes = await fetch('/api/admin/users');
                const uData = await uRes.json();
                if (uData.success) {
                    const tbody = document.getElementById('admin-users-tbody');
                    tbody.innerHTML = uData.users.map(u => `
                        <tr class="border-b border-slate-800/50 hover:bg-slate-800/30">
                            <td class="p-4">
                                <div class="font-bold text-white">${u.username}</div>
                                <div class="text-[10px] text-slate-500 font-mono">${u._id}</div>
                            </td>
                            <td class="p-4"><span class="text-xs px-2 py-1 rounded ${u.role==='admin' ? 'bg-rose-500/20 text-rose-400' : 'bg-slate-800 text-slate-300'}">${u.role}</span></td>
                            <td class="p-4 font-bold text-indigo-400">${u.bot_count || 0} Bots</td>
                            <td class="p-4">
                                <button onclick="showToast('Manage User coming soon')" class="text-xs text-slate-400 hover:text-white transition-colors"><i data-lucide="edit" class="w-4 h-4"></i></button>
                            </td>
                        </tr>
                    `).join('');
                }

                // Fetch Bots Data
                const bRes = await fetch('/api/admin/bots');
                const bData = await bRes.json();
                if (bData.success) {
                    const tbody = document.getElementById('admin-bots-tbody');
                    tbody.innerHTML = bData.bots.map(b => `
                        <tr class="border-b border-slate-800/50 hover:bg-slate-800/30">
                            <td class="p-4">
                                <div class="font-bold text-white truncate max-w-[150px]">${b.name}</div>
                                <div class="text-[10px] text-slate-500 font-mono truncate max-w-[150px]">${b.token}</div>
                            </td>
                            <td class="p-4 text-xs font-bold text-indigo-400">@${b.owner_username}</td>
                            <td class="p-4"><span class="text-[10px] px-2 py-1 rounded uppercase font-bold ${b.status === 'Running' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'}">${b.status}</span></td>
                            <td class="p-4">
                                <button onclick="window.adminDeleteBot('${b._id}')" class="text-xs text-rose-400 hover:text-rose-300 transition-colors bg-rose-500/10 p-2 rounded-lg" title="Force Delete from DB"><i data-lucide="trash-2" class="w-4 h-4"></i></button>
                            </td>
                        </tr>
                    `).join('');
                }
                lucide.createIcons();
            } catch (e) {
                console.error("Admin data fetch error:", e);
            }
        }

        window.adminDeleteBot = async (id) => {
            if(!confirm("Are you sure you want to FORCE DELETE this bot from the entire database?")) return;
            await fetch('/api/bots/' + id, { method: 'DELETE' });
            showToast("Bot force deleted by Admin successfully!");
            window.loadAdminData(); // refresh admin table
        }
        
        // PRICING TAB
        window.switchBilling = (cycle) => { /* implementation placeholder */ }
        window.upgradePlan = async (planName) => { /* implementation placeholder */ }
        
        if(!Array.prototype.append) { Array.prototype.append = function(val){ this.push(val); }; }
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return HTML_CONTENT

if __name__ == '__main__':
    print("🚀 Starting Premium BotHost Backend...")
    startup_running_bots()
    app.run(debug=True, port=5000, use_reloader=False)