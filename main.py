#!/usr/bin/env python3
"""
Main Car Scraper Application
Runs Avto.net and Njuskalo.hr scrapers infinitely
"""

import time
import traceback
from datetime import datetime

# Import the scraper functions
import avto
import njuskalo
from updates import sync_data


def log_message(message):
    """Print message with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def run_avto_scraper():
    """Run the Avto.net scraper"""
    try:
        log_message("🚗 Starting Avto.net scraper...")
        cars = avto.scrape_avto()
        log_message(f"✅ Avto.net scraper completed. Found {len(cars)} cars.")
        return True
    except Exception as e:
        log_message(f"❌ Error in Avto.net scraper: {str(e)}")
        traceback.print_exc()
        return False


def run_njuskalo_scraper():
    """Run the Njuskalo.hr scraper"""
    try:
        log_message("🚗 Starting Njuskalo.hr scraper...")
        cars = njuskalo.scrape_njuskalo()
        log_message(f"✅ Njuskalo.hr scraper completed. Found {len(cars)} cars.")
        return True
    except Exception as e:
        log_message(f"❌ Error in Njuskalo.hr scraper: {str(e)}")
        traceback.print_exc()
        return False


def main():
    """Main function that runs both scrapers infinitely"""
    log_message("🚀 Starting Car Scraper Application")
    log_message("📋 Will run Avto.net first, then Njuskalo.hr, then repeat...")
    log_message("⏹️ Press Ctrl+C to stop")
    
    cycle_count = 0
    
    try:
        while True:
            cycle_count += 1
            
            log_message("checking for updates...")
            sync_data()
            
            
            log_message(f"🔄 Starting scraping cycle #{cycle_count}")
            
            # Run Avto.net scraper first
            avto_success = run_avto_scraper()
            
            # Wait a bit between scrapers
            log_message("⏳ Waiting 10 seconds before next scraper...")
            time.sleep(10)
            
            # Run Njuskalo.hr scraper
            njuskalo_success = run_njuskalo_scraper()
            
            # Summary for this cycle
            if avto_success and njuskalo_success:
                log_message(f"✅ Cycle #{cycle_count} completed successfully")
            else:
                log_message(f"⚠️ Cycle #{cycle_count} completed with some errors")
            
            # Wait before next cycle
            log_message("⏳ Waiting 30 seconds before next cycle...")
            time.sleep(30)  # 5 minutes
            
    except KeyboardInterrupt:
        log_message("⏹️ Stopping application (Ctrl+C pressed)")
    except Exception as e:
        log_message(f"💥 Unexpected error: {str(e)}")
        traceback.print_exc()
    finally:
        log_message("👋 Car Scraper Application stopped")


if __name__ == "__main__":
    main()