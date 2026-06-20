#!/usr/bin/env python3
import os
import json
import sqlite3
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

# Use absolute paths relative to the script directory to support WSGI servers like PythonAnywhere
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "settings.db")
SETTINGS_DIR = os.path.join(BASE_DIR, "settings")

def init_settings_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    
    # Migrate existing json files to database if db is empty
    cur.execute("SELECT COUNT(*) FROM settings")
    if cur.fetchone()[0] == 0:
        # Migrate Avto
        avto_path = os.path.join(SETTINGS_DIR, "avto.json")
        if os.path.exists(avto_path):
            try:
                with open(avto_path, "r", encoding="utf-8") as f:
                    data = json.load(f).get("car_criteria", [])
                    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("avto_criteria", json.dumps(data)))
            except: pass
            
        # Migrate Njuskalo
        njus_path = os.path.join(SETTINGS_DIR, "njuskalo.json")
        if os.path.exists(njus_path):
            try:
                with open(njus_path, "r", encoding="utf-8") as f:
                    data = json.load(f).get("car_criteria", {})
                    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("njuskalo_criteria", json.dumps(data)))
            except: pass
            
        # Migrate Email
        email_path = os.path.join(SETTINGS_DIR, "email.json")
        if os.path.exists(email_path):
            try:
                with open(email_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("email_settings", json.dumps(data)))
            except: pass
        conn.commit()
    conn.close()

def get_setting(key, default):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return default

