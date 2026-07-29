from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import db
from .config import TELEGRAM_BOT_TOKEN
from .handlers import common, events, friends
from .reminders import reminder_loop


def main(token: str | None = None) -> None:
    db.init_db()
    if token is None:
        token = TELEGRAM_BOT_TOKEN
    if not token:
        raise RuntimeError(
            "Bot token is not provided. Set TELEGRAM_BOT_TOKEN environment variable or pass token to main().")

    application = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .build()
    )

    # Обработчики главного меню
    application.add_handler(CommandHandler("start", common.start))
    application.add_handler(CallbackQueryHandler(common.show_main_menu, pattern="^back_to_main$"))
    application.add_handler(CallbackQueryHandler(friends.handle_friends_menu, pattern="^friends$"))
    application.add_handler(CallbackQueryHandler(friends.add_friend_start, pattern="^add_friend$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, friends.add_friend_received), group=10)
    application.add_handler(CallbackQueryHandler(friends.pending_requests_start, pattern="^pending_requests$"))
    application.add_handler(CallbackQueryHandler(friends.friend_accept_callback, pattern="^friend_accept_"))
    application.add_handler(CallbackQueryHandler(friends.friend_reject_callback, pattern="^friend_reject_"))
    application.add_handler(CallbackQueryHandler(friends.list_friends_start, pattern="^list_friends$"))
    application.add_handler(CallbackQueryHandler(friends.remove_friend_start, pattern="^remove_friend$"))
    application.add_handler(CallbackQueryHandler(friends.friend_remove_callback, pattern="^friend_remove_"))
    # Обработчики событий
    application.add_handler(CallbackQueryHandler(events.handle_events_menu, pattern="^events$"))
    application.add_handler(CallbackQueryHandler(events.event_create_start, pattern="^event_create$"))
    application.add_handler(
        CallbackQueryHandler(events.event_calendar_callback, pattern="^(cal_prev_|cal_next_|select_date_)"))
    application.add_handler(CallbackQueryHandler(events.event_type_choice, pattern="^event_type_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, events.event_type_custom_received), group=20)
    application.add_handler(CallbackQueryHandler(events.event_select_friend, pattern="^event_friend_"))
    application.add_handler(CallbackQueryHandler(events.event_select_reminder, pattern="^rem_"))
    application.add_handler(CallbackQueryHandler(events.event_confirm_create, pattern="^event_confirm_create$"))
    application.add_handler(CallbackQueryHandler(events.event_accept_callback, pattern="^accept_event_"))
    application.add_handler(CallbackQueryHandler(events.event_reject_callback, pattern="^reject_event_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, events.event_reject_reason_received), group=30)
    application.add_handler(CallbackQueryHandler(events.event_my_start, pattern="^event_my$"))
    application.add_handler(CallbackQueryHandler(events.event_delete_start, pattern="^event_delete$"))
    application.add_handler(CallbackQueryHandler(events.event_delete_confirm, pattern="^delete_event_"))
    application.add_handler(CallbackQueryHandler(events.event_delete_execute, pattern="^confirm_delete_"))

    application.add_handler(CallbackQueryHandler(events.show_time_suggestions, pattern="^show_time$"))
    application.add_handler(CallbackQueryHandler(events.handle_time_selection, pattern="^(time_|manual_time_input)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, events.event_receive_time), group=1)

    # Напоминания
    application.job_queue.run_repeating(reminder_loop, interval=60, first=10)

    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        print(f"Ошибка при работе бота: {e}")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
