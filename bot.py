import os
import sys
import json
import time
import sqlite3
import requests
import fcntl
import re
from datetime import datetime, timedelta, timezone

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

# ================ НАСТРОЙКИ ================
TOKEN = os.environ.get('TOKEN')
if not TOKEN:
    print("❌ Токен не найден в переменных окружения!")
    sys.exit(1)

BOT_USERNAME = os.environ.get('BOT_USERNAME', 'masterVL25_bot')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', 'masterVL25')
CHANNEL_ID = os.environ.get('CHANNEL_ID', '-1003711282924')
CHAT_ID = os.environ.get('CHAT_ID', "@masterVL25_chat")
ADMIN_ID = int(os.environ.get('ADMIN_ID', '8111497942'))
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'masterVL25_admin')
MASTER_CHAT_ID = os.environ.get('MASTER_CHAT_ID', '@masterVL25_masters')
MASTER_CHAT_INVITE_LINK = os.environ.get('MASTER_CHAT_INVITE_LINK', '')

DB_PATH = os.environ.get('DB_PATH', '/app/data/remont.db')

NIGHT_START_HOUR = int(os.environ.get('NIGHT_START_HOUR', 23))
NIGHT_END_HOUR = int(os.environ.get('NIGHT_END_HOUR', 7))
TIMEZONE_OFFSET = int(os.environ.get('TIMEZONE_OFFSET', 10))

BOT_LINK = f"https://t.me/{BOT_USERNAME}"
CHANNEL_LINK = f"https://t.me/{CHANNEL_USERNAME}"
ADMIN_LINK = f"https://t.me/{ADMIN_USERNAME}"

bot = telebot.TeleBot(TOKEN)

# ================ ПОДГОТОВКА ДИРЕКТОРИИ ДЛЯ БАЗЫ ================
db_dir = os.path.dirname(DB_PATH)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)
    print(f"✅ Создана директория для БД: {db_dir}")

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
                 delayed INTEGER DEFAULT 0,
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

# ----- Таблица мастеров (одна запись – один мастер) -----
cursor.execute('''CREATE TABLE IF NOT EXISTS masters
                (id INTEGER PRIMARY KEY,
                 user_id INTEGER UNIQUE,
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
                 user_id INTEGER UNIQUE,
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
                 created_at TEXT,
                 updated_at TEXT)''')

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

# ================ АВТОМАТИЧЕСКОЕ ДОБАВЛЕНИЕ НЕДОСТАЮЩИХ КОЛОНОК ================
def add_column_if_not_exists(table, column, col_type):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        print(f"✅ Колонка {column} добавлена в {table}")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print(f"ℹ️ Колонка {column} уже существует в {table}")
        else:
            print(f"⚠️ Ошибка при добавлении {column} в {table}: {e}")

# Проверка для master_applications
add_column_if_not_exists('master_applications', 'verification_type', "TEXT DEFAULT 'simple'")
add_column_if_not_exists('master_applications', 'documents_list', "TEXT DEFAULT ''")
add_column_if_not_exists('master_applications', 'payment_methods', "TEXT DEFAULT ''")
add_column_if_not_exists('master_applications', 'preferred_contact', "TEXT DEFAULT 'telegram'")
add_column_if_not_exists('master_applications', 'age_group', "TEXT DEFAULT ''")

# Проверка для masters
add_column_if_not_exists('masters', 'documents', "TEXT DEFAULT ''")
add_column_if_not_exists('masters', 'documents_list', "TEXT DEFAULT ''")
add_column_if_not_exists('masters', 'payment_methods', "TEXT DEFAULT ''")
add_column_if_not_exists('masters', 'preferred_contact', "TEXT DEFAULT 'telegram'")
add_column_if_not_exists('masters', 'age_group', "TEXT DEFAULT ''")
add_column_if_not_exists('masters', 'documents_verified', "INTEGER DEFAULT 0")
add_column_if_not_exists('masters', 'photos_verified', "INTEGER DEFAULT 0")
add_column_if_not_exists('masters', 'reviews_verified', "INTEGER DEFAULT 0")

# Проверка для responses (добавляем updated_at, если нет)
add_column_if_not_exists('responses', 'updated_at', "TEXT DEFAULT ''")

conn.commit()

# ================ СПИСКИ ДЛЯ ВЫБОРА ================

PROFILES = [
    ("plumber", "Сантехник"),
    ("electrician", "Электрик"),
    ("finisher", "Отделочник"),
    ("builder", "Строитель"),
    ("welder", "Сварщик"),
    ("handyman", "Разнорабочий"),
    ("other", "Другое"),
    ("designer", "Дизайнер интерьера"),
    ("full", "Полный комплекс")
]
PROFILES_DICT = {code: name for code, name in PROFILES}

DISTRICTS = [
    ("center", "Центр"),
    ("sneg", "Снеговая Падь"),
    ("pervorech", "Первореченский (Гоголя, Толстого, ДальПресс)"),
    ("sovetsky", "Советский район (100-летие, Вторая речка, Заря, Варяг)"),
    ("pervomay", "Первомайский район (Луговая, Окатовая, Тихая, Патрокл)"),
    ("frunze", "Фрунзенский район (Эгершельд, Маяк)")
]
DISTRICTS_DICT = {code: name for code, name in DISTRICTS}

DOC_TYPES = [
    ("contract", "Договор"),
    ("act", "Акт выполненных работ"),
    ("check", "Чек"),
    ("invoice", "Счёт"),
    ("ip", "Свидетельство ИП"),
    ("selfemployed", "Самозанятость"),
    ("passport", "Паспорт (для проверки)")
]
DOC_TYPES_DICT = {code: name for code, name in DOC_TYPES}

PAYMENT_METHODS = [
    ("cash", "Наличные"),
    ("transfer", "Перевод на карту"),
    ("account", "Расчётный счёт")
]
PAYMENT_DICT = {code: name for code, name in PAYMENT_METHODS}

EXPERIENCE_OPTIONS = [
    ("less1", "Менее 1 года"),
    ("1-3", "1–3 года"),
    ("3-5", "3–5 лет"),
    ("5-10", "5–10 лет"),
    ("more10", "Более 10 лет"),
    ("custom", "Свой вариант (ввести текст)")
]
EXPERIENCE_DICT = {code: name for code, name in EXPERIENCE_OPTIONS}

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
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
        print("✅ Webhook сброшен")
    except Exception as e:
        print(f"⚠️ Ошибка сброса вебхука: {e}")

def stop_other_instances():
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset=-1&timeout=0")
        print("✅ Другие экземпляры остановлены")
    except Exception as e:
        print(f"⚠️ Ошибка остановки других экземпляров: {e}")

def is_night_time():
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    local_time = now_utc + timedelta(hours=TIMEZONE_OFFSET)
    hour = local_time.hour
    if NIGHT_START_HOUR > NIGHT_END_HOUR:
        return hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR
    else:
        return NIGHT_START_HOUR <= hour < NIGHT_END_HOUR

