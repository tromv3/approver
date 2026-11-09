import logging
import re

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from . import db, health
from .config import TELEGRAM_BOT_TOKEN
from .handlers import common, events, friends, paging, start, upcoming
from .handlers.common import REPLY_BUTTONS
from .reminders import reminder_loop, snooze_callback

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Необработанное исключение при обработке update: %s", update, exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ Что-то пошло не так. Попробуйте ещё раз или наберите /start.",
            )
        except Exception:
            pass


BOT_COMMANDS = [
    BotCommand("menu", "Главное меню"),
    BotCommand("today", "События на сегодня"),
    BotCommand("week", "События на 7 дней"),
    BotCommand("cancel", "Отменить текущее действие"),
    BotCommand("help", "Справка"),
]


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)


def main(token: str | None = None) -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
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
        .post_init(post_init)
        .build()
    )

    application.add_error_handler(error_handler)

    # Служебные обработчики, которые должны сработать раньше остальных
    application.add_handler(TypeHandler(Update, start.track_user), group=-2)
    reply_buttons = re.compile("^(" + "|".join(re.escape(b) for b in REPLY_BUTTONS) + ")$")
    application.add_handler(MessageHandler(filters.Regex(reply_buttons), start.reply_menu_router), group=-1)

    # Обработчики главного меню
    application.add_handler(CommandHandler("start", start.start))
    application.add_handler(CommandHandler("help", start.help_command))
    application.add_handler(CommandHandler("today", upcoming.today_command))
    application.add_handler(CommandHandler("week", upcoming.week_command))
    application.add_handler(CommandHandler("cancel", common.show_main_menu))
    application.add_handler(CommandHandler("menu", common.show_main_menu))
    application.add_handler(CallbackQueryHandler(common.ignore_callback, pattern="^ignore$"))
    application.add_handler(CallbackQueryHandler(start.help_command, pattern="^help$"))
    application.add_handler(CallbackQueryHandler(upcoming.upcoming_callback, pattern="^upcoming$"))
    application.add_handler(CallbackQueryHandler(paging.paging_callback, pattern=r"^pg:"))
    application.add_handler(CallbackQueryHandler(snooze_callback, pattern=r"^snooze_\d+_\d+$"))
    application.add_handler(CallbackQueryHandler(friends.invite_link_start, pattern="^invite_link$"))
    application.add_handler(CallbackQueryHandler(friends.invite_reset, pattern="^invite_reset$"))
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
    application.add_handler(CallbackQueryHandler(events.event_pending_sent_start, pattern="^event_pending_sent$"))
    application.add_handler(CallbackQueryHandler(events.event_edit_start, pattern="^event_edit$"))
    application.add_handler(CallbackQueryHandler(events.event_edit_choose_field, pattern=r"^edit_event_\d+$"))
    application.add_handler(CallbackQueryHandler(events.event_edit_pick_date, pattern="^edit_field_datetime$"))
    application.add_handler(CallbackQueryHandler(events.event_edit_pick_type, pattern="^edit_field_type$"))
    application.add_handler(CallbackQueryHandler(events.event_edit_type_choice, pattern="^edit_type_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, events.event_edit_type_custom_received), group=40)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, events.event_edit_receive_time), group=41)

    application.add_handler(CallbackQueryHandler(events.show_time_suggestions, pattern="^show_time$"))
    application.add_handler(CallbackQueryHandler(events.handle_time_selection, pattern="^(time_|manual_time_input)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, events.event_receive_time), group=1)

    # Напоминания и self-healing
    health.start_watchdog()
    application.job_queue.run_repeating(reminder_loop, interval=60, first=10)

    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception:
        logger.exception("Ошибка при работе бота")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
