#!/usr/bin/env python3
import asyncio
import time
import json
import sqlite3
import traceback
import sys
import builtins
import random
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from playwright.async_api import async_playwright

import avto
import njuskalo
import updates

DB_FILE = "database.db"
UPDATE_INTERVAL = 60 
SLEEP_IDLE = 0.5 
SLEEP_ACTIVE = 0.1 

# Global Status State for Heartbeat TUI
STATUS_STATE = {
    "avto_status": "starting",
    "avto_cycles": 0,
    "njus_status": "starting",
    "njus_cycles": 0
}

original_print = builtins.print

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
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

def update_heartbeat():
    current_time = datetime.now().strftime('%H:%M:%S')
    avto_str = f"Avto: {STATUS_STATE['avto_status']} (C:{STATUS_STATE['avto_cycles']})"
    njus_str = f"Njuskalo: {STATUS_STATE['njus_status']} (C:{STATUS_STATE['njus_cycles']})"
    sys.stdout.write(f"\r[{current_time}] 🔍 {avto_str} | {njus_str}                   ")
    sys.stdout.flush()

class DashboardPrint:
    def __init__(self, original_print_func):
        self.orig = original_print_func
        
    def __call__(self, *args, **kwargs):
        # Clear heartbeat line
        sys.stdout.write("\r" + " " * 110 + "\r")
        sys.stdout.flush()
        
        # Print normal output
        self.orig(*args, **kwargs)
        
        # Restore heartbeat line
        update_heartbeat()

# Hijack print to keep heartbeat at the bottom
builtins.print = DashboardPrint(original_print)

async def avto_loop(page):
    conn = init_db()
    while True:
        try:
            avto_crit, _ = load_settings()
            start_time = time.time()
            
            STATUS_STATE["avto_status"] = "fetching"
            update_heartbeat()
            
            await avto.scrape_routine(page, conn, avto_crit)
            elapsed = time.time() - start_time
            
            STATUS_STATE["avto_cycles"] += 1
            STATUS_STATE["avto_status"] = f"idle ({elapsed:.1f}s)"
            update_heartbeat()
            
            if STATUS_STATE["avto_cycles"] % 5 == 0:
                gap = random.uniform(5.0, 10.0)
                STATUS_STATE["avto_status"] = f"cooling ({gap:.1f}s)"
                update_heartbeat()
                await asyncio.sleep(gap)
            else:
                await asyncio.sleep(SLEEP_ACTIVE)
        except Exception as e:
            STATUS_STATE["avto_status"] = f"error"
            update_heartbeat()
            print(f"⚠️ Avto Loop Error: {e}")
            await asyncio.sleep(SLEEP_IDLE)

async def njus_loop(page):
    conn = init_db()
    while True:
        try:
            _, njus_crit = load_settings()
            start_time = time.time()
            
            STATUS_STATE["njus_status"] = "fetching"
            update_heartbeat()
            
            await njuskalo.scrape_routine(page, conn, njus_crit)
            elapsed = time.time() - start_time
            
            STATUS_STATE["njus_cycles"] += 1
            STATUS_STATE["njus_status"] = f"idle ({elapsed:.1f}s)"
            update_heartbeat()
            
            if STATUS_STATE["njus_cycles"] % 5 == 0:
                gap = random.uniform(5.0, 10.0)
                STATUS_STATE["njus_status"] = f"cooling ({gap:.1f}s)"
                update_heartbeat()
                await asyncio.sleep(gap)
            else:
                await asyncio.sleep(SLEEP_ACTIVE)
        except Exception as e:
            STATUS_STATE["njus_status"] = f"error"
            update_heartbeat()
            print(f"⚠️ Njuskalo Loop Error: {e}")
            await asyncio.sleep(SLEEP_IDLE)

async def background_updates():
    executor = ThreadPoolExecutor(max_workers=1)
    while True:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(executor, updates.sync_data)
            await asyncio.sleep(UPDATE_INTERVAL)
        except Exception as e:
            await asyncio.sleep(5)

async def run_browser_session():
    print("🚀 Launching High-Performance Browser...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--disable-extensions", "--blink-settings=imagesEnabled=false"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
        await context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media", "websocket", "manifest"] else route.continue_())

        page_avto = await context.new_page()
        page_njus = await context.new_page()
        
        print("✅ Browser Ready. Starting Independent Live Fetching...")
        
        await asyncio.gather(
            avto_loop(page_avto),
            njus_loop(page_njus),
            background_updates(),
            return_exceptions=True
        )

async def main():
    while True:
        try:
            await run_browser_session()
        except KeyboardInterrupt:
            # Clear heartbeat line on exit so terminal looks clean
            original_print("\r" + " " * 110 + "\r", end="")
            break
        except Exception as e:
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())