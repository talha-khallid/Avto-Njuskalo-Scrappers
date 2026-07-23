#!/usr/bin/env python3
import asyncio
import time
import json
import sqlite3
import traceback
import sys
import os
import threading
import builtins
import random
from datetime import datetime
from urllib.parse import urlparse, unquote
from concurrent.futures import ThreadPoolExecutor
from playwright.async_api import async_playwright

import avto
import njuskalo
import updates

# Force UTF-8 stdout and enable ANSI/VT escapes so the live dashboard renders
# cleanly instead of turning into mojibake ("�") on Windows consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
if os.name == "nt":
    # Enables ANSI escape processing (VT mode) in the Windows console.
    os.system("")

# Single lock guarding ALL writes to stdout. The scrape loops run in the asyncio
# thread while updates.sync_data() prints from a ThreadPoolExecutor thread — without
# this they interleave and tear the dashboard line. RLock so DashboardPrint can call
# update_heartbeat() while already holding it.
_print_lock = threading.RLock()

DB_FILE = "database.db"
UPDATE_INTERVAL = 60
SLEEP_IDLE = 0.5
SLEEP_ACTIVE = 0.1

# --- Anti-captcha / session recycling ---
# How many consecutive captcha blocks before we throw away the browser and
# relaunch a fresh one (fresh cookies + fresh TLS/HTTP fingerprint).
CAPTCHA_RESTART_THRESHOLD = 3
# Hard cap: relaunch the browser every N seconds no matter what, so a session
# never lives long enough to accumulate bot-detection heat. (0 disables.)
SESSION_MAX_AGE = 1200  # 20 minutes
# When blocked, back off this long before retrying (escalates per consecutive block).
CAPTCHA_BACKOFF_BASE = 20.0
CAPTCHA_BACKOFF_MAX = 90.0

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

def _proxy_from_url(raw):
    """Turn 'http://user:pass@host:port' (or 'host:port') into a Playwright proxy dict."""
    raw = raw.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if not parsed.hostname:
        return None
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    proxy = {"server": server}
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return proxy

