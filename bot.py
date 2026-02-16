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

CHANNEL_ID = os.environ.get('CHANNEL_ID', '-1003711282924')  # ID канала (числовой)
CHAT_ID = os.environ.get('CHAT_ID', "@remontvl25chat")          # общий чат
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
MASTER_CHAT_ID = os.environ.get('MASTER_CHAT_ID', '@remontvl25masters')
MASTER_CHAT_INVITE_LINK = os.environ.get('MASTER_CHAT_INVITE_LINK', '')

GOOGLE_FORMS_BASE = os.environ.get('GOOGLE_FORMS_BASE', '')
FORM_ENTRY_TG_ID = os.environ.get('FORM_ENTRY_TG_ID', '')
FORM_ENTRY_TG_USERNAME = os.environ.get('FORM_ENTRY_TG_USERNAME', '')

bot = telebot.TeleBot(TOKEN)

# ================ БАЗА ДАННЫХ ================
conn = sqlite3.connect('remont.db', check_same_thread=False)
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
                 chat_message_id INTEGER,
                 created_at TEXT)''')

# ----- Таблица отзывов -----
cursor.execute('''CREATE TABLE IF NOT EXISTS reviews
                (id INTEGER PRIMARY KEY,
                 master_name TEXT,
                 master_id INTEGER,
                 user_name TEXT,
                 user_id INTEGER,
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
                 master_id INTEGER,          -- id из таблицы masters
                 price TEXT,
                 comment TEXT,
                 status TEXT DEFAULT 'pending',  -- pending, accepted, rejected
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
    if message.text and (message.text.startswith('/') or '@remont_vl25_chat_bot' in message.text):
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
        text = "👋 **Режим: Гость**\n\n• Вы видите заявки в чате, но **не можете на них отвечать**.\n• Ваши контакты **не передаются** клиентам.\n• Хотите получать заказы? Нажмите «👷 Зарегистрироваться как мастер» и пройдите регистрацию."
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
            url="https://t.me/remont_vl25_chat_bot"
        ))
        bot.reply_to(
            message,
            "👋 Добро пожаловать в бот заявок на ремонт!\n\n"
            "📌 В этом чате я только публикую заявки и отзывы.\n\n"
            "👇 Вся работа со мной — в личных сообщениях:\n"
            "👉 @remont_vl25_chat_bot\n\n"
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
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🔨 Я клиент, ищу мастера", callback_data="role_client"),
            types.InlineKeyboardButton("👷 Я мастер", callback_data="role_master")
        )
        bot.send_message(
            message.chat.id,
            "👋 **Добро пожаловать!**\n\nКто вы? Выберите роль, чтобы мы могли предложить нужный функционал.",
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
            types.InlineKeyboardButton("✅ Полная регистрация (верификация)", callback_data="master_full"),
            types.InlineKeyboardButton("👀 Гостевой режим (только просмотр)", callback_data="master_guest")
        )
        bot.edit_message_text(
            "👷 **Регистрация мастера**\n\n"
            "Выберите, как вы хотите участвовать:\n\n"
            "✅ **Полная регистрация** – заполните анкету, после одобрения вы попадёте в базу и закрытый чат мастеров.\n"
            "👀 **Гостевой режим** – вы будете видеть заявки в чате, но не сможете на них отвечать. В любой момент можно зарегистрироваться.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data in ['master_full', 'master_guest'])
def master_registration_choice(call):
    user_id = call.from_user.id
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    if call.data == 'master_full':
        role = 'master'
        cursor.execute('INSERT OR REPLACE INTO users (user_id, role, first_seen, last_active) VALUES (?, ?, ?, ?)',
                       (user_id, 'master', now, now))
        conn.commit()
        bot.edit_message_text("✅ Роль сохранена: **Мастер**. Теперь заполните анкету.",
                              call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        become_master(call.message)
    else:
        role = 'guest'
        cursor.execute('INSERT OR REPLACE INTO users (user_id, role, first_seen, last_active) VALUES (?, ?, ?, ?)',
                       (user_id, 'guest', now, now))
        conn.commit()
        bot.edit_message_text(
            "👀 Вы вошли как **гость**.\n\n"
            "• Вы можете просматривать заявки в чате @remontvl25chat, но **не можете на них отвечать**.\n"
            "• Ваши контакты **не передаются** клиентам.\n"
            "• Хотите получать заказы? Нажмите «👷 Зарегистрироваться как мастер» в меню.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown'
        )
        show_role_menu(call.message, 'guest')
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
    become_master(message)

# ================ КНОПКА "КАНАЛ С МАСТЕРАМИ" ================
@bot.message_handler(func=lambda message: message.text == '📢 Канал с мастерами')
def channel_link(message):
    if not only_private(message):
        return
    try:
        chat = bot.get_chat(int(CHANNEL_ID) if str(CHANNEL_ID).lstrip('-').isdigit() else CHANNEL_ID)
        channel_name = chat.title or "канал"
        link = f"https://t.me/{chat.username}" if chat.username else "канал"
    except:
        channel_name = "канал"
        link = "канал"
    bot.send_message(
        message.chat.id,
        f"📢 **Наш канал:** {link}\n\n"
        "В канале публикуются только анонсы новых заявок, мастеров и отзывов.\n"
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

# ================ АНКЕТА МАСТЕРА (13 шагов) ================
if not hasattr(bot, 'master_data'):
    bot.master_data = {}

@bot.message_handler(commands=['become_master'])
@bot.message_handler(func=lambda message: message.text == '👷 Заполнить анкету')
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
        "Шаг 1 из 13\n"
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

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Полная регистрация", callback_data="verif_full"),
        types.InlineKeyboardButton("🔹 Упрощённое размещение", callback_data="verif_simple")
    )
    bot.edit_message_text(
        f"👷 **ЗАПОЛНЕНИЕ АНКЕТЫ МАСТЕРА**\n\n"
        f"Шаг 2 из 13\n"
        f"👇 **ВЫБЕРИТЕ ТИП РАЗМЕЩЕНИЯ:**\n\n"
        f"✅ **Полная регистрация** – вы заполняете все данные, после проверки попадёте в базу и чат мастеров.\n"
        f"🔹 **Упрощённое размещение** – вы сразу попадаете в базу (без проверки), но не будете получать уведомления о заявках. В любой момент можно пройти полную регистрацию.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data in ['verif_full', 'verif_simple'])
def verif_choice_callback(call):
    verif_type = call.data.split('_')[1]
    user_id = call.from_user.id
    if user_id not in bot.master_data:
        bot.master_data[user_id] = {}
    bot.master_data[user_id]['verification_type'] = verif_type

    if bot.master_data[user_id].get('entity_type') == 'individual':
        question = "👤 **ВВЕДИТЕ ВАШЕ ИМЯ:**"
    else:
        question = "🏢 **ВВЕДИТЕ НАЗВАНИЕ КОМПАНИИ ИЛИ БРИГАДЫ:**"

    bot.edit_message_text(
        f"👷 **ЗАПОЛНЕНИЕ АНКЕТЫ МАСТЕРА**\n\n"
        f"Шаг 3 из 13\n"
        f"👇 {question}",
        call.message.chat.id,
        call.message.message_id
    )
    bot.register_next_step_handler(call.message, process_master_name, 
                                   bot.master_data[user_id]['entity_type'], verif_type)
    bot.answer_callback_query(call.id)

def process_master_name(message, entity_type, verif_type):
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
    bot.master_data[user_id]['entity_type'] = entity_type
    bot.master_data[user_id]['verification_type'] = verif_type

    msg = bot.send_message(
        message.chat.id,
        "👷 **Шаг 4 из 13**\n\n"
        "👇 **ВЫБЕРИТЕ СПЕЦИАЛИЗАЦИЮ:**\n\n"
        "Введите цифру или название:\n"
        "1 - Сантехник\n"
        "2 - Электрик\n"
        "3 - Отделочник\n"
        "4 - Строитель\n"
        "5 - Сварщик\n"
        "6 - Разнорабочий\n"
        "7 - Другое\n"
        "8 - Дизайнер интерьера\n\n"
        "👉 Пример: `1` или `сантехник`"
    )
    bot.register_next_step_handler(msg, process_master_service, name, entity_type, verif_type)

def process_master_service(message, name, entity_type, verif_type):
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
    elif service_input == "7" or "другое" in service_input:
        service = "Другое"
    elif service_input == "8" or "дизайнер" in service_input:
        service = "Дизайнер интерьера"
    else:
        service = text.capitalize()

    user_id = message.from_user.id
    bot.master_data[user_id]['service'] = service

    msg = bot.send_message(
        message.chat.id,
        "📞 **Шаг 5 из 13**\n\n"
        "👇 **ВВЕДИТЕ ВАШ ТЕЛЕФОН:**\n\n"
        "Пример: +7 924 123-45-67\n\n"
        "⚠️ Номер будет виден ТОЛЬКО администратору"
    )
    bot.register_next_step_handler(msg, process_master_phone, name, service, entity_type, verif_type)

def process_master_phone(message, name, service, entity_type, verif_type):
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
        "📍 **Шаг 6 из 13**\n\n"
        "👇 **В КАКИХ РАЙОНАХ/ЖК ВЫ РАБОТАЕТЕ?**\n\n"
        "Перечислите через запятую:\n"
        "Пример: Патрокл, Снеговая Падь, Варяг, Океан"
    )
    bot.register_next_step_handler(msg, process_master_districts, name, service, phone, entity_type, verif_type)

def process_master_districts(message, name, service, phone, entity_type, verif_type):
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
        "💰 **Шаг 7 из 13**\n\n"
        "👇 **МИНИМАЛЬНАЯ ЦЕНА ЗАКАЗА:**\n\n"
        "Пример: 1000₽, 5000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_min, name, service, phone, districts, entity_type, verif_type)

def process_master_price_min(message, name, service, phone, districts, entity_type, verif_type):
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
        "💰 **Шаг 8 из 13**\n\n"
        "👇 **МАКСИМАЛЬНАЯ ЦЕНА ЗАКАЗА:**\n\n"
        "Пример: 50000₽, 100000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_max, name, service, phone, districts, price_min, entity_type, verif_type)

def process_master_price_max(message, name, service, phone, districts, price_min, entity_type, verif_type):
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
        "⏱️ **Шаг 9 из 13**\n\n"
        "👇 **ВАШ ОПЫТ РАБОТЫ:**\n\n"
        "Пример: 3 года, 5 лет, 10+ лет"
    )
    bot.register_next_step_handler(msg, process_master_experience, name, service, phone, districts, price_min, price_max, entity_type, verif_type)

def process_master_experience(message, name, service, phone, districts, price_min, price_max, entity_type, verif_type):
    if message.chat.type != 'private':
        return
    experience = safe_text(message)
    if not experience:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите опыт работы.")
        return
    user_id = message.from_user.id
    bot.master_data[user_id]['experience'] = experience

    user_data = {
        'name': name,
        'service': service,
        'phone': phone,
        'districts': districts,
        'price_min': price_min,
        'price_max': price_max,
        'experience': experience,
        'entity_type': entity_type,
        'verification_type': verif_type
    }
    bot.master_data[user_id].update(user_data)

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="skip_bio"))
    bot.send_message(
        message.chat.id,
        "📝 **Шаг 10 из 13**\n\n"
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
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="skip_portfolio"))
    bot.edit_message_text(
        "📸 **Шаг 11 из 13**\n\n"
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
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="skip_portfolio"))
    bot.send_message(
        message.chat.id,
        "📸 **Шаг 11 из 13**\n\n"
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
        "📄 **Шаг 12 из 13**\n\n"
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
    verification_type = user_data['verification_type']

    cursor.execute('''INSERT INTO master_applications
                    (user_id, username, name, service, phone, districts, 
                     price_min, price_max, experience, bio, portfolio, documents,
                     entity_type, verification_type, source, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id,
                     message.from_user.username or "no_username",
                     name, service, phone, districts,
                     price_min, price_max, experience, bio, portfolio, documents,
                     entity_type, verification_type, 'bot',
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

{entity_display}
👤 **Имя/Название:** {name}
🔧 **Специализация:** {service}
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

# ================ РАСШИРЕННАЯ РЕКОМЕНДАЦИЯ МАСТЕРА ================
if not hasattr(bot, 'recommend_data'):
    bot.recommend_data = {}

@bot.message_handler(commands=['recommend'])
@bot.message_handler(func=lambda message: message.text == '👍 Рекомендовать мастера')
def recommend_master(message):
    if not only_private(message):
        return
    # Проверяем, что пользователь имеет роль клиента
    user_id = message.from_user.id
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row or row[0] != 'client':
        bot.send_message(message.chat.id, "❌ Только клиенты могут рекомендовать мастеров.")
        return

    msg = bot.send_message(
        message.chat.id,
        "👍 **РЕКОМЕНДАЦИЯ МАСТЕРА**\n\n"
        "Шаг 1 из 7\n"
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
    user_id = message.from_user.id
    bot.recommend_data[user_id] = {'master_name': name}

    msg = bot.send_message(
        message.chat.id,
        "🔨 **Шаг 2 из 7**\n\n"
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
    user_id = message.from_user.id
    bot.recommend_data[user_id]['service'] = service

    msg = bot.send_message(
        message.chat.id,
        "📞 **Шаг 3 из 7**\n\n"
        "👇 **КОНТАКТ МАСТЕРА** (телефон / Telegram):"
    )
    bot.register_next_step_handler(msg, process_recommend_contact, name, service)

def process_recommend_contact(message, name, service):
    if message.chat.type != 'private':
        return
    contact = safe_text(message)
    if not contact:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите контакт.")
        return
    user_id = message.from_user.id
    bot.recommend_data[user_id]['contact'] = contact

    msg = bot.send_message(
        message.chat.id,
        "📝 **Шаг 4 из 7**\n\n"
        "👇 **ОПИШИТЕ ВЫПОЛНЕННЫЕ РАБОТЫ:**\n\n"
        "Например: замена смесителя, укладка плитки в ванной."
    )
    bot.register_next_step_handler(msg, process_recommend_description, name, service, contact)

def process_recommend_description(message, name, service, contact):
    if message.chat.type != 'private':
        return
    description = safe_text(message)
    if not description:
        description = "Не указано"
    user_id = message.from_user.id
    bot.recommend_data[user_id]['description'] = description

    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("💸 Дорого", callback_data="price_expensive"),
        types.InlineKeyboardButton("💰 Средне", callback_data="price_medium"),
        types.InlineKeyboardButton("🪙 Дешево", callback_data="price_cheap")
    )
    bot.send_message(
        message.chat.id,
        "💰 **Шаг 5 из 7**\n\n"
        "👇 **ОЦЕНИТЕ ЦЕНУ:**",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('price_'))
def price_callback(call):
    price_level = call.data.split('_')[1]
    user_id = call.from_user.id
    if not hasattr(bot, 'recommend_data') or user_id not in bot.recommend_data:
        bot.answer_callback_query(call.id, "❌ Ошибка, начните заново.")
        return
    bot.recommend_data[user_id]['price_level'] = price_level
    bot.edit_message_text(
        "😊 **Шаг 6 из 7**\n\n"
        "👇 **ВЫ ДОВОЛЬНЫ РАБОТОЙ?**",
        call.message.chat.id,
        call.message.message_id
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Доволен", callback_data="satisfied_yes"),
        types.InlineKeyboardButton("❌ Не доволен", callback_data="satisfied_no")
    )
    bot.send_message(call.message.chat.id, "Выберите:", reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('satisfied_'))
def satisfied_callback(call):
    satisfaction = call.data.split('_')[1]
    user_id = call.from_user.id
    if not hasattr(bot, 'recommend_data') or user_id not in bot.recommend_data:
        bot.answer_callback_query(call.id, "❌ Ошибка, начните заново.")
        return
    bot.recommend_data[user_id]['satisfaction'] = satisfaction
    bot.edit_message_text(
        "👍 **Шаг 7 из 7**\n\n"
        "👇 **ВЫ РЕКОМЕНДУЕТЕ ЭТОГО МАСТЕРА?**",
        call.message.chat.id,
        call.message.message_id
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Да", callback_data="recommend_yes"),
        types.InlineKeyboardButton("❌ Нет", callback_data="recommend_no")
    )
    bot.send_message(call.message.chat.id, "Выберите:", reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('recommend_'))
def recommend_final_callback(call):
    recommend = call.data.split('_')[1]
    user_id = call.from_user.id
    if not hasattr(bot, 'recommend_data') or user_id not in bot.recommend_data:
        bot.answer_callback_query(call.id, "❌ Ошибка, начните заново.")
        return
    data = bot.recommend_data[user_id]
    data['recommend'] = recommend

    cursor.execute('''INSERT INTO recommendations
                    (user_id, username, master_name, service, contact, description,
                     price_level, satisfaction, recommend, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id,
                     call.from_user.username or "no_username",
                     data['master_name'],
                     data['service'],
                     data['contact'],
                     data['description'],
                     data['price_level'],
                     data['satisfaction'],
                     data['recommend'],
                     'на модерации',
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    rec_id = cursor.lastrowid

    admin_msg = f"""
👍 **НОВАЯ РЕКОМЕНДАЦИЯ МАСТЕРА (РАСШИРЕННАЯ)!** (ID: {rec_id})

👤 **Рекомендует:** @{call.from_user.username or "нет"}
🛠 **Мастер:** {data['master_name']}
🔧 **Специализация:** {data['service']}
📞 **Контакт:** {data['contact']}
📝 **Описание работ:** {data['description']}
💰 **Цена:** {data['price_level']}
😊 **Удовлетворён:** {data['satisfaction']}
👍 **Рекомендует:** {data['recommend']}

✅ **Добавить на проверку:** /add_from_rec {rec_id}
❌ **Отклонить:** /reject_rec {rec_id}
    """
    try:
        if ADMIN_ID != 0:
            bot.send_message(ADMIN_ID, admin_msg)
    except:
        pass

    bot.edit_message_text(
        "✅ **СПАСИБО ЗА РЕКОМЕНДАЦИЮ!**\n\n"
        "Администратор проверит данные и, если всё хорошо, добавит мастера в базу.",
        call.message.chat.id,
        call.message.message_id
    )
    del bot.recommend_data[user_id]
    bot.answer_callback_query(call.id)

# ================ КОМАНДЫ ДЛЯ РЕКОМЕНДАЦИЙ ИЗ ЧАТА (лайки/комментарии) ================
@bot.message_handler(commands=['like'])
def like_recommendation(message):
    if not only_private(message):
        return
    try:
        rec_id = int(message.text.split()[1])
        user_id = message.from_user.id
        cursor.execute('SELECT id FROM client_recommendations WHERE id = ? AND status = "approved"', (rec_id,))
        if not cursor.fetchone():
            bot.reply_to(message, "❌ Рекомендация не найдена или ещё не одобрена.")
            return
        cursor.execute('INSERT OR IGNORE INTO rec_likes (rec_id, user_id, created_at) VALUES (?, ?, ?)',
                       (rec_id, user_id, datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()
        bot.reply_to(message, f"❤️ Вы поставили лайк рекомендации {rec_id}.")
    except Exception as e:
        bot.reply_to(message, f"❌ Используйте: /like [ID]. Ошибка: {e}")

@bot.message_handler(commands=['comment'])
def comment_recommendation(message):
    if not only_private(message):
        return
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            bot.reply_to(message, "❌ Используйте: /comment [ID] [ваш текст]")
            return
        rec_id = int(parts[1])
        comment = parts[2]
        user_id = message.from_user.id
        username = message.from_user.username or "no_username"

        cursor.execute('SELECT id FROM client_recommendations WHERE id = ? AND status = "approved"', (rec_id,))
        if not cursor.fetchone():
            bot.reply_to(message, "❌ Рекомендация не найдена или ещё не одобрена.")
            return

        cursor.execute('''INSERT INTO rec_comments (rec_id, user_id, username, comment, created_at)
                          VALUES (?, ?, ?, ?, ?)''',
                       (rec_id, user_id, username, comment,
                        datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()
        bot.reply_to(message, f"💬 Ваш комментарий добавлен к рекомендации {rec_id}.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ================ РЕКОМЕНДАЦИИ ЧЕРЕЗ ХЕШТЕГИ В ЧАТЕ ================
@bot.message_handler(func=lambda message: message.chat.type != 'private')
def handle_chat_recommendations(message):
    print(f"🔍 Сообщение в группе: {message.text}")
    if message.text and message.text.startswith('/'):
        return
    text = message.text.strip()
    if not text:
        return
    match = re.search(r'#рекомендую_([a-zA-Zа-яА-ЯёЁ0-9_]+)', text, re.IGNORECASE)
    if not match:
        return
    hashtag = match.group(1).lower()

    # Проверяем роль пользователя
    user_id = message.from_user.id
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row or row[0] != 'client':
        # Не клиент – удаляем сообщение (если бот админ) и игнорируем
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        return

    if re.match(r'^\s*#рекомендую_\S+\s*$', text):
        show_recommendations_by_hashtag(message, hashtag)
        return
    save_chat_recommendation(message, hashtag)

def save_chat_recommendation(message, hashtag):
    text = message.text
    contact_match = re.search(r'(@[a-zA-Z0-9_]+|\+?\d[\d\s\-\(\)]{7,})', text)
    contact = contact_match.group(0) if contact_match else "Не указан"
    description = text

    cursor.execute('''INSERT INTO client_recommendations
                    (user_id, username, message_id, hashtag, contact, description, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (message.from_user.id,
                     message.from_user.username or "no_username",
                     message.message_id,
                     hashtag,
                     contact,
                     description,
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    rec_id = cursor.lastrowid

    admin_msg = f"""
🆕 **Новая рекомендация в чате!**
👤 От: @{message.from_user.username or "нет"}
🏷 Хештег: #рекомендую_{hashtag}
📞 Контакт: {contact}
📝 Описание: {description[:100]}...
🆔 Сообщение: {message.message_id}

✅ Одобрить: /approve_rec {rec_id}
❌ Отклонить: /reject_rec {rec_id}
    """
    try:
        if ADMIN_ID != 0:
            bot.send_message(ADMIN_ID, admin_msg)
    except:
        pass

    bot.reply_to(message, "✅ Ваша рекомендация сохранена и отправлена на модерацию. Спасибо!")

def show_recommendations_by_hashtag(message, hashtag):
    cursor.execute('''
        SELECT id, username, contact, description, created_at
        FROM client_recommendations
        WHERE hashtag = ? AND status = 'approved'
        ORDER BY created_at DESC
        LIMIT 20
    ''', (hashtag,))
    rows = cursor.fetchall()
    if not rows:
        bot.reply_to(message, f"❌ Пока нет одобренных рекомендаций по тегу #рекомендую_{hashtag}.")
        return

    reply = f"📌 **Рекомендации по тегу #рекомендую_{hashtag}:**\n\n"
    for rec in rows:
        rec_id, user, contact, desc, date = rec
        cursor.execute('SELECT COUNT(*) FROM rec_likes WHERE rec_id = ?', (rec_id,))
        likes = cursor.fetchone()[0]
        cursor.execute('''
            SELECT username, comment FROM rec_comments 
            WHERE rec_id = ? ORDER BY created_at DESC LIMIT 3
        ''', (rec_id,))
        comments = cursor.fetchall()
        reply += f"• От @{user}:\n  {desc}\n  📞 Контакт: {contact}\n  🕒 {date}\n  ❤️ {likes}\n"
        if comments:
            reply += "  💬 Комментарии:\n"
            for cu, cmt in comments:
                reply += f"    – @{cu}: {cmt[:50]}...\n"
        reply += "\n"
    reply += "\n_Чтобы поставить лайк, напишите /like ID_  \n_Чтобы оставить комментарий, напишите /comment ID ваш_текст_"
    bot.reply_to(message, reply, parse_mode='Markdown')

# ================ АДМИН-КОМАНДЫ ДЛЯ РЕКОМЕНДАЦИЙ ================
@bot.message_handler(commands=['list_recs'])
def list_recommendations(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    cursor.execute('''
        SELECT id, username, hashtag, contact, description, created_at
        FROM client_recommendations
        WHERE status = 'new'
        ORDER BY created_at DESC
        LIMIT 20
    ''')
    rows = cursor.fetchall()
    if not rows:
        bot.reply_to(message, "✅ Новых рекомендаций нет.")
        return
    text = "📋 **Новые рекомендации:**\n\n"
    for r in rows:
        text += f"ID {r[0]}: @{r[1]} | #{r[2]}\nКонтакт: {r[3]}\n{r[4][:50]}...\nОдобрить: /approve_rec {r[0]}\nОтклонить: /reject_rec {r[0]}\n\n"
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['approve_rec'])
def approve_rec(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    try:
        rec_id = int(message.text.split()[1])
        cursor.execute('UPDATE client_recommendations SET status = "approved" WHERE id = ?', (rec_id,))
        conn.commit()
        bot.reply_to(message, f"✅ Рекомендация {rec_id} одобрена.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: используйте /approve_rec [ID]. {e}")

@bot.message_handler(commands=['reject_rec'])
def reject_rec(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    try:
        rec_id = int(message.text.split()[1])
        cursor.execute('UPDATE client_recommendations SET status = "rejected" WHERE id = ?', (rec_id,))
        conn.commit()
        bot.reply_to(message, f"❌ Рекомендация {rec_id} отклонена.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: используйте /reject_rec [ID]. {e}")

@bot.message_handler(commands=['promote_rec'])
def promote_recommendation(message):
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
                        (user_id, username, name, service, phone, districts, price_min, price_max,
                         experience, bio, portfolio, documents, entity_type, verification_type, source, status, created_at)
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

# ================ КОМАНДЫ ДЛЯ ПЛАТНОЙ ПОДПИСКИ (пока не используются) ================
@bot.message_handler(commands=['subscribe'])
def subscribe(message):
    if not only_private(message):
        return
    bot.reply_to(message, "ℹ️ В данный момент подписка не требуется. Все функции бесплатны.")

# ================ НОВЫЙ МЕХАНИЗМ ЗАЯВОК ================
if not hasattr(bot, 'request_temp'):
    bot.request_temp = {}

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

    user_id = message.from_user.id
    bot.request_temp[user_id] = {
        'service': service,
        'description': description,
        'district': district,
        'date': date,
        'budget': budget
    }

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔓 Публичная (в канале)", callback_data="req_public"),
        types.InlineKeyboardButton("🔒 Приватная (только мастерам)", callback_data="req_private")
    )
    bot.send_message(
        message.chat.id,
        "Выберите тип заявки:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('req_'))
def request_type_callback(call):
    is_public = 1 if call.data == 'req_public' else 0
    user_id = call.from_user.id
    if user_id not in bot.request_temp:
        bot.answer_callback_query(call.id, "❌ Ошибка, начните заново.")
        return

    data = bot.request_temp[user_id]
    data['is_public'] = is_public

    # Сохраняем заявку в БД
    cursor.execute('''INSERT INTO requests 
                    (user_id, username, service, description, district, date, budget, status, is_public, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id,
                     call.from_user.username or "",
                     data['service'], data['description'], data['district'], data['date'], data['budget'],
                     'активна', is_public,
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    request_id = cursor.lastrowid

    # Анонимный псевдоним для клиента
    client_alias = f"Клиент #{request_id % 10000}"
    request_text = f"""
🆕 **НОВАЯ ЗАЯВКА!**

👤 **От:** {client_alias}
🔨 **Услуга:** {data['service']}
📝 **Задача:** {data['description']}
📍 **Район/ЖК:** {data['district']}
📅 **Когда:** {data['date']}
💰 **Бюджет:** {data['budget']}
"""

    if is_public:
        target_chat = int(CHANNEL_ID) if str(CHANNEL_ID).lstrip('-').isdigit() else CHANNEL_ID
        extra_text = "\n📢 Публичная заявка. Откликнуться можно в боте: @remont_vl25_chat_bot"
    else:
        target_chat = MASTER_CHAT_ID
        extra_text = "\n🔒 Приватная заявка. Откликнуться можно в боте: @remont_vl25_chat_bot"

    request_text += extra_text

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "📩 Откликнуться в боте",
        url="https://t.me/remont_vl25_chat_bot"
    ))

    try:
        bot.send_message(target_chat, request_text, reply_markup=markup)
        # Если заявка публичная, дублируем в мастер-чат
        if is_public:
            bot.send_message(MASTER_CHAT_ID, request_text, reply_markup=markup)
    except Exception as e:
        print(f"Ошибка публикации заявки: {e}")

    bot.send_message(
        call.message.chat.id,
        "✅ **ЗАЯВКА СОЗДАНА!**\n\n"
        "Мы оповестили мастеров. Когда кто-то откликнется, вы получите уведомление.\n\n"
        "Если никто не откликнется, вы можете посмотреть рекомендации других клиентов:",
        reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("👥 Рекомендации мастеров", callback_data=f"show_recs_{data['service']}")
        )
    )

    # Рассылаем уведомления мастерам (без контактов, с кнопкой отклика)
    notify_masters_about_new_request(request_id, data)

    show_role_menu(call.message, 'client')
    del bot.request_temp[user_id]
    bot.answer_callback_query(call.id)

def notify_masters_about_new_request(request_id, request_data):
    service = request_data['service']
    cursor.execute('''
        SELECT DISTINCT user_id FROM masters 
        WHERE service = ? AND status = 'активен'
    ''', (service,))
    masters = cursor.fetchall()
    if not masters:
        return

    text = f"""
📩 **Новая заявка по вашей специализации!**

🔨 **Услуга:** {service}
📝 **Задача:** {request_data['description']}
📍 **Район/ЖК:** {request_data['district']}
📅 **Когда:** {request_data['date']}
💰 **Бюджет:** {request_data['budget']}

💬 Нажмите кнопку ниже, чтобы откликнуться и предложить свою цену.
    """
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "💰 Откликнуться",
        callback_data=f"respond_{request_id}"
    ))

    for (master_id,) in masters:
        try:
            bot.send_message(master_id, text, reply_markup=markup)
        except Exception as e:
            print(f"Не удалось отправить уведомление мастеру {master_id}: {e}")

# ================ ПЕРСОНАЛЬНАЯ ЗАЯВКА ИЗ КАРТОЧКИ МАСТЕРА ================
@bot.callback_query_handler(func=lambda call: call.data.startswith('request_to_master_'))
def request_to_master_callback(call):
    master_id = int(call.data.split('_')[3])
    cursor.execute('SELECT user_id, service FROM masters WHERE id = ?', (master_id,))
    master = cursor.fetchone()
    if not master:
        bot.answer_callback_query(call.id, "❌ Мастер не найден.")
        return
    master_user_id, service = master
    user_id = call.from_user.id

    if not hasattr(bot, 'request_data'):
        bot.request_data = {}
    bot.request_data[user_id] = {
        'master_id': master_user_id,
        'service': service,
        'is_personal': True
    }

    bot.edit_message_text(
        "🔨 **СОЗДАНИЕ ПЕРСОНАЛЬНОЙ ЗАЯВКИ**\n\n"
        "Опишите задачу, которую нужно выполнить этому мастеру:",
        call.message.chat.id,
        call.message.message_id
    )
    bot.register_next_step_handler(call.message, process_personal_description, master_user_id, service)
    bot.answer_callback_query(call.id)

def process_personal_description(message, master_user_id, service):
    if message.chat.type != 'private':
        return
    description = safe_text(message)
    if not description:
        bot.send_message(message.chat.id, "❌ Пожалуйста, опишите задачу.")
        return
    user_id = message.from_user.id
    if not hasattr(bot, 'request_data'):
        bot.request_data = {}
    bot.request_data[user_id]['description'] = description

    msg = bot.send_message(
        message.chat.id,
        "📍 **Укажите район или ЖК:**\n"
        "Например: Патрокл, Снеговая Падь, Варяг, Океан"
    )
    bot.register_next_step_handler(msg, process_personal_district, master_user_id, service, description)

def process_personal_district(message, master_user_id, service, description):
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
        "📅 **Когда нужно выполнить работы?**\n"
        "Например: Сегодня вечером, Завтра с 10:00, На этой неделе, Дата договорная"
    )
    bot.register_next_step_handler(msg, process_personal_date, master_user_id, service, description, district)

def process_personal_date(message, master_user_id, service, description, district):
    if message.chat.type != 'private':
        return
    date = safe_text(message)
    if not date:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите дату.")
        return
    user_id = message.from_user.id
    bot.request_data[user_id]['date'] = date

    msg = bot.send_message(
        message.chat.id,
        "💰 **Ваш бюджет:**\n"
        "Например: до 3000₽, договорной, 50000₽ за квартиру"
    )
    bot.register_next_step_handler(msg, process_personal_budget, master_user_id, service, description, district, date)

def process_personal_budget(message, master_user_id, service, description, district, date):
    if message.chat.type != 'private':
        return
    budget = safe_text(message)
    if not budget:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите бюджет.")
        return
    user_id = message.from_user.id
    data = bot.request_data[user_id]

    cursor.execute('''INSERT INTO requests 
                    (user_id, username, service, description, district, date, budget, status, is_public, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id,
                     message.from_user.username or "",
                     service, description, district, date, budget,
                     'активна', 0,
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    request_id = cursor.lastrowid

    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "💰 Откликнуться",
            callback_data=f"respond_{request_id}"
        ))
        bot.send_message(
            master_user_id,
            f"📩 **Персональная заявка для вас!**\n\n"
            f"🔨 **Услуга:** {service}\n"
            f"📝 **Задача:** {description}\n"
            f"📍 **Район:** {district}\n"
            f"📅 **Когда:** {date}\n"
            f"💰 **Бюджет:** {budget}\n\n"
            f"Нажмите кнопку, чтобы откликнуться и предложить свою цену.",
            reply_markup=markup
        )
    except Exception as e:
        print(f"Не удалось отправить уведомление мастеру: {e}")

    bot.send_message(
        message.chat.id,
        "✅ **Ваша заявка отправлена мастеру!**\n"
        "Когда он откликнется, вы получите уведомление."
    )
    show_role_menu(message, 'client')
    del bot.request_data[user_id]

# ================ ОТКЛИКИ МАСТЕРОВ ================
if not hasattr(bot, 'response_temp'):
    bot.response_temp = {}

@bot.callback_query_handler(func=lambda call: call.data.startswith('respond_'))
def respond_callback(call):
    request_id = int(call.data.split('_')[1])
    master_id = call.from_user.id

    cursor.execute('SELECT id FROM masters WHERE user_id = ? AND status = "активен"', (master_id,))
    master_row = cursor.fetchone()
    if not master_row:
        bot.answer_callback_query(call.id, "❌ Вы не зарегистрированы как мастер.")
        return
    master_db_id = master_row[0]

    bot.response_temp[master_id] = {
        'request_id': request_id,
        'master_db_id': master_db_id
    }

    bot.edit_message_text(
        "💰 **Укажите вашу цену за выполнение работы:**\n"
        "(например: 3000₽, 5000₽, договорная)",
        call.message.chat.id,
        call.message.message_id
    )
    bot.register_next_step_handler(call.message, process_response_price, request_id, master_db_id)
    bot.answer_callback_query(call.id)

def process_response_price(message, request_id, master_db_id):
    if message.chat.type != 'private':
        return
    price = safe_text(message)
    if not price:
        bot.send_message(message.chat.id, "❌ Пожалуйста, укажите цену.")
        return
    master_id = message.from_user.id
    bot.response_temp[master_id]['price'] = price

    msg = bot.send_message(
        message.chat.id,
        "📝 **Добавьте комментарий (необязательно):**\n"
        "(например: могу приступить сегодня, работаю с материалами заказчика и т.д.)\n"
        "Или отправьте /skip, чтобы пропустить."
    )
    bot.register_next_step_handler(msg, process_response_comment, request_id, master_db_id, price)

def process_response_comment(message, request_id, master_db_id, price):
    if message.chat.type != 'private':
        return
    master_id = message.from_user.id
    if message.text == '/skip':
        comment = ''
    else:
        comment = safe_text(message)
        if not comment:
            comment = ''

    cursor.execute('''INSERT INTO responses
                    (request_id, master_id, price, comment, created_at)
                    VALUES (?, ?, ?, ?, ?)''',
                    (request_id, master_db_id, price, comment,
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    response_id = cursor.lastrowid

    bot.send_message(
        message.chat.id,
        "✅ **Ваш отклик отправлен!**\n"
        "Клиент получит уведомление и сможет выбрать вас."
    )

    cursor.execute('SELECT user_id FROM requests WHERE id = ?', (request_id,))
    client = cursor.fetchone()
    if client:
        try:
            bot.send_message(
                client[0],
                f"👋 **На вашу заявку поступил новый отклик!**\n"
                f"Мастер предложил цену: {price}\n"
                f"Комментарий: {comment if comment else '—'}\n\n"
                f"Вы можете посмотреть все отклики и выбрать мастера в разделе «Мои заявки»."
            )
        except:
            pass

    del bot.response_temp[master_id]
    show_role_menu(message, 'master')

# ================ ПРОСМОТР КЛИЕНТОМ ЗАЯВОК И ВЫБОР МАСТЕРА ================
@bot.message_handler(commands=['my_requests'])
def my_requests(message):
    if not only_private(message):
        return
    user_id = message.from_user.id
    cursor.execute('''
        SELECT id, service, description, district, date, budget, status, is_public
        FROM requests
        WHERE user_id = ? AND status = 'активна' AND chosen_master_id IS NULL
        ORDER BY created_at DESC
    ''', (user_id,))
    requests = cursor.fetchall()
    if not requests:
        bot.send_message(message.chat.id, "📭 У вас нет активных заявок.")
        return

    for req in requests:
        req_id, service, desc, district, date, budget, status, is_public = req
        cursor.execute('''
            SELECT r.id, m.name, r.price, r.comment
            FROM responses r
            JOIN masters m ON r.master_id = m.id
            WHERE r.request_id = ? AND r.status = 'pending'
        ''', (req_id,))
        responses = cursor.fetchall()

        text = f"📌 **Заявка #{req_id}**\n🔨 {service}\n📍 {district}\n📅 {date}\n💰 {budget}\n📝 {desc}\n\n"
        markup = types.InlineKeyboardMarkup()

        if responses:
            text += "**Отклики:**\n"
            for resp in responses:
                resp_id, master_name, price, comment = resp
                text += f"• {master_name}: {price}\n  {comment[:50]}...\n"
                markup.add(types.InlineKeyboardButton(
                    f"✅ Выбрать {master_name}",
                    callback_data=f"choose_master_{req_id}_{resp_id}"
                ))
        else:
            text += "😴 Пока нет откликов.\n"

        # Если заявка публичная – добавляем кнопку рекомендаций
        if is_public:
            markup.add(types.InlineKeyboardButton(
                "👥 Рекомендации других клиентов",
                callback_data=f"recs_for_request_{req_id}"
            ))

        bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('choose_master_'))
def choose_master_callback(call):
    parts = call.data.split('_')
    req_id = int(parts[2])
    resp_id = int(parts[3])

    cursor.execute('SELECT master_id, price FROM responses WHERE id = ?', (resp_id,))
    resp = cursor.fetchone()
    if not resp:
        bot.answer_callback_query(call.id, "❌ Отклик не найден.")
        return
    master_db_id, price = resp

    cursor.execute('UPDATE requests SET chosen_master_id = ? WHERE id = ?', (master_db_id, req_id))
    cursor.execute('UPDATE responses SET status = "accepted" WHERE id = ?', (resp_id,))
    conn.commit()

    # Получаем данные мастера
    cursor.execute('SELECT user_id, name, phone FROM masters WHERE id = ?', (master_db_id,))
    master = cursor.fetchone()
    if master:
        master_user_id, master_name, master_phone = master
        cursor.execute('SELECT username FROM users WHERE user_id = ?', (master_user_id,))
        user_row = cursor.fetchone()
        master_username = user_row[0] if user_row else None
        master_contact = f"@{master_username}" if master_username else master_phone

        # Данные клиента
        cursor.execute('SELECT user_id, username FROM requests WHERE id = ?', (req_id,))
        client = cursor.fetchone()
        if client:
            client_user_id, client_username = client
            client_contact = f"@{client_username}" if client_username else f"ID {client_user_id}"

            # Отправляем мастеру контакт клиента
            try:
                bot.send_message(
                    master_user_id,
                    f"✅ Клиент выбрал вас для выполнения заявки #{req_id}!\n"
                    f"Контакт клиента: {client_contact}\n"
                    f"Свяжитесь с ним для обсуждения деталей."
                )
            except:
                pass

            # Отправляем клиенту контакт мастера
            try:
                bot.send_message(
                    client_user_id,
                    f"✅ Вы выбрали мастера {master_name} для заявки #{req_id}.\n"
                    f"Контакт мастера: {master_contact} (свяжитесь с ним)."
                )
            except:
                pass

    # Уведомляем других мастеров о закрытии заявки
    cursor.execute('SELECT master_id FROM responses WHERE request_id = ? AND id != ? AND status = "pending"', (req_id, resp_id))
    other_responses = cursor.fetchall()
    for (other_master_db_id,) in other_responses:
        cursor.execute('SELECT user_id FROM masters WHERE id = ?', (other_master_db_id,))
        other_user = cursor.fetchone()
        if other_user:
            try:
                bot.send_message(other_user[0], f"❌ Заявка #{req_id} больше не актуальна – выбран другой мастер.")
            except:
                pass

    bot.edit_message_text(
        "✅ Вы выбрали мастера. Контакты отправлены обоим.",
        call.message.chat.id,
        call.message.message_id
    )
    bot.answer_callback_query(call.id)

# ================ ПОКАЗ РЕКОМЕНДАЦИЙ ДЛЯ ЗАЯВКИ ================
@bot.callback_query_handler(func=lambda call: call.data.startswith('recs_for_request_'))
def show_recs_for_request(call):
    req_id = int(call.data.split('_')[3])
    # Получаем специализацию заявки
    cursor.execute('SELECT service, is_public FROM requests WHERE id = ?', (req_id,))
    row = cursor.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "❌ Заявка не найдена.")
        return
    service, is_public = row
    if not is_public:
        bot.answer_callback_query(call.id, "❌ Рекомендации доступны только для публичных заявок.")
        return

    cursor.execute('''
        SELECT master_name, contact, description, created_at
        FROM client_recommendations
        WHERE hashtag = ? AND status = 'approved'
        ORDER BY created_at DESC
        LIMIT 10
    ''', (service,))
    recs = cursor.fetchall()
    if not recs:
        bot.edit_message_text(
            f"❌ По услуге {service} пока нет рекомендаций.\n\n"
            "Вы можете оставить свою рекомендацию в нашем чате @remontvl25chat, используя хештег #рекомендую_...",
            call.message.chat.id,
            call.message.message_id
        )
        bot.answer_callback_query(call.id)
        return

    text = f"👥 **Рекомендации других клиентов по услуге {service}:**\n\n"
    for master, contact, desc, date in recs:
        text += f"👤 **{master}**\n📞 Контакт: {contact}\n📝 {desc}\n🕒 {date}\n\n"

    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id
    )
    bot.answer_callback_query(call.id)

# ================ АКТИВНЫЕ ЗАЯВКИ ДЛЯ МАСТЕРА ================
@bot.message_handler(commands=['active_requests'])
def active_requests(message):
    if not only_private(message):
        return
    user_id = message.from_user.id
    cursor.execute('SELECT id, service FROM masters WHERE user_id = ? AND status = "активен"', (user_id,))
    masters = cursor.fetchall()
    if not masters:
        bot.reply_to(message, "❌ Вы не зарегистрированы как мастер.")
        return
    services = [m[1] for m in masters]
    placeholders = ','.join(['?']*len(services))
    cursor.execute(f'''
        SELECT id, service, description, district, date, budget FROM requests
        WHERE status = 'активна' AND chosen_master_id IS NULL AND service IN ({placeholders})
        ORDER BY created_at DESC
    ''', services)
    requests = cursor.fetchall()
    if not requests:
        bot.send_message(message.chat.id, "📭 Нет активных заявок по вашей специализации.")
        return
    for req in requests:
        req_id, service, desc, district, date, budget = req
        text = f"🔨 **{service}**\n📍 {district}\n📅 {date}\n💰 {budget}\n📝 {desc}\n"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💰 Откликнуться", callback_data=f"respond_{req_id}"))
        bot.send_message(message.chat.id, text, reply_markup=markup)

# ================ УЛУЧШЕННЫЕ ОТЗЫВЫ (С ВЫБОРОМ МАСТЕРА, АНОНИМНОСТЬЮ И МЕДИА) ================
if not hasattr(bot, 'review_data'):
    bot.review_data = {}

@bot.message_handler(commands=['review'])
@bot.message_handler(func=lambda message: message.text == '⭐ Оставить отзыв')
def add_review(message):
    if not only_private(message):
        return
    cursor.execute("SELECT DISTINCT service FROM masters WHERE status = 'активен' ORDER BY service")
    services = cursor.fetchall()
    if not services:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📝 Оставить рекомендацию в чате", callback_data="recommend_in_chat"))
        bot.send_message(
            message.chat.id,
            "❌ В базе пока нет мастеров.\n\n"
            "Вы можете оставить рекомендацию о мастере в нашем чате @remontvl25chat, используя хештег #рекомендую_...",
            reply_markup=markup
        )
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for s in services:
        service = s[0]
        buttons.append(types.InlineKeyboardButton(service, callback_data=f"rev_service_{service}"))
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="rev_cancel"))
    bot.send_message(message.chat.id, "🔍 **Выберите специализацию мастера:**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('rev_service_'))
def rev_service_callback(call):
    service = call.data[12:]
    user_id = call.from_user.id
    if user_id not in bot.review_data:
        bot.review_data[user_id] = {}
    bot.review_data[user_id]['service'] = service

    cursor.execute('''
        SELECT id, name FROM masters WHERE service = ? AND status = 'активен' ORDER BY name LIMIT 10
    ''', (service,))
    masters = cursor.fetchall()
    if not masters:
        bot.edit_message_text("❌ Нет мастеров этой специализации.", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for m in masters:
        markup.add(types.InlineKeyboardButton(m[1], callback_data=f"rev_master_{m[0]}"))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="rev_back_to_services"))
    bot.edit_message_text("👤 **Выберите мастера:**", call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('rev_master_'))
def rev_master_callback(call):
    master_id = int(call.data[11:])
    user_id = call.from_user.id
    bot.review_data[user_id]['master_id'] = master_id
    bot.edit_message_text(
        "📝 **Напишите текст отзыва:**\n"
        "Например: Сделал быстро, качественно, цена адекватная",
        call.message.chat.id,
        call.message.message_id
    )
    bot.register_next_step_handler(call.message, process_review_text, master_id)
    bot.answer_callback_query(call.id)

def process_review_text(message, master_id):
    if message.chat.type != 'private':
        return
    review_text = safe_text(message)
    if not review_text:
        bot.send_message(message.chat.id, "❌ Пожалуйста, напишите текст отзыва.")
        return
    user_id = message.from_user.id
    bot.review_data[user_id]['text'] = review_text

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Да, анонимно", callback_data="rev_anon_yes"),
        types.InlineKeyboardButton("❌ Нет, указать автора", callback_data="rev_anon_no")
    )
    bot.send_message(
        message.chat.id,
        "🔒 **Оставить отзыв анонимно?**\n"
        "(Если да, ваше имя/username не будет показано в публикации.)",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('rev_anon_'))
def rev_anon_callback(call):
    anon = 1 if call.data == 'rev_anon_yes' else 0
    user_id = call.from_user.id
    bot.review_data[user_id]['anonymous'] = anon

    bot.edit_message_text(
        "📸 **Прикрепите фото или видео (необязательно).**\n"
        "Если хотите поделиться медиа, отправьте его сейчас.\n"
        "Если нет, отправьте /skip.",
        call.message.chat.id,
        call.message.message_id
    )
    bot.register_next_step_handler(call.message, process_review_media, user_id)
    bot.answer_callback_query(call.id)

def process_review_media(message, user_id):
    media_file_id = None
    if message.text and message.text == '/skip':
        media_file_id = ''
    elif message.photo:
        media_file_id = message.photo[-1].file_id
    elif message.video:
        media_file_id = message.video.file_id
    else:
        bot.send_message(message.chat.id, "Пожалуйста, отправьте фото, видео или /skip.")
        bot.register_next_step_handler(message, process_review_media, user_id)
        return

    bot.review_data[user_id]['media'] = media_file_id

    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = []
    for i in range(1, 6):
        buttons.append(types.InlineKeyboardButton(
            "⭐" * i, callback_data=f"rev_rate_{i}"
        ))
    markup.add(*buttons)
    bot.send_message(
        message.chat.id,
        "⭐ **Оцените работу от 1 до 5:**",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('rev_rate_'))
def rev_rate_callback(call):
    rating = int(call.data.split('_')[2])
    user_id = call.from_user.id
    data = bot.review_data[user_id]
    master_id = data['master_id']
    review_text = data['text']
    anonymous = data['anonymous']
    media_file_id = data.get('media', '')

    cursor.execute('SELECT name FROM masters WHERE id = ?', (master_id,))
    master = cursor.fetchone()
    if not master:
        bot.answer_callback_query(call.id, "❌ Мастер не найден.")
        return
    master_name = master[0]

    cursor.execute('''INSERT INTO reviews
                    (master_name, master_id, user_name, user_id, anonymous, review_text, rating, media_file_id, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (master_name, master_id,
                     call.from_user.username or call.from_user.first_name,
                     user_id,
                     anonymous,
                     review_text,
                     rating,
                     media_file_id,
                     'pending',
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    review_id = cursor.lastrowid

    admin_msg = f"""
⭐ **НОВЫЙ ОТЗЫВ (на модерации)!** (ID: {review_id})
👤 **Мастер:** {master_name}
⭐ **Оценка:** {'⭐' * rating}
📝 **Отзыв:** {review_text}
👤 **От кого:** @{call.from_user.username or "нет"} ({"анонимно" if anonymous else "публично"})
📎 **Медиа:** {'есть' if media_file_id else 'нет'}
✅ Одобрить: /approve_review {review_id}
❌ Отклонить: /reject_review {review_id}
    """
    try:
        if ADMIN_ID != 0:
            bot.send_message(ADMIN_ID, admin_msg)
    except:
        pass

    bot.edit_message_text(
        "✅ **СПАСИБО ЗА ОТЗЫВ!**\n\n"
        "После проверки администратором он появится в канале.",
        call.message.chat.id,
        call.message.message_id
    )
    show_role_menu(call.message, 'client')
    del bot.review_data[user_id]
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'rev_back_to_services')
def rev_back_to_services(call):
    cursor.execute("SELECT DISTINCT service FROM masters WHERE status = 'активен' ORDER BY service")
    services = cursor.fetchall()
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for s in services:
        service = s[0]
        buttons.append(types.InlineKeyboardButton(service, callback_data=f"rev_service_{service}"))
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="rev_cancel"))
    bot.edit_message_text("🔍 **Выберите специализацию мастера:**", call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'rev_cancel')
def rev_cancel(call):
    bot.edit_message_text("❌ Отмена.", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'recommend_in_chat')
def recommend_in_chat(call):
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Перейдите в чат @remontvl25chat и напишите сообщение с хештегом #рекомендую_...")

# ================ АДМИН-КОМАНДЫ ДЛЯ ОТЗЫВОВ ================
@bot.message_handler(commands=['approve_review'])
def approve_review(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    try:
        review_id = int(message.text.split()[1])
        cursor.execute('UPDATE reviews SET status = "published" WHERE id = ?', (review_id,))
        conn.commit()
        cursor.execute('''
            SELECT master_name, user_name, anonymous, review_text, rating, media_file_id, created_at
            FROM reviews WHERE id = ?
        ''', (review_id,))
        rev = cursor.fetchone()
        if rev:
            master_name, user_name, anonymous, review_text, rating, media_file_id, created_at = rev
            author = "Анонимный пользователь" if anonymous else f"@{user_name}"
            review_public = f"""
⭐ **НОВЫЙ ОТЗЫВ!**

👤 **Мастер:** {master_name}
⭐ **Оценка:** {'⭐' * rating}
📝 **Отзыв:** {review_text}
👤 **От:** {author}
⏰ {created_at}
"""
            if media_file_id:
                review_public += "\n📎 **Прикреплено фото/видео.** Для просмотра нажмите /view_review_media {review_id} в боте."
            bot.send_message(CHANNEL_ID, review_public)
        bot.reply_to(message, f"✅ Отзыв {review_id} одобрен и опубликован.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['reject_review'])
def reject_review(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    try:
        review_id = int(message.text.split()[1])
        cursor.execute('UPDATE reviews SET status = "rejected" WHERE id = ?', (review_id,))
        conn.commit()
        bot.reply_to(message, f"❌ Отзыв {review_id} отклонён.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['view_review_media'])
def view_review_media(message):
    if not only_private(message):
        return
    try:
        review_id = int(message.text.split()[1])
        cursor.execute('SELECT media_file_id FROM reviews WHERE id = ?', (review_id,))
        media = cursor.fetchone()
        if not media or not media[0]:
            bot.reply_to(message, "❌ Медиа не найдено.")
            return
        file_id = media[0]
        bot.send_message(message.chat.id, "📎 Вот медиа:")
        bot.send_photo(message.chat.id, file_id)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ================ ПУБЛИКАЦИЯ КАРТОЧКИ МАСТЕРА (с кнопкой прямой заявки) ================
def publish_master_card(master_data, master_id=None):
    if master_data.get('entity_type') == 'company':
        type_icon = '🏢'
        type_text = 'Компания'
    else:
        type_icon = '👤'
        type_text = 'Частное лицо'
    verif_text = '✅ Верифицирован' if master_data.get('verification_type') == 'full' else '🔹 Без верификации'
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
🛡 **Статус проверки:** {verif_text}
   📄 Документы: {docs}
   📷 Фото работ: {photos}
   💬 Отзывы: ⭐ {rating:.1f} ({reviews_count} отзывов)
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "📩 Оставить заявку этому мастеру",
        callback_data=f"request_to_master_{master_id}"
    ))
    try:
        sent = bot.send_message(CHANNEL_ID, card, reply_markup=markup)
        if master_id:
            cursor.execute('UPDATE masters SET channel_message_id = ? WHERE id = ?', (sent.message_id, master_id))
            conn.commit()
        return sent.message_id
    except Exception as e:
        print(f"❌ Ошибка публикации карточки: {e}")
        return None

# ================ КОМАНДЫ АДМИНИСТРАТОРА ДЛЯ МАСТЕРОВ ================
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
                        (user_id, name, service, phone, districts, price_min, price_max,
                         experience, bio, portfolio, rating, reviews_count, status, entity_type,
                         verification_type, source, documents_verified, photos_verified, reviews_verified, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (app[1], app[3], app[4], app[5], app[6],
                         app[7], app[8], app[9], app[10], app[11],
                         0.0, 0, 'активен', app[13],
                         app[14], app[15],
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
            'verification_type': app[14],
            'source': app[15],
            'username': app[2],
            'documents_verified': 0,
            'photos_verified': 0,
            'rating': 0.0,
            'reviews_count': 0
        }
        publish_master_card(master_data, master_id)

        if MASTER_CHAT_INVITE_LINK:
            try:
                bot.send_message(
                    app[1],
                    f"🔐 Вы приглашены в закрытый чат мастеров, где публикуются приватные заявки и обсуждаются профессиональные вопросы:\n{MASTER_CHAT_INVITE_LINK}"
                )
            except:
                pass

        try:
            bot.send_message(
                app[1],
                f"✅ **ВАША АНКЕТА ОДОБРЕНА!**\n\n"
                f"Поздравляем! Ваша карточка уже опубликована в канале {CHANNEL_ID}\n\n"
                f"📌 **Что дальше?**\n"
                f"1. Клиенты будут видеть вашу карточку и смогут оставлять заявки.\n"
                f"2. Вы получите уведомление, когда кто-то оставит заявку по вашей специализации.\n"
                f"3. Отвечайте на заявки, чтобы получать заказы."
            )
        except:
            pass
        bot.reply_to(message, f"✅ Мастер {app[3]} одобрен! Карточка опубликована в канале.")
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
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

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

        cursor.execute('SELECT * FROM masters WHERE id = ?', (master_id,))
        m = cursor.fetchone()
        if not m:
            bot.reply_to(message, f"❌ Мастер с ID {master_id} не найден.")
            return

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
🛡 **Верификация:** {'Полная' if m[15]=='full' else 'Упрощённая'}
📄 **Документы:** {'✅' if m[16] else '❌'}
📷 **Фото:** {'✅' if m[17] else '❌'}
💬 **Отзывы проверены:** {'✅' if m[18] else '❌'}
📱 **Источник:** {m[20]}
📅 **Добавлен:** {m[21]}
"""
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"📄 Документы: {'✅' if m[16] else '❌'}",
                                       callback_data=f"toggle_docs_{master_id}"),
            types.InlineKeyboardButton(f"📷 Фото: {'✅' if m[17] else '❌'}",
                                       callback_data=f"toggle_photo_{master_id}"),
            types.InlineKeyboardButton(f"💬 Отзывы: {'✅' if m[18] else '❌'}",
                                       callback_data=f"toggle_reviews_{master_id}")
        )
        markup.add(types.InlineKeyboardButton("🏅 Верифицировать всё",
                                              callback_data=f"verify_all_{master_id}"))
        markup.add(types.InlineKeyboardButton("✏️ Редактировать",
                                              callback_data=f"edit_master_{master_id}"))
        markup.add(types.InlineKeyboardButton("🗑 Удалить",
                                              callback_data=f"delete_master_{master_id}"))
        bot.send_message(message.chat.id, text, reply_markup=markup)
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_'))
def toggle_verification(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    parts = call.data.split('_')
    field = parts[1]
    master_id = int(parts[2])
    col_map = {
        'docs': 'documents_verified',
        'photo': 'photos_verified',
        'reviews': 'reviews_verified'
    }
    col = col_map.get(field)
    if not col:
        bot.answer_callback_query(call.id, "❌ Неизвестное поле")
        return
    cursor.execute(f'SELECT {col} FROM masters WHERE id = ?', (master_id,))
    current = cursor.fetchone()[0]
    new_val = 1 if current == 0 else 0
    cursor.execute(f'UPDATE masters SET {col} = ? WHERE id = ?', (new_val, master_id))
    conn.commit()
    bot.answer_callback_query(call.id, f"✅ Статус обновлён")

@bot.callback_query_handler(func=lambda call: call.data.startswith('verify_all_'))
def verify_all(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    master_id = int(call.data.split('_')[2])
    cursor.execute('''UPDATE masters 
                      SET documents_verified = 1, photos_verified = 1, reviews_verified = 1 
                      WHERE id = ?''', (master_id,))
    conn.commit()
    bot.answer_callback_query(call.id, "✅ Мастер полностью верифицирован")

# ================ ПОИСК МАСТЕРОВ (КАТАЛОГ) ================
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
            "📝 Оставить заявку",
            callback_data="create_request"
        ))
        bot.send_message(
            message.chat.id,
            "🔍 **В базе пока нет мастеров.**\n\n"
            "Вы можете оставить заявку – мы оповестим мастеров.",
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
        bot.edit_message_text("❌ Поиск отменён.", call.message.chat.id, call.message.message_id)
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
    query = '''
        SELECT id, name, service, districts, price_min, price_max, rating, reviews_count,
               phone, entity_type, bio
        FROM masters
        WHERE service = ? AND status = 'активен'
        ORDER BY rating DESC, reviews_count DESC
        LIMIT ? OFFSET ?
    '''
    cursor.execute(query, (service, LIMIT, offset))
    masters = cursor.fetchall()
    query_count = 'SELECT COUNT(*) FROM masters WHERE service = ? AND status = "активен"'
    cursor.execute(query_count, (service,))
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
    markup = types.InlineKeyboardMarkup()
    for m in masters:
        mid, name, service, districts, price_min, price_max, rating, reviews, phone, entity_type, bio = m
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
        markup.add(types.InlineKeyboardButton(
            f"📩 Заявка {name}",
            callback_data=f"request_to_master_{mid}"
        ))
    pag_buttons = []
    if page > 0:
        pag_buttons.append(types.InlineKeyboardButton(
            "◀️ Назад", callback_data=f"page_{service}_{page-1}"
        ))
    if offset + LIMIT < total:
        pag_buttons.append(types.InlineKeyboardButton(
            "Вперёд ▶️", callback_data=f"page_{service}_{page+1}"
        ))
    if pag_buttons:
        markup.row(*pag_buttons)
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
    parts = call.data.split('_')
    if len(parts) < 3:
        bot.answer_callback_query(call.id, "❌ Неверный формат")
        return
    service = parts[1]
    try:
        page = int(parts[2])
    except:
        bot.answer_callback_query(call.id, "❌ Неверный формат")
        return
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
        bot.edit_message_text("❌ База мастеров пуста.", call.message.chat.id, call.message.message_id)
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

@bot.callback_query_handler(func=lambda call: call.data == 'create_request')
def create_request_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "🔨 Переходим к созданию заявки.")
    request_service(call.message)

# ================ АДМИН-МЕНЮ ================
@bot.message_handler(commands=['admin'])
def admin_command(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав.")
        return
    admin_menu(message)

def admin_menu(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 Список мастеров", callback_data="admin_list_masters"),
        types.InlineKeyboardButton("📋 Новые анкеты", callback_data="admin_list_applications"),
        types.InlineKeyboardButton("📋 Рекомендации", callback_data="admin_list_recs"),
        types.InlineKeyboardButton("📋 Отзывы", callback_data="admin_list_reviews"),
        types.InlineKeyboardButton("➕ Одобрить мастера", callback_data="admin_approve_prompt"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data="admin_reject_prompt")
    )
    bot.send_message(message.chat.id, "👑 Админ-панель", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    action = call.data[6:]
    if action == 'list_masters':
        list_masters(call.message)
    elif action == 'list_applications':
        bot.send_message(call.message.chat.id, "Используйте /list_apps (команда пока не реализована)")
    elif action == 'list_recs':
        list_recommendations(call.message)
    elif action == 'list_reviews':
        bot.send_message(call.message.chat.id, "Используйте /list_reviews (команда пока не реализована)")
    elif action == 'approve_prompt':
        bot.send_message(call.message.chat.id, "Введите ID анкеты для одобрения: /approve [ID]")
    elif action == 'reject_prompt':
        bot.send_message(call.message.chat.id, "Введите ID анкеты и причину: /reject [ID] [причина]")
    bot.answer_callback_query(call.id)

# ================ ОБРАБОТЧИК НОВЫХ УЧАСТНИКОВ ЧАТА ================
def is_new_member(chat_member_update):
    old_status = chat_member_update.old_chat_member.status
    new_status = chat_member_update.new_chat_member.status
    return (old_status in ['left', 'kicked'] and new_status == 'member')

@bot.chat_member_handler()
def greet_new_member(chat_member_update):
    if str(chat_member_update.chat.id) != CHAT_ID.strip('@'):
        return
    if not is_new_member(chat_member_update):
        return
    user = chat_member_update.new_chat_member.user
    user_id = user.id
    username = user.username or ""
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    existing = cursor.fetchone()
    if existing:
        return
    try:
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🔨 Я клиент, ищу мастера", callback_data="role_client"),
            types.InlineKeyboardButton("👷 Я мастер", callback_data="role_master")
        )
        bot.send_message(
            user_id,
            f"👋 **Привет, {user.first_name}!**\n\n"
            f"Ты присоединился к нашему чату @remontvl25chat.\n"
            f"Кто ты? Выбери роль, чтобы мы могли предложить нужный функционал.",
            reply_markup=markup
        )
    except Exception as e:
        print(f"Не удалось отправить приветствие пользователю {user_id}: {e}")

# ================ ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ================
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
    print(f"💬 Общий чат: {CHAT_ID}")
    print(f"📢 Канал: {CHANNEL_ID}")
    print(f"🔐 Чат мастеров: {MASTER_CHAT_ID}")
    print(f"👑 Админ ID: {ADMIN_ID}")
    print("=" * 60)
    check_bot_admin_in_chat(CHAT_ID)
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
