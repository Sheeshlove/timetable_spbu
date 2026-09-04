"""Переводы интерфейса бота.

Язык хранится у пользователя в подписке и подставляется в хендлеры
middleware'ом. Ключи одинаковые для всех языков; если перевода нет, берётся
русский вариант, а затем сам ключ — так забытая строка видна сразу и ничего
не падает.

Тот же код языка уходит на сайт расписания: там своя культурная кука, из-за
которой названия занятий приходят по-русски или по-английски.
"""

from __future__ import annotations

DEFAULT_LANG = "ru"

# Код языка бота -> значение clientCultureName на timetable.spbu.ru
SITE_CULTURES = {"ru": "ru", "en": "en-us"}

LANGUAGE_NAMES = {"ru": "🇷🇺 Русский", "en": "🇬🇧 English"}

WEEKDAYS = {
    "ru": (
        "понедельник", "вторник", "среда", "четверг",
        "пятница", "суббота", "воскресенье",
    ),
    "en": (
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday",
    ),
}

MONTHS_IN_DATE = {
    "ru": (
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ),
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
}

MONTHS_STANDALONE = {
    "ru": (
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    ),
    "en": MONTHS_IN_DATE["en"],
}

TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        # --- знакомство ---
        "choose_language": "Выберите язык / Choose your language",
        "language_saved": "Язык переключён на русский.",
        "greeting": (
            "Привет! Я присылаю расписание программы «{program}» "
            "с сайта timetable.spbu.ru.\n\n"
            "Ещё я умею хранить заметки и присылать их в нужный день: /note"
        ),
        "ask_last_name": (
            "Как ваша фамилия? Напишите её — по списку программы я определю ваши "
            "когорты и буду показывать только ваши занятия.\n\n"
            "Можно писать по-русски («Иванов») или латиницей, как в ведомости "
            "(«Ivanov»)."
        ),
        "not_found": (
            "Не нашёл такой фамилии в списке 🤔\n\n"
            "Проверьте написание или пришлите фамилию вместе с именем. "
            "Если вас нет в списке, нажмите кнопку — покажу расписание всей программы."
        ),
        "no_cohorts": (
            "Хорошо, буду показывать расписание всей программы целиком, без деления "
            "на когорты.\nУказать фамилию позже можно в «⚙️ Настройки»."
        ),
        "is_it_you": "Это вы? <b>{name}</b>",
        "several_matches": "Нашёл несколько совпадений — выберите себя:",
        "saved_student": "Записал: <b>{name}</b>",
        "list_outdated": "Список устарел, напишите фамилию ещё раз.",
        "record_not_found": "Не нашёл эту запись, попробуйте ещё раз.",
        # --- периодичность и время ---
        "ask_frequency": "Как часто присылать расписание?",
        "ask_time": (
            "Периодичность: <b>{frequency}</b>.\n\nВ какое время присылать? "
            "Часовой пояс — {tz}."
        ),
        "ask_time_short": "В какое время присылать? Часовой пояс — {tz}.",
        "done": "Готово! ✅",
        "menu_hint": "Расписание можно посмотреть в любой момент кнопками ниже.",
        # --- карточка настроек ---
        "settings_title": "<b>Ваши настройки</b>",
        "settings_program": "🎓 Программа: {program}",
        "settings_language": "🌐 Язык: {language}",
        "settings_course_language": "🗣 Иностранный язык: {course}",
        "settings_student": "👤 Вы: {name}",
        "settings_student_missing": (
            "👤 Вы: {name} (в текущем списке не найдены — обновите фамилию)"
        ),
        "settings_no_student": "👤 Фамилия не указана — показываю расписание всей программы",
        "settings_filter_all": "🔎 Показываю: всё расписание",
        "settings_filter_mine": "🔎 Показываю: только занятия моих когорт",
        "settings_frequency": "🔔 Рассылка: {frequency}",
        "settings_time": "⏰ Время: {time}",
        "settings_next_run": "➡️ Следующая отправка: {moment}",
        "cohorts_title": "<b>Ваши когорты</b>",
        "cohorts_empty": "Когорты для вас в списке не указаны.",
        "cohorts_unknown": "Фамилия не указана или вас нет в списке программы. Указать: /setup",
        "ask_course_language": (
            "Какой иностранный язык вы изучаете? Языковые пары идут параллельными "
            "потоками, и я оставлю в расписании только ваш."
        ),
        "ask_course_teacher": (
            "У этого языка несколько групп. Выберите своего преподавателя — "
            "или «Любая группа», если пока не знаете."
        ),
        "course_language_saved": "Записал: <b>{course}</b>",
        "course_language_none": "Хорошо, языковые пары показывать не буду.",
        "course_language_all": "Хорошо, буду показывать все языковые пары.",
        "hidden_language_note": "Скрыто чужих языковых пар: {count}.",
        "btn_course_none": "Не изучаю",
        "btn_course_all": "Показывать все",
        "btn_any_teacher": "Любая группа",
        "btn_settings_course_language": "🗣 Иностранный язык",
        "course_language_unknown": (
            "Не удалось получить список языков с сайта — вот обычный набор."
        ),
        "changes_title": "🔄 Расписание изменилось",
        "changes_added": "➕ Добавилось",
        "changes_removed": "➖ Убрали",
        "changes_moved": "🔀 Перенесли",
        "changes_edited": "✏️ Изменилось",
        "changes_was": "было: {value}",
        "changes_now": "стало: {value}",
        "changes_field_locations": "аудитория",
        "changes_field_educators": "преподаватель",
        "changes_hint": "Я слежу за расписанием сам; выключить — в «⚙️ Настройки».",
        "settings_notify_on": "🔄 Слежу за изменениями расписания",
        "settings_notify_off": "🔄 За изменениями расписания не слежу",
        "btn_settings_notify_on": "🔄 Следить за изменениями",
        "btn_settings_notify_off": "🔕 Не следить за изменениями",
        "toast_notify_on": "Буду сообщать об изменениях",
        "toast_notify_off": "Больше не слежу за изменениями",
        # --- расписание ---
        "loading": "Смотрю расписание…",
        "site_down": "Сайт расписания не отвечает 😕 Попробуйте позже.",
        "site_down_setup": (
            "Сайт расписания сейчас не отвечает 😕\nПопробуйте ещё раз через пару минут: /start"
        ),
        "not_configured": "Сначала напишите фамилию — это займёт полминуты: /setup",
        "no_classes": "Занятий на этот период нет 🎉",
        "no_classes_day": "  — занятий нет",
        "open_on_site": "Открыть на сайте",
        "canceled": "отменено",
        "hidden_note": "Скрыто занятий других когорт: {count}. Показать всё: «⚙️ Настройки».",
        "not_in_roster": "Вас нет в текущем списке программы — показываю всё расписание.",
        "header_day": "Расписание на {date}",
        "header_week": "Расписание на неделю {start} — {end}",
        "header_month": "Расписание на {month} {year}",
        "header_range": "Расписание {start} — {end}",
        # --- заметки ---
        "note_ask_text": "Напишите текст заметки — я пришлю его в выбранный день.",
        "note_ask_day": "Когда напомнить?",
        "note_ask_custom_day": (
            "Напишите день: <code>05.09</code>, <code>05.09.2026 18:30</code>, "
            "<code>5 сентября</code>, <code>через 3 дня</code> или <code>в пятницу</code>."
        ),
        "note_saved": (
            "Записал ✅\nПришлю {date} в {time}.\nСписок заметок: /notes, удалить: /delnote {id}"
        ),
        "note_draft": "Сохранить это как заметку? Выберите день, когда её прислать.",
        "note_bad_date": "Не понял дату 🤔 ",
        "note_lost": "Текст заметки потерялся",
        "notes_title": "<b>Запланированные заметки</b>",
        "notes_empty": "У вас нет запланированных заметок.",
        "notes_delete_hint": "Удалить: /delnote &lt;номер&gt;",
        "note_reminder": "📝 <b>Ваша заметка на {date}</b>",
        "note_deleted": "Удалил 🗑",
        "note_not_found": "Заметка не найдена.",
        "note_need_number": "Укажите номер заметки: /delnote 12 (номера — в /notes)",
        # --- прочее ---
        "stopped": "Рассылка выключена, настройки удалены. Вернуться: /setup",
        "setup_first": "Сначала /setup",
        "group_label": "👥 {name}",
        # --- кнопки ---
        "btn_today": "📅 Сегодня",
        "btn_week": "🗓 Неделя",
        "btn_notes": "📝 Заметки",
        "btn_settings": "⚙️ Настройки",
        "btn_placeholder": "Выберите действие или напишите заметку",
        "btn_its_me": "✅ Это я",
        "btn_retry_name": "🔁 Ввести фамилию заново",
        "btn_not_in_list": "Меня нет в списке",
        "btn_daily": "Раз в день",
        "btn_weekly": "Раз в неделю",
        "btn_monthly": "Раз в месяц",
        "btn_off": "Не присылать",
        "btn_settings_freq": "🔔 Периодичность",
        "btn_settings_time": "⏰ Время отправки",
        "btn_settings_show_all": "📋 Показывать всё расписание",
        "btn_settings_show_mine": "🔎 Показывать только мою когорту",
        "btn_settings_student": "🎓 Сменить фамилию",
        "btn_settings_language": "🌐 Язык / Language",
        "btn_today_note": "Сегодня",
        "btn_tomorrow": "Завтра",
        "btn_day_after": "Послезавтра",
        "btn_in_a_week": "Через неделю",
        "btn_other_date": "📆 Другая дата",
        "btn_cancel": "❌ Отмена",
        "btn_new_note": "➕ Новая заметка",
        "btn_note_list": "📋 Список заметок",
        "canceled_action": "Отменено",
        # --- периодичность ---
        "freq_daily": "раз в день",
        "freq_weekly": "раз в неделю",
        "freq_monthly": "раз в месяц",
        "freq_off": "рассылка выключена",
        "toast_show_all": "Показываю всё расписание",
        "toast_show_mine": "Показываю только мои когорты",
    },
    "en": {
        "choose_language": "Choose your language / Выберите язык",
        "language_saved": "Language switched to English.",
        "greeting": (
            "Hi! I send the timetable for the «{program}» programme "
            "from timetable.spbu.ru.\n\n"
            "I can also keep notes and send them back on the day you pick: /note"
        ),
        "ask_last_name": (
            "What is your last name? Type it — I will look up your cohorts in the "
            "programme roster and show only your classes.\n\n"
            "You can type it in Latin letters as in the roster («Ivanov») or in "
            "Russian («Иванов»)."
        ),
        "not_found": (
            "I could not find that last name in the roster 🤔\n\n"
            "Check the spelling or send your last name together with your first name. "
            "If you are not on the list, tap the button — I will show the whole "
            "programme timetable."
        ),
        "no_cohorts": (
            "Fine, I will show the whole programme timetable without splitting it by "
            "cohorts.\nYou can set your last name later in «⚙️ Settings»."
        ),
        "is_it_you": "Is this you? <b>{name}</b>",
        "several_matches": "Found several matches — pick yourself:",
        "saved_student": "Saved: <b>{name}</b>",
        "list_outdated": "That list is stale, please type your last name again.",
        "record_not_found": "I could not find that record, please try again.",
        "ask_frequency": "How often should I send the timetable?",
        "ask_time": (
            "Frequency: <b>{frequency}</b>.\n\nAt what time should I send it? "
            "Time zone — {tz}."
        ),
        "ask_time_short": "At what time should I send it? Time zone — {tz}.",
        "done": "All set! ✅",
        "menu_hint": "You can check the timetable any time with the buttons below.",
        "settings_title": "<b>Your settings</b>",
        "settings_program": "🎓 Programme: {program}",
        "settings_language": "🌐 Language: {language}",
        "settings_course_language": "🗣 Foreign language: {course}",
        "settings_student": "👤 You: {name}",
        "settings_student_missing": (
            "👤 You: {name} (not in the current roster — update your last name)"
        ),
        "settings_no_student": "👤 No last name set — showing the whole programme timetable",
        "settings_filter_all": "🔎 Showing: the whole timetable",
        "settings_filter_mine": "🔎 Showing: only my cohorts' classes",
        "settings_frequency": "🔔 Digest: {frequency}",
        "settings_time": "⏰ Time: {time}",
        "settings_next_run": "➡️ Next delivery: {moment}",
        "cohorts_title": "<b>Your cohorts</b>",
        "cohorts_empty": "The roster lists no cohorts for you.",
        "cohorts_unknown": "No last name set, or you are not in the roster. Set it: /setup",
        "ask_course_language": (
            "Which foreign language do you study? Language classes run in parallel "
            "streams, and I will keep only yours in the timetable."
        ),
        "ask_course_teacher": (
            "This language has several groups. Pick your teacher — or «Any group» "
            "if you do not know yet."
        ),
        "course_language_saved": "Saved: <b>{course}</b>",
        "course_language_none": "Fine, I will not show language classes.",
        "course_language_all": "Fine, I will show all language classes.",
        "hidden_language_note": "Hidden language classes of other groups: {count}.",
        "btn_course_none": "I don't study one",
        "btn_course_all": "Show all of them",
        "btn_any_teacher": "Any group",
        "btn_settings_course_language": "🗣 Foreign language",
        "course_language_unknown": (
            "Could not fetch the language list from the site — here is the usual set."
        ),
        "changes_title": "🔄 The timetable has changed",
        "changes_added": "➕ Added",
        "changes_removed": "➖ Removed",
        "changes_moved": "🔀 Moved",
        "changes_edited": "✏️ Updated",
        "changes_was": "was: {value}",
        "changes_now": "now: {value}",
        "changes_field_locations": "room",
        "changes_field_educators": "teacher",
        "changes_hint": "I check the timetable myself; turn it off in «⚙️ Settings».",
        "settings_notify_on": "🔄 Watching the timetable for changes",
        "settings_notify_off": "🔄 Not watching the timetable for changes",
        "btn_settings_notify_on": "🔄 Watch for changes",
        "btn_settings_notify_off": "🔕 Stop watching for changes",
        "toast_notify_on": "I will report changes",
        "toast_notify_off": "No longer watching for changes",
        "loading": "Fetching the timetable…",
        "site_down": "The timetable site is not responding 😕 Please try later.",
        "site_down_setup": (
            "The timetable site is not responding 😕\nTry again in a couple of minutes: /start"
        ),
        "not_configured": "Type your last name first — it takes half a minute: /setup",
        "no_classes": "No classes in this period 🎉",
        "no_classes_day": "  — no classes",
        "open_on_site": "Open on the site",
        "canceled": "cancelled",
        "hidden_note": "Hidden classes of other cohorts: {count}. Show everything: «⚙️ Settings».",
        "not_in_roster": "You are not in the current roster — showing the whole timetable.",
        "header_day": "Timetable for {date}",
        "header_week": "Timetable for the week {start} — {end}",
        "header_month": "Timetable for {month} {year}",
        "header_range": "Timetable {start} — {end}",
        "note_ask_text": "Type the note — I will send it back on the day you choose.",
        "note_ask_day": "When should I remind you?",
        "note_ask_custom_day": (
            "Type the day: <code>05.09</code>, <code>05.09.2026 18:30</code>, "
            "<code>5 September</code>, <code>in 3 days</code> or <code>on Friday</code>."
        ),
        "note_saved": (
            "Saved ✅\nI will send it on {date} at {time}.\nAll notes: /notes, "
            "delete: /delnote {id}"
        ),
        "note_draft": "Save this as a note? Pick the day to send it back.",
        "note_bad_date": "I did not understand the date 🤔 ",
        "note_lost": "The note text got lost",
        "notes_title": "<b>Scheduled notes</b>",
        "notes_empty": "You have no scheduled notes.",
        "notes_delete_hint": "Delete: /delnote &lt;number&gt;",
        "note_reminder": "📝 <b>Your note for {date}</b>",
        "note_deleted": "Deleted 🗑",
        "note_not_found": "Note not found.",
        "note_need_number": "Give the note number: /delnote 12 (numbers are in /notes)",
        "stopped": "Digest turned off, settings removed. Come back: /setup",
        "setup_first": "Run /setup first",
        "group_label": "👥 {name}",
        "btn_today": "📅 Today",
        "btn_week": "🗓 Week",
        "btn_notes": "📝 Notes",
        "btn_settings": "⚙️ Settings",
        "btn_placeholder": "Pick an action or write a note",
        "btn_its_me": "✅ That's me",
        "btn_retry_name": "🔁 Type the name again",
        "btn_not_in_list": "I'm not on the list",
        "btn_daily": "Every day",
        "btn_weekly": "Every week",
        "btn_monthly": "Every month",
        "btn_off": "Don't send",
        "btn_settings_freq": "🔔 Frequency",
        "btn_settings_time": "⏰ Delivery time",
        "btn_settings_show_all": "📋 Show the whole timetable",
        "btn_settings_show_mine": "🔎 Show only my cohort",
        "btn_settings_student": "🎓 Change last name",
        "btn_settings_language": "🌐 Язык / Language",
        "btn_today_note": "Today",
        "btn_tomorrow": "Tomorrow",
        "btn_day_after": "In two days",
        "btn_in_a_week": "In a week",
        "btn_other_date": "📆 Another date",
        "btn_cancel": "❌ Cancel",
        "btn_new_note": "➕ New note",
        "btn_note_list": "📋 All notes",
        "canceled_action": "Cancelled",
        "freq_daily": "every day",
        "freq_weekly": "every week",
        "freq_monthly": "every month",
        "freq_off": "digest is off",
        "toast_show_all": "Showing the whole timetable",
        "toast_show_mine": "Showing only my cohorts",
    },
}