def publish_delayed_requests():
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
🔨 **Профиль:** {service}
📝 **Задача:** {desc}
📍 **Район/ЖК:** {district}
📅 **Когда:** {date}
💰 **Бюджет:** {budget}
📢 Публичная заявка. Мастера, откликайтесь в боте!
        """
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📞 Откликнуться", callback_data=f"channel_respond_{req_id}"))
        try:
            sent = bot.send_message(CHANNEL_ID, text, reply_markup=markup)
            cursor.execute("UPDATE requests SET delayed = 0, chat_message_id = ? WHERE id = ?", (sent.message_id, req_id))
            conn.commit()
        except Exception as e:
            print(f"Ошибка публикации отложенной заявки {req_id}: {e}")

def get_master_status(user_id):
    print(f"DEBUG get_master_status: user_id={user_id}")
    cursor.execute("SELECT status FROM masters WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        print(f"DEBUG: найден в masters со статусом {row[0]}")
        return ('active', row[0])
    cursor.execute("SELECT status FROM master_applications WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        print(f"DEBUG: найден в master_applications со статусом {row[0]}")
        return ('pending', row[0])
    print("DEBUG: статус не найден")
    return (None, None)

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

# ================ УДАЛЕНИЕ КОМАНД В ЧАТЕ ================
@bot.message_handler(func=lambda message: message.chat.type != 'private')
def delete_group_commands(message):
    if message.text and (message.text.startswith('/') or f'@{BOT_USERNAME}' in message.text):
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
# ================ МЕНЮ ПО РОЛИ (С УЧЁТОМ СТАТУСА МАСТЕРА) ================
def show_role_menu(message, role):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)

    if role == 'client':
        markup.row('🔨 Оставить заявку', '🔍 Найти мастера')
        markup.row('⭐ Оставить отзыв', '👍 Рекомендовать мастера')
        markup.row('📢 Канал с мастерами', '📋 Мои заявки')
        markup.row('🔄 Сменить роль')
        text = "👋 **Режим: Клиент**\n\n• Ищете мастера? Оставьте заявку или выберите из каталога.\n• Понравился мастер? Оставьте отзыв.\n• Знаете хорошего специалиста? Порекомендуйте его!"

    elif role == 'master':
        status_type, status_text = get_master_status(user_id)
        if status_type == 'active':
            markup.row('👤 Моя анкета', '🔔 Заявки по моему профилю')
            markup.row('✉️ Написать админу')
            if user_id == ADMIN_ID:
                markup.row('👑 Админ-панель')
            markup.row('🔄 Сменить роль')
            text = "👋 **Режим: Мастер**\n\n✅ Вы активны. Все публичные заявки публикуются в канале. Здесь вы можете:\n• Посмотреть и редактировать свою анкету.\n• Получить список заявок, подходящих под ваш профиль и районы."
            markup.row('👤 Моя анкета', '❌ Отозвать анкету')
            markup.row('📢 Канал с мастерами', '✉️ Написать админу')
            if user_id == ADMIN_ID:
                markup.row('👑 Админ-панель')
            markup.row('🔄 Сменить роль')
            text = "👋 **Режим: Мастер**\n\n⏳ Ваша анкета на проверке. Вы можете отозвать её или написать администратору."
        else:
            markup.row('👷 Заполнить анкету', '📢 Канал с мастерами')
            markup.row('✉️ Написать админу')
            if user_id == ADMIN_ID:
                markup.row('👑 Админ-панель')
            markup.row('🔄 Сменить роль')
            text = "👋 **Режим: Мастер**\n\nУ вас ещё нет анкеты. Заполните её, чтобы получать заказы."

    elif role == 'guest':
        markup.row('🔍 Найти мастера', '📢 Канал с мастерами')
        markup.row('👷 Зарегистрироваться как мастер')
        markup.row('🔄 Сменить роль')
        text = "👋 **Режим: Гость**\n\n• Вы можете просматривать заявки в канале и искать мастеров.\n• Чтобы участвовать активнее, зарегистрируйтесь как клиент или мастер."
    else:
        markup.row('🔨 Оставить заявку', '🔍 Найти мастера')
        markup.row('📢 Канал с мастерами')
        markup.row('🔄 Сменить роль')
        text = "👋 Добро пожаловать!"

    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='Markdown')

# ================ СТАРТ / ВЫБОР РОЛИ ================
@bot.message_handler(commands=['start'])
def start(message):
    print(f"DEBUG: start вызван от user {message.from_user.id}")
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
            "👇 Для работы со мной перейдите в личные сообщения:\n"
            f"👉 @{BOT_USERNAME}\n\n"
            "Там вы сможете:\n"
            "✅ Оставить заявку\n"
            "✅ Найти мастера в каталоге\n"
            "✅ Стать мастером и добавить анкету\n"
            "✅ Управлять своими заявками и анкетами",
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
        st, _ = get_master_status(user_id)
        if st is not None:
            bot.edit_message_text("❌ Вы уже зарегистрированы как мастер. Используйте меню для управления анкетой.",
                                  call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id)
            return
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
    st, _ = get_master_status(user_id)
    if st is not None:
        bot.send_message(message.chat.id, "❌ Вы уже зарегистрированы как мастер. Используйте меню.")
        return
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('UPDATE users SET role = ?, last_active = ? WHERE user_id = ?', ('master', now, user_id))
    conn.commit()
    bot.send_message(message.chat.id, "✅ Теперь вы – мастер. Заполните анкету для получения заказов.")
    become_master(message, 'simple')

# ================ АНКЕТА МАСТЕРА (полная) ================
if not hasattr(bot, 'master_data'):
    bot.master_data = {}

def become_master(message, verif_type='simple'):
    if not only_private(message):
        return
    user_id = message.from_user.id
    st, _ = get_master_status(user_id)
    if st is not None:
        bot.send_message(message.chat.id, "❌ У вас уже есть анкета. Используйте меню для управления.")
        return

    if user_id in bot.master_data:
        del bot.master_data[user_id]
        bot.master_data[user_id] = {'verification_type': verif_type, 'portfolio': 'Не указано'}

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👤 Частное лицо", callback_data="entity_individual"),
        types.InlineKeyboardButton("🏢 Компания / ИП", callback_data="entity_company")
    )
    bot.send_message(
        message.chat.id,
        "👷 **ЗАПОЛНЕНИЕ АНКЕТЫ МАСТЕРА**\n\n"
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
        question = "👤 **ВВЕДИТЕ ВАШЕ ПОЛНОЕ ИМЯ (как в документах):**"
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
    if user_id not in bot.master_data:
        bot.master_data[user_id] = {}
    bot.master_data[user_id]['name'] = name

    # Шаг 3 – возраст
    ask_age(message.chat.id, user_id)

def ask_age(chat_id, user_id):
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
        "🎂 **Шаг 3 из 16**\n\n"
        "Укажите ваш возраст (необязательно). Это поможет клиентам лучше узнать вас.",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('age_'))
def age_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Начните анкету заново")
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
    # Шаг 4 – выбор профилей
    ask_profiles_multiple(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)

def ask_profiles_multiple(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    if 'selected_profiles' not in bot.master_data[user_id]:
        bot.master_data[user_id]['selected_profiles'] = []
    selected = bot.master_data[user_id]['selected_profiles']
    for code, name in PROFILES:
        prefix = "✅ " if name in selected else ""
        markup.add(types.InlineKeyboardButton(
            f"{prefix}{name}",
            callback_data=f"prof_{code}"
        ))
    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="prof_done"))
    bot.send_message(
        chat_id,
        "👷 **Шаг 4 из 16**\n\n"
        "Выберите **профили**, по которым вы работаете (можно несколько). "
        "Именно по ним будут приходить заявки от клиентов.\n\n"
        "⚠️ Вы можете заполнить только одну анкету. Позже её можно будет редактировать или отозвать.",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('prof_'))
def profile_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Начните анкету заново")
        return
    data = call.data[5:]  # убираем 'prof_'
    if data == "done":
        selected = bot.master_data[user_id].get('selected_profiles', [])
        if not selected:
            bot.answer_callback_query(call.id, "❌ Выберите хотя бы один профиль")
            return
        bot.master_data[user_id]['profiles'] = ", ".join(selected)
        bot.master_data[user_id]['service'] = selected[0]
        bot.master_data[user_id]['services'] = ", ".join(selected)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        # Шаг 5 – опыт
        ask_experience(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id, "✅ Профили сохранены")
    else:
        profile_name = PROFILES_DICT.get(data)
        if not profile_name:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        selected = bot.master_data[user_id].get('selected_profiles', [])
        if profile_name in selected:
            selected.remove(profile_name)
        else:
            selected.append(profile_name)
        bot.master_data[user_id]['selected_profiles'] = selected
        ask_profiles_multiple(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)

def ask_experience(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for code, name in EXPERIENCE_OPTIONS:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"exp_{code}"))
    bot.send_message(
        chat_id,
        "⏱️ **Шаг 5 из 16**\n\nВыберите ваш опыт работы:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('exp_'))
def experience_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Начните анкету заново")
        return
    code = call.data[4:]
    if code == "custom":
        bot.edit_message_text(
            "⏱️ Введите ваш опыт работы текстом:",
            call.message.chat.id,
            call.message.message_id
        )
        bot.register_next_step_handler(call.message, process_custom_experience, user_id)
        bot.answer_callback_query(call.id)
    else:
        exp_map = {k: v for k, v in EXPERIENCE_OPTIONS if k != "custom"}
        bot.master_data[user_id]['experience'] = exp_map[code]
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        # Шаг 6 – районы
        ask_districts_multiple(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)

def process_custom_experience(message, user_id):
    exp = safe_text(message)
    if not exp:
        bot.send_message(message.chat.id, "❌ Введите опыт.")
        return
    bot.master_data[user_id]['experience'] = exp
    ask_districts_multiple(message.chat.id, user_id)

def ask_districts_multiple(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    if 'selected_districts' not in bot.master_data[user_id]:
        bot.master_data[user_id]['selected_districts'] = []
    selected = bot.master_data[user_id]['selected_districts']
    for code, name in DISTRICTS:
        prefix = "✅ " if name in selected else ""
        markup.add(types.InlineKeyboardButton(
            f"{prefix}{name}",
            callback_data=f"dist_{code}"
        ))
    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="dist_done"))
    bot.send_message(
        chat_id,
        "📍 **Шаг 6 из 16**\n\n**Выберите районы работы** (можно несколько):",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('dist_'))
def district_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Начните анкету заново")
        return
    data = call.data[5:]  # убираем 'dist_'
    if data == "done":
        selected = bot.master_data[user_id].get('selected_districts', [])
        if not selected:
            bot.answer_callback_query(call.id, "❌ Выберите хотя бы один район")
            return
        bot.master_data[user_id]['districts'] = ", ".join(selected)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        # Шаг 7 – цена
        bot.send_message(
            call.message.chat.id,
            "💰 **Шаг 7 из 16**\n\n"
            "Введите **минимальную цену заказа** (например: 1000₽, договорная):"
        )
        bot.register_next_step_handler(call.message, process_master_price_min)
        bot.answer_callback_query(call.id, "✅ Районы сохранены")
    else:
        district_name = DISTRICTS_DICT.get(data)
        if not district_name:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        selected = bot.master_data[user_id].get('selected_districts', [])
        if district_name in selected:
            selected.remove(district_name)
        else:
            selected.append(district_name)
        bot.master_data[user_id]['selected_districts'] = selected
        ask_districts_multiple(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)

def process_master_price_min(message):
    if message.chat.type != 'private':
        return
    price_min = safe_text(message)
    if not price_min:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите минимальную цену.")
        return
    user_id = message.from_user.id
    bot.master_data[user_id]['price_min'] = price_min
    bot.master_data[user_id]['price_max'] = ''
    # Шаг 8 – способы оплаты
    ask_payment_methods(message.chat.id, user_id)

def ask_payment_methods(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    if 'selected_payments' not in bot.master_data[user_id]:
        bot.master_data[user_id]['selected_payments'] = []
    selected = bot.master_data[user_id]['selected_payments']
    for code, name in PAYMENT_METHODS:
        prefix = "✅ " if name in selected else ""
        markup.add(types.InlineKeyboardButton(
            f"{prefix}{name}",
            callback_data=f"pay_{code}"
        ))
    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="pay_done"))
    bot.send_message(
        chat_id,
        "💳 **Шаг 8 из 16**\n\n"
        "Какие способы оплаты вы принимаете? (можно несколько)",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
def payment_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Начните анкету заново")
        return
    data = call.data[4:]  # убираем 'pay_'
    if data == "done":
        selected = bot.master_data[user_id].get('selected_payments', [])
        bot.master_data[user_id]['payment_methods'] = ", ".join(selected)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        # Шаг 9 – био
        ask_bio(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id, "✅ Способы оплаты сохранены")
    else:
        pay_name = PAYMENT_DICT.get(data)
        if not pay_name:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        selected = bot.master_data[user_id].get('selected_payments', [])
        if pay_name in selected:
            selected.remove(pay_name)
        else:
            selected.append(pay_name)
        bot.master_data[user_id]['selected_payments'] = selected
        ask_payment_methods(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)
def ask_bio(chat_id, user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="skip_bio"))
    bot.send_message(
        chat_id,
        "📝 **Шаг 9 из 16**\n\n"
        "👇 **КОММЕНТАРИЙ О СЕБЕ (кратко):**\n\n"
        "Расскажите о себе пару слов: опыт, подход к работе.\n"
        "Это увидят клиенты в вашей карточке.\n\n"
        "👉 **Или нажмите «Пропустить»**",
        reply_markup=markup
    )
    bot.register_next_step_handler_by_chat_id(chat_id, process_master_bio, user_id)

@bot.callback_query_handler(func=lambda call: call.data == 'skip_bio')
def skip_bio_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Начните анкету заново")
        return
    bot.master_data[user_id]['bio'] = "Не указано"
    ask_portfolio(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id, "⏩ Пропущено")

def process_master_bio(message, user_id):
    if message.chat.type != 'private':
        return
    bio = safe_text(message)
    if not bio or bio.lower() == "пропустить":
        bio = "Не указано"
    bot.master_data[user_id]['bio'] = bio
    ask_portfolio(message.chat.id, user_id)

def ask_portfolio(chat_id, user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="skip_portfolio"))
    markup.add(types.InlineKeyboardButton("❓ Как загрузить фото?", callback_data="help_portfolio"))
    if bot.master_data[user_id].get('verification_type') != 'simple':
        markup.add(types.InlineKeyboardButton("📤 Отправить фото админу", callback_data="portfolio_send_to_admin"))
    bot.send_message(
        chat_id,
        "📸 **Шаг 10 из 16**\n\n"
        "👇 **ОТПРАВЬТЕ ССЫЛКУ НА ПОРТФОЛИО:**\n\n"
        "Это может быть ссылка на Яндекс.Диск, Google Фото, Telegram-канал с работами.\n"
        "Если у вас нет ссылки, вы можете отправить фото администратору – он создаст ссылку.\n\n"
        "👉 **Или нажмите кнопку**",
        reply_markup=markup
    )
    bot.register_next_step_handler_by_chat_id(chat_id, process_master_portfolio_text, user_id)

@bot.callback_query_handler(func=lambda call: call.data == 'help_portfolio')
def help_portfolio_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "📸 **Как загрузить фото в портфолио:**\n\n"
        "1. Отправьте фото администратору в личные сообщения – нажмите кнопку ниже.\n"
        "2. После получения фото администратор создаст для вас ссылку.\n"
        "3. Скопируйте полученную ссылку и отправьте её в это поле.\n\n"
        "Или вы можете самостоятельно загрузить фото на Яндекс.Диск или Google Фото и поделиться ссылкой."
    )

@bot.callback_query_handler(func=lambda call: call.data == 'skip_portfolio')
def skip_portfolio_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Начните анкету заново")
        return
    bot.master_data[user_id]['portfolio'] = "Не указано"
    show_documents_buttons(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id, "⏩ Пропущено")

@bot.callback_query_handler(func=lambda call: call.data == 'portfolio_send_to_admin')
def portfolio_send_to_admin_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.master_data[user_id] = {}
    bot.master_data[user_id]['send_portfolio_later'] = True
    bot.answer_callback_query(call.id, "✅ Вы сможете отправить фото после заполнения анкеты.")
    show_documents_buttons(call.message.chat.id, user_id)

def process_master_portfolio_text(message, user_id):
    if message.chat.type != 'private':
        return
    portfolio = safe_text(message)
    if not portfolio or portfolio.lower() == "пропустить":
        portfolio = "Не указано"
    bot.master_data[user_id]['portfolio'] = portfolio
    show_documents_buttons(message.chat.id, user_id)

def show_documents_buttons(chat_id, user_id):
    if bot.master_data[user_id].get('verification_type') == 'simple':
        # Для упрощённой регистрации пропускаем документы
        ask_contact_methods(chat_id, user_id)
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Да, предоставляю", callback_data="doc_yes"),
        types.InlineKeyboardButton("❌ Нет, не предоставляю", callback_data="doc_no")
    )
    bot.send_message(
        chat_id,
        "📄 **Шаг 11 из 16**\n\n"
        "Предоставляете ли вы при работе какие-либо документы (договор, акт, чек и т.п.)?",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('doc_'))
def documents_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Начните анкету заново")
        return
    choice = call.data.split('_')[1]
    if choice == 'yes':
        bot.master_data[user_id]['documents'] = "Есть"
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        ask_doc_types_multiple(call.message.chat.id, user_id)   # переход к выбору конкретных документов
    else:  # 'no'
        bot.master_data[user_id]['documents'] = "Нет"
        bot.master_data[user_id]['documents_list'] = ""
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        ask_contact_methods(call.message.chat.id, user_id)      # сразу к контактам
    bot.answer_callback_query(call.id)

def ask_doc_types_multiple(chat_id, user_id):
    if 'selected_docs' not in bot.master_data[user_id]:
        bot.master_data[user_id]['selected_docs'] = []
    selected = bot.master_data[user_id]['selected_docs']
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for code, name in DOC_TYPES:
        prefix = "✅ " if name in selected else ""
        markup.add(types.InlineKeyboardButton(
            f"{prefix}{name}",
            callback_data=f"doc_type_{code}"
        ))
    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="doc_type_done"))
    
    if 'doc_message_id' in bot.master_data[user_id]:
        try:
            bot.edit_message_reply_markup(
                chat_id,
                bot.master_data[user_id]['doc_message_id'],
                reply_markup=markup
            )
            return
        except:
            pass
    
    sent = bot.send_message(
        chat_id,
        "📄 **Шаг 12 из 16**\n\n"
        "Какие именно документы вы можете предоставить? (можно выбрать несколько):",
        reply_markup=markup
    )
    bot.master_data[user_id]['doc_message_id'] = sent.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('doc_type_'))
def doc_type_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Начните анкету заново")
        return
    data = call.data[9:]  # убираем 'doc_type_'
    
    if data == "done":
        selected = bot.master_data[user_id].get('selected_docs', [])
        bot.master_data[user_id]['documents_list'] = ", ".join(selected)
        if 'doc_message_id' in bot.master_data[user_id]:
            del bot.master_data[user_id]['doc_message_id']
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
        ask_documents_verification(call.message, user_id)   # переход к вопросу о проверке
        bot.answer_callback_query(call.id, "✅ Список документов сохранён")
    else:
        doc_name = DOC_TYPES_DICT.get(data)
        if not doc_name:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        selected = bot.master_data[user_id].get('selected_docs', [])
        if doc_name in selected:
            selected.remove(doc_name)
        else:
            selected.append(doc_name)
        bot.master_data[user_id]['selected_docs'] = selected
        ask_doc_types_multiple(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)

def ask_documents_verification(message, user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Да, готов", callback_data="verify_yes"),
        types.InlineKeyboardButton("❌ Нет, не готов", callback_data="verify_no")
    )
    bot.send_message(
        message.chat.id,
        "🛡️ **Шаг 13 из 16**\n\n"
        "Готовы ли вы пройти проверку этих документов (предоставить фото/скан администратору)?",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('verify_'))
def verify_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Начните анкету заново")
        return
    if call.data == 'verify_yes':
        bot.master_data[user_id]['documents_verified'] = 'pending'
    else:
        bot.master_data[user_id]['documents_verified'] = 'no'
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    ask_contact_methods(call.message.chat.id, user_id)   # переход к контактам
    bot.answer_callback_query(call.id)

def ask_contact_methods(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    if 'selected_contacts' not in bot.master_data[user_id]:
        bot.master_data[user_id]['selected_contacts'] = []
    selected = bot.master_data[user_id]['selected_contacts']
    for code, name in [("telegram", "Telegram"), ("whatsapp", "WhatsApp"), ("phone", "Телефонный звонок")]:
        prefix = "✅ " if name in selected else ""
        markup.add(types.InlineKeyboardButton(
            f"{prefix}{name}",
            callback_data=f"contact_{code}"
        ))
    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="contact_done"))
    bot.send_message(
        chat_id,
        "📞 **Шаг 14 из 16**\n\n"
        "Выберите предпочтительные способы связи (можно несколько):",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('contact_'))
def contact_callback(call):
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Начните анкету заново")
        return
    data = call.data[8:]  # убираем 'contact_'
    if data == "done":
        selected = bot.master_data[user_id].get('selected_contacts', [])
        if not selected:
            bot.answer_callback_query(call.id, "❌ Выберите хотя бы один способ связи")
            return
        bot.master_data[user_id]['preferred_contact'] = ", ".join(selected)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        # Шаг 15 – телефон
        ask_phone_after_contacts(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id, "✅ Способы связи сохранены")
    else:
        contact_names = {"telegram": "Telegram", "whatsapp": "WhatsApp", "phone": "Телефонный звонок"}
        contact_name = contact_names.get(data)
        if not contact_name:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        selected = bot.master_data[user_id].get('selected_contacts', [])
        if contact_name in selected:
            selected.remove(contact_name)
        else:
            selected.append(contact_name)
        bot.master_data[user_id]['selected_contacts'] = selected
        ask_contact_methods(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)

def ask_phone_after_contacts(chat_id, user_id):
    bot.send_message(
        chat_id,
        "📞 **Шаг 15 из 16**\n\n"
        "Введите ваш телефон (будет виден только администратору):"
    )
    bot.register_next_step_handler_by_chat_id(chat_id, process_master_phone_final, user_id)

def process_master_phone_final(message, user_id):
    if message.chat.type != 'private':
        return
    phone = safe_text(message)
    if not phone:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите телефон.")
        bot.register_next_step_handler(message, process_master_phone_final, user_id)
        return
    bot.master_data[user_id]['phone'] = phone
    show_summary(message, user_id)

def show_summary(message, user_id):
    data = bot.master_data[user_id]
    summary = f"""
    if 'portfolio' not in data:
        data['portfolio'] = 'Не указано'    
