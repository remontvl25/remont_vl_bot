import os
import sys
import json
import time
import sqlite3
import requests
import fcntl
import re
from datetime import datetime, timedelta

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

# Основные идентификаторы
BOT_USERNAME = os.environ.get('BOT_USERNAME', 'masterVL25_bot')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', 'masterVL25')
CHANNEL_ID = os.environ.get('CHANNEL_ID', '-1003711282924')  # числовой ID канала
CHAT_ID = os.environ.get('CHAT_ID', "@remontvl25chat")          # общий чат
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
MASTER_CHAT_ID = os.environ.get('MASTER_CHAT_ID', '@remontvl25masters')
MASTER_CHAT_INVITE_LINK = os.environ.get('MASTER_CHAT_INVITE_LINK', '')

# Google Forms
GOOGLE_FORMS_BASE = os.environ.get('GOOGLE_FORMS_BASE', '')
FORM_ENTRY_TG_ID = os.environ.get('FORM_ENTRY_TG_ID', '')
FORM_ENTRY_TG_USERNAME = os.environ.get('FORM_ENTRY_TG_USERNAME', '')

# Путь к базе данных (подготовка к Volume)
DB_PATH = os.environ.get('DB_PATH', 'remont.db')

# Ночной режим (Владивосток, UTC+10)
NIGHT_START_HOUR = int(os.environ.get('NIGHT_START_HOUR', 23))
NIGHT_END_HOUR = int(os.environ.get('NIGHT_END_HOUR', 7))
TIMEZONE_OFFSET = int(os.environ.get('TIMEZONE_OFFSET', 10))

# Ссылки для удобства
BOT_LINK = f"https://t.me/{BOT_USERNAME}"
CHANNEL_LINK = f"https://t.me/{CHANNEL_USERNAME}"

bot = telebot.TeleBot(TOKEN)

# ================ БАЗА ДАННЫХ ================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# ----- Таблица пользователей (роли) -----
cursor.execute('''CREATE TABLE IF NOT EXISTS users
                (user_id INTEGER PRIMARY KEY,
                 role TEXT DEFAULT 'client',
                 first_seen TEXT,
                 last_active TEXT)''')

# ----- Таблица заявок -----
cursor.execute('''CREATE TABLE IF NOT EXISTS requests
                (id INTEGER PRIMARY KEY,
                 user_id INTEGER,
                 username TEXT,
                 service TEXT,
                 description TEXT,
                 district TEXT,
                 date TEXT,
                 budget TEXT,
                 status TEXT DEFAULT 'активна',
                 is_public INTEGER DEFAULT 0,
                 chosen_master_id INTEGER DEFAULT NULL,
                 delayed INTEGER DEFAULT 0,   -- 1 если заявка создана ночью и ждёт публикации
                 chat_message_id INTEGER,
                 created_at TEXT)''')

# ----- Таблица отзывов -----
cursor.execute('''CREATE TABLE IF NOT EXISTS reviews
                (id INTEGER PRIMARY KEY,
                 master_id INTEGER,
                 master_name TEXT,
                 user_id INTEGER,
                 user_name TEXT,
                 anonymous INTEGER DEFAULT 0,
                 review_text TEXT,
                 rating INTEGER,
                 media_file_id TEXT,
                 status TEXT DEFAULT 'pending',
                 created_at TEXT)''')

# ----- Таблица мастеров (одна запись – одна услуга) -----
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
                 verification_type TEXT DEFAULT 'simple',
                 documents_verified INTEGER DEFAULT 0,
                 photos_verified INTEGER DEFAULT 0,
                 reviews_verified INTEGER DEFAULT 0,
                 preferred_contact TEXT DEFAULT 'telegram',
                 documents_list TEXT DEFAULT '',
                 payment_methods TEXT DEFAULT '',
                 age_group TEXT DEFAULT '',
                 channel_message_id INTEGER,
                 source TEXT DEFAULT 'bot',
                 created_at TEXT)''')

# ----- Таблица анкет мастеров (на проверку) -----
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
                 verification_type TEXT DEFAULT 'simple',
                 documents_list TEXT DEFAULT '',
                 payment_methods TEXT DEFAULT '',
                 preferred_contact TEXT DEFAULT 'telegram',
                 age_group TEXT DEFAULT '',
                 source TEXT DEFAULT 'bot',
                 status TEXT,
                 created_at TEXT)''')

# ----- Таблица рекомендаций (расширенная, через /recommend) -----
cursor.execute('''CREATE TABLE IF NOT EXISTS recommendations
                (id INTEGER PRIMARY KEY,
                 user_id INTEGER,
                 username TEXT,
                 master_name TEXT,
                 service TEXT,
                 contact TEXT,
                 description TEXT,
                 price_level TEXT,
                 satisfaction TEXT,
                 recommend TEXT,
                 media_file_id TEXT,
                 status TEXT DEFAULT 'на модерации',
                 created_at TEXT)''')

# ----- Таблица клиентских рекомендаций (из чата через хештеги) -----
cursor.execute('''CREATE TABLE IF NOT EXISTS client_recommendations
                (id INTEGER PRIMARY KEY,
                 user_id INTEGER,
                 username TEXT,
                 message_id INTEGER,
                 hashtag TEXT,
                 contact TEXT,
                 description TEXT,
                 media_file_id TEXT,
                 status TEXT DEFAULT 'new',
                 created_at TEXT)''')

# ----- Таблица лайков для клиентских рекомендаций -----
cursor.execute('''CREATE TABLE IF NOT EXISTS rec_likes
                (id INTEGER PRIMARY KEY,
                 rec_id INTEGER,
                 user_id INTEGER,
                 created_at TEXT,
                 UNIQUE(rec_id, user_id))''')

# ----- Таблица комментариев для клиентских рекомендаций -----
cursor.execute('''CREATE TABLE IF NOT EXISTS rec_comments
                (id INTEGER PRIMARY KEY,
                 rec_id INTEGER,
                 user_id INTEGER,
                 username TEXT,
                 comment TEXT,
                 created_at TEXT)''')

# ----- Таблица откликов мастеров на заявки -----
cursor.execute('''CREATE TABLE IF NOT EXISTS responses
                (id INTEGER PRIMARY KEY,
                 request_id INTEGER,
                 master_id INTEGER,
                 price TEXT,
                 comment TEXT,
                 status TEXT DEFAULT 'pending',
                 created_at TEXT)''')

# ----- Таблица запросов на подробности об отзыве -----
cursor.execute('''CREATE TABLE IF NOT EXISTS review_questions
                (id INTEGER PRIMARY KEY,
                 review_id INTEGER,
                 from_user_id INTEGER,
                 from_username TEXT,
                 question TEXT,
                 answered INTEGER DEFAULT 0,
                 created_at TEXT)''')

# ----- Таблица для хранения жалоб на отзывы -----
cursor.execute('''CREATE TABLE IF NOT EXISTS review_complaints
                (id INTEGER PRIMARY KEY,
                 review_id INTEGER,
                 master_id INTEGER,
                 complaint_text TEXT,
                 status TEXT DEFAULT 'new',
                 created_at TEXT)''')

conn.commit()

# ================ ФУНКЦИИ GOOGLE SHEETS (опционально) ================
def get_google_sheet():
    if not GOOGLE_SHEETS_AVAILABLE:
        return None
    try:
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        sheet_id = os.environ.get('GOOGLE_SHEET_ID')
        if not creds_json or not sheet_id:
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
        return worksheet
    except Exception as e:
        print(f"❌ Ошибка Google Sheets: {e}")
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
            str(master_data.get('bio', 'Не указано')),
            str(master_data.get('portfolio', 'Не указано')),
            str(master_data.get('documents', 'Не указано')),
            str(master_data.get('rating', '4.8')),
            str(master_data.get('reviews_count', '0')),
            str(master_data.get('status', 'На проверке')),
            str(master_data.get('telegram_id', '')),
            str(master_data.get('entity_type', 'individual')),
            str(master_data.get('verification_type', 'simple')),
            str(master_data.get('source', 'bot'))
        ]
        sheet.append_row(row)
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
                sheet.update_cell(i, 15, status)
                return True
    except Exception as e:
        print(f"❌ Ошибка обновления статуса: {e}")
    return False

# ================ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ================
def safe_text(message):
    return message.text.strip() if message and message.text else ""

