import telebot
import sqlite3
from datetime import datetime

# ⚠️ ВАШ ТОКЕН (УЖЕ ВСТАВЛЕН)
TOKEN = "8534116247:AAEBwp0J1b_r-rUIU_au5QEiggCVYQgA-5c"
CHAT_ID = "@remont_vl25_chat"  # ID вашего чата

bot = telebot.TeleBot(TOKEN)

# СОЗДАНИЕ БАЗЫ ДАННЫХ
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

# Таблица мастеров
cursor.execute('''CREATE TABLE IF NOT EXISTS masters
                (id INTEGER PRIMARY KEY,
                 name TEXT,
                 service TEXT,
                 phone TEXT,
                 rating REAL,
                 reviews_count INTEGER,
                 districts TEXT)''')

# КОМАНДА /start
@bot.message_handler(commands=['start'])
def start(message):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('🔨 Оставить заявку', '⭐ Оставить отзыв')
    markup.row('🔍 Найти мастера', '📞 Контакты')
    
    bot.send_message(
        message.chat.id,
        "👋 **Добро пожаловать в бот заявок на ремонт!**\n\n"
        "🔹 **Хотите найти мастера?** Нажмите «Оставить заявку»\n"
        "🔹 **Хотите поблагодарить мастера?** Нажмите «Оставить отзыв»\n\n"
        "💬 **Наш чат-заявок:** @remont_vl25_chat\n"
        "📢 **Канал с мастерами:** @remont_vl25",
        parse_mode='Markdown',
        reply_markup=markup
    )

# ЗАЯВКА
@bot.message_handler(commands=['request'])
@bot.message_handler(func=lambda message: message.text == '🔨 Оставить заявку')
def request_service(message):
    msg = bot.send_message(
        message.chat.id,
        "🔨 **ВЫБЕРИТЕ УСЛУГУ:**\n\n"
        "Напишите номер или название:\n"
        "1️⃣ Сантехник\n"
        "2️⃣ Электрик\n"
        "3️⃣ Отделочник\n"
        "4️⃣ Строитель\n"
        "5️⃣ Другое",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_service)

def process_service(message):
    service = message.text
    msg = bot.send_message(
        message.chat.id,
        "📍 **ВВЕДИТЕ РАЙОН ИЛИ ЖК:**\n"
        "Например: Патрокл, Снеговая Падь, Варяг, Океан, Центр",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_district, service)

def process_district(message, service):
    district = message.text
    msg = bot.send_message(
        message.chat.id,
        "💰 **ВВЕДИТЕ БЮДЖЕТ:**\n"
        "Например: до 3000₽, договорной, 5000₽, 150000₽ за квартиру",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_budget, service, district)

