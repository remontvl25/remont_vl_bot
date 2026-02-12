import telebot
import sqlite3
import os
import time
from datetime import datetime

# ================ НАСТРОЙКИ ================
# Токен берется из переменных окружения Railway
TOKEN = os.environ.get('TOKEN')
CHAT_ID = "@remontvl25chat"  # ПРАВИЛЬНАЯ ссылка на чат!
CHANNEL_LINK = "@remont_vl25"  # Ссылка на канал

# Создаем бота
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
                 district TEXT,
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

# ================ КОМАНДА /start ================
@bot.message_handler(commands=['start'])
def start(message):
    # Создаем клавиатуру
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('🔨 Оставить заявку', '⭐ Оставить отзыв')
    markup.row('🔍 Найти мастера', '📞 Контакты')
    markup.row('📢 Канал с мастерами')
    
    # Отправляем приветствие
    bot.send_message(
        message.chat.id,
        "👋 Добро пожаловать в бот заявок на ремонт!\n\n"
        "🔹 Хотите найти мастера? Нажмите «Оставить заявку»\n"
        "🔹 Хотите поблагодарить мастера? Нажмите «Оставить отзыв»\n\n"
        f"💬 Чат-заявок: {CHAT_ID}\n"
        f"📢 Канал с мастерами: {CHANNEL_LINK}",
        reply_markup=markup
    )

# ================ КНОПКА "КАНАЛ С МАСТЕРАМИ" ================
@bot.message_handler(func=lambda message: message.text == '📢 Канал с мастерами')
def channel_link(message):
    # Создаем инлайн-кнопку со ссылкой
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
        "Шаг 1 из 4\n"
        "👇 **ВЫБЕРИТЕ УСЛУГУ:**\n\n"
        "Напишите номер или название:\n"
        "1 - Сантехник\n"
        "2 - Электрик\n"
        "3 - Отделочник\n"
        "4 - Строитель\n"
        "5 - Другое"
    )
    bot.register_next_step_handler(msg, process_service)

def process_service(message):
    service = message.text
    msg = bot.send_message(
        message.chat.id,
        "📝 **Шаг 2 из 4**\n\n"
        "👇 **КРАТКО ОПИШИТЕ ЗАДАЧУ:**\n\n"
        "Например:\n"
        "• Заменить смеситель на кухне\n"
        "• Перенести 3 розетки в зале\n"
        "• Поклеить обои в спальне 15м²",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_description, service)
def process_description(message, service):
    description = message.text
    msg = bot.send_message(
        message.chat.id,
        "📍 **Шаг 3 из 4**\n\n"
        "👇 **ВВЕДИТЕ РАЙОН ИЛИ ЖК:**\n"
        "Например: Патрокл, Снеговая Падь, Варяг, Океан"
    )
    bot.register_next_step_handler(msg, process_district, service, description)
def process_district(message, service, description):
    district = message.text
    msg = bot.send_message(
        message.chat.id,
        "📅 **Шаг 4 из 4**\n\n"
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
        "💰 **ФИНАЛЬНЫЙ ШАГ**\n\n"
        "👇 **ВВЕДИТЕ БЮДЖЕТ:**\n"
        "Например: до 3000₽, договорной, 50000₽ за квартиру"
    )
    bot.register_next_step_handler(msg, process_budget, service, description, district, date)
