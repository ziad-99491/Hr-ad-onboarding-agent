import os, smtplib
from email.message import EmailMessage

def send_credentials(manager_email: str, name: str, sam: str, upn: str, password: str, start: str):
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise RuntimeError("SMTP_HOST not configured - cannot deliver credentials")
    m = EmailMessage()
    m["From"], m["To"] = os.environ["SMTP_FROM"], manager_email
    m["Subject"] = f"New hire account ready: {name} (starts {start})"
    m.set_content(f"Account for {name} is active.\n\nUsername: {upn}\nSAM: {sam}\n"
                  f"Temporary password: {password}\n\nThe user must change it at first logon.\n"
                  "Please hand it over securely and do not forward this email.")
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
        if os.getenv("SMTP_STARTTLS", "1") == "1":
            s.starttls()
        if os.getenv("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(m)
