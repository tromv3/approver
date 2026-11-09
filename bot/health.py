"""Heartbeat и watchdog.

reminder_loop раз в минуту вызывает beat(). Пока цикл событий жив, файл
свежий. Docker healthcheck смотрит на возраст файла, а watchdog-поток
завершает процесс, если цикл завис дольше STALE_AFTER секунд: контейнер с
`restart: unless-stopped` тогда поднимется заново.
"""
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

HEARTBEAT_FILE = os.getenv("HEARTBEAT_FILE", "/tmp/approver_heartbeat")
STALE_AFTER = 300  # секунд


def beat() -> None:
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        logger.exception("Не удалось обновить heartbeat")


def age() -> float:
    try:
        return time.time() - os.path.getmtime(HEARTBEAT_FILE)
    except OSError:
        return float("inf")


def _watchdog() -> None:
    while True:
        time.sleep(60)
        if age() > STALE_AFTER:
            logger.critical("Heartbeat не обновлялся более %s с, перезапуск процесса", STALE_AFTER)
            os._exit(1)


def start_watchdog() -> None:
    beat()  # стартовая отметка, чтобы не убить процесс до первого запуска reminder_loop
    threading.Thread(target=_watchdog, name="watchdog", daemon=True).start()


if __name__ == "__main__":
    # Команда для Docker healthcheck: exit 0, если heartbeat свежий.
    raise SystemExit(0 if age() < STALE_AFTER else 1)
