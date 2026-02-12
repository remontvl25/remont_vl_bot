import telebot
import sqlite3
import os
import time
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ================ НАСТРОЙКИ ================
# Токен берется из переменных окружения Railway
TOKEN = os.environ.get('TOKEN')
if not TOKEN:
    print("❌ ОШИБКА: Токен не найден в переменных окружения!")
    exit(1)

CHAT_ID = "@remontvl25chat"  # Чат для заявок
CHANNEL_LINK = "@remont_vl25"  # Канал с мастерами

# ID администратора для уведомлений - ЗАМЕНИТЕ НА ВАШ!
ADMIN_ID = 8111497942  # ⚠️ ВАЖНО: ВСТАВЬТЕ СВОЙ ID!

# Создаем бота
bot = telebot.TeleBot(TOKEN)

# ================ GOOGLE SHEETS ИНТЕГРАЦИЯ ================
def get_google_sheet():
    """Подключение к Google Sheets"""
    try:
        google_creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if not google_creds_json:
            print("⚠️ GOOGLE_CREDENTIALS не найдены в переменных окружения")
            return None
        
        creds_dict = json.loads(google_creds_json)
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        sheet_id = os.environ.get('GOOGLE_SHEET_ID')
        if not sheet_id:
            print("⚠️ GOOGLE_SHEET_ID не найден в переменных окружения")
            return None
        
        sheet = client.open_by_key(sheet_id).worksheet('Мастера')
        return sheet
    except Exception as e:
        print(f"❌ Ошибка подключения к Google Sheets: {e}")
        return None

def add_master_to_google_sheet(master_data):
    """Добавление мастера в Google Sheets"""
    try:
        sheet = get_google_sheet()
        if not sheet:
            return False
        
        row = [
            master_data.get('id', ''),              # A: ID
            master_data.get('date', ''),            # B: Дата
            master_data.get('name', ''),            # C: Имя
            master_data.get('service', ''),         # D: Специализация
            master_data.get('phone', ''),           # E: Телефон
            master_data.get('districts', ''),       # F: Районы/ЖК
            master_data.get('price_min', ''),       # G: Цена от
            master_data.get('price_max', ''),       # H: Цена до
            master_data.get('experience', ''),      # I: Опыт
            master_data.get('portfolio', ''),       # J: Портфолио
            master_data.get('documents', ''),       # K: Документы
            master_data.get('rating', '4.8'),       # L: Рейтинг
            master_data.get('reviews_count', '0'),  # M: Отзывов
            master_data.get('status', 'На проверке'), # N: Статус
            master_data.get('telegram_id', '')      # O: Telegram ID
        ]
        
        sheet.append_row(row)
        print(f"✅ Мастер {master_data.get('name')} добавлен в Google Sheets")
        return True
    except Exception as e:
        print(f"❌ Ошибка добавления в Google Sheets: {e}")
        return False