# Кнопки главного меню приходят от пользователя текстом, поэтому нужен
# быстрый способ узнать их на любом языке.
MENU_KEYS = ("btn_today", "btn_week", "btn_notes", "btn_settings")


def normalize_lang(value: str | None) -> str:
    """Приводит код языка к поддерживаемому: «ru-RU» -> «ru», прочее -> en."""
    code = (value or "").strip().lower().replace("_", "-")
    if not code:
        return DEFAULT_LANG
    short = code.split("-")[0]
    if short in TEXTS:
        return short
    # Языки соседних стран ближе к русскому интерфейсу, чем к английскому.
    return "ru" if short in {"be", "uk", "kk", "ky", "uz", "tg", "hy", "az"} else "en"


class Translator:
    """Переводчик, привязанный к языку пользователя."""

    __slots__ = ("lang",)

    def __init__(self, lang: str = DEFAULT_LANG) -> None:
        self.lang = lang if lang in TEXTS else DEFAULT_LANG

    def __call__(self, key: str, **kwargs: object) -> str:
        template = TEXTS[self.lang].get(key) or TEXTS[DEFAULT_LANG].get(key) or key
        return template.format(**kwargs) if kwargs else template

    @property
    def weekdays(self) -> tuple[str, ...]:
        return WEEKDAYS[self.lang]

    @property
    def months_in_date(self) -> tuple[str, ...]:
        return MONTHS_IN_DATE[self.lang]

    @property
    def months_standalone(self) -> tuple[str, ...]:
        return MONTHS_STANDALONE[self.lang]

    @property
    def language_name(self) -> str:
        return LANGUAGE_NAMES[self.lang]

    @property
    def site_culture(self) -> str:
        return SITE_CULTURES[self.lang]


def menu_texts() -> set[str]:
    """Подписи кнопок главного меню на всех языках."""
    return {TEXTS[lang][key] for lang in TEXTS for key in MENU_KEYS}


def all_keys_present() -> list[str]:
    """Ключи, которых не хватает в каком-нибудь языке (для теста)."""
    reference = set(TEXTS[DEFAULT_LANG])
    missing: list[str] = []
    for lang, texts in TEXTS.items():
        missing.extend(f"{lang}:{key}" for key in sorted(reference - set(texts)))
    return missing