📋 **Сводка анкеты:**

👤 **Имя/Название:** {data['name']}
🔧 **Профили:** {data.get('profiles', data.get('services', ''))}
🎂 **Возраст:** {data.get('age_group', 'Не указан')}
⏱ **Опыт:** {data['experience']}
📍 **Районы:** {data['districts']}
💰 **Минимальная цена:** {data['price_min']}
💳 **Оплата:** {data.get('payment_methods', 'Не указано')}
💬 **О себе:** {data.get('bio', 'Не указано')}
📸 **Портфолио:** {data.get('portfolio', 'Не указано')}
📄 **Документы:** {data.get('documents', 'Не указано')}
   **Список:** {data.get('documents_list', '')}
🛡️ **Готовность к проверке:** {'✅ Да' if data.get('documents_verified')=='pending' else '❌ Нет'}
📞 **Предпочтительный контакт:** {data.get('preferred_contact', 'telegram')}
📞 **Телефон:** {data['phone']}
    """
    markup = types.InlineKeyboardMarkup(row_width=2)
    if data.get('verification_type') == 'simple':
        btn_text = "✅ Добавить анкету в базу мастеров"
    else:
        btn_text = "✅ Отправить на модерацию"
    markup.add(
        types.InlineKeyboardButton(btn_text, callback_data=f"save_app_{user_id}"),
        types.InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_summary_{user_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_app")
    )
    bot.send_message(message.chat.id, summary, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_summary_'))
def edit_summary_callback(call):
    user_id = int(call.data.split('_')[2])
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша анкета")
        return
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Данные не найдены")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    fields = [
        ("name", "Имя"),
        ("profiles", "Профили (через запятую)"),
        ("age_group", "Возраст"),
        ("experience", "Опыт"),
        ("districts", "Районы (через запятую)"),
        ("price_min", "Минимальная цена"),
        ("payment_methods", "Способы оплаты (через запятую)"),
        ("bio", "О себе"),
        ("portfolio", "Портфолио (ссылка)"),
        ("documents", "Используете документы? (Есть/Нет/Пропустить)"),
        ("documents_list", "Список документов (через запятую)"),
        ("documents_verified", "Готовы к проверке? (pending/no)"),
        ("preferred_contact", "Предпочтительный контакт (через запятую)"),
        ("phone", "Телефон")
    ]
    for key, label in fields:
        markup.add(types.InlineKeyboardButton(label, callback_data=f"edit_field_{key}_{user_id}"))
    bot.edit_message_text(
        "✏️ **Выберите поле для редактирования:**",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_field_'))
def edit_field_callback(call):
    data = call.data
    prefix = "edit_field_"
    if not data.startswith(prefix):
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    rest = data[len(prefix):]
    last_underscore = rest.rfind('_')
    if last_underscore == -1:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    field = rest[:last_underscore]
    user_id_str = rest[last_underscore+1:]
    try:
        user_id = int(user_id_str)
    except ValueError:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша анкета")
        return
    if user_id not in bot.master_data:
        bot.answer_callback_query(call.id, "❌ Данные не найдены")
        return
    bot.edit_message_text(
        f"✏️ Введите новое значение для поля **{field}**:",
        call.message.chat.id,
        call.message.message_id
    )
    bot.register_next_step_handler(call.message, process_edit_field_value, field, user_id)
    bot.answer_callback_query(call.id)

def process_edit_field_value(message, field, user_id):
    value = safe_text(message)
    if not value:
        bot.send_message(message.chat.id, "❌ Значение не может быть пустым.")
        show_summary(message, user_id)
        return
    if field == "profiles":
        bot.master_data[user_id]['profiles'] = value
        bot.master_data[user_id]['services'] = value
        bot.master_data[user_id]['service'] = value.split(',')[0].strip()
    else:
        bot.master_data[user_id][field] = value
    bot.send_message(message.chat.id, f"✅ Поле {field} обновлено.")
    show_summary(message, user_id)

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_app')
def cancel_app_callback(call):
    user_id = call.from_user.id
    if user_id in bot.master_data:
        del bot.master_data[user_id]
    bot.edit_message_text("❌ Создание анкеты отменено.", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

# ================ СОХРАНЕНИЕ АНКЕТЫ (в БД) ================
def save_master_application(message, user_id, user_data):
    if 'verification_type' not in user_data:
        user_data['verification_type'] = 'simple'
        print(f"⚠️ verification_type отсутствовал, установлен 'simple' для user {user_id}")

    required_keys = ['verification_type', 'name', 'phone', 'districts', 'price_min', 'experience']
    missing = [key for key in required_keys if key not in user_data]
    if missing:
        bot.send_message(message.chat.id, f"❌ Отсутствуют данные: {', '.join(missing)}. Пожалуйста, начните анкету заново.")
        print(f"DEBUG: missing keys for user {user_id}: {missing}")
        return

    name = user_data['name']
    services_str = user_data.get('services', user_data.get('profiles', ''))
    service = services_str.split(',')[0].strip()
    phone = user_data['phone']
    districts = user_data['districts']
    price_min = user_data['price_min']
    price_max = user_data.get('price_max', '')
    experience = user_data['experience']
    bio = user_data.get('bio', 'Не указано')
    portfolio = user_data.get('portfolio', 'Не указано')
    documents = user_data.get('documents', 'Не указано')
    entity_type = user_data.get('entity_type', 'individual')
    verification_type = user_data['verification_type']
    documents_list = user_data.get('documents_list', '')
    payment_methods = user_data.get('payment_methods', '')
    preferred_contact = user_data.get('preferred_contact', 'telegram')
    age_group = user_data.get('age_group', '')

    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    if verification_type == 'simple':
        # Упрощённая регистрация – сразу в masters
        cursor.execute('''INSERT INTO masters
                        (user_id, name, service, phone, districts, price_min, price_max,
                         experience, bio, portfolio, documents, entity_type, verification_type,
                         documents_list, payment_methods, preferred_contact, age_group,
                         source, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (user_id, name, service, phone, districts, price_min, price_max,
                         experience, bio, portfolio, documents, entity_type, verification_type,
                         documents_list, payment_methods, preferred_contact, age_group,
                         'bot', 'активен', now))
        conn.commit()
        master_id = cursor.lastrowid
        print(f"DEBUG: Упрощённая регистрация, мастер ID={master_id}, user_id={user_id}")

        bot.send_message(
            message.chat.id,
            "✅ **Упрощённая регистрация завершена!**\n\n"
            "Вы добавлены в базу мастеров. Теперь клиенты смогут находить вас в каталоге.\n"
            "⚠️ Вы **не будете получать уведомления** о новых заявках, так как выбрали упрощённый режим.\n"
            "Чтобы начать получать заказы, пройдите полную регистрацию с проверкой документов."
        )
        if MASTER_CHAT_INVITE_LINK:
            bot.send_message(message.chat.id, f"Приглашаем в закрытый чат мастеров: {MASTER_CHAT_INVITE_LINK}")
        return master_id
    else:
        # Полная регистрация – в master_applications на модерацию
        cursor.execute('''INSERT INTO master_applications
                        (user_id, username, name, service, phone, districts, 
                         price_min, price_max, experience, bio, portfolio, documents,
                         entity_type, verification_type, source, documents_list, payment_methods, preferred_contact, age_group, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (user_id,
                         message.from_user.username or "no_username",
                         name, services_str, phone, districts,
                         price_min, price_max, experience, bio, portfolio, documents,
                         entity_type, verification_type, 'bot',
                         documents_list, payment_methods, preferred_contact, age_group,
                         'На проверке', now))
        conn.commit()
        application_id = cursor.lastrowid
        print(f"DEBUG: Полная регистрация, заявка ID={application_id}, user_id={user_id}")

        # Уведомление админу с кнопкой связи
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📩 Связаться с мастером", url=f"tg://user?id={user_id}"))
        admin_msg = f"""
🆕 **НОВАЯ АНКЕТА МАСТЕРА!** (ID: {application_id})
📱 **Источник:** Бот
👤 **Telegram:** @{message.from_user.username or "нет"} (ID {user_id})

👤 Имя: {name}
🔧 Профили: {services_str}
📞 Телефон: {phone}
📍 Районы: {districts}
💰 Мин. цена: {price_min}
⏱ Опыт: {experience}
💬 О себе: {bio}
📸 Портфолио: {portfolio}
🎂 Возраст: {age_group}
📄 Документы: {documents}
📋 Список документов: {documents_list}
🛡️ Готов к проверке: {'✅ Да' if user_data.get('documents_verified')=='pending' else '❌ Нет'}
💳 Оплата: {payment_methods}
📞 Контакт: {preferred_contact}
Статус: На проверке

