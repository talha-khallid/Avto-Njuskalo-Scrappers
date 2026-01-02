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
        new_count = 0
        cur = conn.cursor()

        for row in rows:
            car = parse_car_row(row, URL)
            if not car: continue

            # DB Check
            cur.execute("SELECT 1 FROM cars WHERE id=?", (car["id"],))
            if cur.fetchone(): continue

            new_count += 1
            match, reason = check_car_against_criteria(car, criteria)
            email_sent = 0

            if match:
                print(f"🔥 Avto Match: {car['name']}")
                # Using sync wrapper for mail
                if mail.send_email_sync(f"Avto Match: {car['name']}", mail.format_car_email(car, reason)):
                    email_sent = 1

            insert_car_with_status(conn, car, email_sent, reason)
        
        if new_count > 0: conn.commit()
        return new_count

    except Exception as e:
        print(f"⚠️ Avto Error: {e}")
        return 0

# --- Helper Logic (Exact match to your provided script) ---

def parse_car_row(row, base_url):
    try:
        a = row.select_one("a.stretched-link")
        if not a or not a.get("href"): return None
        full_link = urljoin(base_url, a["href"].strip())
        qs = parse_qs(urlparse(full_link).query)
        car_id = (qs.get("id") or [None])[0]
        
        name_el = row.select_one(".GO-Results-Naziv span")
        name = name_el.get_text(strip=True) if name_el else None
        
        img_el = row.select_one(".GO-Results-Photo img")
        image = urljoin(base_url, img_el["src"]) if img_el and img_el.get("src") else None
        
        price_el = row.select_one(".GO-Results-Price-TXT-Regular")
        if not price_el: price_el = row.select_one(".GO-Results-Price-Mid .GO-Results-Price-TXT-Regular")
        price = price_el.get_text(strip=True) if price_el else None

        year, mileage = None, None
        dt = row.select_one(".GO-Results-Data table")
        if dt:
            for tr in dt.select("tr"):
                tds = tr.find_all("td")
                if len(tds) >= 2:
                    k = tds[0].get_text(strip=True).lower()
                    v = tds[1].get_text(" ", strip=True)
                    
                    if "registracija" in k:
                        if "1.registracija" in k:
                            m = re.search(r'\b(19\d\d|20\d\d)\b', v)
                            if m: year = int(m.group(1))
                        else:
                            try: year = int(v.strip().split()[0])
                            except: pass
                    
                    if "prevoženih" in k:
                        try: mileage = int(v.lower().replace("km","").replace(".","").strip())
                        except: pass

        return {"id": car_id, "link": full_link, "name": name, "image": image, "price": price, "year": year, "mileage": mileage, "specs": {}}
    except: return None

def check_car_against_criteria(car, criteria_list):
    name = (car.get("name") or "").lower()
    year = car.get("year")
    mileage = car.get("mileage")

    for crit in criteria_list:
        if crit.get("name", "").lower() not in name: continue
        
        if year is not None:
            try:
                y = int(year)
                if crit.get("min_year") and y < crit.get("min_year"): return False, f"Old ({y})"
                if crit.get("max_year") and y > crit.get("max_year"): return False, f"New ({y})"
            except: pass
            
        if mileage is not None:
            try:
                m = int(mileage)
                if crit.get("max_mileage") and m > crit.get("max_mileage"): return False, f"High Miles ({m})"
            except: pass
            
        return True, "match"
    return False, "no match"

def insert_car_with_status(conn, car, email_sent, reason):
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO cars (id, link, name, image, price, year, mileage, email_sent, reason)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (car["id"], car["link"], car["name"], car["image"], car["price"], car["year"], car["mileage"], email_sent, reason))
    
    cur.execute("DELETE FROM car_specs WHERE id=?", (car["id"],))
    for k, v in car.get("specs", {}).items():
        cur.execute("INSERT INTO car_specs VALUES (?,?,?)", (car["id"], k, str(v)))