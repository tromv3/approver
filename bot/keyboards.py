import calendar
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import db


def build_calendar_keyboard(y: int, m: int, user_id: int, mode: str = "create") -> InlineKeyboardMarkup:
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(y, m)
    days_with_events = db.get_days_with_events_for_user_month(user_id, y, m)

    keyboard = []
    header = [
        InlineKeyboardButton("<<", callback_data=f"cal_prev_{mode}_{y}_{m}_{user_id}"),
        InlineKeyboardButton(f"{calendar.month_name[m]} {y}", callback_data="ignore"),
        InlineKeyboardButton(">>", callback_data=f"cal_next_{mode}_{y}_{m}_{user_id}"),
    ]
    keyboard.append(header)

    wk = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    keyboard.append([InlineKeyboardButton(d, callback_data="ignore") for d in wk])

    for week in month_days:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                date_str = date(y, m, day).isoformat()
                label = str(day) + ("✱" if date_str in days_with_events else "")
                row.append(InlineKeyboardButton(label, callback_data=f"select_date_{mode}_{date_str}"))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("Назад", callback_data="events")])
    return InlineKeyboardMarkup(keyboard)
