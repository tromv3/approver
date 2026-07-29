import os
import sqlite3
import calendar
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()
DB_PATH = os.getenv("USERS_DB_PATH", "users.db")

# States
(EV_MENU, EV_SEL_DATE, EV_SEL_TIME, EV_TYPE_CH, EV_TYPE_CUSTOM,
 EV_SEL_FRIEND, EV_SEL_REM, EV_CONFIRM, AWAIT_REJECT) = range(9)

STD_TYPES = ["Отдых", "Работа", "Развлечения", "Спорт", "Другое (ввести свой)"]
STD_REMS = [
    ("Нет напоминания", 0),
    ("За 5 минут", 5),
    ("За 15 минут", 15),
    ("За 1 час", 60),
    ("За 1 день", 1440)
]


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


async def send_text(update: Update, text: str, reply_markup=None):
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup)


def format_event_row(ev, user_id):
    user_1 = get_user_by_identifier(ev[1])
    user_2 = get_user_by_identifier(ev[2])
    user = user_2[1] if user_1[0] == user_id else user_1[1]
    status = "Принято" if ev[6] == 'accepted' else 'Отклонено'
    return f"#{ev[0]} — {ev[3]} {ev[4]} — {ev[5]} c {user} — статус: {status}"


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


async def handle_events_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("Создать событие", callback_data="event_create")],
        [InlineKeyboardButton("Мои события", callback_data="event_my")],
        [InlineKeyboardButton("Удалить событие", callback_data="event_delete")],
        [InlineKeyboardButton("Назад", callback_data="back_to_main")]
    ]
    await send_text(update, "Меню событий", InlineKeyboardMarkup(kb))


async def show_time_suggestions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_date = datetime.strptime(context.user_data["event_date"], "%Y-%m-%d").date()
    today = date.today()

    if selected_date < today:
        await query.edit_message_text(
            "❌ Нельзя создавать события на прошедшие даты!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
        )
        return None

    now = datetime.now()
    if selected_date == today:
        start_time = now + timedelta(minutes=30)
        current_hour = start_time.hour
        current_minute = (start_time.minute // 30) * 30
    else:
        current_hour, current_minute = 8, 0

    time_slots = []
    while current_hour < 22 or (current_hour == 22 and current_minute == 0):
        time_str = f"{current_hour:02d}:{current_minute:02d}"

        if selected_date == today:
            selected_datetime = datetime.combine(selected_date, datetime.strptime(time_str, "%H:%M").time())
            if selected_datetime < now:
                current_minute += 30
                if current_minute >= 60:
                    current_hour += 1
                    current_minute = 0
                continue

        time_slots.append(InlineKeyboardButton(time_str, callback_data=f"time_{time_str}"))
        current_minute += 30
        if current_minute >= 60:
            current_hour += 1
            current_minute = 0

    if not time_slots and selected_date == today:
        await query.edit_message_text(
            "❌ На сегодня все возможные временные слоты уже прошли!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
        )
        return None

    keyboard = [time_slots[i:i + 4] for i in range(0, len(time_slots), 4)]
    keyboard.append([InlineKeyboardButton("✏️ Ввести вручную", callback_data="manual_time_input")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="events")])

    await query.edit_message_text(
        "🕒 Выберите время или введите вручную (HH:MM):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EV_SEL_TIME


async def event_receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "event_date" not in context.user_data:
        return await show_main_menu(update, context)

    text = update.message.text.strip()

    try:
        input_time = datetime.strptime(text, "%H:%M").time()
        selected_date = datetime.strptime(context.user_data["event_date"], "%Y-%m-%d").date()
        selected_datetime = datetime.combine(selected_date, input_time)

        if selected_datetime < datetime.now():
            await update.message.reply_text("❌ Нельзя создавать события в прошедшем времени! Выберите будущее время.")
            return EV_SEL_TIME

        context.user_data["event_time"] = text
        return await show_event_type_selection(update, context)

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени. Введите в формате ЧЧ:ММ (например, 14:30) или выберите из предложенных.")
        return EV_SEL_TIME


async def handle_time_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "manual_time_input":
        await query.edit_message_text(
            "⌨️ Введите время в формате ЧЧ:ММ (например, 14:30):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="events")]])
        )
        return EV_SEL_TIME

    if query.data.startswith("time_"):
        time_str = query.data.split("_")[1]
        context.user_data["event_time"] = time_str
        await query.edit_message_text(f"✅ Выбрано время: {time_str}")
        return await show_event_type_selection(update, context)

    return None


async def show_event_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(t, callback_data=f"event_type_{t}")] for t in STD_TYPES]
    kb.append([InlineKeyboardButton("Назад", callback_data="events")])
    await send_text(update, "Выберите тип события или введите свой:", InlineKeyboardMarkup(kb))
    return EV_TYPE_CH


