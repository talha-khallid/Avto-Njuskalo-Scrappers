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
SLEEP_IDLE = 5.0 
SLEEP_ACTIVE = 0.5 

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

async def run_browser_session():
    conn = init_db()
    executor = ThreadPoolExecutor(max_workers=3)
    
    print("🚀 Launching High-Performance Browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--disable-extensions", "--blink-settings=imagesEnabled=false"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
        await context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font"] else route.continue_())

        page_avto = await context.new_page()
        page_njus = await context.new_page()
        
        print("✅ Browser Ready.")
        avto_crit, njus_crit = load_settings()
        last_update = 0
        
        while True:
            if time.time() - last_update > UPDATE_INTERVAL:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(executor, updates.sync_data)
                avto_crit, njus_crit = load_settings()
                last_update = time.time()

            results = await asyncio.gather(
                avto.scrape_routine(page_avto, conn, avto_crit),
                njuskalo.scrape_routine(page_njus, conn, njus_crit),
                return_exceptions=True
            )
            
            new_avto = results[0] if isinstance(results[0], int) else 0
            new_njus = results[1] if isinstance(results[1], int) else 0
            
            if new_avto + new_njus > 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ Cycle: {new_avto} Avto, {new_njus} Njuskalo")
                await asyncio.sleep(SLEEP_ACTIVE)
            else:
                await asyncio.sleep(SLEEP_IDLE)

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