def only_private(message):
    if message.chat.type != 'private':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "🤖 Перейти в бота",
            url=BOT_LINK
        ))
        bot.reply_to(
            message,
            "❌ Эта команда работает только в личных сообщениях с ботом.\n\n"
            f"👉 Напишите мне в ЛС: @{BOT_USERNAME}",
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

def check_bot_admin_in_chat(chat_id):
    try:
        admins = bot.get_chat_administrators(chat_id)
        bot_id = bot.get_me().id
        for admin in admins:
            if admin.user.id == bot_id:
                print(f"✅ Бот администратор в чате {chat_id}")
                return True
        print(f"❌ Бот НЕ администратор в чате {chat_id}")
        return False
    except Exception as e:
        print(f"⚠️ Не удалось проверить права в чате {chat_id}: {e}")
        return False

def is_night_time():
    """Проверяет, сейчас ночное время по Владивостоку."""
    now_utc = datetime.utcnow()
    local_time = now_utc + timedelta(hours=TIMEZONE_OFFSET)
    hour = local_time.hour
    if NIGHT_START_HOUR > NIGHT_END_HOUR:
        return hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR
    else:
        return NIGHT_START_HOUR <= hour < NIGHT_END_HOUR

def publish_delayed_requests():
    """Публикует отложенные заявки (если сейчас не ночь)."""
    if is_night_time():
        return
    cursor.execute("SELECT id, service, description, district, date, budget FROM requests WHERE delayed = 1 AND status = 'активна'")
    delayed = cursor.fetchall()
    for req in delayed:
        req_id, service, desc, district, date, budget = req
        client_alias = f"Клиент #{req_id % 10000}"
        text = f"""
🆕 **НОВАЯ ЗАЯВКА!**

👤 **От:** {client_alias}
🔨 **Услуга:** {service}
📝 **Задача:** {desc}
📍 **Район/ЖК:** {district}
📅 **Когда:** {date}
💰 **Бюджет:** {budget}
📢 Публичная заявка. Мастера, откликайтесь в боте!
        """
        try:
            bot.send_message(CHANNEL_ID, text)
            cursor.execute("UPDATE requests SET delayed = 0 WHERE id = ?", (req_id,))
            conn.commit()
        except Exception as e:
            print(f"Ошибка публикации отложенной заявки {req_id}: {e}")

# ================ УДАЛЕНИЕ КОМАНД В ЧАТЕ ================
@bot.message_handler(func=lambda message: message.chat.type != 'private')
def delete_group_commands(message):
    if message.text and (message.text.startswith('/') or f'@{BOT_USERNAME}' in message.text):
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass

# ================ МЕНЮ ПО РОЛИ ================
def show_role_menu(message, role):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if role == 'client':
        markup.row('🔨 Оставить заявку', '🔍 Найти мастера')
        markup.row('⭐ Оставить отзыв', '👍 Рекомендовать мастера')
        markup.row('📢 Канал с мастерами', '📋 Мои заявки')
        text = "👋 **Режим: Клиент**\n\n• Ищете мастера? Оставьте заявку или выберите из каталога.\n• Понравился мастер? Оставьте отзыв.\n• Знаете хорошего специалиста? Порекомендуйте его!"
    elif role == 'master':
        markup.row('👷 Заполнить анкету', '📋 Анкета (Google Forms)')
        markup.row('📢 Канал с мастерами', '📋 Активные заявки')
        text = "👋 **Режим: Мастер**\n\n✅ Заполните анкету – после одобрения вы попадёте в базу и в закрытый чат мастеров.\n🔹 Получайте уведомления о новых заявках по вашей специализации."
    elif role == 'guest':
        markup.row('🔍 Найти мастера', '📢 Канал с мастерами')
        markup.row('👷 Зарегистрироваться как мастер')
        text = "👋 **Режим: Гость**\n\n• Вы можете просматривать заявки в канале и искать мастеров.\n• Чтобы участвовать активнее, зарегистрируйтесь как клиент или мастер."
    else:
        markup.row('🔨 Оставить заявку', '🔍 Найти мастера')
        markup.row('📢 Канал с мастерами')
        text = "👋 Добро пожаловать!"
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='Markdown')

# ================ ВЫБОР РОЛИ ПРИ ПЕРВОМ ЗАПУСКЕ ================
@bot.message_handler(commands=['start'])
def start(message):
    if message.chat.type != 'private':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "🤖 Перейти в бота",
            url=BOT_LINK
        ))
        bot.reply_to(
            message,
            "👋 Добро пожаловать в бот заявок на ремонт!\n\n"
            "📌 В этом чате я только публикую заявки и отзывы.\n\n"
            "👇 Вся работа со мной — в личных сообщениях:\n"
            f"👉 @{BOT_USERNAME}\n\n"
            "Там вы можете:\n"
            "✅ Оставить заявку\n"
            "✅ Найти мастера в каталоге\n"
            "✅ Стать мастером и добавить анкету\n"
            "✅ Оставить отзыв или рекомендацию\n"
            "✅ Проверить статус анкеты",
            reply_markup=markup
        )
        return

    user_id = message.from_user.id
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row:
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("🔨 Клиент", callback_data="role_client"),
            types.InlineKeyboardButton("👷 Мастер", callback_data="role_master"),
            types.InlineKeyboardButton("👀 Гость", callback_data="role_guest")
        )
        bot.send_message(
            message.chat.id,
            "👋 **Добро пожаловать!**\n\nКто вы? Выберите роль, чтобы мы могли предложить нужный функционал.\n\n"
            "• Клиент – ищете мастеров, оставляете заявки и отзывы.\n"
            "• Мастер – хотите получать заказы.\n"
            "• Гость – просто посмотреть, без регистрации.",
            reply_markup=markup
        )
    else:
        role = row[0]
        show_role_menu(message, role)

@bot.callback_query_handler(func=lambda call: call.data.startswith('role_'))
def role_callback(call):
    role = call.data.split('_')[1]
    user_id = call.from_user.id
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    if role == 'client':
        cursor.execute('INSERT OR REPLACE INTO users (user_id, role, first_seen, last_active) VALUES (?, ?, ?, ?)',
                       (user_id, 'client', now, now))
        conn.commit()
        bot.edit_message_text("✅ Роль сохранена: **Клиент**.", 
                              call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        show_role_menu(call.message, 'client')
        bot.answer_callback_query(call.id)
        return
    if role == 'master':
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("✅ Полная регистрация (с проверкой)", callback_data="master_full"),
            types.InlineKeyboardButton("🔹 Упрощённое размещение", callback_data="master_simple")
        )
        bot.edit_message_text(
            "👷 **Регистрация мастера**\n\n"
            "Выберите, как вы хотите участвовать:\n\n"
            "✅ **Полная регистрация** – заполните анкету с документами. После проверки администратором вы попадёте в базу и закрытый чат мастеров.\n"
            "🔹 **Упрощённое размещение** – вы сразу попадаете в базу без проверки документов, но не будете получать уведомления о заявках. В любой момент можно пройти полную регистрацию.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        bot.answer_callback_query(call.id)
    if role == 'guest':
        cursor.execute('INSERT OR REPLACE INTO users (user_id, role, first_seen, last_active) VALUES (?, ?, ?, ?)',
                       (user_id, 'guest', now, now))
        conn.commit()
        bot.edit_message_text("✅ Роль сохранена: **Гость**.", 
                              call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        show_role_menu(call.message, 'guest')
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data in ['master_full', 'master_simple'])
def master_registration_choice(call):
    verif_type = 'full' if call.data == 'master_full' else 'simple'
    user_id = call.from_user.id
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('INSERT OR REPLACE INTO users (user_id, role, first_seen, last_active) VALUES (?, ?, ?, ?)',
                   (user_id, 'master', now, now))
    conn.commit()
    bot.edit_message_text("✅ Роль сохранена: **Мастер**. Теперь заполните анкету.",
                          call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    become_master(call.message, verif_type)
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: message.text == '👷 Зарегистрироваться как мастер')
def guest_register(message):
    if not only_private(message):
        return
    user_id = message.from_user.id
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('UPDATE users SET role = ?, last_active = ? WHERE user_id = ?', ('master', now, user_id))
    conn.commit()
    bot.send_message(message.chat.id, "✅ Теперь вы – мастер. Заполните анкету для получения заказов.")
    become_master(message, 'simple')

# ================ КНОПКА "КАНАЛ С МАСТЕРАМИ" ================
@bot.message_handler(func=lambda message: message.text == '📢 Канал с мастерами')
def channel_link(message):
    if not only_private(message):
        return
    bot.send_message(
        message.chat.id,
        f"📢 **Наш канал:** {CHANNEL_LINK}\n\n"
        "В канале публикуются анонсы новых заявок, мастеров и отзывов.\n"
        "Все подробности доступны в боте.",
        parse_mode='Markdown'
    )

# ================ КНОПКА "МОИ ЗАЯВКИ" ================
@bot.message_handler(func=lambda message: message.text == '📋 Мои заявки')
def my_requests_handler(message):
    if not only_private(message):
        return
    my_requests(message)

# ================ КНОПКА "АКТИВНЫЕ ЗАЯВКИ" ДЛЯ МАСТЕРА ================
@bot.message_handler(func=lambda message: message.text == '📋 Активные заявки')
def active_requests_handler(message):
    if not only_private(message):
        return
    active_requests(message)

# ================ ПЕРСОНАЛИЗИРОВАННАЯ ССЫЛКА НА GOOGLE FORMS ================
def generate_form_url(user_id, username):
    if not GOOGLE_FORMS_BASE or not FORM_ENTRY_TG_ID:
        return GOOGLE_FORMS_BASE
    params = {
        FORM_ENTRY_TG_ID: str(user_id),
        FORM_ENTRY_TG_USERNAME: username or ''
    }
    query = '&'.join([f"{k}={v}" for k, v in params.items()])
    return f"{GOOGLE_FORMS_BASE}?{query}"

@bot.message_handler(func=lambda message: message.text == '📋 Анкета (Google Forms)')
def forms_link(message):
    if not only_private(message):
        return
    if not GOOGLE_FORMS_BASE:
        bot.send_message(
            message.chat.id,
            "❌ Ссылка на анкету ещё не настроена.\n"
            "Пожалуйста, обратитесь к администратору."
        )
        return
    user_id = message.from_user.id
    username = message.from_user.username or ''
    url = generate_form_url(user_id, username)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📋 Перейти к анкете", url=url))
    bot.send_message(
        message.chat.id,
        "📋 **Анкета мастера в Google Forms**\n\n"
        "Ваш Telegram ID и username будут автоматически переданы в форму.\n"
        "После отправки администратор проверит данные.",
        reply_markup=markup
    )

# ================ АНКЕТА МАСТЕРА (расширенная) ================
if not hasattr(bot, 'master_data'):
    bot.master_data = {}

@bot.message_handler(commands=['become_master'])
def become_master(message, verif_type='simple'):
    if not only_private(message):
        return
    user_id = message.from_user.id
    if user_id not in bot.master_data:
        bot.master_data[user_id] = {}
    bot.master_data[user_id]['verification_type'] = verif_type
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👤 Частное лицо", callback_data="entity_individual"),
        types.InlineKeyboardButton("🏢 Компания / ИП", callback_data="entity_company")
    )
    bot.send_message(
        message.chat.id,
        "👷 **ЗАПОЛНЕНИЕ АНКЕТЫ МАСТЕРА**\n\n"
        "Если вы работаете по нескольким специальностям, после завершения этой анкеты вы сможете добавить ещё одну.\n\n"
        "Шаг 1 из 16\n"
        "👇 **ВЫБЕРИТЕ ТИП:**",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('entity_'))
def entity_callback(call):
    entity_type = call.data.split('_')[1]
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.master_data[user_id] = {}
    bot.master_data[user_id]['entity_type'] = entity_type

    if bot.master_data[user_id].get('entity_type') == 'individual':
        question = "👤 **ВВЕДИТЕ ВАШЕ ИМЯ:**"
    else:
        question = "🏢 **ВВЕДИТЕ НАЗВАНИЕ КОМПАНИИ ИЛИ БРИГАДЫ:**"

    bot.edit_message_text(
        f"👷 **ЗАПОЛНЕНИЕ АНКЕТЫ МАСТЕРА**\n\n"
        f"Шаг 2 из 16\n"
        f"👇 {question}",
        call.message.chat.id,
        call.message.message_id
    )
    bot.register_next_step_handler(call.message, process_master_name)
    bot.answer_callback_query(call.id)