async def handle_friends_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [
        [InlineKeyboardButton("Добавить в друзья", callback_data="add_friend")],
        [InlineKeyboardButton("Мои друзья", callback_data="list_friends")],
        [InlineKeyboardButton("Заявки в друзья", callback_data="pending_requests")],
        [InlineKeyboardButton("Удалить из друзей", callback_data="remove_friend")],
        [InlineKeyboardButton("Назад", callback_data="back_to_main")],
        [InlineKeyboardButton("К Событиям", callback_data="events")],
    ]
    await q.edit_message_text(
        text="Раздел 'Друзья'. Выберите действие:",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def add_friend_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["adding_friend"] = True
    await send_text(
        update,
        "Введите @username или числовой ID пользователя, которого хотите добавить:",
        InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]])
    )


async def add_friend_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("adding_friend", False):
        return None

    text = update.message.text.strip()
    me = update.effective_user
    target = get_user_by_identifier(text)

    if not target:
        return await update.message.reply_text("Пользователь не найден или не запускал бота.")

    tid, _ = target
    if tid == me.id:
        return await update.message.reply_text("Нельзя добавить себя в друзья.")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status FROM friends WHERE user_id = ? AND friend_id = ?", (me.id, tid))
    row = cur.fetchone()

    if row and row[0] == "accepted":
        conn.close()
        await update.message.reply_text("Вы уже в друзьях.")
        return await show_main_menu(update, context)

    cur.execute(
        "INSERT OR IGNORE INTO friends (user_id, friend_id, status) VALUES (?, ?, ?)",
        (me.id, tid, "pending")
    )
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Принять", callback_data=f"friend_accept_{me.id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"friend_reject_{me.id}")
        ]
    ])

    try:
        await context.bot.send_message(
            chat_id=tid,
            text=f"@{me.username} отправил(а) вам заявку в друзья.",
            reply_markup=kb
        )
    except Exception:
        pass

    await update.message.reply_text("Заявка отправлена.")
    return await show_main_menu(update, context)


async def pending_requests_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    rows = get_pending_requests(user.id)

    if not rows:
        await q.edit_message_text("Нет входящих заявок.")
        return await show_main_menu(update, context)

    kb = []
    text = "Заявки:"
    for sender_id, uname in rows:
        label = f"@{uname}" if uname else str(sender_id)
        kb.append([
            InlineKeyboardButton(f"Принять {label}", callback_data=f"friend_accept_{sender_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"friend_reject_{sender_id}")
        ])
        text += f"{label}"

    kb.append([InlineKeyboardButton("Назад", callback_data="friends")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def friend_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sender_id = int(q.data.split("_")[-1])
    recipient_id = q.from_user.id

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE friends SET status = 'accepted' WHERE user_id = ? AND friend_id = ?",
        (sender_id, recipient_id)
    )
    cur.execute(
        "INSERT OR REPLACE INTO friends (user_id, friend_id, status) VALUES (?, ?, ?)",
        (recipient_id, sender_id, "accepted")
    )
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(
            chat_id=sender_id,
            text=f"Пользователь @{q.from_user.username} принял вашу заявку."
        )
        await q.edit_message_text("Заявка принята.")
    except Exception:
        pass


async def friend_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sender_id = int(q.data.split("_")[-1])
    recipient_id = q.from_user.id

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM friends WHERE user_id = ? AND friend_id = ?",
        (sender_id, recipient_id)
    )
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(
            chat_id=sender_id,
            text=f"Пользователь @{q.from_user.username} отклонил вашу заявку."
        )
    except Exception:
        pass

    await q.edit_message_text("Заявка отклонена.")
    return await show_main_menu(update, context)


async def list_friends_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rows = get_friends(q.from_user.id)

    if not rows:
        return await q.edit_message_text("У вас нет друзей.")

    text = "Ваши друзья:\n" + "".join([f"@{r[1]}\n" if r[1] else str(r[0]) for r in rows])
    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="friends")]])
    )