✅ Одобрить: /approve {application_id}
❌ Отклонить: /reject {application_id} [причина]
        """
        try:
            if ADMIN_ID != 0:
                bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup)
        except Exception as e:
            print(f"Ошибка отправки админу: {e}")

        bot.send_message(
            message.chat.id,
            "✅ **Ваша анкета отправлена на модерацию!**\n\n"
            "Администратор проверит данные (обычно 1-2 дня). После одобрения вы попадёте в базу мастеров и будете получать уведомления о заявках."
        )
        return application_id
# ================ ОБРАБОТЧИК СОХРАНЕНИЯ (СВОДКА) ================
@bot.callback_query_handler(func=lambda call: call.data.startswith('save_app_'))
def save_app_callback(call):
    user_id = int(call.data.split('_')[2])
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша анкета")
        return
    user_data = bot.master_data.get(user_id)
    if not user_data:
        bot.answer_callback_query(call.id, "❌ Данные не найдены")
        return
    try:
        app_id = save_master_application(call.message, user_id, user_data)
        bot.answer_callback_query(call.id, "✅ Анкета отправлена!")
        bot.send_message(call.message.chat.id, "✅ Ваша анкета успешно отправлена!")

        if user_data.get('verification_type') == 'simple':
            # Упрощённая регистрация – сразу в меню
            show_role_menu(call.message, 'master')
        else:
            # Полная регистрация – предложения документов и фото
            if user_data.get('documents_verified') == 'pending':
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("📎 Отправить документы", callback_data=f"send_docs_{app_id}"))
                bot.send_message(
                    call.message.chat.id,
                    "Вы выбрали вариант с проверкой документов. Теперь вы можете отправить фото/скан документов администратору.",
                    reply_markup=markup
                )
            elif user_data.get('send_portfolio_later'):
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("📸 Отправить фото для портфолио", callback_data=f"send_photo_{app_id}"))
                bot.send_message(
                    call.message.chat.id,
                    "Вы хотели отправить фото для портфолио. Сделайте это сейчас.",
                    reply_markup=markup
                )
            else:
                show_role_menu(call.message, 'master')

        if user_id in bot.master_data:
            del bot.master_data[user_id]

    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Ошибка сохранения")
        bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

# ================ ОТПРАВКА ДОКУМЕНТОВ И ФОТО ================
@bot.callback_query_handler(func=lambda call: call.data.startswith('send_docs_'))
def send_docs_callback(call):
    app_id = int(call.data.split('_')[2])
    user_id = call.from_user.id
    bot.send_message(
        call.message.chat.id,
        "📎 Отправьте фото/скан документов (можно несколько). После отправки администратор получит их."
    )
    bot.register_next_step_handler(call.message, process_docs_for_verification, app_id, user_id)
    bot.answer_callback_query(call.id)

def process_docs_for_verification(message, app_id, user_id):
    if message.photo:
        file_id = message.photo[-1].file_id
        try:
            bot.send_photo(
                ADMIN_ID,
                file_id,
                caption=f"📎 Документы от мастера (заявка #{app_id}, user {user_id})"
            )
            bot.send_message(message.chat.id, "✅ Документ отправлен администратору.")
        except Exception as e:
            bot.send_message(message.chat.id, "⚠️ Не удалось отправить документ. Попробуйте позже.")

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📎 Отправить ещё документ", callback_data=f"send_docs_{app_id}"),
            types.InlineKeyboardButton("📸 Отправить фото для портфолио", callback_data=f"send_photo_{app_id}"),
            types.InlineKeyboardButton("✅ Завершить", callback_data="finish_docs")
        )
        bot.send_message(
            message.chat.id,
            "Что хотите сделать дальше?",
            reply_markup=markup
        )
    else:
        bot.send_message(message.chat.id, "❌ Пожалуйста, отправьте фото.")
        bot.register_next_step_handler(message, process_docs_for_verification, app_id, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('send_photo_'))
def send_photo_callback(call):
    app_id = int(call.data.split('_')[2])
    user_id = call.from_user.id
    bot.send_message(
        call.message.chat.id,
        "📸 Отправьте фото/видео для портфолио. Администратор получит их и создаст ссылку."
    )
    bot.register_next_step_handler(call.message, process_photo_for_portfolio, app_id, user_id)
    bot.answer_callback_query(call.id)

def process_photo_for_portfolio(message, app_id, user_id):
    if message.photo:
        file_id = message.photo[-1].file_id
        try:
            bot.send_photo(
                ADMIN_ID,
                file_id,
                caption=f"📸 Портфолио от мастера (заявка #{app_id}, user {user_id})"
            )
            bot.send_message(message.chat.id, "✅ Фото отправлено администратору. После создания ссылки ваш статус будет обновлён.")
        except Exception as e:
            bot.send_message(message.chat.id, "⚠️ Не удалось отправить фото. Попробуйте позже.")

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📸 Отправить ещё фото", callback_data=f"send_photo_{app_id}"),
            types.InlineKeyboardButton("📎 Отправить документ", callback_data=f"send_docs_{app_id}"),
            types.InlineKeyboardButton("✅ Завершить", callback_data="finish_docs")
        )
        bot.send_message(
            message.chat.id,
            "Что хотите сделать дальше?",
            reply_markup=markup
        )
    else:
        bot.send_message(message.chat.id, "❌ Пожалуйста, отправьте фото.")
        bot.register_next_step_handler(message, process_photo_for_portfolio, app_id, user_id)

@bot.callback_query_handler(func=lambda call: call.data == 'finish_docs')
def finish_docs_callback(call):
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(call.message.chat.id, "✅ Вы завершили отправку. Спасибо!")
    show_role_menu(call.message, 'master')
    bot.answer_callback_query(call.id)

# ================ ФУНКЦИИ УВЕДОМЛЕНИЙ МАСТЕРОВ ================
def notify_masters_about_new_request(request_id, request_data):
    service = request_data['service'].lower()
    district = request_data['district'].lower()

    cursor.execute('''SELECT user_id, name, service, districts, verification_type FROM masters WHERE status = 'активен' ''')
    masters = cursor.fetchall()
    notified = 0
    for master in masters:
        master_user_id, master_name, master_service, master_districts, master_verif = master
        if master_user_id == 0 or master_verif == 'simple':
            continue
        service_match = any(prof.strip().lower() in master_service.lower() for prof in service.split())
        district_match = any(d.strip().lower() in district for d in master_districts.split(','))
        if service_match and district_match:
            try:
                bot.send_message(
                    master_user_id,
                    f"🔔 **Новая заявка #{request_id}**\n\n"
                    f"🔧 Профиль: {request_data['service']}\n"
                    f"📝 Описание: {request_data['description']}\n"
                    f"📍 Район: {request_data['district']}\n"
                    f"📅 Срок: {request_data['date']}\n"
                    f"💰 Бюджет: {request_data['budget']}\n\n"
                    f"Чтобы откликнуться, используйте команду /respond {request_id} или найдите заявку в разделе «Активные заявки»."
                )
                notified += 1
            except Exception as e:
                print(f"Не удалось уведомить мастера {master_user_id}: {e}")
    print(f"Уведомлено {notified} мастеров по заявке #{request_id}")

def notify_masters_about_private_request(request_id, request_data):
    service = request_data['service'].lower()
    district = request_data['district'].lower()

    cursor.execute('''SELECT user_id, name, service, districts, verification_type FROM masters WHERE status = 'активен' ''')
    masters = cursor.fetchall()
    notified = 0
    for master in masters:
        master_user_id, master_name, master_service, master_districts, master_verif = master
        if master_user_id == 0 or master_verif == 'simple':
            continue
        service_match = any(prof.strip().lower() in master_service.lower() for prof in service.split())
        district_match = any(d.strip().lower() in district for d in master_districts.split(','))
        if service_match and district_match:
            try:
                bot.send_message(
                    master_user_id,
                    f"🔔 **Новая приватная заявка #{request_id}**\n\n"
                    f"🔧 Профиль: {request_data['service']}\n"
                    f"📝 Описание: {request_data['description']}\n"
                    f"📍 Район: {request_data['district']}\n"
                    f"📅 Срок: {request_data['date']}\n"
                    f"💰 Бюджет: {request_data['budget']}\n\n"
                    f"Чтобы откликнуться, используйте команду /respond {request_id} или найдите заявку в разделе «Активные заявки»."
                )
                notified += 1
            except Exception as e:
                print(f"Не удалось уведомить мастера {master_user_id}: {e}")
    print(f"Уведомлено {notified} мастеров по приватной заявке #{request_id}")

# ================ КЛИЕНТСКАЯ ЧАСТЬ (ЗАЯВКИ) ================
if not hasattr(bot, 'request_data'):
    bot.request_data = {}

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
    req_type = call.data.split('_')[1]
    user_id = call.from_user.id
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('UPDATE users SET last_active = ? WHERE user_id = ?', (now, user_id))
    conn.commit()
    bot.request_data[user_id] = {'type': req_type}
    ask_client_service(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)

def ask_client_service(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for code, name in PROFILES:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"cl_serv_{code}"))
    bot.send_message(
        chat_id,
        "🔧 **Шаг 1 из 5**\n\nВыберите **профиль**, который вам нужен (только один):",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('cl_serv_'))
def client_service_callback(call):
    user_id = call.from_user.id
    code = call.data[8:]
    service_name = PROFILES_DICT.get(code)
    if not service_name:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    if user_id not in bot.request_data:
        bot.request_data[user_id] = {}
    bot.request_data[user_id]['service'] = service_name
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    ask_client_district(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)

def ask_client_district(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for code, name in DISTRICTS:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"cl_dist_{code}"))
    bot.send_message(
        chat_id,
        "📍 **Шаг 2 из 5**\n\nВыберите **район**, где нужно выполнить работу (только один):",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('cl_dist_'))
def client_district_callback(call):
    user_id = call.from_user.id
    code = call.data[8:]
    district_name = DISTRICTS_DICT.get(code)
    if not district_name:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    bot.request_data[user_id]['district'] = district_name
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(
        call.message.chat.id,
        "📝 **Шаг 3 из 5**\n\nОпишите задачу подробнее:"
    )
    bot.register_next_step_handler(call.message, process_request_description)
    bot.answer_callback_query(call.id)

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
        "📅 **Шаг 4 из 5**\n\nКогда нужно приступить?\nПример: *В ближайшие дни, на следующей неделе, после 15 мая*"
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
        "💰 **Шаг 5 из 5**\n\nКакой бюджет?\nПример: *до 5000₽, договорной, 10-15 тыс.*"
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
    data = bot.request_data[user_id]
    summary = f"""
📋 **Сводка заявки:**

🔧 Профиль: {data['service']}
📝 Описание: {data['description']}
📍 Район: {data['district']}
📅 Срок: {data['date']}
💰 Бюджет: {data['budget']}
📢 Тип: {'Публичная' if data['type'] == 'public' else 'Персональный подбор'}
    """
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_req_{user_id}"),
        types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit_req"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_req")
    )
    bot.send_message(message.chat.id, summary, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'edit_req')
def edit_request_callback(call):
    user_id = call.from_user.id
    bot.edit_message_text(
        "Начните создание заявки заново.",
        call.message.chat.id,
        call.message.message_id
    )
    create_request_start(call.message)
    bot.answer_callback_query(call.id)

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
                "Ваша заявка будет опубликована утром, а мастера получат уведомления утром.\n"
                "Спасибо за понимание!"
            )
        else:
            client_alias = f"Клиент #{request_id % 10000}"
            text = f"""
🆕 **НОВАЯ ЗАЯВКА!**

👤 **От:** {client_alias}
🔨 **Профиль:** {data['service']}
📝 **Задача:** {data['description']}
📍 **Район/ЖК:** {data['district']}
📅 **Когда:** {data['date']}
💰 **Бюджет:** {data['budget']}
📢 Публичная заявка. Мастера, откликайтесь в боте!
            """
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📞 Откликнуться", callback_data=f"channel_respond_{request_id}"))
            try:
                sent = bot.send_message(CHANNEL_ID, text, reply_markup=markup)
                cursor.execute("UPDATE requests SET chat_message_id = ? WHERE id = ?", (sent.message_id, request_id))
                conn.commit()
            except Exception as e:
                bot.send_message(ADMIN_ID, f"❌ Ошибка отправки заявки в канал: {e}")
                bot.send_message(call.message.chat.id, "❌ Не удалось опубликовать заявку. Администратор уже уведомлён.")
            notify_masters_about_new_request(request_id, data)
        bot.send_message(
            call.message.chat.id,
            "📢 Ваша заявка опубликована в канале и разослана подходящим мастерам.\n"
            "Как только появятся отклики, вы получите уведомление.\n"
            "Статус заявки можно отслеживать в разделе «Мои заявки»."
        )
    else:
        bot.send_message(
            call.message.chat.id,
            "🤝 **Заявка на персональный подбор принята!**\n\n"
            "Мы подберём для вас подходящих мастеров и свяжемся с вами."
        )
        notify_masters_about_private_request(request_id, data)
        bot.send_message(
            call.message.chat.id,
            "📢 Ваша заявка разослана подходящим мастерам.\n"
            "Как только появятся отклики, вы получите уведомление.\n"
            "Статус заявки можно отслеживать в разделе «Мои заявки»."
        )

    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(call.message.chat.id, "✅ Заявка сохранена! Спасибо.")
    if user_id in bot.request_data:
        del bot.request_data[user_id]
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_req')
def cancel_request(call):
    user_id = call.from_user.id
    if user_id in bot.request_data:
        del bot.request_data[user_id]
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(call.message.chat.id, "❌ Создание заявки отменено.")
    bot.answer_callback_query(call.id)

# ================ КНОПКА "МОИ ЗАЯВКИ" (КЛИЕНТ) ================
@bot.message_handler(func=lambda message: message.text == '📋 Мои заявки')
def my_requests_handler(message):
    if not only_private(message):
        return
    my_requests(message)

def my_requests(message):
    user_id = message.from_user.id
    cursor.execute('''SELECT id, service, description, district, date, budget, status, created_at, chat_message_id
                      FROM requests WHERE user_id = ? ORDER BY created_at DESC''', (user_id,))
    requests = cursor.fetchall()
    if not requests:
        bot.send_message(message.chat.id, "У вас пока нет заявок.")
        return
    for req in requests:
        req_id, service, desc, district, date, budget, status, created, chat_msg_id = req
        text = f"""
