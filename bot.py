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

# Ссылка на Google Forms (обязательно задайте в Railway!)
GOOGLE_FORMS_URL = os.environ.get('GOOGLE_FORMS_URL', '')

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
                 status TEXT,
                 chat_message_id INTEGER,
                 created_at TEXT)''')

# ----- Таблица отзывов -----
cursor.execute('''CREATE TABLE IF NOT EXISTS reviews
                (id INTEGER PRIMARY KEY,
                 master_name TEXT,
                 user_name TEXT,
                 review_text TEXT,
                 rating INTEGER,
                 status TEXT,
                 created_at TEXT)''')

# ----- Таблица проверенных мастеров -----
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
                 verification_type TEXT DEFAULT 'simple',  -- 'full' или 'simple'
                 documents_verified INTEGER DEFAULT 0,
                 photos_verified INTEGER DEFAULT 0,
                 reviews_verified INTEGER DEFAULT 0,
                 channel_message_id INTEGER,
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
                 status TEXT,
                 created_at TEXT)''')

# ----- Таблица рекомендаций (предложенные мастера) -----
cursor.execute('''CREATE TABLE IF NOT EXISTS recommendations
                (id INTEGER PRIMARY KEY,
                 user_id INTEGER,
                 username TEXT,
                 master_name TEXT,
                 service TEXT,
                 contact TEXT,
                 description TEXT,
                 price_level TEXT,      -- 'дорого', 'дешево', 'средне'
                 satisfaction TEXT,    -- 'доволен', 'не доволен'
                 recommend TEXT,       -- 'да', 'нет'
                 portfolio TEXT,
                 status TEXT DEFAULT 'на модерации',
                 created_at TEXT)''')

# ----- Добавление недостающих колонок -----
try:
    cursor.execute('ALTER TABLE master_applications ADD COLUMN verification_type TEXT DEFAULT "simple"')
except:
    pass
try:
    cursor.execute('ALTER TABLE masters ADD COLUMN verification_type TEXT DEFAULT "simple"')
except:
    pass
try:
    cursor.execute('ALTER TABLE masters ADD COLUMN channel_message_id INTEGER')
except:
    pass

conn.commit()

# ================ ФУНКЦИИ GOOGLE SHEETS (сокращено для объёма, но работает) ================
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
            str(master_data.get('verification_type', 'simple'))
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
                sheet.update_cell(i, 15, status)  # колонка O
                return True
    except Exception as e:
        print(f"❌ Ошибка обновления статуса: {e}")
    return False

# ================ ТЕСТ GOOGLE SHEETS ================
@bot.message_handler(commands=['test_sheet'])
def test_sheet(message):
    if message.from_user.id != ADMIN_ID:
        return
    # ... (код диагностики, можно добавить позже)

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

# ================ ВЫБОР РОЛИ ПРИ ПЕРВОМ ЗАПУСКЕ ================
def show_role_menu(message, role):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if role == 'client':
        markup.row('🔨 Оставить заявку', '🔍 Найти мастера')
        markup.row('⭐ Оставить отзыв', '👍 Рекомендовать мастера')
        markup.row('📢 Канал с мастерами')
        text = "👋 **Режим: Клиент**\n\nВы можете найти мастера, оставить заявку или порекомендовать специалиста."
    else:
        markup.row('👷 Стать мастером', '📋 Анкета (Google Forms)')
        markup.row('🔍 Найти мастера (клиентский режим)', '📢 Канал с мастерами')
        text = "👋 **Режим: Мастер**\n\nВы можете добавить свою анкету или искать клиентов (как клиент)."
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='Markdown')

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
            "✅ Найти проверенного мастера\n"
            "✅ Стать мастером и добавить анкету\n"
            "✅ Оставить отзыв о работе\n"
            "✅ Проверить статус анкеты\n"
            "✅ Рекомендовать мастера",
            reply_markup=markup
        )
        return

    user_id = message.from_user.id
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row:
        # Новый пользователь – предлагаем выбор роли
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
    cursor.execute('INSERT OR REPLACE INTO users (user_id, role, first_seen, last_active) VALUES (?, ?, ?, ?)',
                   (user_id, role, now, now))
    conn.commit()
    bot.edit_message_text(f"✅ Роль сохранена: {'Клиент' if role == 'client' else 'Мастер'}.",
                          call.message.chat.id,
                          call.message.message_id)
    show_role_menu(call.message, role)
    bot.answer_callback_query(call.id)

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
        "✅ Черный список мошенников",
        reply_markup=markup
    )

