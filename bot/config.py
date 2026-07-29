import os

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("USERS_DB_PATH", "users.db")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