def process_master_name(message):
    if message.chat.type != 'private':
        return
    name = safe_text(message)
    if not name:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите имя/название.")
        return
    user_id = message.from_user.id
    bot.master_data[user_id]['name'] = name

    msg = bot.send_message(
        message.chat.id,
        "👷 **Шаг 3 из 16**\n\n"
        "👇 **ВЫБЕРИТЕ СПЕЦИАЛИЗАЦИЮ:**\n\n"
        "Введите цифру или название (можно несколько через запятую):\n"
        "1 - Сантехник\n"
        "2 - Электрик\n"
        "3 - Отделочник\n"
        "4 - Строитель\n"
        "5 - Сварщик\n"
        "6 - Разнорабочий\n"
        "7 - Другое\n"
        "8 - Дизайнер интерьера\n"
        "9 - Полный комплекс\n\n"
        "👉 Пример: `1, 3, 8` или `сантехник, электрик, дизайнер`"
    )
    bot.register_next_step_handler(msg, process_master_services)

def process_master_services(message):
    if message.chat.type != 'private':
        return
    text = safe_text(message)
    if not text:
        bot.send_message(message.chat.id, "❌ Пожалуйста, выберите специализацию(и).")
        return
    parts = [p.strip() for p in text.split(',')]
    services = []
    for p in parts:
        p_lower = p.lower()
        if p == '1' or 'сантехник' in p_lower:
            services.append('Сантехник')
        elif p == '2' or 'электрик' in p_lower:
            services.append('Электрик')
        elif p == '3' or 'отделочник' in p_lower:
            services.append('Отделочник')
        elif p == '4' or 'строитель' in p_lower:
            services.append('Строитель')
        elif p == '5' or 'сварщик' in p_lower:
            services.append('Сварщик')
        elif p == '6' or 'разнорабочий' in p_lower:
            services.append('Разнорабочий')
        elif p == '7' or 'другое' in p_lower:
            services.append('Другое')
        elif p == '8' or 'дизайнер' in p_lower:
            services.append('Дизайнер интерьера')
        elif p == '9' or 'полный комплекс' in p_lower:
            services.append('Полный комплекс')
        else:
            services.append(p.capitalize())
    services = list(set(filter(None, services)))
    if not services:
        bot.send_message(message.chat.id, "❌ Не выбрано ни одной специализации.")
        return
    services_str = ', '.join(services)
    user_id = message.from_user.id
    bot.master_data[user_id]['services'] = services_str
    bot.master_data[user_id]['service'] = services[0]

    msg = bot.send_message(
        message.chat.id,
        "📞 **Шаг 4 из 16**\n\n"
        "👇 **ВВЕДИТЕ ВАШ ТЕЛЕФОН:**\n\n"
        "Пример: +7 924 123-45-67\n\n"
        "⚠️ Номер будет виден ТОЛЬКО администратору"
    )
    bot.register_next_step_handler(msg, process_master_phone)

def process_master_phone(message):
    if message.chat.type != 'private':
        return
    phone = safe_text(message)
    if not phone:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите телефон.")
        return
    user_id = message.from_user.id
    bot.master_data[user_id]['phone'] = phone
    msg = bot.send_message(
        message.chat.id,
        "📍 **Шаг 5 из 16**\n\n"
        "👇 **В КАКИХ РАЙОНАХ/ЖК ВЫ РАБОТАЕТЕ?**\n\n"
        "Перечислите через запятую:\n"
        "Пример: Патрокл, Снеговая Падь, Варяг, Океан"
    )
    bot.register_next_step_handler(msg, process_master_districts)

def process_master_districts(message):
    if message.chat.type != 'private':
        return
    districts = safe_text(message)
    if not districts:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите районы.")
        return
    user_id = message.from_user.id
    bot.master_data[user_id]['districts'] = districts
    msg = bot.send_message(
        message.chat.id,
        "💰 **Шаг 6 из 16**\n\n"
        "👇 **МИНИМАЛЬНАЯ ЦЕНА ЗАКАЗА:**\n\n"
        "Укажите диапазон ваших обычных цен. Окончательная цена обсуждается с клиентом.\n"
        "Пример: 1000₽, 5000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_min)

def process_master_price_min(message):
    if message.chat.type != 'private':
        return
    price_min = safe_text(message)
    if not price_min:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите минимальную цену.")
        return
    user_id = message.from_user.id
    bot.master_data[user_id]['price_min'] = price_min
    msg = bot.send_message(
        message.chat.id,
        "💰 **Шаг 7 из 16**\n\n"
        "👇 **МАКСИМАЛЬНАЯ ЦЕНА ЗАКАЗА:**\n\n"
        "Пример: 50000₽, 100000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_max)

def process_master_price_max(message):
    if message.chat.type != 'private':
        return
    price_max = safe_text(message)
    if not price_max:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите максимальную цену.")
        return
    user_id = message.from_user.id
    bot.master_data[user_id]['price_max'] = price_max
    msg = bot.send_message(
        message.chat.id,
        "⏱️ **Шаг 8 из 16**\n\n"
        "👇 **ВАШ ОПЫТ РАБОТЫ:**\n\n"
        "Пример: 3 года, 5 лет, 10+ лет"
    )
    bot.register_next_step_handler(msg, process_master_experience)

def process_master_experience(message):
    if message.chat.type != 'private':
        return
    experience = safe_text(message)
    if not experience:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите опыт работы.")
        return
    user_id = message.from_user.id
    bot.master_data[user_id]['experience'] = experience

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="skip_bio"))
    bot.send_message(
        message.chat.id,
        "📝 **Шаг 9 из 16**\n\n"
        "👇 **КОММЕНТАРИЙ О СЕБЕ (кратко):**\n\n"
        "Расскажите о себе пару слов: опыт, специализация, подход к работе.\n"
        "Это увидят клиенты в вашей карточке.\n\n"
        "👉 **Или нажмите «Пропустить»**",
        reply_markup=markup
    )
    bot.register_next_step_handler(message, process_master_bio)

@bot.callback_query_handler(func=lambda call: call.data == 'skip_bio')
def skip_bio_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные не найдены. Начните анкету заново.")
        return
    bot.master_data[user_id]['bio'] = "Не указано"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="skip_portfolio"))
    markup.add(types.InlineKeyboardButton("❓ Как загрузить фото?", callback_data="help_portfolio"))
    bot.edit_message_text(
        "📸 **Шаг 10 из 16**\n\n"
        "👇 **ОТПРАВЬТЕ ССЫЛКУ НА ПОРТФОЛИО:**\n\n"
        "Это может быть:\n"
        "• Ссылка на Яндекс.Диск с фото\n"
        "• Ссылка на Google Фото\n"
        "• Telegram-канал с работами\n\n"
        "Если у вас нет ссылки, вы можете отправить фото администратору в личные сообщения, и он создаст ссылку для вас.\n\n"
        "👉 **Или нажмите кнопку «Пропустить»**",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id, "⏩ Пропущено")

def process_master_bio(message):
    if message.chat.type != 'private':
        return
    bio = safe_text(message)
    if not bio or bio.lower() == "пропустить":
        bio = "Не указано"
    user_id = message.from_user.id
    if user_id not in bot.master_data:
        bot.master_data[user_id] = {}
    bot.master_data[user_id]['bio'] = bio
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="skip_portfolio"))
    markup.add(types.InlineKeyboardButton("❓ Как загрузить фото?", callback_data="help_portfolio"))
    bot.send_message(
        message.chat.id,
        "📸 **Шаг 10 из 16**\n\n"
        "👇 **ОТПРАВЬТЕ ССЫЛКУ НА ПОРТФОЛИО:**\n\n"
        "Это может быть:\n"
        "• Ссылка на Яндекс.Диск с фото\n"
        "• Ссылка на Google Фото\n"
        "• Telegram-канал с работами\n\n"
        "Если у вас нет ссылки, вы можете отправить фото администратору в личные сообщения, и он создаст ссылку для вас.\n\n"
        "👉 **Или нажмите кнопку «Пропустить»**",
        reply_markup=markup
    )
    bot.register_next_step_handler(message, process_master_portfolio_text)

@bot.callback_query_handler(func=lambda call: call.data == 'help_portfolio')
def help_portfolio_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "📸 **Как загрузить фото в портфолио:**\n\n"
        "1. Отправьте фото администратору в личные сообщения (@remont_vl25).\n"
        "2. После получения фото администратор создаст для вас ссылку.\n"
        "3. Скопируйте полученную ссылку и отправьте её в это поле.\n\n"
        "Или вы можете самостоятельно загрузить фото на Яндекс.Диск или Google Фото и поделиться ссылкой."
    )

@bot.callback_query_handler(func=lambda call: call.data == 'skip_portfolio')
def skip_portfolio_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные не найдены. Начните анкету заново.")
        return
    bot.master_data[user_id]['portfolio'] = "Не указано"
    ask_age(call.message.chat.id, user_id, bot.master_data[user_id])
    bot.answer_callback_query(call.id, "⏩ Пропущено")

def process_master_portfolio_text(message):
    if message.chat.type != 'private':
        return
    portfolio = safe_text(message)
    if not portfolio or portfolio.lower() == "пропустить":
        portfolio = "Не указано"
    user_id = message.from_user.id
    if user_id not in bot.master_data:
        bot.master_data[user_id] = {}
    bot.master_data[user_id]['portfolio'] = portfolio
    ask_age(message.chat.id, user_id, bot.master_data[user_id])

def ask_age(chat_id, user_id, user_data):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("до 25 лет", callback_data="age_under25"),
        types.InlineKeyboardButton("25-35 лет", callback_data="age_25_35"),
        types.InlineKeyboardButton("35-50 лет", callback_data="age_35_50"),
        types.InlineKeyboardButton("старше 50", callback_data="age_over50"),
        types.InlineKeyboardButton("⏩ Пропустить", callback_data="age_skip")
    )
    bot.send_message(
        chat_id,
        "🎂 **Шаг 11 из 16**\n\n"
        "Укажите ваш возраст (необязательно). Это поможет клиентам лучше узнать вас.",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('age_'))
