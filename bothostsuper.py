from flask import Flask, request, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
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

app = Flask(__name__)

# ==========================================
# MONGODB CONNECTION
# ==========================================
MONGO_URI = "mongodb+srv://kamrolha725_db_user:aass1122@cluster0.wkybonq.mongodb.net/?appName=Cluster0"
try:
    client = MongoClient(MONGO_URI)
    db = client["hostbotsuper_db"]
    users_col = db["users"]
    bots_col = db["bots"]
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
    stop_bot(bot_id)  # Stop any existing instance first
    
    script_path = os.path.join(BOTS_DIR, f"{bot_id}.py")
    log_path = os.path.join(BOTS_DIR, f"{bot_id}.log")
    
    # Write the user code to a physical Python file
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)
        
    # Open log file to capture print statements and errors
    log_file = open(log_path, "w", encoding="utf-8")
    
    try:
        proc = subprocess.Popen(
            [sys.executable, script_path],
            stdout=log_file,
            stderr=subprocess.STDOUT
        )
        active_processes[bot_id] = {'proc': proc, 'log_file': log_file}
        print(f"✅ Bot {bot_id} started successfully. PID: {proc.pid}")
    except Exception as e:
        print(f"❌ Failed to start bot {bot_id}: {e}")
        log_file.write(f"\n[SYSTEM] ❌ CRITICAL ERROR: Failed to launch process. Details: {str(e)}\n")
        log_file.close()

def stop_bot(bot_id):
    """Stops the running bot process."""
    if bot_id in active_processes:
        proc_info = active_processes[bot_id]
        proc = proc_info['proc']
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except:
            proc.kill()
        try:
            proc_info['log_file'].close()
        except:
            pass
        del active_processes[bot_id]
        print(f"🛑 Bot {bot_id} stopped.")

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
    data = request.json
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if users_col.find_one({"username": username}):
        return jsonify({"success": False, "message": "Username already exists!"})
    
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

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    user = users_col.find_one({"username": username, "password": password})
    if user:
        if user.get('is_blocked'):
            return jsonify({"success": False, "message": "Your account has been blocked by Admin."})
        
        if username == 'kamrolh1' and user.get('role') != 'admin':
            users_col.update_one({"_id": user['_id']}, {"$set": {"role": "admin"}})
            user['role'] = 'admin'

        return jsonify({"success": True, "user": serialize_doc(user)})
    else:
        return jsonify({"success": False, "message": "Invalid Username or Password"})

@app.route('/api/users/<user_id>/upgrade', methods=['POST'])
def upgrade_plan(user_id):
    data = request.json
    new_plan = data.get('plan', 'Pro')
    users_col.update_one({"_id": ObjectId(user_id)}, {"$set": {"plan": new_plan}})
    return jsonify({"success": True, "plan": new_plan})


