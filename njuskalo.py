from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import mail
import json
import asyncio

URL = "https://www.njuskalo.hr/auti/toyota"

async def scrape_routine(page, conn, criteria):
    try:
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        # Container Finder (Matches your strategy)
        main = soup.select_one('section.EntityList--Regular ul.EntityList-items') or \
               soup.select_one('ul.EntityList-items')
        
        if not main: return 0

        listings = main.select('li')
        new_count = 0
        cur = conn.cursor()

        for li in listings:
            # Skip VauVau
            cls = li.get('class', [])
            if 'EntityList-item--VauVau' in cls: continue
            if 'EntityList-item--Regular' not in cls: continue

            car = parse_car_listing(li, URL)
            if not car or not car.get('id'): continue

            cur.execute("SELECT 1 FROM njuskalo_cars WHERE id=?", (car["id"],))
            if cur.fetchone(): continue

            new_count += 1
            match, reason = check_car_against_criteria(car, criteria)
            email_sent = 0

            if match:
                print(f"🔥 Njuskalo Match: {car['name']}")
                if mail.send_email_sync(f"Njuskalo Match: {car['name']}", mail.format_car_email(car, reason)):
                    email_sent = 1
            
            insert_car_with_status(conn, car, email_sent, reason)

        if new_count > 0: conn.commit()
        return new_count

    except Exception as e:
        print(f"⚠️ Njuskalo Error: {e}")
        return 0

# --- Helper Logic (Exact match to your script) ---

def clean_text(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def parse_car_listing(li, base_url):
    try:
        data = {'specs': {}}
        
        # ID from data-options
        opts = li.get('data-options', '')
        id_m = re.search(r'"id"\s*:\s*(\d+)', opts.replace('&quot;', '"'))
        data['id'] = id_m.group(1) if id_m else None

        # Title/Link
        title_el = li.select_one('.entity-title a')
        if title_el:
            data['name'] = clean_text(title_el.text)
            data['link'] = urljoin(base_url, title_el.get('href', ''))
            # ID Fallback
            if not data['id'] and 'oglas-' in data['link']:
                data['id'] = data['link'].split('oglas-')[-1]

        # Price
        price_el = li.select_one('.entity-prices .price--hrk')
        data['price'] = clean_text(price_el.text) if price_el else None

        # Image
        img = li.select_one('.entity-thumbnail img')
        if img:
            src = img.get('src') or img.get('data-src')
            data['image'] = urljoin(base_url, src) if src else None

        # Description parsing (Your exact logic)
        desc_el = li.select_one('.entity-description-main')
        year, mileage, loc, date = None, None, None, None
        
        if desc_el:
            txt = clean_text(desc_el.get_text())
            full_html = str(desc_el)

            # Mileage
            km = re.search(r'\b(\d{1,3}(?:[.,]\d{3})*)\s*km\b', txt, re.I)
            if km: 
                mileage = int(km.group(1).replace('.', '').replace(',', ''))
                data['specs']['Kilometers'] = f"{km.group(1)} km"
            
            # Year
            yr = re.search(r'Godište automobila:\s*(\d{4})|Car year:\s*(\d{4})|Godina vozila:\s*(\d{4})', txt)
            if yr: year = yr.group(1) or yr.group(2) or yr.group(3)
            else:
                yr_simple = re.search(r'\b(19\d\d|20\d\d)\b', txt)
                if yr_simple: year = yr_simple.group(1)

            if year: data['specs']['Year'] = year

            # Location
            loc_m = re.search(r'Lokacija vozila:\s*([^<\n\r]+)|Vehicle location:\s*([^<\n\r]+)', txt)
            if loc_m: 
                loc = (loc_m.group(1) or loc_m.group(2)).strip()
                loc = re.sub(r'\s*Financing.*$|Financiranje.*$', '', loc)
                data['specs']['Location'] = loc

            # Financing
            fin = re.search(r'Financiranje već od\s*([0-9.,]+)\s*€', txt)
            if fin: data['specs']['Financing'] = f"Financing from €{fin.group(1)}"

        # Year from Title fallback
        if not year and data.get('name'):
            ym = re.search(r'\b(19\d\d|20\d\d)\b', data['name'])
            if ym: year = ym.group(1)

        # Pub Date
        date_el = li.select_one('.entity-pub-date time')
        if date_el: 
            date = clean_text(date_el.text)
            data['specs']['Published'] = date

        data.update({'year': year, 'mileage': mileage, 'location': loc, 'date_published': date})
        return data
    except: return None

def check_car_against_criteria(car, criteria):
    # Price
    price_val = None
    if car.get("price"):
        try: 
            clean = re.sub(r'[^\d,.]', '', car["price"]).replace(',', '').replace('.', '')
            price_val = int(clean)
        except: pass

    # Year
    if car.get("year"):
        try:
            y = int(car["year"])
            if criteria.get("min_year") and y < criteria.get("min_year"): return False, "Old"
            if criteria.get("max_year") and y > criteria.get("max_year"): return False, "New"
        except: pass

    # Mileage
    if car.get("mileage"):
        try:
            m = int(car["mileage"])
            if criteria.get("max_mileage") and m > criteria.get("max_mileage"): return False, "High Miles"
        except: pass

    # Price Check
    if price_val and criteria.get("max_price") and price_val > criteria.get("max_price"):
        return False, "Expensive"

    return True, "match"

def insert_car_with_status(conn, car, email_sent, reason):
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO njuskalo_cars (id, link, name, image, price, year, mileage, location, date_published, email_sent, reason)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (car.get("id"), car.get("link"), car.get("name"), car.get("image"), car.get("price"), car.get("year"), car.get("mileage"), car.get("location"), car.get("date_published"), email_sent, reason))