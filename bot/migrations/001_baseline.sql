-- Исходная схема. IF NOT EXISTS: на уже работающей базе миграция ничего не меняет.
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT UNIQUE,
    first_name TEXT,
    last_name TEXT,
    date_joined TEXT
);

CREATE TABLE IF NOT EXISTS friends (
    user_id BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    friend_id BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted')),
    PRIMARY KEY (user_id, friend_id)
);

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
);

CREATE TABLE IF NOT EXISTS reminders (
    reminder_id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    remind_at TEXT NOT NULL,
    sent INTEGER DEFAULT 0
);