def age_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные не найдены. Начните анкету заново.")
        return
    age_map = {
        'under25': 'до 25',
        '25_35': '25-35',
        '35_50': '35-50',
        'over50': 'старше 50',
        'skip': ''
    }
    key = call.data[4:]
    bot.master_data[user_id]['age_group'] = age_map.get(key, '')
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    show_documents_buttons(call.message.chat.id, user_id, bot.master_data[user_id])
    bot.answer_callback_query(call.id)

def show_documents_buttons(chat_id, user_id, user_data):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("✅ Есть документы", callback_data="doc_yes"),
        types.InlineKeyboardButton("❌ Нет документов", callback_data="doc_no"),
        types.InlineKeyboardButton("⏩ Пропустить", callback_data="doc_skip")
    )
    bot.send_message(
        chat_id,
        "📄 **Шаг 12 из 16**\n\n"
        "👇 **ПОДТВЕРЖДАЮЩИЕ ДОКУМЕНТЫ:**\n\n"
        "Какие документы вы предоставляете при работе?\n"
        "• Договор\n"
        "• ИП / Самозанятость\n"
        "• Чек / Акт\n"
        "• Паспорт (для проверки администратором)\n\n"
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
        bot.edit_message_text(
            "📄 **Какие документы у вас есть?**\n\n"
            "Введите через запятую, например: договор, ИП, самозанятость, чек, паспорт",
            call.message.chat.id,
            call.message.message_id
        )
        bot.register_next_step_handler(call.message, process_documents_list, user_id)
    elif choice == 'no':
        user_data['documents'] = "Нет"
        user_data['documents_list'] = ""
        bot.master_data[user_id] = user_data
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        ask_documents_verification(call.message, user_id, user_data)
    else:
        user_data['documents'] = "Пропустить"
        user_data['documents_list'] = ""
        bot.master_data[user_id] = user_data
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        ask_preferred_contact(call.message, user_id, user_data)
    bot.answer_callback_query(call.id, f"Выбрано: {choice}")

def process_documents_list(message, user_id):
    if message.chat.type != 'private':
        return
    docs_list = safe_text(message)
    if not docs_list:
        docs_list = ""
    user_data = bot.master_data[user_id]
    user_data['documents_list'] = docs_list
    user_data['documents'] = "Есть"
    bot.master_data[user_id] = user_data
    ask_documents_verification(message, user_id, user_data)

def ask_documents_verification(message, user_id, user_data):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Да, готов", callback_data="verify_yes"),
        types.InlineKeyboardButton("❌ Нет, не готов", callback_data="verify_no")
    )
    bot.send_message(
        message.chat.id,
        "🛡️ **Шаг 13 из 16**\n\n"
        "Готовы ли вы предоставить администратору документы для проверки (в том числе паспорт)?\n"
        "Если да, после проверки ваша карточка получит статус «Документы проверены».",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('verify_'))
def verify_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Ошибка, начните заново.")
        return
    user_data = bot.master_data[user_id]
    if call.data == 'verify_yes':
        user_data['documents_verified'] = 'pending'
    else:
        user_data['documents_verified'] = 'no'
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    ask_preferred_contact(call.message, user_id, user_data)
    bot.answer_callback_query(call.id)

def ask_preferred_contact(message, user_id, user_data):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("Telegram", callback_data="contact_telegram"),
        types.InlineKeyboardButton("WhatsApp", callback_data="contact_whatsapp"),
        types.InlineKeyboardButton("Телефонный звонок", callback_data="contact_phone")
    )
    bot.send_message(
        message.chat.id,
        "📞 **Шаг 14 из 16**\n\n"
        "Как вам удобнее общаться с клиентами?",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('contact_'))
def contact_callback(call):
    contact = call.data.split('_')[1]
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Ошибка, начните заново.")
        return
    bot.master_data[user_id]['preferred_contact'] = contact
    bot.edit_message_text(
        "💳 **Шаг 15 из 16**\n\n"
        "Какие способы оплаты вы принимаете?\n"
        "Введите через запятую, например: наличные, карта, перевод",
        call.message.chat.id,
        call.message.message_id
    )
    bot.register_next_step_handler(call.message, process_payment_methods, user_id)
    bot.answer_callback_query(call.id)

def process_payment_methods(message, user_id):
    if message.chat.type != 'private':
        return
    methods = safe_text(message)
    if not methods:
        methods = "Не указано"
    user_data = bot.master_data[user_id]
    user_data['payment_methods'] = methods
    bot.master_data[user_id] = user_data

    summary = f"""
📋 **Сводка анкеты:**

👤 Имя/Название: {user_data['name']}
🔧 Специализации: {user_data['services']}
📞 Телефон: {user_data['phone']}
📍 Районы: {user_data['districts']}
💰 Цены: {user_data['price_min']} – {user_data['price_max']}
⏱ Опыт: {user_data['experience']}
💬 О себе: {user_data.get('bio', 'Не указано')}
📸 Портфолио: {user_data.get('portfolio', 'Не указано')}
🎂 Возраст: {user_data.get('age_group', 'Не указан')}
📄 Документы: {user_data['documents']}
   Список: {user_data.get('documents_list', '')}
🛡️ Готовность к проверке: {'✅ Да' if user_data.get('documents_verified')=='pending' else '❌ Нет'}
📞 Предпочтительный контакт: {user_data.get('preferred_contact', 'telegram')}
💳 Оплата: {user_data.get('payment_methods', 'Не указано')}
    """
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Сохранить анкету", callback_data=f"save_app_{user_id}"))
    bot.send_message(message.chat.id, summary, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('save_app_'))
def save_app_callback(call):
    user_id = int(call.data.split('_')[2])
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша анкета")
        return
    user_data = bot.master_data[user_id]
    try:
        save_master_application(call.message, user_id, user_data)
        bot.answer_callback_query(call.id, "✅ Анкета сохранена!")
    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Ошибка сохранения")
        bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")