async def remove_friend_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rows = get_friends(q.from_user.id)

    if not rows:
        await q.edit_message_text("Нет друзей для удаления.")
        return await show_main_menu(update, context)

    kb = [[InlineKeyboardButton(f"Удалить @{r[1] or r[0]}", callback_data=f"friend_remove_{r[0]}")] for r in rows]
    kb.append([InlineKeyboardButton("Назад", callback_data="friends")])
    await q.edit_message_text(
        "Выберите друга для удаления:",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def friend_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    fid = int(q.data.split("_")[-1])
    me = q.from_user.id

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM friends WHERE (user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?)",
        (me, fid, fid, me),
    )
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(
            chat_id=fid,
            text=f"Пользователь @{q.from_user.username} удалил вас из друзей."
        )
    except Exception:
        pass

    await q.edit_message_text("Друг удалён.")
    return await show_main_menu(update, context)


def get_friends(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT u.user_id, u.username FROM friends f JOIN users u ON f.friend_id = u.user_id "
        "WHERE f.user_id = ? AND f.status = 'accepted'",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_pending_requests(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT f.user_id, u.username FROM friends f JOIN users u ON f.user_id = u.user_id "
        "WHERE f.friend_id = ? AND f.status = 'pending'",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_events_on_day_for_user(user_id: int, day_str: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT event_id, creator_id, participant_id, event_date, event_time, event_type, status, "
        "decline_reason, reminder_minutes FROM events WHERE event_date = ? AND "
        "(creator_id = ? OR participant_id = ?) ORDER BY event_time",
        (day_str, user_id, user_id),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_days_with_events_for_user_month(user_id: int, y: int, m: int):
    conn = get_conn()
    cur = conn.cursor()
    start = date(y, m, 1)
    end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    cur.execute(
        "SELECT DISTINCT event_date FROM events WHERE (creator_id = ? OR participant_id = ?) "
        "AND event_date >= ? AND event_date < ?",
        (user_id, user_id, start.isoformat(), end.isoformat()),
    )
    rows = cur.fetchall()
    conn.close()
    return set(r[0] for r in rows)


def build_calendar_keyboard(y: int, m: int, user_id: int, mode: str = "create") -> InlineKeyboardMarkup:
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(y, m)
    days_with_events = get_days_with_events_for_user_month(user_id, y, m)

    keyboard = []
    header = [
        InlineKeyboardButton("<<", callback_data=f"cal_prev_{mode}_{y}_{m}_{user_id}"),
        InlineKeyboardButton(f"{calendar.month_name[m]} {y}", callback_data="ignore"),
        InlineKeyboardButton(">>", callback_data=f"cal_next_{mode}_{y}_{m}_{user_id}"),
    ]
    keyboard.append(header)

    weekdays = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    keyboard.append([InlineKeyboardButton(d, callback_data="ignore") for d in weekdays])

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

    keyboard.append([InlineKeyboardButton("Назад", callback_data=("events" if mode == "create" else "friends"))])
    return InlineKeyboardMarkup(keyboard)


async def event_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    today = date.today()
    kb = build_calendar_keyboard(today.year, today.month, q.from_user.id, mode="create")
    await q.edit_message_text(text="Выберите дату для события:", reply_markup=kb)
    return EV_SEL_DATE


async def event_my_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    today = date.today()
    kb = build_calendar_keyboard(today.year, today.month, query.from_user.id, mode="view")
    await query.edit_message_text(
        "Календарь — дни с событиями помечены ✱. Выберите день для просмотра:",
        reply_markup=kb
    )


async def event_calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data.startswith("select_date_create_"):
        day_str = data.split("_", 3)[3]
        selected_date = datetime.strptime(day_str, "%Y-%m-%d").date()
        today = date.today()

        if selected_date < today:
            await q.edit_message_text(
                "❌ Нельзя создавать события на прошедшие даты!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
            )
            return None

        context.user_data["event_date"] = day_str
        return await show_time_suggestions(update, context)

    if data.startswith("cal_prev_"):
        _, _, mode, year, month, _ = data.split('_')
        year, month = int(year), int(month)
        prev_month = 12 if month == 1 else month - 1
        prev_year = year - 1 if month == 1 else year
        kb = build_calendar_keyboard(prev_year, prev_month, q.from_user.id, mode)
        text = "Выберите дату для события:" if mode == "create" else "Календарь событий"
        await q.edit_message_text(text=text, reply_markup=kb)
        return EV_SEL_DATE if mode == "create" else None

    elif data.startswith("cal_next_"):
        _, _, mode, year, month, _ = data.split('_')
        year, month = int(year), int(month)
        next_month = 1 if month == 12 else month + 1
        next_year = year + 1 if month == 12 else year
        kb = build_calendar_keyboard(next_year, next_month, q.from_user.id, mode)
        text = "Выберите дату для события:" if mode == "create" else "Календарь событий"
        await q.edit_message_text(text=text, reply_markup=kb)
        return EV_SEL_DATE if mode == "create" else None

    if data.startswith("select_date_view_"):
        day_str = data.split("_", 3)[3]
        events = get_events_on_day_for_user(q.from_user.id, day_str)

        if not events:
            await q.edit_message_text(
                text=f"📅 На {day_str} у вас нет событий.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="event_my")]])
            )
            return None

        text = f"📅 События на {day_str}:\n"
        text += "\n".join([format_event_row(e, q.from_user.id) for e in events])
        await q.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="event_my")]])
        )
        return None

    return None


