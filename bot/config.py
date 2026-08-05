import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL") or (
    "postgresql://{user}:{password}@{host}:{port}/{db}".format(
        user=os.getenv("POSTGRES_USER", "approver"),
        password=os.getenv("POSTGRES_PASSWORD", "approver"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        db=os.getenv("POSTGRES_DB", "approver"),
    )
)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Часовой пояс пользователей бота. Задаётся явно (а не через автодетект
# tzlocal), потому что внутри Docker-контейнера нет /etc/localtime и
# автодетект молча откатывается на UTC, ломая расчёт времени напоминаний.
LOCAL_TZ = ZoneInfo(os.getenv("LOCAL_TZ", "Europe/Moscow"))
