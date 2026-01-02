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
    If car_data is provided, it will use the HTML template.
    """
    try:
        settings = load_settings()
        email_sender = settings.get("email_sender", "")
        email_password = settings.get("email_password", "")
        email_recipients = settings.get("email_recipients", [])
        
        if not email_sender or not email_password or not email_recipients:
            print("Email settings are incomplete or missing.")
            return False

        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = email_sender
        msg["To"] = ", ".join(email_recipients) if isinstance(email_recipients, list) else email_recipients

        html_part = MIMEText(body, "html")
        msg.attach(html_part)

        # Send the email
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(email_sender, email_password)
            server.send_message(msg)
            
        print(f"Email sent: {subject}")
            
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False