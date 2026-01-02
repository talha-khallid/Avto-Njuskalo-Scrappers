from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json
import os
import sqlite3
from sqlite3 import Connection
import mail
import re


# Initialize the DB once
from pathlib import Path
DB_FILE = "database.db"
URL = "https://www.njuskalo.hr/auti/toyota"


def load_criteria(path="settings/njuskalo.json"):
    """Load car criteria from settings file"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("car_criteria", {})


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
    
    # Format specifications table
    car_specs_html = ""
    specs = car.get("specs", {})
    for key, value in specs.items():
        car_specs_html += f"<tr><td>{key}</td><td>{value}</td></tr>"
    
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


def extract_price_number(price_text):
    """Extract numeric price from price text"""
    if not price_text:
        return None
    
    # Remove currency symbols and extract numbers
    price_clean = re.sub(r'[^\d,.]', '', price_text)
    price_clean = price_clean.replace(',', '').replace('.', '')
    
    try:
        return int(price_clean)
    except:
        return None


def check_car_against_criteria(car, criteria):
    """
    Returns (matches: bool, reason: str)
    """
    year = car.get("year")
    mileage = car.get("mileage")
    price = extract_price_number(car.get("price"))

    # Check year
    if year is not None:
        try:
            year_int = int(year)
            min_y = criteria.get("min_year")
            max_y = criteria.get("max_year")
            if min_y is not None and year_int < min_y:
                return False, f"too old (year {year_int})"
            if max_y is not None and year_int > max_y:
                return False, f"too new (year {year_int})"
        except:
            pass

    # Check mileage
    if mileage is not None:
        try:
            mileage_int = int(str(mileage).replace('.', '').replace(',', ''))
            if mileage_int > criteria.get("max_mileage", 999999):
                return False, f"mileage exceeded ({mileage_int})"
        except:
            pass

    # Check price
    if price is not None and criteria.get("max_price"):
        if price > criteria.get("max_price"):
            return False, f"price exceeded ({price})"

    # passed all checks
    return True, "match"


def init_db(db_name=DB_FILE):
    """Initialize database with njuskalo table"""
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS njuskalo_cars (
        id TEXT PRIMARY KEY,
        link TEXT,
        name TEXT,
        image TEXT,
        price TEXT,
        year INTEGER,
        mileage INTEGER,
        location TEXT,
        date_published TEXT,
        email_sent INTEGER DEFAULT 0,
        reason TEXT
    )
    """)

    conn.commit()
    return conn, cur