def save_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))
    conn.commit()
    conn.close()
    
    # Write to local JSON files in settings directory
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    if key == "avto_criteria":
        with open(os.path.join(SETTINGS_DIR, "avto.json"), "w", encoding="utf-8") as f:
            json.dump({"car_criteria": value}, f, indent=4, ensure_ascii=False)
    elif key == "njuskalo_criteria":
        with open(os.path.join(SETTINGS_DIR, "njuskalo.json"), "w", encoding="utf-8") as f:
            json.dump({"car_criteria": value}, f, indent=4, ensure_ascii=False)
    elif key == "email_settings":
        with open(os.path.join(SETTINGS_DIR, "email.json"), "w", encoding="utf-8") as f:
            json.dump(value, f, indent=4, ensure_ascii=False)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Control Panel</title>
    <style>
        :root {
            --bg-color: #ffffff;
            --border-color: #e2e8f0;
            --primary: #4f46e5;
            --primary-hover: #4338ca;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --danger: #ef4444;
            --danger-hover: #dc2626;
            --input-bg: #ffffff;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            min-height: 100vh;
            padding: 2rem 1rem;
            display: flex;
            justify-content: center;
        }

        .container {
            width: 100%;
            max-width: 600px;
            display: flex;
            flex-direction: column;
            gap: 2rem;
        }

        header {
            margin-bottom: 0.5rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1rem;
        }

        h1 {
            font-size: 1.6rem;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 0.25rem;
            letter-spacing: -0.5px;
        }

        .subtitle {
            color: var(--text-muted);
            font-size: 0.9rem;
        }

        .settings-form {
            display: flex;
            flex-direction: column;
            gap: 2.5rem;
        }

        .form-section {
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
        }

        h2 {
            font-size: 1.15rem;
            font-weight: 600;
            color: var(--text-main);
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 0.5rem;
            margin-bottom: 0.5rem;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 0.375rem;
        }

        label {
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--text-main);
        }

        input[type="text"],
        input[type="number"],
        input[type="password"],
        input[type="email"] {
            width: 100%;
            padding: 0.625rem 0.85rem;
            background: var(--input-bg);
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            color: var(--text-main);
            font-size: 0.95rem;
            outline: none;
            transition: border-color 0.15s, box-shadow 0.15s;
        }

        input:focus {
            border-color: var(--primary);
            box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.1);
        }

        .row-grid {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 1rem;
        }

        @media (max-width: 600px) {
            body {
                padding: 1rem 0.5rem;
            }
            .container {
                gap: 1.5rem;
            }
            .row-grid {
                grid-template-columns: 1fr;
                gap: 1rem;
            }
            .form-section {
                gap: 1rem;
            }
        }

        .criteria-item {
            border-bottom: 1px dashed var(--border-color);
            padding-bottom: 1.5rem;
            margin-bottom: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
        }

        .criteria-item:last-child {
            border-bottom: none;
            padding-bottom: 0;
            margin-bottom: 0;
        }

        .criteria-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .criteria-title {
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .remove-btn {
            background: transparent;
            border: none;
            color: var(--danger);
            cursor: pointer;
            font-size: 0.85rem;
            font-weight: 500;
        }

        .remove-btn:hover {
            color: var(--danger-hover);
            text-decoration: underline;
        }

        .add-btn {
            background: transparent;
            border: 1px solid #cbd5e1;
            color: var(--text-main);
            width: 100%;
            padding: 0.625rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 500;
            margin-top: 0.5rem;
            transition: background-color 0.15s;
        }

        .add-btn:hover {
            background-color: #f1f5f9;
        }

        .save-btn {
            background: var(--primary);
            color: white;
            border: none;
            width: 100%;
            padding: 0.85rem;
            border-radius: 6px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.15s;
            margin-top: 1.5rem;
        }

        .save-btn:hover {
            background-color: var(--primary-hover);
        }

        #toast {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            background: #10b981;
            color: white;
            padding: 0.85rem 1.5rem;
            border-radius: 6px;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.15);
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-weight: 500;
            font-size: 0.95rem;
            opacity: 0;
            visibility: hidden;
            transform: translateY(1rem);
            transition: transform 0.3s ease-out, opacity 0.3s ease-out, visibility 0.3s;
            z-index: 1000;
        }

        #toast.show {
            opacity: 1;
            visibility: visible;
            transform: translateY(0);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Control Panel</h1>
            <p class="subtitle">Manage search criteria and notification parameters</p>
        </header>

        <form id="settingsForm" class="settings-form">
            
            <!-- AVTO.NET SECTION -->
            <div class="form-section">
                <h2>Avto.net Search Criteria</h2>
                <div id="avto-container">
                    <!-- Dynamic Items loaded here -->
                </div>
                <button type="button" class="add-btn" onclick="addAvtoCriteria()">+ Add New Criteria</button>
            </div>

            <!-- NJUSKALO.HR SECTION -->
            <div class="form-section">
                <h2>Njuskalo.hr Search Criteria</h2>
                <div class="row-grid">
                    <div class="form-group">
                        <label>Minimum Year</label>
                        <input type="number" name="njus_min_year" id="njus_min_year" placeholder="e.g. 2012">
                    </div>
                    <div class="form-group">
                        <label>Maximum Year</label>
                        <input type="number" name="njus_max_year" id="njus_max_year" placeholder="e.g. 2020">
                    </div>
                    <div class="form-group">
                        <label>Maximum Price (€)</label>
                        <input type="number" name="njus_max_price" id="njus_max_price" placeholder="e.g. 10000">
                    </div>
                </div>
            </div>

            <!-- EMAIL SETTINGS SECTION -->
            <div class="form-section">
                <h2>Notification Settings</h2>
                <div class="form-group">
                    <label>Sender Gmail Address</label>
                    <input type="email" name="email_sender" id="email_sender" placeholder="e.g. your_email@gmail.com" required>
                </div>
                <div class="form-group">
                    <label>Gmail App Password</label>
                    <input type="password" name="email_password" id="email_password" placeholder="16-character app password" required>
                </div>
                <div class="form-group">
                    <label>Recipient Emails (comma-separated)</label>
                    <input type="text" name="email_recipients" id="email_recipients" placeholder="recipient1@gmail.com, recipient2@gmail.com" required>
                </div>
            </div>

            <button type="submit" class="save-btn">Save Settings</button>
        </form>
    </div>

    <div id="toast">
        <span id="toast-msg">Settings saved successfully!</span>
    </div>

    <script>
        const initialData = {
            avto: {{ avto_criteria | tojson }},
            njuskalo: {{ njuskalo_criteria | tojson }},
            email: {{ email_settings | tojson }}
        };

        document.addEventListener('DOMContentLoaded', () => {
            // Load Njuskalo
            document.getElementById('njus_min_year').value = initialData.njuskalo.min_year || '';
            document.getElementById('njus_max_year').value = initialData.njuskalo.max_year || '';
            document.getElementById('njus_max_price').value = initialData.njuskalo.max_price || '';

            // Load Email
            document.getElementById('email_sender').value = initialData.email.email_sender || '';
            document.getElementById('email_password').value = initialData.email.email_password || '';
            
            const recps = initialData.email.email_recipients;
            if (Array.isArray(recps)) {
                document.getElementById('email_recipients').value = recps.join(', ');
            } else {
                document.getElementById('email_recipients').value = recps || '';
            }

            // Load Avto items
            const avtoItems = initialData.avto || [];
            avtoItems.forEach(item => {
                addAvtoCriteria(item.name, item.min_year, item.max_year, item.max_mileage);
            });
            if (avtoItems.length === 0) {
                addAvtoCriteria();
            }
        });

        function addAvtoCriteria(name = '', min_year = '', max_year = '', max_mileage = '') {
            const container = document.getElementById('avto-container');
            const index = container.children.length;
            
            const itemHtml = `
                <div class="criteria-item" id="avto-item-${index}">
                    <div class="criteria-header">
                        <span class="criteria-title">Criteria #${index + 1}</span>
                        <button type="button" class="remove-btn" onclick="removeAvtoCriteria(${index})">
                            Remove
                        </button>
                    </div>
                    <div class="form-group">
                        <label>Car Name (substring match)</label>
                        <input type="text" class="avto-name" value="${name}" placeholder="e.g. Clio" required>
                    </div>
                    <div class="row-grid">
                        <div class="form-group">
                            <label>Minimum Year</label>
                            <input type="number" class="avto-min-year" value="${min_year}" placeholder="e.g. 2015">
                        </div>
                        <div class="form-group">
                            <label>Maximum Year</label>
                            <input type="number" class="avto-max-year" value="${max_year}" placeholder="e.g. 2020">
                        </div>
                        <div class="form-group">
                            <label>Maximum Mileage (km)</label>
                            <input type="number" class="avto-max-mileage" value="${max_mileage}" placeholder="e.g. 150000">
                        </div>
                    </div>
                </div>
            `;
            
            container.insertAdjacentHTML('beforeend', itemHtml);
        }

        function removeAvtoCriteria(index) {
            const el = document.getElementById(`avto-item-${index}`);
            if (el) {
                el.remove();
                const container = document.getElementById('avto-container');
                Array.from(container.children).forEach((child, idx) => {
                    child.id = `avto-item-${idx}`;
                    child.querySelector('.criteria-title').textContent = `Criteria #${idx + 1}`;
                    child.querySelector('.remove-btn').setAttribute('onclick', `removeAvtoCriteria(${idx})`);
                });
            }
        }

        document.getElementById('settingsForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const avtoItems = [];
            const container = document.getElementById('avto-container');
            Array.from(container.children).forEach(child => {
                const name = child.querySelector('.avto-name').value.trim();
                const minYear = child.querySelector('.avto-min-year').value;
                const maxYear = child.querySelector('.avto-max-year').value;
                const maxMileage = child.querySelector('.avto-max-mileage').value;
                
                if (name) {
                    avtoItems.push({
                        name: name,
                        min_year: minYear ? parseInt(minYear) : null,
                        max_year: maxYear ? parseInt(maxYear) : null,
                        max_mileage: maxMileage ? parseInt(maxMileage) : null
                    });
                }
            });

            const njusMinYear = document.getElementById('njus_min_year').value;
            const njusMaxYear = document.getElementById('njus_max_year').value;
            const njusMaxPrice = document.getElementById('njus_max_price').value;
            
            const njusCriteria = {
                min_year: njusMinYear ? parseInt(njusMinYear) : null,
                max_year: njusMaxYear ? parseInt(njusMaxYear) : null,
                max_price: njusMaxPrice ? parseInt(njusMaxPrice) : null
            };

            const emailRecipientsRaw = document.getElementById('email_recipients').value;
            const emailRecipients = emailRecipientsRaw
                .split(',')
                .map(email => email.trim())
                .filter(email => email.length > 0);

            const emailSettings = {
                email_sender: document.getElementById('email_sender').value.trim(),
                email_password: document.getElementById('email_password').value,
                email_recipients: emailRecipients
            };

            const payload = {
                avto: avtoItems,
                njuskalo: njusCriteria,
                email: emailSettings
            };

            try {
                const response = await fetch('/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                if (response.ok) {
                    showToast(true, 'Settings saved successfully!');
                } else {
                    showToast(false, 'Error saving settings.');
                }
            } catch (err) {
                showToast(false, 'Connection error.');
            }
        });

        function showToast(isSuccess, msg) {
            const toast = document.getElementById('toast');
            document.getElementById('toast-msg').textContent = msg;
            
            if (isSuccess) {
                toast.style.background = '#10b981';
            } else {
                toast.style.background = '#ef4444';
            }
            
            toast.classList.add('show');
            setTimeout(() => {
                toast.classList.remove('show');
            }, 3000);
        }
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    avto_criteria = get_setting("avto_criteria", [])
    njuskalo_criteria = get_setting("njuskalo_criteria", {})
    email_settings = get_setting("email_settings", {})
    return render_template_string(HTML_TEMPLATE, 
                                  avto_criteria=avto_criteria,
                                  njuskalo_criteria=njuskalo_criteria,
                                  email_settings=email_settings)

@app.route("/save", methods=["POST"])
def save():
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
        
    avto_criteria = data.get("avto", [])
    njuskalo_criteria = data.get("njuskalo", {})
    email_settings = data.get("email", {})
    
    save_setting("avto_criteria", avto_criteria)
    save_setting("njuskalo_criteria", njuskalo_criteria)
    save_setting("email_settings", email_settings)
    
    return jsonify({"success": True})

@app.route("/data/api/", methods=["GET"])
def api():
    avto_criteria = get_setting("avto_criteria", [])
    njuskalo_criteria = get_setting("njuskalo_criteria", {})
    return jsonify({
        "avto": avto_criteria,
        "njuskalo": njuskalo_criteria
    })

# Initialize settings database when loaded/imported (critical for WSGI entry points on PythonAnywhere)
init_settings_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