async def event_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chosen = q.data[len("event_type_"):]

    if chosen == "Другое (ввести свой)":
        context.user_data["awaiting_event_type_custom"] = True
        await q.edit_message_text(
            text="Введите название типа события (например, Встреча с клиентом):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="events")]])
        )
        return EV_TYPE_CUSTOM

    context.user_data["event_type"] = chosen
    return await prompt_choose_friend_for_event(update, context)


async def event_type_custom_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("awaiting_event_type_custom", False):
        return None

    text = update.message.text.strip()
    if not text:
        return await update.message.reply_text("Пустой тип. Введите текст типа события:")

    context.user_data["event_type"] = text
    return await prompt_choose_friend_for_event(update, context)


async def prompt_choose_friend_for_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.callback_query.from_user if update.callback_query else update.message.from_user
    friends = get_friends(user.id)

    if not friends:
        return await send_text(
            update,
            "У вас нет друзей для предложения события. Добавьте друзей и попробуйте снова.",
            InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
        )

    kb = [[InlineKeyboardButton(f"@{u[1]}" if u[1] else str(u[0]), callback_data=f"event_friend_{u[0]}")]
          for u in friends]
    kb.append([InlineKeyboardButton("Отмена", callback_data="events")])
    await send_text(update, "Кому предложить событие? Выберите друга:", InlineKeyboardMarkup(kb))


async def event_select_friend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["event_friend_id"] = int(q.data.split("_")[-1])

    kb = [[InlineKeyboardButton(label, callback_data=f"rem_{minutes}")]
          for label, minutes in STD_REMS]
    kb.append([InlineKeyboardButton("Отмена", callback_data="events")])

    await q.edit_message_text(
        text="Выберите напоминание (когда бот должен напомнить вам перед событием):",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return EV_SEL_REM


async def event_select_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    minutes = int(q.data.split("_")[-1])
    context.user_data["event_reminder_minutes"] = minutes

    date_str = context.user_data.get("event_date")
    time_str = context.user_data.get("event_time")
    type_str = context.user_data.get("event_type")
    friend_id = context.user_data.get("event_friend_id")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE user_id = ?", (friend_id,))
    row = cur.fetchone()
    conn.close()
    friend_username = row[0] if row and row[0] else str(friend_id)

    text = (
        f"Подтвердите создание события:\nДата: {date_str}\nВремя: {time_str}\n"
        f"Тип: {type_str}\nКому: @{friend_username}\n"
        f"Напомнить: {minutes} минут(ы) до события\n\nСоздать?"
    )

    kb = [
        [InlineKeyboardButton("Создать", callback_data="event_confirm_create")],
        [InlineKeyboardButton("Отмена", callback_data="events")]
    ]

    await q.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(kb))
    return EV_CONFIRM