def save_master_application(message, user_id, user_data):
    name = user_data['name']
    services_str = user_data['services']
    service = user_data.get('service', services_str.split(',')[0])
    phone = user_data['phone']
    districts = user_data['districts']
    price_min = user_data['price_min']
    price_max = user_data['price_max']
    experience = user_data['experience']
    bio = user_data.get('bio', 'Не указано')
    portfolio = user_data.get('portfolio', 'Не указано')
    documents = user_data['documents']
    entity_type = user_data['entity_type']
    verification_type = user_data['verification_type']
    documents_list = user_data.get('documents_list', '')
    payment_methods = user_data.get('payment_methods', '')
    preferred_contact = user_data.get('preferred_contact', 'telegram')
    age_group = user_data.get('age_group', '')

    cursor.execute('''INSERT INTO master_applications
                    (user_id, username, name, service, phone, districts, 
                     price_min, price_max, experience, bio, portfolio, documents,
                     entity_type, verification_type, source, documents_list, payment_methods, preferred_contact, age_group, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id,
                     message.from_user.username or "no_username",
                     name, service, phone, districts,
                     price_min, price_max, experience, bio, portfolio, documents,
                     entity_type, verification_type, 'bot',
                     documents_list, payment_methods, preferred_contact, age_group,
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
        'entity_type': entity_type,
        'verification_type': verification_type,
        'source': 'bot'
    }
    add_master_to_google_sheet(master_data)

    entity_display = "👤 Частное лицо" if entity_type == 'individual' else "🏢 Компания/ИП"
    admin_msg = f"""
🆕 **НОВАЯ АНКЕТА МАСТЕРА!** (ID: {application_id})
📱 **Источник:** Бот
👤 **Telegram:** @{message.from_user.username or "нет"}
🆔 **ID:** {user_id}

{entity_display}
👤 **Имя/Название:** {name}
🔧 **Специализации:** {services_str}
📞 **Телефон:** {phone}
📍 **Районы:** {districts}
💰 **Цены:** {price_min} - {price_max}
⏱️ **Опыт:** {experience}
💬 **О себе:** {bio}
📸 **Портфолио:** {portfolio}
🎂 **Возраст:** {age_group}
📄 **Документы:** {documents}
📋 **Список документов:** {documents_list}
🛡️ **Готов к проверке:** {'✅ Да' if user_data.get('documents_verified')=='pending' else '❌ Нет'}
💳 **Оплата:** {payment_methods}
📞 **Предпочтительный контакт:** {preferred_contact}
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
        "2. После проверки ваша карточка появится в канале\n\n"
        "Если вы работаете ещё по другой специальности, вы можете добавить ещё одну анкету."
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "➕ Добавить ещё одну специализацию",
        callback_data=f"add_another_{user_id}"
    ))
    bot.send_message(
        message.chat.id,
        "Хотите добавить ещё одну специализацию? Нажмите кнопку ниже.",
        reply_markup=markup
    )

    if user_id in bot.master_data:
        del bot.master_data[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_another_'))
def add_another_callback(call):
    user_id = int(call.data.split('_')[2])
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша анкета")
        return
    bot.answer_callback_query(call.id, "Заполните новую анкету для другой специальности.")
    become_master(call.message)
    # ================ ОСТАВИТЬ ЗАЯВКУ ================
@bot.message_handler(func=lambda message: message.text == '🔨 Оставить заявку')
def create_request_start(message):
    if not only_private(message):
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔧 Публичная заявка", callback_data="request_public"),
        types.InlineKeyboardButton("🤝 Персональный подбор", callback_data="request_private")
    )
    bot.send_message(
        message.chat.id,
        "🔨 **Какую заявку хотите оставить?**\n\n"
        "• **Публичная** – увидят все мастера, кто захочет – откликнется.\n"
        "• **Персональный подбор** – мы подберём лучших мастеров по вашим критериям.",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('request_'))
def request_type_callback(call):
    req_type = call.data.split('_')[1]  # 'public' или 'private'
    user_id = call.from_user.id
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('UPDATE users SET last_active = ? WHERE user_id = ?', (now, user_id))
    conn.commit()

    # Сохраняем тип заявки во временном хранилище
    if not hasattr(bot, 'request_data'):
        bot.request_data = {}
    bot.request_data[user_id] = {'type': req_type}

    bot.edit_message_text(
        f"📝 **Шаг 1 из 6**\n\nУкажите **услугу**, которая вам нужна.\nПример: *Заменить смеситель, проложить проводку*",
        call.message.chat.id,
        call.message.message_id
    )
    bot.register_next_step_handler(call.message, process_request_service)
    bot.answer_callback_query(call.id)

def process_request_service(message):
    if message.chat.type != 'private':
        return
    service = safe_text(message)
    if not service:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите услугу.")
        return
    user_id = message.from_user.id
    bot.request_data[user_id]['service'] = service

    msg = bot.send_message(
        message.chat.id,
        "📝 **Шаг 2 из 6**\n\nОпишите задачу подробнее.\nЧто нужно сделать? Какие материалы? Есть ли нюансы?"
    )
    bot.register_next_step_handler(msg, process_request_description)

def process_request_description(message):
    if message.chat.type != 'private':
        return
    desc = safe_text(message)
    if not desc:
        bot.send_message(message.chat.id, "❌ Пожалуйста, опишите задачу.")
        return
    user_id = message.from_user.id
    bot.request_data[user_id]['description'] = desc

    msg = bot.send_message(
        message.chat.id,
        "📍 **Шаг 3 из 6**\n\nУкажите **район или ЖК**, где нужно выполнить работу.\nПример: *Патрокл, Снеговая Падь, Варяг, Центр*"
    )
    bot.register_next_step_handler(msg, process_request_district)

def process_request_district(message):
    if message.chat.type != 'private':
        return
    district = safe_text(message)
    if not district:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите район.")
        return
    user_id = message.from_user.id
    bot.request_data[user_id]['district'] = district

    msg = bot.send_message(
        message.chat.id,
        "📅 **Шаг 4 из 6**\n\nКогда нужно приступить?\nПример: *В ближайшие дни, на следующей неделе, после 15 мая*"
    )
    bot.register_next_step_handler(msg, process_request_date)

def process_request_date(message):
    if message.chat.type != 'private':
        return
    date = safe_text(message)
    if not date:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите желаемые сроки.")
        return
    user_id = message.from_user.id
    bot.request_data[user_id]['date'] = date

    msg = bot.send_message(
        message.chat.id,
        "💰 **Шаг 5 из 6**\n\nКакой бюджет?\nПример: *до 5000₽, договорной, 10-15 тыс.*"
    )
    bot.register_next_step_handler(msg, process_request_budget)

def process_request_budget(message):
    if message.chat.type != 'private':
        return
    budget = safe_text(message)
    if not budget:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите бюджет.")
        return
    user_id = message.from_user.id
    bot.request_data[user_id]['budget'] = budget

    # Показываем сводку
    data = bot.request_data[user_id]
    summary = f"""
📋 **Сводка заявки:**

🔧 Услуга: {data['service']}
📝 Описание: {data['description']}
📍 Район: {data['district']}
📅 Срок: {data['date']}
💰 Бюджет: {data['budget']}
📢 Тип: {'Публичная' if data['type'] == 'public' else 'Персональный подбор'}
    """
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_req_{user_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_req")
    )
    bot.send_message(message.chat.id, summary, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_req_'))
def confirm_request(call):
    user_id = int(call.data.split('_')[2])
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша заявка")
        return

    data = bot.request_data.get(user_id)
    if not data:
        bot.answer_callback_query(call.id, "❌ Данные не найдены. Начните заново.")
        return

    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('''INSERT INTO requests
                    (user_id, username, service, description, district, date, budget, is_public, status, delayed, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id,
                     call.from_user.username or "no_username",
                     data['service'],
                     data['description'],
                     data['district'],
                     data['date'],
                     data['budget'],
                     1 if data['type'] == 'public' else 0,
                     'активна',
                     1 if is_night_time() and data['type'] == 'public' else 0,
                     now))
    conn.commit()
    request_id = cursor.lastrowid

    if data['type'] == 'public':
        if is_night_time():
            bot.send_message(
                call.message.chat.id,
                "🌙 **Сейчас ночное время** (по Владивостоку).\n"
                "Ваша заявка будет опубликована утром, чтобы не беспокоить мастеров.\n"
                "Спасибо за понимание!"
            )
        else:
            client_alias = f"Клиент #{request_id % 10000}"
            text = f"""
🆕 **НОВАЯ ЗАЯВКА!**

👤 **От:** {client_alias}
🔨 **Услуга:** {data['service']}
📝 **Задача:** {data['description']}
📍 **Район/ЖК:** {data['district']}
📅 **Когда:** {data['date']}
💰 **Бюджет:** {data['budget']}
📢 Публичная заявка. Мастера, откликайтесь в боте!
            """
            try:
                sent = bot.send_message(CHANNEL_ID, text)
                cursor.execute("UPDATE requests SET chat_message_id = ? WHERE id = ?", (sent.message_id, request_id))
                conn.commit()
            except Exception as e:
                bot.send_message(ADMIN_ID, f"❌ Ошибка отправки заявки в канал: {e}")
                bot.send_message(call.message.chat.id, "❌ Не удалось опубликовать заявку. Администратор уже уведомлён.")
    else:
        bot.send_message(
            call.message.chat.id,
            "🤝 **Заявка на персональный подбор принята!**\n\n"
            "В ближайшее время мы подберём для вас подходящих мастеров и свяжемся с вами."
        )
        # Уведомление админу о персональном подборе
        admin_text = f"""
🆕 **НОВАЯ ЗАЯВКА (ПЕРСОНАЛЬНЫЙ ПОДБОР)!**
ID: {request_id}
👤 Клиент: @{call.from_user.username or "нет"} (ID: {user_id})
🔧 Услуга: {data['service']}
📝 Описание: {data['description']}
📍 Район: {data['district']}
📅 Срок: {data['date']}
💰 Бюджет: {data['budget']}
        """
        try:
            bot.send_message(ADMIN_ID, admin_text)
        except:
            pass

    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(call.message.chat.id, "✅ Заявка сохранена! Спасибо.")

    if user_id in bot.request_data:
        del bot.request_data[user_id]

    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_req')
def cancel_request(call):
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(call.message.chat.id, "❌ Создание заявки отменено.")
    bot.answer_callback_query(call.id)

# ================ ПОИСК МАСТЕРА (КАТАЛОГ) ================
@bot.message_handler(func=lambda message: message.text == '🔍 Найти мастера')
def find_master_start(message):
    if not only_private(message):
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('По специализации', 'По району', 'По рейтингу')
    markup.row('◀️ Назад в меню')
    bot.send_message(
        message.chat.id,
        "🔍 **Поиск мастера**\n\nВыберите критерий поиска:",
        reply_markup=markup
    )
    bot.register_next_step_handler(message, find_master_menu)

def find_master_menu(message):
    text = message.text
    if text == '◀️ Назад в меню':
        cursor.execute('SELECT role FROM users WHERE user_id = ?', (message.from_user.id,))
        row = cursor.fetchone()
        show_role_menu(message, row[0] if row else 'client')
        return
    if text == 'По специализации':
        bot.send_message(
            message.chat.id,
            "🔧 **Введите специализацию**\nНапример: *сантехник, электрик, отделочник*"
        )
        bot.register_next_step_handler(message, search_by_service)
    elif text == 'По району':
        bot.send_message(
            message.chat.id,
            "📍 **Введите район или ЖК**\nНапример: *Патрокл, Снеговая Падь, Центр*"
        )
        bot.register_next_step_handler(message, search_by_district)
    elif text == 'По рейтингу':
        search_by_rating(message)
    else:
        bot.send_message(message.chat.id, "❌ Неверный выбор. Попробуйте снова.")
        find_master_start(message)

def search_by_service(message):
    service = safe_text(message).lower()
    if not service:
        bot.send_message(message.chat.id, "❌ Введите специализацию.")
        return
    cursor.execute('''SELECT id, name, service, rating, reviews_count, districts
                      FROM masters WHERE status = 'активен' AND LOWER(service) LIKE ?''',
                   (f'%{service}%',))
    masters = cursor.fetchall()
    if not masters:
        bot.send_message(message.chat.id, "😕 Мастеров с такой специализацией пока нет.")
        return
    send_masters_list(message.chat.id, masters)

def search_by_district(message):
    district = safe_text(message).lower()
    if not district:
        bot.send_message(message.chat.id, "❌ Введите район.")
        return
    cursor.execute('''SELECT id, name, service, rating, reviews_count, districts
                      FROM masters WHERE status = 'активен' AND LOWER(districts) LIKE ?''',
                   (f'%{district}%',))
    masters = cursor.fetchall()
    if not masters:
        bot.send_message(message.chat.id, "😕 Мастеров в этом районе пока нет.")
        return
    send_masters_list(message.chat.id, masters)

def search_by_rating(message):
    cursor.execute('''SELECT id, name, service, rating, reviews_count, districts
                      FROM masters WHERE status = 'активен' ORDER BY rating DESC, reviews_count DESC LIMIT 10''')
    masters = cursor.fetchall()
    if not masters:
        bot.send_message(message.chat.id, "😕 Активных мастеров пока нет.")
        return
    send_masters_list(message.chat.id, masters)

def send_masters_list(chat_id, masters):
    for master in masters:
        master_id, name, service, rating, reviews_count, districts = master
        rating_display = f"{rating:.1f}" if rating else "Нет"
        text = f"""
👤 **{name}**
🔧 {service}
⭐ Рейтинг: {rating_display} ({reviews_count} отзывов)
📍 Районы: {districts}
        """
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👤 Подробнее", callback_data=f"master_{master_id}"))
        bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('master_'))
