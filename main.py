#!/usr/bin/env python3
import asyncio
import time
import json
import sqlite3
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from playwright.async_api import async_playwright

import avto
import njuskalo
import updates

DB_FILE = "database.db"
UPDATE_INTERVAL = 60 
SLEEP_IDLE = 0.5 # Reduced for testing speed
SLEEP_ACTIVE = 0.1 # Reduced for testing speed

def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS cars (id TEXT PRIMARY KEY, link TEXT, name TEXT, image TEXT, price REAL, year INTEGER, mileage INTEGER, email_sent INTEGER DEFAULT 0, reason TEXT)""")
    cur.execute("CREATE TABLE IF NOT EXISTS car_specs (id TEXT, spec_key TEXT, spec_value TEXT)")
    cur.execute("""CREATE TABLE IF NOT EXISTS njuskalo_cars (id TEXT PRIMARY KEY, link TEXT, name TEXT, image TEXT, price TEXT, year INTEGER, mileage INTEGER, location TEXT, date_published TEXT, email_sent INTEGER DEFAULT 0, reason TEXT)""")
    conn.commit()
    return conn

def load_settings():
    try:
        with open("settings/avto.json", "r") as f: avto_c = json.load(f).get("car_criteria", [])
    except: avto_c = []
    try:
        with open("settings/njuskalo.json", "r") as f: njus_c = json.load(f).get("car_criteria", {})
    except: njus_c = {}
    return avto_c, njus_c

async def avto_loop(page, conn):
    while True:
        try:
            avto_crit, _ = load_settings()
            start_time = time.time()
            result = await avto.scrape_routine(page, conn, avto_crit)
            elapsed = time.time() - start_time
            
            ok, total, new = result if isinstance(result, tuple) else (False, 0, 0)
            icon = "✅" if ok else "❌"
            current_time = datetime.now().strftime('%H:%M:%S')
            
            log = f"[{current_time}] 🏎️  Avto {icon} | {elapsed:.2f}s | F:{total} E:{new}"
            print(f"{log:<50}")
            
            await asyncio.sleep(SLEEP_ACTIVE)
        except Exception as e:
            print(f"Avto Loop Error: {e}")
            await asyncio.sleep(SLEEP_IDLE)

async def njus_loop(page, conn):
    while True:
        try:
            _, njus_crit = load_settings()
            start_time = time.time()
            result = await njuskalo.scrape_routine(page, conn, njus_crit)
            elapsed = time.time() - start_time
            
            ok, total, new = result if isinstance(result, tuple) else (False, 0, 0)
            icon = "✅" if ok else "❌"
            current_time = datetime.now().strftime('%H:%M:%S')
            
            log = f"[{current_time}] 🚙 Njuskalo {icon} | {elapsed:.2f}s | F:{total} E:{new}"
            print(f"{' '*50}{log}")
            
            await asyncio.sleep(SLEEP_ACTIVE)
        except Exception as e:
            print(f"Njuskalo Loop Error: {e}")
            await asyncio.sleep(SLEEP_IDLE)

async def background_updates():
    executor = ThreadPoolExecutor(max_workers=1)
    while True:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(executor, updates.sync_data)
            await asyncio.sleep(UPDATE_INTERVAL)
        except Exception as e:
            print(f"Background Update Error: {e}")
            await asyncio.sleep(5)

async def run_browser_session():
    conn = init_db()
    
    print("🚀 Launching High-Performance Browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--disable-extensions", "--blink-settings=imagesEnabled=false"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
        await context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media", "websocket", "manifest"] else route.continue_())

        page_avto = await context.new_page()
        page_njus = await context.new_page()
        
        print("✅ Browser Ready. Starting Independent Live Fetching...")
        print(f"{'--- AVTO.NET ---':<50}{'--- NJUSKALO.HR ---'}")
        
        await asyncio.gather(
            avto_loop(page_avto, conn),
            njus_loop(page_njus, conn),
            background_updates(),
            return_exceptions=True
        )

async def main():
    while True:
        try:
            await run_browser_session()
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"💥 Browser Crash: {e}. Restarting...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())