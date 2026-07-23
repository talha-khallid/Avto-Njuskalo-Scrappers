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

# Every fetch launches a brand-new browser and closes it afterwards (which throws
# away all cookies + cache), then waits this many seconds before the next fetch.
WAIT_AFTER_FETCH = 3.0

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
        print(f"[proxy] Could not read settings/proxy.json: {e}")
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

async def fetch_site(p, launch_kwargs, scrape_fn, conn, crit):
    """
    Launch a BRAND-NEW browser, do exactly one fetch, then close it. Closing the
    browser discards all cookies + cache, so the next fetch starts clean.
    """
    browser = None
    try:
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="hr-HR",
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
        # Drop images/media/etc. for speed; keep CSS/fonts so WAF checks don't fail.
        await context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "websocket", "manifest"] else route.continue_())
        page = await context.new_page()
        return await scrape_fn(page, conn, crit)
    finally:
        if browser is not None:
            try:
                await browser.close()  # discards this fetch's cookies + cache
            except Exception:
                pass

async def scrape_loop(p, launch_kwargs, name, status_key, cycles_key, scrape_fn):
    """One site: fresh browser -> fetch -> close (clears cache) -> wait 3s -> repeat."""
    conn = init_db()
    while True:
        try:
            avto_crit, njus_crit = load_settings()
            crit = avto_crit if name == "avto" else njus_crit

            start = time.time()
            STATUS_STATE[status_key] = "fetching"
            update_heartbeat()

            result = await fetch_site(p, launch_kwargs, scrape_fn, conn, crit)
            took = time.time() - start

            # result = (success, total_seen, new_items). success is None on captcha.
            success, total, new = result if isinstance(result, tuple) and len(result) == 3 else (False, 0, 0)

            STATUS_STATE[cycles_key] += 1
            if success is None:
                STATUS_STATE[status_key] = f"BLOCKED, retrying (wait {WAIT_AFTER_FETCH:.0f}s)"
            elif success:
                STATUS_STATE[status_key] = f"{total} seen, {new} new ({took:.1f}s), wait {WAIT_AFTER_FETCH:.0f}s"
            else:
                STATUS_STATE[status_key] = f"no data ({took:.1f}s), wait {WAIT_AFTER_FETCH:.0f}s"
            update_heartbeat()
            await asyncio.sleep(WAIT_AFTER_FETCH)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            STATUS_STATE[status_key] = "error"
            update_heartbeat()
            print(f"[{name}] loop error: {e}")
            await asyncio.sleep(SLEEP_IDLE)

async def background_updates():
    executor = ThreadPoolExecutor(max_workers=1)
    while True:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(executor, updates.sync_data)
            await asyncio.sleep(UPDATE_INTERVAL)
        except Exception:
            await asyncio.sleep(5)

def build_launch_kwargs():
    # Optional proxy (rotating residential recommended). None = direct connection.
    proxy = load_proxy()
    if proxy:
        print(f"[proxy] enabled: {proxy['server']}")
    else:
        print("[proxy] none (direct connection). Set settings/proxy.json or $SCRAPER_PROXY to enable.")

    kwargs = dict(
        headless=True,
        args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--disable-extensions", "--blink-settings=imagesEnabled=false"],
    )
    if proxy:
        kwargs["proxy"] = proxy
    return kwargs

async def run():
    print("[start] Fresh-browser-per-fetch mode: new browser each fetch, closed after (clears cache), 3s wait.")
    launch_kwargs = build_launch_kwargs()
    async with async_playwright() as p:
        print("[start] Ready. Live fetching Avto + Njuskalo...")
        await asyncio.gather(
            scrape_loop(p, launch_kwargs, "avto", "avto_status", "avto_cycles", avto.scrape_routine),
            scrape_loop(p, launch_kwargs, "njuskalo", "njus_status", "njus_cycles", njuskalo.scrape_routine),
            background_updates(),
            return_exceptions=True,
        )

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        original_print(CLEAR_LINE, end="")