def master_detail(call):
    master_id = int(call.data.split('_')[1])
    cursor.execute('''SELECT name, service, phone, districts, price_min, price_max, experience, bio, portfolio, rating, reviews_count
                      FROM masters WHERE id = ?''', (master_id,))
    master = cursor.fetchone()
    if not master:
        bot.answer_callback_query(call.id, "❌ Мастер не найден")
        return
    name, service, phone, districts, price_min, price_max, experience, bio, portfolio, rating, reviews_count = master
    rating_display = f"{rating:.1f}" if rating else "Нет"
    text = f"""
👤 **{name}**
🔧 {service}
⭐ Рейтинг: {rating_display} ({reviews_count} отзывов)
📍 Районы: {districts}
💰 Цены: {price_min} - {price_max}
⏱ Опыт: {experience}
💬 О себе: {bio}
📸 Портфолио: {portfolio}
    """
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📞 Связаться", callback_data=f"contact_{master_id}"))
    markup.add(types.InlineKeyboardButton("⭐ Отзывы", callback_data=f"reviews_{master_id}"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('contact_'))
def contact_master(call):
    master_id = int(call.data.split('_')[1])
    cursor.execute('SELECT phone FROM masters WHERE id = ?', (master_id,))
    row = cursor.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "❌ Контакт не найден")
        return
    phone = row[0]
    bot.answer_callback_query(call.id, f"Телефон: {phone}", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('reviews_'))
def show_master_reviews(call):
    master_id = int(call.data.split('_')[1])
    cursor.execute('''SELECT user_name, review_text, rating, created_at
                      FROM reviews WHERE master_id = ? AND status = 'approved'
                      ORDER BY created_at DESC LIMIT 5''', (master_id,))
    reviews = cursor.fetchall()
    if not reviews:
        bot.send_message(call.message.chat.id, "У этого мастера пока нет отзывов.")
        return
    text = f"⭐ **Отзывы о мастере**\n\n"
    for r in reviews:
        user_name, rev_text, rating, created = r
        text += f"👤 {user_name} – {rating}/5\n{rev_text}\n_{created}_\n\n"
    bot.send_message(call.message.chat.id, text)

# ================ ОСТАВИТЬ ОТЗЫВ ================
@bot.message_handler(func=lambda message: message.text == '⭐ Оставить отзыв')
def review_start(message):
    if not only_private(message):
        return
    bot.send_message(
        message.chat.id,
        "⭐ **Оставьте отзыв о мастере**\n\nВведите имя или ID мастера, чтобы найти его в базе."
    )
    bot.register_next_step_handler(message, find_master_for_review)

def find_master_for_review(message):
    query = safe_text(message)
    if not query:
        bot.send_message(message.chat.id, "❌ Введите имя или ID.")
        return
    cursor.execute('''SELECT id, name, service FROM masters
                      WHERE status = 'активен' AND (name LIKE ? OR id = ?)''',
                   (f'%{query}%', query if query.isdigit() else -1))
    masters = cursor.fetchall()
    if not masters:
        bot.send_message(message.chat.id, "😕 Мастер не найден. Попробуйте другое имя.")
        return
    if len(masters) == 1:
        master_id, name, service = masters[0]
        bot.send_message(
            message.chat.id,
            f"Найден мастер: {name} ({service})\nВведите текст отзыва:"
        )
        bot.register_next_step_handler(message, process_review_text, master_id, name)
    else:
        text = "Найдено несколько мастеров:\n"
        for m in masters:
            text += f"ID {m[0]}: {m[1]} ({m[2]})\n"
        text += "\nВведите ID нужного мастера:"
        bot.send_message(message.chat.id, text)
        bot.register_next_step_handler(message, choose_master_for_review, masters)

def choose_master_for_review(message, masters):
    try:
        master_id = int(message.text)
        selected = [m for m in masters if m[0] == master_id]
        if not selected:
            raise ValueError
        name, service = selected[0][1], selected[0][2]
        bot.send_message(message.chat.id, f"Вы выбрали {name} ({service}). Введите текст отзыва:")
        bot.register_next_step_handler(message, process_review_text, master_id, name)
    except:
        bot.send_message(message.chat.id, "❌ Неверный ID. Попробуйте снова.")
        find_master_for_review(message)

def process_review_text(message, master_id, master_name):
    text = safe_text(message)
    if not text:
        bot.send_message(message.chat.id, "❌ Текст не может быть пустым.")
        return
    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = [types.InlineKeyboardButton(str(i), callback_data=f"review_rate_{i}_{master_id}") for i in range(1, 6)]
    markup.add(*buttons)
    bot.send_message(
        message.chat.id,
        f"⭐ Оцените мастера {master_name} от 1 до 5:",
        reply_markup=markup
    )
    bot.master_review_text = {message.from_user.id: (master_id, master_name, text)}

@bot.callback_query_handler(func=lambda call: call.data.startswith('review_rate_'))
def review_rate_callback(call):
    parts = call.data.split('_')
    rating = int(parts[2])
    master_id = int(parts[3])
    user_id = call.from_user.id
    if user_id not in bot.master_review_text:
        bot.answer_callback_query(call.id, "❌ Ошибка, начните заново.")
        return
    master_id, master_name, review_text = bot.master_review_text[user_id]
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('''INSERT INTO reviews
                    (master_id, master_name, user_id, user_name, review_text, rating, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (master_id, master_name, user_id,
                     call.from_user.username or "Аноним",
                     review_text, rating, 'pending', now))
    conn.commit()
    bot.edit_message_text(
        "✅ Спасибо! Отзыв отправлен на модерацию.",
        call.message.chat.id,
        call.message.message_id
    )
    bot.answer_callback_query(call.id, "Отзыв сохранён")
    del bot.master_review_text[user_id]

    # Уведомление админу
    admin_text = f"""
🆕 **НОВЫЙ ОТЗЫВ** (ожидает модерации)
👤 Мастер: {master_name} (ID {master_id})
👤 От: @{call.from_user.username or "аноним"}
⭐ Оценка: {rating}
💬 Текст: {review_text}
    """
    try:
        bot.send_message(ADMIN_ID, admin_text)
    except:
        pass

# ================ РЕКОМЕНДОВАТЬ МАСТЕРА (КЛИЕНТСКАЯ РЕКОМЕНДАЦИЯ) ================
@bot.message_handler(func=lambda message: message.text == '👍 Рекомендовать мастера')
def recommend_start(message):
    if not only_private(message):
        return
    bot.send_message(
        message.chat.id,
        "👍 **Рекомендация мастера**\n\n"
        "Знаете хорошего специалиста, которого пока нет в базе? Расскажите о нём, и мы добавим его.\n\n"
        "Введите имя мастера:"
    )
    bot.register_next_step_handler(message, process_recommend_name)

def process_recommend_name(message):
    name = safe_text(message)
    if not name:
        bot.send_message(message.chat.id, "❌ Введите имя.")
        return
    user_id = message.from_user.id
    if not hasattr(bot, 'recommend_data'):
        bot.recommend_data = {}
    bot.recommend_data[user_id] = {'master_name': name}
    bot.send_message(
        message.chat.id,
        "🔧 Какую специализацию вы можете порекомендовать?\nПример: *сантехник, электрик*"
    )
    bot.register_next_step_handler(message, process_recommend_service)

def process_recommend_service(message):
    service = safe_text(message)
    if not service:
        bot.send_message(message.chat.id, "❌ Введите специализацию.")
        return
    user_id = message.from_user.id
    bot.recommend_data[user_id]['service'] = service
    bot.send_message(
        message.chat.id,
        "📞 Контакт мастера (телефон, ник в Telegram и т.п.) – будет передан администратору для связи:"
    )
    bot.register_next_step_handler(message, process_recommend_contact)

def process_recommend_contact(message):
    contact = safe_text(message)
    if not contact:
        bot.send_message(message.chat.id, "❌ Введите контакт.")
        return
    user_id = message.from_user.id
    bot.recommend_data[user_id]['contact'] = contact
    bot.send_message(
        message.chat.id,
        "📝 Краткое описание: почему вы рекомендуете этого мастера? (качество, опыт, отношение)"
    )
    bot.register_next_step_handler(message, process_recommend_desc)

def process_recommend_desc(message):
    desc = safe_text(message)
    if not desc:
        bot.send_message(message.chat.id, "❌ Введите описание.")
        return
    user_id = message.from_user.id
    bot.recommend_data[user_id]['description'] = desc
    bot.send_message(
        message.chat.id,
        "💰 Уровень цен (необязательно, можно пропустить, отправив 'пропустить'):"
    )
    bot.register_next_step_handler(message, process_recommend_price)

def process_recommend_price(message):
    price = safe_text(message)
    if not price or price.lower() == 'пропустить':
        price = ""
    user_id = message.from_user.id
    bot.recommend_data[user_id]['price_level'] = price
    bot.send_message(
        message.chat.id,
        "😊 Удовлетворение (необязательно, можно пропустить):"
    )
    bot.register_next_step_handler(message, process_recommend_satisfaction)

def process_recommend_satisfaction(message):
    sat = safe_text(message)
    if not sat or sat.lower() == 'пропустить':
        sat = ""
    user_id = message.from_user.id
    bot.recommend_data[user_id]['satisfaction'] = sat
    bot.send_message(
        message.chat.id,
        "👍 Порекомендовали бы другим? (да/нет) (необязательно, можно пропустить)"
    )
    bot.register_next_step_handler(message, process_recommend_would_recommend)

def process_recommend_would_recommend(message):
    would = safe_text(message)
    if not would or would.lower() == 'пропустить':
        would = ""
    user_id = message.from_user.id
    bot.recommend_data[user_id]['recommend'] = would
    bot.send_message(
        message.chat.id,
        "📸 При желании можете отправить фото/видео работ мастера (или нажмите 'пропустить'):"
    )
    bot.register_next_step_handler(message, process_recommend_media)

def process_recommend_media(message):
    user_id = message.from_user.id
    media_id = None
    if message.photo:
        media_id = message.photo[-1].file_id
    elif message.video:
        media_id = message.video.file_id
    else:
        # текст или пропуск
        pass
    bot.recommend_data[user_id]['media_file_id'] = media_id

    data = bot.recommend_data[user_id]
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('''INSERT INTO recommendations
                    (user_id, username, master_name, service, contact, description, price_level, satisfaction, recommend, media_file_id, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id,
                     message.from_user.username or "no_username",
                     data['master_name'],
                     data['service'],
                     data['contact'],
                     data['description'],
                     data.get('price_level', ''),
                     data.get('satisfaction', ''),
                     data.get('recommend', ''),
                     data.get('media_file_id', ''),
                     'на модерации',
                     now))
    conn.commit()
    rec_id = cursor.lastrowid

    bot.send_message(
        message.chat.id,
        "✅ Спасибо за рекомендацию! Администратор проверит её и свяжется с мастером."
    )
    del bot.recommend_data[user_id]

    # Уведомление админу
    admin_text = f"""
🆕 **НОВАЯ РЕКОМЕНДАЦИЯ МАСТЕРА** (ID: {rec_id})
👤 Рекомендатель: @{message.from_user.username or "нет"}
👤 Мастер: {data['master_name']}
🔧 Специализация: {data['service']}
📞 Контакт: {data['contact']}
📝 Описание: {data['description']}
💰 Цены: {data.get('price_level', 'не указано')}
😊 Удовлетворение: {data.get('satisfaction', 'не указано')}
👍 Рекомендует: {data.get('recommend', 'не указано')}
    """
    try:
        bot.send_message(ADMIN_ID, admin_text)
    except:
        pass

