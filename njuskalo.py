from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import mail
import asyncio

URL = "https://www.njuskalo.hr/auti/toyota"

async def scrape_routine(page, conn, criteria):
    try:
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        main = soup.select_one('section.EntityList--Regular ul.EntityList-items') or \
               soup.select_one('ul.EntityList-items')
        
        if not main: return 0

        listings = main.select('li')
        new_items_count = 0
        cur = conn.cursor()

        for li in listings:
            # Filter Logic
            cls = li.get('class', [])
            if 'EntityList-item--VauVau' in cls: continue
            if 'EntityList-item--Regular' not in cls: continue

            car = parse_car_listing(li, URL)
            if not car or not car.get('id'): continue

            # 1. Check if NEW (for debug/email)
            cur.execute("SELECT email_sent FROM njuskalo_cars WHERE id=?", (car["id"],))
            existing = cur.fetchone()
            
            is_new = existing is None
            already_emailed = existing[0] if existing else 0

            # 2. DEBUG PRINT (Only for NEW cars)
            if is_new:
                 print(f"➕ Found New Njuskalo: {car.get('name')} | Year: {car.get('year')} | Price: {car.get('price')}")
                 new_items_count += 1

            # 3. Check Criteria
            match, reason = check_car_against_criteria(car, criteria)
            should_send_email = 0

            # 4. Email Logic
            if match and (is_new or already_emailed == 0):
                print(f"🔔 MATCH Njuskalo: {car['name']} ({reason})")
                if mail.send_email_sync(f"Njuskalo Match: {car['name']}", mail.format_car_email(car, reason)):
                    should_send_email = 1
            elif already_emailed == 1:
                should_send_email = 1

            # 5. ALWAYS SAVE
            insert_car_with_status(conn, car, should_send_email, reason)

        if new_items_count > 0:
            conn.commit()
        return new_items_count

    except Exception as e:
        print(f"⚠️ Njuskalo Error: {e}")
        return 0

# --- Helper Logic ---

def clean_text(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def parse_car_listing(li, base_url):
    try:
        data = {'specs': {}}
        opts = li.get('data-options', '')
        id_m = re.search(r'"id"\s*:\s*(\d+)', opts.replace('&quot;', '"'))
        data['id'] = id_m.group(1) if id_m else None

        title_el = li.select_one('.entity-title a')
        if title_el:
            data['name'] = clean_text(title_el.text)
            data['link'] = urljoin(base_url, title_el.get('href', ''))
            if not data['id'] and 'oglas-' in data['link']:
                data['id'] = data['link'].split('oglas-')[-1]

        price_el = li.select_one('.entity-prices .price--hrk')
        data['price'] = clean_text(price_el.text) if price_el else None

        img = li.select_one('.entity-thumbnail img')
        if img:
            src = img.get('src') or img.get('data-src')
            data['image'] = urljoin(base_url, src) if src else None

        desc_el = li.select_one('.entity-description-main')
        year, mileage, loc, date = None, None, None, None
        
        if desc_el:
            txt = clean_text(desc_el.get_text())
            
            # Mileage
            km = re.search(r'\b(\d{1,3}(?:[.,]\d{3})*)\s*km\b', txt, re.I)
            if km: mileage = int(km.group(1).replace('.', '').replace(',', ''))
            
            # Year
            yr = re.search(r'Godište.*?(\d{4})|(\d{4}).*?Godište', txt)
            if yr: year = yr.group(1) or yr.group(2)
            else:
                yr_simple = re.search(r'\b(19\d\d|20\d\d)\b', txt)
                if yr_simple: year = yr_simple.group(1)

            # Location
            loc_m = re.search(r'Lokacija vozila:\s*([^<\n\r]+)', txt)
            if loc_m: 
                loc = re.sub(r'\s*Financ.*$', '', loc_m.group(1)).strip()

        date_el = li.select_one('.entity-pub-date time')
        if date_el: date = clean_text(date_el.text)

        data.update({'year': year, 'mileage': mileage, 'location': loc, 'date_published': date})
        return data
    except: return None

def check_car_against_criteria(car, criteria):
    # Quick Criteria Check
    price_val = None
    if car.get("price"):
        try: price_val = int(re.sub(r'[^\d]', '', car["price"]))
        except: pass

    if car.get("year"):
        try:
            y = int(car["year"])
            if criteria.get("min_year") and y < criteria.get("min_year"): return False, "Old"
            if criteria.get("max_year") and y > criteria.get("max_year"): return False, "New"
        except: pass

    if price_val and criteria.get("max_price") and price_val > criteria.get("max_price"):
        return False, "Expensive"

    return True, "Match"

def insert_car_with_status(conn, car, email_sent, reason):
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO njuskalo_cars (id, link, name, image, price, year, mileage, location, date_published, email_sent, reason)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (car.get("id"), car.get("link"), car.get("name"), car.get("image"), car.get("price"), car.get("year"), car.get("mileage"), car.get("location"), car.get("date_published"), email_sent, reason))