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

## Обновление

```bash
git pull
docker compose up -d --build
```

Схема БД обновляется сама: при старте бот применяет новые файлы из `bot/migrations/` (версии записываются в таблицу `schema_migrations`). Данные хранятся в томе `approver_pgdata`; **не используйте `docker compose down -v`** — он удалит базу.

## Резервные копии

Сервис `backup` раз в сутки делает `pg_dump` в папку `./backups` (файлы `approver_*.sql.gz`) и хранит последние `BACKUP_KEEP_DAYS` дней (по умолчанию 7).

Восстановление в чистую базу:

```bash
gunzip -c backups/approver_YYYYMMDD_HHMMSS.sql.gz | docker compose exec -T db psql -U approver -d approver
```

## Доступ к базе

Порт Postgres наружу не публикуется. Для ручной работы: `docker compose exec db psql -U approver`.

## Здоровье бота

Бот раз в минуту отмечает «жив» в служебном файле; Docker healthcheck и встроенный watchdog следят за ним. Если цикл событий завис дольше 5 минут, процесс завершается и контейнер перезапускается сам.

## Настройки (`.env`)

| Переменная | Назначение |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | токен бота от @BotFather |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | доступ к базе |
| `LOCAL_TZ` | часовой пояс пользователей (IANA), по умолчанию `Europe/Moscow` |
| `BACKUP_KEEP_DAYS` | сколько дней хранить дампы БД, по умолчанию 7 |

## Структура

```
main.py            точка входа
bot/app.py         регистрация обработчиков
bot/db.py          доступ к Postgres, запуск миграций
bot/migrations/    SQL-миграции схемы (001_*.sql, 002_*.sql, ...)
bot/health.py      heartbeat и watchdog
scripts/backup.sh  ежедневный дамп БД
bot/handlers/      друзья, события, общие экраны
bot/keyboards.py   календарь
bot/reminders.py   рассылка напоминаний
```