# ================ АДМИНИСТРАТИВНЫЕ КОМАНДЫ ================
@bot.message_handler(commands=['approve'])
def approve_master(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    try:
        app_id = int(message.text.split()[1])
        cursor.execute('''SELECT user_id, name, service, phone, districts, price_min, price_max,
                          experience, bio, portfolio, documents, entity_type, verification_type,
                          documents_list, payment_methods, preferred_contact, age_group, source
                          FROM master_applications WHERE id = ?''', (app_id,))
        app = cursor.fetchone()
        if not app:
            bot.reply_to(message, f"❌ Анкета с ID {app_id} не найдена.")
            return
        (user_id, name, service, phone, districts, price_min, price_max,
         experience, bio, portfolio, documents, entity_type, verification_type,
         documents_list, payment_methods, preferred_contact, age_group, source) = app

        # Добавляем в таблицу мастеров
        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        cursor.execute('''INSERT INTO masters
                        (user_id, name, service, phone, districts, price_min, price_max,
                         experience, bio, portfolio, documents, entity_type, verification_type,
                         documents_list, payment_methods, preferred_contact, age_group,
                         source, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (user_id, name, service, phone, districts, price_min, price_max,
                         experience, bio, portfolio, documents, entity_type, verification_type,
                         documents_list, payment_methods, preferred_contact, age_group,
                         source, 'активен', now))
        conn.commit()
        master_id = cursor.lastrowid

        # Удаляем из заявок
        cursor.execute("DELETE FROM master_applications WHERE id = ?", (app_id,))
        conn.commit()

        # Уведомляем мастера
        try:
            bot.send_message(
                user_id,
                f"✅ Поздравляем! Ваша анкета одобрена!\n\nВы добавлены в базу мастеров. Теперь вы будете получать уведомления о новых заявках по вашей специализации.\n\nПриглашаем в закрытый чат мастеров: {MASTER_CHAT_INVITE_LINK}"
            )
        except:
            pass

        # Публикуем карточку в канал (если нужно)
        publish_master_card(master_id, name, service, districts, price_min, price_max, experience, bio, portfolio)

        bot.reply_to(message, f"✅ Мастер одобрен (ID {master_id}).")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['reject'])
def reject_master(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    try:
        parts = message.text.split(maxsplit=2)
        app_id = int(parts[1])
        reason = parts[2] if len(parts) > 2 else "Причина не указана"
        cursor.execute('SELECT user_id FROM master_applications WHERE id = ?', (app_id,))
        row = cursor.fetchone()
        if not row:
            bot.reply_to(message, f"❌ Анкета с ID {app_id} не найдена.")
            return
        user_id = row[0]
        cursor.execute("DELETE FROM master_applications WHERE id = ?", (app_id,))
        conn.commit()
        try:
            bot.send_message(
                user_id,
                f"❌ Ваша анкета отклонена.\nПричина: {reason}\n\nВы можете попробовать снова, исправив ошибки."
            )
        except:
            pass
        bot.reply_to(message, f"✅ Анкета {app_id} отклонена.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

def publish_master_card(master_id, name, service, districts, price_min, price_max, experience, bio, portfolio):
    text = f"""
👤 **НОВЫЙ МАСТЕР В БАЗЕ!**

👤 **Имя:** {name}
🔧 **Специализация:** {service}
📍 **Районы:** {districts}
💰 **Цены:** {price_min} – {price_max}
⏱ **Опыт:** {experience}
💬 **О себе:** {bio}
📸 **Портфолио:** {portfolio}

⭐ Подробнее и отзывы – в боте: @{BOT_USERNAME}
    """
    try:
        sent = bot.send_message(CHANNEL_ID, text)
        cursor.execute("UPDATE masters SET channel_message_id = ? WHERE id = ?", (sent.message_id, master_id))
        conn.commit()
    except Exception as e:
        print(f"Ошибка публикации карточки мастера: {e}")

# ================ ОТЛОЖЕННЫЕ ЗАЯВКИ ПРИ ЗАПУСКЕ ================
@bot.message_handler(commands=['publish_delayed'])
def manual_publish_delayed(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    publish_delayed_requests()
    bot.reply_to(message, "✅ Попытка публикации отложенных заявок выполнена.")

# ================ АДМИНИСТРАТИВНЫЕ КНОПКИ ================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 Заявки мастеров", callback_data="admin_apps"),
        types.InlineKeyboardButton("📝 Отзывы на модерации", callback_data="admin_reviews"),
        types.InlineKeyboardButton("👍 Рекомендации", callback_data="admin_recs"),
        types.InlineKeyboardButton("📢 Клиентские рекомендации", callback_data="admin_client_recs"),
        types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        types.InlineKeyboardButton("🚀 Опубликовать отложенные", callback_data="admin_publish_delayed")
    )
    bot.send_message(message.chat.id, "🔧 **Панель администратора**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    cmd = call.data.split('_')[1]
    if cmd == 'apps':
        cursor.execute('''SELECT id, name, service, phone, created_at FROM master_applications WHERE status = 'На проверке' ORDER BY created_at DESC''')
        apps = cursor.fetchall()
        if not apps:
            bot.send_message(call.message.chat.id, "Нет заявок на проверку.")
            return
        for app in apps:
            app_id, name, service, phone, created = app
            text = f"ID: {app_id} | {name} | {service} | {phone} | {created}"
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✅ Одобрить", callback_data=f"app_approve_{app_id}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"app_reject_{app_id}")
            )
            bot.send_message(call.message.chat.id, text, reply_markup=markup)
        bot.answer_callback_query(call.id)
    elif cmd == 'reviews':
        cursor.execute('''SELECT id, master_name, user_name, rating, review_text, created_at
                          FROM reviews WHERE status = 'pending' ORDER BY created_at''')
        revs = cursor.fetchall()
        if not revs:
            bot.send_message(call.message.chat.id, "Нет отзывов на модерации.")
            return
        for rev in revs:
            rev_id, master, user, rating, text, created = rev
            msg = f"ID {rev_id} | {master} | от {user} | {rating}/5\n{text}\n_{created}_"
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✅ Одобрить", callback_data=f"rev_approve_{rev_id}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"rev_reject_{rev_id}")
            )
            bot.send_message(call.message.chat.id, msg, reply_markup=markup)
        bot.answer_callback_query(call.id)
    elif cmd == 'recs':
        cursor.execute('''SELECT id, master_name, service, contact, user_id FROM recommendations WHERE status = 'на модерации' ORDER BY created_at''')
        recs = cursor.fetchall()
        if not recs:
            bot.send_message(call.message.chat.id, "Нет рекомендаций на модерации.")
            return
        for rec in recs:
            rec_id, name, service, contact, recommender_id = rec
            msg = f"ID {rec_id} | {name} | {service} | Контакт: {contact}"
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✅ Принять", callback_data=f"rec_approve_{rec_id}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"rec_reject_{rec_id}")
            )
            bot.send_message(call.message.chat.id, msg, reply_markup=markup)
        bot.answer_callback_query(call.id)
    elif cmd == 'client_recs':
        cursor.execute('''SELECT id, user_id, username, hashtag, contact, description
                          FROM client_recommendations WHERE status = 'new' ORDER BY created_at''')
        recs = cursor.fetchall()
        if not recs:
            bot.send_message(call.message.chat.id, "Нет новых клиентских рекомендаций.")
            return
        for rec in recs:
            rec_id, user_id, username, hashtag, contact, desc = rec
            msg = f"ID {rec_id} | От @{username or 'нет'} | #{hashtag}\nКонтакт: {contact}\nОписание: {desc}"
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✅ Принять", callback_data=f"clientrec_approve_{rec_id}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"clientrec_reject_{rec_id}")
            )
            bot.send_message(call.message.chat.id, msg, reply_markup=markup)
        bot.answer_callback_query(call.id)
    elif cmd == 'stats':
        stats = get_stats()
        bot.send_message(call.message.chat.id, stats, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
    elif cmd == 'publish_delayed':
        publish_delayed_requests()
        bot.send_message(call.message.chat.id, "✅ Отложенные заявки опубликованы.")
        bot.answer_callback_query(call.id)

def get_stats():
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM masters WHERE status = 'активен'")
    active_masters = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM requests WHERE status = 'активна'")
    active_requests = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM reviews WHERE status = 'approved'")
    approved_reviews = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM master_applications WHERE status = 'На проверке'")
    pending_apps = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recommendations WHERE status = 'на модерации'")
    pending_recs = cursor.fetchone()[0]
    return f"""
📊 **СТАТИСТИКА**

👥 Всего пользователей: {total_users}
👷 Активных мастеров: {active_masters}
📋 Активных заявок: {active_requests}
⭐ Одобренных отзывов: {approved_reviews}
⏳ Заявок мастеров на проверке: {pending_apps}
👍 Рекомендаций на модерации: {pending_recs}
    """

# ================ ОБРАБОТКА КЛИЕНТСКИХ РЕКОМЕНДАЦИЙ (ИЗ ЧАТА) ================
@bot.message_handler(commands=['add_from_rec'])
def add_master_from_rec(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    try:
        rec_id = int(message.text.split()[1])
        cursor.execute('SELECT user_id, username, contact, description, hashtag FROM client_recommendations WHERE id = ?', (rec_id,))
        rec = cursor.fetchone()
        if not rec:
            bot.reply_to(message, f"❌ Рекомендация с ID {rec_id} не найдена.")
            return
        user_id, username, contact, desc, hashtag = rec
        name = f"Рекомендация #{rec_id}"
        service = hashtag

        cursor.execute('''INSERT INTO master_applications
                        (user_id, username, name, service, phone, districts,
                         price_min, price_max, experience, bio, portfolio, documents,
                         entity_type, verification_type, source, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (user_id, username, name, service, contact,
                         'Не указано', 'Не указано', 'Не указано',
                         'Не указано', desc, '', 'Не указано',
                         'individual', 'simple', 'recommendation',
                         'На проверке (из рекомендации)',
                         datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()
        app_id = cursor.lastrowid
        bot.reply_to(message, f"✅ Создана анкета мастера (ID {app_id}) из рекомендации. Теперь вы можете отредактировать её командой /approve {app_id} или отклонить /reject.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ================ ОБРАБОТЧИКИ ДЛЯ КЛИЕНТСКИХ РЕКОМЕНДАЦИЙ (АДМИН) ================
@bot.callback_query_handler(func=lambda call: call.data.startswith('clientrec_'))
def clientrec_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    parts = call.data.split('_')
    action = parts[1]
    rec_id = int(parts[2])
    if action == 'approve':
        cursor.execute("UPDATE client_recommendations SET status = 'approved' WHERE id = ?", (rec_id,))
        conn.commit()
        bot.answer_callback_query(call.id, "✅ Рекомендация одобрена")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(call.message.chat.id, f"Рекомендация {rec_id} одобрена. Используйте /add_from_rec {rec_id} для создания анкеты мастера.")
    elif action == 'reject':
        cursor.execute("UPDATE client_recommendations SET status = 'rejected' WHERE id = ?", (rec_id,))
        conn.commit()
        bot.answer_callback_query(call.id, "❌ Рекомендация отклонена")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(call.message.chat.id, f"Рекомендация {rec_id} отклонена.")

# ================ ОБРАБОТЧИКИ ДЛЯ ЗАЯВОК МАСТЕРОВ (АДМИН) ================
@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def app_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    parts = call.data.split('_')
    action = parts[1]
    app_id = int(parts[2])
    if action == 'approve':
        # Здесь можно вызвать approve_master, но проще повторить логику
        cursor.execute('''SELECT user_id, name, service, phone, districts, price_min, price_max,
                          experience, bio, portfolio, documents, entity_type, verification_type,
                          documents_list, payment_methods, preferred_contact, age_group, source
                          FROM master_applications WHERE id = ?''', (app_id,))
        app = cursor.fetchone()
        if not app:
            bot.answer_callback_query(call.id, "❌ Анкета не найдена")
            return
        (user_id, name, service, phone, districts, price_min, price_max,
         experience, bio, portfolio, documents, entity_type, verification_type,
         documents_list, payment_methods, preferred_contact, age_group, source) = app

        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        cursor.execute('''INSERT INTO masters
                        (user_id, name, service, phone, districts, price_min, price_max,
                         experience, bio, portfolio, documents, entity_type, verification_type,
                         documents_list, payment_methods, preferred_contact, age_group,
                         source, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (user_id, name, service, phone, districts, price_min, price_max,
                         experience, bio, portfolio, documents, entity_type, verification_type,
                         documents_list, payment_methods, preferred_contact, age_group,
                         source, 'активен', now))
        conn.commit()
        master_id = cursor.lastrowid
        cursor.execute("DELETE FROM master_applications WHERE id = ?", (app_id,))
        conn.commit()
        try:
            bot.send_message(
                user_id,
                f"✅ Ваша анкета одобрена! Вы добавлены в базу мастеров. Приглашаем в закрытый чат мастеров: {MASTER_CHAT_INVITE_LINK}"
            )
        except:
            pass
        publish_master_card(master_id, name, service, districts, price_min, price_max, experience, bio, portfolio)
        bot.answer_callback_query(call.id, "✅ Одобрено")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(call.message.chat.id, f"Мастер {name} добавлен (ID {master_id}).")
    elif action == 'reject':
        cursor.execute('SELECT user_id FROM master_applications WHERE id = ?', (app_id,))
        row = cursor.fetchone()
        if row:
            user_id = row[0]
            cursor.execute("DELETE FROM master_applications WHERE id = ?", (app_id,))
            conn.commit()
            try:
                bot.send_message(user_id, "❌ Ваша анкета отклонена. Свяжитесь с администратором для уточнения причин.")
            except:
                pass
        bot.answer_callback_query(call.id, "❌ Отклонено")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(call.message.chat.id, f"Анкета {app_id} отклонена.")

# ================ ОБРАБОТЧИКИ ДЛЯ ОТЗЫВОВ (АДМИН) ================
@bot.callback_query_handler(func=lambda call: call.data.startswith('rev_'))
def review_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    parts = call.data.split('_')
    action = parts[1]
    rev_id = int(parts[2])
    if action == 'approve':
        cursor.execute("UPDATE reviews SET status = 'approved' WHERE id = ?", (rev_id,))
        conn.commit()
        # Обновляем рейтинг мастера
        cursor.execute('SELECT master_id, rating FROM reviews WHERE id = ?', (rev_id,))
        master_id, rating = cursor.fetchone()
        cursor.execute('''UPDATE masters SET 
                          rating = (SELECT AVG(rating) FROM reviews WHERE master_id = ? AND status = 'approved'),
                          reviews_count = (SELECT COUNT(*) FROM reviews WHERE master_id = ? AND status = 'approved')
                          WHERE id = ?''', (master_id, master_id, master_id))
        conn.commit()
        bot.answer_callback_query(call.id, "✅ Отзыв одобрен")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    elif action == 'reject':
        cursor.execute("DELETE FROM reviews WHERE id = ?", (rev_id,))
        conn.commit()
        bot.answer_callback_query(call.id, "❌ Отзыв отклонён")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

# ================ ОБРАБОТЧИКИ ДЛЯ РЕКОМЕНДАЦИЙ (АДМИН) ================
@bot.callback_query_handler(func=lambda call: call.data.startswith('rec_'))
def rec_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    parts = call.data.split('_')
    action = parts[1]
    rec_id = int(parts[2])
    if action == 'approve':
        cursor.execute("UPDATE recommendations SET status = 'approved' WHERE id = ?", (rec_id,))
        conn.commit()
        bot.answer_callback_query(call.id, "✅ Рекомендация одобрена")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(call.message.chat.id, f"Рекомендация {rec_id} одобрена. Для создания анкеты используйте данные из неё.")
    elif action == 'reject':
        cursor.execute("DELETE FROM recommendations WHERE id = ?", (rec_id,))
        conn.commit()
        bot.answer_callback_query(call.id, "❌ Рекомендация отклонена")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        # ================ ГРУППОВЫЕ СООБЩЕНИЯ (МОНИТОРИНГ) ================
@bot.message_handler(func=lambda message: message.chat.type in ['group', 'supergroup'], content_types=['text', 'photo', 'video'])
def handle_group_messages(message):
    """Отслеживаем сообщения в чате @remontvl25chat на наличие хештегов и добавляем в рекомендации."""
    if not message.text and not message.caption:
        return
    text = message.text or message.caption or ""
    hashtags = re.findall(r'#(\w+)', text)
    if hashtags:
        # Есть хештеги – добавляем в client_recommendations
        user_id = message.from_user.id
        username = message.from_user.username or ""
        contact = f"https://t.me/{username}" if username else f"ID: {user_id}"
        description = text
        media_file_id = None
        if message.photo:
            media_file_id = message.photo[-1].file_id
        elif message.video:
            media_file_id = message.video.file_id

        # Определяем основной хештег (первый) для категории
        main_hashtag = hashtags[0].lower()
        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        cursor.execute('''INSERT INTO client_recommendations
                        (user_id, username, message_id, hashtag, contact, description, media_file_id, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (user_id, username, message.message_id, main_hashtag, contact, description, media_file_id, 'new', now))
        conn.commit()
        # Можно поставить реакцию или ответить
        try:
            bot.react_to_message(message.chat.id, message.message_id, '👍')
        except:
            pass

    # Также обрабатываем команды в чате (удаляем)
    if message.text and (message.text.startswith('/') or f'@{BOT_USERNAME}' in message.text):
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass

# ================ КОМАНДА ДЛЯ ПОЛУЧЕНИЯ СТАТИСТИКИ ПО РЕКОМЕНДАЦИЯМ В ЧАТЕ ================
@bot.message_handler(commands=['rec_stats'])
def rec_stats(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    cursor.execute('''
        SELECT hashtag, COUNT(*) FROM client_recommendations
        WHERE status IN ('new', 'approved')
        GROUP BY hashtag ORDER BY COUNT(*) DESC
    ''')
    rows = cursor.fetchall()
    if not rows:
        bot.reply_to(message, "Нет данных по рекомендациям.")
        return
    text = "📊 **Статистика рекомендаций по хештегам:**\n"
    for row in rows:
        text += f"#{row[0]}: {row[1]}\n"
    bot.reply_to(message, text, parse_mode='Markdown')

# ================ ОБРАБОТКА НЕИЗВЕСТНЫХ КОМАНД В ЛС ================
@bot.message_handler(func=lambda message: message.chat.type == 'private')
def unknown_private(message):
    if message.text and message.text.startswith('/'):
        bot.reply_to(message, "❌ Неизвестная команда. Введите /start для начала работы.")
    else:
        bot.reply_to(message, "❌ Я не понимаю. Воспользуйтесь кнопками меню.")

# ================ ОБРАБОТКА CALLBACK-ЗАПРОСОВ (если остались необработанные) ================
@bot.callback_query_handler(func=lambda call: True)
def fallback_callback(call):
    bot.answer_callback_query(call.id, "⏳ Функция в разработке или уже неактуальна.")

# ================ ЗАПУСК БОТА ================
if __name__ == '__main__':
    print(f"✅ Бот запущен: @{BOT_USERNAME}")
    # Проверка администраторства в канале и чатах (необязательно, но полезно)
    if CHANNEL_ID:
        check_bot_admin_in_chat(CHANNEL_ID)
    if CHAT_ID and CHAT_ID.startswith('-'):
        check_bot_admin_in_chat(int(CHAT_ID))
    # Сброс вебхука и остановка других экземпляров
    reset_webhook()
    stop_other_instances()
    # Публикация отложенных заявок при запуске (если не ночь)
    publish_delayed_requests()
    # Запуск поллинга
    bot.infinity_polling(skip_pending=True)