📋 **Заявка #{req_id}**
🔧 Профиль: {service}
📝 Описание: {desc}
📍 Район: {district}
📅 Срок: {date}
💰 Бюджет: {budget}
📌 Статус: {status}
🕒 Создана: {created}
        """
        markup = types.InlineKeyboardMarkup()
        if chat_msg_id is None and status == 'активна':
            markup.add(types.InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_request_{req_id}"))
        cursor.execute('SELECT COUNT(*) FROM responses WHERE request_id = ?', (req_id,))
        resp_count = cursor.fetchone()[0]
        if resp_count > 0:
            markup.add(types.InlineKeyboardButton(f"👥 Отклики ({resp_count})", callback_data=f"view_responses_{req_id}"))
        if status == 'завершена':
            # Проверяем, есть ли принятый мастер
            cursor.execute('SELECT master_id FROM responses WHERE request_id = ? AND status = "accepted"', (req_id,))
            acc = cursor.fetchone()
            if acc:
                master_id = acc[0]
                markup.add(types.InlineKeyboardButton("⭐ Оставить отзыв", callback_data=f"leave_review_{req_id}_{master_id}"))
        if status != 'активна':
            markup.add(types.InlineKeyboardButton("🔄 Опубликовать заново", callback_data=f"republish_request_{req_id}"))
        if markup.keyboard:
            bot.send_message(message.chat.id, text, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, text)
         
        if status == 'завершена':
            # Находим принятого мастера (если есть)
            cursor.execute('SELECT master_id FROM responses WHERE request_id = ? AND status = "accepted"', (req_id,))
            acc = cursor.fetchone()
            if acc:
                master_id = acc[0]
                markup.add(types.InlineKeyboardButton("⭐ Оставить отзыв", callback_data=f"leave_review_{req_id}_{master_id}"))

@bot.callback_query_handler(func=lambda call: call.data.startswith('leave_review_'))
def leave_review_callback(call):
    parts = call.data.split('_')
    req_id = int(parts[2])
    master_id = int(parts[3])
    user_id = call.from_user.id
    # Проверяем, что заявка принадлежит этому клиенту
    cursor.execute('SELECT user_id FROM requests WHERE id = ?', (req_id,))
    row = cursor.fetchone()
    if not row or row[0] != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша заявка")
        return
    # Получаем имя мастера
    cursor.execute('SELECT name FROM masters WHERE id = ?', (master_id,))
    row = cursor.fetchone()
    master_name = row[0] if row else "Мастер"
    bot.send_message(
        call.message.chat.id,
        f"⭐ Напишите отзыв о мастере **{master_name}**:"
    )
    bot.register_next_step_handler(call.message, process_review_text_from_request, req_id, master_id, master_name)
    bot.answer_callback_query(call.id)

def process_review_text_from_request(message, req_id, master_id, master_name):
    text = safe_text(message)
    if not text:
        bot.send_message(message.chat.id, "❌ Текст не может быть пустым.")
        return
    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = [types.InlineKeyboardButton(str(i), callback_data=f"review_rate_{i}_{master_id}") for i in range(1, 6)]
    markup.add(*buttons)
    bot.send_message(
        message.chat.id,
        f"⭐ Оцените мастера от 1 до 5:",
        reply_markup=markup
    )
    if not hasattr(bot, 'master_review_text'):
        bot.master_review_text = {}
    bot.master_review_text[message.from_user.id] = (master_id, master_name, text)

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_request_'))
def edit_request_callback(call):
    req_id = int(call.data.split('_')[2])
    user_id = call.from_user.id
    cursor.execute("DELETE FROM requests WHERE id = ? AND user_id = ?", (req_id, user_id))
    conn.commit()
    bot.answer_callback_query(call.id, "✅ Старая заявка удалена, создайте новую.")
    create_request_start(call.message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('view_responses_'))
def view_responses_callback(call):
    req_id = int(call.data.split('_')[2])
    user_id = call.from_user.id

    cursor.execute('SELECT user_id FROM requests WHERE id = ?', (req_id,))
    row = cursor.fetchone()
    if not row or row[0] != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша заявка")
        return

    cursor.execute('''
        SELECT r.id, m.name, r.price, r.comment, r.status, m.id
        FROM responses r
        JOIN masters m ON r.master_id = m.id
        WHERE r.request_id = ?
        ORDER BY r.created_at DESC
    ''', (req_id,))
    responses = cursor.fetchall()
    if not responses:
        bot.answer_callback_query(call.id, "Нет откликов")
        return

    for resp in responses:
        resp_id, master_name, price, comment, status, master_id = resp
        text = f"""
👤 Мастер: {master_name}
📝 Комментарий: {comment}
📌 Статус: {status}
        """
        markup = types.InlineKeyboardMarkup()
        if status == 'pending':
            markup.add(
                types.InlineKeyboardButton("✅ Принять", callback_data=f"accept_response_{req_id}_{master_id}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_response_{req_id}_{master_id}")
            )
        bot.send_message(call.message.chat.id, text, reply_markup=markup if markup.keyboard else None)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('republish_request_'))
def republish_request_callback(call):
    req_id = int(call.data.split('_')[2])
    user_id = call.from_user.id

    cursor.execute('SELECT user_id FROM requests WHERE id = ?', (req_id,))
    row = cursor.fetchone()
    if not row or row[0] != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша заявка")
        return

    # Запрашиваем подтверждение
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Да, заявка не исполнена", callback_data=f"confirm_republish_{req_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_republish")
    )
    bot.edit_message_text(
        "⚠️ Вы подтверждаете, что заявка не была исполнена? После повторной публикации все предыдущие отклики будут удалены.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_republish_'))
def confirm_republish_callback(call):
    req_id = int(call.data.split('_')[2])
    user_id = call.from_user.id

    cursor.execute('SELECT user_id, service, description, district, date, budget, is_public FROM requests WHERE id = ?', (req_id,))
    req = cursor.fetchone()
    if not req or req[0] != user_id:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    user_id, service, desc, district, date, budget, is_public = req
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    # Удаляем старые отклики (можно не удалять, а просто создать новую заявку)
    cursor.execute('''INSERT INTO requests
                    (user_id, username, service, description, district, date, budget, is_public, status, delayed, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id,
                     call.from_user.username or "no_username",
                     service, desc, district, date, budget,
                     is_public, 'активна',
                     1 if is_night_time() and is_public else 0,
                     now))
    conn.commit()
    new_req_id = cursor.lastrowid

    bot.edit_message_text(
        f"✅ Заявка #{new_req_id} создана заново.",
        call.message.chat.id,
        call.message.message_id
    )
    if is_public and not is_night_time():
        bot.send_message(call.message.chat.id, "Заявка будет опубликована в ближайшее время.")
    else:
        bot.send_message(call.message.chat.id, "Заявка сохранена и будет опубликована утром.")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "cancel_republish")
def cancel_republish_callback(call):
    bot.edit_message_text("❌ Повторная публикация отменена.", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)
    
# ================ КНОПКА "АКТИВНЫЕ ЗАЯВКИ" (ДЛЯ МАСТЕРА) ================
@bot.message_handler(func=lambda message: message.text == '📋 Активные заявки')
def active_requests_handler(message):
    if not only_private(message):
        return
    active_requests(message)

def active_requests(message):
    cursor.execute('''SELECT id, service, description, district, date, budget, created_at 
                      FROM requests WHERE status = 'активна' AND is_public = 1 ORDER BY created_at DESC LIMIT 10''')
    requests = cursor.fetchall()
    if not requests:
        bot.send_message(message.chat.id, "Нет активных публичных заявок.")
        return
    for req in requests:
        req_id, service, desc, district, date, budget, created = req
        text = f"""
📋 **Заявка #{req_id}**
🔧 Профиль: {service}
📝 Описание: {desc}
📍 Район: {district}
📅 Срок: {date}
💰 Бюджет: {budget}
        """
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📞 Откликнуться", callback_data=f"respond_{req_id}"))
        bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '🔔 Заявки по моему профилю')
def my_profile_requests_handler(message):
    if not only_private(message):
        return
    user_id = message.from_user.id
    cursor.execute("SELECT service, districts FROM masters WHERE user_id = ? AND status = 'активен'", (user_id,))
    master = cursor.fetchone()
    if not master:
        bot.send_message(message.chat.id, "❌ Вы не активный мастер. Заполните анкету и дождитесь одобрения.")
        return
    master_service, master_districts = master
    master_profiles = [p.strip().lower() for p in master_service.split(',')]
    master_districts_list = [d.strip().lower() for d in master_districts.split(',')]

    cursor.execute('''SELECT id, service, description, district, date, budget, created_at 
                      FROM requests WHERE status = 'активна' AND is_public = 1 ORDER BY created_at DESC''')
    all_requests = cursor.fetchall()
    suitable = []
    for req in all_requests:
        req_id, service, desc, district, date, budget, created = req
        service_match = any(prof in service.lower() for prof in master_profiles)
        district_match = any(d in district.lower() for d in master_districts_list)
        if service_match and district_match:
            suitable.append((req_id, service, desc, district, date, budget, created))

    if not suitable:
        bot.send_message(message.chat.id, "Нет активных заявок, подходящих под ваш профиль и районы.")
        return
    for req in suitable:
        req_id, service, desc, district, date, budget, created = req
        text = f"""
📋 **Заявка #{req_id}**
🔧 Профиль: {service}
📝 Описание: {desc}
📍 Район: {district}
📅 Срок: {date}
💰 Бюджет: {budget}
        """
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📞 Откликнуться", callback_data=f"respond_{req_id}"))
        bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('respond_'))
def respond_to_request(call):
    req_id = int(call.data.split('_')[1])
    user_id = call.from_user.id
    cursor.execute('SELECT id FROM masters WHERE user_id = ? AND status = "активен"', (user_id,))
    master = cursor.fetchone()
    if not master:
        bot.answer_callback_query(call.id, "❌ Вы не активный мастер. Заполните анкету и дождитесь одобрения.")
        return
    master_id = master[0]
    cursor.execute('SELECT id FROM responses WHERE request_id = ? AND master_id = ?', (req_id, master_id))
    if cursor.fetchone():
        bot.answer_callback_query(call.id, "❌ Вы уже откликнулись на эту заявку.")
        return
    bot.send_message(
        call.message.chat.id,
        "📝 Напишите ваше предложение (цену, комментарий):"
    )
    bot.register_next_step_handler(call.message, process_response, req_id, master_id)
    bot.answer_callback_query(call.id)

def process_response(message, req_id, master_id):
    text = safe_text(message)
    if not text:
        bot.send_message(message.chat.id, "❌ Введите текст отклика.")
        return
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('''INSERT INTO responses (request_id, master_id, price, comment, status, created_at, updated_at)
                      VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (req_id, master_id, '', text, 'pending', now, now))
    conn.commit()
    bot.send_message(message.chat.id, "✅ Ваш отклик отправлен клиенту и администратору.")

    # Уведомление клиенту
        # Уведомление клиенту
        cursor.execute('SELECT user_id FROM requests WHERE id = ?', (req_id,))
        client = cursor.fetchone()
        if client:
            client_id = client[0]
            # Получаем данные мастера
            cursor.execute('''SELECT name, service, districts, phone, preferred_contact, user_id 
                              FROM masters WHERE id = ?''', (master_id,))
            master_info = cursor.fetchone()
            if master_info:
                master_name, master_service, master_districts, master_phone, master_pref, master_user_id = master_info
                # Формируем сообщение с краткой информацией о мастере
                master_text = f"""