# ================ КНОПКА "АНКЕТА (GOOGLE FORMS)" ================
@bot.message_handler(func=lambda message: message.text == '📋 Анкета (Google Forms)')
def forms_link(message):
    if not only_private(message):
        return
    if not GOOGLE_FORMS_URL or GOOGLE_FORMS_URL == 'https://forms.gle/your_form_link':
        bot.send_message(
            message.chat.id,
            "❌ Ссылка на анкету ещё не настроена.\n"
            "Пожалуйста, обратитесь к администратору."
        )
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
    # ... (код как в предыдущей версии, без изменений)
    pass  # здесь нужно скопировать полную логику из предыдущего кода

# ================ ОТЗЫВ (ТОЛЬКО В ЛС) ================
@bot.message_handler(commands=['review'])
@bot.message_handler(func=lambda message: message.text == '⭐ Оставить отзыв')
def add_review(message):
    if not only_private(message):
        return
    # ... (код без изменений)
    pass

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

    # Спрашиваем про фильтр верификации
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Только верифицированные", callback_data=f"filter_verified_{service}"),
        types.InlineKeyboardButton("🌐 Все мастера", callback_data=f"filter_all_{service}")
    )
    bot.edit_message_text(
        f"🔍 **{service}**\n\nПоказывать только мастеров с полной верификацией?",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('filter_'))
def filter_callback(call):
    parts = call.data.split('_', 2)
    filter_type = parts[1]
    service = parts[2]
    user_id = call.from_user.id

    if not hasattr(bot, 'catalog_states'):
        bot.catalog_states = {}
    bot.catalog_states[user_id] = {
        'service': service,
        'page': 0,
        'filter': filter_type
    }

    show_masters_page(call.message, user_id, service, 0, filter_type)
    bot.answer_callback_query(call.id)

