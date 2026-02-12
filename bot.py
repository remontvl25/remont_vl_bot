# ===== В САМОМ НАЧАЛЕ КОДА =====
import telebot
import sqlite3
import os
from datetime import datetime

TOKEN = os.environ.get('TOKEN', "8534116247:AAEBwp0J1b_r-rUIU_au5QEiggCVYQgA-5c")
CHAT_ID = "@remont_vl25_chat"  // ПРАВИЛЬНО! с подчеркиваниями

bot = telebot.TeleBot(TOKEN)
# ================================

# ===== В ФУНКЦИИ start() =====
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
        "💬 **Наш чат-заявок:** @remont_vl25_chat\n"  // ПРАВИЛЬНО!
        "📢 **Канал с мастерами:** @remont_vl25",
        parse_mode='Markdown',
        reply_markup=markup
    )
# ==============================

# ===== В ФУНКЦИИ process_budget() =====
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
        f"📢 Чат с мастерами: @remont_vl25_chat\n"  // ПРАВИЛЬНО!
        f"⏱ Ожидайте откликов в течение 5-10 минут.\n\n"
        f"📌 Если никто не ответил за 30 минут — создайте новую заявку.",
        parse_mode='Markdown'
    )
# ======================================

# ===== В ФУНКЦИИ search_master() =====
@bot.message_handler(commands=['search'])
@bot.message_handler(func=lambda message: message.text == '🔍 Найти мастера')
def search_master(message):
    text = "🔍 **МАСТЕРА В БАЗЕ:**\n\n"
    text += "• Электрики: 5 мастеров ⭐4.8\n"
    text += "• Сантехники: 4 мастера ⭐4.9\n"
    text += "• Отделочники: 3 мастера ⭐4.7\n"
    text += "• Строители: 2 мастера ⭐4.6\n\n"
    text += "👉 **Хотите найти мастера?**\n"
    text += "Зайдите в чат и оставьте заявку:\n"
    text += "@remont_vl25_chat"  // ПРАВИЛЬНО!
    
    bot.send_message(
        message.chat.id,
        text,
        parse_mode='Markdown'
    )
# ======================================

# ===== В ФУНКЦИИ contacts() =====
@bot.message_handler(commands=['contacts'])
@bot.message_handler(func=lambda message: message.text == '📞 Контакты')
def contacts(message):
    bot.send_message(
        message.chat.id,
        "📞 **КОНТАКТЫ**\n\n"
        "📢 **Канал с мастерами:** @remont_vl25\n"
        "💬 **Чат-заявок:** @remont_vl25_chat\n"  // ПРАВИЛЬНО!
        "🤖 **Этот бот:** @remont_vl25_chat_bot\n"
        "👨‍💻 **Администратор:** @remont_vl25\n\n"
        "📌 **По вопросам сотрудничества и рекламы** — пишите админу!",
        parse_mode='Markdown'
    )
# ================================
