from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import json
import os
import sqlite3
from sqlite3 import Connection
import mail


# Initialize the DB once
from pathlib import Path
DB_FILE = "database.db"


URL = "https://www.avto.net/Ads/results_100.asp?oglasrubrika=1&prodajalec=2"


def load_criteria(path="settings/avto.json"):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("car_criteria", [])


def load_template():
    """Load the HTML template for email"""
    try:
        with open("Template.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print("Template.html not found")
        return None


def format_car_email(car, reason):
    """Format car data into HTML email using template"""
    template = load_template()
    if not template:
        return None
    
    # Format car image
    car_image_html = ""
    if car.get("image"):
        car_image_html = f'<img src="{car["image"]}" alt="Car Image" class="car-image">'
    
    # Simple specs without table
    car_specs_html = f"<tr><td>Year</td><td>{car.get('year', 'N/A')}</td></tr>"
    car_specs_html += f"<tr><td>Mileage</td><td>{car.get('mileage', 'N/A')}</td></tr>"
    
    # Replace placeholders in template
    html_content = template.format(
        car_name=car.get("name", "Unknown Car"),
        car_price=car.get("price", "Price not available"),
        car_image_html=car_image_html,
        car_specs_html=car_specs_html,
        car_link=car.get("link", "#"),
        match_reason=reason
    )
    
    return html_content


def send_car_email(car, reason):
    """Send email notification for a matching car"""
    subject = f"Car Match Found: {car.get('name', 'Unknown Car')}"
    body = format_car_email(car, reason)
    
    if body:
        return mail.send_email(subject, body)
    else:
        print("Failed to format email template")
        return False


def check_car_against_criteria(car, criteria_list):
    """
    Returns (matches: bool, reason: str)
    """
    name = (car.get("name") or "").lower()
    year = car.get("year")
    mileage = car.get("mileage")
    print(f"Name {name} Year {year} Mileage {mileage}")

    for crit in criteria_list:
        crit_name = crit.get("name", "").lower()
        if crit_name not in name:
            continue

        # ---------- year ----------
        if year is not None:
            try:
                year_int = int(year)
                min_y = crit.get("min_year")
                max_y = crit.get("max_year")

                if min_y is not None and year_int < min_y:
                    return False, f"too old (year {year_int})"
                if max_y is not None and year_int > max_y:
                    return False, f"too new (year {year_int})"
            except Exception:
                pass

        # ---------- mileage ----------
        if mileage is not None:
            try:
                mileage_int = int(str(mileage).replace(".", "").replace(",", ""))
                max_m = crit.get("max_mileage")
                if max_m is not None and mileage_int > max_m:
                    return False, f"mileage exceeded ({mileage_int})"
            except Exception:
                pass

        # passed all checks
        return True, "match"

    return False, "name not match"



def init_db(db_name=DB_FILE):
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cars (
        id          TEXT PRIMARY KEY,
        link        TEXT,
        name        TEXT,
        image       TEXT,
        price       REAL,
        year        INTEGER,          -- NEW
        mileage     INTEGER,          -- NEW
        email_sent  INTEGER DEFAULT 0,
        reason      TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS car_specs (
        id         TEXT,
        spec_key   TEXT,
        spec_value TEXT,
        FOREIGN KEY (id) REFERENCES cars(id)
    )
    """)
    conn.commit()
    return conn, cur



def insert_car_with_status(conn: Connection, car: dict, email_sent: int, reason: str):
    cur = conn.cursor()

    cur.execute("""
    INSERT OR REPLACE INTO cars
        (id, link, name, image, price, year, mileage, email_sent, reason)
    VALUES
        (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        car.get("id"),
        car.get("link"),
        car.get("name"),
        car.get("image"),
        car.get("price"),
        car.get("year"),      # can be None → NULL in DB
        car.get("mileage"),   # can be None → NULL in DB
        email_sent,
        reason
    ))

    # specs table unchanged
    cur.execute("DELETE FROM car_specs WHERE id=?", (car["id"],))
    for key, value in car.get("specs", {}).items():
        cur.execute("""
        INSERT INTO car_specs (id, spec_key, spec_value) VALUES (?, ?, ?)
        """, (car["id"], key, value))

    conn.commit()



def insert_car_if_new(conn: Connection, car: dict):
    cur = conn.cursor()

    # skip if already present
    cur.execute("SELECT 1 FROM cars WHERE id=?", (car["id"],))
    if cur.fetchone():
        return False

    # insert full row, including the new columns
    cur.execute("""
        INSERT INTO cars
            (id, link, name, image, price, year, mileage)
        VALUES
            (?, ?, ?, ?, ?, ?, ?)
    """, (
        car.get("id"),
        car.get("link"),
        car.get("name"),
        car.get("image"),
        car.get("price"),
        car.get("year"),      # None → NULL
        car.get("mileage")    # None → NULL
    ))

    # specs table unchanged
    cur.execute("DELETE FROM car_specs WHERE id=?", (car["id"],))
    for key, value in car.get("specs", {}).items():
        cur.execute("""
            INSERT INTO car_specs (id, spec_key, spec_value)
            VALUES (?, ?, ?)
        """, (car["id"], key, value))

    conn.commit()
    return True




def parse_car_row(row, base_url):
    # Find main stretched link (contains id)
    a = row.select_one("a.stretched-link")
    if not a or not a.get("href"):
        return None

    href = a["href"].strip()
    full_link = urljoin(base_url, href)

    # Parse id from querystring
    parsed = urlparse(full_link)
    qs = parse_qs(parsed.query)
    car_id = (qs.get("id") or [None])[0]

    # Title / name
    title_el = row.select_one(".GO-Results-Naziv span")
    name = title_el.get_text(strip=True) if title_el else None

    # Image
    img_el = row.select_one(".GO-Results-Photo img")
    image = urljoin(base_url, img_el["src"]) if img_el and img_el.get("src") else None

    # Price (some pages use this class)
    price_el = row.select_one(".GO-Results-Price-TXT-Regular")
    if not price_el:
        # fallback: any price-like div
        price_el = row.select_one(".GO-Results-Price-Mid .GO-Results-Price-TXT-Regular")
    price = price_el.get_text(strip=True) if price_el else None

    # Extract year and mileage from specs table
    year = None
    mileage = None
    data_table = row.select_one(".GO-Results-Data table")
    if data_table:
        for tr in data_table.select("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 2:
                key = tds[0].get_text(strip=True)
                val = tds[1].get_text(" ", strip=True)
                
                if "registracija" in key.lower():  # Check if it's production year info
                    if "1.registracija" in key.lower():
                        import re
                        year_match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                        if year_match:
                            year = int(year_match.group(1))
                            print(f"Using registration as year_of_production: {year}")
                    else:
                        try:
                            year = int(val.strip().split()[0])
                        except:
                            pass
                
                
                if "prevoženih" in key.lower():  # example: "16300 km"
                    try:
                        mileage = int(val.lower().replace("km", "").replace(".", "").strip())
                    except:
                        pass

    print(f"✅   name {name} year {year} milage {mileage}")
    return {
        "id": car_id,
        "link": full_link,
        "name": name,
        "image": image,
        "price": price,
        "year": year,
        "mileage": mileage
    }

def scrape_avto():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-extensions"
            ]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="Europe/Ljubljana",
        )

        page = context.new_page()

        # stealth-ish injection (helps against basic bot detection)
        page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
            window.chrome = { runtime: {} };
            """
        )

        # load page
        page.goto(URL, timeout=60000)
        page.wait_for_load_state("networkidle")

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        # isolate form
        form = soup.find("form", {"id": "results"})
        if not form:
            print("ERROR: <form id='results'> not found. Saved full page to 'response_full.html' for debugging.")
            os.makedirs("debug", exist_ok=True)
            with open(os.path.join("debug", "response_full.html"), "w", encoding="utf-8") as f:
                f.write(html)
            browser.close()
            return []

        # find rows with the GO-Results-Row class (each is one listing)
        rows = form.select("div.GO-Results-Row")
        extracted = []
        for row in rows:
            car = parse_car_row(row, URL)
            if car:
                extracted.append(car)

        conn, cur = init_db()
        criteria = load_criteria()
        new_count, matched_count = 0, 0

        for car in extracted:
            # skip if already in DB
            cur.execute("SELECT 1 FROM cars WHERE id=?", (car["id"],))
            if cur.fetchone():
                continue

            new_count += 1
            match, reason = check_car_against_criteria(car, criteria)

            if match:
                matched_count += 1
                email_sent = 0
                if send_car_email(car, reason):
                    email_sent = 1
                    print(f"Email sent for car: {car.get('name', 'Unknown')}")
                else:
                    print(f"Failed to send email for car: {car.get('name', 'Unknown')}")

                insert_car_with_status(conn, car, email_sent, reason)
            else:
                insert_car_with_status(conn, car, 0, reason)

        print(f"Checked {len(extracted)} cars → {new_count} new, {matched_count} matched criteria.")
        conn.close()
        browser.close()
        return extracted


if __name__ == "__main__":
    print("Starting Avto.net car scraper...")
    try:
        cars = scrape_avto()
        print("Scraping completed successfully!")
    except Exception as e:
        print(f"Error during scraping: {e}")
        import traceback
        traceback.print_exc()