def update_master_status_in_google_sheet(telegram_id, status):
    """Обновление статуса мастера в Google Sheets"""
    try:
        sheet = get_google_sheet()
        if not sheet:
            return False
        
        all_records = sheet.get_all_records()
        for i, record in enumerate(all_records, start=2):
            if str(record.get('Telegram ID')) == str(telegram_id):
                sheet.update_cell(i, 14, status)
                print(f"✅ Статус мастера обновлён на '{status}' в Google Sheets")
                return True
        
        print(f"⚠️ Мастер с Telegram ID {telegram_id} не найден в таблице")
        return False
    except Exception as e:
        print(f"❌ Ошибка обновления статуса в Google Sheets: {e}")
        return False

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
                 rating INTEGER,
                 text TEXT,
                 created_at TEXT)''')

# Таблица мастеров (проверенные)
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

# Таблица анкет мастеров (заявки на добавление)
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

# Добавляем недостающие колонки
try:
    cursor.execute('ALTER TABLE requests ADD COLUMN description TEXT')
except:
    pass

try:
    cursor.execute('ALTER TABLE requests ADD COLUMN date TEXT')
except:
    pass

# ================ ФУНКЦИЯ СБРОСА ВЕБХУКА ================
def reset_webhook():
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        response = requests.get(url)
        if response.status_code == 200:
            print("✅ Webhook сброшен")
        else:
            print(f"⚠️ Ошибка сброса webhook: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Не удалось сбросить webhook: {e}")

def stop_other_instances():
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset=-1&timeout=0"
        requests.get(url)
        print("✅ Другие экземпляры остановлены")
    except Exception as e:
        print(f"⚠️ Не удалось остановить другие экземпляры: {e}")

# ================ КОМАНДА /start ================
@bot.message_handler(commands=['start'])
def start(message):
    # Проверяем, есть ли параметр
    if len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param == 'become_master':
            # Запускаем анкету сразу
            msg = bot.send_message(
                message.chat.id,
                "👷 **ЗАПОЛНЕНИЕ АНКЕТЫ МАСТЕРА**\n\n"
                "Шаг 1 из 10\n"
                "👇 **ВВЕДИТЕ ВАШЕ ИМЯ ИЛИ НАЗВАНИЕ БРИГАДЫ:**\n\n"
                "Пример: Иван Петров\n"
                "Или: Бригада «МастерОК»"
            )
            bot.register_next_step_handler(msg, process_master_name)
            return
    
    # Обычный start
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('🔨 Оставить заявку', '⭐ Оставить отзыв')
    markup.row('🔍 Найти мастера', '📞 Контакты')
    markup.row('📢 Канал с мастерами', '👷 Стать мастером')
    
    bot.send_message(
        message.chat.id,
        "👋 Добро пожаловать в бот заявок на ремонт!\n\n"
        "🔹 Хотите найти мастера? Нажмите «Оставить заявку»\n"
        "🔹 Хотите поблагодарить мастера? Нажмите «Оставить отзыв»\n"
        "🔹 Хотите добавить свою анкету? Нажмите «Стать мастером»\n\n"
        f"💬 Чат-заявок: {CHAT_ID}\n"
        f"📢 Канал с мастерами: {CHANNEL_LINK}",
        reply_markup=markup
    )

# ================ КНОПКА "КАНАЛ С МАСТЕРАМИ" ================
@bot.message_handler(func=lambda message: message.text == '📢 Канал с мастерами')
def channel_link(message):
    markup = telebot.types.InlineKeyboardMarkup()
    button = telebot.types.InlineKeyboardButton(
        text="📢 Перейти в канал", 
        url="https://t.me/remont_vl25"
    )
    markup.add(button)
    
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

# ================ ЗАЯВКА ================
@bot.message_handler(commands=['request'])
@bot.message_handler(func=lambda message: message.text == '🔨 Оставить заявку')
def request_service(message):
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
        "👉 Пример: 1  или  сантехник"
    )
    bot.register_next_step_handler(msg, process_service)

def process_service(message):
    service_input = message.text.strip().lower()
    
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
        service = service_input.capitalize()
    
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
    description = message.text
    msg = bot.send_message(
        message.chat.id,
        "📍 **Шаг 3 из 5**\n\n"
        "👇 **ВВЕДИТЕ РАЙОН ИЛИ ЖК:**\n"
        "Например: Патрокл, Снеговая Падь, Варяг, Океан"
    )
    bot.register_next_step_handler(msg, process_district, service, description)

def process_district(message, service, description):
    district = message.text
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
    date = message.text
    msg = bot.send_message(
        message.chat.id,
        "💰 **Шаг 5 из 5**\n\n"
        "👇 **ВВЕДИТЕ БЮДЖЕТ:**\n"
        "Например: до 3000₽, договорной, 50000₽ за квартиру"
    )
    bot.register_next_step_handler(msg, process_budget, service, description, district, date)

def process_budget(message, service, description, district, date):
    budget = message.text
    
    cursor.execute('''INSERT INTO requests 
                    (user_id, username, service, description, district, date, budget, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (message.from_user.id,
                     message.from_user.username or message.from_user.first_name,
                     service, description, district, date, budget,
                     'активна',
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    
    username = message.from_user.username or message.from_user.first_name
    request_text = f"""
🆕 **НОВАЯ ЗАЯВКА!**

👤 **От:** @{username}
🔨 **Услуга:** {service}
📝 **Задача:** {description}
📍 **Район/ЖК:** {district}
📅 **Когда:** {date}
💰 **Бюджет:** {budget}
⏰ **Создано:** {datetime.now().strftime("%H:%M %d.%m.%Y")}

👇 **Мастера, откликайтесь в комментариях!**
    """
    
    bot.send_message(CHAT_ID, request_text)
    
    bot.send_message(
        message.chat.id,
        f"✅ **ЗАЯВКА ОПУБЛИКОВАНА!**\n\n"
        f"💬 Чат с мастерами: {CHAT_ID}\n"
        f"⏱ Ожидайте откликов в течение 5-10 минут.\n\n"
        f"📌 Если никто не ответил за 30 минут — создайте новую заявку."
    )

# ================ ОТЗЫВ ================
@bot.message_handler(commands=['review'])
@bot.message_handler(func=lambda message: message.text == '⭐ Оставить отзыв')
def add_review(message):
    msg = bot.send_message(
        message.chat.id,
        "⭐ **ОСТАВИТЬ ОТЗЫВ**\n\n"
        "Напишите **ИМЯ МАСТЕРА** или **НАЗВАНИЕ БРИГАДЫ**:"
    )
    bot.register_next_step_handler(msg, process_review_master)

def process_review_master(message):
    master = message.text
    msg = bot.send_message(
        message.chat.id,
        "📝 **НАПИШИТЕ ТЕКСТ ОТЗЫВА:**\n"
        "Например: Сделал быстро, качественно, цена адекватная"
    )
    bot.register_next_step_handler(msg, process_review_text, master)

def process_review_text(message, master):
    review_text = message.text
    
    markup = telebot.types.InlineKeyboardMarkup(row_width=5)
    buttons = [
        telebot.types.InlineKeyboardButton("⭐", callback_data=f"rating_1_{master}"),
        telebot.types.InlineKeyboardButton("⭐⭐", callback_data=f"rating_2_{master}"),
        telebot.types.InlineKeyboardButton("⭐⭐⭐", callback_data=f"rating_3_{master}"),
        telebot.types.InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"rating_4_{master}"),
        telebot.types.InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"rating_5_{master}")
    ]
    markup.add(*buttons)
    
    bot.send_message(
        message.chat.id,
        f"👤 **Мастер:** {master}\n"
        f"📝 **Отзыв:** {review_text}\n\n"
        "⭐ **ОЦЕНИТЕ РАБОТУ ОТ 1 ДО 5:**",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('rating_'))
