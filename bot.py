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

# Для Google Forms – замените на реальную ссылку после создания формы
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
                 name TEXT,
                 service TEXT,
                 phone TEXT,
                 districts TEXT,
                 price_min TEXT,
                 price_max TEXT,
                 experience TEXT,
                 portfolio TEXT,
                 rating REAL,
                 reviews_count INTEGER,
                 status TEXT,
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
                 portfolio TEXT,
                 documents TEXT,
                 status TEXT,
                 created_at TEXT)''')

# Добавляем недостающие колонки, если их нет
try:
    cursor.execute('ALTER TABLE requests ADD COLUMN description TEXT')
except:
    pass
try:
    cursor.execute('ALTER TABLE requests ADD COLUMN date TEXT')
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
            str(master_data.get('portfolio', 'Не указано')),
            str(master_data.get('documents', 'Не указано')),
            str(master_data.get('rating', '4.8')),
            str(master_data.get('reviews_count', '0')),
            str(master_data.get('status', 'На проверке')),
            str(master_data.get('telegram_id', ''))
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
                sheet.update_cell(i, 14, status)  # колонка N – статус
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
            "Нет",
            "Есть",
            "5.0",
            "1",
            "Тест",
            "12345"
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
            url="https://t.me/remont_vl25_final_bot"
        ))
        bot.reply_to(
            message,
            "❌ Эта команда работает только в личных сообщениях с ботом.\n\n"
            "👉 Напишите мне в ЛС: @remont_vl25_final_bot",
            reply_markup=markup
        )
        return False
    return True

# ================ УДАЛЕНИЕ КОМАНД В ЧАТЕ ================
@bot.message_handler(func=lambda message: message.chat.type != 'private')
def delete_group_commands(message):
    if message.text and (message.text.startswith('/') or '@remont_vl25_final_bot' in message.text):
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
            url="https://t.me/remont_vl25_final_bot"
        ))
        bot.reply_to(
            message,
            "👋 Добро пожаловать в бот заявок на ремонт!\n\n"
            "📌 В этом чате я только публикую заявки и отзывы.\n\n"
            "👇 Вся работа со мной — в личных сообщениях:\n"
            "👉 @remont_vl25_final_bot\n\n"
            "Там вы можете:\n"
            "✅ Оставить заявку на ремонт\n"
            "✅ Найти проверенного мастера\n"
            "✅ Стать мастером и добавить анкету\n"
            "✅ Оставить отзыв о работе\n"
            "✅ Проверить статус анкеты",
            reply_markup=markup
        )
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('🔨 Оставить заявку', '⭐ Оставить отзыв')
    markup.row('🔍 Найти мастера', '📞 Контакты')
    markup.row('📢 Канал с мастерами', '👷 Стать мастером')
    markup.row('📋 Анкета (Google Forms)')

    bot.send_message(
        message.chat.id,
        "👋 Добро пожаловать в бот заявок на ремонт!\n\n"
        "🔹 Хотите найти мастера? Нажмите «Оставить заявку»\n"
        "🔹 Хотите поблагодарить мастера? Нажмите «Оставить отзыв»\n"
        "🔹 Хотите добавить свою анкету? Нажмите «Стать мастером» (в боте) или «📋 Анкета (Google Forms)»\n\n"
        f"💬 Чат-заявок: {CHAT_ID}\n"
        f"📢 Канал с мастерами: {CHANNEL_LINK}",
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
        f"📢 Наш канал с проверенными мастерами: {CHANNEL_LINK}\n\n"
        "В канале вы найдете:\n"
        "✅ Карточки мастеров с отзывами\n"
        "✅ Реальные цены на ремонт\n"
        "✅ Фото работ до/после\n"
        "✅ Черный список мошенников",
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
        "🔨 СОЗДАНИЕ ЗАЯВКИ\n\n"
        "Шаг 1 из 5\n"
        "👇 ВЫБЕРИТЕ УСЛУГУ:\n\n"
        "Введите цифру или название:\n"
        "1 - Сантехник\n"
        "2 - Электрик\n"
        "3 - Отделочник\n"
        "4 - Строитель\n"
        "5 - Другое\n\n"
        "👉 Пример: 1 или сантехник"
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
        "📝 Шаг 2 из 5\n\n"
        "👇 КРАТКО ОПИШИТЕ ЗАДАЧУ:\n\n"
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
        "📍 Шаг 3 из 5\n\n"
        "👇 ВВЕДИТЕ РАЙОН ИЛИ ЖК:\n"
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
        "📅 Шаг 4 из 5\n\n"
        "👇 КОГДА НУЖНО ВЫПОЛНИТЬ РАБОТЫ?\n\n"
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
        "💰 Шаг 5 из 5\n\n"
        "👇 ВВЕДИТЕ БЮДЖЕТ:\n"
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

    cursor.execute('''INSERT INTO requests 
                    (user_id, username, service, description, district, date, budget, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (message.from_user.id,
                     message.from_user.username or "user",
                     service, description, district, date, budget,
                     'активна',
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()

    username = message.from_user.username or "Клиент"
    request_text = f"""
🆕 НОВАЯ ЗАЯВКА!

👤 От: @{username}
🔨 Услуга: {service}
📝 Задача: {description}
📍 Район/ЖК: {district}
📅 Когда: {date}
💰 Бюджет: {budget}
⏰ Создано: {datetime.now().strftime("%H:%M %d.%m.%Y")}

👇 Мастера, откликайтесь в комментариях!
"""
    bot.send_message(CHAT_ID, request_text)
    bot.send_message(
        message.chat.id,
        f"✅ ЗАЯВКА ОПУБЛИКОВАНА!\n\n"
        f"💬 Чат с мастерами: {CHAT_ID}\n"
        f"⏱ Ожидайте откликов в течение 5-10 минут.\n\n"
        f"📌 Если никто не ответил за 30 минут — создайте новую заявку."
    )

# ================ ОТЗЫВ (ТОЛЬКО В ЛС) ================
@bot.message_handler(commands=['review'])
@bot.message_handler(func=lambda message: message.text == '⭐ Оставить отзыв')
def add_review(message):
    if not only_private(message):
        return
    msg = bot.send_message(
        message.chat.id,
        "⭐ ОСТАВИТЬ ОТЗЫВ\n\n"
        "Напишите ИМЯ МАСТЕРА или НАЗВАНИЕ БРИГАДЫ:"
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
        "📝 НАПИШИТЕ ТЕКСТ ОТЗЫВА:\n"
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
        f"👤 Мастер: {master}\n"
        f"📝 Отзыв: {review_text}\n\n"
        "⭐ ОЦЕНИТЕ РАБОТУ ОТ 1 ДО 5:",
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
    cursor.execute('''SELECT service, phone FROM masters WHERE name LIKE ?''', (f'%{master_name}%',))
    master_data = cursor.fetchone()
    if master_data:
        service, phone = master_data
        extra_info = f"🔧 Специализация: {service}\n📞 Контакты: {phone[:10]}…"

    review_public = f"""
⭐ НОВЫЙ ОТЗЫВ!

👤 Мастер: {master_name}
⭐ Оценка: {'⭐' * rating}
📝 Отзыв: {review_text}
👤 От кого: @{user_name}
{extra_info}
⏰ {created_at}
"""
    bot.send_message(CHAT_ID, review_public)

    bot.answer_callback_query(call.id, f"Спасибо! Оценка {rating} ⭐ сохранена")
    bot.edit_message_text(
        f"✅ СПАСИБО ЗА ОТЗЫВ!\n\n"
        f"👤 Мастер: {master_name}\n"
        f"⭐ Оценка: {'⭐' * rating}\n"
        f"📝 Отзыв: {review_text}\n\n"
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
            "🔍 В базе пока нет мастеров.\n\n"
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
        "🔍 **Каталог мастеров**\n\nВыберите специализацию:",
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
        SELECT name, service, districts, price_min, price_max, rating, reviews_count, phone
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
        name, service, districts, price_min, price_max, rating, reviews, phone = m
        rating_stars = '⭐' * int(round(rating or 0)) + ('½' if rating and rating % 1 >= 0.5 else '')
        phone_display = phone[:10] + '…' if len(phone) > 10 else phone

        text += f"👤 **{name}**\n"
        text += f"   📍 {districts}\n"
        text += f"   💰 {price_min} – {price_max}\n"
        text += f"   ⭐ {rating:.1f} ({reviews} отзывов)\n"
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
        f"📞 КОНТАКТЫ\n\n"
        f"📢 Канал с мастерами: {CHANNEL_LINK}\n"
        f"💬 Чат-заявок: {CHAT_ID}\n"
        f"🤖 Этот бот: @remont_vl25_final_bot\n"
        f"👨‍💻 Администратор: @remont_vl25\n\n"
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
        "❓ ПОМОЩЬ\n\n"
        "Доступные команды:\n"
        "/start - Запустить бота\n"
        "/request - Оставить заявку\n"
        "/review - Оставить отзыв\n"
        "/search - Найти мастера (каталог)\n"
        "/become_master - Стать мастером (анкета в боте)\n"
        "/my_status - Статус анкеты\n"
        "/contacts - Контакты\n"
        "/help - Это сообщение\n\n"
        "Как найти мастера?\n"
        "1. Нажмите «🔍 Найти мастера» и выберите специализацию.\n"
        "2. Или оставьте заявку в чате @remontvl25chat – мастера сами откликнутся."
    )

# ================ АНКЕТА МАСТЕРА (ТОЛЬКО В ЛС) ================
@bot.message_handler(commands=['become_master'])
@bot.message_handler(func=lambda message: message.text == '👷 Стать мастером')
def become_master(message):
    if not only_private(message):
        return
    msg = bot.send_message(
        message.chat.id,
        "👷 ЗАПОЛНЕНИЕ АНКЕТЫ МАСТЕРА\n\n"
        "Шаг 1 из 10\n"
        "👇 ВВЕДИТЕ ВАШЕ ИМЯ ИЛИ НАЗВАНИЕ БРИГАДЫ:\n\n"
        "Пример: Иван Петров\n"
        "Или: Бригада «МастерОК»"
    )
    bot.register_next_step_handler(msg, process_master_name)

def process_master_name(message):
    if message.chat.type != 'private':
        return
    name = safe_text(message)
    if not name:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите имя.")
        return
    msg = bot.send_message(
        message.chat.id,
        "👷 Шаг 2 из 10\n\n"
        "👇 ВЫБЕРИТЕ СПЕЦИАЛИЗАЦИЮ:\n\n"
        "Введите цифру или название:\n"
        "1 - Сантехник\n"
        "2 - Электрик\n"
        "3 - Отделочник\n"
        "4 - Строитель\n"
        "5 - Сварщик\n"
        "6 - Разнорабочий\n"
        "7 - Другое"
    )
    bot.register_next_step_handler(msg, process_master_service, name)

def process_master_service(message, name):
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
        "📞 Шаг 3 из 10\n\n"
        "👇 ВВЕДИТЕ ВАШ ТЕЛЕФОН:\n\n"
        "Пример: +7 924 123-45-67\n\n"
        "⚠️ Номер будет виден ТОЛЬКО администратору"
    )
    bot.register_next_step_handler(msg, process_master_phone, name, service)

def process_master_phone(message, name, service):
    if message.chat.type != 'private':
        return
    phone = safe_text(message)
    if not phone:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите телефон.")
        return
    msg = bot.send_message(
        message.chat.id,
        "📍 Шаг 4 из 10\n\n"
        "👇 В КАКИХ РАЙОНАХ/ЖК ВЫ РАБОТАЕТЕ?\n\n"
        "Перечислите через запятую:\n"
        "Пример: Патрокл, Снеговая Падь, Варяг, Океан"
    )
    bot.register_next_step_handler(msg, process_master_districts, name, service, phone)

def process_master_districts(message, name, service, phone):
    if message.chat.type != 'private':
        return
    districts = safe_text(message)
    if not districts:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите районы.")
        return
    msg = bot.send_message(
        message.chat.id,
        "💰 Шаг 5 из 10\n\n"
        "👇 МИНИМАЛЬНАЯ ЦЕНА ЗАКАЗА:\n\n"
        "Пример: 1000₽, 5000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_min, name, service, phone, districts)

def process_master_price_min(message, name, service, phone, districts):
    if message.chat.type != 'private':
        return
    price_min = safe_text(message)
    if not price_min:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите минимальную цену.")
        return
    msg = bot.send_message(
        message.chat.id,
        "💰 Шаг 6 из 10\n\n"
        "👇 МАКСИМАЛЬНАЯ ЦЕНА ЗАКАЗА:\n\n"
        "Пример: 50000₽, 100000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_max, name, service, phone, districts, price_min)

def process_master_price_max(message, name, service, phone, districts, price_min):
    if message.chat.type != 'private':
        return
    price_max = safe_text(message)
    if not price_max:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите максимальную цену.")
        return
    msg = bot.send_message(
        message.chat.id,
        "⏱️ Шаг 7 из 10\n\n"
        "👇 ВАШ ОПЫТ РАБОТЫ:\n\n"
        "Пример: 3 года, 5 лет, 10+ лет"
    )
    bot.register_next_step_handler(msg, process_master_experience, name, service, phone, districts, price_min, price_max)

def process_master_experience(message, name, service, phone, districts, price_min, price_max):
    if message.chat.type != 'private':
        return
    experience = safe_text(message)
    if not experience:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите опыт работы.")
        return
    msg = bot.send_message(
        message.chat.id,
        "📸 Шаг 8 из 10\n\n"
        "👇 ОТПРАВЬТЕ ССЫЛКУ НА ПОРТФОЛИО:\n\n"
        "Это может быть:\n"
        "• Ссылка на Яндекс.Диск с фото\n"
        "• Ссылка на Google Фото\n"
        "• Telegram-канал с работами\n\n"
        "Или просто нажмите 'Пропустить'"
    )
    bot.register_next_step_handler(msg, process_master_portfolio, name, service, phone, districts, price_min, price_max, experience)

def process_master_portfolio(message, name, service, phone, districts, price_min, price_max, experience):
    if message.chat.type != 'private':
        return
    portfolio = safe_text(message)
    if not portfolio or portfolio.lower() == "пропустить":
        portfolio = "Не указано"
    msg = bot.send_message(
        message.chat.id,
        "📄 Шаг 9 из 10\n\n"
        "👇 ПОДТВЕРЖДАЮЩИЕ ДОКУМЕНТЫ:\n\n"
        "Есть ли у вас:\n"
        "• Самозанятость/ИП\n"
        "• Паспорт (личная встреча)\n"
        "• Договор подряда\n\n"
        "Напишите: Есть / Нет / Пропустить"
    )
    bot.register_next_step_handler(msg, process_master_documents, name, service, phone, districts, price_min, price_max, experience, portfolio)

def process_master_documents(message, name, service, phone, districts, price_min, price_max, experience, portfolio):
    if message.chat.type != 'private':
        return
    documents = safe_text(message)
    if not documents:
        documents = "Не указано"

    cursor.execute('''INSERT INTO master_applications
                    (user_id, username, name, service, phone, districts, 
                     price_min, price_max, experience, portfolio, documents, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (message.from_user.id,
                     message.from_user.username or "no_username",
                     name, service, phone, districts,
                     price_min, price_max, experience, portfolio, documents,
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
        'portfolio': portfolio,
        'documents': documents,
        'rating': '4.8',
        'reviews_count': '0',
        'status': 'На проверке',
        'telegram_id': message.from_user.id
    }
    add_master_to_google_sheet(master_data)

    admin_msg = f"""
🆕 НОВАЯ АНКЕТА МАСТЕРА! (ID: {application_id})

👤 Имя: {name}
🔨 Специализация: {service}
📞 Телефон: {phone}
📍 Районы: {districts}
💰 Цены: {price_min} - {price_max}
⏱️ Опыт: {experience}
📸 Портфолио: {portfolio}
📄 Документы: {documents}
👤 Telegram: @{message.from_user.username or "нет"}
🆔 ID: {message.from_user.id}
Статус: ⏳ На проверке

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
        "✅ ВАША АНКЕТА ОТПРАВЛЕНА!\n\n"
        "Спасибо за доверие!\n\n"
        "📌 Что дальше?\n"
        "1. Администратор проверит анкету (обычно 1-2 дня)\n"
        "2. Мы можем запросить фото работ или отзывы\n"
        "3. После проверки ваша карточка появится в канале\n\n"
        "Статус проверки можно узнать по команде /my_status"
    )

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
            text = "⏳ Статус: На проверке\n\nВаша анкета ещё проверяется администратором. Обычно это занимает 1-2 дня."
        elif status == "Одобрена":
            text = "✅ Статус: Одобрена!\n\nПоздравляем! Ваша карточка скоро появится в канале."
        elif status == "Отклонена":
            text = "❌ Статус: Отклонена\n\nК сожалению, ваша анкета не прошла проверку. Свяжитесь с администратором для уточнения причин."
        else:
            text = f"📌 Статус: {status}"
    else:
        text = "❌ У вас нет активных анкет\n\nЧтобы подать заявку, нажмите «👷 Стать мастером»"
    bot.send_message(message.chat.id, text)

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

        cursor.execute('''UPDATE master_applications SET status = 'Одобрена' WHERE id = ?''', (application_id,))
        cursor.execute('''INSERT INTO masters
                        (name, service, phone, districts, price_min, price_max, 
                         experience, portfolio, rating, reviews_count, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (app[3], app[4], app[5], app[6],
                         app[7], app[8], app[9], app[10],
                         4.8, 0, 'активен',
                         datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()

        update_master_status_in_google_sheet(app[1], 'Одобрена')

        try:
            bot.send_message(
                app[1],
                f"✅ ВАША АНКЕТА ОДОБРЕНА!\n\n"
                f"Поздравляем! Теперь вы в базе проверенных мастеров.\n"
                f"Ваша карточка будет опубликована в канале {CHANNEL_LINK}\n\n"
                f"📌 Что дальше?\n"
                f"1. Мы подготовим вашу карточку\n"
                f"2. Вы получите заявки из чата\n"
                f"3. Клиенты смогут оставлять отзывы"
            )
        except:
            pass
        bot.reply_to(message, f"✅ Мастер {app[3]} одобрен!")
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
                f"❌ ВАША АНКЕТА ОТКЛОНЕНА\n\n"
                f"Причина: {reason}\n\n"
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

if __name__ == '__main__':
    print("=" * 50)
    print("✅ Бот запускается...")
    print(f"🤖 Токен: {TOKEN[:10]}...")
    print(f"💬 Чат: {CHAT_ID}")
    print(f"📢 Канал: {CHANNEL_LINK}")
    print(f"👑 Админ ID: {ADMIN_ID}")
    print("=" * 50)

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
