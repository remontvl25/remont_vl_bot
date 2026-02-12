import os
import sys
import fcntl
import telebot
import sqlite3
import time
import requests
from datetime import datetime

# ================ БЛОКИРОВКА ЗАПУСКА ВТОРОГО ЭКЗЕМПЛЯРА ================
def single_instance():
    """Блокировка запуска второго экземпляра"""
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
    exit(1)

CHAT_ID = os.environ.get('CHAT_ID', "@remontvl25chat")        # Чат для заявок и отзывов
CHANNEL_LINK = os.environ.get('CHANNEL_LINK', "@remont_vl25") # Канал с мастерами
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))

bot = telebot.TeleBot(TOKEN)

# ================ БАЗА ДАННЫХ ================
conn = sqlite3.connect('remont.db', check_same_thread=False)
cursor = conn.cursor()

# Заявки
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

# Отзывы
cursor.execute('''CREATE TABLE IF NOT EXISTS reviews
                (id INTEGER PRIMARY KEY,
                 master_name TEXT,
                 user_name TEXT,
                 review_text TEXT,
                 rating INTEGER,
                 status TEXT,
                 created_at TEXT)''')

# Проверенные мастера
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

# Анкеты мастеров (на проверку)
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

# Добавляем колонки, если их нет
try:
    cursor.execute('ALTER TABLE requests ADD COLUMN description TEXT')
except:
    pass
try:
    cursor.execute('ALTER TABLE requests ADD COLUMN date TEXT')
except:
    pass

conn.commit()

# ================ ФУНКЦИИ ================
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

# Проверка на личные сообщения
def only_private(message):
    if message.chat.type != 'private':
        bot.reply_to(
            message,
            "❌ Эта команда работает только в личных сообщениях с ботом.\n\n"
            f"👉 Напишите мне в ЛС: @remont_vl25_chat_bot",
            reply_markup=telebot.types.InlineKeyboardMarkup().add(
                telebot.types.InlineKeyboardButton(
                    text="🤖 Перейти в бота",
                    url="https://t.me/remont_vl25_chat_bot"
                )
            )
        )
        return False
    return True

# ================ УДАЛЕНИЕ КОМАНД В ЧАТЕ ================
@bot.message_handler(func=lambda message: message.chat.type != 'private')
def delete_group_commands(message):
    # Если сообщение начинается с '/' или содержит упоминание бота
    if message.text and (message.text.startswith('/') or '@remont_vl25_chat_bot' in message.text):
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
@bot.message_handler(commands=['test_sheet'])
def test_sheet(message):
    # Проверка прав (только для админа)
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для этой команды.")
        return

    result_text = "🔍 **ДИАГНОСТИКА GOOGLE SHEETS**\n\n"
    
    # 1. Проверка переменных окружения
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    
    result_text += f"**GOOGLE_CREDENTIALS:** {'✅ Есть' if creds_json else '❌ НЕТ'}\n"
    result_text += f"**GOOGLE_SHEET_ID:** {'✅ Есть' if sheet_id else '❌ НЕТ'}\n\n"
    
    if not creds_json or not sheet_id:
        result_text += "❌ **Ошибка:** переменные окружения не заданы.\n"
        result_text += "Добавьте их в Railway: Variables → New Variable"
        bot.reply_to(message, result_text)
        return
    
    # 2. Проверка подключения
    try:
        sheet = get_google_sheet()
    except Exception as e:
        result_text += f"❌ **Ошибка при вызове get_google_sheet():**\n`{type(e).__name__}: {e}`"
        bot.reply_to(message, result_text)
        return
    
    if not sheet:
        result_text += "❌ **get_google_sheet() вернул None**\n"
        result_text += "Смотрите логи Railway для подробностей."
        bot.reply_to(message, result_text)
        return
    
    # 3. Успешное подключение
    result_text += f"✅ **Подключение успешно!**\n"
    result_text += f"📄 **Лист:** {sheet.title}\n"
    result_text += f"📊 **Всего строк:** {len(sheet.get_all_values())}\n\n"
    
    # 4. Тестовая запись
    try:
        test_row = [
            "TEST",                             # A: ID
            datetime.now().strftime("%d.%m.%Y"), # B: Дата
            "Тестовый мастер",                  # C: Имя
            "Тест",                            # D: Специализация
            "+7 999 999-99-99",                # E: Телефон
            "Патрокл",                         # F: Районы
            "1000₽",                           # G: Цена от
            "5000₽",                           # H: Цена до
            "5 лет",                           # I: Опыт
            "Нет",                             # J: Портфолио
            "Есть",                            # K: Документы
            "5.0",                             # L: Рейтинг
            "1",                               # M: Отзывов
            "Тест",                            # N: Статус
            "12345"                            # O: Telegram ID
        ]
        sheet.append_row(test_row)
        result_text += "✅ **Тестовая запись успешно добавлена!**\n"
        result_text += "Посмотрите таблицу — должна появиться новая строка."
    except Exception as e:
        result_text += f"❌ **Ошибка при записи:**\n`{type(e).__name__}: {e}`"
    
    bot.reply_to(message, result_text)