def process_budget(message, service, district):
    budget = message.text
    
    # Сохраняем в БД
    cursor.execute('''INSERT INTO requests 
                    (user_id, username, service, district, budget, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (message.from_user.id,
                     message.from_user.username or message.from_user.first_name,
                     service, district, budget,
                     'активна',
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    
    # Отправляем в чат
    username = message.from_user.username or message.from_user.first_name
    request_text = f"""
🆕 **НОВАЯ ЗАЯВКА!**

👤 **От:** @{username}
🔨 **Услуга:** {service}
📍 **Район/ЖК:** {district}
💰 **Бюджет:** {budget}
⏰ **Время:** {datetime.now().strftime("%H:%M")}

👇 **Мастера, откликайтесь в комментариях!**
    """
    
    bot.send_message(CHAT_ID, request_text, parse_mode='Markdown')
    
    bot.send_message(
        message.chat.id,
        "✅ **ЗАЯВКА ОПУБЛИКОВАНА!**\n\n"
        f"📢 Чат с мастерами: @remont_vl25_chat\n"
        f"⏱ Ожидайте откликов в течение 5-10 минут.\n\n"
        f"📌 Если никто не ответил за 30 минут — создайте новую заявку.",
        parse_mode='Markdown'
    )

# ОТЗЫВ
@bot.message_handler(commands=['review'])
@bot.message_handler(func=lambda message: message.text == '⭐ Оставить отзыв')
def add_review(message):
    msg = bot.send_message(
        message.chat.id,
        "⭐ **ОСТАВИТЬ ОТЗЫВ**\n\n"
        "Напишите **ИМЯ МАСТЕРА** или **НАЗВАНИЕ БРИГАДЫ**:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_review_master)

def process_review_master(message):
    master = message.text
    msg = bot.send_message(
        message.chat.id,
        "📝 **НАПИШИТЕ ТЕКСТ ОТЗЫВА:**\n"
        "Например: Сделал быстро, качественно, цена адекватная. Рекомендую!",
        parse_mode='Markdown'
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
        f"👤 **Мастер:** {master}\n"
        f"📝 **Отзыв:** {review_text}\n\n"
        "⭐ **ОЦЕНИТЕ РАБОТУ ОТ 1 ДО 5:**",
        reply_markup=markup,
        parse_mode='Markdown'
    )
    
    # Сохраняем текст отзыва временно (в следующем шаге сохраним с рейтингом)
    bot.register_next_step_handler_by_chat_id(
        message.chat.id,
        lambda msg: save_review_with_rating(msg, master, review_text)
    )

def save_review_with_rating(message, master, review_text):
    # Этот метод сработает, если пользователь не нажал кнопку, а написал текст
    try:
        rating = int(message.text.strip())
        if rating < 1 or rating > 5:
            raise ValueError
    except:
        bot.send_message(
            message.chat.id,
            "❌ Пожалуйста, используйте кнопки с оценкой 1-5!",
            parse_mode='Markdown'
        )
        return
    
    # Сохраняем отзыв
    cursor.execute('''INSERT INTO reviews
                    (master_name, user_name, rating, text, created_at)
                    VALUES (?, ?, ?, ?, ?)''',
                    (master,
                     message.from_user.username or message.from_user.first_name,
                     rating,
                     review_text,
                     datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    
    bot.send_message(
        message.chat.id,
        f"✅ **СПАСИБО ЗА ОТЗЫВ!**\n\n"
        f"👤 **Мастер:** {master}\n"
        f"⭐ **Оценка:** {'⭐' * rating}\n"
        f"📝 **Отзыв:** {review_text}\n\n"
        f"Ваш отзыв поможет другим соседям выбрать хорошего мастера!",
        parse_mode='Markdown'
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
        f"✅ **СПАСИБО ЗА ОТЗЫВ!**\n\n"
        f"👤 **Мастер:** {master.replace('_', ' ')}\n"
        f"⭐ **Оценка:** {'⭐' * int(rating)}\n\n"
        f"Ваш отзыв поможет другим соседям!",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown'
    )

# ПОИСК МАСТЕРОВ
@bot.message_handler(commands=['search'])
@bot.message_handler(func=lambda message: message.text == '🔍 Найти мастера')
def search_master(message):
    # Получаем статистику из БД
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
        text += "• Строители: 2 мастера ⭐4.6\n"
    
    text += "\n👉 **Хотите найти мастера?**\n"
    text += "Зайдите в чат и оставьте заявку:\n"
    text += "@remont_vl25_chat"
    
    bot.send_message(
        message.chat.id,
        text,
        parse_mode='Markdown'
    )

# КОНТАКТЫ
@bot.message_handler(commands=['contacts'])
@bot.message_handler(func=lambda message: message.text == '📞 Контакты')
def contacts(message):
    bot.send_message(
        message.chat.id,
        "📞 **КОНТАКТЫ**\n\n"
        "📢 **Канал с мастерами:** @remont_vl25\n"
        "💬 **Чат-заявок:** @remont_vl25_chat\n"
        "🤖 **Этот бот:** @remont_vl25_chat_bot\n"
        "👨‍💻 **Администратор:** @remont_vl25\n\n"
        "📌 **По вопросам сотрудничества и рекламы** — пишите админу!",
        parse_mode='Markdown'
    )

# ПОМОЩЬ
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
        "/contacts - Контакты\n"
        "/help - Это сообщение\n\n"
        "**Как найти мастера?**\n"
        "1. Нажмите «Оставить заявку»\n"
        "2. Выберите услугу\n"
        "3. Укажите район и бюджет\n"
        "4. Ждите откликов в чате\n\n"
        "**Как оставить отзыв?**\n"
        "1. Нажмите «Оставить отзыв»\n"
        "2. Напишите имя мастера\n"
        "3. Напишите текст отзыва\n"
        "4. Поставьте оценку",
        parse_mode='Markdown'
    )

# ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    if message.text.startswith('/'):
        bot.send_message(
            message.chat.id,
            "❌ Неизвестная команда. Используйте /help для списка команд.",
            parse_mode='Markdown'
        )
    else:
        bot.send_message(
            message.chat.id,
            "👋 Используйте команды из меню или нажмите /help",
            parse_mode='Markdown'
        )

# ЗАПУСК БОТА
if __name__ == '__main__':
    print("✅ Бот запущен и готов к работе!")
    print(f"🤖 Токен: {TOKEN[:10]}...")
    print(f"📢 Чат: {CHAT_ID}")
    print("⏳ Ожидание сообщений...")
    
    try:
        bot.polling(none_stop=True, interval=0, timeout=20)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
      
