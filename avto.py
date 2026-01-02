from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import re
import mail
import asyncio

# The URL to scrape
URL = "https://www.avto.net/Ads/results_100.asp?oglasrubrika=1&prodajalec=2"

async def scrape_routine(page, conn, criteria):     
    """
    Async worker for Avto.net. 
    Receives an open page and db connection from main.py.
    """
    try:
        # Fast load - we don't wait for 'networkidle' (too slow), just DOM
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        
        # Get HTML
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        # Find the results form
        form = soup.find("form", {"id": "results"})
        if not form:
            # print("⚠️ Avto.net: Form not found") 
            return 0

        rows = form.select("div.GO-Results-Row")
        new_cars_count = 0
        cur = conn.cursor()

        for row in rows:
            # Parse the car using the robust function below
            car = parse_car_row(row, URL)
            
            # If parsing failed or no ID, skip
            if not car or not car.get("id"): 
                continue

            # Quick DB check
            cur.execute("SELECT 1 FROM cars WHERE id=?", (car["id"],))
            if cur.fetchone():
                continue

            # It's a new car!
            new_cars_count += 1
            match, reason = check_car_against_criteria(car, criteria)
            email_sent = 0

            if match:
                print(f"🔥 MATCH Avto: {car['name']}")
                # Send email (using the sync wrapper)
                if mail.send_email_sync(f"Avto Match: {car['name']}", mail.format_car_email(car, reason)):
                    email_sent = 1

            insert_car_with_status(conn, car, email_sent, reason)
        
        if new_cars_count > 0:
            conn.commit()
            
        return new_cars_count

    except Exception as e:
        print(f"⚠️ Avto Scrape Error: {e}")
        return 0

# --- ROBUST PARSING LOGIC ---

def parse_car_row(row, base_url):
    try:
        # 1. Extract ID and Link
        a_link = row.select_one("a.stretched-link")
        if not a_link or not a_link.get("href"):
            return None
        
        full_link = urljoin(base_url, a_link["href"].strip())
        
        # Parse ID from URL query
        qs = parse_qs(urlparse(full_link).query)
        car_id = (qs.get("id") or [None])[0]
        
        if not car_id:
            return None

        # 2. Extract Name
        # Based on your HTML: <div class="GO-Results-Naziv ..."><span>Audi...</span></div>
        name_el = row.select_one(".GO-Results-Naziv") 
        name = name_el.get_text(strip=True) if name_el else "Unknown"

        # 3. Extract Image
        img_el = row.select_one(".GO-Results-Photo img")
        image = urljoin(base_url, img_el["src"]) if img_el and img_el.get("src") else None

        # 4. Extract Price (Robust Mode)
        price = None
        # We select ALL price elements because the HTML has duplicates (mobile vs desktop)
        price_els = row.select(".GO-Results-Price-TXT-Regular")
        for p_el in price_els:
            txt = p_el.get_text(strip=True)
            if not txt: continue
            
            # Remove dots (thousands separator) and non-digits
            # Example: "8.940 €" -> "8940"
            clean_txt = re.sub(r'[^\d]', '', txt)
            if clean_txt:
                try:
                    price = float(clean_txt)
                    break # Stop once we find a valid price
                except:
                    continue
        
        # 5. Extract Specs (Year, Mileage) from Table
        year = None
        mileage = None
        
        table = row.select_one(".GO-Results-Data table")
        if table:
            rows_tr = table.select("tr")
            for tr in rows_tr:
                tds = tr.select("td")
                if len(tds) < 2: continue
                
                # Clean the key and value
                key = tds[0].get_text(strip=True).lower()
                val = tds[1].get_text(strip=True)
                
                # Year Logic
                if "registracija" in key:
                    # Look for 4 digit year 19xx or 20xx
                    yr_match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                    if yr_match:
                        year = int(yr_match.group(1))
                    elif not year:
                         # Fallback for simple "2013"
                        try: year = int(val.split()[0])
                        except: pass
                
                # Mileage Logic
                if "prevoženih" in key:
                    # Example: "239856 km" -> remove "km", ".", spaces
                    m_clean = re.sub(r'[^\d]', '', val)
                    if m_clean:
                        mileage = int(m_clean)

        return {
            "id": car_id,
            "link": full_link,
            "name": name,
            "image": image,
            "price": price,
            "year": year,
            "mileage": mileage,
            "specs": {} 
        }
    except Exception as e:
        # print(f"Error parsing specific row: {e}")
        return None

def check_car_against_criteria(car, criteria_list):
    name = (car.get("name") or "").lower()
    year = car.get("year")
    mileage = car.get("mileage")

    for crit in criteria_list:
        crit_name = crit.get("name", "").lower()
        if crit_name not in name: continue
        
        # Year Check
        if year is not None:
            try:
                y = int(year)
                if crit.get("min_year") and y < crit.get("min_year"): return False, f"Old ({y})"
                if crit.get("max_year") and y > crit.get("max_year"): return False, f"New ({y})"
            except: pass
            
        # Mileage Check
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
    
    # Clean insert of specs if you want to store them
    cur.execute("DELETE FROM car_specs WHERE id=?", (car["id"],))
    for k, v in car.get("specs", {}).items():
        cur.execute("INSERT INTO car_specs VALUES (?,?,?)", (car["id"], k, str(v)))