# Approver

Telegram-бот для планирования событий с друзьями: заявки в друзья, календарь, подтверждение или отказ с причиной и напоминания перед событием.

**Попробовать:** [@myaligner_bot](https://t.me/myaligner_bot)

## Возможности

- **Друзья** — добавление по `@username` или ID, входящие заявки, удаление из друзей.
- **События** — создание через календарь (дни с событиями помечены), выбор времени и типа, предложение другу.
- **Ответ на приглашение** — принять или отклонить с указанием причины; создатель видит статус.
- **Редактирование и удаление** событий, список «Ожидают ответа».
- **Напоминания** — за 5 минут, 15 минут, 1 час или 1 день до события.

## Стек

Python 3.12, [python-telegram-bot](https://python-telegram-bot.org/), PostgreSQL 16, Docker Compose.

## Запуск

```bash
cp .env.example .env
# впишите токен бота от @BotFather в TELEGRAM_BOT_TOKEN и смените POSTGRES_PASSWORD
docker compose up -d --build
```

Логи: `docker compose logs -f bot`.

## Настройки (`.env`)

| Переменная | Назначение |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | токен бота от @BotFather |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | доступ к базе |
| `LOCAL_TZ` | часовой пояс пользователей (IANA), по умолчанию `Europe/Moscow` |

## Структура

```
main.py            точка входа
bot/app.py         регистрация обработчиков
bot/db.py          доступ к Postgres
bot/handlers/      друзья, события, общие экраны
bot/keyboards.py   календарь
bot/reminders.py   рассылка напоминаний
```