👤 **Мастер:** {master_name}
🔧 **Профили:** {master_service}
📍 **Районы:** {master_districts}
📞 **Контакт:** {master_phone if master_phone else 'не указан'}
📱 **Предпочтительный способ связи:** {master_pref}
                """
            else:
                master_text = "Информация о мастере временно недоступна."

            # Клавиатура с действиями
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Принять", callback_data=f"accept_response_{req_id}_{master_id}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_response_{req_id}_{master_id}")
            )
            # Кнопка "Посмотреть карточку"
            markup.add(types.InlineKeyboardButton("👤 Посмотреть карточку мастера", callback_data=f"view_master_{master_id}"))
            
            # Если предпочтительный способ связи Telegram, добавляем кнопку "Написать мастеру"
            if master_info and 'telegram' in master_pref.lower() and master_user_id and master_user_id != 0:
                markup.add(types.InlineKeyboardButton("✉️ Написать мастеру в Telegram", url=f"tg://user?id={master_user_id}"))
            else:
                # Иначе просто показываем телефон (если есть) в тексте, а кнопка не нужна
                pass

            try:
                bot.send_message(
                    client_id,
                    f"🔔 На вашу заявку #{req_id} поступил отклик от мастера.\n\n"
                    f"**Предложение мастера:** {text}\n\n"
                    f"{master_text}\n\n"
                    f"Вы можете принять или отклонить отклик, а также посмотреть полную карточку мастера.",
                    reply_markup=markup
                )
            except Exception as e:
                print(f"Не удалось уведомить клиента {client_id}: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('channel_respond_'))
def channel_respond_callback(call):
    request_id = int(call.data.split('_')[2])
    user_id = call.from_user.id
    cursor.execute('SELECT id, service FROM masters WHERE user_id = ? AND status = "активен"', (user_id,))
    master = cursor.fetchone()
    if not master:
        bot.answer_callback_query(call.id, "❌ Только активные мастера могут откликаться.", show_alert=True)
        return
    master_id, master_service = master
    cursor.execute('SELECT service FROM requests WHERE id = ?', (request_id,))
    row = cursor.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "❌ Заявка не найдена.")
        return
    request_service = row[0]
    if not any(prof.strip().lower() in request_service.lower() for prof in master_service.split(',')):
        bot.answer_callback_query(call.id, "❌ Ваш профиль не подходит для этой заявки.", show_alert=True)
        return
    bot.answer_callback_query(call.id, "✅ Перейдите в бота для отклика.")
    bot.send_message(
        user_id,
        f"Вы хотите откликнуться на заявку #{request_id}. Напишите ваше предложение (цена и комментарий):"
    )
    bot.register_next_step_handler_by_chat_id(user_id, process_response_from_channel, request_id, master_id)

def process_response_from_channel(message, request_id, master_id):
    text = safe_text(message)
    if not text:
        bot.send_message(message.chat.id, "❌ Введите текст отклика.")
        return
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('''INSERT INTO responses (request_id, master_id, price, comment, status, created_at, updated_at)
                      VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (request_id, master_id, '', text, 'pending', now, now))
    conn.commit()
    bot.send_message(message.chat.id, "✅ Ваш отклик отправлен клиенту и администратору.")
    cursor.execute('SELECT user_id FROM requests WHERE id = ?', (request_id,))
    client_id = cursor.fetchone()[0]
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Принять", callback_data=f"accept_response_{request_id}_{master_id}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_response_{request_id}_{master_id}")
        )
        bot.send_message(
            client_id,
            f"🔔 На вашу заявку #{request_id} поступил отклик от мастера.\n\n"
            f"Предложение: {text}\n\n"
            f"Вы можете принять или отклонить его.",
            reply_markup=markup
        )
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('accept_response_'))
def accept_response_callback(call):
    parts = call.data.split('_')
    req_id = int(parts[2])
    master_id = int(parts[3])
    user_id = call.from_user.id

    cursor.execute('SELECT user_id FROM requests WHERE id = ?', (req_id,))
    row = cursor.fetchone()
    if not row or row[0] != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша заявка")
        return

    cursor.execute('SELECT status FROM responses WHERE request_id = ? AND master_id = ?', (req_id, master_id))
    resp = cursor.fetchone()
    if not resp or resp[0] != 'pending':
        bot.answer_callback_query(call.id, "❌ Отклик уже обработан")
        return

    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('UPDATE responses SET status = ?, updated_at = ? WHERE request_id = ? AND master_id = ?',
                   ('accepted', now, req_id, master_id))
    cursor.execute('UPDATE responses SET status = ?, updated_at = ? WHERE request_id = ? AND status = "pending"',
                   ('rejected', now, req_id))
    cursor.execute('UPDATE requests SET status = ? WHERE id = ?', ('завершена', req_id))
    conn.commit()

    cursor.execute('SELECT name, phone, preferred_contact FROM masters WHERE id = ?', (master_id,))
    master = cursor.fetchone()
    master_name, master_phone, master_contact = master if master else ("Неизвестно", "нет", "нет")

    bot.send_message(
        user_id,
        f"✅ Вы приняли отклик мастера **{master_name}**.\n\n"
        f"📞 Контакт мастера: {master_phone}\n"
        f"📱 Предпочтительный способ связи: {master_contact}\n\n"
        f"Свяжитесь с мастером для обсуждения деталей."
    )

    cursor.execute('SELECT user_id FROM masters WHERE id = ?', (master_id,))
    master_user = cursor.fetchone()
    if master_user and master_user[0] != 0:
        try:
            cursor.execute('SELECT username, user_id FROM requests WHERE id = ?', (req_id,))
            client = cursor.fetchone()
            client_username, client_id_db = client if client else ("", "")
            client_contact = f"@{client_username}" if client_username else f"ID: {client_id_db}"
            bot.send_message(
                master_user[0],
                f"✅ Ваш отклик на заявку #{req_id} принят!\n\n"
                f"👤 Контакт клиента: {client_contact}\n"
                f"Свяжитесь с клиентом для обсуждения деталей."
            )
        except Exception as e:
            print(f"Не удалось уведомить мастера {master_user[0]}: {e}")

    bot.edit_message_text(
        "✅ Вы приняли отклик. Контакты отправлены.",
        call.message.chat.id,
        call.message.message_id
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('reject_response_'))
def reject_response_callback(call):
    parts = call.data.split('_')
    req_id = int(parts[2])
    master_id = int(parts[3])
    user_id = call.from_user.id

    cursor.execute('SELECT user_id FROM requests WHERE id = ?', (req_id,))
    row = cursor.fetchone()
    if not row or row[0] != user_id:
        bot.answer_callback_query(call.id, "❌ Это не ваша заявка")
        return

    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('UPDATE responses SET status = ?, updated_at = ? WHERE request_id = ? AND master_id = ?',
                   ('rejected', now, req_id, master_id))
    conn.commit()

    cursor.execute('SELECT user_id FROM masters WHERE id = ?', (master_id,))
    master_user = cursor.fetchone()
    if master_user and master_user[0] != 0:
        try:
            bot.send_message(
                master_user[0],
                f"❌ Ваш отклик на заявку #{req_id} был отклонён клиентом."
            )
        except:
            pass

    bot.edit_message_text(
        "❌ Отклик отклонён.",
        call.message.chat.id,
        call.message.message_id
    )
    bot.answer_callback_query(call.id)
    
@bot.message_handler(func=lambda message: message.text == '👤 Моя анкета')
def my_profile(message):
    if not only_private(message):
        return
    user_id = message.from_user.id
    # Сначала ищем в активных мастерах
    cursor.execute('''SELECT id, name, service, phone, districts, price_min, experience, bio, portfolio,
                      preferred_contact, payment_methods, age_group, status
                      FROM masters WHERE user_id = ?''', (user_id,))
    master = cursor.fetchone()
    if master:
        master_id, name, service, phone, districts, price_min, experience, bio, portfolio, pref_contact, payment, age, status = master
        text = f"""
👤 **Ваша анкета (активный мастер)**

👤 Имя: {name}
🔧 Профили: {service}
📞 Телефон: {phone}
📍 Районы: {districts}
💰 Мин. цена: {price_min}
⏱ Опыт: {experience}
💬 О себе: {bio}
📸 Портфолио: {portfolio}
📞 Контакт: {pref_contact}
💳 Оплата: {payment}
🎂 Возраст: {age}
📌 Статус: {status}
        """
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_master_{master_id}"))
        bot.send_message(message.chat.id, text, reply_markup=markup)
    else:
        # Ищем в заявках на проверку
        cursor.execute('''SELECT id, name, service, phone, districts, price_min, experience, bio, portfolio,
                          preferred_contact, payment_methods, age_group, status
                          FROM master_applications WHERE user_id = ?''', (user_id,))
        app = cursor.fetchone()
        if app:
            app_id, name, service, phone, districts, price_min, experience, bio, portfolio, pref_contact, payment, age, status = app
            text = f"""
👤 **Ваша анкета (на проверке)**

👤 Имя: {name}
🔧 Профили: {service}
📞 Телефон: {phone}
📍 Районы: {districts}
💰 Мин. цена: {price_min}
⏱ Опыт: {experience}
💬 О себе: {bio}
📸 Портфолио: {portfolio}
📞 Контакт: {pref_contact}
💳 Оплата: {payment}
🎂 Возраст: {age}
📌 Статус: {status}
            """
            bot.send_message(message.chat.id, text)
        else:
            bot.send_message(message.chat.id, "У вас ещё нет анкеты. Нажмите «👷 Заполнить анкету».")

@bot.callback_query_handler(func=lambda call: call.data.startswith('view_master_'))
def view_master_from_notification(call):
    master_id = int(call.data.split('_')[2])
    # Показываем карточку мастера (используем существующую логику master_detail)
    # Но нужно отправить новое сообщение, не редактируя текущее
    cursor.execute('''SELECT name, service, phone, districts, price_min, experience, bio, portfolio, rating, reviews_count
                      FROM masters WHERE id = ?''', (master_id,))
    master = cursor.fetchone()
    if not master:
        bot.answer_callback_query(call.id, "❌ Мастер не найден")
        return
    name, service, phone, districts, price_min, experience, bio, portfolio, rating, reviews_count = master
    rating_display = f"{rating:.1f}" if rating else "Нет"
    text = f"""
👤 **{name}**
🔧 Профили: {service}
⭐ Рейтинг: {rating_display} ({reviews_count} отзывов)
📍 Районы: {districts}
💰 Мин. цена: {price_min}
⏱ Опыт: {experience}
💬 О себе: {bio}
📸 Портфолио: {portfolio}
📞 Телефон: {phone}
    """
    bot.send_message(call.message.chat.id, text)
    bot.answer_callback_query(call.id)
# ================ ПОИСК МАСТЕРА (КАТАЛОГ) ================
@bot.message_handler(func=lambda message: message.text == '🔍 Найти мастера')
def find_master_start(message):
    if not only_private(message):
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('По профилю', 'По району', 'По рейтингу')
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
        role = row[0] if row else 'client'
        show_role_menu(message, role)
        return
    if text == 'По профилю':
        ask_client_service_for_search(message.chat.id, message.from_user.id)
        return
    if text == 'По району':
        ask_client_district_for_search(message.chat.id, message.from_user.id)
        return
    if text == 'По рейтингу':
        search_by_rating(message)
        return
    else:
        bot.send_message(message.chat.id, "❌ Неверный выбор. Попробуйте снова.")
        find_master_start(message)

@bot.message_handler(func=lambda message: message.text == '◀️ Назад в меню')
def back_to_menu(message):
    if not only_private(message):
        return
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (message.from_user.id,))
    row = cursor.fetchone()
    role = row[0] if row else 'client'
    show_role_menu(message, role)

def ask_client_service_for_search(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for code, name in PROFILES:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"search_serv_{code}"))
    bot.send_message(
        chat_id,
        "🔧 **Выберите профиль для поиска:**",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('search_serv_'))
def search_service_callback(call):
    code = call.data[12:]  # убираем 'search_serv_'
    service_name = PROFILES_DICT.get(code)
    if not service_name:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    cursor.execute('''SELECT id, name, service, rating, reviews_count, districts
                      FROM masters WHERE status = 'активен' AND LOWER(service) LIKE ?''',
                   (f'%{service_name.lower()}%',))
    masters = cursor.fetchall()
    if not masters:
        bot.send_message(call.message.chat.id, "😕 Мастеров с таким профилем пока нет.")
    else:
        send_masters_list(call.message.chat.id, masters)
    bot.answer_callback_query(call.id)

def ask_client_district_for_search(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for code, name in DISTRICTS:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"search_dist_{code}"))
    bot.send_message(
        chat_id,
        "📍 **Выберите район для поиска:**",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('search_dist_'))
def search_district_callback(call):
    code = call.data[12:]  # убираем 'search_dist_'
    district_name = DISTRICTS_DICT.get(code)
    if not district_name:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    cursor.execute('''SELECT id, name, service, rating, reviews_count, districts
                      FROM masters WHERE status = 'активен' AND LOWER(districts) LIKE ?''',
                   (f'%{district_name.lower()}%',))
    masters = cursor.fetchall()
    if not masters:
        bot.send_message(call.message.chat.id, "😕 Мастеров в этом районе пока нет.")
    else:
        send_masters_list(call.message.chat.id, masters)
    bot.answer_callback_query(call.id)

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
🔧 Профили: {service}
⭐ Рейтинг: {rating_display} ({reviews_count} отзывов)
📍 Районы: {districts}
        """
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👤 Подробнее", callback_data=f"master_{master_id}"))
        bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('master_'))