def load_proxy():
    """
    Load a proxy for the browser, giving each fresh session a rotating exit IP.
    Precedence:
      1. env var  SCRAPER_PROXY = "http://user:pass@host:port"
      2. settings/proxy.json  ({"enabled": true, "url": "..."} OR explicit
         {"server","username","password"} fields)
    Returns a Playwright proxy dict, or None if not configured.
    """
    raw = os.environ.get("SCRAPER_PROXY", "").strip()
    if raw:
        return _proxy_from_url(raw)
    try:
        with open("settings/proxy.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"⚠️ Could not read settings/proxy.json: {e}")
        return None

    if not cfg.get("enabled", True):
        return None
    if cfg.get("url"):
        return _proxy_from_url(cfg["url"])
    if cfg.get("server"):
        proxy = {"server": cfg["server"]}
        if cfg.get("username"): proxy["username"] = cfg["username"]
        if cfg.get("password"): proxy["password"] = cfg["password"]
        return proxy
    return None

# "\r\033[2K" = carriage-return + ANSI "erase entire line". Clears whatever was
# there regardless of length, so long status strings never leave trailing garbage.
CLEAR_LINE = "\r\033[2K"

def update_heartbeat():
    current_time = datetime.now().strftime('%H:%M:%S')
    avto_str = f"Avto: {STATUS_STATE['avto_status']} (C:{STATUS_STATE['avto_cycles']})"
    njus_str = f"Njuskalo: {STATUS_STATE['njus_status']} (C:{STATUS_STATE['njus_cycles']})"
    # ASCII-only status line so it can never mojibake on any console.
    line = f"[{current_time}] {avto_str} | {njus_str}"
    with _print_lock:
        sys.stdout.write(CLEAR_LINE + line)
        sys.stdout.flush()

class DashboardPrint:
    def __init__(self, original_print_func):
        self.orig = original_print_func

    def __call__(self, *args, **kwargs):
        # Hold the lock across the whole clear+print+redraw so a print from the
        # background-updates thread can't tear the heartbeat line.
        with _print_lock:
            sys.stdout.write(CLEAR_LINE)
            sys.stdout.flush()
            self.orig(*args, **kwargs)
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
            
            success, _total, _new = await avto.scrape_routine(page, conn, avto_crit)
            elapsed = time.time() - start_time

            STATUS_STATE["avto_cycles"] += 1

            # success is False when avto.net returned no usable page (no results
            # form) — usually rate-limiting/blocking. Back off instead of spinning
            # through instant empty 0.0s cycles.
            if not success:
                gap = random.uniform(5.0, 10.0)
                STATUS_STATE["avto_status"] = f"no data, backoff {gap:.0f}s"
                update_heartbeat()
                await asyncio.sleep(gap)
                continue

            STATUS_STATE["avto_status"] = f"idle ({elapsed:.1f}s)"
            update_heartbeat()

            # Steady, non-bursty polling. The old code fired 5 requests ~0.1s apart
            # then cooled — that burst is what got avto.net to soft-block us. A single
            # randomized gap every cycle keeps the same average rate without the spike.
            gap = random.uniform(4.0, 8.0)
            STATUS_STATE["avto_status"] = f"cooling ({gap:.1f}s)"
            update_heartbeat()
            await asyncio.sleep(gap)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            STATUS_STATE["avto_status"] = f"error"
            update_heartbeat()
            print(f"⚠️ Avto Loop Error: {e}")
            await asyncio.sleep(SLEEP_IDLE)

async def njus_loop(page, restart_event):
    conn = init_db()
    consecutive_captchas = 0
    while True:
        try:
            _, njus_crit = load_settings()
            start_time = time.time()

            STATUS_STATE["njus_status"] = "fetching"
            update_heartbeat()

            success, _total, _new = await njuskalo.scrape_routine(page, conn, njus_crit)
            elapsed = time.time() - start_time

            STATUS_STATE["njus_cycles"] += 1

            # success is None specifically when a captcha/ShieldSquare block was hit.
            if success is None:
                consecutive_captchas += 1

                if consecutive_captchas >= CAPTCHA_RESTART_THRESHOLD:
                    print(f"♻️ Njuskalo blocked {consecutive_captchas}x in a row — relaunching browser for a fresh session...")
                    restart_event.set()
                    return  # supervisor will tear down and relaunch the browser

                # Escalating backoff so we stop hammering while blocked.
                backoff = min(CAPTCHA_BACKOFF_BASE * consecutive_captchas, CAPTCHA_BACKOFF_MAX)
                STATUS_STATE["njus_status"] = f"blocked, backoff {backoff:.0f}s ({consecutive_captchas}/{CAPTCHA_RESTART_THRESHOLD})"
                update_heartbeat()
                await asyncio.sleep(backoff)
                continue

            # Clean cycle — reset the block counter.
            consecutive_captchas = 0
            STATUS_STATE["njus_status"] = f"idle ({elapsed:.1f}s)"
            update_heartbeat()

            # Polling delay: wait 5-8s to avoid triggering ShieldSquare / WAF rate-limiting
            gap = random.uniform(5.0, 8.0)
            await asyncio.sleep(gap)
        except asyncio.CancelledError:
            raise
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

async def session_timer(restart_event):
    """Force a browser relaunch every SESSION_MAX_AGE seconds."""
    if not SESSION_MAX_AGE:
        return
    await asyncio.sleep(SESSION_MAX_AGE)
    print(f"♻️ Session reached max age ({SESSION_MAX_AGE}s) — relaunching browser...")
    restart_event.set()


async def run_browser_session():
    print("🚀 Launching High-Performance Browser...")

    restart_event = asyncio.Event()

    # Route the whole browser through a proxy (rotating residential recommended) so
    # each relaunched session gets a fresh exit IP — the real fix for IP/region
    # blocks (Njuskalo ShieldSquare, avto.net Cloudflare). None = direct connection.
    proxy = load_proxy()
    if proxy:
        print(f"🌐 Proxy enabled: {proxy['server']}")
    else:
        print("🌐 No proxy configured (direct connection). Set settings/proxy.json or $SCRAPER_PROXY to enable.")

    launch_kwargs = dict(
        headless=True,
        args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--disable-extensions", "--blink-settings=imagesEnabled=false"],
    )
    if proxy:
        launch_kwargs["proxy"] = proxy

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="hr-HR"
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
        # Allow stylesheets & fonts so ShieldSquare bot verification doesn't fail!
        await context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "websocket", "manifest"] else route.continue_())

        page_avto = await context.new_page()
        page_njus = await context.new_page()

        print("✅ Browser Ready. Starting Independent Live Fetching...")

        tasks = [
            asyncio.create_task(avto_loop(page_avto)),
            asyncio.create_task(njus_loop(page_njus, restart_event)),
            asyncio.create_task(background_updates()),
            asyncio.create_task(session_timer(restart_event)),
        ]

        # Run until something asks for a browser relaunch (repeated captchas or max age).
        await restart_event.wait()

        # Tear down this session cleanly; main()'s loop will relaunch a fresh one.
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await context.close()
            await browser.close()
        except Exception:
            pass

async def main():
    while True:
        try:
            await run_browser_session()
            # Brief cooldown between sessions so a fresh browser doesn't immediately
            # re-hit the site (and possibly re-trip the same block).
            await asyncio.sleep(random.uniform(8.0, 15.0))
        except KeyboardInterrupt:
            # Clear heartbeat line on exit so terminal looks clean
            original_print(CLEAR_LINE, end="")
            break
        except Exception as e:
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())