from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import re
import mail
import asyncio

URL = "https://www.avto.net/Ads/results_100.asp?oglasrubrika=1&prodajalec=2"

async def scrape_routine(page, conn, criteria):
    try:
        # Fast load
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        form = soup.find("form", {"id": "results"})
        if not form: return 0

        rows = form.select("div.GO-Results-Row")
        new_items_count = 0
        cur = conn.cursor()

        for row in rows:
            car = parse_car_row(row, URL)
            if not car or not car.get("id"): continue

            # Check if car exists to decide if we print/email
            cur.execute("SELECT email_sent FROM cars WHERE id=?", (car["id"],))
            existing = cur.fetchone()
            
            is_new = existing is None
            already_emailed = existing[0] if existing else 0
            
            # --- DEBUG PRINT (Only for NEW cars) ---
            if is_new:
                print(f"➕ Found New: {car.get('name')} | Year: {car.get('year')} | Mileage: {car.get('mileage')} | Price: {car.get('price')}")
                new_items_count += 1
            
            # Check Criteria
            match, reason = check_car_against_criteria(car, criteria)
            should_send_email = 0

            # Logic: If matches AND (it's new OR we haven't emailed about it yet)
            if match and (is_new or already_emailed == 0):
                print(f"🔔 MATCH Avto: {car['name']} ({reason})")
                if mail.send_email_sync(f"Avto Match: {car['name']}", mail.format_car_email(car, reason)):
                    should_send_email = 1
            elif already_emailed == 1:
                should_send_email = 1 # Keep status as sent

            # ALWAYS Save/Update DB (Insert or Replace)
            insert_car_with_status(conn, car, should_send_email, reason)
        
        if new_items_count > 0:
            conn.commit()
            
        return new_items_count

    except Exception as e:
        print(f"⚠️ Avto Scrape Error: {e}")
        return 0

def parse_car_row(row, base_url):
    try:
        # ID & Link
        a_link = row.select_one("a.stretched-link")
        if not a_link: return None
        full_link = urljoin(base_url, a_link["href"].strip())
        qs = parse_qs(urlparse(full_link).query)
        car_id = (qs.get("id") or [None])[0]
        if not car_id: return None

        # Name
        name_el = row.select_one(".GO-Results-Naziv")
        name = name_el.get_text(strip=True) if name_el else "Unknown"

        # Image
        img_el = row.select_one(".GO-Results-Photo img")
        image = urljoin(base_url, img_el["src"]) if img_el else None

        # Price (Loop to find valid number)
        price = None
        for p_el in row.select(".GO-Results-Price-TXT-Regular"):
            txt = p_el.get_text(strip=True)
            # Remove dots, € sign
            clean = re.sub(r'[^\d]', '', txt) 
            if clean:
                price = float(clean)
                break 

        # Specs (Year, Mileage)
        year, mileage = None, None
        table = row.select_one(".GO-Results-Data table")
        if table:
            for tr in table.select("tr"):
                tds = tr.select("td")
                if len(tds) < 2: continue
                
                key = tds[0].get_text(strip=True).lower()
                val = tds[1].get_text(strip=True)

                # Explicit check for "1.registracija" (Production Year)
                if "1.registracija" in key:
                    # Look for 4 digits (e.g. 2013)
                    ym = re.search(r'\b(19\d\d|20\d\d)\b', val)
                    if ym: year = int(ym.group(1))
                    elif val.strip().isdigit(): year = int(val.strip())

                # Explicit check for "Prevoženih" (Mileage)
                if "prevoženih" in key:
                    # Remove 'km', spaces, dots
                    m_clean = re.sub(r'[^\d]', '', val)
                    if m_clean: mileage = int(m_clean)

        return {
            "id": car_id, "link": full_link, "name": name, 
            "image": image, "price": price, "year": year, 
            "mileage": mileage, "specs": {}
        }
    except: return None

def check_car_against_criteria(car, criteria_list):
    name = (car.get("name") or "").lower()
    year = car.get("year")
    mileage = car.get("mileage")

    for crit in criteria_list:
        crit_name = crit.get("name", "").lower()
        if crit_name not in name: continue
        
        # Year Check
        if year:
            try:
                y = int(year)
                if crit.get("min_year") and y < crit.get("min_year"): return False, f"Old ({y})"
                if crit.get("max_year") and y > crit.get("max_year"): return False, f"New ({y})"
            except: pass
            
        # Mileage Check
        if mileage:
            try:
                m = int(mileage)
                if crit.get("max_mileage") and m > crit.get("max_mileage"): return False, f"High Miles ({m})"
            except: pass
            
        return True, "match"
    return False, "no match"

def insert_car_with_status(conn, car, email_sent, reason):
    cur = conn.cursor()
    # Always update so we capture price changes
    cur.execute("""
    INSERT OR REPLACE INTO cars (id, link, name, image, price, year, mileage, email_sent, reason)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (car["id"], car["link"], car["name"], car["image"], car["price"], car["year"], car["mileage"], email_sent, reason))