# --- TELEGRAM TOKEN VERIFICATION ---
@app.route('/api/verify_token', methods=['POST'])
def verify_token():
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({"success": False, "message": "Token is required!"})

    token = token.strip()
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
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
        return jsonify({"success": False, "message": "Invalid Bot Token! Please check your token."})
    except urllib.error.URLError as e:
        return jsonify({"success": False, "message": f"Network Error: {str(e.reason)}."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Connection Failed: {str(e)}"})


# --- Normal User Bot Routes ---
@app.route('/api/bots', methods=['GET'])
def get_bots():
    owner_id = request.args.get('ownerId')
    bots = list(bots_col.find({"ownerId": owner_id}))
    bots = bots[::-1]
    
    for bot in bots:
        bot_id_str = str(bot['_id'])
        log_path = os.path.join(BOTS_DIR, f"{bot_id_str}.log")
        
        # Read the real physical log file
        file_logs = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    file_logs = f.read().splitlines()[-100:] # Last 100 lines for UI
            except:
                pass
        
        # Merge System Logs from DB with Live Terminal Logs
        db_logs = bot.get('logs', [])
        bot['logs'] = db_logs + file_logs
    
    return jsonify({"success": True, "bots": [serialize_doc(bot) for bot in bots]})

@app.route('/api/bots', methods=['POST'])
def create_bot():
    bot_data = request.json
    result = bots_col.insert_one(bot_data)
    bot_id = str(result.inserted_id)
    bot_data['_id'] = bot_id
    
    # Start bot immediately if status is Running
    if bot_data.get('status') == 'Running':
        start_bot(bot_id, bot_data.get('code', ''))
        
    return jsonify({"success": True, "bot": bot_data})

@app.route('/api/bots/<bot_id>', methods=['PUT'])
def update_bot(bot_id):
    update_data = request.json
    if '_id' in update_data: del update_data['_id']
    
    # Filter logs to prevent duplicate execution logs saving to database
    if 'logs' in update_data:
        update_data['logs'] = [l for l in update_data['logs'] if isinstance(l, str) and l.startswith('[SYSTEM]')]
    
    bot = bots_col.find_one({"_id": ObjectId(bot_id)})
    new_code = update_data.get('code', bot.get('code', ''))
    
    bots_col.update_one({"_id": ObjectId(bot_id)}, {"$set": update_data})
    
    # Control the process based on explicit status updates
    if 'status' in update_data:
        if update_data['status'] == 'Running':
            start_bot(bot_id, new_code)
        else:
            stop_bot(bot_id)
            
    return jsonify({"success": True})

@app.route('/api/bots/<bot_id>', methods=['DELETE'])
def delete_bot(bot_id):
    stop_bot(bot_id) # Stop it physically
    bots_col.delete_one({"_id": ObjectId(bot_id)})
    
    # Clean up physical files
    script_path = os.path.join(BOTS_DIR, f"{bot_id}.py")
    log_path = os.path.join(BOTS_DIR, f"{bot_id}.log")
    if os.path.exists(script_path): os.remove(script_path)
    if os.path.exists(log_path): os.remove(log_path)
    
    return jsonify({"success": True})

@app.route('/api/bots/<bot_id>/install', methods=['POST'])
def install_package(bot_id):
    """API for installing python packages via PIP"""
    pkg = request.json.get('package')
    if not pkg: 
        return jsonify({"success": False, "message": "No package specified"})
    
    # User types "telebot" but the actual library is "pyTelegramBotAPI"
    if pkg.lower() == "telebot":
        pkg = "pyTelegramBotAPI"
        
    try:
        # Run pip install securely and capture output
        result = subprocess.run([sys.executable, "-m", "pip", "install", pkg], capture_output=True, text=True)
        
        if result.returncode == 0:
            # Log to the DB system log
            bots_col.update_one({"_id": ObjectId(bot_id)}, {"$push": {"logs": f"[SYSTEM] 📦 Package installation successful: {pkg}"}})
            return jsonify({"success": True, "output": result.stdout})
        else:
            return jsonify({"success": False, "message": result.stderr})
            
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

# --- SUPER ADMIN ROUTES ---
@app.route('/api/admin/users', methods=['GET'])
def admin_get_users():
    users = list(users_col.find({}, {"password": 0}))
    for u in users:
        u['bot_count'] = bots_col.count_documents({"ownerId": str(u['_id'])})
    return jsonify({"success": True, "users": [serialize_doc(u) for u in users]})

@app.route('/api/admin/users/<user_id>', methods=['PUT'])
def admin_update_user(user_id):
    update_data = request.json
    users_col.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
    return jsonify({"success": True})

@app.route('/api/admin/bots', methods=['GET'])
def admin_get_all_bots():
    bots = list(bots_col.find())
    for b in bots:
        owner = users_col.find_one({"_id": ObjectId(b['ownerId'])})
        b['owner_username'] = owner['username'] if owner else 'Unknown'
    return jsonify({"success": True, "bots": [serialize_doc(bot) for bot in bots]})

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
    <title>BotHostBD - Premium Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background-color: #0b0f19; }
        .hide-scroll::-webkit-scrollbar { display: none; }
        .hide-scroll { -ms-overflow-style: none; scrollbar-width: none; }
        .tab-active { border-bottom: 2px solid #22c55e; color: #22c55e; }
        .tab-inactive { color: #94a3b8; }
        .tab-inactive:hover { color: #f1f5f9; }
        
        /* Stepper CSS */
        .step-circle { width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; transition: all 0.3s ease; z-index: 10;}
        .step-active { background: #3b82f6; color: white; box-shadow: 0 0 15px rgba(59, 130, 246, 0.5); }
        .step-completed { background: #1e293b; color: #94a3b8; border: 1px solid #334155; }
        .step-inactive { background: #111827; color: #475569; border: 1px solid #1f2937; }
        .step-line { position: absolute; top: 20px; left: 0; width: 100%; height: 2px; background: #1e293b; z-index: 0; }
        
        .gradient-btn { background: linear-gradient(to right, #a855f7, #ec4899); box-shadow: 0 4px 15px rgba(236, 72, 153, 0.3); transition: all 0.3s; }
        .gradient-btn:hover { box-shadow: 0 6px 20px rgba(236, 72, 153, 0.5); transform: translateY(-1px); }
        
        .gradient-text { background: linear-gradient(to right, #818cf8, #e879f9); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        
        /* Premium Editor Scrollbar */
        .editor-scroll::-webkit-scrollbar { width: 6px; height: 6px; }
        .editor-scroll::-webkit-scrollbar-track { background: transparent; }
        .editor-scroll::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 10px; }
        .editor-scroll::-webkit-scrollbar-thumb:hover { background: #334155; }
    </style>
</head>
<body class="text-slate-200 font-sans selection:bg-blue-500/30 overflow-hidden">

    <!-- BIG SUCCESS OVERLAY -->
    <div id="big-success-overlay" class="fixed inset-0 z-[100] flex items-center justify-center bg-[#050810]/80 backdrop-blur-md opacity-0 pointer-events-none transition-all duration-500">
        <div class="bg-gradient-to-b from-green-900/50 to-slate-900 border border-green-500/50 p-10 rounded-3xl shadow-[0_0_100px_rgba(34,197,94,0.3)] text-center transform scale-75 transition-transform duration-500 max-w-sm w-full" id="big-success-content">
            <div class="w-24 h-24 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-6 border-4 border-green-500 shadow-[0_0_30px_rgba(34,197,94,0.5)]">
                <i data-lucide="check-circle" class="w-12 h-12 text-green-400"></i>
            </div>
            <h2 class="text-3xl font-extrabold text-white mb-2">SUCCESS!</h2>
            <p id="big-success-msg" class="text-green-400 text-sm font-medium">Operation completed successfully.</p>
            <button onclick="document.getElementById('big-success-overlay').classList.add('opacity-0', 'pointer-events-none'); document.getElementById('big-success-content').classList.replace('scale-100', 'scale-75');" class="mt-8 px-8 py-3 w-full bg-green-600 hover:bg-green-500 text-white rounded-xl font-bold transition-colors shadow-lg">Awesome!</button>
        </div>
    </div>

    <div class="flex h-screen w-full relative">
        <!-- Sidebar (Wider & More Premium) -->
        <div class="w-72 bg-gradient-to-b from-[#0f172a] to-[#0b0f19] border-r border-slate-800/80 flex flex-col hidden md:flex shrink-0 z-20 shadow-[4px_0_24px_rgba(0,0,0,0.4)]">
            
            <!-- Premium Logo Section -->
            <div class="p-6 md:p-8 flex items-center gap-4 border-b border-slate-800/80 relative overflow-hidden">
                <div class="absolute top-1/2 left-10 -translate-y-1/2 w-20 h-20 bg-blue-500/20 blur-3xl rounded-full pointer-events-none"></div>
                <div class="w-12 h-12 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-xl flex items-center justify-center shadow-[0_0_20px_rgba(79,70,229,0.4)] relative z-10 shrink-0">
                    <i data-lucide="bot" class="text-white w-7 h-7"></i>
                </div>
                <h1 class="text-3xl font-black tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-400 relative z-10 drop-shadow-sm">BotHost<span class="text-white">BD</span></h1>
            </div>

            <!-- Navigation Links -->
            <nav class="flex-1 py-8 px-4 space-y-3 overflow-y-auto hide-scroll">
                <button onclick="window.switchView('dashboard')" id="nav-dashboard" class="nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[15px] font-bold transition-all duration-300 bg-gradient-to-r from-blue-600/20 to-indigo-600/5 border-l-4 border-blue-500 text-blue-400 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05)]">
                    <i data-lucide="layout-grid" class="w-5 h-5"></i> Manage Your Bots
                </button>
                <button onclick="window.switchView('create')" id="nav-create" class="nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[15px] font-medium transition-all duration-300 text-slate-400 hover:bg-slate-800/80 hover:text-white hover:pl-6 border-l-4 border-transparent hover:border-slate-600">
                    <i data-lucide="rocket" class="w-5 h-5"></i> Deploy New Bot
                </button>
                <button onclick="window.switchView('pricing')" id="nav-pricing" class="nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[15px] font-medium transition-all duration-300 text-slate-400 hover:bg-slate-800/80 hover:text-white hover:pl-6 border-l-4 border-transparent hover:border-slate-600">
                    <i data-lucide="credit-card" class="w-5 h-5"></i> Plans & Pricing
                </button>
                
                <div id="nav-admin-section" class="hidden">
                    <div class="pt-8 pb-4 relative">
                        <div class="absolute inset-0 bg-gradient-to-r from-red-500/10 to-transparent opacity-50 blur-xl pointer-events-none"></div>
                        <p class="text-[11px] font-black text-red-500 uppercase tracking-[0.25em] px-4 flex items-center gap-2 drop-shadow-[0_0_8px_rgba(239,68,68,0.5)] relative z-10">
                            <i data-lucide="shield-alert" class="w-4 h-4"></i> Super Admin
                        </p>
                    </div>
                    <button onclick="window.switchView('superadmin')" id="nav-superadmin" class="nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[15px] font-medium transition-all duration-300 text-slate-400 hover:bg-slate-800/80 hover:text-white hover:pl-6 border-l-4 border-transparent hover:border-red-500/50">
                        <i data-lucide="layout-dashboard" class="w-5 h-5"></i> Admin Panel
                    </button>
                </div>
            </nav>

            <!-- User Profile Bottom Area -->
            <div class="p-4 border-t border-slate-800/80 bg-slate-900/50">
                <div class="flex items-center justify-between px-4 py-3 rounded-2xl bg-[#0b0f19] border border-slate-800/80 shadow-inner group hover:border-slate-600 transition-colors">
                    <div class="flex items-center gap-3">
                        <div id="sidebar-user-initial" class="w-10 h-10 rounded-xl bg-gradient-to-br from-slate-700 to-slate-800 flex items-center justify-center text-lg font-black text-white uppercase shadow-lg border border-slate-600/50">U</div>
                        <div class="overflow-hidden">
                            <p id="sidebar-user-name" class="text-[15px] font-bold text-white truncate max-w-[110px] group-hover:text-blue-400 transition-colors">Guest</p>
                            <p id="sidebar-user-role" class="text-[10px] font-black text-blue-500 uppercase tracking-widest">Free Plan</p>
                        </div>
                    </div>
                    <button onclick="window.handleLogout()" class="text-slate-500 hover:text-red-400 transition-colors p-2 hover:bg-red-500/10 rounded-xl" title="Logout">
                        <i data-lucide="log-out" class="w-5 h-5"></i>
                    </button>
                </div>
            </div>
        </div>

        <!-- Main Content -->
        <div class="flex-1 flex flex-col overflow-hidden relative w-full bg-[#0b0f19]">
            <header id="main-header" class="h-16 border-b border-slate-800/80 flex items-center justify-between px-4 md:px-8 bg-[#0f172a]/80 backdrop-blur-md z-10 shrink-0">
                <h2 id="header-title" class="text-base md:text-lg font-medium text-white">Bot Command Center</h2>
                <div class="flex items-center gap-4">
                    <span id="db-status-badge" class="flex items-center gap-2 text-xs md:text-sm text-green-400 bg-green-500/10 px-3 py-1.5 rounded-full border border-green-500/20">
                        <span class="relative flex h-2 w-2">
                          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                          <span class="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                        </span>
                        System Online
                    </span>
                    <button class="md:hidden text-slate-400 hover:text-white"><i data-lucide="menu"></i></button>
                </div>
            </header>

            <main class="flex-1 overflow-y-auto p-4 md:p-8" id="main-content">
                
                <!-- NEW PREMIUM DASHBOARD VIEW (MASTER-DETAIL) -->
                <div id="view-dashboard" class="view-section space-y-6 block h-full flex flex-col">
                    
                    <!-- Header Top Area -->
                    <div class="flex flex-col md:flex-row justify-between items-start md:items-end shrink-0 gap-4">
                        <div>
                            <h2 class="text-2xl md:text-3xl font-extrabold text-white mb-2">Manage Your Bots</h2>
                            <p class="text-sm text-slate-400">Full control and customization of your Telegram bots.</p>
                        </div>
                        <button onclick="window.switchView('create')" class="bg-white text-slate-900 hover:bg-slate-200 px-6 py-2.5 rounded-xl font-bold flex items-center gap-2 transition-all shadow-[0_0_20px_rgba(255,255,255,0.1)]">
                            <i data-lucide="plus" class="w-5 h-5"></i> Create New Bot
                        </button>
                    </div>

                    <!-- Empty State -->
                    <div id="dashboard-empty-state" class="hidden flex flex-col items-center justify-center flex-1 bg-[#0f172a]/50 border border-slate-800 border-dashed rounded-3xl min-h-[400px]">
                        <div class="w-20 h-20 bg-slate-800/50 rounded-full flex items-center justify-center mb-6 text-slate-500 shadow-inner">
                            <i data-lucide="bot" class="w-10 h-10"></i>
                        </div>
                        <h4 class="text-xl font-bold text-white mb-2">কোনো বট নেই</h4>
                        <p class="text-sm text-slate-400 mb-8 text-center max-w-sm">নতুন বট তৈরি করে আপনার হোস্টিং যাত্রা শুরু করুন।</p>
                        <button onclick="window.switchView('create')" class="gradient-btn text-white px-8 py-3 rounded-full font-bold shadow-lg">
                            Deploy First Bot
                        </button>
                    </div>

                    <!-- Layout: Left List & Right Details -->
                    <div id="dashboard-content" class="flex-1 flex flex-col lg:flex-row gap-6 min-h-0 hidden pb-4">
                        
                        <!-- LEFT COLUMN: Bot List -->
                        <div class="w-full lg:w-1/3 flex flex-col gap-3 overflow-y-auto editor-scroll pr-1" id="dashboard-bot-list">
                            <!-- Populated by JS -->
                        </div>

                        <!-- RIGHT COLUMN: Selected Bot Details -->
                        <div class="w-full lg:w-2/3 bg-[#0f172a] border border-slate-800 rounded-3xl p-6 md:p-8 shadow-2xl flex flex-col overflow-y-auto editor-scroll relative" id="dashboard-bot-details">
                            <!-- Populated by JS -->
                        </div>

                    </div>
                </div>

                <!-- CREATE BOT WIZARD VIEW -->
                <div id="view-create" class="view-section hidden max-w-4xl mx-auto py-4">
                    <!-- Header -->
                    <div class="text-center mb-12">
                        <h2 class="text-4xl font-extrabold text-white mb-3">Create Your Bot <span class="text-2xl">🚀</span></h2>
                        <p class="text-slate-400 text-sm">Follow the steps to deploy your bot in minutes</p>
                    </div>

                    <!-- Stepper -->
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

                    <!-- Wizard Content Box -->
                    <div class="bg-[#0f172a] border border-slate-800 rounded-3xl p-6 md:p-10 shadow-2xl relative overflow-hidden">
                        <!-- Step 1: Platform -->
                        <div id="wizard-step-1" class="wizard-step block">
                            <h3 class="text-xl font-extrabold text-white mb-6 text-center">Choose Bot Platform</h3>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
                                <div class="border border-blue-500 bg-blue-500/5 rounded-2xl p-6 cursor-pointer relative transition-all hover:bg-blue-500/10">
                                    <div class="absolute top-4 right-4 text-blue-500"><i data-lucide="check-circle" class="fill-current w-6 h-6"></i></div>
                                    <h4 class="text-lg font-bold text-white mb-2">Telegram Bot</h4>
                                    <p class="text-sm text-slate-400">Create interactive bots for Telegram</p>
                                </div>
                                <div class="border border-slate-800 bg-slate-900/50 rounded-2xl p-6 opacity-60 cursor-not-allowed relative">
                                    <h4 class="text-lg font-bold text-white mb-2">Discord Bot</h4>
                                    <p class="text-sm text-slate-500">Coming Soon</p>
                                </div>
                            </div>
                            <div class="flex justify-end mt-10">
                                <button onclick="window.nextWizard(2)" class="gradient-btn text-white px-8 py-3 rounded-full font-bold flex items-center gap-2">Next <i data-lucide="arrow-right" class="w-4 h-4"></i></button>
                            </div>
                        </div>

                        <!-- Step 2: Language -->
                        <div id="wizard-step-2" class="wizard-step hidden">
                            <h3 class="text-xl font-extrabold text-white mb-6 text-center">Select Language</h3>
                            <div class="grid grid-cols-1 gap-5 max-w-lg mx-auto">
                                <div class="border border-blue-500 bg-blue-500/5 rounded-2xl p-6 cursor-pointer relative">
                                    <div class="absolute top-4 right-4 text-blue-500"><i data-lucide="check-circle" class="fill-current w-6 h-6"></i></div>
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
                                <button onclick="window.nextWizard(1)" class="text-slate-400 hover:text-white px-6 py-3 rounded-full font-bold flex items-center gap-2 transition-colors"><i data-lucide="arrow-left" class="w-4 h-4"></i> Back</button>
                                <button onclick="window.nextWizard(3)" class="gradient-btn text-white px-8 py-3 rounded-full font-bold flex items-center gap-2">Next <i data-lucide="arrow-right" class="w-4 h-4"></i></button>
                            </div>
                        </div>

                        <!-- Step 3: Source -->
                        <div id="wizard-step-3" class="wizard-step hidden">
                            <h3 class="text-xl font-extrabold text-white mb-6 text-center">Choose Source Code</h3>
                            <div class="grid grid-cols-1 gap-5 max-w-lg mx-auto">
                                <div class="border border-blue-500 bg-blue-500/5 rounded-2xl p-6 cursor-pointer relative">
                                    <div class="absolute top-4 right-4 text-blue-500"><i data-lucide="check-circle" class="fill-current w-6 h-6"></i></div>
                                    <h4 class="text-lg font-bold text-white mb-1 flex items-center gap-2"><i data-lucide="file-code-2" class="w-5 h-5 text-blue-400"></i> Template</h4>
                                    <p class="text-sm text-slate-400">Start with "Create Your First Bot" template</p>
                                </div>
                            </div>
                            <div class="flex justify-between mt-10">
                                <button onclick="window.nextWizard(2)" class="text-slate-400 hover:text-white px-6 py-3 rounded-full font-bold flex items-center gap-2 transition-colors"><i data-lucide="arrow-left" class="w-4 h-4"></i> Back</button>
                                <button onclick="window.nextWizard(4)" class="gradient-btn text-white px-8 py-3 rounded-full font-bold flex items-center gap-2">Next <i data-lucide="arrow-right" class="w-4 h-4"></i></button>
                            </div>
                        </div>

                        <!-- Step 4: Config -->
                        <div id="wizard-step-4" class="wizard-step hidden">
                            <h3 class="text-xl font-extrabold text-white mb-6 text-center">Bot Configuration</h3>
                            <div class="max-w-lg mx-auto space-y-6">
                                <div class="space-y-2">
                                    <label class="text-sm font-bold text-slate-300 ml-1">Bot Token (from @BotFather)</label>
                                    <input id="wizard-token" type="text" placeholder="e.g. 1234567890:ABCdefGhIJKlmNoPQRsTuvWxyz" class="w-full bg-[#0a0f1c] border border-slate-700 rounded-xl px-5 py-4 text-white focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 font-mono text-sm shadow-inner transition-all"/>
                                </div>
                                <div class="bg-slate-800/50 p-4 rounded-xl border border-slate-700/50 flex items-start gap-3">
                                    <i data-lucide="lightbulb" class="w-5 h-5 text-yellow-400 shrink-0 mt-0.5"></i>
                                    <p class="text-sm text-slate-300 font-medium">Click <span class="text-blue-400">Verify</span> to fetch bot information from Telegram automatically.</p>
                                </div>
                            </div>
                            <div class="flex justify-between mt-10 max-w-lg mx-auto">
                                <button onclick="window.nextWizard(3)" class="text-slate-400 hover:text-white px-6 py-3 rounded-full font-bold flex items-center gap-2 transition-colors"><i data-lucide="arrow-left" class="w-4 h-4"></i> Back</button>
                                <button id="wizard-verify-btn" onclick="window.verifyWizardToken()" class="gradient-btn text-white px-8 py-3 rounded-full font-bold flex items-center gap-2">
                                    Verify <i data-lucide="shield-check" class="w-4 h-4"></i>
                                </button>
                            </div>
                        </div>

                        <!-- Step 5: Deploy -->
                        <div id="wizard-step-5" class="wizard-step hidden">
                            <h3 class="text-xl font-extrabold text-white mb-6 text-center">Review & Deploy</h3>
                            <div class="max-w-lg mx-auto bg-[#0a0f1c] border border-slate-800 rounded-2xl p-6 shadow-inner mb-8">
                                <div class="space-y-4">
                                    <div class="flex justify-between border-b border-slate-800 pb-3">
                                        <span class="text-slate-400 text-sm">Platform</span>
                                        <span class="text-white font-medium text-sm flex items-center gap-1.5"><i data-lucide="bot" class="w-4 h-4 text-blue-400"></i> Telegram</span>
                                    </div>
                                    <div class="flex justify-between border-b border-slate-800 pb-3">
                                        <span class="text-slate-400 text-sm">Language</span>
                                        <span class="text-white font-medium text-sm flex items-center gap-1.5"><i data-lucide="code" class="w-4 h-4 text-yellow-400"></i> Python</span>
                                    </div>
                                    <div class="flex justify-between border-b border-slate-800 pb-3">
                                        <span class="text-slate-400 text-sm">Source Type</span>
                                        <span class="text-white font-medium text-sm">Template: Create Your First Bot</span>
                                    </div>
                                    <div class="flex justify-between items-center pt-1">
                                        <span class="text-slate-400 text-sm">Bot Name</span>
                                        <span id="wizard-review-name" class="text-blue-400 font-bold text-lg">Fetching...</span>
                                    </div>
                                </div>
                            </div>
                            <div class="flex justify-center mt-6">
                                <button id="wizard-deploy-btn" onclick="window.finalizeDeploy()" class="gradient-btn text-white px-10 py-4 rounded-full font-bold text-lg flex items-center gap-2 w-full max-w-md justify-center">
                                    <i data-lucide="rocket" class="w-5 h-5"></i> Deploy Now
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- ULTIMATE BOT CODE EDITOR VIEW -->
                <div id="view-editor" class="view-section hidden h-full flex flex-col -m-4 md:-m-8">
                    <!-- Editor Header Toolbar -->
                    <div class="flex flex-col sm:flex-row justify-between items-center bg-[#0f172a] p-4 border-b border-slate-800 gap-4">
                        <div>
                            <h2 class="text-xl font-bold text-white flex items-center gap-2"><i data-lucide="terminal-square" class="text-blue-500"></i> Ultimate Bot Code Editor</h2>
                            <p class="text-sm text-slate-400 mt-1">Editing: <span id="editor-bot-name" class="text-blue-400 font-bold">Bot Name</span></p>
                        </div>
                        <div class="flex flex-wrap gap-2">
                            <button onclick="window.switchView('dashboard')" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2"><i data-lucide="arrow-left" class="w-4 h-4"></i> Back</button>
                            <button onclick="showToast('Load Template menu opened')" class="px-4 py-2 bg-[#050810] border border-slate-700 hover:border-blue-500 text-slate-300 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"><i data-lucide="download" class="w-4 h-4"></i> Load Code</button>
                            <button onclick="showToast('File upload dialog opened')" class="px-4 py-2 bg-[#050810] border border-slate-700 hover:border-blue-500 text-slate-300 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"><i data-lucide="upload" class="w-4 h-4"></i> Upload File</button>
                            <button id="btn-save-code" onclick="window.saveEditorCode(false)" class="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-bold shadow-[0_0_10px_rgba(37,99,235,0.4)] transition-all flex items-center gap-2"><i data-lucide="save" class="w-4 h-4"></i> Save</button>
                            <button id="btn-save-restart" onclick="window.saveEditorCode(true)" class="px-5 py-2 bg-green-600 hover:bg-green-500 text-white rounded-lg text-sm font-bold shadow-[0_0_10px_rgba(34,197,94,0.4)] transition-all flex items-center gap-2"><i data-lucide="refresh-cw" class="w-4 h-4"></i> Save & Restart</button>
                        </div>
                    </div>

                    <!-- Editor Workspace -->
                    <div class="flex-1 flex flex-col lg:flex-row bg-[#0b0f19] overflow-hidden">
                        
                        <!-- Left: Code Area -->
                        <div class="flex-1 flex flex-col bg-[#050810] border-r border-slate-800">
                            <!-- File Tabs -->
                            <div class="bg-[#0f172a] px-4 pt-3 flex border-b border-slate-800">
                                <div class="bg-[#050810] px-4 py-2 text-sm font-medium text-blue-400 border-t-2 border-blue-500 rounded-t-lg flex items-center gap-2">
                                    <i data-lucide="file-code" class="w-4 h-4"></i> <span id="editor-file-name">main.py</span>
                                </div>
                                <div class="flex-1 flex justify-end items-end pb-2 pr-2 text-xs text-slate-500 font-mono" id="editor-line-count">
                                    Lines: 0
                                </div>
                            </div>
                            
                            <!-- Coding Textarea -->
                            <textarea id="editor-textarea" class="flex-1 w-full bg-transparent text-green-400 font-mono p-5 outline-none resize-none editor-scroll" spellcheck="false" placeholder="Write your Python bot code here..."></textarea>
                            
                            <!-- Footer -->
                            <div class="bg-[#0f172a] px-4 py-2 border-t border-slate-800 text-xs text-slate-500 flex justify-between">
                                <span>Ultimate Bot Code Editor - Direct file access with professional interface</span>
                                <span>UTF-8 • Python</span>
                            </div>
                        </div>

                        <!-- Right: Sidebar (Guide & Logs) -->
                        <div class="w-full lg:w-96 flex flex-col bg-[#0f172a] overflow-hidden">
                            <!-- Quick Guide -->
                            <div class="p-5 border-b border-slate-800 shrink-0">
                                <h4 class="font-bold text-white mb-3 text-sm flex items-center gap-2"><i data-lucide="book-open" class="w-4 h-4 text-blue-400"></i> Quick Edit Guide</h4>
                                <ul class="text-xs text-slate-400 space-y-2">
                                    <li class="flex items-start gap-2"><i data-lucide="search" class="w-3.5 h-3.5 mt-0.5 text-slate-500"></i> Use <kbd class="bg-slate-800 px-1.5 py-0.5 rounded text-white border border-slate-700 text-[10px] mx-1">Ctrl+F</kbd> to find specific code sections.</li>
                                    <li class="flex items-start gap-2"><i data-lucide="save" class="w-3.5 h-3.5 mt-0.5 text-slate-500"></i> All changes are automatically backed up before saving.</li>
                                    <li class="flex items-start gap-2"><i data-lucide="zap" class="w-3.5 h-3.5 mt-0.5 text-slate-500"></i> Use <span class="text-white font-medium">"Save & Restart"</span> to apply changes immediately.</li>
                                </ul>
                            </div>

                            <!-- Live Logs -->
                            <div class="flex-1 flex flex-col min-h-[300px]">
                                <div class="px-4 py-3 border-b border-slate-800 flex justify-between items-center bg-[#1e293b]/50">
                                    <span class="text-sm font-bold text-white flex items-center gap-2"><i data-lucide="activity" class="w-4 h-4 text-green-500"></i> Live Bot Logs</span>
                                    <div class="flex gap-2">
                                        <button onclick="showToast('Auto-scroll toggled')" class="text-slate-400 hover:text-white transition-colors" title="Auto-scroll"><i data-lucide="arrow-down-circle" class="w-4 h-4"></i></button>
                                        <button onclick="showToast('Errors copied to clipboard')" class="text-slate-400 hover:text-white transition-colors" title="Copy Errors"><i data-lucide="copy" class="w-4 h-4"></i></button>
                                        <button onclick="window.openEditor(window.selectedBotId); showToast('Logs Refreshed')" class="text-slate-400 hover:text-white transition-colors" title="Refresh"><i data-lucide="refresh-cw" class="w-4 h-4"></i></button>
                                        <button onclick="document.getElementById('editor-logs-container').innerHTML='<div class=\'text-center text-slate-600 mt-4\'>Logs cleared.</div>'" class="text-slate-400 hover:text-red-400 transition-colors" title="Clear Logs"><i data-lucide="trash" class="w-4 h-4"></i></button>
                                        <button onclick="window.switchView('logs')" class="text-blue-400 hover:text-blue-300 text-[10px] font-bold px-2 py-0.5 border border-blue-500/30 rounded bg-blue-500/10 uppercase tracking-wide">All Logs</button>
                                    </div>
                                </div>
                                <div class="flex text-[11px] font-medium bg-[#0a0f1c] border-b border-slate-800">
                                    <button class="flex-1 py-2 text-slate-300 bg-slate-800/80 border-b-2 border-slate-500">Output Logs <span class="opacity-50">stdout</span></button>
                                    <button class="flex-1 py-2 text-slate-500 hover:text-red-400 transition-colors">Error Logs <span class="opacity-50">stderr</span></button>
                                </div>
                                <div id="editor-logs-container" class="flex-1 p-3 font-mono text-xs overflow-y-auto text-slate-400 space-y-1 bg-[#050810] editor-scroll">
                                    <div class="text-center text-slate-600 mt-8">
                                        <i data-lucide="coffee" class="w-8 h-8 mx-auto mb-2 opacity-50"></i>
                                        No errors logs available yet<br>Start your bot to see logs here
                                    </div>
                                </div>
                                <div class="px-4 py-2 border-t border-slate-800 text-[10px] text-slate-500 flex justify-between bg-[#1e293b]/30 font-medium">
                                    <span>Live terminal output included</span>
                                    <span>Updates on save/refresh</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- PRICING / UPGRADE PLAN VIEW -->
                <div id="view-pricing" class="view-section hidden max-w-6xl mx-auto py-8">
                    <div class="text-center mb-10">
                        <div class="inline-block bg-gradient-to-r from-red-500 via-pink-500 to-purple-500 p-[1px] rounded-full mb-4">
                            <span class="block bg-slate-950 px-4 py-1.5 rounded-full text-sm font-bold text-transparent bg-clip-text bg-gradient-to-r from-red-400 to-purple-400">
                                🎊 New Year Special Offer 🎉
                            </span>
                        </div>
                        <h2 class="text-3xl md:text-4xl font-extrabold text-white mb-3">🎊 Limited Time 2026 Discount 🎉</h2>
                        <p class="text-slate-400">Start free, upgrade as you grow</p>
                        
                        <div class="mt-8 inline-flex items-center bg-slate-900 border border-slate-800 rounded-xl p-1 shadow-inner">
                            <button id="btn-monthly" onclick="window.switchBilling('monthly')" class="px-6 py-2 rounded-lg bg-slate-800 text-white font-medium shadow-sm transition-all">Monthly</button>
                            <button id="btn-semiannual" onclick="window.switchBilling('semiannual')" class="px-6 py-2 rounded-lg text-slate-400 font-medium hover:text-white transition-colors">6 Months</button>
                            <button id="btn-annual" onclick="window.switchBilling('annual')" class="px-6 py-2 rounded-lg text-slate-400 font-medium hover:text-white transition-colors">Annual</button>
                        </div>
                        <p class="text-xs text-green-400 mt-3 font-medium">Choose longer billing cycles for bigger discounts!</p>
                    </div>
                    
                    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 max-w-5xl mx-auto">
                        <!-- Free Plan -->
                        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-8 flex flex-col shadow-lg hover:border-slate-700 transition-colors">
                            <h3 class="text-xl font-medium text-white mb-2">Free</h3>
                            <div class="mb-8"><span class="text-4xl font-bold text-white">৳0</span> <span class="text-slate-400">/ month</span></div>
                            <ul class="space-y-4 mb-8 flex-1 text-sm text-slate-300">
                                <li class="flex items-center gap-3"><i data-lucide="x-circle" class="text-red-500/70 w-5 h-5"></i> <span class="opacity-70">0 Bots</span></li>
                                <li class="flex items-center gap-3"><i data-lucide="x-circle" class="text-red-500/70 w-5 h-5"></i> <span class="opacity-70">No Bot Builder</span></li>
                                <li class="flex items-center gap-3"><i data-lucide="x-circle" class="text-red-500/70 w-5 h-5"></i> <span class="opacity-70">No Code Editor</span></li>
                                <li class="flex items-center gap-3"><i data-lucide="info" class="text-slate-500 w-5 h-5"></i> Limited Access</li>
                            </ul>
                            <button onclick="window.upgradePlan('Free')" class="w-full py-3 rounded-xl bg-slate-800 text-white hover:bg-slate-700 transition-colors font-medium border border-slate-700">
                                Select Free
                            </button>
                        </div>

                        <!-- Pro Plan -->
                        <div class="bg-slate-900 border-2 border-green-500 rounded-2xl p-8 flex flex-col shadow-[0_0_30px_rgba(34,197,94,0.15)] relative transform lg:-translate-y-4">
                            <div class="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-green-500 text-white px-4 py-1 rounded-full text-xs font-bold tracking-wider shadow-lg">RECOMMENDED</div>
                            <h3 class="text-xl font-medium text-white mb-2">Pro</h3>
                            <div class="mb-4">
                                <div id="pro-old-price" class="text-slate-500 line-through mb-1">৳499</div>
                                <div class="text-[10px] font-bold text-red-400 bg-red-500/10 px-2 py-0.5 rounded inline-block mb-2 border border-red-500/20" id="pro-discount-badge">🎊 NEW YEAR OFFER 60% OFF 🎉</div>
                                <div><span id="pro-price" class="text-4xl font-bold text-green-400">৳199</span> <span id="pro-period" class="text-slate-400">/ month</span></div>
                            </div>
                            <ul class="space-y-4 mb-8 flex-1 text-sm text-slate-300">
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-green-500 w-5 h-5"></i> <span class="font-medium text-white">2 Bots</span></li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-green-500 w-5 h-5"></i> Access Files</li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-green-500 w-5 h-5"></i> Code Editor</li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-green-500 w-5 h-5"></i> Package Installation</li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-green-500 w-5 h-5"></i> Full Support</li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-green-500 w-5 h-5"></i> 24/7 Uptime</li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-green-500 w-5 h-5"></i> 99.99% Uptime Guarantee</li>
                            </ul>
                            <button id="upgrade-btn-pro" onclick="window.upgradePlan('Pro')" class="w-full py-3 rounded-xl bg-green-600 hover:bg-green-500 text-white font-bold transition-all shadow-lg shadow-green-600/30 flex justify-center items-center gap-2">
                                Choose Pro
                            </button>
                        </div>

                        <!-- Enterprise Plan -->
                        <div class="bg-slate-900 border border-purple-500/50 rounded-2xl p-8 flex flex-col shadow-lg hover:border-purple-500 transition-colors">
                            <h3 class="text-xl font-medium text-white mb-2">Enterprise</h3>
                            <div class="mb-4">
                                <div id="ent-old-price" class="text-slate-500 line-through mb-1">৳1499</div>
                                <div class="text-[10px] font-bold text-purple-400 bg-purple-500/10 px-2 py-0.5 rounded inline-block mb-2 border border-purple-500/20" id="ent-discount-badge">🎊 NEW YEAR OFFER 67% OFF 🎊</div>
                                <div><span id="ent-price" class="text-4xl font-bold text-purple-400">৳499</span> <span id="ent-period" class="text-slate-400">/ month</span></div>
                            </div>
                            <ul class="space-y-4 mb-8 flex-1 text-sm text-slate-300">
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-purple-500 w-5 h-5"></i> <span class="font-medium text-white">5 Bots</span></li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-purple-500 w-5 h-5"></i> Access Files</li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-purple-500 w-5 h-5"></i> Code Editor</li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-purple-500 w-5 h-5"></i> Package Installation</li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-purple-500 w-5 h-5"></i> Full Support</li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-purple-500 w-5 h-5"></i> 24/7 Uptime</li>
                                <li class="flex items-center gap-3"><i data-lucide="check-circle" class="text-purple-500 w-5 h-5"></i> 99.99% Uptime Guarantee</li>
                                <li class="flex items-center gap-3"><i data-lucide="star" class="text-yellow-500 w-5 h-5 fill-current"></i> Priority Support</li>
                            </ul>
                            <button id="upgrade-btn-enterprise" onclick="window.upgradePlan('Enterprise')" class="w-full py-3 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-bold transition-all shadow-lg shadow-purple-600/30 flex justify-center items-center gap-2">
                                Choose Enterprise
                            </button>
                        </div>
                    </div>
                </div>

                <!-- LOGS VIEW -->
                <div id="view-logs" class="view-section hidden h-full flex flex-col space-y-4">
                    <div class="flex items-center justify-between bg-[#0f172a] border border-slate-800 p-4 rounded-2xl shadow-sm">
                        <div class="flex items-center gap-4">
                            <button onclick="window.switchView('dashboard')" class="text-slate-400 hover:text-white p-1.5 hover:bg-slate-800 rounded-md transition-colors"><i data-lucide="arrow-left" class="w-5 h-5"></i></button>
                            <div>
                                <h3 id="log-bot-name" class="text-lg font-bold text-white leading-tight">Bot Name</h3>
                                <p class="text-xs text-slate-400 mt-0.5" id="log-bot-details">Python • ID: ...</p>
                            </div>
                        </div>
                        <span id="log-bot-status" class="px-3 py-1 rounded-full text-xs font-medium border">Status</span>
                    </div>
                    <div id="log-scroll-area" class="flex-1 bg-[#050810] border border-slate-800 rounded-2xl font-mono text-xs md:text-sm p-5 overflow-y-auto relative shadow-inner min-h-[400px]">
                        <div class="sticky top-0 right-0 flex justify-end pb-2 mb-3 border-b border-slate-800/80 bg-[#050810]/90 backdrop-blur z-10">
                            <button onclick="window.openLogs(window.selectedBotId)" class="mr-2 text-xs text-blue-400 hover:text-white flex items-center gap-1"><i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> Refresh</button>
                            <span class="text-xs text-slate-500 flex items-center gap-1.5"><i data-lucide="terminal" class="w-3.5 h-3.5"></i> Live Server Logs</span>
                        </div>
                        <div id="log-container" class="space-y-1.5 pb-4 leading-relaxed"></div>
                    </div>
                </div>

                <!-- SUPER ADMIN VIEW REMAIN THE SAME -->
                <div id="view-superadmin" class="view-section hidden flex flex-col h-full">
                    <div class="mb-6"><h2 class="text-2xl font-bold text-white flex items-center gap-2"><i data-lucide="shield-check" class="text-red-500"></i> Super Admin Center</h2></div>
                    <div class="flex border-b border-slate-800 mb-6 gap-6">
                        <button onclick="window.switchAdminTab('users')" id="tab-btn-users" class="pb-3 text-sm font-medium transition-colors tab-active">User Management</button>
                        <button onclick="window.switchAdminTab('bots')" id="tab-btn-bots" class="pb-3 text-sm font-medium transition-colors tab-inactive">All Bots</button>
                    </div>
                    <div id="admin-tab-users" class="admin-tab-content block"><div class="bg-[#0f172a] rounded-xl overflow-hidden shadow-lg"><table class="w-full text-left text-sm text-slate-300"><tbody id="admin-users-tbody"></tbody></table></div></div>
                    <div id="admin-tab-bots" class="admin-tab-content hidden"><div class="bg-[#0f172a] rounded-xl overflow-hidden shadow-lg"><table class="w-full text-left text-sm text-slate-300"><tbody id="admin-bots-tbody"></tbody></table></div></div>
                </div>

            </main>
        </div>

        <!-- Authentication Modal -->
        <div id="login-modal" class="fixed inset-0 z-50 flex items-center justify-center bg-[#050810]/90 backdrop-blur-sm p-4 opacity-0 pointer-events-none transition-opacity duration-300">
            <div id="login-content" class="w-full max-w-sm bg-[#0f172a] border border-slate-800 rounded-3xl p-8 shadow-[0_0_50px_rgba(37,99,235,0.1)] relative transform scale-95 translate-y-4 transition-all duration-300">
                <div class="text-center mb-8">
                    <div class="w-16 h-16 bg-blue-500/10 rounded-full flex items-center justify-center mx-auto mb-4 border border-blue-500/20 text-blue-500">
                        <i data-lucide="fingerprint" class="w-8 h-8"></i>
                    </div>
                    <h2 id="auth-title" class="text-2xl font-bold text-white mb-1">Welcome Back</h2>
                </div>
                <form id="auth-form" class="space-y-4" onsubmit="window.handleAuthSubmit(event)">
                    <div class="relative"><div class="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500"><i data-lucide="user" class="w-4 h-4"></i></div><input id="auth-username" type="text" placeholder="Username" class="w-full bg-[#1e293b]/50 border border-slate-700 rounded-xl pl-10 pr-4 py-3 text-sm text-white focus:outline-none focus:border-blue-500 transition-colors" required></div>
                    <div id="email-field" class="relative hidden"><div class="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500"><i data-lucide="mail" class="w-4 h-4"></i></div><input id="auth-email" type="email" placeholder="Email Address" class="w-full bg-[#1e293b]/50 border border-slate-700 rounded-xl pl-10 pr-4 py-3 text-sm text-white focus:outline-none focus:border-blue-500 transition-colors"></div>
                    <div class="relative"><div class="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500"><i data-lucide="key" class="w-4 h-4"></i></div><input id="auth-password" type="password" placeholder="Password" class="w-full bg-[#1e293b]/50 border border-slate-700 rounded-xl pl-10 pr-10 py-3 text-sm text-white focus:outline-none focus:border-blue-500 transition-colors" required minlength="6"></div>
                    <button id="auth-submit-btn" type="submit" class="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 rounded-xl flex items-center justify-center gap-2 transition-all shadow-[0_0_15px_rgba(37,99,235,0.3)] mt-4"><span id="auth-btn-text">Sign In</span> <i data-lucide="arrow-right" class="w-4 h-4"></i></button>
                    <div class="text-center pt-4 mt-6"><a href="#" id="auth-switch-link" onclick="window.toggleAuthMode(event)" class="text-xs text-blue-400 font-medium hover:text-blue-300">Create an account</a></div>
                </form>
            </div>
        </div>
    </div>

    <script>
        let currentUser = null;
        let myBots = [];
        let isSignupMode = false;
        let adminData = { users: [], bots: [], system: {} };
        let activeDashboardBotId = null; // New state for premium layout
        
        // Wizard State
        let wizardData = { token: '', botName: '', botUsername: '' };

        document.addEventListener('DOMContentLoaded', () => {
            lucide.createIcons();
            const savedUser = localStorage.getItem('botHostUser');
            if (savedUser) {
                currentUser = JSON.parse(savedUser);
                applyUserRoleUI();
                fetchBotsFromMongo(currentUser._id);
            } else {
                showModal();
            }
        });

        function showToast(msg, isError = false) {
            const toast = document.createElement('div');
            toast.className = `fixed top-6 right-6 px-4 py-3 rounded-xl shadow-2xl z-[100] text-sm font-bold transition-all duration-300 flex items-center gap-2 border ${isError ? 'bg-[#2a1215] border-red-500/50 text-red-400' : 'bg-[#0f172a] border-blue-500/50 text-blue-400'}`;
            toast.innerHTML = `<i data-lucide="${isError ? 'alert-octagon' : 'check-circle'}" class="w-4 h-4"></i> ${msg}`;
            document.body.appendChild(toast);
            lucide.createIcons();
            setTimeout(() => { toast.classList.add('opacity-0', 'translate-x-8'); setTimeout(() => toast.remove(), 300); }, 3000);
        }

        // BIG SUCCESS OVERLAY FUNCTION
        function showBigSuccess(msg) {
            const overlay = document.getElementById('big-success-overlay');
            const content = document.getElementById('big-success-content');
            document.getElementById('big-success-msg').innerText = msg;
            
            overlay.classList.remove('opacity-0', 'pointer-events-none');
            content.classList.replace('scale-75', 'scale-100');
            lucide.createIcons();
            
            // Auto close after 5 seconds
            setTimeout(() => {
                overlay.classList.add('opacity-0', 'pointer-events-none');
                content.classList.replace('scale-100', 'scale-75');
            }, 5000);
        }

        // ---------------- AUTH ----------------
        window.toggleAuthMode = (e) => {
            if(e) e.preventDefault();
            isSignupMode = !isSignupMode;
            document.getElementById('auth-title').innerText = isSignupMode ? "Create Account" : "Welcome Back";
            document.getElementById('auth-btn-text').innerText = isSignupMode ? "Sign Up" : "Sign In";
            document.getElementById('auth-switch-link').innerText = isSignupMode ? "Sign in instead" : "Create an account";
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
                hideModal();
                applyUserRoleUI();
                fetchBotsFromMongo(currentUser._id);
                document.getElementById('auth-form').reset();
            } catch (err) {
                showToast("Server Connection Error!", true);
                btn.innerHTML = originalHtml; btn.disabled = false;
            }
        }

        window.handleLogout = () => {
            localStorage.removeItem('botHostUser');
            currentUser = null; myBots = []; activeDashboardBotId = null;
            window.switchView('dashboard');
            showModal();
        }

        function applyUserRoleUI() {
            document.getElementById('sidebar-user-name').innerText = currentUser.username;
            document.getElementById('sidebar-user-initial').innerText = currentUser.username.charAt(0);
            if(currentUser.role === 'admin' || currentUser.username === 'kamrolh1') {
                document.getElementById('nav-admin-section').classList.remove('hidden');
                document.getElementById('sidebar-user-role').innerHTML = `<span class="text-red-400 font-bold">SUPER ADMIN</span>`;
            } else {
                document.getElementById('nav-admin-section').classList.add('hidden');
                document.getElementById('sidebar-user-role').innerText = `${currentUser.plan || 'Free'} Plan`;
            }
        }

        // ---------------- VIEW LOGIC ----------------
        window.switchView = (viewName) => {
            document.querySelectorAll('.view-section').forEach(el => el.classList.add('hidden'));
            document.getElementById('view-' + viewName).classList.remove('hidden');
            
            if(viewName === 'create') window.nextWizard(1); // Reset wizard
            if(viewName === 'superadmin') window.loadAdminData();

            // Toggle top header visibility (Hide header in Editor for fullscreen feel)
            const mainHeader = document.getElementById('main-header');
            if(viewName === 'editor') {
                mainHeader.classList.add('hidden');
            } else {
                mainHeader.classList.remove('hidden');
            }

            const titles = { 'dashboard': 'Bot Command Center', 'create': 'Create New Bot', 'logs': 'Server Logs', 'superadmin': 'Super Admin Core', 'pricing': 'Upgrade Plan' };
            if(titles[viewName]) document.getElementById('header-title').innerText = titles[viewName];

            // Update Navigation Button Styles (Premium Effect)
            document.querySelectorAll('.nav-btn').forEach(btn => {
                btn.className = "nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[15px] font-medium transition-all duration-300 text-slate-400 hover:bg-slate-800/80 hover:text-white hover:pl-6 border-l-4 border-transparent hover:border-slate-600";
            });
            const activeBtn = document.getElementById('nav-' + (viewName === 'editor' || viewName === 'logs' ? 'dashboard' : viewName));
            if(activeBtn) {
                if(viewName === 'superadmin') {
                     activeBtn.className = "nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[15px] font-bold transition-all duration-300 bg-gradient-to-r from-red-600/20 to-orange-600/5 border-l-4 border-red-500 text-red-400 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05)]";
                } else {
                     activeBtn.className = "nav-btn w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-[15px] font-bold transition-all duration-300 bg-gradient-to-r from-blue-600/20 to-indigo-600/5 border-l-4 border-blue-500 text-blue-400 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05)]";
                }
            }
        }

        // ---------------- NEW DASHBOARD RENDER LOGIC (PREMIUM MASTER-DETAIL) ----------------
        async function fetchBotsFromMongo(userId) {
            try {
                const response = await fetch('/api/bots?ownerId=' + userId);
                const data = await response.json();
                if(data.success) { 
                    myBots = data.bots; 
                    renderDashboard(); 
                }
            } catch(e) {}
        }

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

            // Select first bot if none selected or selected bot was deleted
            if (!activeDashboardBotId || !myBots.find(b => b._id === activeDashboardBotId)) {
                activeDashboardBotId = myBots[0]._id;
            }

            // Render Left Sidebar List
            listContainer.innerHTML = myBots.map(bot => {
                const isActive = bot._id === activeDashboardBotId;
                const isRunning = bot.status === 'Running';
                return `
                    <div onclick="window.selectDashboardBot('${bot._id}')" class="cursor-pointer transition-all duration-300 p-4 rounded-2xl border ${isActive ? 'bg-blue-600/10 border-blue-500 shadow-[0_0_20px_rgba(37,99,235,0.15)]' : 'bg-[#0f172a] border-slate-800 hover:border-slate-600 hover:bg-slate-800/50'} flex items-center justify-between group">
                        <div class="flex items-center gap-4">
                            <div class="w-12 h-12 rounded-xl flex items-center justify-center shrink-0 ${isRunning ? 'bg-blue-500/20 text-blue-400' : 'bg-slate-800 text-slate-400'}">
                                <i data-lucide="bot" class="w-6 h-6"></i>
                            </div>
                            <div class="overflow-hidden">
                                <h4 class="text-base font-bold text-white mb-0.5 truncate group-hover:text-blue-400 transition-colors">${bot.name}</h4>
                                <div class="flex items-center gap-2">
                                    <span class="flex items-center gap-1.5 text-[11px] uppercase tracking-wider font-bold ${isRunning ? 'text-green-400' : 'text-slate-500'}">
                                        <span class="w-2 h-2 rounded-full ${isRunning ? 'bg-green-500 animate-pulse' : 'bg-slate-600'}"></span>
                                        ${bot.status}
                                    </span>
                                </div>
                            </div>
                        </div>
                        <i data-lucide="chevron-right" class="w-5 h-5 shrink-0 ${isActive ? 'text-blue-500' : 'text-slate-600 group-hover:text-slate-400'}"></i>
                    </div>
                `;
            }).join('');

            // Render Right Details Panel
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
                <!-- Top Bot Identity -->
                <div class="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-slate-800/80 pb-6 mb-8 gap-4">
                    <div class="flex items-center gap-5">
                        <div class="w-16 h-16 shrink-0 rounded-2xl bg-gradient-to-br from-slate-800 to-slate-900 border border-slate-700 flex items-center justify-center relative shadow-lg">
                            ${isRunning ? '<div class="absolute -top-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-[#0f172a] animate-pulse"></div>' : '<div class="absolute -top-1 -right-1 w-4 h-4 bg-slate-500 rounded-full border-2 border-[#0f172a]"></div>'}
                            <i data-lucide="bot" class="w-8 h-8 text-white"></i>
                        </div>
                        <div class="overflow-hidden">
                            <h2 class="text-3xl font-black text-white tracking-tight mb-1 truncate">${bot.name}</h2>
                            <p class="text-sm text-blue-400 font-medium truncate">@${bot.bot_username || 'unknown_bot'}</p>
                        </div>
                    </div>
                    <div class="flex gap-4 shrink-0">
                         <div class="bg-[#050810] px-4 py-2 rounded-xl border border-slate-800 flex flex-col items-end">
                             <span class="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-0.5">CPU Usage</span>
                             <span class="text-sm font-mono font-bold ${isRunning ? 'text-green-400' : 'text-slate-500'}">${bot.cpuUsage || '0%'}</span>
                         </div>
                         <div class="bg-[#050810] px-4 py-2 rounded-xl border border-slate-800 flex flex-col items-end">
                             <span class="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-0.5">RAM Usage</span>
                             <span class="text-sm font-mono font-bold ${isRunning ? 'text-yellow-400' : 'text-slate-500'}">${bot.ramUsage || '0MB'}</span>
                         </div>
                    </div>
                </div>

                <!-- Action Button Grid -->
                <h3 class="text-sm font-bold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2"><i data-lucide="zap" class="w-4 h-4 text-amber-400"></i> Core Actions</h3>
                <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3 mb-10">
                    
                    <!-- Start/Stop/Kill Button -->
                    <button onclick="window.toggleBot('${bot._id}')" class="group relative overflow-hidden rounded-2xl p-4 bg-gradient-to-b ${isRunning ? 'from-red-500/10 to-red-900/10 border-red-500/30 hover:border-red-500 text-red-400 hover:shadow-[0_0_20px_rgba(239,68,68,0.2)]' : 'from-green-500/10 to-green-900/10 border-green-500/30 hover:border-green-500 text-green-400 hover:shadow-[0_0_20px_rgba(34,197,94,0.2)]'} border transition-all flex flex-col items-center justify-center gap-2 lg:col-span-2">
                        <i data-lucide="${isRunning ? 'power' : 'play'}" class="w-8 h-8 transition-transform group-hover:scale-110"></i>
                        <span class="text-sm font-bold">${isRunning ? 'Stop Server' : 'Start Server'}</span>
                    </button>

                    <!-- Restart Button -->
                    <button onclick="window.restartBot('${bot._id}')" class="group relative overflow-hidden rounded-2xl p-4 bg-gradient-to-b from-blue-500/10 to-blue-900/10 border border-blue-500/30 hover:border-blue-500 text-blue-400 transition-all hover:shadow-[0_0_20px_rgba(59,130,246,0.2)] flex flex-col items-center justify-center gap-2" ${!isRunning ? 'disabled style="opacity:0.4; cursor:not-allowed;"' : ''}>
                        <i data-lucide="refresh-cw" class="w-8 h-8 transition-transform group-hover:rotate-180"></i>
                        <span class="text-sm font-bold">Restart</span>
                    </button>

                    <!-- Editor Button -->
                    <button onclick="window.openEditor('${bot._id}')" class="group relative overflow-hidden rounded-2xl p-4 bg-gradient-to-b from-purple-500/10 to-purple-900/10 border border-purple-500/30 hover:border-purple-500 text-purple-400 transition-all hover:shadow-[0_0_20px_rgba(168,85,247,0.2)] flex flex-col items-center justify-center gap-2">
                        <i data-lucide="code-2" class="w-8 h-8 transition-transform group-hover:scale-110"></i>
                        <span class="text-sm font-bold">Editor</span>
                    </button>

                    <!-- Logs Button -->
                    <button onclick="window.openLogs('${bot._id}')" class="group relative overflow-hidden rounded-2xl p-4 bg-gradient-to-b from-slate-500/10 to-slate-800/30 border border-slate-600 hover:border-slate-400 text-slate-300 transition-all hover:shadow-lg flex flex-col items-center justify-center gap-2">
                        <i data-lucide="terminal-square" class="w-8 h-8 transition-transform group-hover:scale-110"></i>
                        <span class="text-sm font-bold">Logs</span>
                    </button>
                </div>

                <div class="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-8">
                    <!-- Dependencies Section -->
                    <div class="bg-[#050810] border border-slate-800 rounded-2xl p-6 flex flex-col">
                        <h3 class="text-lg font-bold text-white mb-1 flex items-center gap-2"><i data-lucide="package-plus" class="w-5 h-5 text-indigo-400"></i> Dependencies</h3>
                        <p class="text-xs text-slate-500 mb-5">Install python packages directly via pip.</p>
                        
                        <div class="mt-auto space-y-3">
                            <input type="text" id="pkg-${bot._id}" placeholder="e.g. aiogram==3.2.0" class="w-full bg-[#0f172a] border border-slate-700 rounded-xl px-4 py-3.5 text-sm text-white focus:outline-none focus:border-indigo-500 transition-colors">
                            <button onclick="window.installPackage('${bot._id}')" class="w-full py-3.5 bg-indigo-600 hover:bg-indigo-500 text-white font-bold rounded-xl shadow-[0_0_20px_rgba(79,70,229,0.3)] transition-all flex justify-center items-center gap-2">
                                Install Package <i data-lucide="arrow-right" class="w-4 h-4"></i>
                            </button>
                        </div>
                    </div>

                    <!-- File Manager / Requirements Section -->
                    <div class="bg-[#050810] border border-slate-800 rounded-2xl p-6 flex flex-col justify-between relative overflow-hidden">
                        <!-- Decorative bg -->
                        <div class="absolute -right-10 -bottom-10 opacity-5 pointer-events-none"><i data-lucide="folder" class="w-48 h-48"></i></div>
                        
                        <div>
                            <h3 class="text-lg font-bold text-white mb-1 flex items-center gap-2"><i data-lucide="folder-kanban" class="w-5 h-5 text-amber-400"></i> File Management</h3>
                            <p class="text-xs text-slate-500 mb-5">Upload requirements.txt or other assets.</p>
                        </div>
                        <div class="space-y-3 mt-auto relative z-10">
                            <div class="border border-slate-700 bg-[#0f172a] rounded-xl flex items-center p-2 gap-2">
                                <button class="px-4 py-2 bg-slate-800 rounded-lg text-xs font-bold text-slate-300 shrink-0">Choose File</button>
                                <span class="text-xs text-slate-500 truncate">No file chosen</span>
                            </div>
                            <button onclick="showToast('File manager coming soon!')" class="w-full py-3.5 bg-slate-800 hover:bg-slate-700 text-white font-bold rounded-xl border border-slate-600 transition-all flex justify-center items-center gap-2 shadow-lg">
                                Open File Manager
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Danger Zone Bottom -->
                <div class="mt-auto pt-6 border-t border-slate-800/80 flex flex-wrap justify-between items-center gap-4">
                    <div class="bg-slate-900 px-3 py-1.5 rounded-md border border-slate-800 flex items-center gap-2">
                        <i data-lucide="fingerprint" class="w-4 h-4 text-slate-500"></i>
                        <span class="text-[10px] font-mono text-slate-400 uppercase tracking-widest">${bot._id}</span>
                    </div>
                    <button onclick="window.deleteBot('${bot._id}')" class="text-xs font-bold text-red-500 hover:text-white bg-red-500/10 hover:bg-red-600 px-5 py-2.5 rounded-xl transition-all border border-red-500/20 hover:border-red-600 hover:shadow-[0_0_15px_rgba(239,68,68,0.4)] flex items-center gap-2">
                        <i data-lucide="trash-2" class="w-4 h-4"></i> Delete Bot Instance
                    </button>
                </div>
            `;
        }

        // Toggle Bot Status
        window.toggleBot = async (id) => {
            const bot = myBots.find(b => b._id === id);
            if(!bot) return;
            const isRunning = bot.status === 'Running';
            bot.status = isRunning ? 'Stopped' : 'Running';
            
            // Add professional logs
            if(!bot.logs) bot.logs = [];
            bot.logs.push(bot.status === 'Running' ? '[SYSTEM] ▶️ Bot server has been started and is now online.' : '[SYSTEM] 🛑 Bot server has been stopped and is currently offline.');

            // Re-render dashboard instantly to show loading/change
            renderDashboard(); 
            
            await fetch('/api/bots/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({status: bot.status, logs: bot.logs}) });
            await fetchBotsFromMongo(currentUser._id); // Fetch fresh data
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
                await fetch('/api/bots/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({status: 'Running', logs: bot.logs}) });
                showToast('Bot Restarted Successfully!');
                await fetchBotsFromMongo(currentUser._id);
            }, 1500);
        }

        // Delete Bot
        window.deleteBot = async (id) => {
            if(!confirm("Are you sure you want to permanently delete this bot?")) return;
            
            // If deleting the active bot, reset the selection
            if(activeDashboardBotId === id) {
                activeDashboardBotId = null;
            }

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
            btn.innerHTML = `<i data-lucide="loader" class="w-5 h-5 animate-spin"></i>`;
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

            // Render mini logs in Editor
            const logsContainer = document.getElementById('editor-logs-container');
            if(bot.logs && bot.logs.length > 0) {
                logsContainer.innerHTML = bot.logs.slice(-50).map(log => {
                    let color = "text-slate-400";
                    if(log.includes('[ERROR]') || log.includes('Exception') || log.includes('Error') || log.includes('ModuleNotFoundError')) color = "text-red-400";
                    if(log.includes('[SUCCESS]')) color = "text-green-400";
                    if(log.includes('[SYSTEM]')) color = "text-blue-400";
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
            updates.logs = bot.logs; // Pass it, the backend will filter properly

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
                    await fetchBotsFromMongo(currentUser._id); // Refresh data and file logs
                }
            } catch (err) {
                showToast("Failed to save code.", true);
            } finally {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
                lucide.createIcons();
                // Update mini logs
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

            for(let i=1; i<=5; i++) {
                const el = document.getElementById(`wizard-step-${i}`);
                if(el) { el.classList.add('hidden'); el.classList.remove('block'); }
                
                const ind = document.getElementById(`step-indicator-${i}`);
                const txt = document.getElementById(`step-text-${i}`);
                if(ind && txt) {
                    if(i === stepNum) {
                        ind.className = "step-circle step-active";
                        txt.className = "text-xs font-bold text-white";
                    } else if (i < stepNum) {
                        ind.className = "step-circle step-completed";
                        ind.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path></svg>`;
                        txt.className = "text-xs font-medium text-blue-400";
                    } else {
                        ind.className = "step-circle step-inactive";
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
                    showToast(data.message || "Invalid Token!", true);
                    btn.disabled = false; btn.innerHTML = orig; lucide.createIcons();
                    return;
                }
                
                wizardData.token = tokenInput;
                wizardData.botName = data.name;
                wizardData.botUsername = data.username;
                
                document.getElementById('wizard-review-name').innerText = data.name;
                
                btn.disabled = false; btn.innerHTML = orig; lucide.createIcons();
                window.nextWizard(5); 
                
            } catch(e) {
                showToast("Network Error during verification.", true);
                btn.disabled = false; btn.innerHTML = orig; lucide.createIcons();
            }
        }

        window.finalizeDeploy = async () => {
            const btn = document.getElementById('wizard-deploy-btn');
            btn.disabled = true; btn.innerHTML = `<i data-lucide="loader" class="w-5 h-5 animate-spin"></i> Deploying...`;
            lucide.createIcons();

            // Setup default code so bot runs instantly
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
                    activeDashboardBotId = data.bot._id; // select the newly created bot
                    window.switchView('dashboard');
                    renderDashboard();
                    showBigSuccess("Deployment Successful! Bot is Running.");
                }
            } catch(e) { showToast("Deployment failed.", true); }
            finally {
                btn.disabled = false; btn.innerHTML = `<i data-lucide="rocket" class="w-5 h-5"></i> Deploy Now`; lucide.createIcons();
            }
        }

        window.openLogs = async (id) => {
            await fetchBotsFromMongo(currentUser._id); // Fetch fresh logs before opening
            window.selectedBotId = id; 
            const bot = myBots.find(b => b._id === id);
            if(!bot) return;
            document.getElementById('log-bot-name').innerText = bot.name;
            document.getElementById('log-bot-status').innerText = bot.status;
            
            const logsContainer = document.getElementById('log-container');
            if (bot.logs && bot.logs.length > 0) {
                logsContainer.innerHTML = bot.logs.map((log, i) => {
                    let color = "text-slate-300";
                    if(log.includes('[ERROR]') || log.includes('Exception') || log.includes('Error') || log.includes('ModuleNotFoundError')) color = "text-red-400 font-bold";
                    if(log.includes('[SYSTEM]')) color = "text-blue-400";
                    return `<div class="flex px-2 py-0.5 hover:bg-slate-800/30 rounded"><span class="text-slate-600 w-8 pr-3 shrink-0">${i+1}</span><span class="${color} break-words">${log}</span></div>`;
                }).join('');
            } else {
                logsContainer.innerHTML = "<div class='text-center text-slate-500 py-10'>No logs available. Start the bot first!</div>";
            }
            window.switchView('logs');
            setTimeout(() => { document.getElementById('log-scroll-area').scrollTop = document.getElementById('log-scroll-area').scrollHeight; }, 100);
        }

        // PRICING TAB & ADMIN TAB
        window.switchBilling = (cycle) => { /* implementation placeholder */ }
        window.upgradePlan = async (planName) => { /* implementation placeholder */ }
        window.switchAdminTab = (tab) => { /* implementation placeholder */ }
        window.loadAdminData = async () => { /* implementation placeholder */ }
        
        function showModal() { document.getElementById('login-modal').classList.remove('opacity-0', 'pointer-events-none'); }
        function hideModal() { document.getElementById('login-modal').classList.add('opacity-0', 'pointer-events-none'); }
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
    startup_running_bots()  # Restore any previously running bots on server start!
    app.run(debug=True, port=5000)