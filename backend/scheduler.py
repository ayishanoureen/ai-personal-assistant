import uuid
import logging
import datetime as dt_module
from datetime import datetime, timedelta
from firebase_admin import firestore
from dateutil.relativedelta import relativedelta
from apscheduler.schedulers.background import BackgroundScheduler
from firebase_config import db, firebase_initialized
from reminder_service import (
    send_due_reminder_emails,
    cleanup_expired_reminders
)

logger = logging.getLogger("scheduler")

# Unique identifier for this process instance
SCHEDULER_ID = f"scheduler_{uuid.uuid4().hex[:8]}"
has_lock = False

scheduler = BackgroundScheduler()

WEEKDAY_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6
}

def check_and_renew_lock():
    global has_lock
    if not firebase_initialized or db is None:
        logger.warning(f"Process {SCHEDULER_ID}: Firebase not initialized. Cannot check/renew scheduler lock.")
        has_lock = False
        return

    try:
        lock_ref = db.collection("metadata").document("scheduler_lock")

        @firestore.transactional
        def transact_lock(transaction):
            snapshot = lock_ref.get(transaction=transaction)
            now_utc = dt_module.datetime.now(dt_module.timezone.utc)

            if not snapshot.exists:
                # Document does not exist, acquire lock
                transaction.set(lock_ref, {
                    "owner_id": SCHEDULER_ID,
                    "last_heartbeat": now_utc
                })
                return True

            data = snapshot.to_dict() or {}
            owner_id = data.get("owner_id")
            last_heartbeat = data.get("last_heartbeat")

            if owner_id == SCHEDULER_ID:
                # We own the lock, update heartbeat
                transaction.update(lock_ref, {
                    "last_heartbeat": now_utc
                })
                return True

            # If someone else owns it, check for heartbeat expiration (> 90 seconds)
            if last_heartbeat:
                # Ensure last_heartbeat is timezone-aware
                if last_heartbeat.tzinfo is None:
                    last_heartbeat = last_heartbeat.replace(tzinfo=dt_module.timezone.utc)
                age = (now_utc - last_heartbeat).total_seconds()
                if age > 90:
                    transaction.set(lock_ref, {
                        "owner_id": SCHEDULER_ID,
                        "last_heartbeat": now_utc
                    })
                    logger.info(f"Scheduler lock expired for owner {owner_id}. Process {SCHEDULER_ID} is taking over.")
                    return True
            else:
                # No heartbeat timestamp exists, acquire lock
                transaction.set(lock_ref, {
                    "owner_id": SCHEDULER_ID,
                    "last_heartbeat": now_utc
                })
                return True

            return False

        transaction = db.transaction()
        acquired = transact_lock(transaction)

        if acquired:
            if not has_lock:
                logger.info(f"Process {SCHEDULER_ID} acquired/renewed the scheduler lock.")
            has_lock = True
        else:
            if has_lock:
                logger.info(f"Process {SCHEDULER_ID} lost/does not hold the scheduler lock.")
            has_lock = False

    except Exception as e:
        logger.error(f"Error checking/renewing scheduler lock: {e}")
        has_lock = False

def calculate_next_occurrence_datetime(
    start_dt: datetime,
    repeat_type: str | None,
    repeat_interval: int | None,
    repeat_unit: str | None,
    repeat_weekdays: list | None,
    now: datetime
) -> datetime | None:
    try:
        if not repeat_type:
            return None

        next_dt = start_dt

        if repeat_type == "interval":
            interval = repeat_interval if (repeat_interval and repeat_interval > 0) else 1
            unit = (repeat_unit or "").lower()

            if "minute" in unit:
                while next_dt <= now:
                    next_dt += timedelta(minutes=interval)
            elif "hour" in unit:
                while next_dt <= now:
                    next_dt += timedelta(hours=interval)
            elif "day" in unit:
                while next_dt <= now:
                    next_dt += timedelta(days=interval)
            elif "week" in unit:
                while next_dt <= now:
                    next_dt += timedelta(weeks=interval)
            elif "month" in unit:
                while next_dt <= now:
                    next_dt += relativedelta(months=interval)
            else:
                return None

        elif repeat_type == "weekday":
            if not repeat_weekdays:
                return None
            target_weekdays = []
            for w in repeat_weekdays:
                w_clean = str(w).lower().strip()
                if w_clean in WEEKDAY_MAP:
                    target_weekdays.append(WEEKDAY_MAP[w_clean])

            if not target_weekdays:
                return None

            limit = 366
            found = False
            for _ in range(limit):
                next_dt += timedelta(days=1)
                if next_dt.weekday() in target_weekdays and next_dt > now:
                    found = True
                    break
            if not found:
                return None

        else:
            return None

        return next_dt

    except Exception as e:
        logger.error(f"Error calculating next occurrence: {e}")
        return None

