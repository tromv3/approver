import sqlite3
from datetime import date, datetime, timedelta

from .config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            first_name TEXT,
            last_name TEXT,
            date_joined TEXT
        );
        CREATE TABLE IF NOT EXISTS friends (
            user_id INTEGER,
            friend_id INTEGER,
            status TEXT CHECK(status IN ('pending','accepted')),
            PRIMARY KEY (user_id, friend_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
            FOREIGN KEY (friend_id) REFERENCES users (user_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            participant_id INTEGER NOT NULL,
            event_date TEXT NOT NULL,
            event_time TEXT NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            decline_reason TEXT,
            reminder_minutes INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (creator_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (participant_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS reminders (
            reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            remind_at TEXT NOT NULL,
            sent INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()
    conn.close()


# ---------------- users ----------------
def upsert_user(user_id, username, first_name, last_name, date_joined):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, date_joined) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, first_name, last_name, date_joined),
    )
    cur.execute(
        "UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE user_id = ? AND (username != ? OR first_name != ? OR last_name != ?)",
        (username, first_name, last_name, user_id, username, first_name, last_name),
    )
    conn.commit()
    conn.close()


def get_user_by_identifier(identifier: str):
    conn = get_conn()
    cur = conn.cursor()
    try:
        uid = int(identifier)
        cur.execute("SELECT user_id, username FROM users WHERE user_id = ?", (uid,))
    except ValueError:
        name = identifier.lstrip("@")
        cur.execute("SELECT user_id, username FROM users WHERE username = ?", (name,))
    row = cur.fetchone()
    conn.close()
    return row


def get_username(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# ---------------- friends ----------------
def get_friends(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT u.user_id, u.username FROM friends f JOIN users u ON f.friend_id = u.user_id WHERE f.user_id = ? AND f.status = 'accepted'",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_pending_requests(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT f.user_id, u.username FROM friends f JOIN users u ON f.user_id = u.user_id WHERE f.friend_id = ? AND f.status = 'pending'",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_friend_status(user_id: int, friend_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status FROM friends WHERE user_id = ? AND friend_id = ?", (user_id, friend_id))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def add_pending_friend_request(user_id: int, friend_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO friends (user_id, friend_id, status) VALUES (?, ?, ?)",
                (user_id, friend_id, "pending"))
    conn.commit()
    conn.close()


def accept_friend_request(sender_id: int, recipient_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE friends SET status = 'accepted' WHERE user_id = ? AND friend_id = ?",
                (sender_id, recipient_id))
    cur.execute("INSERT OR REPLACE INTO friends (user_id, friend_id, status) VALUES (?, ?, ?)",
                (recipient_id, sender_id, "accepted"))
    conn.commit()
    conn.close()


def delete_friend_request(sender_id: int, recipient_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM friends WHERE user_id = ? AND friend_id = ?", (sender_id, recipient_id))
    conn.commit()
    conn.close()


def remove_friendship(user_a: int, user_b: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM friends WHERE (user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?)",
        (user_a, user_b, user_b, user_a),
    )
    conn.commit()
    conn.close()


# ---------------- events ----------------
def get_events_on_day_for_user(user_id: int, day_str: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT event_id, creator_id, participant_id, event_date, event_time, event_type, status, decline_reason, reminder_minutes FROM events WHERE event_date = ? AND (creator_id = ? OR participant_id = ?) ORDER BY event_time",
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
           WHERE (creator_id = ? OR participant_id = ?)
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
        "SELECT DISTINCT event_date FROM events WHERE (creator_id = ? OR participant_id = ?) AND event_date >= ? AND event_date < ?",
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
        "INSERT INTO events (creator_id, participant_id, event_date, event_time, event_type, status, reminder_minutes, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
        (creator_id, participant_id, day_str, time_str, type_str, reminder_minutes, now),
    )
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def mark_event_accepted(event_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE events SET status = 'accepted', decline_reason = NULL WHERE event_id = ?", (event_id,))
    conn.commit()
    conn.close()


def mark_event_declined(event_id, reason):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE events SET status = 'declined', decline_reason = ? WHERE event_id = ?", (reason, event_id))
    conn.commit()
    conn.close()


def cancel_event(event_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE events SET status = 'cancelled' WHERE event_id = ?", (event_id,))
    conn.commit()
    conn.close()


def delete_event(event_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
    cur.execute("DELETE FROM reminders WHERE event_id = ?", (event_id,))
    conn.commit()
    conn.close()


def get_event(event_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT event_id, creator_id, participant_id, event_date, event_time, event_type, status, decline_reason, reminder_minutes FROM events WHERE event_id = ?",
        (event_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


# ---------------- reminders ----------------
def add_reminder_for_user(user_id, event_id, day_str, time_str, reminder_minutes):
    if reminder_minutes <= 0:
        return
    # naive local -> UTC shift (keeps current simple behaviour)
    dt_local = datetime.fromisoformat(f"{day_str}T{time_str}")
    offset = datetime.now() - datetime.utcnow()
    dt_utc = dt_local - offset
    remind_at = (dt_utc - timedelta(minutes=reminder_minutes)).isoformat(timespec="minutes")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO reminders (user_id, event_id, remind_at, sent) VALUES (?, ?, ?, 0)",
                (user_id, event_id, remind_at))
    conn.commit()
    conn.close()


def get_due_reminders(now_iso: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT r.reminder_id, r.user_id, e.event_date, e.event_time, e.event_type FROM reminders r JOIN events e ON r.event_id = e.event_id WHERE r.sent = 0 AND r.remind_at <= ?",
        (now_iso,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def mark_reminder_sent(reminder_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE reminders SET sent = 1 WHERE reminder_id = ?", (reminder_id,))
    conn.commit()
    conn.close()
