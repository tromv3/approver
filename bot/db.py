import logging
import time
from datetime import date, datetime, timedelta, timezone

import psycopg
import tzlocal

from .config import DATABASE_URL

LOCAL_TZ = tzlocal.get_localzone()
logger = logging.getLogger(__name__)


def get_conn():
    return psycopg.connect(DATABASE_URL)


def init_db():
    last_error = None
    for attempt in range(10):
        try:
            conn = get_conn()
            break
        except psycopg.OperationalError as e:
            last_error = e
            logger.warning("Postgres недоступен, повтор через 2с (попытка %s/10): %s", attempt + 1, e)
            time.sleep(2)
    else:
        raise RuntimeError(f"Не удалось подключиться к Postgres: {last_error}")

    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT UNIQUE,
            first_name TEXT,
            last_name TEXT,
            date_joined TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS friends (
            user_id BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
            friend_id BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK (status IN ('pending', 'accepted')),
            PRIMARY KEY (user_id, friend_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id SERIAL PRIMARY KEY,
            creator_id BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
            participant_id BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
            event_date TEXT NOT NULL,
            event_time TEXT NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            decline_reason TEXT,
            reminder_minutes INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            reminder_id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
            event_id INTEGER NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
            remind_at TEXT NOT NULL,
            sent INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()


# ---------------- users ----------------
def upsert_user(user_id, username, first_name, last_name, date_joined):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (user_id, username, first_name, last_name, date_joined)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name
        """,
        (user_id, username, first_name, last_name, date_joined),
    )
    conn.commit()
    conn.close()


def get_user_by_identifier(identifier: str):
    conn = get_conn()
    cur = conn.cursor()
    try:
        uid = int(identifier)
        cur.execute("SELECT user_id, username FROM users WHERE user_id = %s", (uid,))
    except ValueError:
        name = identifier.lstrip("@")
        cur.execute("SELECT user_id, username FROM users WHERE lower(username) = lower(%s)", (name,))
    row = cur.fetchone()
    conn.close()
    return row


def get_username(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# ---------------- friends ----------------
def get_friends(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT u.user_id, u.username FROM friends f JOIN users u ON f.friend_id = u.user_id WHERE f.user_id = %s AND f.status = 'accepted'",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_pending_requests(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT f.user_id, u.username FROM friends f JOIN users u ON f.user_id = u.user_id WHERE f.friend_id = %s AND f.status = 'pending'",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_friend_status(user_id: int, friend_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status FROM friends WHERE user_id = %s AND friend_id = %s", (user_id, friend_id))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def add_pending_friend_request(user_id: int, friend_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO friends (user_id, friend_id, status) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (user_id, friend_id, "pending"),
    )
    conn.commit()
    conn.close()


def accept_friend_request(sender_id: int, recipient_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE friends SET status = 'accepted' WHERE user_id = %s AND friend_id = %s",
                (sender_id, recipient_id))
    cur.execute(
        """
        INSERT INTO friends (user_id, friend_id, status) VALUES (%s, %s, 'accepted')
        ON CONFLICT (user_id, friend_id) DO UPDATE SET status = 'accepted'
        """,
        (recipient_id, sender_id),
    )
    conn.commit()
    conn.close()


def delete_friend_request(sender_id: int, recipient_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM friends WHERE user_id = %s AND friend_id = %s", (sender_id, recipient_id))
    conn.commit()
    conn.close()


def remove_friendship(user_a: int, user_b: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM friends WHERE (user_id = %s AND friend_id = %s) OR (user_id = %s AND friend_id = %s)",
        (user_a, user_b, user_b, user_a),
    )
    conn.commit()
    conn.close()


# ---------------- events ----------------
def get_events_on_day_for_user(user_id: int, day_str: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT event_id, creator_id, participant_id, event_date, event_time, event_type, status, decline_reason, reminder_minutes FROM events WHERE event_date = %s AND (creator_id = %s OR participant_id = %s) ORDER BY event_time",
        (day_str, user_id, user_id),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_active_events_for_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT event_id, creator_id, event_date, event_time, event_type, status
           FROM events
           WHERE (creator_id = %s OR participant_id = %s)
           AND status != 'cancelled'
           ORDER BY event_date DESC, event_time DESC""",
        (user_id, user_id),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_days_with_events_for_user_month(user_id: int, y: int, m: int):
    conn = get_conn()
    cur = conn.cursor()
    start = date(y, m, 1)
    if m == 12:
        end = date(y + 1, 1, 1)
    else:
        end = date(y, m + 1, 1)
    cur.execute(
        "SELECT DISTINCT event_date FROM events WHERE (creator_id = %s OR participant_id = %s) AND event_date >= %s AND event_date < %s",
        (user_id, user_id, start.isoformat(), end.isoformat()),
    )
    rows = cur.fetchall()
    conn.close()
    return set(r[0] for r in rows)


def create_event(creator_id, participant_id, day_str, time_str, type_str, reminder_minutes):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        "INSERT INTO events (creator_id, participant_id, event_date, event_time, event_type, status, reminder_minutes, created_at) VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s) RETURNING event_id",
        (creator_id, participant_id, day_str, time_str, type_str, reminder_minutes, now),
    )
    eid = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return eid


def mark_event_accepted(event_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE events SET status = 'accepted', decline_reason = NULL WHERE event_id = %s", (event_id,))
    conn.commit()
    conn.close()


def mark_event_declined(event_id, reason):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE events SET status = 'declined', decline_reason = %s WHERE event_id = %s", (reason, event_id))
    conn.commit()
    conn.close()


def cancel_event(event_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE events SET status = 'cancelled' WHERE event_id = %s", (event_id,))
    conn.commit()
    conn.close()


def delete_event(event_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE event_id = %s", (event_id,))
    cur.execute("DELETE FROM reminders WHERE event_id = %s", (event_id,))
    conn.commit()
    conn.close()


def get_event(event_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT event_id, creator_id, participant_id, event_date, event_time, event_type, status, decline_reason, reminder_minutes FROM events WHERE event_id = %s",
        (event_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


# ---------------- reminders ----------------
def add_reminder_for_user(user_id, event_id, day_str, time_str, reminder_minutes):
    if reminder_minutes <= 0:
        return
    dt_local = datetime.fromisoformat(f"{day_str}T{time_str}").replace(tzinfo=LOCAL_TZ)
    dt_utc = dt_local.astimezone(timezone.utc).replace(tzinfo=None)
    remind_at = (dt_utc - timedelta(minutes=reminder_minutes)).isoformat(timespec="minutes")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO reminders (user_id, event_id, remind_at, sent) VALUES (%s, %s, %s, 0)",
                (user_id, event_id, remind_at))
    conn.commit()
    conn.close()


def claim_due_reminders(now_iso: str):
    """Atomically select due, unsent reminders and mark them as sent.

    A single UPDATE ... RETURNING claims and returns the rows in one
    round trip; Postgres's row-level locking means two overlapping calls
    (e.g. a slow job run still in flight when the next one fires) can't
    both claim the same reminder and send it twice.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE reminders r
        SET sent = 1
        FROM events e
        WHERE r.event_id = e.event_id
          AND r.sent = 0
          AND r.remind_at <= %s
        RETURNING r.reminder_id, r.user_id, e.event_date, e.event_time, e.event_type
        """,
        (now_iso,),
    )
    rows = cur.fetchall()
    conn.commit()
    conn.close()
    return rows