def get_normalized_recurrence(data: dict) -> tuple[str | None, int | None, str | None, list | None]:
    repeat_type = data.get("repeat_type")
    repeat_interval = data.get("repeat_interval")
    repeat_unit = data.get("repeat_unit")
    repeat_weekdays = data.get("repeat_weekdays")

    if not repeat_type:
        if repeat_weekdays:
            repeat_type = "weekday"
        elif repeat_unit and repeat_interval:
            unit_lower = str(repeat_unit).lower().strip()
            weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                             "mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            if unit_lower in weekday_names:
                repeat_type = "weekday"
                weekday_map = {
                    "monday": "monday", "mon": "monday",
                    "tuesday": "tuesday", "tue": "tuesday", "tues": "tuesday",
                    "wednesday": "wednesday", "wed": "wednesday",
                    "thursday": "thursday", "thu": "thursday", "thur": "thursday", "thurs": "thursday",
                    "friday": "friday", "fri": "friday",
                    "saturday": "saturday", "sat": "saturday",
                    "sunday": "sunday", "sun": "sunday"
                }
                std_day = weekday_map.get(unit_lower)
                repeat_weekdays = [std_day] if std_day else []
                repeat_interval = 1
                repeat_unit = "weekdays"
            else:
                repeat_type = "interval"
        elif repeat_unit:
            unit_lower = str(repeat_unit).lower().strip()
            weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                             "mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            if unit_lower in weekday_names:
                repeat_type = "weekday"
                weekday_map = {
                    "monday": "monday", "mon": "monday",
                    "tuesday": "tuesday", "tue": "tuesday", "tues": "tuesday",
                    "wednesday": "wednesday", "wed": "wednesday",
                    "thursday": "thursday", "thu": "thursday", "thur": "thursday", "thurs": "thursday",
                    "friday": "friday", "fri": "friday",
                    "saturday": "saturday", "sat": "saturday",
                    "sunday": "sunday", "sun": "sunday"
                }
                std_day = weekday_map.get(unit_lower)
                repeat_weekdays = [std_day] if std_day else []
                repeat_interval = 1
                repeat_unit = "weekdays"

    # Further normalization of keys
    if repeat_type == "interval":
        if repeat_interval:
            try:
                repeat_interval = int(repeat_interval)
            except ValueError:
                repeat_interval = 1
        else:
            repeat_interval = 1
            
        if repeat_unit:
            unit_clean = str(repeat_unit).lower().strip()
            if not unit_clean.endswith("s"):
                if unit_clean.startswith("min"):
                    unit_clean = "minutes"
                elif unit_clean.startswith("hour") or unit_clean.startswith("hr"):
                    unit_clean = "hours"
                elif unit_clean.startswith("day"):
                    unit_clean = "days"
                elif unit_clean.startswith("week"):
                    unit_clean = "weeks"
                elif unit_clean.startswith("month"):
                    unit_clean = "months"
                else:
                    unit_clean = unit_clean + "s"
            repeat_unit = unit_clean
    elif repeat_type == "weekday":
        repeat_interval = 1
        repeat_unit = "weekdays"
        if not repeat_weekdays:
            repeat_weekdays = []
        repeat_weekdays = [str(w).lower().strip() for w in repeat_weekdays]

    return repeat_type, repeat_interval, repeat_unit, repeat_weekdays

