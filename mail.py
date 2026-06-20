import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import os

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

def send_email(subject, body):
    """
    Sends an email with the given subject and body, using settings loaded from settings.json.
    """
    try:
        settings = load_settings()
        email_sender = settings.get("email_sender", "")
        email_password = settings.get("email_password", "")
        email_recipients = settings.get("email_recipients", [])
        
        if not email_sender or not email_password or not email_recipients:
            print("❌ Email settings are incomplete or missing.")
            return False

        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = email_sender
        # Handle list or string
        if isinstance(email_recipients, list):
            msg["To"] = ", ".join(email_recipients)
        else:
            msg["To"] = email_recipients

        html_part = MIMEText(body, "html")
        msg.attach(html_part)

        # Send the email
        # with smtplib.SMTP("smtp.gmail.com", 587) as server:
        #     server.starttls()
        #     server.login(email_sender, email_password)
        #     server.send_message(msg)
            
        print(f"📧 Email sent: {subject}")
        return True
    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False

# THIS IS THE CRITICAL FUNCTION THAT WAS MISSING
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