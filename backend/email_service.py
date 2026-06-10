import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
    logger.warning("EMAIL_ADDRESS or EMAIL_PASSWORD environment variables are not set. Email notifications will fail.")

def send_email_notification(
    recipient_email: str,
    user_name: str,
    reminder_text: str,
    reminder_time: str
) -> bool:

    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        logger.error("Cannot send email. SMTP credentials are not configured.")
        return False

    subject = f"🔔 Reminder: {reminder_text}"

    plain_body = f"""
Hi {user_name},

This is a reminder from your AI Personal Assistant.

Task: {reminder_text}
Scheduled Time: {reminder_time}

Have a great and productive day!

Best regards,
AI Personal Assistant
"""

    html_body = f"""
    <html>
    <body>
        <h2>Reminder Notification</h2>
        <p>Hello {user_name},</p>
        <p>This is your reminder:</p>

        <b>Task:</b> {reminder_text}<br>
        <b>Time:</b> {reminder_time}

        <p>Have a productive day!</p>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = recipient_email
    msg["Subject"] = subject

    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    server = None

    try:
        logger.info("Opening SMTP connection...")

        server = smtplib.SMTP_SSL(
            "smtp.gmail.com",
            587,
            timeout=30
        )

        logger.info("SMTP connected")

        logger.info(f"Logging in as {EMAIL_ADDRESS}")
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)

        logger.info("Logged in successfully")

        logger.info(f"Sending email to {recipient_email}")

        server.sendmail(
            EMAIL_ADDRESS,
            recipient_email,
            msg.as_string()
        )

        logger.info("Email sent successfully")

        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.exception(f"SMTP Authentication Error: {e}")
        return False

    except smtplib.SMTPConnectError as e:
        logger.exception(f"SMTP Connect Error: {e}")
        return False

    except TimeoutError as e:
        logger.exception(f"SMTP Timeout Error: {e}")
        return False

    except OSError as e:
        logger.exception(f"Network Error: {e}")
        return False

    except Exception as e:
        logger.exception(f"General SMTP Error: {e}")
        return False

    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass