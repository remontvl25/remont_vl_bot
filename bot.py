import os
import sys
import json
import time
import sqlite3
import requests
import fcntl
from datetime import datetime

import telebot
from telebot import types

# ================ БЛОКИРОВКА ЗАПУСКА ВТОРОГО ЭКЗЕМПЛЯРА ================
def single_instance():
    lock_file = '/tmp/bot.lock'
    try:
        f = open(lock_file, 'w')
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except:
        print("❌ Бот уже запущен! Завершаем работу.")
        sys.exit(1)

single_instance()

# ================ ПОДКЛЮЧЕНИЕ GOOGLE SHEETS (опционально) ================
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    GOOGLE_SHEETS_AVAILABLE = True
except ImportError:
    GOOGLE_SHEETS_AVAILABLE = False
    print("⚠️ Библиотеки gspread/oauth2client не установлены. Google Sheets отключён.")

# ================ НАСТРОЙКИ ================
TOKEN = os.environ.get('TOKEN')
if not TOKEN:
    print("❌ Токен не найден в переменных окружения!")
    sys.exit(1)

CHAT_ID = os.environ.get('CHAT_ID', "@remontvl25chat")
CHANNEL_LINK = os.environ.get('CHANNEL_LINK', "@remont_vl25")
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))

# Ссылка на Google Forms (замените на реальную)
GOOGLE_FORMS_URL = os.environ.get('GOOGLE_FORMS_URL', 'https://forms.gle/your_form_link')

bot = telebot.TeleBot(TOKEN)

# ================ БАЗА ДАННЫХ ================
conn = sqlite3.connect('remont.db', check_same_thread=False)
cursor = conn.cursor()

# Таблица заявок
cursor.execute('''CREATE TABLE IF NOT EXISTS requests
                (id INTEGER PRIMARY KEY,
                 user_id INTEGER,
                 username TEXT,
                 service TEXT,
                 description TEXT,
                 district TEXT,
                 date TEXT,
                 budget TEXT,
                 status TEXT,
                 chat_message_id INTEGER,
                 created_at TEXT)''')

# Таблица отзывов
cursor.execute('''CREATE TABLE IF NOT EXISTS reviews
                (id INTEGER PRIMARY KEY,
                 master_name TEXT,
                 user_name TEXT,
                 review_text TEXT,
                 rating INTEGER,
                 status TEXT,
                 created_at TEXT)''')

# Таблица проверенных мастеров
cursor.execute('''CREATE TABLE IF NOT EXISTS masters
                (id INTEGER PRIMARY KEY,
                 user_id INTEGER,
                 name TEXT,
                 service TEXT,
                 phone TEXT,
                 districts TEXT,
                 price_min TEXT,
                 price_max TEXT,
                 experience TEXT,
                 bio TEXT DEFAULT "",
                 portfolio TEXT,
                 rating REAL DEFAULT 0,
                 reviews_count INTEGER DEFAULT 0,
                 status TEXT DEFAULT 'активен',
                 entity_type TEXT DEFAULT 'individual',
                 documents_verified INTEGER DEFAULT 0,
                 photos_verified INTEGER DEFAULT 0,
                 reviews_verified INTEGER DEFAULT 0,
                 channel_message_id INTEGER,
                 created_at TEXT)''')

# Таблица анкет мастеров (на проверку)
cursor.execute('''CREATE TABLE IF NOT EXISTS master_applications
                (id INTEGER PRIMARY KEY,
                 user_id INTEGER,
                 username TEXT,
                 name TEXT,
                 service TEXT,
                 phone TEXT,
                 districts TEXT,
                 price_min TEXT,
                 price_max TEXT,
                 experience TEXT,
                 bio TEXT DEFAULT "",
                 portfolio TEXT,
                 documents TEXT,
                 entity_type TEXT DEFAULT 'individual',
                 status TEXT,
                 created_at TEXT)''')

# Таблица рекомендаций (предложенные мастера)
cursor.execute('''CREATE TABLE IF NOT EXISTS recommendations
                (id INTEGER PRIMARY KEY,
                 user_id INTEGER,
                 username TEXT,
                 master_name TEXT,
                 service TEXT,
                 contact TEXT,
                 description TEXT,
                 portfolio TEXT,
                 status TEXT,
                 created_at TEXT)''')

# Добавляем недостающие колонки в старые таблицы
try:
    cursor.execute('ALTER TABLE requests ADD COLUMN description TEXT')
except:
    pass
try:
    cursor.execute('ALTER TABLE requests ADD COLUMN date TEXT')
except:
    pass
try:
    cursor.execute('ALTER TABLE requests ADD COLUMN chat_message_id INTEGER')
except:
    pass
try:
    cursor.execute('ALTER TABLE masters ADD COLUMN bio TEXT DEFAULT ""')
except:
    pass
try:
    cursor.execute('ALTER TABLE masters ADD COLUMN user_id INTEGER')
except:
    pass
try:
    cursor.execute('ALTER TABLE masters ADD COLUMN entity_type TEXT DEFAULT "individual"')
except:
    pass
try:
    cursor.execute('ALTER TABLE masters ADD COLUMN documents_verified INTEGER DEFAULT 0')
except:
    pass
try:
    cursor.execute('ALTER TABLE masters ADD COLUMN photos_verified INTEGER DEFAULT 0')
except:
    pass
try:
    cursor.execute('ALTER TABLE masters ADD COLUMN reviews_verified INTEGER DEFAULT 0')
except:
    pass
try:
    cursor.execute('ALTER TABLE masters ADD COLUMN channel_message_id INTEGER')
except:
    pass
try:
    cursor.execute('ALTER TABLE master_applications ADD COLUMN bio TEXT DEFAULT ""')
except:
    pass

conn.commit()

# ================ ФУНКЦИИ GOOGLE SHEETS ================
def get_google_sheet():
    if not GOOGLE_SHEETS_AVAILABLE:
        print("⚠️ Google Sheets библиотеки не установлены")
        return None
    try:
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        sheet_id = os.environ.get('GOOGLE_SHEET_ID')
        if not creds_json or not sheet_id:
            print("⚠️ Переменные GOOGLE_CREDENTIALS или GOOGLE_SHEET_ID не заданы")
            return None

        creds_dict = json.loads(creds_json)
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        sh = client.open_by_key(sheet_id)
        try:
            worksheet = sh.worksheet('Мастера')
        except:
            worksheet = sh.sheet1
            print(f"⚠️ Лист 'Мастера' не найден, используется '{worksheet.title}'")
        return worksheet
    except Exception as e:
        print(f"❌ Ошибка в get_google_sheet: {e}")
        return None

def add_master_to_google_sheet(master_data):
    sheet = get_google_sheet()
    if not sheet:
        return False
    try:
        # Порядок колонок: A-ID, B-Дата, C-Имя, D-Специализация, E-Телефон, F-Районы,
        # G-Цена от, H-Цена до, I-Опыт, J-Комментарий, K-Портфолио, L-Документы,
        # M-Рейтинг, N-Отзывов, O-Статус, P-Telegram ID, Q-Тип
        row = [
            str(master_data.get('id', '')),
            str(master_data.get('date', '')),
            str(master_data.get('name', '')),
            str(master_data.get('service', '')),
            str(master_data.get('phone', '')),
            str(master_data.get('districts', '')),
            str(master_data.get('price_min', '')),
            str(master_data.get('price_max', '')),
            str(master_data.get('experience', '')),
            str(master_data.get('bio', 'Не указано')),          # J
            str(master_data.get('portfolio', 'Не указано')),    # K
            str(master_data.get('documents', 'Не указано')),    # L
            str(master_data.get('rating', '4.8')),             # M
            str(master_data.get('reviews_count', '0')),        # N
            str(master_data.get('status', 'На проверке')),      # O
            str(master_data.get('telegram_id', '')),           # P
            str(master_data.get('entity_type', 'individual'))  # Q
        ]
        sheet.append_row(row)
        print(f"✅ Мастер {master_data.get('name')} добавлен в Google Sheets")
        return True
    except Exception as e:
        print(f"❌ Ошибка добавления в Google Sheets: {e}")
        return False

def update_master_status_in_google_sheet(telegram_id, status):
    sheet = get_google_sheet()
    if not sheet:
        return False
    try:
        records = sheet.get_all_records()
        for i, rec in enumerate(records, start=2):
            if str(rec.get('Telegram ID')) == str(telegram_id):
                sheet.update_cell(i, 15, status)  # колонка O – статус
                return True
    except Exception as e:
        print(f"❌ Ошибка обновления статуса: {e}")
    return False

# ================ ТЕСТ GOOGLE SHEETS ================
@bot.message_handler(commands=['test_sheet'])
def test_sheet(message):
    if message.from_user.id != ADMIN_ID:
        return
    lines = []
    lines.append("🔍 **ДИАГНОСТИКА GOOGLE SHEETS**\n")
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    lines.append(f"**GOOGLE_CREDENTIALS:** {'✅ Есть' if creds_json else '❌ НЕТ'}")
    lines.append(f"**GOOGLE_SHEET_ID:** {'✅ Есть' if sheet_id else '❌ НЕТ'}\n")
    if not creds_json or not sheet_id:
        lines.append("❌ Переменные не заданы.")
        bot.reply_to(message, "\n".join(lines))
        return
    if not GOOGLE_SHEETS_AVAILABLE:
        lines.append("❌ Библиотеки gspread/oauth2client не установлены.")
        bot.reply_to(message, "\n".join(lines))
        return
    try:
        sheet = get_google_sheet()
        if not sheet:
            lines.append("❌ get_google_sheet() вернул None")
            bot.reply_to(message, "\n".join(lines))
            return
        lines.append(f"✅ Подключение успешно!")
        lines.append(f"📄 Лист: {sheet.title}")
        lines.append(f"📊 Строк: {len(sheet.get_all_values())}\n")
        test_row = [
            "TEST",
            datetime.now().strftime("%d.%m.%Y"),
            "Тестовый мастер",
            "Тест",
            "+7 999 999-99-99",
            "Патрокл",
            "1000₽",
            "5000₽",
            "5 лет",
            "Тестовый комментарий",
            "Нет",
            "Есть",
            "5.0",
            "1",
            "Тест",
            "12345",
            "individual"
        ]
        sheet.append_row(test_row)
        lines.append("✅ Тестовая запись выполнена!")
    except Exception as e:
        lines.append(f"❌ Ошибка: {type(e).__name__}: {e}")
    bot.reply_to(message, "\n".join(lines))

# ================ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ================
def safe_text(message):
    return message.text.strip() if message and message.text else ""

def only_private(message):
    if message.chat.type != 'private':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "🤖 Перейти в бота",
            url="https://t.me/remont_vl25_chat_bot"
        ))
        bot.reply_to(
            message,
            "❌ Эта команда работает только в личных сообщениях с ботом.\n\n"
            "👉 Напишите мне в ЛС: @remont_vl25_chat_bot",
            reply_markup=markup
        )
        return False
    return True

def reset_webhook():
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")
        print("✅ Webhook сброшен")
    except:
        pass

def stop_other_instances():
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset=-1&timeout=0")
        print("✅ Другие экземпляры остановлены")
    except:
        pass

# ================ УДАЛЕНИЕ КОМАНД В ЧАТЕ ================
@bot.message_handler(func=lambda message: message.chat.type != 'private')
def delete_group_commands(message):
    if message.text and (message.text.startswith('/') or '@remont_vl25_chat_bot' in message.text):
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass

# ================ КОМАНДА /start ================
@bot.message_handler(commands=['start'])
def start(message):
    if message.chat.type != 'private':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "🤖 Перейти в бота",
            url="https://t.me/remont_vl25_chat_bot"
        ))
        bot.reply_to(
            message,
            "👋 Добро пожаловать в бот заявок на ремонт!\n\n"
            "📌 В этом чате я только публикую заявки и отзывы.\n\n"
            "👇 Вся работа со мной — в личных сообщениях:\n"
            "👉 @remont_vl25_chat_bot\n\n"
            "Там вы можете:\n"
            "✅ Оставить заявку на ремонт\n"
            "✅ Найти проверенного мастера (каталог с рейтингом и статусом)\n"
            "✅ Стать мастером и добавить анкету\n"
            "✅ Оставить отзыв о работе\n"
            "✅ Проверить статус анкеты\n"
            "✅ Рекомендовать мастера",
            reply_markup=markup
        )
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('🔨 Оставить заявку', '⭐ Оставить отзыв')
    markup.row('🔍 Найти мастера', '👍 Рекомендовать мастера')
    markup.row('📢 Канал с мастерами', '👷 Стать мастером')
    markup.row('📋 Анкета (Google Forms)')

    bot.send_message(
        message.chat.id,
        "👋 **Добро пожаловать в бот заявок на ремонт!**\n\n"
        "🔹 **Хотите найти мастера?**\n"
        "   • Нажмите «🔍 Найти мастера» – выберите из каталога (рейтинг, цены, статус проверки)\n"
        "   • Или оставьте заявку в чате @remontvl25chat – мастера сами откликнутся\n\n"
        "🔹 **Хотите поблагодарить мастера?** Нажмите «⭐ Оставить отзыв»\n"
        "🔹 **Хотите добавить свою анкету?** Нажмите «👷 Стать мастером» (в боте) или «📋 Анкета (Google Forms)»\n"
        "🔹 **Знаете хорошего мастера?** Нажмите «👍 Рекомендовать мастера» – после проверки он попадёт в базу\n\n"
        f"💬 **Чат-заявок:** {CHAT_ID}\n"
        f"📢 **Канал с мастерами:** {CHANNEL_LINK}",
        parse_mode='Markdown',
        reply_markup=markup
    )

# ================ КНОПКА "КАНАЛ С МАСТЕРАМИ" ================
@bot.message_handler(func=lambda message: message.text == '📢 Канал с мастерами')
def channel_link(message):
    if not only_private(message):
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "📢 Перейти в канал",
        url="https://t.me/remont_vl25"
    ))
    bot.send_message(
        message.chat.id,
        f"📢 **Наш канал с проверенными мастерами:** {CHANNEL_LINK}\n\n"
        "В канале вы найдете:\n"
        "✅ Карточки мастеров с отзывами, рейтингом и статусом проверки\n"
        "✅ Реальные цены на ремонт\n"
        "✅ Фото работ до/после\n"
        "✅ Черный список мошенников\n\n"
        "🛡️ **Статусы мастеров:**\n"
        "   • 👤 Частное лицо / 🏢 Компания\n"
        "   • 📄 Документы проверены\n"
        "   • 📸 Фото/видео подтверждены\n"
        "   • 💬 Отзывы проверены\n"
        "   • ✅ Верифицировано (полный пакет)",
        reply_markup=markup
    )

# ================ КНОПКА "АНКЕТА (GOOGLE FORMS)" ================
@bot.message_handler(func=lambda message: message.text == '📋 Анкета (Google Forms)')
def forms_link(message):
    if not only_private(message):
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "📋 Перейти к анкете",
        url=GOOGLE_FORMS_URL
    ))
    bot.send_message(
        message.chat.id,
        "📋 **Анкета мастера в Google Forms**\n\n"
        "Если вам удобнее заполнить анкету в браузере – нажмите кнопку ниже.\n\n"
        "✅ После отправки администратор проверит данные (обычно 1-2 дня).\n"
        "❌ Узнать статус можно в этом боте по команде /my_status (если вы указали Telegram username).",
        reply_markup=markup
    )

# ================ ЗАЯВКА (ТОЛЬКО В ЛС) ================
@bot.message_handler(commands=['request'])
@bot.message_handler(func=lambda message: message.text == '🔨 Оставить заявку')
def request_service(message):
    if not only_private(message):
        return
    msg = bot.send_message(
        message.chat.id,
        "🔨 **СОЗДАНИЕ ЗАЯВКИ**\n\n"
        "Шаг 1 из 5\n"
        "👇 **ВЫБЕРИТЕ УСЛУГУ:**\n\n"
        "Введите цифру или название:\n"
        "1 - Сантехник\n"
        "2 - Электрик\n"
        "3 - Отделочник\n"
        "4 - Строитель\n"
        "5 - Другое\n\n"
        "👉 Пример: `1` или `сантехник`"
    )
    bot.register_next_step_handler(msg, process_service)

def process_service(message):
    if message.chat.type != 'private':
        return
    text = safe_text(message)
    if not text:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите текст.")
        return
    service_input = text.lower()
    if service_input == "1" or "сантехник" in service_input:
        service = "Сантехник"
    elif service_input == "2" or "электрик" in service_input:
        service = "Электрик"
    elif service_input == "3" or "отделочник" in service_input:
        service = "Отделочник"
    elif service_input == "4" or "строитель" in service_input:
        service = "Строитель"
    elif service_input == "5" or "другое" in service_input:
        service = "Другое"
    else:
        service = text.capitalize()
    msg = bot.send_message(
        message.chat.id,
        "📝 **Шаг 2 из 5**\n\n"
        "👇 **КРАТКО ОПИШИТЕ ЗАДАЧУ:**\n\n"
        "Например:\n"
        "• Заменить смеситель на кухне\n"
        "• Перенести 3 розетки в зале\n"
        "• Поклеить обои в спальне 15м²"
    )
    bot.register_next_step_handler(msg, process_description, service)

def process_description(message, service):
    if message.chat.type != 'private':
        return
    description = safe_text(message)
    if not description:
        bot.send_message(message.chat.id, "❌ Пожалуйста, опишите задачу.")
        return
    msg = bot.send_message(
        message.chat.id,
        "📍 **Шаг 3 из 5**\n\n"
        "👇 **ВВЕДИТЕ РАЙОН ИЛИ ЖК:**\n"
        "Например: Патрокл, Снеговая Падь, Варяг, Океан"
    )
    bot.register_next_step_handler(msg, process_district, service, description)

def process_district(message, service, description):
    if message.chat.type != 'private':
        return
    district = safe_text(message)
    if not district:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите район.")
        return
    msg = bot.send_message(
        message.chat.id,
        "📅 **Шаг 4 из 5**\n\n"
        "👇 **КОГДА НУЖНО ВЫПОЛНИТЬ РАБОТЫ?**\n\n"
        "Например:\n"
        "• Сегодня вечером\n"
        "• Завтра с 10:00\n"
        "• На этой неделе\n"
        "• Дата договорная"
    )
    bot.register_next_step_handler(msg, process_date, service, description, district)

def process_date(message, service, description, district):
    if message.chat.type != 'private':
        return
    date = safe_text(message)
    if not date:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите дату.")
        return
    msg = bot.send_message(
        message.chat.id,
        "💰 **Шаг 5 из 5**\n\n"
        "👇 **ВВЕДИТЕ БЮДЖЕТ:**\n"
        "Например: до 3000₽, договорной, 50000₽ за квартиру"
    )
    bot.register_next_step_handler(msg, process_budget, service, description, district, date)

def process_budget(message, service, description, district, date):
    if message.chat.type != 'private':
        return
    budget = safe_text(message)
    if not budget:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите бюджет.")
        return

    # Сохраняем заявку в БД
    cursor.execute('''INSERT INTO requests 
                    (user_id, username, service, description, district, date, budget, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (message.from_user.id,
                     message.from_user.username or "",
                     service, description, district, date, budget,
                     'активна',
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    request_id = cursor.lastrowid

    # Анонимный псевдоним
    client_alias = f"Клиент #{request_id % 10000}"

    request_text = f"""
🆕 **НОВАЯ ЗАЯВКА!**

👤 **От:** {client_alias}
🔨 **Услуга:** {service}
📝 **Задача:** {description}
📍 **Район/ЖК:** {district}
📅 **Когда:** {date}
💰 **Бюджет:** {budget}
⏰ **Создано:** {datetime.now().strftime("%H:%M %d.%m.%Y")}

👇 **Мастера, откликайтесь в комментариях!**
"""
    sent_msg = bot.send_message(CHAT_ID, request_text)
    chat_message_id = sent_msg.message_id

    cursor.execute('UPDATE requests SET chat_message_id = ? WHERE id = ?', (chat_message_id, request_id))
    conn.commit()

    bot.send_message(
        message.chat.id,
        f"✅ **ЗАЯВКА ОПУБЛИКОВАНА!**\n\n"
        f"💬 **Чат с мастерами:** {CHAT_ID}\n"
        f"⏱ Ожидайте откликов в течение 5-10 минут.\n\n"
        f"📌 Если никто не ответил за 30 минут — создайте новую заявку."
    )

    notify_masters_about_request({
        'service': service,
        'description': description,
        'district': district,
        'date': date,
        'budget': budget
    })

# ================ УВЕДОМЛЕНИЕ МАСТЕРОВ О НОВОЙ ЗАЯВКЕ ================
def notify_masters_about_request(request_data):
    cursor.execute("SELECT user_id FROM masters WHERE status = 'активен'")
    masters = cursor.fetchall()
    if not masters:
        return
    text = f"""
📩 **Новая заявка по вашей специализации!**

🔨 **Услуга:** {request_data['service']}
📝 **Задача:** {request_data['description']}
📍 **Район/ЖК:** {request_data['district']}
📅 **Когда:** {request_data['date']}
💰 **Бюджет:** {request_data['budget']}

💬 **Откликнуться:** напишите комментарий под заявкой в чате @remontvl25chat
"""
    for master in masters:
        try:
            bot.send_message(master[0], text)
        except Exception as e:
            print(f"❌ Не удалось отправить уведомление мастеру {master[0]}: {e}")

# ================ ОБРАБОТЧИК ОТКЛИКОВ МАСТЕРОВ ================
@bot.message_handler(func=lambda message: 
    message.chat.type != 'private' and 
    message.reply_to_message and 
    message.reply_to_message.from_user.id == bot.get_me().id
)
def handle_master_reply(message):
    cursor.execute("SELECT 1 FROM masters WHERE user_id = ? AND status = 'активен'", (message.from_user.id,))
    if not cursor.fetchone():
        bot.reply_to(
            message,
            "❌ Только проверенные мастера могут получать контакты клиентов.\n"
            "Зарегистрируйтесь и пройдите проверку через бота."
        )
        return

    replied_msg_id = message.reply_to_message.message_id
    cursor.execute("SELECT user_id, username FROM requests WHERE chat_message_id = ?", (replied_msg_id,))
    row = cursor.fetchone()
    if not row:
        bot.reply_to(message, "❌ Не удалось найти заявку. Возможно, она устарела.")
        return

    client_user_id, client_username = row

    if client_username:
        contact = f"📬 **Контакт клиента:** @{client_username}"
    else:
        contact = f"📬 **Контакт клиента:** пользователь (ID {client_user_id})"

    try:
        bot.send_message(
            message.from_user.id,
            f"{contact}\n\n"
            f"📌 Заявка: {message.reply_to_message.text[:200]}...\n"
            f"Свяжитесь с клиентом для обсуждения деталей."
        )
        try:
            bot.react_to(message, '👍')
        except:
            pass
    except Exception as e:
        bot.reply_to(message, "❌ Не удалось отправить контакт в ЛС. Возможно, вы заблокировали бота.")
        return

    try:
        bot.send_message(
            client_user_id,
            f"👋 На вашу заявку откликнулся мастер @{message.from_user.username}!\n\n"
            f"Он уже получил ваш контакт и скоро свяжется с вами.\n"
            f"Вы также можете написать ему: @{message.from_user.username}"
        )
    except:
        pass

# ================ ОТЗЫВ (ТОЛЬКО В ЛС) ================
@bot.message_handler(commands=['review'])
@bot.message_handler(func=lambda message: message.text == '⭐ Оставить отзыв')
def add_review(message):
    if not only_private(message):
        return
    msg = bot.send_message(
        message.chat.id,
        "⭐ **ОСТАВИТЬ ОТЗЫВ**\n\n"
        "Напишите **ИМЯ МАСТЕРА** или **НАЗВАНИЕ БРИГАДЫ**:"
    )
    bot.register_next_step_handler(msg, process_review_master)

def process_review_master(message):
    if message.chat.type != 'private':
        return
    master = safe_text(message)
    if not master:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите имя мастера.")
        return
    msg = bot.send_message(
        message.chat.id,
        "📝 **НАПИШИТЕ ТЕКСТ ОТЗЫВА:**\n"
        "Например: Сделал быстро, качественно, цена адекватная"
    )
    bot.register_next_step_handler(msg, process_review_text, master)

def process_review_text(message, master):
    if message.chat.type != 'private':
        return
    review_text = safe_text(message)
    if not review_text:
        bot.send_message(message.chat.id, "❌ Пожалуйста, напишите текст отзыва.")
        return

    cursor.execute('''INSERT INTO reviews
                    (master_name, user_name, review_text, rating, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (master,
                     message.from_user.username or message.from_user.first_name,
                     review_text,
                     0,
                     'pending',
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    review_id = cursor.lastrowid

    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = []
    for i in range(1, 6):
        buttons.append(types.InlineKeyboardButton(
            "⭐" * i, callback_data=f"rate_{review_id}_{i}"
        ))
    markup.add(*buttons)

    bot.send_message(
        message.chat.id,
        f"👤 **Мастер:** {master}\n"
        f"📝 **Отзыв:** {review_text}\n\n"
        "⭐ **ОЦЕНИТЕ РАБОТУ ОТ 1 ДО 5:**",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('rate_'))
def rate_callback(call):
    _, review_id, rating = call.data.split('_')
    review_id = int(review_id)
    rating = int(rating)

    cursor.execute('''UPDATE reviews 
                      SET rating = ?, status = 'published' 
                      WHERE id = ?''', (rating, review_id))
    conn.commit()

    cursor.execute('''SELECT master_name, user_name, review_text, rating, created_at 
                      FROM reviews WHERE id = ?''', (review_id,))
    review = cursor.fetchone()
    if not review:
        bot.answer_callback_query(call.id, "Ошибка: отзыв не найден")
        return

    master_name, user_name, review_text, rating, created_at = review

    extra_info = ""
    cursor.execute('''SELECT service, phone, entity_type FROM masters WHERE name LIKE ?''', (f'%{master_name}%',))
    master_data = cursor.fetchone()
    if master_data:
        service, phone, entity_type = master_data
        type_icon = '🏢' if entity_type == 'company' else '👤'
        type_label = 'Компания' if entity_type == 'company' else 'Частное лицо'
        extra_info = f"{type_icon} {type_label}\n🔧 Специализация: {service}\n📞 Контакты: {phone[:10]}…"

    review_public = f"""
⭐ **НОВЫЙ ОТЗЫВ!**

👤 **Мастер:** {master_name}
⭐ **Оценка:** {'⭐' * rating}
📝 **Отзыв:** {review_text}
👤 **От кого:** @{user_name}
{extra_info}
⏰ {created_at}
"""
    bot.send_message(CHAT_ID, review_public)

    bot.answer_callback_query(call.id, f"Спасибо! Оценка {rating} ⭐ сохранена")
    bot.edit_message_text(
        f"✅ **СПАСИБО ЗА ОТЗЫВ!**\n\n"
        f"👤 **Мастер:** {master_name}\n"
        f"⭐ **Оценка:** {'⭐' * rating}\n"
        f"📝 **Отзыв:** {review_text}\n\n"
        f"Ваш отзыв опубликован в чате {CHAT_ID}",
        call.message.chat.id,
        call.message.message_id
    )

# ================ НОВЫЙ ПОИСК МАСТЕРОВ (КАТАЛОГ) ================
@bot.message_handler(commands=['search'])
@bot.message_handler(func=lambda message: message.text == '🔍 Найти мастера')
def search_master(message):
    if not only_private(message):
        return

    cursor.execute("SELECT DISTINCT service FROM masters WHERE status = 'активен' ORDER BY service")
    services = cursor.fetchall()

    if not services:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "📝 Оставить заявку в чате",
            url=f"https://t.me/{CHAT_ID.replace('@', '')}"
        ))
        bot.send_message(
            message.chat.id,
            "🔍 **В базе пока нет мастеров.**\n\n"
            "Вы можете оставить заявку в чате – мастера сами откликнутся!",
            reply_markup=markup
        )
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for s in services:
        service = s[0]
        buttons.append(types.InlineKeyboardButton(service, callback_data=f"cat_{service}"))
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cat_cancel"))

    bot.send_message(
        message.chat.id,
        "🔍 **Каталог мастеров**\n\n"
        "Выберите специализацию:\n\n"
        "🛡️ *В карточках мастеров указаны:*\n"
        "• 👤 Частное лицо / 🏢 Компания\n"
        "• ⭐ Рейтинг и количество отзывов\n"
        "• 📍 Районы работы\n"
        "• 💰 Цены\n"
        "• 📞 Контакт (после отклика)",
        parse_mode='Markdown',
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('cat_'))
def catalog_callback(call):
    data = call.data[4:]
    if data == 'cancel':
        bot.edit_message_text(
            "❌ Поиск отменён.",
            call.message.chat.id,
            call.message.message_id
        )
        bot.answer_callback_query(call.id)
        return

    service = data
    user_id = call.from_user.id

    if not hasattr(bot, 'catalog_states'):
        bot.catalog_states = {}
    bot.catalog_states[user_id] = {
        'service': service,
        'page': 0
    }

    show_masters_page(call.message, user_id, service, 0)
    bot.answer_callback_query(call.id)

def show_masters_page(message, user_id, service, page):
    LIMIT = 3
    offset = page * LIMIT

    cursor.execute('''
        SELECT name, service, districts, price_min, price_max, rating, reviews_count, phone, entity_type, bio
        FROM masters
        WHERE service = ? AND status = 'активен'
        ORDER BY rating DESC, reviews_count DESC
        LIMIT ? OFFSET ?
    ''', (service, LIMIT, offset))
    masters = cursor.fetchall()

    cursor.execute('''
        SELECT COUNT(*) FROM masters WHERE service = ? AND status = 'активен'
    ''', (service,))
    total = cursor.fetchone()[0]

    if not masters:
        bot.edit_message_text(
            f"❌ По специализации «{service}» больше нет мастеров.",
            message.chat.id,
            message.message_id
        )
        return

    total_pages = (total - 1) // LIMIT + 1
    text = f"🔍 **Мастера – {service}** (страница {page+1}/{total_pages})\n\n"

    for m in masters:
        name, service, districts, price_min, price_max, rating, reviews, phone, entity_type, bio = m
        rating_stars = '⭐' * int(round(rating or 0)) + ('½' if rating and rating % 1 >= 0.5 else '')
        phone_display = phone[:10] + '…' if len(phone) > 10 else phone
        type_icon = '🏢' if entity_type == 'company' else '👤'
        type_label = 'Компания' if entity_type == 'company' else 'Частное лицо'

        text += f"{type_icon} **{name}** ({type_label})\n"
        text += f"   📍 {districts}\n"
        text += f"   💰 {price_min} – {price_max}\n"
        text += f"   ⭐ {rating:.1f} ({reviews} отзывов)\n"
        if bio and bio != 'Не указано':
            text += f"   💬 {bio}\n"
        text += f"   📞 Контакт: `{phone_display}` (после отклика)\n\n"

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    if page > 0:
        buttons.append(types.InlineKeyboardButton(
            "◀️ Назад", callback_data=f"page_{service}_{page-1}"
        ))
    if offset + LIMIT < total:
        buttons.append(types.InlineKeyboardButton(
            "Вперёд ▶️", callback_data=f"page_{service}_{page+1}"
        ))
    if buttons:
        markup.add(*buttons)
    markup.add(types.InlineKeyboardButton(
        "🔙 К списку специализаций", callback_data="cat_back_to_services"
    ))

    bot.edit_message_text(
        text,
        message.chat.id,
        message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('page_'))
def page_callback(call):
    _, service, page_str = call.data.split('_', 2)
    page = int(page_str)
    user_id = call.from_user.id

    if not hasattr(bot, 'catalog_states'):
        bot.catalog_states = {}
    bot.catalog_states[user_id] = {
        'service': service,
        'page': page
    }

    show_masters_page(call.message, user_id, service, page)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'cat_back_to_services')
def back_to_services(call):
    user_id = call.from_user.id
    if hasattr(bot, 'catalog_states') and user_id in bot.catalog_states:
        del bot.catalog_states[user_id]

    cursor.execute("SELECT DISTINCT service FROM masters WHERE status = 'активен' ORDER BY service")
    services = cursor.fetchall()

    if not services:
        bot.edit_message_text(
            "❌ База мастеров пуста.",
            call.message.chat.id,
            call.message.message_id
        )
        bot.answer_callback_query(call.id)
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for s in services:
        service = s[0]
        buttons.append(types.InlineKeyboardButton(service, callback_data=f"cat_{service}"))
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cat_cancel"))

    bot.edit_message_text(
        "🔍 **Каталог мастеров**\n\nВыберите специализацию:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)

# ================ РЕКОМЕНДАЦИЯ МАСТЕРА (ТОЛЬКО В ЛС) ================
@bot.message_handler(commands=['recommend'])
@bot.message_handler(func=lambda message: message.text == '👍 Рекомендовать мастера')
def recommend_master(message):
    if not only_private(message):
        return
    msg = bot.send_message(
        message.chat.id,
        "👍 **РЕКОМЕНДАЦИЯ МАСТЕРА**\n\n"
        "Шаг 1 из 5\n"
        "👇 **ВВЕДИТЕ ИМЯ МАСТЕРА ИЛИ НАЗВАНИЕ БРИГАДЫ:**"
    )
    bot.register_next_step_handler(msg, process_recommend_name)

def process_recommend_name(message):
    if message.chat.type != 'private':
        return
    name = safe_text(message)
    if not name:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите имя.")
        return
    msg = bot.send_message(
        message.chat.id,
        "🔨 **Шаг 2 из 5**\n\n"
        "👇 **ВЫБЕРИТЕ СПЕЦИАЛИЗАЦИЮ МАСТЕРА:**\n\n"
        "Введите цифру или название:\n"
        "1 - Сантехник\n"
        "2 - Электрик\n"
        "3 - Отделочник\n"
        "4 - Строитель\n"
        "5 - Сварщик\n"
        "6 - Разнорабочий\n"
        "7 - Другое"
    )
    bot.register_next_step_handler(msg, process_recommend_service, name)

def process_recommend_service(message, name):
    if message.chat.type != 'private':
        return
    text = safe_text(message)
    if not text:
        bot.send_message(message.chat.id, "❌ Пожалуйста, выберите специализацию.")
        return
    service_input = text.lower()
    if service_input == "1" or "сантехник" in service_input:
        service = "Сантехник"
    elif service_input == "2" or "электрик" in service_input:
        service = "Электрик"
    elif service_input == "3" or "отделочник" in service_input:
        service = "Отделочник"
    elif service_input == "4" or "строитель" in service_input:
        service = "Строитель"
    elif service_input == "5" or "сварщик" in service_input:
        service = "Сварщик"
    elif service_input == "6" or "разнорабочий" in service_input:
        service = "Разнорабочий"
    else:
        service = text.capitalize()
    msg = bot.send_message(
        message.chat.id,
        "📞 **Шаг 3 из 5**\n\n"
        "👇 **КОНТАКТ МАСТЕРА** (телефон / Telegram):\n\n"
        "Укажите, как связаться с мастером.\n"
        "Пример: +7 924 123-45-67 или @username"
    )
    bot.register_next_step_handler(msg, process_recommend_contact, name, service)

def process_recommend_contact(message, name, service):
    if message.chat.type != 'private':
        return
    contact = safe_text(message)
    if not contact:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите контакт.")
        return
    msg = bot.send_message(
        message.chat.id,
        "📝 **Шаг 4 из 5**\n\n"
        "👇 **ОПИШИТЕ, ПОЧЕМУ ВЫ РЕКОМЕНДУЕТЕ ЭТОГО МАСТЕРА**\n\n"
        "Например: делал ремонт в 2-комнатной, качественно, без доплат.\n"
        "Это поможет при проверке."
    )
    bot.register_next_step_handler(msg, process_recommend_description, name, service, contact)

def process_recommend_description(message, name, service, contact):
    if message.chat.type != 'private':
        return
    description = safe_text(message)
    if not description:
        description = "Не указано"
    msg = bot.send_message(
        message.chat.id,
        "📸 **Шаг 5 из 5**\n\n"
        "👇 **ССЫЛКА НА ПОРТФОЛИО / ОТЗЫВЫ (ЕСЛИ ЕСТЬ)**\n\n"
        "Можно указать ссылку на Яндекс.Диск, Google Фото или отзыв.\n"
        "Или просто нажмите «Пропустить»"
    )
    bot.register_next_step_handler(msg, process_recommend_portfolio, name, service, contact, description)

def process_recommend_portfolio(message, name, service, contact, description):
    if message.chat.type != 'private':
        return
    portfolio = safe_text(message)
    if not portfolio or portfolio.lower() == "пропустить":
        portfolio = "Не указано"

    cursor.execute('''INSERT INTO recommendations
                    (user_id, username, master_name, service, contact, description, portfolio, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (message.from_user.id,
                     message.from_user.username or "no_username",
                     name, service, contact, description, portfolio,
                     'на модерации',
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    rec_id = cursor.lastrowid

    admin_msg = f"""
👍 **НОВАЯ РЕКОМЕНДАЦИЯ МАСТЕРА!** (ID: {rec_id})

👤 **Рекомендует:** @{message.from_user.username or "нет"}
🛠 **Мастер:** {name}
🔧 **Специализация:** {service}
📞 **Контакт:** {contact}
📝 **Описание:** {description}
📸 **Портфолио:** {portfolio}

✅ **Добавить на проверку:** /add_from_rec {rec_id}
❌ **Отклонить:** /reject_rec {rec_id}
    """
    try:
        if ADMIN_ID != 0:
            bot.send_message(ADMIN_ID, admin_msg)
    except:
        pass

    bot.send_message(
        message.chat.id,
        "✅ **СПАСИБО ЗА РЕКОМЕНДАЦИЮ!**\n\n"
        "Мы проверим этого мастера и, если он подходит, добавим в базу.\n"
        "Статус рекомендации можно узнать по команде /my_recommend_status"
    )

@bot.message_handler(commands=['my_recommend_status'])
def my_recommend_status(message):
    if not only_private(message):
        return
    cursor.execute('''SELECT master_name, status, created_at FROM recommendations 
                    WHERE user_id = ? ORDER BY id DESC LIMIT 5''', (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "❌ У вас пока нет рекомендаций.")
        return
    text = "📋 **Ваши рекомендации:**\n\n"
    for row in rows:
        master, status, date = row
        if status == 'на модерации':
            status_emoji = '⏳'
        elif status == 'одобрено':
            status_emoji = '✅'
        elif status == 'отклонено':
            status_emoji = '❌'
        else:
            status_emoji = '📌'
        text += f"{status_emoji} {master} – {status} ({date})\n"
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['add_from_rec'])
def add_from_recommendation(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав.")
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Используйте: /add_from_rec [ID рекомендации]")
            return
        rec_id = int(parts[1])

        cursor.execute('SELECT * FROM recommendations WHERE id = ?', (rec_id,))
        rec = cursor.fetchone()
        if not rec:
            bot.reply_to(message, f"❌ Рекомендация с ID {rec_id} не найдена.")
            return

        cursor.execute('''INSERT INTO master_applications
                        (user_id, username, name, service, phone, districts, price_min, price_max,
                         experience, portfolio, documents, entity_type, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (rec[1], rec[2], rec[3], rec[4], rec[5],
                         'Не указано', 'Не указано', 'Не указано',
                         'Не указано', rec[7], 'Рекомендация',
                         'individual', 'На проверке (рекомендован)',
                         datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()

        cursor.execute('''UPDATE recommendations SET status = 'одобрено' WHERE id = ?''', (rec_id,))
        conn.commit()

        bot.reply_to(message, f"✅ Мастер {rec[3]} добавлен на проверку (анкета создана).")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['reject_rec'])
def reject_recommendation(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав.")
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Используйте: /reject_rec [ID рекомендации]")
            return
        rec_id = int(parts[1])
        cursor.execute('''UPDATE recommendations SET status = 'отклонено' WHERE id = ?''', (rec_id,))
        conn.commit()
        bot.reply_to(message, f"❌ Рекомендация {rec_id} отклонена.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ================ АНКЕТА МАСТЕРА (ТОЛЬКО В ЛС) ================
if not hasattr(bot, 'master_data'):
    bot.master_data = {}

@bot.message_handler(commands=['become_master'])
@bot.message_handler(func=lambda message: message.text == '👷 Стать мастером')
def become_master(message):
    if not only_private(message):
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👤 Частное лицо", callback_data="entity_individual"),
        types.InlineKeyboardButton("🏢 Компания / ИП", callback_data="entity_company")
    )

    bot.send_message(
        message.chat.id,
        "👷 **ЗАПОЛНЕНИЕ АНКЕТЫ МАСТЕРА**\n\n"
        "Шаг 1 из 12\n"
        "👇 **ВЫБЕРИТЕ ТИП:**",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('entity_'))
def entity_callback(call):
    entity_type = call.data.split('_')[1]
    bot.master_data[call.from_user.id] = {'entity_type': entity_type}

    if entity_type == 'individual':
        question = "👤 **ВВЕДИТЕ ВАШЕ ИМЯ:**"
    else:
        question = "🏢 **ВВЕДИТЕ НАЗВАНИЕ КОМПАНИИ ИЛИ БРИГАДЫ:**"

    bot.edit_message_text(
        f"👷 **ЗАПОЛНЕНИЕ АНКЕТЫ МАСТЕРА**\n\n"
        f"Шаг 2 из 12\n"
        f"👇 {question}",
        call.message.chat.id,
        call.message.message_id
    )
    bot.register_next_step_handler(call.message, process_master_name, entity_type)
    bot.answer_callback_query(call.id)

def process_master_name(message, entity_type):
    if message.chat.type != 'private':
        return
    name = safe_text(message)
    if not name:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите имя/название.")
        return

    bot.master_data[message.from_user.id]['name'] = name
    bot.master_data[message.from_user.id]['entity_type'] = entity_type

    msg = bot.send_message(
        message.chat.id,
        "👷 **Шаг 3 из 12**\n\n"
        "👇 **ВЫБЕРИТЕ СПЕЦИАЛИЗАЦИЮ:**\n\n"
        "Введите цифру или название:\n"
        "1 - Сантехник\n"
        "2 - Электрик\n"
        "3 - Отделочник\n"
        "4 - Строитель\n"
        "5 - Сварщик\n"
        "6 - Разнорабочий\n"
        "7 - Другое"
    )
    bot.register_next_step_handler(msg, process_master_service, name, entity_type)

def process_master_service(message, name, entity_type):
    if message.chat.type != 'private':
        return
    text = safe_text(message)
    if not text:
        bot.send_message(message.chat.id, "❌ Пожалуйста, выберите специализацию.")
        return
    service_input = text.lower()
    if service_input == "1" or "сантехник" in service_input:
        service = "Сантехник"
    elif service_input == "2" or "электрик" in service_input:
        service = "Электрик"
    elif service_input == "3" or "отделочник" in service_input:
        service = "Отделочник"
    elif service_input == "4" or "строитель" in service_input:
        service = "Строитель"
    elif service_input == "5" or "сварщик" in service_input:
        service = "Сварщик"
    elif service_input == "6" or "разнорабочий" in service_input:
        service = "Разнорабочий"
    else:
        service = text.capitalize()

    bot.master_data[message.from_user.id]['service'] = service

    msg = bot.send_message(
        message.chat.id,
        "📞 **Шаг 4 из 12**\n\n"
        "👇 **ВВЕДИТЕ ВАШ ТЕЛЕФОН:**\n\n"
        "Пример: +7 924 123-45-67\n\n"
        "⚠️ Номер будет виден ТОЛЬКО администратору"
    )
    bot.register_next_step_handler(msg, process_master_phone, name, service, entity_type)

def process_master_phone(message, name, service, entity_type):
    if message.chat.type != 'private':
        return
    phone = safe_text(message)
    if not phone:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите телефон.")
        return

    bot.master_data[message.from_user.id]['phone'] = phone

    msg = bot.send_message(
        message.chat.id,
        "📍 **Шаг 5 из 12**\n\n"
        "👇 **В КАКИХ РАЙОНАХ/ЖК ВЫ РАБОТАЕТЕ?**\n\n"
        "Перечислите через запятую:\n"
        "Пример: Патрокл, Снеговая Падь, Варяг, Океан"
    )
    bot.register_next_step_handler(msg, process_master_districts, name, service, phone, entity_type)

def process_master_districts(message, name, service, phone, entity_type):
    if message.chat.type != 'private':
        return
    districts = safe_text(message)
    if not districts:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите районы.")
        return

    bot.master_data[message.from_user.id]['districts'] = districts

    msg = bot.send_message(
        message.chat.id,
        "💰 **Шаг 6 из 12**\n\n"
        "👇 **МИНИМАЛЬНАЯ ЦЕНА ЗАКАЗА:**\n\n"
        "Пример: 1000₽, 5000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_min, name, service, phone, districts, entity_type)

def process_master_price_min(message, name, service, phone, districts, entity_type):
    if message.chat.type != 'private':
        return
    price_min = safe_text(message)
    if not price_min:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите минимальную цену.")
        return

    bot.master_data[message.from_user.id]['price_min'] = price_min

    msg = bot.send_message(
        message.chat.id,
        "💰 **Шаг 7 из 12**\n\n"
        "👇 **МАКСИМАЛЬНАЯ ЦЕНА ЗАКАЗА:**\n\n"
        "Пример: 50000₽, 100000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_max, name, service, phone, districts, price_min, entity_type)

def process_master_price_max(message, name, service, phone, districts, price_min, entity_type):
    if message.chat.type != 'private':
        return
    price_max = safe_text(message)
    if not price_max:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите максимальную цену.")
        return

    bot.master_data[message.from_user.id]['price_max'] = price_max

    msg = bot.send_message(
        message.chat.id,
        "⏱️ **Шаг 8 из 12**\n\n"
        "👇 **ВАШ ОПЫТ РАБОТЫ:**\n\n"
        "Пример: 3 года, 5 лет, 10+ лет"
    )
    bot.register_next_step_handler(msg, process_master_experience, name, service, phone, districts, price_min, price_max, entity_type)

def process_master_experience(message, name, service, phone, districts, price_min, price_max, entity_type):
    if message.chat.type != 'private':
        return
    experience = safe_text(message)
    if not experience:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите опыт работы.")
        return

    bot.master_data[message.from_user.id]['experience'] = experience

    # Шаг 9 – Комментарий о себе (можно пропустить)
    user_data = {
        'name': name,
        'service': service,
        'phone': phone,
        'districts': districts,
        'price_min': price_min,
        'price_max': price_max,
        'experience': experience,
        'entity_type': entity_type
    }
    bot.master_data[message.from_user.id].update(user_data)

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "⏩ Пропустить",
        callback_data="skip_bio"
    ))

    bot.send_message(
        message.chat.id,
        "📝 **Шаг 9 из 12**\n\n"
        "👇 **КОММЕНТАРИЙ О СЕБЕ (кратко):**\n\n"
        "Расскажите о себе пару слов: опыт, специализация, подход к работе.\n"
        "Это увидят клиенты в вашей карточке.\n\n"
        "👉 **Или нажмите «Пропустить»**",
        reply_markup=markup
    )
    bot.register_next_step_handler(message, process_master_bio, user_data)

@bot.callback_query_handler(func=lambda call: call.data == 'skip_bio')
def skip_bio_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные не найдены. Начните анкету заново.")
        return

    user_data = bot.master_data[user_id]
    user_data['bio'] = "Не указано"
    bot.master_data[user_id] = user_data

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "⏩ Пропустить",
        callback_data="skip_portfolio"
    ))
    bot.edit_message_text(
        "📸 **Шаг 10 из 12**\n\n"
        "👇 **ОТПРАВЬТЕ ССЫЛКУ НА ПОРТФОЛИО:**\n\n"
        "Это может быть:\n"
        "• Ссылка на Яндекс.Диск с фото\n"
        "• Ссылка на Google Фото\n"
        "• Telegram-канал с работами\n\n"
        "👉 **Или нажмите кнопку «Пропустить»**",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id, "⏩ Пропущено")

def process_master_bio(message, user_data):
    if message.chat.type != 'private':
        return
    bio = safe_text(message)
    if not bio or bio.lower() == "пропустить":
        bio = "Не указано"

    user_id = message.from_user.id
    if user_id not in bot.master_data:
        bot.master_data[user_id] = user_data
    bot.master_data[user_id]['bio'] = bio

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "⏩ Пропустить",
        callback_data="skip_portfolio"
    ))
    bot.send_message(
        message.chat.id,
        "📸 **Шаг 10 из 12**\n\n"
        "👇 **ОТПРАВЬТЕ ССЫЛКУ НА ПОРТФОЛИО:**\n\n"
        "Это может быть:\n"
        "• Ссылка на Яндекс.Диск с фото\n"
        "• Ссылка на Google Фото\n"
        "• Telegram-канал с работами\n\n"
        "👉 **Или нажмите кнопку «Пропустить»**",
        reply_markup=markup
    )
    bot.register_next_step_handler(message, process_master_portfolio_text, user_data)

@bot.callback_query_handler(func=lambda call: call.data == 'skip_portfolio')
def skip_portfolio_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные не найдены. Начните анкету заново.")
        return

    user_data = bot.master_data[user_id]
    user_data['portfolio'] = "Не указано"
    bot.master_data[user_id] = user_data

    show_documents_buttons(call.message.chat.id, user_id, user_data)
    bot.answer_callback_query(call.id, "⏩ Пропущено")

def process_master_portfolio_text(message, user_data):
    if message.chat.type != 'private':
        return
    portfolio = safe_text(message)
    if not portfolio or portfolio.lower() == "пропустить":
        portfolio = "Не указано"

    user_id = message.from_user.id
    if user_id not in bot.master_data:
        bot.master_data[user_id] = user_data
    bot.master_data[user_id]['portfolio'] = portfolio

    show_documents_buttons(message.chat.id, user_id, bot.master_data[user_id])

def show_documents_buttons(chat_id, user_id, user_data):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("✅ Есть", callback_data="doc_yes"),
        types.InlineKeyboardButton("❌ Нет", callback_data="doc_no"),
        types.InlineKeyboardButton("⏩ Пропустить", callback_data="doc_skip")
    )
    bot.send_message(
        chat_id,
        "📄 **Шаг 11 из 12**\n\n"
        "👇 **ПОДТВЕРЖДАЮЩИЕ ДОКУМЕНТЫ:**\n\n"
        "Есть ли у вас:\n"
        "• Самозанятость/ИП\n"
        "• Паспорт (личная встреча)\n"
        "• Договор подряда\n\n"
        "👉 **Выберите вариант:**",
        reply_markup=markup
    )
    bot.master_data[user_id] = user_data

@bot.callback_query_handler(func=lambda call: call.data.startswith('doc_'))
def documents_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные не найдены. Начните анкету заново.")
        return

    user_data = bot.master_data[user_id]
    choice = call.data.split('_')[1]

    if choice == 'yes':
        documents = "Есть"
    elif choice == 'no':
        documents = "Нет"
    else:
        documents = "Пропустить"

    user_data['documents'] = documents
    bot.master_data[user_id] = user_data

    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

    save_master_application(call.message, user_id, user_data)
    bot.answer_callback_query(call.id, f"Выбрано: {documents}")

def save_master_application(message, user_id, user_data):
    name = user_data['name']
    service = user_data['service']
    phone = user_data['phone']
    districts = user_data['districts']
    price_min = user_data['price_min']
    price_max = user_data['price_max']
    experience = user_data['experience']
    bio = user_data.get('bio', 'Не указано')
    portfolio = user_data.get('portfolio', 'Не указано')
    documents = user_data['documents']
    entity_type = user_data['entity_type']

    cursor.execute('''INSERT INTO master_applications
                    (user_id, username, name, service, phone, districts, 
                     price_min, price_max, experience, bio, portfolio, documents, 
                     entity_type, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id,
                     message.from_user.username or "no_username",
                     name, service, phone, districts,
                     price_min, price_max, experience, bio, portfolio, documents,
                     entity_type,
                     'На проверке',
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    application_id = cursor.lastrowid

    master_data = {
        'id': application_id,
        'date': datetime.now().strftime("%d.%m.%Y"),
        'name': name,
        'service': service,
        'phone': phone,
        'districts': districts,
        'price_min': price_min,
        'price_max': price_max,
        'experience': experience,
        'bio': bio,
        'portfolio': portfolio,
        'documents': documents,
        'rating': '4.8',
        'reviews_count': '0',
        'status': 'На проверке',
        'telegram_id': user_id,
        'entity_type': entity_type
    }
    add_master_to_google_sheet(master_data)

    entity_display = "👤 Частное лицо" if entity_type == 'individual' else "🏢 Компания/ИП"
    admin_msg = f"""
🆕 **НОВАЯ АНКЕТА МАСТЕРА!** (ID: {application_id})

{entity_display}
👤 **Имя/Название:** {name}
🔨 **Специализация:** {service}
📞 **Телефон:** {phone}
📍 **Районы:** {districts}
💰 **Цены:** {price_min} - {price_max}
⏱️ **Опыт:** {experience}
💬 **О себе:** {bio}
📸 **Портфолио:** {portfolio}
📄 **Документы:** {documents}
👤 **Telegram:** @{message.from_user.username or "нет"}
🆔 **ID:** {user_id}
**Статус:** ⏳ На проверке

✅ Одобрить: /approve {application_id}
❌ Отклонить: /reject {application_id} [причина]
    """
    try:
        if ADMIN_ID != 0:
            bot.send_message(ADMIN_ID, admin_msg)
    except:
        pass

    bot.send_message(
        message.chat.id,
        "✅ **ВАША АНКЕТА ОТПРАВЛЕНА!**\n\n"
        "Спасибо за доверие!\n\n"
        "📌 **Что дальше?**\n"
        "1. Администратор проверит анкету (обычно 1-2 дня)\n"
        "2. Мы можем запросить фото работ или отзывы\n"
        "3. После проверки ваша карточка появится в канале\n\n"
        "Статус проверки можно узнать по команде /my_status"
    )

    if user_id in bot.master_data:
        del bot.master_data[user_id]

# ================ ПРОВЕРКА СТАТУСА АНКЕТЫ ================
@bot.message_handler(commands=['my_status'])
def my_status(message):
    if not only_private(message):
        return
    cursor.execute('''SELECT status, created_at FROM master_applications 
                    WHERE user_id = ? ORDER BY id DESC LIMIT 1''', (message.from_user.id,))
    row = cursor.fetchone()
    if row:
        status, date = row
        if status == "На проверке":
            text = "⏳ **Статус:** На проверке\n\nВаша анкета ещё проверяется администратором. Обычно это занимает 1-2 дня."
        elif status == "Одобрена":
            text = "✅ **Статус:** Одобрена!\n\nПоздравляем! Ваша карточка уже опубликована в канале."
        elif status == "Отклонена":
            text = "❌ **Статус:** Отклонена\n\nК сожалению, ваша анкета не прошла проверку. Свяжитесь с администратором для уточнения причин."
        else:
            text = f"📌 **Статус:** {status}"
    else:
        text = "❌ У вас нет активных анкет.\n\nЧтобы подать заявку, нажмите «👷 Стать мастером»"
    bot.send_message(message.chat.id, text)

# ================ ПУБЛИКАЦИЯ КАРТОЧКИ МАСТЕРА В КАНАЛЕ ================
def publish_master_card(master_data):
    if master_data.get('entity_type') == 'company':
        type_icon = '🏢'
        type_text = 'Компания'
    else:
        type_icon = '👤'
        type_text = 'Частное лицо'

    card = f"""
{type_icon} **{master_data['name']}** ({type_text})
🔧 **Специализация:** {master_data['service']}
📍 **Районы:** {master_data['districts']}
💰 **Цены:** {master_data['price_min']} – {master_data['price_max']}
⏱ **Опыт:** {master_data['experience']}
"""

    if master_data.get('bio') and master_data['bio'] != 'Не указано':
        card += f"💬 **О себе:** {master_data['bio']}\n"

    if master_data.get('portfolio') and master_data['portfolio'] != 'Не указано':
        card += f"📸 **Портфолио:** {master_data['portfolio']}\n"

    docs = '✅ Есть' if master_data.get('documents_verified') else '⏳ Ожидает'
    photos = '✅ Есть' if master_data.get('photos_verified') else '⏳ Ожидает'
    rating = master_data.get('rating', 0)
    reviews_count = master_data.get('reviews_count', 0)

    card += f"""
🛡 **Статус проверки:**
   📄 Документы: {docs}
   📷 Фото работ: {photos}
   💬 Отзывы: ⭐ {rating:.1f} ({reviews_count} отзывов)
"""

    if master_data.get('username'):
        contact = f"📞 **Контакт:** @{master_data['username']}"
    else:
        contact = f"📞 **Контакт:** `{master_data.get('phone', 'Не указан')[:10]}…`"

    card += f"""
{contact}

👉 **Оставить заявку:** @remontvl25chat
"""
    try:
        sent = bot.send_message(CHANNEL_LINK, card)
        print(f"✅ Карточка мастера {master_data['name']} опубликована в канале")
        return sent.message_id
    except Exception as e:
        print(f"❌ Ошибка публикации карточки: {e}")
        return None

# ================ КОМАНДЫ АДМИНИСТРАТОРА ================
@bot.message_handler(commands=['approve'])
def approve_master(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для этой команды.")
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Используйте: /approve [ID анкеты]")
            return
        application_id = int(parts[1])

        cursor.execute('SELECT * FROM master_applications WHERE id = ?', (application_id,))
        app = cursor.fetchone()
        if not app:
            bot.reply_to(message, f"❌ Анкета с ID {application_id} не найдена.")
            return

        # Индексы: 0-id,1-user_id,2-username,3-name,4-service,5-phone,6-districts,7-price_min,
        # 8-price_max,9-experience,10-bio,11-portfolio,12-documents,13-entity_type,14-status,15-created_at
        cursor.execute('''UPDATE master_applications SET status = 'Одобрена' WHERE id = ?''', (application_id,))

        cursor.execute('''INSERT INTO masters
                        (user_id, name, service, phone, districts, price_min, price_max,
                         experience, bio, portfolio, rating, reviews_count, status, entity_type,
                         documents_verified, photos_verified, reviews_verified, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (app[1], app[3], app[4], app[5], app[6],
                         app[7], app[8], app[9], app[10], app[11],
                         0.0, 0, 'активен', app[13],
                         0, 0, 0,
                         datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()
        master_id = cursor.lastrowid

        master_data = {
            'name': app[3],
            'service': app[4],
            'phone': app[5],
            'districts': app[6],
            'price_min': app[7],
            'price_max': app[8],
            'experience': app[9],
            'bio': app[10],
            'portfolio': app[11],
            'entity_type': app[13],
            'username': app[2],
            'documents_verified': 0,
            'photos_verified': 0,
            'rating': 0.0,
            'reviews_count': 0
        }

        publish_master_card(master_data)
        update_master_status_in_google_sheet(app[1], 'Одобрена')

        try:
            bot.send_message(
                app[1],
                f"✅ **ВАША АНКЕТА ОДОБРЕНА!**\n\n"
                f"Поздравляем! Ваша карточка уже опубликована в канале {CHANNEL_LINK}\n\n"
                f"📌 **Что дальше?**\n"
                f"1. Клиенты будут видеть вашу карточку и смогут оставлять заявки.\n"
                f"2. Вы получите уведомление, когда кто-то оставит заявку.\n"
                f"3. Отвечайте на заявки в чате @remontvl25chat."
            )
        except:
            pass

        bot.reply_to(message, f"✅ Мастер {app[3]} одобрен! Карточка опубликована в канале.")
    except ValueError:
        bot.reply_to(message, "❌ ID анкеты должен быть числом.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['reject'])
def reject_master(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для этой команды.")
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Используйте: /reject [ID анкеты] [причина]")
            return
        application_id = int(parts[1])
        reason = ' '.join(parts[2:]) if len(parts) > 2 else 'Не указана'

        cursor.execute('SELECT * FROM master_applications WHERE id = ?', (application_id,))
        app = cursor.fetchone()
        if not app:
            bot.reply_to(message, f"❌ Анкета с ID {application_id} не найдена.")
            return

        cursor.execute('''UPDATE master_applications SET status = 'Отклонена' WHERE id = ?''', (application_id,))
        conn.commit()

        update_master_status_in_google_sheet(app[1], 'Отклонена')

        try:
            bot.send_message(
                app[1],
                f"❌ **ВАША АНКЕТА ОТКЛОНЕНА**\n\n"
                f"**Причина:** {reason}\n\n"
                f"Свяжитесь с администратором: @remont_vl25\n\n"
                f"Вы можете подать заявку снова после исправления замечаний."
            )
        except:
            pass

        bot.reply_to(message, f"❌ Мастер {app[3]} отклонён. Причина: {reason}.")
    except ValueError:
        bot.reply_to(message, "❌ ID анкеты должен быть числом.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ================ КОМАНДЫ АДМИНИСТРАТОРА ДЛЯ УПРАВЛЕНИЯ МАСТЕРАМИ ================
@bot.message_handler(commands=['list_masters'])
def list_masters(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для этой команды.")
        return

    cursor.execute('''
        SELECT id, name, service, phone, status 
        FROM masters 
        ORDER BY id DESC 
        LIMIT 30
    ''')
    masters = cursor.fetchall()

    if not masters:
        bot.reply_to(message, "📭 База мастеров пуста.")
        return

    text = "📋 **Список мастеров (последние 30):**\n\n"
    for m in masters:
        mid, name, service, phone, status = m
        status_icon = '✅' if status == 'активен' else '❌'
        phone_short = phone[:10] + '…' if phone else '—'
        text += f"{status_icon} ID {mid}: **{name}** – {service}, {phone_short}\n"

    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['view_master'])
def view_master(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для этой команды.")
        return

    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Используйте: /view_master [ID мастера]")
            return
        master_id = int(parts[1])

        cursor.execute('''SELECT * FROM masters WHERE id = ?''', (master_id,))
        m = cursor.fetchone()
        if not m:
            bot.reply_to(message, f"❌ Мастер с ID {master_id} не найден.")
            return

        # Индексы полей:
        # 0-id,1-user_id,2-name,3-service,4-phone,5-districts,6-price_min,7-price_max,
        # 8-experience,9-bio,10-portfolio,11-rating,12-reviews_count,13-status,
        # 14-entity_type,15-documents_verified,16-photos_verified,17-reviews_verified,
        # 18-channel_message_id,19-created_at
        text = f"""
📌 **Мастер ID:** {m[0]}
👤 **Имя:** {m[2]}
🔧 **Специализация:** {m[3]}
📞 **Телефон:** {m[4]}
📍 **Районы:** {m[5]}
💰 **Цены:** {m[6]} – {m[7]}
⏱ **Опыт:** {m[8]}
💬 **О себе:** {m[9] or 'Не указано'}
📸 **Портфолио:** {m[10] or 'Не указано'}
⭐ **Рейтинг:** {m[11]:.1f} ({m[12]} отзывов)
📊 **Статус:** {m[13]}
🏷 **Тип:** {m[14]}
🆔 **Telegram ID:** {m[1]}
📄 **Документы:** {'✅' if m[15] else '❌'}
📷 **Фото:** {'✅' if m[16] else '❌'}
💬 **Отзывы проверены:** {'✅' if m[17] else '❌'}
📅 **Добавлен:** {m[19]}

📋 **Изменить:** /edit_master {m[0]}
🗑 **Удалить:** /delete_master {m[0]}
"""
        bot.send_message(message.chat.id, text)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

if not hasattr(bot, 'edit_states'):
    bot.edit_states = {}

@bot.message_handler(commands=['edit_master'])
def edit_master(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для этой команды.")
        return

    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Используйте: /edit_master [ID мастера]")
            return
        master_id = int(parts[1])

        cursor.execute('SELECT * FROM masters WHERE id = ?', (master_id,))
        master = cursor.fetchone()
        if not master:
            bot.reply_to(message, f"❌ Мастер с ID {master_id} не найден.")
            return

        bot.edit_states[message.from_user.id] = {'master_id': master_id, 'step': 0}

        markup = types.InlineKeyboardMarkup(row_width=2)
        fields = [
            ("Имя", "name"),
            ("Специализация", "service"),
            ("Телефон", "phone"),
            ("Районы", "districts"),
            ("Мин. цена", "price_min"),
            ("Макс. цена", "price_max"),
            ("Опыт", "experience"),
            ("Комментарий", "bio"),
            ("Портфолио", "portfolio"),
            ("Статус (активен/заблокирован)", "status"),
            ("Документы проверены", "documents_verified"),
            ("Фото проверены", "photos_verified"),
            ("Отзывы проверены", "reviews_verified"),
        ]
        for label, field in fields:
            markup.add(types.InlineKeyboardButton(
                label, callback_data=f"edit_{field}_{master_id}"
            ))
        markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="edit_cancel"))

        bot.send_message(
            message.chat.id,
            f"✏️ **Редактирование мастера ID {master_id}**\n\nВыберите поле для изменения:",
            reply_markup=markup
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_') or call.data == 'edit_cancel')
def edit_callback(call):
    user_id = call.from_user.id
    if call.data == 'edit_cancel':
        bot.edit_message_text("❌ Редактирование отменено.", call.message.chat.id, call.message.message_id)
        if user_id in bot.edit_states:
            del bot.edit_states[user_id]
        bot.answer_callback_query(call.id)
        return

    _, field, master_id = call.data.split('_', 2)
    master_id = int(master_id)

    bot.edit_states[user_id] = {'master_id': master_id, 'field': field}

    bot.edit_message_text(
        f"✏️ Введите новое значение для поля **{field}**:\n\n"
        f"(отправьте текст или /cancel для отмены)",
        call.message.chat.id,
        call.message.message_id
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: 
    message.chat.type == 'private' and 
    message.from_user.id in bot.edit_states and 
    'field' in bot.edit_states[message.from_user.id]
)
def process_edit_value(message):
    user_id = message.from_user.id
    state = bot.edit_states[user_id]
    field = state['field']
    master_id = state['master_id']
    new_value = message.text.strip()

    if new_value == '/cancel':
        bot.send_message(message.chat.id, "❌ Редактирование отменено.")
        del bot.edit_states[user_id]
        return

    try:
        if field in ['documents_verified', 'photos_verified', 'reviews_verified']:
            if new_value.lower() in ['1', 'да', 'yes', 'true']:
                new_value = 1
            elif new_value.lower() in ['0', 'нет', 'no', 'false']:
                new_value = 0
            else:
                bot.send_message(message.chat.id, "❌ Введите 1/0 или да/нет.")
                return
            cursor.execute(f'UPDATE masters SET {field} = ? WHERE id = ?', (new_value, master_id))
        elif field == 'status':
            if new_value.lower() not in ['активен', 'заблокирован']:
                bot.send_message(message.chat.id, "❌ Статус должен быть 'активен' или 'заблокирован'.")
                return
            cursor.execute(f'UPDATE masters SET {field} = ? WHERE id = ?', (new_value, master_id))
        else:
            cursor.execute(f'UPDATE masters SET {field} = ? WHERE id = ?', (new_value, master_id))
        conn.commit()
        bot.send_message(message.chat.id, f"✅ Поле **{field}** обновлено на: {new_value}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при обновлении: {e}")
    finally:
        del bot.edit_states[user_id]

@bot.message_handler(commands=['delete_master'])
def delete_master(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для этой команды.")
        return

    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Используйте: /delete_master [ID мастера]")
            return
        master_id = int(parts[1])

        cursor.execute('SELECT name, user_id FROM masters WHERE id = ?', (master_id,))
        master = cursor.fetchone()
        if not master:
            bot.reply_to(message, f"❌ Мастер с ID {master_id} не найден.")
            return
        master_name, user_id = master

        cursor.execute('DELETE FROM masters WHERE id = ?', (master_id,))
        conn.commit()

        update_master_status_in_google_sheet(user_id, 'Удалён')

        try:
            bot.send_message(
                user_id,
                f"❌ Ваша карточка была удалена из каталога.\n"
                f"По вопросам: @remont_vl25"
            )
        except:
            pass

        bot.reply_to(message, f"✅ Мастер {master_name} (ID {master_id}) удалён из базы.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ================ КОНТАКТЫ (ТОЛЬКО В ЛС) ================
@bot.message_handler(commands=['contacts'])
@bot.message_handler(func=lambda message: message.text == '📞 Контакты')
def contacts(message):
    if not only_private(message):
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📢 Канал с мастерами", url="https://t.me/remont_vl25"),
        types.InlineKeyboardButton("💬 Чат-заявок", url="https://t.me/remontvl25chat"),
        types.InlineKeyboardButton("👨‍💻 Администратор", url="https://t.me/remont_vl25")
    )
    bot.send_message(
        message.chat.id,
        f"📞 **КОНТАКТЫ**\n\n"
        f"📢 **Канал с мастерами:** {CHANNEL_LINK}\n"
        f"💬 **Чат-заявок:** {CHAT_ID}\n"
        f"🤖 **Этот бот:** @remont_vl25_chat_bot\n"
        f"👨‍💻 **Администратор:** @remont_vl25\n\n"
        f"📌 По вопросам сотрудничества и рекламы — пишите админу!",
        reply_markup=markup
    )

# ================ ПОМОЩЬ (ТОЛЬКО В ЛС) ================
@bot.message_handler(commands=['help'])
def help_command(message):
    if not only_private(message):
        return
    bot.send_message(
        message.chat.id,
        "❓ **ПОМОЩЬ**\n\n"
        "**Доступные команды:**\n"
        "/start - Запустить бота\n"
        "/request - Оставить заявку\n"
        "/review - Оставить отзыв\n"
        "/search - Найти мастера (каталог)\n"
        "/recommend - Рекомендовать мастера\n"
        "/become_master - Стать мастером (анкета в боте)\n"
        "/my_status - Статус анкеты\n"
        "/my_recommend_status - Статус рекомендаций\n"
        "/contacts - Контакты\n"
        "/help - Это сообщение\n\n"
        "**Как найти мастера?**\n"
        "1️⃣ **Самостоятельный выбор** – нажмите «🔍 Найти мастера», выберите специализацию, сравните рейтинг и цены.\n"
        "2️⃣ **Заявка в чате** – напишите в @remontvl25chat: «Ищу [услуга], [район], [бюджет]». Мастера откликнутся.\n\n"
        "**Как стать мастером?**\n"
        "• Заполните анкету в боте («👷 Стать мастером») или через Google Forms («📋 Анкета (Google Forms)»).\n"
        "• После проверки администратора ваша карточка появится в канале и каталоге.\n\n"
        "**Как рекомендовать мастера?**\n"
        "• Нажмите «👍 Рекомендовать мастера» и укажите данные.\n"
        "• После проверки мастер будет добавлен в базу."
    )

# ================ ОБРАБОТКА НЕИЗВЕСТНЫХ КОМАНД ================
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    if message.chat.type == 'private':
        if message.text and message.text.startswith('/'):
            bot.send_message(
                message.chat.id,
                "❌ Неизвестная команда. Используйте /help для списка команд."
            )
        else:
            bot.send_message(
                message.chat.id,
                "👋 Используйте команды из меню или нажмите /help"
            )

# ================ ЗАПУСК БОТА ================
if __name__ == '__main__':
    print("=" * 60)
    print("✅ Бот запускается...")
    print(f"🤖 Токен: {TOKEN[:10]}...")
    print(f"💬 Чат: {CHAT_ID}")
    print(f"📢 Канал: {CHANNEL_LINK}")
    print(f"👑 Админ ID: {ADMIN_ID}")
    print("=" * 60)

    reset_webhook()
    stop_other_instances()
    time.sleep(2)

    print("⏳ Бот работает 24/7...")
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            if "409" in str(e):
                print("🔄 Обнаружен конфликт! Сброс...")
                reset_webhook()
                stop_other_instances()
            time.sleep(5)
