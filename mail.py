import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import os
import queue
import threading
import time

# Global queue for emails
_email_queue = queue.Queue()
_worker_thread = None
_lock = threading.Lock()

class EmailTask:
    def __init__(self, subject, body):
        self.subject = subject
        self.body = body

def load_settings():
    path = os.path.join("settings", "email.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Settings file not found: {path}")
        return {}
    except json.JSONDecodeError:
        print(f"Invalid JSON in settings file: {path}")
        return {}

def _email_worker():
    server = None
    
    while True:
        try:
            # Wait for an email task with a timeout (e.g. 10 seconds)
            try:
                task = _email_queue.get(timeout=10)
            except queue.Empty:
                # Close SMTP connection if idle for more than 10 seconds
                if server is not None:
                    try:
                        server.quit()
                    except:
                        pass
                    server = None
                continue
            
            # We got a task! Send it.
            settings = load_settings()
            email_sender = settings.get("email_sender", "")
            email_password = settings.get("email_password", "")
            email_recipients = settings.get("email_recipients", [])
            
            if not email_sender or not email_password or not email_recipients:
                print("[mail] Email settings are incomplete or missing.")
                _email_queue.task_done()
                continue
            
            # Connect to SMTP if not connected
            if server is None:
                try:
                    server = smtplib.SMTP("smtp.gmail.com", 587)
                    server.starttls()
                    server.login(email_sender, email_password)
                except Exception as e:
                    print(f"[mail] SMTP Connection/Login failed: {e}")
                    server = None
                    _email_queue.task_done()
                    continue
            
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = task.subject
            msg["From"] = email_sender
            if isinstance(email_recipients, list):
                msg["To"] = ", ".join(email_recipients)
            else:
                msg["To"] = email_recipients
                
            html_part = MIMEText(task.body, "html")
            msg.attach(html_part)
            
            # Send message
            try:
                server.send_message(msg)
                print(f"[mail] sent: {task.subject}")
            except Exception as e:
                print(f"[mail] FAILED to send via SMTP: {e}")
                # Reset connection on failure
                try:
                    server.close()
                except:
                    pass
                server = None
                
            _email_queue.task_done()
            
        except Exception as e:
            print(f"[mail] worker error: {e}")
            if server is not None:
                try:
                    server.close()
                except:
                    pass
                server = None
            time.sleep(1)

def start_worker_if_needed():
    global _worker_thread
    with _lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_email_worker, daemon=True)
            _worker_thread.start()

def send_email(subject, body):
    """Enqueues the email to be sent in the background instantly without blocking"""
    _email_queue.put(EmailTask(subject, body))
    start_worker_if_needed()
    return True

def send_email_sync(subject, body):
    """Wrapper to safely call send_email from scraper threads"""
    return send_email(subject, body)

def format_car_email(car, reason):
    """Helper to format email body"""
    try:
        with open("Template.html", "r", encoding="utf-8") as f:
            template = f.read()
    except:
        template = "<h2>Car Match: {car_name}</h2><p>Reason: {match_reason}</p><a href='{car_link}'>Link</a>"

    car_image_html = f'<img src="{car.get("image")}" style="max-width:300px;">' if car.get("image") else ""
    
    specs_html = f"<tr><td>Price</td><td>{car.get('price', 'N/A')}</td></tr>"
    specs_html += f"<tr><td>Year</td><td>{car.get('year', 'N/A')}</td></tr>"
    specs_html += f"<tr><td>Mileage</td><td>{car.get('mileage', 'N/A')}</td></tr>"

    return template.format(
        car_name=car.get("name", "Unknown"),
        car_price=car.get("price", "N/A"),
        car_image_html=car_image_html,
        car_specs_html=specs_html,
        car_link=car.get("link", "#"),
        match_reason=reason
    )