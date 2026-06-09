import datetime
import logging

from firebase_admin import firestore
from zoneinfo import ZoneInfo

from firebase_config import db
from email_service import send_email_notification

logger = logging.getLogger(__name__)
def send_due_reminder_emails():
    try:
        logger.info("Checking due reminders..")
        now = datetime.datetime.now()

        logger.info("STEP 1 - Starting email check")
        reminders = list(db.collection_group("reminders").stream())
        logger.info(f"STEP 2 - Found {len(reminders)} reminders")
        for reminder_doc in reminders:
            logger.info(f"Processing reminder: {reminder_doc.id}")
            reminder = reminder_doc.to_dict()
            logger.info(f"Reminder data: {reminder}")
            if reminder.get("email_sent", False):
                continue
            repeat_type = reminder.get("repeat_type")
            if repeat_type and repeat_type != "none":
                continue
            reminder_date = reminder.get("date")
            reminder_time = reminder.get("time")
            if not reminder_date or not reminder_time:
                continue
            try:
                reminder_datetime = datetime.datetime.strptime(
                    f"{reminder_date} {reminder_time}",
                    "%Y-%m-%d %I:%M %p"
                )
            except Exception:
                continue
            if reminder_datetime <= now:
                user_ref = (reminder_doc.reference.parent.parent)
                user_doc = user_ref.get()
                if not user_doc.exists:
                    continue
                user_data = user_doc.to_dict()
                email = user_data.get("email")
                name = user_data.get("name", "User")

                if not email:
                    continue

                success = send_email_notification(email, name, reminder.get("text", ""), reminder_time)
                if success:
                    reminder_doc.reference.update({"email_sent": True})
                    logger.info(
                        f"Notification sent for reminder "
                        f"{reminder_doc.id}"
                    )
    except Exception as e:
        logger.exception(f"send_due_reminder_emails failed: {e}")


def cleanup_expired_reminders():
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