def insert_car_with_status(conn: Connection, car: dict, email_sent: int, reason: str):
    """Insert car into database with email status"""
    cur = conn.cursor()

    cur.execute("""
    INSERT OR REPLACE INTO njuskalo_cars (id, link, name, image, price, year, mileage, location, date_published, email_sent, reason)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        car.get("id"),
        car.get("link"),
        car.get("name"),
        car.get("image"),
        car.get("price"),
        car.get("year"),
        car.get("mileage"),
        car.get("location"),
        car.get("date_published"),
        email_sent,
        reason
    ))

    conn.commit()


def clean_text(text):
    """Remove HTML tags and clean up text"""
    if not text:
        return ""
    # Remove font tags and other HTML
    text = re.sub(r'<[^>]+>', '', text)
    # Replace multiple spaces with a single space
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_id_from_data_options(data_options):
    """Extract ID from the data-options attribute"""
    if not data_options:
        return None
        
    # Replace HTML encoded quotes with actual quotes
    data_options = data_options.replace('&quot;', '"')
    
    # Try to parse as JSON
    try:
        options_dict = json.loads(data_options)
        if 'id' in options_dict:
            return str(options_dict['id'])
    except json.JSONDecodeError:
        # If JSON parsing fails, try regex
        id_match = re.search(r'"id"\s*:\s*(\d+)', data_options)
        if id_match:
            return id_match.group(1)
            
    return None


def extract_id_from_url(url):
    """Extract the ID from a URL containing 'oglas-'"""
    if not url:
        return None
    if 'oglas-' in url:
        return url.split('oglas-')[-1]
    return None


def parse_car_listing(listing, base_url):
    """Parse a single car listing from njuskalo"""
    try:
        # Initialize car data dictionary
        car_data = {
            'id': None,
            'name': None,
            'price': None,
            'location': None,
            'date_published': None,
            'link': None,
            'image': None,
            'year': None,
            'mileage': None,
            'specs': {}
        }
        
        # Extract ID from data-options attribute
        data_options = listing.get('data-options', '')
        car_id = extract_id_from_data_options(data_options)
        car_data['id'] = car_id
        
        # Extract title and URL from .entity-title a
        title_element = listing.select_one('.entity-title a')
        if title_element:
            # Get the text and clean it
            title = clean_text(title_element.text)
            car_data['name'] = title
            
            # Get the URL from the link
            url = title_element.get('href', '')
            if url:
                # Make sure URL is absolute
                if not url.startswith('http'):
                    url = urljoin(base_url, url)
                car_data['link'] = url
                
                # If we couldn't get ID from data-options, try to get it from URL
                if not car_id:
                    car_id = extract_id_from_url(url)
                    car_data['id'] = car_id
        
        # Extract price from .entity-prices .price--hrk
        price_element = listing.select_one('.entity-prices .price--hrk')
        if price_element:
            price = clean_text(price_element.text)
            car_data['price'] = price
        
        # Extract image URL from .entity-thumbnail img
        img_element = listing.select_one('.entity-thumbnail img')
        if img_element:
            image_url = img_element.get('src', '')
            if not image_url:
                image_url = img_element.get('data-src', '')
            if image_url:
                # Handle protocol-relative URLs
                if image_url.startswith('//'):
                    image_url = 'https:' + image_url
                elif not image_url.startswith('http'):
                    image_url = urljoin(base_url, image_url)
                car_data['image'] = image_url
        
        # Extract published date from .entity-pub-date time
        date_element = listing.select_one('.entity-pub-date time')
        if date_element:
            date = clean_text(date_element.text)
            car_data['date_published'] = date
            car_data['specs']['Published'] = date
        
        # Get the full description block for detailed extraction
        description_element = listing.select_one('.entity-description-main')
        if description_element:
            # Get the HTML content to preserve structure
            description_html = str(description_element)
            full_description = clean_text(description_element.get_text())
            
            # Extract mileage - look for pattern like "29000 km"
            km_match = re.search(r'\b(\d{1,3}(?:[.,]\d{3})*)\s*km\b', full_description, re.I)
            if km_match:
                car_data['mileage'] = int(km_match.group(1).replace('.', '').replace(',', ''))
                car_data['specs']['Kilometers'] = f"{km_match.group(1)} km"
            
            # Extract year - look for Croatian pattern "Godište automobila: 2023."
            # 1. try the labelled form
            year_match = re.search(
                r'Godište automobila:\s*(\d{4})|Car year:\s*(\d{4})|Godina vozila:\s*(\d{4})',
                full_description
            )
            if year_match:
                year = year_match.group(1) or year_match.group(2) or year_match.group(3)
            else:
                # 2. fall back to any 19/20xx number
                year_match = re.search(r'\b(19\d\d|20\d\d)\b', full_description)
                year = year_match.group(1) if year_match else None

            if year:
                car_data['year'] = year
                car_data['specs']['Year'] = year
            
            # Extract location - look for Croatian pattern "Lokacija vozila: "
            location_match = re.search(r'Lokacija vozila:\s*([^<\n\r]+)|Vehicle location:\s*([^<\n\r]+)', full_description)
            if location_match:
                location = (location_match.group(1) or location_match.group(2)).strip()
                # Remove any financing info that might be attached
                location = re.sub(r'\s*Financing.*$|Financiranje.*$', '', location)
                car_data['location'] = location
                car_data['specs']['Location'] = location
            
            # Extract financing info if present (Croatian: "Financiranje već od 304,62 € mjesečno")
            financing_match = re.search(r'Financiranje već od\s*([0-9.,]+)\s*€|Financing from [€$]\s*([0-9.,]+)', full_description)
            if financing_match:
                amount = financing_match.group(1) or financing_match.group(2)
                car_data['specs']['Financing'] = f"Financing from €{amount} per month"
            
            # Extract vehicle status (Croatian: "Rabljeno vozilo" = Used, "Novo vozilo" = New)
            if 'Rabljeno vozilo' in full_description or 'Used vehicle' in full_description:
                car_data['specs']['Status'] = 'Used'
            elif 'Novo vozilo' in full_description or 'New vehicle' in full_description:
                car_data['specs']['Status'] = 'New'
        
        # Extract year from title if not found in description
        if not car_data['year'] and car_data['name']:
            year_match = re.search(r'\b(19\d\d|20\d\d)\b', car_data['name'])
            if year_match:
                car_data['year'] = year_match.group(1)
                car_data['specs']['Year'] = year_match.group(1)
        
        return car_data
    except Exception as e:
        print(f"Error parsing car listing: {e}")
        return None


def is_vauvau_listing(listing):
    """Check if a listing is a VauVau listing (which we want to skip)"""
    try:
        # Check the class attribute directly
        class_attr = listing.get('class', [])
        if isinstance(class_attr, str):
            class_attr = class_attr.split()
        
        # Check if it's explicitly a VauVau listing
        if 'EntityList-item--VauVau' in class_attr:
            return True
            
        # Check if it's NOT a Regular listing
        if 'EntityList-item--Regular' not in class_attr:
            # Only process Regular listings
            return True
        
        # Check for VauVau logo or mention
        vauvau_elements = listing.select('.VauVau-logo, .VauVau-icon, .EntityList-vauVauLabel')
        if vauvau_elements:
            return True
        
        return False
    except Exception as e:
        print(f"Error checking if listing is VauVau: {e}")
        return False


def scrape_njuskalo():
    """Main function to scrape Njuskalo using Playwright and BeautifulSoup"""
    criteria = load_criteria()
    url = URL
    
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
            timezone_id="Europe/Zagreb",
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
        print(f"Loading page: {url}")
        page.goto(url, timeout=60000)
        page.wait_for_load_state("networkidle")

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        # Find the main listing container
        main_container = None
        
        # Strategy 1: Find the specific "Regular ads" section
        regular_section = soup.select_one('section.EntityList--Regular.EntityList--ListItemRegularAd')
        if regular_section:
            main_container = regular_section.select_one('ul.EntityList-items')
            print(f"Found regular section with container: {main_container is not None}")
        
        # Strategy 2: Find any ul.EntityList-items with listings
        if not main_container:
            containers = soup.select('ul.EntityList-items')
            print(f"Found {len(containers)} EntityList-items containers")
            for i, container in enumerate(containers):
                listings = container.select('li')
                print(f"Container {i+1} has {len(listings)} listings")
                if listings:
                    main_container = container
                    print(f"Using container {i+1} as main container")
                    break
        
        if not main_container:
            print("ERROR: Could not find listing container. Saved full page to 'debug/njuskalo_response.html' for debugging.")
            os.makedirs("debug", exist_ok=True)
            with open(os.path.join("debug", "njuskalo_response.html"), "w", encoding="utf-8") as f:
                f.write(html)
            browser.close()
            return []

        # find all car listings
        listings = main_container.select('li')
        print(f"Found {len(listings)} total listings in container")
        extracted = []
        
        for i, listing in enumerate(listings):
            # Skip VauVau and non-regular listings
            if is_vauvau_listing(listing):
                continue
                
            car = parse_car_listing(listing, url)
            if car and car.get('id'):
                extracted.append(car)
            else:
                print(f"Failed to extract car from listing {i+1}")

        print(f"Total cars extracted: {len(extracted)}")

        conn, cur = init_db()
        new_count, matched_count = 0, 0

        for car in extracted:
            # skip if already in DB
            cur.execute("SELECT 1 FROM njuskalo_cars WHERE id=?", (car["id"],))
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
    print("Starting Njuskalo.hr car scraper...")
    try:
        cars = scrape_njuskalo()
        print("Scraping completed successfully!")
    except Exception as e:
        print(f"Error during scraping: {e}")
        import traceback
        traceback.print_exc()