def calculate_next_occurrence(date_str, time_str, interval, unit):
    # Backward compatibility wrapper
    try:
        current = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %I:%M %p")
        now = datetime.now()
        
        # Determine repeat type
        unit_lower = (unit or "").lower().strip()
        weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                         "mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        if unit_lower in weekday_names:
            repeat_type = "weekday"
            repeat_weekdays = [unit_lower]
            repeat_unit = "weekdays"
        else:
            repeat_type = "interval"
            repeat_weekdays = []
            repeat_unit = unit_lower

        return calculate_next_occurrence_datetime(
            start_dt=current,
            repeat_type=repeat_type,
            repeat_interval=interval,
            repeat_unit=repeat_unit,
            repeat_weekdays=repeat_weekdays,
            now=now
        )
    except Exception as e:
        logger.error(f"Error in backward compatible calculate_next_occurrence: {e}")
        return None

def process_recurring_reminders():
    if not has_lock:
        return

    if not firebase_initialized or db is None:
        logger.warning("Firebase not initialized. Skipping process_recurring_reminders.")
        return

    try:
        now = datetime.now()
        users = db.collection("users").stream()

        for user_doc in users:
            uid = user_doc.id
            reminders_ref = (
                db.collection("users")
                .document(uid)
                .collection("reminders")
            )
            reminders = reminders_ref.stream()

            for reminder in reminders:
                data = reminder.to_dict() or {}
                text = data.get("text", "")
                date_str = data.get("date")
                time_str = data.get("time")

                if not date_str or not time_str:
                    continue

                try:
                    reminder_dt = datetime.strptime(
                        f"{date_str} {time_str}",
                        "%Y-%m-%d %I:%M %p"
                    )
                except Exception:
                    continue

                if reminder_dt > now:
                    continue

                logger.info(
                    f"Triggering reminder for user {uid}: {text}"
                )

                repeat_type, r_interval, r_unit, r_weekdays = get_normalized_recurrence(data)

                if not repeat_type:
                    try:
                        reminder.reference.delete()
                    except Exception as e:
                        logger.error(f"Delete failed: {e}")
                    continue

                next_dt = calculate_next_occurrence_datetime(
                    start_dt=reminder_dt,
                    repeat_type=repeat_type,
                    repeat_interval=r_interval,
                    repeat_unit=r_unit,
                    repeat_weekdays=r_weekdays,
                    now=now
                )

                if not next_dt:
                    try:
                        reminder.reference.delete()
                    except Exception:
                        pass
                    continue

                try:
                    reminder.reference.update({
                        "date": next_dt.strftime("%Y-%m-%d"),
                        "time": next_dt.strftime("%I:%M %p"),
                        "repeat_type": repeat_type,
                        "repeat_interval": r_interval,
                        "repeat_unit": r_unit,
                        "repeat_weekdays": r_weekdays
                    })
                except Exception as e:
                    logger.error(f"Update failed: {e}")

    except Exception as e:
        logger.error(f"Scheduler crash: {e}")

def heartbeat():
    logger.info(f"Scheduler heartbeat (Process {SCHEDULER_ID}, has_lock={has_lock})")

# Wrappers for tasks from reminder_service to enforce lock constraints
def run_send_due_reminder_emails():
    if not has_lock:
        return
    send_due_reminder_emails()

def run_cleanup_expired_reminders():
    if not has_lock:
        return
    cleanup_expired_reminders()

def start_scheduler():
    if not scheduler.running:
        # Initial lock check synchronously before running
        check_and_renew_lock()

        # Check and renew lock every 30 seconds
        scheduler.add_job(
            check_and_renew_lock,
            "interval",
            seconds=30,
            id="scheduler_lock_check",
            max_instances=1
        )

        scheduler.add_job(
            process_recurring_reminders,
            "interval",
            minutes=1,
            id="recurring_reminders",
            max_instances=1
        )

        scheduler.add_job(
            heartbeat,
            "interval",
            minutes=1,
            id="heartbeat",
            max_instances=1
        )

        scheduler.add_job(
            run_send_due_reminder_emails,
            "interval",
            minutes=1,
            id="send_emails",
            max_instances=1
        )

        scheduler.add_job(
            run_cleanup_expired_reminders,
            "interval",
            minutes=1,
            id="cleanup_reminders",
            max_instances=1
        )

        scheduler.start()
        logger.info(f"Scheduler started in process: {SCHEDULER_ID}")