async def event_confirm_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    creator_id = q.from_user.id
    participant_id = context.user_data.get("event_friend_id")
    day_str = context.user_data.get("event_date")
    time_str = context.user_data.get("event_time")
    type_str = context.user_data.get("event_type")
    reminder_minutes = context.user_data.get("event_reminder_minutes", 0)

    try:
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        cur.execute(
            "INSERT INTO events (creator_id, participant_id, event_date, event_time, event_type, "
            "status, reminder_minutes, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
            (creator_id, participant_id, day_str, time_str, type_str, reminder_minutes, now),
        )
        event_id = cur.lastrowid
        conn.commit()
        conn.close()
    except Exception as e:
        print("DB ERROR create_event", e)
        return await q.edit_message_text("Не удалось создать событие.")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Принять", callback_data=f"accept_event_{event_id}")],
        [InlineKeyboardButton("Отклонить", callback_data=f"reject_event_{event_id}")]
    ])

    try:
        await context.bot.send_message(
            chat_id=participant_id,
            text=f"@{q.from_user.username} предлагает вам событие:\n📅 {day_str} 🕒 {time_str}\n🎯 {type_str}",
            reply_markup=kb
        )
    except Exception as e:
        print("BOT SEND WARNING", e)

    await q.edit_message_text(
        "Событие предложено. Ожидайте ответа.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
    )

    for key in ("event_date", "event_time", "event_type", "event_friend_id", "event_reminder_minutes"):
        context.user_data.pop(key, None)
    return None