# ================ КОМАНДА /start ================
@bot.message_handler(commands=['start'])
def start(message):
    if message.chat.type != 'private':
        bot.reply_to(
            message,
            "👋 Добро пожаловать в бот заявок на ремонт!\n\n"
            "📌 В этом чате я только публикую заявки и отзывы.\n\n"
            "👇 Вся работа со мной — в личных сообщениях:\n"
            f"👉 @remont_vl25_chat_bot\n\n"
            "Там вы можете:\n"
            "✅ Оставить заявку на ремонт\n"
            "✅ Найти проверенного мастера\n"
            "✅ Стать мастером и добавить анкету\n"
            "✅ Оставить отзыв о работе\n"
            "✅ Проверить статус анкеты",
            reply_markup=telebot.types.InlineKeyboardMarkup().add(
                telebot.types.InlineKeyboardButton(
                    text="🤖 Перейти в бота",
                    url="https://t.me/remont_vl25_chat_bot"
                )
            )
        )
        return

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
    if not only_private(message):
        return
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
    if message.chat.type != 'private': return
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
        "📝 Шаг 2 из 5\n\n"
        "👇 КРАТКО ОПИШИТЕ ЗАДАЧУ:\n\n"
        "Например:\n"
        "• Заменить смеситель на кухне\n"
        "• Перенести 3 розетки в зале\n"
        "• Поклеить обои в спальне 15м²"
    )
    bot.register_next_step_handler(msg, process_description, service)

def process_description(message, service):
    if message.chat.type != 'private': return
    description = message.text
    msg = bot.send_message(
        message.chat.id,
        "📍 Шаг 3 из 5\n\n"
        "👇 ВВЕДИТЕ РАЙОН ИЛИ ЖК:\n"
        "Например: Патрокл, Снеговая Падь, Варяг, Океан"
    )
    bot.register_next_step_handler(msg, process_district, service, description)

def process_district(message, service, description):
    if message.chat.type != 'private': return
    district = message.text
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
    if message.chat.type != 'private': return
    date = message.text
    msg = bot.send_message(
        message.chat.id,
        "💰 Шаг 5 из 5\n\n"
        "👇 ВВЕДИТЕ БЮДЖЕТ:\n"
        "Например: до 3000₽, договорной, 50000₽ за квартиру"
    )
    bot.register_next_step_handler(msg, process_budget, service, description, district, date)

def process_budget(message, service, description, district, date):
    if message.chat.type != 'private': return
    budget = message.text
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
    if message.chat.type != 'private': return
    master = message.text.strip()
    msg = bot.send_message(
        message.chat.id,
        "📝 НАПИШИТЕ ТЕКСТ ОТЗЫВА:\n"
        "Например: Сделал быстро, качественно, цена адекватная"
    )
    bot.register_next_step_handler(msg, process_review_text, master)