def master_detail(call):
    master_id = int(call.data.split('_')[1])
    cursor.execute('''SELECT name, service, phone, districts, price_min, experience, bio, portfolio, rating, reviews_count
                      FROM masters WHERE id = ?''', (master_id,))
    master = cursor.fetchone()
    if not master:
        bot.answer_callback_query(call.id, "❌ Мастер не найден")
        return
    name, service, phone, districts, price_min, experience, bio, portfolio, rating, reviews_count = master
    rating_display = f"{rating:.1f}" if rating else "Нет"
    text = f"""
👤 **{name}**
🔧 Профили: {service}
⭐ Рейтинг: {rating_display} ({reviews_count} отзывов)
📍 Районы: {districts}
💰 Мин. цена: {price_min}
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

# ================ РЕКОМЕНДОВАТЬ МАСТЕРА ================
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
        "📞 Контакт мастера (телефон, ник в Telegram и т.п.):"
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
        "📝 Краткое описание: почему вы рекомендуете этого мастера?"
    )
    bot.register_next_step_handler(message, process_recommend_desc)

def process_recommend_desc(message):
    desc = safe_text(message)
    if not desc:
        bot.send_message(message.chat.id, "❌ Введите описание.")
        return
    user_id = message.from_user.id
    bot.recommend_data[user_id]['description'] = desc
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('''INSERT INTO recommendations
                    (user_id, username, master_name, service, contact, description, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id,
                     message.from_user.username or "no_username",
                     bot.recommend_data[user_id]['master_name'],
                     bot.recommend_data[user_id]['service'],
                     bot.recommend_data[user_id]['contact'],
                     bot.recommend_data[user_id]['description'],
                     'на модерации',
                     now))
    conn.commit()
    rec_id = cursor.lastrowid
    bot.send_message(
        message.chat.id,
        "✅ Спасибо за рекомендацию! Администратор проверит её и свяжется с мастером."
    )
    del bot.recommend_data[user_id]
    admin_text = f"""
🆕 **НОВАЯ РЕКОМЕНДАЦИЯ МАСТЕРА** (ID: {rec_id})
👤 Рекомендатель: @{message.from_user.username or "нет"}
👤 Мастер: {bot.recommend_data[user_id]['master_name']}
🔧 Специализация: {bot.recommend_data[user_id]['service']}
📞 Контакт: {bot.recommend_data[user_id]['contact']}
📝 Описание: {bot.recommend_data[user_id]['description']}
    """
    try:
        bot.send_message(ADMIN_ID, admin_text)
    except:
        pass

# ================ СМЕНА РОЛИ ================
@bot.message_handler(func=lambda message: message.text == '🔄 Сменить роль')
def change_role_start(message):
    if not only_private(message):
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Да, сменить роль", callback_data="confirm_change_role"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_change_role")
    )
    bot.send_message(
        message.chat.id,
        "⚠️ **Внимание!** Смена роли приведёт к удалению всех ваших заявок, анкет, отзывов и рекомендаций. Это действие необратимо. Продолжить?",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "confirm_change_role")
def confirm_change_role(call):
    user_id = call.from_user.id
    cursor.execute("DELETE FROM requests WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM master_applications WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM masters WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM responses WHERE master_id IN (SELECT id FROM masters WHERE user_id = ?)", (user_id,))
    cursor.execute("DELETE FROM reviews WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM recommendations WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM client_recommendations WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()
    bot.edit_message_text("✅ Ваши данные удалены. Используйте /start для выбора новой роли.", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "cancel_change_role")
def cancel_change_role(call):
    bot.edit_message_text("❌ Смена роли отменена.", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

# ================ КНОПКА "АДМИН-ПАНЕЛЬ" ================
@bot.message_handler(func=lambda message: message.text == '👑 Админ-панель')
def admin_panel_button(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    admin_panel(message)

# ================ АДМИНИСТРАТИВНЫЕ КОМАНДЫ ================
@bot.message_handler(commands=['approve'])
def approve_master(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    try:
        app_id = int(message.text.split()[1])
        cursor.execute('''SELECT user_id, name, service, phone, districts, price_min,
                          experience, bio, portfolio, documents, entity_type, verification_type,
                          documents_list, payment_methods, preferred_contact, age_group, source
                          FROM master_applications WHERE id = ?''', (app_id,))
        app = cursor.fetchone()
        if not app:
            bot.reply_to(message, f"❌ Анкета с ID {app_id} не найдена.")
            return
        (user_id, name, service, phone, districts, price_min,
         experience, bio, portfolio, documents, entity_type, verification_type,
         documents_list, payment_methods, preferred_contact, age_group, source) = app

        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        cursor.execute('''INSERT INTO masters
                        (user_id, name, service, phone, districts, price_min, price_max,
                         experience, bio, portfolio, documents, entity_type, verification_type,
                         documents_list, payment_methods, preferred_contact, age_group,
                         source, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (user_id, name, service, phone, districts, price_min, '',
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
                f"✅ Поздравляем! Ваша анкета одобрена!\n\nВы добавлены в базу мастеров. Теперь вы будете получать уведомления о новых заявках по вашим профилям и районам.\n\nПриглашаем в закрытый чат мастеров: {MASTER_CHAT_INVITE_LINK}"
            )
        except:
            pass

        publish_master_card(master_id, name, service, districts, price_min, experience, bio, portfolio)
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

def publish_master_card(master_id, name, service, districts, price_min, experience, bio, portfolio):
    if portfolio and portfolio.strip() and portfolio != 'Не указано':
        portfolio_text = portfolio
    else:
        portfolio_text = "Не указано"
    text = f"""
👤 **НОВЫЙ МАСТЕР В БАЗЕ!**

👤 **Имя:** {name}
🔧 **Профили:** {service}
📍 **Районы:** {districts}
💰 **Мин. цена:** {price_min}
⏱ **Опыт:** {experience}
💬 **О себе:** {bio}
📸 **Портфолио:** {portfolio_text}