async def event_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT event_id, creator_id, event_date, event_time, event_type, status 
           FROM events 
           WHERE (creator_id = ? OR participant_id = ?) 
           AND status != 'cancelled'
           ORDER BY event_date DESC, event_time DESC""",
        (user_id, user_id)
    )
    events = cur.fetchall()
    conn.close()

    if not events:
        await query.edit_message_text(
            "У вас нет активных событий для удаления.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
        )
        return

    keyboard = []
    for event in events:
        event_id, creator_id, date, time, etype, status = event
        prefix = "🟢" if status == "accepted" else "🟡" if status == "pending" else "🔴"
        text = f"{prefix} {date} {time} - {etype} (ID: {event_id})"
        if creator_id == user_id:
            text += " [вы создатель]"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"delete_event_{event_id}")])

    keyboard.append([InlineKeyboardButton("Назад", callback_data="events")])

    await query.edit_message_text(
        "Выберите событие для удаления:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def event_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split('_')[-1])
    user_id = query.from_user.id

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT creator_id, participant_id, event_date, event_time, event_type FROM events WHERE event_id = ?",
        (event_id,)
    )
    event = cur.fetchone()

    if not event:
        await query.edit_message_text(
            "Событие не найдено или уже удалено.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="event_delete")]])
        )
        conn.close()
        return

    creator_id, participant_id, date, time, etype = event

    if user_id not in (creator_id, participant_id):
        await query.edit_message_text(
            "Вы не можете удалить это событие.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="event_delete")]])
        )
        conn.close()
        return

    text = (
        f"Вы уверены, что хотите удалить событие?\n\n"
        f"📅 Дата: {date}\n"
        f"🕒 Время: {time}\n"
        f"🎯 Тип: {etype}\n\n"
        f"ID: {event_id}"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{event_id}")],
        [InlineKeyboardButton("❌ Нет, отмена", callback_data="event_delete")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    conn.close()


async def event_delete_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split('_')[-1])
    user_id = query.from_user.id

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT creator_id, participant_id, event_date, event_time, event_type FROM events WHERE event_id = ?",
        (event_id,)
    )
    event = cur.fetchone()

    if not event:
        await query.edit_message_text(
            "Событие не найдено или уже удалено.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="events")]])
        )
        conn.close()
        return

    creator_id, participant_id, date, time, etype = event

    cur.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
    cur.execute("DELETE FROM reminders WHERE event_id = ?", (event_id,))
    conn.commit()
    conn.close()

    other_user_id = participant_id if user_id == creator_id else creator_id
    try:
        await context.bot.send_message(
            chat_id=other_user_id,
            text=f"Событие было удалено:\n{date} {time} - {etype}\nID: {event_id}"
        )
    except Exception as e:
        print(f"Не удалось уведомить пользователя {other_user_id}: {e}")

    await query.edit_message_text(
        "Событие успешно удалено.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Вернуться в меню", callback_data="events")]])
    )


async def event_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    event_id = int(q.data.split("_")[-1])
    ev = get_event(event_id)

    if not ev:
        return await q.edit_message_text("Событие не найдено или уже удалено.")

    user_id = q.from_user.id
    if user_id != ev[2]:
        return await q.answer("Вы не можете принять это событие.", show_alert=True)

    mark_event_accepted(event_id)
    ev2 = get_event(event_id)
    reminder_minutes = ev2[8] or 0

    if reminder_minutes > 0:
        add_reminder_for_user(ev2[1], event_id, ev2[3], ev2[4], reminder_minutes)
        add_reminder_for_user(ev2[2], event_id, ev2[3], ev2[4], reminder_minutes)

    try:
        await context.bot.send_message(
            chat_id=ev2[1],
            text=f"Пользователь @{q.from_user.username} принял ваше приглашение на событие #{event_id} ({ev2[3]} {ev2[4]})."
        )
        await context.bot.send_message(
            chat_id=ev2[2],
            text=f"Вы подтвердили участие в событии #{event_id} ({ev2[3]} {ev2[4]})."
        )
    except Exception:
        pass

    try:
        await q.edit_message_text(f"Вы приняли событие #{event_id} — спасибо!")
    except Exception:
        pass


async def event_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    event_id = int(q.data.split("_")[-1])
    ev = get_event(event_id)

    if not ev:
        return await q.edit_message_text("Событие не найдено или уже удалено.")

    if q.from_user.id != ev[2]:
        return await q.answer("Вы не можете отклонить это событие.", show_alert=True)

    context.user_data["awaiting_reject_for_event"] = event_id
    await q.edit_message_text(
        "Вы решили отклонить событие. Укажите причину отказа (или введите '-' для пустой причины):"
    )
    return AWAIT_REJECT


async def event_reject_reason_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "awaiting_reject_for_event" not in context.user_data:
        return

    text = update.message.text.strip()
    event_id = context.user_data.pop("awaiting_reject_for_event")
    mark_event_declined(event_id, text if text != "-" else "")
    ev = get_event(event_id)

    if ev:
        try:
            await context.bot.send_message(
                chat_id=ev[1],
                text=f"Пользователь отклонил ваше событие #{event_id}. Причина: {text or '(не указана)'}"
            )
        except Exception:
            pass

    await update.message.reply_text("Отказ отправлен.")


def get_event(event_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT event_id, creator_id, participant_id, event_date, event_time, event_type, "
        "status, decline_reason, reminder_minutes FROM events WHERE event_id = ?",
        (event_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def mark_event_accepted(event_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE events SET status = 'accepted', decline_reason = NULL WHERE event_id = ?",
        (event_id,)
    )
    conn.commit()
    conn.close()


def mark_event_declined(event_id, reason):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE events SET status = 'declined', decline_reason = ? WHERE event_id = ?",
        (reason, event_id)
    )
    conn.commit()
    conn.close()


def add_reminder_for_user(user_id, event_id, day_str, time_str, reminder_minutes):
    if reminder_minutes <= 0:
        return

    dt_local = datetime.fromisoformat(f"{day_str}T{time_str}")
    offset = datetime.now() - datetime.utcnow()
    dt_utc = dt_local - offset
    remind_at = (dt_utc - timedelta(minutes=reminder_minutes)).isoformat(timespec="minutes")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reminders (user_id, event_id, remind_at, sent) VALUES (?, ?, ?, 0)",
        (user_id, event_id, remind_at)
    )
    conn.commit()
    conn.close()


async def reminder_loop(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.utcnow().isoformat(timespec="minutes")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT r.reminder_id, r.user_id, e.event_date, e.event_time, e.event_type "
        "FROM reminders r JOIN events e ON r.event_id = e.event_id "
        "WHERE r.sent = 0 AND r.remind_at <= ?",
        (now,),
    )
    reminders = cur.fetchall()

    for reminder_id, user_id, ev_date, ev_time, ev_type in reminders:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⏰ Напоминание!\n📅 {ev_date} 🕒 {ev_time}\n🎯 {ev_type}"
            )
        except Exception as e:
            print("Ошибка отправки напоминания:", e)

        cur.execute("UPDATE reminders SET sent = 1 WHERE reminder_id = ?", (reminder_id,))

    conn.commit()
    conn.close()


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("Друзья", callback_data="friends")],
        [InlineKeyboardButton("События", callback_data="events")]
    ]
    await send_text(update, "Главное меню. Выберите раздел:", InlineKeyboardMarkup(kb))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    date_joined = (update.message.date or datetime.utcnow()).isoformat()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, date_joined) "
        "VALUES (?, ?, ?, ?, ?)",
        (u.id, u.username, u.first_name, u.last_name, date_joined),
    )
    cur.execute(
        "UPDATE users SET username = ?, first_name = ?, last_name = ? "
        "WHERE user_id = ? AND (username != ? OR first_name != ? OR last_name != ?)",
        (u.username, u.first_name, u.last_name, u.id, u.username, u.first_name, u.last_name),
    )
    conn.commit()
    conn.close()
    await show_main_menu(update, context)


def main(token: str | None = None) -> None:
    init_db()
    if token is None:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Bot token is not provided. Set TELEGRAM_BOT_TOKEN environment variable or pass token to main().")

    application = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .build()
    )

    # Main menu handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^back_to_main$"))

    # Friends handlers
    application.add_handler(CallbackQueryHandler(handle_friends_menu, pattern="^friends$"))
    application.add_handler(CallbackQueryHandler(add_friend_start, pattern="^add_friend$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_friend_received), group=10)
    application.add_handler(CallbackQueryHandler(pending_requests_start, pattern="^pending_requests$"))
    application.add_handler(CallbackQueryHandler(friend_accept_callback, pattern="^friend_accept_"))
    application.add_handler(CallbackQueryHandler(friend_reject_callback, pattern="^friend_reject_"))
    application.add_handler(CallbackQueryHandler(list_friends_start, pattern="^list_friends$"))
    application.add_handler(CallbackQueryHandler(remove_friend_start, pattern="^remove_friend$"))
    application.add_handler(CallbackQueryHandler(friend_remove_callback, pattern="^friend_remove_"))

    # Events handlers
    application.add_handler(CallbackQueryHandler(handle_events_menu, pattern="^events$"))
    application.add_handler(CallbackQueryHandler(event_create_start, pattern="^event_create$"))
    application.add_handler(
        CallbackQueryHandler(event_calendar_callback, pattern="^(cal_prev_|cal_next_|select_date_)"))
    application.add_handler(CallbackQueryHandler(event_type_choice, pattern="^event_type_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, event_type_custom_received), group=20)
    application.add_handler(CallbackQueryHandler(event_select_friend, pattern="^event_friend_"))
    application.add_handler(CallbackQueryHandler(event_select_reminder, pattern="^rem_"))
    application.add_handler(CallbackQueryHandler(event_confirm_create, pattern="^event_confirm_create$"))
    application.add_handler(CallbackQueryHandler(event_accept_callback, pattern="^accept_event_"))
    application.add_handler(CallbackQueryHandler(event_reject_callback, pattern="^reject_event_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, event_reject_reason_received), group=30)
    application.add_handler(CallbackQueryHandler(event_my_start, pattern="^event_my$"))
    application.add_handler(CallbackQueryHandler(event_delete_start, pattern="^event_delete$"))
    application.add_handler(CallbackQueryHandler(event_delete_confirm, pattern="^delete_event_"))
    application.add_handler(CallbackQueryHandler(event_delete_execute, pattern="^confirm_delete_"))

    # Time selection handlers
    application.add_handler(CallbackQueryHandler(show_time_suggestions, pattern="^show_time$"))
    application.add_handler(CallbackQueryHandler(handle_time_selection, pattern="^(time_|manual_time_input)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, event_receive_time), group=1)

    # Reminders
    application.job_queue.run_repeating(reminder_loop, interval=60, first=10)

    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        print(f"Ошибка при работе бота: {e}")
    finally:
        conn = get_conn()
        conn.close()


if __name__ == "__main__":
    main()