from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import mail
import asyncio
import json

# URL to scrape
URL = "https://www.njuskalo.hr/auti/toyota"

async def scrape_routine(page, conn, criteria):
    try:
        # --- 1. AGGRESSIVE STEALTH SETUP ---
        # We must override the User-Agent because the default 'HeadlessChrome' gets blocked immediately.
        # This matches the User-Agent from your working old script.
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        await page.set_extra_http_headers({
            "User-Agent": user_agent,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Referer": "https://www.google.com/"
        })

        await page.set_viewport_size({"width": 1280, "height": 900})

        # Inject the stealth JS to hide 'navigator.webdriver'
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
            window.chrome = { runtime: {} };
        """)

        # --- 2. WARMUP NAVIGATION ---
        # Going directly to the search URL often triggers the bot detector.
        # We go to the homepage first to get valid session cookies.
        print("🔄 Njuskalo: Warming up session (Homepage)...")
        try:
            await page.goto("https://www.njuskalo.hr/", timeout=15000, wait_until="domcontentloaded")
            await asyncio.sleep(2) # Short pause to act human
        except:
            print("⚠️ Warmup timed out, proceeding to target...")

        # --- 3. TARGET NAVIGATION ---
        print(f"🔄 Njuskalo: Loading listings...")
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        # Check for Captcha
        title = await page.title()
        if "ShieldSquare" in title or "Captcha" in title:
            print(f"⚠️ Njuskalo BLOCKED: ShieldSquare Captcha detected. (Attempting to parse anyway)")
        
        # --- 4. PARSING (Logic from your Old Script) ---
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        # Strategy 1: Find the specific "Regular ads" section
        main_container = soup.select_one('section.EntityList--Regular.EntityList--ListItemRegularAd ul.EntityList-items')
        
        # Strategy 2: Find any ul.EntityList-items with listings
        if not main_container:
            for container in soup.select('ul.EntityList-items'):
                if container.select('li'):
                    main_container = container
                    break
        
        if not main_container:
            # Fallback for when the structure is flat (no UL)
            main_container = soup.select_one('.EntityList-items')

        if not main_container:
            print(f"⚠️ Njuskalo: Could not find main list. Page Title: {title}")
            return 0

        listings = main_container.select('li')
        new_items_count = 0
        cur = conn.cursor()

        for li in listings:
            # Filter Logic (VauVau check)
            if is_vauvau_listing(li): continue

            # Parse
            car = parse_car_listing(li, URL)
            if not car or not car.get('id'): continue

            # Check Status
            cur.execute("SELECT email_sent FROM njuskalo_cars WHERE id=?", (car["id"],))
            existing = cur.fetchone()
            
            is_new = existing is None
            already_emailed = existing[0] if existing else 0

            # Debug Print
            if is_new:
                 print(f"➕ Found New Njuskalo: {car.get('name')} | {car.get('price')} | {car.get('year')}")
                 new_items_count += 1

            # Match Logic
            match, reason = check_car_against_criteria(car, criteria)
            should_send_email = 0

            if match and (is_new or already_emailed == 0):
                print(f"🔔 MATCH Njuskalo: {car['name']} ({reason})")
                if mail.send_email_sync(f"Njuskalo Match: {car['name']}", mail.format_car_email(car, reason)):
                    should_send_email = 1
            elif already_emailed == 1:
                should_send_email = 1

            insert_car_with_status(conn, car, should_send_email, reason)

        if new_items_count > 0:
            conn.commit()
        return new_items_count

    except Exception as e:
        print(f"⚠️ Njuskalo Error: {e}")
        return 0

# --- EXACT HELPER FUNCTIONS FROM YOUR OLD SCRIPT ---

def clean_text(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_id_from_data_options(data_options):
    if not data_options: return None
    data_options = data_options.replace('&quot;', '"')
    try:
        options_dict = json.loads(data_options)
        if 'id' in options_dict: return str(options_dict['id'])
    except:
        id_match = re.search(r'"id"\s*:\s*(\d+)', data_options)
        if id_match: return id_match.group(1)
    return None

def extract_id_from_url(url):
    if not url: return None
    if 'oglas-' in url: return url.split('oglas-')[-1]
    return None

def is_vauvau_listing(listing):
    try:
        class_attr = listing.get('class', [])
        # Check string or list
        if isinstance(class_attr, str): class_attr = class_attr.split()
        
        if 'EntityList-item--VauVau' in class_attr: return True
        if 'EntityList-item--Regular' not in class_attr: return True
        if listing.select('.VauVau-logo, .VauVau-icon, .EntityList-vauVauLabel'): return True
        return False
    except: return False

def parse_car_listing(listing, base_url):
    try:
        car_data = {'id': None, 'name': None, 'price': None, 'location': None, 'date_published': None, 'link': None, 'image': None, 'year': None, 'mileage': None, 'specs': {}}
        
        # ID
        data_options = listing.get('data-options', '')
        car_id = extract_id_from_data_options(data_options)
        car_data['id'] = car_id
        
        # Title
        title_element = listing.select_one('.entity-title a')
        if title_element:
            car_data['name'] = clean_text(title_element.text)
            url = title_element.get('href', '')
            if url:
                if not url.startswith('http'): url = urljoin(base_url, url)
                car_data['link'] = url
                if not car_id: car_data['id'] = extract_id_from_url(url)
        
        # Price (Supports HRK and EUR)
        price_element = listing.select_one('.entity-prices .price--hrk') or listing.select_one('.price--eur') or listing.select_one('.price-item')
        if price_element:
            car_data['price'] = clean_text(price_element.text)
        
        # Image
        img_element = listing.select_one('.entity-thumbnail img')
        if img_element:
            image_url = img_element.get('src', '') or img_element.get('data-src', '')
            if image_url:
                if image_url.startswith('//'): image_url = 'https:' + image_url
                elif not image_url.startswith('http'): image_url = urljoin(base_url, image_url)
                car_data['image'] = image_url
        
        # Date
        date_element = listing.select_one('.entity-pub-date time')
        if date_element:
            car_data['date_published'] = clean_text(date_element.text)

        # Specs (Year, Mileage)
        description_element = listing.select_one('.entity-description-main')
        if description_element:
            full_description = clean_text(description_element.get_text())
            
            # Mileage
            km_match = re.search(r'\b(\d{1,3}(?:[.,]\d{3})*)\s*km\b', full_description, re.I)
            if km_match:
                car_data['mileage'] = int(km_match.group(1).replace('.', '').replace(',', ''))
            
            # Year
            year_match = re.search(r'Godište automobila:\s*(\d{4})|Car year:\s*(\d{4})|Godina vozila:\s*(\d{4})', full_description)
            if year_match:
                car_data['year'] = year_match.group(1) or year_match.group(2) or year_match.group(3)
            else:
                year_match = re.search(r'\b(19\d\d|20\d\d)\b', full_description)
                if year_match: car_data['year'] = year_match.group(1)

            # Location
            location_match = re.search(r'Lokacija vozila:\s*([^<\n\r]+)|Vehicle location:\s*([^<\n\r]+)', full_description)
            if location_match:
                loc = (location_match.group(1) or location_match.group(2)).strip()
                car_data['location'] = re.sub(r'\s*Financing.*$|Financiranje.*$', '', loc)

        return car_data
    except Exception as e:
        print(f"Error parsing: {e}")
        return None

def check_car_against_criteria(car, criteria):
    price_val = None
    if car.get("price"):
        try: 
            price_clean = re.sub(r'[^\d]', '', car["price"])
            if price_clean: price_val = int(price_clean)
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