def rating_callback(call):
    data = call.data.split('_')
    rating = data[1]
    master = '_'.join(data[2:])
    
    cursor.execute('''INSERT INTO reviews
                    (master_name, user_name, rating, created_at)
                    VALUES (?, ?, ?, ?)''',
                    (master.replace('_', ' '),
                     call.from_user.username or call.from_user.first_name,
                     int(rating),
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    
    bot.answer_callback_query(call.id, f"Вы поставили оценку {rating} ⭐")
    
    bot.edit_message_text(
        f"✅ **СПАСИБО ЗА ОТЗЫВ!**\n\n"
        f"👤 **Мастер:** {master.replace('_', ' ')}\n"
        f"⭐ **Оценка:** {'⭐' * int(rating)}\n\n"
        f"Ваш отзыв поможет другим соседям!",
        call.message.chat.id,
        call.message.message_id
    )

# ================ ПОИСК МАСТЕРОВ ================
@bot.message_handler(commands=['search'])
@bot.message_handler(func=lambda message: message.text == '🔍 Найти мастера')
def search_master(message):
    cursor.execute("SELECT service, COUNT(*), AVG(rating) FROM masters GROUP BY service")
    masters_stats = cursor.fetchall()
    
    if masters_stats:
        text = "🔍 **МАСТЕРА В БАЗЕ:**\n\n"
        for stat in masters_stats:
            text += f"• {stat[0]}: {stat[1]} мастеров ⭐{stat[2]:.1f}\n"
    else:
        text = "🔍 **МАСТЕРА В БАЗЕ:**\n\n"
        text += "• Электрики: 5 мастеров ⭐4.8\n"
        text += "• Сантехники: 4 мастера ⭐4.9\n"
        text += "• Отделочники: 3 мастера ⭐4.7\n"
        text += "• Строители: 2 мастера ⭐4.6\n\n"
    
    text += f"👉 **Хотите найти мастера?**\n"
    text += f"Зайдите в чат и оставьте заявку:\n"
    text += f"{CHAT_ID}"
    
    markup = telebot.types.InlineKeyboardMarkup()
    btn_channel = telebot.types.InlineKeyboardButton(
        text="📢 Подписаться на канал", 
        url="https://t.me/remont_vl25"
    )
    markup.add(btn_channel)
    
    bot.send_message(
        message.chat.id,
        text,
        reply_markup=markup
    )

# ================ КОНТАКТЫ ================
@bot.message_handler(commands=['contacts'])
@bot.message_handler(func=lambda message: message.text == '📞 Контакты')
def contacts(message):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    
    btn_channel = telebot.types.InlineKeyboardButton(
        text="📢 Канал с мастерами", 
        url="https://t.me/remont_vl25"
    )
    btn_chat = telebot.types.InlineKeyboardButton(
        text="💬 Чат-заявок", 
        url="https://t.me/remontvl25chat"
    )
    btn_admin = telebot.types.InlineKeyboardButton(
        text="👨‍💻 Администратор", 
        url="https://t.me/remont_vl25"
    )
    
    markup.add(btn_channel, btn_chat, btn_admin)
    
    bot.send_message(
        message.chat.id,
        f"📞 **КОНТАКТЫ**\n\n"
        f"📢 Канал с мастерами: {CHANNEL_LINK}\n"
        f"💬 Чат-заявок: {CHAT_ID}\n"
        f"🤖 Этот бот: @remont_vl25_chat_bot\n"
        f"👨‍💻 Администратор: @remont_vl25\n\n"
        f"📌 По вопросам сотрудничества и рекламы — пишите админу!",
        reply_markup=markup
    )

# ================ ПОМОЩЬ ================
@bot.message_handler(commands=['help'])
def help_command(message):
    bot.send_message(
        message.chat.id,
        "❓ **ПОМОЩЬ**\n\n"
        "**Доступные команды:**\n"
        "/start - Запустить бота\n"
        "/request - Оставить заявку\n"
        "/review - Оставить отзыв\n"
        "/search - Поиск мастеров\n"
        "/become_master - Стать мастером\n"
        "/my_status - Статус анкеты\n"
        "/contacts - Контакты\n"
        "/help - Это сообщение\n\n"
        "**Как найти мастера?**\n"
        "1. Нажмите «Оставить заявку»\n"
        "2. Выберите услугу\n"
        "3. Опишите задачу\n"
        "4. Укажите район и дату\n"
        "5. Введите бюджет\n"
        "6. Ждите откликов в чате"
    )

# ================ АНКЕТА МАСТЕРА ================
@bot.message_handler(commands=['become_master'])
@bot.message_handler(func=lambda message: message.text == '👷 Стать мастером')
def become_master(message):
    # Проверяем, где вызвана команда
    if message.chat.type != 'private':
        # Это групповой чат
        bot.reply_to(
            message,
            "👷 **Заполнение анкеты происходит в личных сообщениях с ботом!**\n\n"
            "👇 **Напишите мне в ЛС:**\n"
            f"@{bot.get_me().username}\n\n"
            "Или нажмите кнопку ниже 👇",
            reply_markup=telebot.types.InlineKeyboardMarkup().add(
                telebot.types.InlineKeyboardButton(
                    text="👷 Заполнить анкету",
                    url=f"https://t.me/{bot.get_me().username}?start=become_master"
                )
            )
        )
        return
    
    # Если это личка - начинаем анкету
    msg = bot.send_message(
        message.chat.id,
        "👷 **ЗАПОЛНЕНИЕ АНКЕТЫ МАСТЕРА**\n\n"
        "Шаг 1 из 10\n"
        "👇 **ВВЕДИТЕ ВАШЕ ИМЯ ИЛИ НАЗВАНИЕ БРИГАДЫ:**\n\n"
        "Пример: Иван Петров\n"
        "Или: Бригада «МастерОК»"
    )
    bot.register_next_step_handler(msg, process_master_name)

def process_master_name(message):
    # Проверка на личные сообщения
    if message.chat.type != 'private':
        bot.reply_to(message, "❌ Заполняйте анкету в ЛС с ботом: @remont_vl25_chat_bot")
        return
    
    name = message.text
    msg = bot.send_message(
        message.chat.id,
        "👷 **Шаг 2 из 10**\n\n"
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
    bot.register_next_step_handler(msg, process_master_service, name)

def process_master_service(message, name):
    service_input = message.text.strip().lower()
    
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
        service = service_input.capitalize()
    
    msg = bot.send_message(
        message.chat.id,
        "📞 **Шаг 3 из 10**\n\n"
        "👇 **ВВЕДИТЕ ВАШ ТЕЛЕФОН:**\n\n"
        "Пример: +7 924 123-45-67\n\n"
        "⚠️ Номер будет виден ТОЛЬКО администратору"
    )
    bot.register_next_step_handler(msg, process_master_phone, name, service)

def process_master_phone(message, name, service):
    phone = message.text
    msg = bot.send_message(
        message.chat.id,
        "📍 **Шаг 4 из 10**\n\n"
        "👇 **В КАКИХ РАЙОНАХ/ЖК ВЫ РАБОТАЕТЕ?**\n\n"
        "Перечислите через запятую:\n"
        "Пример: Патрокл, Снеговая Падь, Варяг, Океан"
    )
    bot.register_next_step_handler(msg, process_master_districts, name, service, phone)

def process_master_districts(message, name, service, phone):
    districts = message.text
    msg = bot.send_message(
        message.chat.id,
        "💰 **Шаг 5 из 10**\n\n"
        "👇 **МИНИМАЛЬНАЯ ЦЕНА ЗАКАЗА:**\n\n"
        "Пример: 1000₽, 5000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_min, name, service, phone, districts)

def process_master_price_min(message, name, service, phone, districts):
    price_min = message.text
    msg = bot.send_message(
        message.chat.id,
        "💰 **Шаг 6 из 10**\n\n"
        "👇 **МАКСИМАЛЬНАЯ ЦЕНА ЗАКАЗА:**\n\n"
        "Пример: 50000₽, 100000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_max, name, service, phone, districts, price_min)

def process_master_price_max(message, name, service, phone, districts, price_min):
    price_max = message.text
    msg = bot.send_message(
        message.chat.id,
        "⏱️ **Шаг 7 из 10**\n\n"
        "👇 **ВАШ ОПЫТ РАБОТЫ:**\n\n"
        "Пример: 3 года, 5 лет, 10+ лет"
    )
    bot.register_next_step_handler(msg, process_master_experience, name, service, phone, districts, price_min, price_max)

def process_master_experience(message, name, service, phone, districts, price_min, price_max):
    experience = message.text
    msg = bot.send_message(
        message.chat.id,
        "📸 **Шаг 8 из 10**\n\n"
        "👇 **ОТПРАВЬТЕ ССЫЛКУ НА ПОРТФОЛИО:**\n\n"
        "Это может быть:\n"
        "• Ссылка на Яндекс.Диск с фото\n"
        "• Ссылка на Google Фото\n"
        "• Telegram-канал с работами\n\n"
        "Или просто нажмите 'Пропустить'"
    )
    bot.register_next_step_handler(msg, process_master_portfolio, name, service, phone, districts, price_min, price_max, experience)

def process_master_portfolio(message, name, service, phone, districts, price_min, price_max, experience):
    portfolio = message.text
    if portfolio.lower() == "пропустить":
        portfolio = "Не указано"
    
    msg = bot.send_message(
        message.chat.id,
        "📄 **Шаг 9 из 10**\n\n"
        "👇 **ПОДТВЕРЖДАЮЩИЕ ДОКУМЕНТЫ:**\n\n"
        "Есть ли у вас:\n"
        "• Самозанятость/ИП\n"
        "• Паспорт (личная встреча)\n"
        "• Договор подряда\n\n"
        "Напишите: Есть / Нет / Пропустить"
    )
    bot.register_next_step_handler(msg, process_master_documents, name, service, phone, districts, price_min, price_max, experience, portfolio)

def process_master_documents(message, name, service, phone, districts, price_min, price_max, experience, portfolio):
    documents = message.text
    
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
    
    # ========== ОТПРАВКА В GOOGLE ТАБЛИЦУ ==========
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
    # ==============================================
    
    admin_message = f"""
🆕 **НОВАЯ АНКЕТА МАСТЕРА!** (ID: {application_id})

👤 **Имя:** {name}
🔨 **Специализация:** {service}
📞 **Телефон:** {phone}
📍 **Районы:** {districts}
💰 **Цены:** {price_min} - {price_max}
⏱️ **Опыт:** {experience}
📸 **Портфолио:** {portfolio}
📄 **Документы:** {documents}

👤 **Telegram:** @{message.from_user.username or "нет"}
🆔 **ID:** {message.from_user.id}

**Статус:** ⏳ На проверке
📊 **Google Таблица:** обновлена

✅ Одобрить: /approve {application_id}
❌ Отклонить: /reject {application_id} [причина]
    """
    
    try:
        bot.send_message(ADMIN_ID, admin_message)
    except Exception as e:
        print(f"⚠️ Не удалось отправить уведомление админу: {e}")
    
    bot.send_message(
        message.chat.id,
        "✅ **ВАША АНКЕТА ОТПРАВЛЕНА!**\n\n"
        "Спасибо за доверие!\n\n"
        "📌 **Что дальше?**\n"
        "1. Администратор проверит анкету (обычно 1-2 дня)\n"
        "2. Мы можем запросить фото работ или отзывы\n"
        "3. После проверки ваша карточка появится в канале\n\n"
        f"📊 Данные также сохранены в Google Таблице\n\n"
        "Статус проверки можно узнать по команде /my_status"
    )

# ================ ПРОВЕРКА СТАТУСА АНКЕТЫ ================
@bot.message_handler(commands=['my_status'])
def my_status(message):
    cursor.execute('''SELECT status, created_at FROM master_applications 
                    WHERE user_id = ? ORDER BY id DESC LIMIT 1''',
                    (message.from_user.id,))
    result = cursor.fetchone()
    
    if result:
        status = result[0]
        date = result[1]
        
        if status == "На проверке":
            text = "⏳ **Статус: На проверке**\n\nВаша анкета ещё проверяется администратором. Обычно это занимает 1-2 дня."
        elif status == "Одобрена":
            text = "✅ **Статус: Одобрена!**\n\nПоздравляем! Ваша карточка скоро появится в канале."
        elif status == "Отклонена":
            text = "❌ **Статус: Отклонена**\n\nК сожалению, ваша анкета не прошла проверку. Свяжитесь с администратором для уточнения причин."
        else:
            text = f"📌 **Статус: {status}**"
    else:
        text = "❌ **У вас нет активных анкет**\n\nЧтобы подать заявку, нажмите «👷 Стать мастером»"
    
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
        application = cursor.fetchone()
        
        if not application:
            bot.reply_to(message, f"❌ Анкета с ID {application_id} не найдена.")
            return
        
        # Обновляем статус анкеты
        cursor.execute('''UPDATE master_applications 
                        SET status = 'Одобрена' 
                        WHERE id = ?''', (application_id,))
        
        # Добавляем мастера в таблицу проверенных
        cursor.execute('''INSERT INTO masters
                        (name, service, phone, districts, price_min, price_max, 
                         experience, portfolio, rating, reviews_count, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (application[3], application[4], application[5], application[6],
                         application[7], application[8], application[9], application[10],
                         4.8, 0, 'активен',
                         datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()
        
        # Обновление статуса в Google Таблице
        update_master_status_in_google_sheet(application[1], 'Одобрена')
        
        # Уведомление мастеру
        try:
            bot.send_message(
                application[1],
                "✅ **ВАША АНКЕТА ОДОБРЕНА!**\n\n"
                "Поздравляем! Теперь вы в базе проверенных мастеров.\n"
                f"Ваша карточка будет опубликована в канале {CHANNEL_LINK}\n\n"
                f"📊 Статус обновлен в Google Таблице\n\n"
                "📌 **Что дальше?**\n"
                "1. Мы подготовим вашу карточку\n"
                "2. Вы получите заявки из чата\n"
                "3. Клиенты смогут оставлять отзывы"
            )
        except:
            pass
        
        bot.reply_to(message, f"✅ Мастер {application[3]} одобрен! Статус обновлен в Google Таблице.")
        
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
        application = cursor.fetchone()
        
        if not application:
            bot.reply_to(message, f"❌ Анкета с ID {application_id} не найдена.")
            return
        
        # Обновляем статус анкеты
        cursor.execute('''UPDATE master_applications 
                        SET status = 'Отклонена' 
                        WHERE id = ?''', (application_id,))
        conn.commit()
        
        # Обновление статуса в Google Таблице
        update_master_status_in_google_sheet(application[1], 'Отклонена')
        
        # Уведомление мастеру
        try:
            bot.send_message(
                application[1],
                f"❌ **ВАША АНКЕТА ОТКЛОНЕНА**\n\n"
                f"**Причина:** {reason}\n\n"
                f"Свяжитесь с администратором: @remont_vl25\n\n"
                f"📊 Статус обновлен в Google Таблице\n\n"
                f"Вы можете подать заявку снова после исправления замечаний."
            )
        except:
            pass
        
        bot.reply_to(message, f"❌ Мастер {application[3]} отклонён. Причина: {reason}. Статус обновлен в Google Таблице.")
        
    except ValueError:
        bot.reply_to(message, "❌ ID анкеты должен быть числом.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ================ ТЕСТОВАЯ КОМАНДА ДЛЯ ПРОВЕРКИ GOOGLE SHEETS ================
@bot.message_handler(commands=['test_sheet'])
def test_sheet(message):
    if message.from_user.id == ADMIN_ID:
        sheet = get_google_sheet()
        if sheet:
            bot.reply_to(message, "✅ Подключение к Google Sheets работает! Таблица найдена.")
        else:
            bot.reply_to(message, "❌ Ошибка подключения к Google Sheets. Проверьте переменные GOOGLE_CREDENTIALS и GOOGLE_SHEET_ID")

# ================ ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ================
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    if message.text.startswith('/'):
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
    print(f"🤖 Токен: {TOKEN[:10]}... (скрыт)")
    print(f"💬 Чат: {CHAT_ID}")
    print(f"📢 Канал: {CHANNEL_LINK}")
    print(f"👑 Админ ID: {ADMIN_ID}")
    print(f"📊 Google Sheets: {'Подключен' if get_google_sheet() else 'Не подключен'}")
    print("=" * 60)
    
    reset_webhook()
    stop_other_instances()
    time.sleep(2)
    
    print("⏳ Бот работает 24/7...")
    print("=" * 60)
    
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            if "409" in str(e):
                print("🔄 Обнаружен конфликт! Принудительный сброс...")
                reset_webhook()
                stop_other_instances()
            print("🔄 Перезапуск через 5 секунд...")
            time.sleep(5)
            continue