def process_review_text(message, master):
    if message.chat.type != 'private': return
    review_text = message.text.strip()
    
    # Сохраняем отзыв без рейтинга, статус "pending"
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

    # Клавиатура с оценкой
    markup = telebot.types.InlineKeyboardMarkup(row_width=5)
    buttons = []
    for i in range(1, 6):
        buttons.append(telebot.types.InlineKeyboardButton(
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
    
    # Обновляем отзыв: ставим рейтинг, статус 'published'
    cursor.execute('''UPDATE reviews 
                      SET rating = ?, status = 'published' 
                      WHERE id = ?''', (rating, review_id))
    conn.commit()
    
    # Получаем полные данные отзыва
    cursor.execute('''SELECT master_name, user_name, review_text, rating, created_at 
                      FROM reviews WHERE id = ?''', (review_id,))
    review = cursor.fetchone()
    if not review:
        bot.answer_callback_query(call.id, "Ошибка: отзыв не найден")
        return
    
    master_name, user_name, review_text, rating, created_at = review
    
    # Ищем мастера в базе проверенных, чтобы добавить специализацию и контакты
    extra_info = ""
    cursor.execute('''SELECT service, phone FROM masters WHERE name LIKE ?''', (f'%{master_name}%',))
    master_data = cursor.fetchone()
    if master_data:
        service, phone = master_data
        extra_info = f"🔧 Специализация: {service}\n📞 Контакты: {phone}"
    
    # Публикуем отзыв в общий чат
    review_text_public = f"""
⭐ НОВЫЙ ОТЗЫВ!

👤 Мастер: {master_name}
⭐ Оценка: {'⭐' * rating}
📝 Отзыв: {review_text}
👤 От кого: @{user_name}
{extra_info}
⏰ {created_at}
"""
    bot.send_message(CHAT_ID, review_text_public)
    
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

# ================ ПОИСК МАСТЕРОВ (ТОЛЬКО В ЛС) ================
@bot.message_handler(commands=['search'])
@bot.message_handler(func=lambda message: message.text == '🔍 Найти мастера')
def search_master(message):
    if not only_private(message):
        return
    cursor.execute("SELECT service, COUNT(*), AVG(rating) FROM masters GROUP BY service")
    stats = cursor.fetchall()
    if stats:
        text = "🔍 МАСТЕРА В БАЗЕ:\n\n"
        for s in stats:
            text += f"• {s[0]}: {s[1]} мастеров ⭐{s[2]:.1f}\n"
    else:
        text = "🔍 МАСТЕРА В БАЗЕ:\n\n• Электрики: 5 мастеров ⭐4.8\n• Сантехники: 4 мастера ⭐4.9\n• Отделочники: 3 мастера ⭐4.7\n• Строители: 2 мастера ⭐4.6\n\n"
    text += f"\n👉 Хотите найти мастера?\nЗайдите в чат и оставьте заявку:\n{CHAT_ID}"
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("📢 Канал", url="https://t.me/remont_vl25"))
    markup.add(telebot.types.InlineKeyboardButton("💬 Чат", url="https://t.me/remontvl25chat"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

# ================ КОНТАКТЫ (ТОЛЬКО В ЛС) ================
@bot.message_handler(commands=['contacts'])
@bot.message_handler(func=lambda message: message.text == '📞 Контакты')
def contacts(message):
    if not only_private(message):
        return
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        telebot.types.InlineKeyboardButton("📢 Канал с мастерами", url="https://t.me/remont_vl25"),
        telebot.types.InlineKeyboardButton("💬 Чат-заявок", url="https://t.me/remontvl25chat"),
        telebot.types.InlineKeyboardButton("👨‍💻 Администратор", url="https://t.me/remont_vl25")
    )
    bot.send_message(
        message.chat.id,
        f"📞 КОНТАКТЫ\n\n"
        f"📢 Канал с мастерами: {CHANNEL_LINK}\n"
        f"💬 Чат-заявок: {CHAT_ID}\n"
        f"🤖 Этот бот: @remont_vl25_chat_bot\n"
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
        "/search - Поиск мастеров\n"
        "/become_master - Стать мастером\n"
        "/my_status - Статус анкеты\n"
        "/contacts - Контакты\n"
        "/help - Это сообщение\n\n"
        "Как найти мастера?\n"
        "1. Нажмите «Оставить заявку»\n"
        "2. Выберите услугу\n"
        "3. Опишите задачу\n"
        "4. Укажите район и дату\n"
        "5. Введите бюджет\n"
        "6. Ждите откликов в чате"
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
    if message.chat.type != 'private': return
    name = message.text
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
    if message.chat.type != 'private': return
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
        "📞 Шаг 3 из 10\n\n"
        "👇 ВВЕДИТЕ ВАШ ТЕЛЕФОН:\n\n"
        "Пример: +7 924 123-45-67\n\n"
        "⚠️ Номер будет виден ТОЛЬКО администратору"
    )
    bot.register_next_step_handler(msg, process_master_phone, name, service)

def process_master_phone(message, name, service):
    if message.chat.type != 'private': return
    phone = message.text
    msg = bot.send_message(
        message.chat.id,
        "📍 Шаг 4 из 10\n\n"
        "👇 В КАКИХ РАЙОНАХ/ЖК ВЫ РАБОТАЕТЕ?\n\n"
        "Перечислите через запятую:\n"
        "Пример: Патрокл, Снеговая Падь, Варяг, Океан"
    )
    bot.register_next_step_handler(msg, process_master_districts, name, service, phone)

def process_master_districts(message, name, service, phone):
    if message.chat.type != 'private': return
    districts = message.text
    msg = bot.send_message(
        message.chat.id,
        "💰 Шаг 5 из 10\n\n"
        "👇 МИНИМАЛЬНАЯ ЦЕНА ЗАКАЗА:\n\n"
        "Пример: 1000₽, 5000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_min, name, service, phone, districts)

def process_master_price_min(message, name, service, phone, districts):
    if message.chat.type != 'private': return
    price_min = message.text
    msg = bot.send_message(
        message.chat.id,
        "💰 Шаг 6 из 10\n\n"
        "👇 МАКСИМАЛЬНАЯ ЦЕНА ЗАКАЗА:\n\n"
        "Пример: 50000₽, 100000₽, договорная"
    )
    bot.register_next_step_handler(msg, process_master_price_max, name, service, phone, districts, price_min)

def process_master_price_max(message, name, service, phone, districts, price_min):
    if message.chat.type != 'private': return
    price_max = message.text
    msg = bot.send_message(
        message.chat.id,
        "⏱️ Шаг 7 из 10\n\n"
        "👇 ВАШ ОПЫТ РАБОТЫ:\n\n"
        "Пример: 3 года, 5 лет, 10+ лет"
    )
    bot.register_next_step_handler(msg, process_master_experience, name, service, phone, districts, price_min, price_max)

def process_master_experience(message, name, service, phone, districts, price_min, price_max):
    if message.chat.type != 'private': return
    experience = message.text
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
    if message.chat.type != 'private': return
    portfolio = message.text
    if portfolio.lower() == "пропустить":
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
    if message.chat.type != 'private': return
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

# ================ ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ================
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    if message.chat.type == 'private':
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