⭐ Подробнее и отзывы – в боте: @{BOT_USERNAME}
    """
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📝 Оставить заявку этому мастеру", callback_data=f"channel_master_{master_id}"))
    try:
        sent = bot.send_message(CHANNEL_ID, text, reply_markup=markup)
        cursor.execute("UPDATE masters SET channel_message_id = ? WHERE id = ?", (sent.message_id, master_id))
        conn.commit()
    except Exception as e:
        print(f"Ошибка публикации карточки мастера: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('channel_master_'))
def channel_master_callback(call):
    master_id = int(call.data.split('_')[2])
    user_id = call.from_user.id
    bot.answer_callback_query(call.id, "✅ Перейдите в бота, чтобы оставить заявку.")
    bot.send_message(
        user_id,
        f"Вы хотите оставить заявку мастеру. Перейдите в бота и нажмите «🔨 Оставить заявку», укажите его профиль."
    )

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
        types.InlineKeyboardButton("🚀 Опубликовать отложенные", callback_data="admin_publish_delayed"),
        types.InlineKeyboardButton("➕ Добавить мастера вручную", callback_data="admin_manual_add")
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
    elif cmd == 'manual_add':
        start_manual_master_add(call)

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

# ================ РУЧНОЕ ДОБАВЛЕНИЕ МАСТЕРА (АДМИН) ================
if not hasattr(bot, 'admin_add_data'):
    bot.admin_add_data = {}

def start_manual_master_add(call):
    user_id = call.from_user.id
    if user_id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    bot.admin_add_data[user_id] = {}
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👤 Частное лицо", callback_data="admin_entity_individual"),
        types.InlineKeyboardButton("🏢 Компания / ИП", callback_data="admin_entity_company")
    )
    bot.edit_message_text(
        "👷 **РУЧНОЕ ДОБАВЛЕНИЕ МАСТЕРА**\n\n"
        "Шаг 1 из 14\n"
        "👇 **ВЫБЕРИТЕ ТИП:**",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_entity_'))
def admin_entity_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    entity_type = call.data.split('_')[2]
    user_id = call.from_user.id
    bot.admin_add_data[user_id]['entity_type'] = entity_type
    question = "👤 **ВВЕДИТЕ ПОЛНОЕ ИМЯ МАСТЕРА:**" if entity_type == 'individual' else "🏢 **ВВЕДИТЕ НАЗВАНИЕ КОМПАНИИ ИЛИ БРИГАДЫ:**"
    bot.edit_message_text(
        f"👷 **РУЧНОЕ ДОБАВЛЕНИЕ МАСТЕРА**\n\nШаг 2 из 14\n👇 {question}",
        call.message.chat.id,
        call.message.message_id
    )
    bot.register_next_step_handler(call.message, admin_process_name)
    bot.answer_callback_query(call.id)

def admin_process_name(message):
    if message.from_user.id != ADMIN_ID:
        return
    name = safe_text(message)
    if not name:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите имя/название.")
        bot.register_next_step_handler(message, admin_process_name)
        return
    user_id = message.from_user.id
    bot.admin_add_data[user_id]['name'] = name
    admin_ask_age(message.chat.id, user_id)

def admin_ask_age(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("до 25 лет", callback_data="admin_age_under25"),
        types.InlineKeyboardButton("25-35 лет", callback_data="admin_age_25_35"),
        types.InlineKeyboardButton("35-50 лет", callback_data="admin_age_35_50"),
        types.InlineKeyboardButton("старше 50", callback_data="admin_age_over50"),
        types.InlineKeyboardButton("⏩ Пропустить", callback_data="admin_age_skip")
    )
    bot.send_message(chat_id, "🎂 **Шаг 3 из 14**\n\nУкажите возраст мастера (необязательно).", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_age_'))
def admin_age_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    age_map = {'under25':'до 25','25_35':'25-35','35_50':'35-50','over50':'старше 50','skip':''}
    key = call.data[10:]
    bot.admin_add_data[user_id]['age_group'] = age_map.get(key, '')
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    admin_ask_profiles(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)

def admin_ask_profiles(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    if 'selected_profiles' not in bot.admin_add_data[user_id]:
        bot.admin_add_data[user_id]['selected_profiles'] = []
    selected = bot.admin_add_data[user_id]['selected_profiles']
    for code, name in PROFILES:
        prefix = "✅ " if name in selected else ""
        markup.add(types.InlineKeyboardButton(f"{prefix}{name}", callback_data=f"admin_prof_{code}"))
    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="admin_prof_done"))
    bot.send_message(chat_id, "👷 **Шаг 4 из 14**\n\nВыберите **профили** мастера (можно несколько):", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_prof_'))
def admin_profile_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    data = call.data[11:]
    if data == "done":
        selected = bot.admin_add_data[user_id].get('selected_profiles', [])
        if not selected:
            bot.answer_callback_query(call.id, "❌ Выберите хотя бы один профиль")
            return
        bot.admin_add_data[user_id]['profiles'] = ", ".join(selected)
        bot.admin_add_data[user_id]['services'] = ", ".join(selected)
        bot.admin_add_data[user_id]['service'] = selected[0]
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        admin_ask_experience(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id, "✅ Профили сохранены")
    else:
        profile_name = PROFILES_DICT.get(data)
        if not profile_name:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        selected = bot.admin_add_data[user_id].get('selected_profiles', [])
        if profile_name in selected:
            selected.remove(profile_name)
        else:
            selected.append(profile_name)
        bot.admin_add_data[user_id]['selected_profiles'] = selected
        admin_ask_profiles(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)

def admin_ask_experience(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for code, name in EXPERIENCE_OPTIONS:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"admin_exp_{code}"))
    bot.send_message(chat_id, "⏱️ **Шаг 5 из 14**\n\nВыберите опыт работы мастера:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_exp_'))
def admin_experience_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    code = call.data[10:]
    if code == "custom":
        bot.edit_message_text("⏱️ Введите опыт работы текстом:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(call.message, admin_process_custom_experience, user_id)
        bot.answer_callback_query(call.id)
    else:
        exp_map = {k:v for k,v in EXPERIENCE_OPTIONS if k!="custom"}
        bot.admin_add_data[user_id]['experience'] = exp_map[code]
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        admin_ask_districts(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)

def admin_process_custom_experience(message, user_id):
    if message.from_user.id != ADMIN_ID:
        return
    exp = safe_text(message)
    if not exp:
        bot.send_message(message.chat.id, "❌ Введите опыт.")
        bot.register_next_step_handler(message, admin_process_custom_experience, user_id)
        return
    bot.admin_add_data[user_id]['experience'] = exp
    admin_ask_districts(message.chat.id, user_id)

def admin_ask_districts(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    if 'selected_districts' not in bot.admin_add_data[user_id]:
        bot.admin_add_data[user_id]['selected_districts'] = []
    selected = bot.admin_add_data[user_id]['selected_districts']
    for code, name in DISTRICTS:
        prefix = "✅ " if name in selected else ""
        markup.add(types.InlineKeyboardButton(f"{prefix}{name}", callback_data=f"admin_dist_{code}"))
    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="admin_dist_done"))
    bot.send_message(chat_id, "📍 **Шаг 6 из 14**\n\nВыберите районы работы мастера (можно несколько):", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_dist_'))
def admin_district_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    data = call.data[11:]
    if data == "done":
        selected = bot.admin_add_data[user_id].get('selected_districts', [])
        if not selected:
            bot.answer_callback_query(call.id, "❌ Выберите хотя бы один район")
            return
        bot.admin_add_data[user_id]['districts'] = ", ".join(selected)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        admin_ask_price_min(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id, "✅ Районы сохранены")
    else:
        district_name = DISTRICTS_DICT.get(data)
        if not district_name:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        selected = bot.admin_add_data[user_id].get('selected_districts', [])
        if district_name in selected:
            selected.remove(district_name)
        else:
            selected.append(district_name)
        bot.admin_add_data[user_id]['selected_districts'] = selected
        admin_ask_districts(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)

def admin_ask_price_min(chat_id, user_id):
    msg = bot.send_message(chat_id, "💰 **Шаг 7 из 14**\n\nВведите **минимальную цену заказа** (например: 1000₽, договорная):")
    bot.register_next_step_handler(msg, admin_process_price_min, user_id)

def admin_process_price_min(message, user_id):
    if message.from_user.id != ADMIN_ID:
        return
    price_min = safe_text(message)
    if not price_min:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите минимальную цену.")
        bot.register_next_step_handler(message, admin_process_price_min, user_id)
        return
    bot.admin_add_data[user_id]['price_min'] = price_min
    bot.admin_add_data[user_id]['price_max'] = ''
    admin_ask_payment_methods(message.chat.id, user_id)

def admin_ask_payment_methods(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    if 'selected_payments' not in bot.admin_add_data[user_id]:
        bot.admin_add_data[user_id]['selected_payments'] = []
    selected = bot.admin_add_data[user_id]['selected_payments']
    for code, name in PAYMENT_METHODS:
        prefix = "✅ " if name in selected else ""
        markup.add(types.InlineKeyboardButton(f"{prefix}{name}", callback_data=f"admin_pay_{code}"))
    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="admin_pay_done"))
    bot.send_message(chat_id, "💳 **Шаг 8 из 14**\n\nКакие способы оплаты принимает мастер? (можно несколько)", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_pay_'))
def admin_payment_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    data = call.data[10:]
    if data == "done":
        selected = bot.admin_add_data[user_id].get('selected_payments', [])
        bot.admin_add_data[user_id]['payment_methods'] = ", ".join(selected)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        admin_ask_bio(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id, "✅ Способы оплаты сохранены")
    else:
        pay_name = PAYMENT_DICT.get(data)
        if not pay_name:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        selected = bot.admin_add_data[user_id].get('selected_payments', [])
        if pay_name in selected:
            selected.remove(pay_name)
        else:
            selected.append(pay_name)
        bot.admin_add_data[user_id]['selected_payments'] = selected
        admin_ask_payment_methods(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)

def admin_ask_bio(chat_id, user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="admin_skip_bio"))
    bot.send_message(chat_id, "📝 **Шаг 9 из 14**\n\n👇 **КОММЕНТАРИЙ О МАСТЕРЕ (кратко):**\n\nРасскажите о мастере пару слов.\n\n👉 **Или нажмите «Пропустить»**", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(chat_id, admin_process_bio, user_id)

@bot.callback_query_handler(func=lambda call: call.data == 'admin_skip_bio')
def admin_skip_bio_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    bot.admin_add_data[user_id]['bio'] = "Не указано"
    admin_ask_portfolio(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id, "⏩ Пропущено")

def admin_process_bio(message, user_id):
    if message.from_user.id != ADMIN_ID:
        return
    bio = safe_text(message)
    if not bio or bio.lower() == "пропустить":
        bio = "Не указано"
    bot.admin_add_data[user_id]['bio'] = bio
    admin_ask_portfolio(message.chat.id, user_id)

def admin_ask_portfolio(chat_id, user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="admin_skip_portfolio"))
    bot.send_message(chat_id, "📸 **Шаг 10 из 14**\n\n👇 **ССЫЛКА НА ПОРТФОЛИО МАСТЕРА:**\n\nЭто может быть ссылка на Яндекс.Диск, Google Фото, Telegram-канал с работами.\n\n👉 **Или нажмите «Пропустить»**", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(chat_id, admin_process_portfolio, user_id)

@bot.callback_query_handler(func=lambda call: call.data == 'admin_skip_portfolio')
def admin_skip_portfolio_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    bot.admin_add_data[user_id]['portfolio'] = "Не указано"
    admin_ask_documents_question(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id, "⏩ Пропущено")

def admin_process_portfolio(message, user_id):
    if message.from_user.id != ADMIN_ID:
        return
    portfolio = safe_text(message)
    if not portfolio or portfolio.lower() == "пропустить":
        portfolio = "Не указано"
    bot.admin_add_data[user_id]['portfolio'] = portfolio
    admin_ask_documents_question(message.chat.id, user_id)

def admin_ask_documents_question(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("✅ Да", callback_data="admin_doc_yes"),
        types.InlineKeyboardButton("❌ Нет", callback_data="admin_doc_no"),
        types.InlineKeyboardButton("⏩ Пропустить", callback_data="admin_doc_skip")
    )
    bot.send_message(chat_id, "📄 **Шаг 11 из 14**\n\nИспользует ли мастер документы (договор, акт и т.п.)?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_doc_'))
def admin_documents_question_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    choice = call.data.split('_')[2]
    if choice == 'yes':
        bot.admin_add_data[user_id]['documents'] = "Есть"
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        admin_ask_doc_types(call.message.chat.id, user_id)
    elif choice == 'no':
        bot.admin_add_data[user_id]['documents'] = "Нет"
        bot.admin_add_data[user_id]['documents_list'] = ""
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        admin_ask_contact_methods(call.message.chat.id, user_id)
    else:
        bot.admin_add_data[user_id]['documents'] = "Пропустить"
        bot.admin_add_data[user_id]['documents_list'] = ""
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        admin_ask_contact_methods(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)

def admin_ask_doc_types(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    if 'selected_docs' not in bot.admin_add_data[user_id]:
        bot.admin_add_data[user_id]['selected_docs'] = []
    selected = bot.admin_add_data[user_id]['selected_docs']
    for code, name in DOC_TYPES:
        prefix = "✅ " if name in selected else ""
        markup.add(types.InlineKeyboardButton(f"{prefix}{name}", callback_data=f"admin_doc_type_{code}"))
    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="admin_doc_type_done"))
    bot.send_message(chat_id, "📄 **Шаг 12 из 14**\n\nКакие документы может предоставить мастер? (можно несколько)", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_doc_type_'))
def admin_doc_type_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    data = call.data[15:]
    if data == "done":
        selected = bot.admin_add_data[user_id].get('selected_docs', [])
        bot.admin_add_data[user_id]['documents_list'] = ", ".join(selected)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        admin_ask_contact_methods(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id, "✅ Список документов сохранён")
    else:
        doc_name = DOC_TYPES_DICT.get(data)
        if not doc_name:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        selected = bot.admin_add_data[user_id].get('selected_docs', [])
        if doc_name in selected:
            selected.remove(doc_name)
        else:
            selected.append(doc_name)
        bot.admin_add_data[user_id]['selected_docs'] = selected
        admin_ask_doc_types(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)

def admin_ask_contact_methods(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    if 'selected_contacts' not in bot.admin_add_data[user_id]:
        bot.admin_add_data[user_id]['selected_contacts'] = []
    selected = bot.admin_add_data[user_id]['selected_contacts']
    for code, name in [("telegram","Telegram"), ("whatsapp","WhatsApp"), ("phone","Телефонный звонок")]:
        prefix = "✅ " if name in selected else ""
        markup.add(types.InlineKeyboardButton(f"{prefix}{name}", callback_data=f"admin_contact_{code}"))
    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="admin_contact_done"))
    bot.send_message(chat_id, "📞 **Шаг 13 из 14**\n\nВыберите способы связи мастера (можно несколько):", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_contact_'))
def admin_contact_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    data = call.data[14:]
    if data == "done":
        selected = bot.admin_add_data[user_id].get('selected_contacts', [])
        if not selected:
            bot.answer_callback_query(call.id, "❌ Выберите хотя бы один способ связи")
            return
        bot.admin_add_data[user_id]['preferred_contact'] = ", ".join(selected)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        admin_ask_phone(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id, "✅ Способы связи сохранены")
    else:
        contact_names = {"telegram":"Telegram","whatsapp":"WhatsApp","phone":"Телефонный звонок"}
        contact_name = contact_names.get(data)
        if not contact_name:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        selected = bot.admin_add_data[user_id].get('selected_contacts', [])
        if contact_name in selected:
            selected.remove(contact_name)
        else:
            selected.append(contact_name)
        bot.admin_add_data[user_id]['selected_contacts'] = selected
        admin_ask_contact_methods(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)

def admin_ask_phone(chat_id, user_id):
    bot.send_message(chat_id, "📞 **Шаг 14 из 14**\n\nВведите **контактный телефон мастера** (будет виден клиентам):")
    bot.register_next_step_handler_by_chat_id(chat_id, admin_process_phone, user_id)

def admin_process_phone(message, user_id):
    if message.from_user.id != ADMIN_ID:
        return
    phone = safe_text(message)
    if not phone:
        bot.send_message(message.chat.id, "❌ Пожалуйста, введите телефон.")
        bot.register_next_step_handler(message, admin_process_phone, user_id)
        return
    bot.admin_add_data[user_id]['phone'] = phone
    admin_show_summary(message, user_id)

def admin_show_summary(message, user_id):
    data = bot.admin_add_data[user_id]
    summary = f"""
📋 **Сводка данных мастера:**

👤 **Имя/Название:** {data['name']}
🔧 **Профили:** {data.get('profiles', '')}
🎂 **Возраст:** {data.get('age_group', 'Не указан')}
⏱ **Опыт:** {data['experience']}
📍 **Районы:** {data['districts']}
💰 **Минимальная цена:** {data['price_min']}
💳 **Оплата:** {data.get('payment_methods', 'Не указано')}
💬 **О себе:** {data.get('bio', 'Не указано')}
📸 **Портфолио:** {data.get('portfolio', 'Не указано')}
📄 **Документы:** {data.get('documents', 'Не указано')}
   **Список:** {data.get('documents_list', '')}
📞 **Предпочтительный контакт:** {data.get('preferred_contact', 'telegram')}
📞 **Телефон:** {data['phone']}
    """
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Сохранить мастера", callback_data=f"admin_save_{user_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="admin_cancel_add")
    )
    bot.send_message(message.chat.id, summary, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_save_'))
def admin_save_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    data = bot.admin_add_data.get(user_id)
    if not data:
        bot.answer_callback_query(call.id, "❌ Данные не найдены")
        return
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute('''INSERT INTO masters
                    (user_id, name, service, phone, districts, price_min, price_max,
                     experience, bio, portfolio, documents, entity_type, verification_type,
                     documents_list, payment_methods, preferred_contact, age_group,
                     source, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (0,
                     data['name'],
                     data.get('services', data.get('profiles', '')),
                     data['phone'],
                     data['districts'],
                     data['price_min'],
                     data.get('price_max', ''),
                     data['experience'],
                     data.get('bio', 'Не указано'),
                     data.get('portfolio', 'Не указано'),
                     data.get('documents', 'Не указано'),
                     data.get('entity_type', 'individual'),
                     'simple',
                     data.get('documents_list', ''),
                     data.get('payment_methods', ''),
                     data.get('preferred_contact', 'telegram'),
                     data.get('age_group', ''),
                     'manual',
                     'активен',
                     now))
    conn.commit()
    master_id = cursor.lastrowid
    bot.edit_message_text(f"✅ Мастер успешно добавлен в базу с ID {master_id}.", call.message.chat.id, call.message.message_id)
    publish_master_card(master_id, data['name'], data.get('services', data.get('profiles', '')),
                        data['districts'], data['price_min'], data['experience'],
                        data.get('bio', 'Не указано'), data.get('portfolio', 'Не указано'))
    del bot.admin_add_data[user_id]
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_cancel_add")
def admin_cancel_add_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    user_id = call.from_user.id
    if user_id in bot.admin_add_data:
        del bot.admin_add_data[user_id]
    bot.edit_message_text("❌ Добавление мастера отменено.", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

# ================ ЗАПУСК БОТА ================
if __name__ == '__main__':
    print("🚀 Бот запускается...")
    print(f"   Бот: @{BOT_USERNAME}")
    print(f"   Канал: @{CHANNEL_USERNAME}")
    print(f"   Админ: @{ADMIN_USERNAME}")
    print(f"   База данных: {DB_PATH}")

    try:
        if not check_bot_admin_in_chat(CHANNEL_ID):
            print(f"⚠️ Бот не является администратором канала {CHANNEL_ID}. Публикация заявок может не работать.")
    except:
        print("⚠️ Не удалось проверить права в канале.")

    if not is_night_time():
        publish_delayed_requests()

    reset_webhook()
    stop_other_instances()
    time.sleep(2)

    print("✅ Бот готов к работе. Запуск polling...")
    bot.infinity_polling(skip_pending=True)