def process_budget(message, service, description, district, date):
    budget = message.text
    
    # Сохраняем в БД (добавляем новые колонки)
    cursor.execute('''INSERT INTO requests 
                    (user_id, username, service, description, district, date, budget, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (message.from_user.id,
                     message.from_user.username or message.from_user.first_name,
                     service, description, district, date, budget,
                     'активна',
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    
    # Отправляем заявку в чат с НОВЫМИ полями
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
    
    bot.send_message(CHAT_ID, request_text, parse_mode='Markdown')
    
    bot.send_message(
        message.chat.id,
        f"✅ **ЗАЯВКА ОПУБЛИКОВАНА!**\n\n"
        f"📢 Чат с мастерами: {CHAT_ID}\n"
        f"⏱ Ожидайте откликов в течение 5-10 минут.\n\n"
        f"📌 Если никто не ответил за 30 минут — создайте новую заявку.",
        parse_mode='Markdown'
    )
# Добавляем новые колонки в таблицу requests (если их ещё нет)
try:
    cursor.execute('ALTER TABLE requests ADD COLUMN description TEXT')
except:
    pass  # колонка уже есть

try:
    cursor.execute('ALTER TABLE requests ADD COLUMN date TEXT')
except:
    pass  # колонка уже есть
# ================ ОТЗЫВ ================
@bot.message_handler(commands=['review'])
@bot.message_handler(func=lambda message: message.text == '⭐ Оставить отзыв')
def add_review(message):
    msg = bot.send_message(
        message.chat.id,
        "⭐ ОСТАВИТЬ ОТЗЫВ\n\n"
        "Напишите ИМЯ МАСТЕРА или НАЗВАНИЕ БРИГАДЫ:"
    )
    bot.register_next_step_handler(msg, process_review_master)

def process_review_master(message):
    master = message.text
    msg = bot.send_message(
        message.chat.id,
        "📝 НАПИШИТЕ ТЕКСТ ОТЗЫВА:\n"
        "Например: Сделал быстро, качественно, цена адекватная"
    )
    bot.register_next_step_handler(msg, process_review_text, master)

def process_review_text(message, master):
    review_text = message.text
    
    # Клавиатура с оценкой
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
        f"👤 Мастер: {master}\n"
        f"📝 Отзыв: {review_text}\n\n"
        "⭐ ОЦЕНИТЕ РАБОТУ ОТ 1 ДО 5:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('rating_'))
def rating_callback(call):
    data = call.data.split('_')
    rating = data[1]
    master = '_'.join(data[2:])
    
    # Сохраняем отзыв
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
        f"✅ СПАСИБО ЗА ОТЗЫВ!\n\n"
        f"👤 Мастер: {master.replace('_', ' ')}\n"
        f"⭐ Оценка: {'⭐' * int(rating)}\n\n"
        f"Ваш отзыв поможет другим соседям!",
        call.message.chat.id,
        call.message.message_id
    )

# ================ ПОИСК МАСТЕРОВ ================
@bot.message_handler(commands=['search'])
@bot.message_handler(func=lambda message: message.text == '🔍 Найти мастера')
def search_master(message):
    text = "🔍 МАСТЕРА В БАЗЕ:\n\n"
    text += "• Электрики: 5 мастеров ⭐4.8\n"
    text += "• Сантехники: 4 мастера ⭐4.9\n"
    text += "• Отделочники: 3 мастера ⭐4.7\n"
    text += "• Строители: 2 мастера ⭐4.6\n\n"
    text += f"👉 Хотите найти мастера?\n"
    text += f"Зайдите в чат и оставьте заявку:\n"
    text += f"{CHAT_ID}"
    
    # Кнопка с каналом
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
    # Создаем инлайн-кнопки
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
        f"📞 КОНТАКТЫ\n\n"
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
        "❓ ПОМОЩЬ\n\n"
        "Доступные команды:\n"
        "/start - Запустить бота\n"
        "/request - Оставить заявку\n"
        "/review - Оставить отзыв\n"
        "/search - Поиск мастеров\n"
        "/contacts - Контакты\n"
        "/help - Это сообщение\n\n"
        "Как найти мастера?\n"
        "1. Нажмите «Оставить заявку»\n"
        "2. Выберите услугу\n"
        "3. Укажите район и бюджет\n"
        "4. Ждите откликов в чате"
    )

# ================ ЗАПУСК БОТА ================
if __name__ == '__main__':
    print("✅ Бот запускается...")
    print(f"🤖 Токен загружен из переменных")
    print(f"📢 Чат: {CHAT_ID}")
    print(f"📢 Канал: {CHANNEL_LINK}")
    print("⏳ Бот работает 24/7...")
    
    # Бесконечный цикл с обработкой ошибок
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            if "409" in str(e):
                print("🔄 Обнаружен конфликт! Сбрасываем...")
                # Принудительный сброс через API
                import requests
                requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")
                time.sleep(2)
            print("🔄 Перезапуск через 5 секунд...")
            time.sleep(5)
            continue
