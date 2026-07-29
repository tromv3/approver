# Conversation states
(EV_MENU, EV_SEL_DATE, EV_SEL_TIME, EV_TYPE_CH, EV_TYPE_CUSTOM, EV_SEL_FRIEND, EV_SEL_REM, EV_CONFIRM,
 AWAIT_REJECT) = range(9)

STD_TYPES = ["Отдых", "Работа", "Развлечения", "Спорт", "Другое (ввести свой)"]
STD_REMS = [("Нет напоминания", 0), ("За 5 минут", 5), ("За 15 минут", 15), ("За 1 час", 60), ("За 1 день", 1440)]
