#!/usr/bin/env python3
import asyncio
import time
import json
import sqlite3
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from playwright.async_api import async_playwright

# Import your modules
import avto
import njuskalo
import updates

# --- CONFIGURATION ---
DB_FILE = "database.db"
UPDATE_INTERVAL = 60  # Check for JSON updates every 60s
SLEEP_IDLE = 5.0      # Wait 5s if no cars found
SLEEP_ACTIVE = 0.5    # Wait 0.5s if cars WERE found (go fast)

def init_db():
    """Initialize the shared database with both tables"""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    
    # 1. Avto Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS cars (
        id TEXT PRIMARY KEY, link TEXT, name TEXT, image TEXT, price REAL,
        year INTEGER, mileage INTEGER, email_sent INTEGER DEFAULT 0, reason TEXT
    )""")
    cur.execute("CREATE TABLE IF NOT EXISTS car_specs (id TEXT, spec_key TEXT, spec_value TEXT)")
    
    # 2. Njuskalo Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS njuskalo_cars (
        id TEXT PRIMARY KEY, link TEXT, name TEXT, image TEXT, price TEXT,
        year INTEGER, mileage INTEGER, location TEXT, date_published TEXT,
        email_sent INTEGER DEFAULT 0, reason TEXT
    )""")
    conn.commit()
    return conn

def load_settings():
    """Load criteria safely from JSON"""
    try:
        with open("settings/avto.json", "r", encoding="utf-8") as f:
            avto_c = json.load(f).get("car_criteria", [])
    except: avto_c = []
    
    try:
        with open("settings/njuskalo.json", "r", encoding="utf-8") as f:
            njus_c = json.load(f).get("car_criteria", {})
    except: njus_c = {}
    
    return avto_c, njus_c

async def run_browser_session():
    """Manages the persistent browser session."""
    conn = init_db()
    executor = ThreadPoolExecutor(max_workers=3) # Helper for sending emails without blocking
    
    print("🚀 Launching High-Performance Browser...")
    
    async with async_playwright() as p:
        # Launch options for speed
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-extensions", "--blink-settings=imagesEnabled=false" 
            ]
        )
        
        # Context with stealth scripts
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US"
        )
        
        # Anti-detection + Resource Blocking
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
        await context.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["image", "stylesheet", "font", "media"] 
            else route.continue_())

        # Open tabs once
        page_avto = await context.new_page()
        page_njus = await context.new_page()
        
        print("✅ Browser Ready. Starting Loops.")
        avto_crit, njus_crit = load_settings()
        last_update = 0
        
        while True:
            cycle_start = time.time()
            
            # 1. Background Settings Update
            if time.time() - last_update > UPDATE_INTERVAL:
                loop = asyncio.get_event_loop()
                # Run sync_data in background thread
                await loop.run_in_executor(executor, updates.sync_data)
                avto_crit, njus_crit = load_settings()
                last_update = time.time()

            # 2. Run Both Scrapers in Parallel
            results = await asyncio.gather(
                avto.scrape_routine(page_avto, conn, avto_crit),
                njuskalo.scrape_routine(page_njus, conn, njus_crit),
                return_exceptions=True
            )
            
            # Handle results
            new_avto = results[0] if isinstance(results[0], int) else 0
            new_njus = results[1] if isinstance(results[1], int) else 0
            total = new_avto + new_njus
            
            if total > 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ Found: {new_avto} Avto, {new_njus} Njuskalo")
                await asyncio.sleep(SLEEP_ACTIVE)
            else:
                await asyncio.sleep(SLEEP_IDLE)

async def main():
    while True:
        try:
            await run_browser_session()
        except KeyboardInterrupt:
            print("\n🛑 Stopped by user.")
            break
        except Exception as e:
            print(f"\n💥 Browser Crash: {e}. Restarting...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())