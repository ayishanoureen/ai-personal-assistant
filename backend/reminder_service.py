import datetime
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
from firebase_config import db, firebase_initialized
from email_service import send_email_notification

logger = logging.getLogger(__name__)

# ThreadPoolExecutor to offload network-bound SMTP operations (prevents blocking the scheduler)
executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="email_sender")

# Thread-safe tracker to prevent duplicate email dispatches for in-flight requests
sending_reminder_ids = set()
sending_lock = threading.Lock()

def send_due_reminder_emails():
    """
    Finds all reminders in the database that are due for email notifications,
    parses their scheduled times in the Asia/Kolkata timezone, and handles
    asynchronous non-blocking dispatch.
    """
    if not firebase_initialized or db is None:
        logger.warning("Firebase not initialized. Skipping send_due_reminder_emails.")
        return

    try:
        kolkata_tz = ZoneInfo("Asia/Kolkata")
        now = datetime.datetime.now(kolkata_tz)

        logger.info("Checking due reminders (Asia/Kolkata timezone)...")
        reminders = list(db.collection_group("reminders").stream())
        
        for reminder_doc in reminders:
            reminder_id = reminder_doc.id
            
            # Safely check if this reminder is currently in-flight
            with sending_lock:
                if reminder_id in sending_reminder_ids:
                    continue
            
            reminder = reminder_doc.to_dict() or {}
            
            # Skip if already marked as sent
            if reminder.get("email_sent", False):
                continue
                
            # Skip recurring reminders (recurring scheduling details are updated separately)
            repeat_type = reminder.get("repeat_type")
            if repeat_type and repeat_type != "none":
                continue
                
            reminder_date = reminder.get("date")
            reminder_time = reminder.get("time")
            if not reminder_date or not reminder_time:
                continue
                
            try:
                # Parse date and time in the user's timezone (Asia/Kolkata)
                reminder_datetime = datetime.datetime.strptime(
                    f"{reminder_date} {reminder_time}",
                    "%Y-%m-%d %I:%M %p"
                )
                reminder_datetime = reminder_datetime.replace(tzinfo=kolkata_tz)
            except Exception as parse_err:
                logger.error(f"Failed to parse reminder datetime for {reminder_id}: {parse_err}")
                continue
                
            # If the scheduled time is in the past/due, proceed to dispatch
            if reminder_datetime <= now:
                # Retrieve parent user details
                user_ref = reminder_doc.reference.parent.parent
                user_doc = user_ref.get()
                if not user_doc.exists:
                    continue
                user_data = user_doc.to_dict() or {}
                email = user_data.get("email")
                name = user_data.get("name", "User")
                
                if not email:
                    logger.warning(f"No email found for user {user_ref.id}. Skipping reminder {reminder_id}.")
                    continue
                
                # Mark as in-flight
                with sending_lock:
                    sending_reminder_ids.add(reminder_id)
                
                # Offload the SMTP network call to the worker pool
                executor.submit(
                    _send_email_async_worker,
                    reminder_doc.reference,
                    reminder_id,
                    email,
                    name,
                    reminder.get("text", "No title"),
                    reminder_time,
                    reminder_date
                )
                
    except Exception as e:
        logger.exception(f"send_due_reminder_emails loop failed: {e}")

def _send_email_async_worker(doc_ref, reminder_id: str, email: str, name: str, text: str, reminder_time: str, reminder_date: str):
    """
    Background thread worker responsible for transmitting the email.
    Only updates the firestore database flag once transmission is validated.
    """
    try:
        logger.info(f"Initiating email send for reminder {reminder_id} to {email}...")
        
        # Perform SMTP operations (blocks only this thread worker)
        success = send_email_notification(email, name, text, f"{reminder_date} at {reminder_time}")
        
        if success:
            # Transactionally update flag only on success
            doc_ref.update({"email_sent": True})
            logger.info(f"Database updated successfully for reminder {reminder_id} (email_sent=True).")
        else:
            logger.error(f"Failed to deliver email for reminder {reminder_id}. Flag NOT updated (will retry).")
            
    except Exception as e:
        logger.error(f"Error in async email worker for reminder {reminder_id}: {e}")
    finally:
        # Unlock the in-flight tracking ID
        with sending_lock:
            sending_reminder_ids.discard(reminder_id)


def cleanup_expired_reminders():
    if not firebase_initialized or db is None:
        logger.warning("Firebase not initialized. Skipping cleanup_expired_reminders.")
        return

    try:
        logger.info("Starting expired reminder cleanup...")

        now = datetime.datetime.now(ZoneInfo("Asia/Kolkata"))
        deleted_count = 0

        # Search ALL reminders across ALL users
        reminders = db.collection_group("reminders").stream()

        for reminder_doc in reminders:
            try:
                data = reminder_doc.to_dict()

                # Skip recurring reminders
                repeat_type = data.get("repeat_type")
                if repeat_type and repeat_type != "none":
                    continue

                reminder_date = data.get("date")
                reminder_time = data.get("time")

                if not reminder_date or not reminder_time:
                    continue

                try:
                    datetime_str = f"{reminder_date} {reminder_time}"

                    formats = [
                        "%Y-%m-%d %I:%M %p",  # 07:00 PM
                        "%Y-%m-%d %I %p",     # 7 PM
                        "%Y-%m-%d %H:%M",     # 19:00
                    ]

                    reminder_datetime = None

                    for fmt in formats:
                        try:
                            reminder_datetime = datetime.datetime.strptime(
                                datetime_str,
                                fmt
                            )
                            reminder_datetime = reminder_datetime.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                            break
                        except ValueError:
                            pass

                    if reminder_datetime is None:
                        logger.warning(
                            f"Failed parsing reminder datetime for "
                            f"{reminder_doc.id}: {datetime_str}"
                        )
                        continue
                except Exception as e:
                    logger.warning(
                        f"Failed parsing reminder datetime "
                        f"for {reminder_doc.id}: {e}"
                    )
                    continue

                if reminder_datetime < now:
                    reminder_doc.reference.delete()

                    deleted_count += 1

                    logger.info(
                        f"Deleted expired reminder: "
                        f"{data.get('text', 'Unknown')}"
                    )

            except Exception as e:
                logger.error(
                    f"Error processing reminder {reminder_doc.id}: {e}"
                )

        logger.info(
            f"Cleanup complete. Deleted {deleted_count} reminders."
        )

    except Exception as e:
        logger.exception(
            f"cleanup_expired_reminders failed: {e}"
        )