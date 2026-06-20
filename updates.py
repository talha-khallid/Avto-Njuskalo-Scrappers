import json
import requests
from pathlib import Path

# Paths to local JSON files
BASE_DIR = Path(__file__).resolve().parent
SETTINGS_DIR = BASE_DIR / "settings"
AVTO_FILE = SETTINGS_DIR / "avto.json"
NJUSKALO_FILE = SETTINGS_DIR / "njuskalo.json"

API_URL = "https://avtonjuskalo.pythonanywhere.com/data/api/"

def sync_data():
    try:
        # Fetch data from API
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        api_data = response.json()
    except Exception as e:
        print(f"❌ Error fetching API: {e}")
        return

    # --- Sync Avto ---
    avto_new = {"car_criteria": api_data.get("avto", [])}
    avto_changed = True
    if AVTO_FILE.exists():
        with open(AVTO_FILE, "r", encoding="utf-8") as f:
            avto_current = json.load(f)
        avto_changed = avto_current != avto_new

    if avto_changed:
        with open(AVTO_FILE, "w", encoding="utf-8") as f:
            json.dump(avto_new, f, indent=4, ensure_ascii=False)
        print("✅ Avto updated")
    else:
        pass

    # --- Sync Njuskalo ---
    njuskalo_new = {"car_criteria": api_data.get("njuskalo", {})}
    njuskalo_changed = True
    if NJUSKALO_FILE.exists():
        with open(NJUSKALO_FILE, "r", encoding="utf-8") as f:
            njuskalo_current = json.load(f)
        njuskalo_changed = njuskalo_current != njuskalo_new

    if njuskalo_changed:
        with open(NJUSKALO_FILE, "w", encoding="utf-8") as f:
            json.dump(njuskalo_new, f, indent=4, ensure_ascii=False)
        print("✅ Njuskalo updated")
    else:
        pass