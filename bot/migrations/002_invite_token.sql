-- Персональный токен для ссылки-приглашения в друзья (t.me/<bot>?start=inv_<токен>).
ALTER TABLE users ADD COLUMN IF NOT EXISTS invite_token TEXT UNIQUE;