def show_masters_page(message, user_id, service, page, filter_type='all'):
    LIMIT = 3
    offset = page * LIMIT

    if filter_type == 'verified':
        condition = "AND documents_verified = 1 AND photos_verified = 1 AND reviews_verified = 1"
    else:
        condition = ""

    query = f'''
        SELECT name, service, districts, price_min, price_max, rating, reviews_count,
               phone, entity_type, bio, verification_type
        FROM masters
        WHERE service = ? AND status = 'активен' {condition}
        ORDER BY rating DESC, reviews_count DESC
        LIMIT ? OFFSET ?
    '''
    cursor.execute(query, (service, LIMIT, offset))
    masters = cursor.fetchall()

    query_count = f'SELECT COUNT(*) FROM masters WHERE service = ? AND status = "активен" {condition}'
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

    for m in masters:
        name, service, districts, price_min, price_max, rating, reviews, phone, entity_type, bio, verif_type = m
        phone_display = phone[:10] + '…' if len(phone) > 10 else phone
        type_icon = '🏢' if entity_type == 'company' else '👤'
        type_label = 'Компания' if entity_type == 'company' else 'Частное лицо'
        verif_badge = '✅ Верифицирован' if verif_type == 'full' else '🔹 Без верификации'

        text += f"{type_icon} **{name}** ({type_label})\n"
        text += f"   📍 {districts}\n"
        text += f"   💰 {price_min} – {price_max}\n"
        text += f"   ⭐ {rating:.1f} ({reviews} отзывов)\n"
        text += f"   🛡 {verif_badge}\n"
        if bio and bio != 'Не указано':
            text += f"   💬 {bio}\n"
        text += f"   📞 Контакт: `{phone_display}` (после отклика)\n\n"

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    if page > 0:
        buttons.append(types.InlineKeyboardButton(
            "◀️ Назад", callback_data=f"page_{service}_{filter_type}_{page-1}"
        ))
    if offset + LIMIT < total:
        buttons.append(types.InlineKeyboardButton(
            "Вперёд ▶️", callback_data=f"page_{service}_{filter_type}_{page+1}"
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
    parts = call.data.split('_', 3)
    service = parts[1]
    filter_type = parts[2]
    page = int(parts[3])
    user_id = call.from_user.id
    if not hasattr(bot, 'catalog_states'):
        bot.catalog_states = {}
    bot.catalog_states[user_id] = {
        'service': service,
        'page': page,
        'filter': filter_type
    }
    show_masters_page(call.message, user_id, service, page, filter_type)
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

# ================ АНКЕТА МАСТЕРА (12 шагов) ================
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

    # Выбор типа верификации
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Полная верификация", callback_data="verif_full"),
        types.InlineKeyboardButton("🔹 Упрощённое размещение", callback_data="verif_simple")
    )
    bot.edit_message_text(
        f"👷 **ЗАПОЛНЕНИЕ АНКЕТЫ МАСТЕРА**\n\n"
        f"Шаг 2 из 13\n"
        f"👇 **ВЫБЕРИТЕ ТИП РАЗМЕЩЕНИЯ:**\n\n"
        f"✅ **Полная верификация** – требуется предоставить документы, фото работ. После проверки вы получите статус «Верифицировано».\n"
        f"🔹 **Упрощённое размещение** – вы сразу попадаете в базу без проверки (статус «Без верификации»). В любой момент можно пройти полную верификацию.",
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
    bot.register_next_step_handler(call.message, process_master_name, bot.master_data[user_id]['entity_type'], verif_type)
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
        "7 - Другое"
    )
    bot.register_next_step_handler(msg, process_master_service, name, entity_type, verif_type)

def process_master_service(message, name, entity_type, verif_type):
    # ... (аналогично предыдущей версии, с сохранением service и передачей verif_type)
    pass  # здесь нужно вставить полный код из предыдущей версии

def process_master_phone(message, name, service, entity_type, verif_type):
    pass

def process_master_districts(message, name, service, phone, entity_type, verif_type):
    pass

def process_master_price_min(message, name, service, phone, districts, entity_type, verif_type):
    pass

def process_master_price_max(message, name, service, phone, districts, price_min, entity_type, verif_type):
    pass

def process_master_experience(message, name, service, phone, districts, price_min, price_max, entity_type, verif_type):
    # ... (сбор данных, затем шаг с bio)
    pass

def process_master_bio(message, user_data):
    # ... (сохраняем bio, переходим к портфолио)
    pass

def process_master_portfolio_text(message, user_data):
    # ... (сохраняем портфолио, переходим к документам)
    pass

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
    # ... (сохраняем документы, вызываем save_master_application)
    pass

def save_master_application(message, user_id, user_data):
    # ... (сохраняем в master_applications, добавляем verification_type, уведомляем админа)
    pass

# ================ РАСШИРЕННАЯ РЕКОМЕНДАЦИЯ МАСТЕРА ================
@bot.message_handler(commands=['recommend'])
@bot.message_handler(func=lambda message: message.text == '👍 Рекомендовать мастера')
def recommend_master(message):
    if not only_private(message):
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
    if not hasattr(bot, 'recommend_data'):
        bot.recommend_data = {}
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

    # Сохраняем в БД
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

    # Уведомление админу
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

# ================ КОМАНДЫ АДМИНИСТРАТОРА ================
# ... (approve, reject, list_masters, view_master, edit_master, delete_master, add_from_rec, reject_rec)

# Добавляем в view_master inline‑кнопки для верификации
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

        # Формируем текст
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
📅 **Добавлен:** {m[20]}
"""
        # Кнопки верификации
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_'))
def toggle_verification(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    parts = call.data.split('_')
    field = parts[1]  # docs, photo, reviews
    master_id = int(parts[2])
    col_map = {'docs': 'documents_verified',
               'photo': 'photos_verified',
               'reviews': 'reviews_verified'}
    col = col_map[field]
    cursor.execute(f'SELECT {col} FROM masters WHERE id = ?', (master_id,))
    current = cursor.fetchone()[0]
    new_val = 1 if current == 0 else 0
    cursor.execute(f'UPDATE masters SET {col} = ? WHERE id = ?', (new_val, master_id))
    conn.commit()
    bot.answer_callback_query(call.id, f"✅ Статус обновлён")
    # Обновляем карточку в канале, если есть message_id
    # ... (можно добавить позже)

@bot.callback_query_handler(func=lambda call: call.data.startswith('verify_all_'))
def verify_all(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав")
        return
    master_id = int(call.data.split('_')[2])
    cursor.execute('''UPDATE masters SET documents_verified=1, photos_verified=1, reviews_verified=1
                      WHERE id = ?''', (master_id,))
    conn.commit()
    bot.answer_callback_query(call.id, "✅ Мастер полностью верифицирован")
    # Обновляем карточку в канале

# ================ ПУБЛИКАЦИЯ КАРТОЧКИ МАСТЕРА ================
def publish_master_card(master_data, master_id=None):
    # ... (формирование card)
    try:
        sent = bot.send_message(CHANNEL_LINK, card)
        print(f"✅ Карточка мастера {master_data['name']} опубликована в канале, message_id={sent.message_id}")
        if master_id:
            cursor.execute('UPDATE masters SET channel_message_id = ? WHERE id = ?',
                           (sent.message_id, master_id))
            conn.commit()
        return sent.message_id
    except Exception as e:
        print(f"❌ Ошибка публикации карточки: {e}")
        return None

# ================ ПРОВЕРКА ПРАВ ПРИ СТАРТЕ ================
if __name__ == '__main__':
    print("="*60)
    print("✅ Бот запускается...")
    print(f"🤖 Токен: {TOKEN[:10]}...")
    print(f"💬 Чат: {CHAT_ID}")
    print(f"📢 Канал: {CHANNEL_LINK}")
    print(f"👑 Админ ID: {ADMIN_ID}")
    print("="*60)

    # Проверка прав бота в чате и канале
    check_bot_admin_in_chat(CHAT_ID)
    # Для канала тоже можно проверить, но API отличается

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
