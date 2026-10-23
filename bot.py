import sqlite3
import json
import datetime
import pytz
import os
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = "8853693876:AAHtYFQoYrlZaTdFwEPDOW9mnYIqkNMeP4U"

# --- Lightweight Web Server for Render Health Check ---
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Burka Harbu Schedule Bot is running!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- Define the School Bells Schedule ---
PERIOD_TIMES = {
    1: "2:30 - 3:15",
    2: "3:15 - 4:00",
    3: "4:00 - 4:45",
    4: "5:00 - 5:45", 
    5: "5:45 - 6:30",
    6: "7:30 - 8:15",   
    7: "8:15 - 9:00"
}

# Load the full schedule data using local path
try:
    with open('schedule.json', 'r', encoding='utf-8') as f:
        SCHEDULE_DATA = json.load(f)
except FileNotFoundError:
    print("Error: schedule.json not found! Make sure the file path is correct.")
    SCHEDULE_DATA = {}

# --- Dynamically Extract All Teachers ---
UNIQUE_TEACHERS = set()
for section in SCHEDULE_DATA.values():
    for day in section.values():
        for c in day:
            if c.get('teacher'):
                UNIQUE_TEACHERS.add(c.get('teacher'))
UNIQUE_TEACHERS = sorted(list(UNIQUE_TEACHERS))

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect("school_users.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            telegram_id INTEGER PRIMARY KEY,
            full_name TEXT,
            grade_section TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teachers (
            telegram_id INTEGER PRIMARY KEY,
            teacher_name TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_user(telegram_id):
    conn = sqlite3.connect("school_users.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT full_name, grade_section FROM students WHERE telegram_id = ?", (telegram_id,))
    student = cursor.fetchone()
    if student:
        conn.close()
        return ("student", student[0], student[1])
        
    cursor.execute("SELECT teacher_name FROM teachers WHERE telegram_id = ?", (telegram_id,))
    teacher = cursor.fetchone()
    if teacher:
        conn.close()
        return ("teacher", teacher[0], teacher[0])
        
    conn.close()
    return None

# --- UI Menus ---
def get_main_menu():
    keyboard = [
        [KeyboardButton("📅 Today"), KeyboardButton("📅 Tomorrow")],
        [KeyboardButton("🗓️ This Week"), KeyboardButton("👤 My Profile")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

# --- Student Formatting Engine ---
def build_student_schedule(day_name: str, section: str):
    if section not in SCHEDULE_DATA or day_name not in SCHEDULE_DATA[section] or not SCHEDULE_DATA[section][day_name]:
        return f"📅 *{day_name}*\n━━━━━━━━━━━━━━━━━━━━\nNo classes scheduled for {section} on this day."

    classes = sorted(SCHEDULE_DATA[section][day_name], key=lambda x: int(x.get('period', 0)))
    text = f"📅 *{day_name} Schedule for {section}*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for c in classes:
        p_num = c.get('period', 'Unknown')
        time_str = PERIOD_TIMES.get(int(p_num) if str(p_num).isdigit() else p_num, "Unknown Time")
        text += f"📖 *{c.get('subject', 'Unknown Subject')}*\n🕒 Period {p_num} ({time_str})\n👨‍🏫 {c.get('teacher', 'Unknown Teacher')}\n\n"
        
        if p_num == 3:
            text += "☕ Break (4:45 - 5:00)\n\n"
        elif p_num == 5:
            text += "🍽️ Lunch Break (6:30 - 7:30)\n\n"
            
    text += f"━━━━━━━━━━━━━━━━━━━━\n{len(classes)} classes today"
    return text

# --- Teacher Formatting Engine ---
def build_teacher_schedule(day_name: str, teacher_name: str):
    day_classes = []
    
    for section, days in SCHEDULE_DATA.items():
        if day_name in days:
            for c in days[day_name]:
                if c.get('teacher') == teacher_name:
                    day_classes.append({
                        'period': c.get('period', 0),
                        'subject': c.get('subject', 'Unknown'),
                        'section': section
                    })
                    
    if not day_classes:
        return f"📅 *{day_name}*\n━━━━━━━━━━━━━━━━━━━━\nNo classes scheduled for you on this day."
        
    day_classes = sorted(day_classes, key=lambda x: int(x['period']))
    text = f"📅 *{day_name} Schedule for {teacher_name}*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for c in day_classes:
        p_num = c['period']
        time_str = PERIOD_TIMES.get(int(p_num) if str(p_num).isdigit() else p_num, "Unknown Time")
        text += f"🏫 *Section {c['section']}* - {c['subject']}\n🕒 Period {p_num} ({time_str})\n\n"
        
        if int(p_num) == 3:
            text += "☕ Break (4:45 - 5:00)\n\n"
        elif int(p_num) == 5:
            text += "🍽️ Lunch Break (6:30 - 7:30)\n\n"
            
    text += f"━━━━━━━━━━━━━━━━━━━━\n{len(day_classes)} classes today"
    return text

# --- Registration Flow ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("👨‍🎓 I am a Student", callback_data="role_student")],
        [InlineKeyboardButton("👨‍🏫 I am a Teacher", callback_data="role_teacher")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👋 Welcome to the Burka Harbu Schedule Bot!\n\nAre you registering as a Student or a Teacher?", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    state = context.user_data.get('state')
    
    if state == 'WAITING_FOR_STUDENT_NAME':
        context.user_data['full_name'] = text
        keyboard = [
            [InlineKeyboardButton("9A", callback_data="9A"), InlineKeyboardButton("9B", callback_data="9B"), InlineKeyboardButton("9C", callback_data="9C")],
            [InlineKeyboardButton("10A", callback_data="10A"), InlineKeyboardButton("10B", callback_data="10B")],
            [InlineKeyboardButton("11A", callback_data="11A"), InlineKeyboardButton("11B", callback_data="11B"), InlineKeyboardButton("11C", callback_data="11C")],
            [InlineKeyboardButton("12A", callback_data="12A"), InlineKeyboardButton("12B", callback_data="12B"), InlineKeyboardButton("12C", callback_data="12C")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Welcome {text}! Now select your **Grade & Section**:", reply_markup=reply_markup)
        context.user_data['state'] = None
        return

    user = get_user(update.message.from_user.id)
    if not user:
        await update.message.reply_text("Please type /start to register first.")
        return

    role, name, assignment = user
    today = datetime.datetime.now(pytz.timezone('Africa/Nairobi')).strftime('%A')
    
    if text == "📅 Today":
        msg = build_student_schedule(today, assignment) if role == "student" else build_teacher_schedule(today, assignment)
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    elif text == "📅 Tomorrow":
        tomorrow = (datetime.datetime.now(pytz.timezone('Africa/Nairobi')) + datetime.timedelta(days=1)).strftime('%A')
        msg = build_student_schedule(tomorrow, assignment) if role == "student" else build_teacher_schedule(tomorrow, assignment)
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    elif text == "🗓️ This Week":
        week_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        full_week_msg = f"🗓️ **Full Week Schedule for {name}**\n\n"
        for day in week_days:
            day_msg = build_student_schedule(day, assignment) if role == "student" else build_teacher_schedule(day, assignment)
            if "No classes scheduled" not in day_msg:
                full_week_msg += day_msg + "\n\n"
        await update.message.reply_text(full_week_msg, parse_mode='Markdown')
        
    elif text == "👤 My Profile":
        if role == "student":
            await update.message.reply_text(f"👤 **Name:** {name}\n🏫 **Section:** {assignment}", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"👨‍🏫 **Teacher Profile:** {name}", parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    
    if query.data == "role_student":
        context.user_data['state'] = 'WAITING_FOR_STUDENT_NAME'
        await query.edit_message_text("👨‍🎓 **Student Registration**\n\nPlease type your **Full Name**:")
        return
        
    elif query.data == "role_teacher":
        teacher_buttons = [InlineKeyboardButton(t, callback_data=f"tch_{t}") for t in UNIQUE_TEACHERS]
        teacher_keyboard = [teacher_buttons[i:i+3] for i in range(0, len(teacher_buttons), 3)]
        reply_markup = InlineKeyboardMarkup(teacher_keyboard)
        await query.edit_message_text("👨‍🏫 **Teacher Registration**\n\nPlease select your name from the list:", reply_markup=reply_markup)
        return

    conn = sqlite3.connect("school_users.db")
    cursor = conn.cursor()
    
    if query.data.startswith("tch_"):
        teacher_name = query.data.replace("tch_", "")
        cursor.execute("DELETE FROM students WHERE telegram_id = ?", (telegram_id,))
        cursor.execute("INSERT OR REPLACE INTO teachers (telegram_id, teacher_name) VALUES (?, ?)", (telegram_id, teacher_name))
        conn.commit()
        await query.edit_message_text(f"✅ Successfully registered as Teacher: **{teacher_name}**!", parse_mode='Markdown')
    else:
        full_name = context.user_data.get('full_name', "Student")
        grade_section = query.data
        cursor.execute("DELETE FROM teachers WHERE telegram_id = ?", (telegram_id,))
        cursor.execute("INSERT OR REPLACE INTO students (telegram_id, full_name, grade_section) VALUES (?, ?, ?)", (telegram_id, full_name, grade_section))
        conn.commit()
        await query.edit_message_text(f"✅ Successfully registered {full_name} into {grade_section}!")
        
    conn.close()
    await context.bot.send_message(chat_id=telegram_id, text="Use the menu below to check your classes:", reply_markup=get_main_menu())

async def send_nightly_updates(context: ContextTypes.DEFAULT_TYPE):
    tomorrow = (datetime.datetime.now(pytz.timezone('Africa/Nairobi')) + datetime.timedelta(days=1)).strftime('%A')
    if tomorrow in ['Saturday', 'Sunday']:
        return

    conn = sqlite3.connect("school_users.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT telegram_id, grade_section FROM students")
    for telegram_id, section in cursor.fetchall():
        msg = f"🌙 **Nightly Update: Tomorrow's Schedule**\n\n" + build_student_schedule(tomorrow, section)
        try:
            await context.bot.send_message(chat_id=telegram_id, text=msg, parse_mode='Markdown')
        except Exception:
            pass

    cursor.execute("SELECT telegram_id, teacher_name FROM teachers")
    for telegram_id, teacher_name in cursor.fetchall():
        msg = f"🌙 **Nightly Update: Tomorrow's Schedule**\n\n" + build_teacher_schedule(tomorrow, teacher_name)
        try:
            await context.bot.send_message(chat_id=telegram_id, text=msg, parse_mode='Markdown')
        except Exception:
            pass
            
    conn.close()

def main():
    # Start the Flask web server in a separate background thread
    threading.Thread(target=run_web_server, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()
    
    tz = pytz.timezone('Africa/Nairobi')
    time_to_run = datetime.time(hour=20, minute=0, tzinfo=tz)
    app.job_queue.run_daily(send_nightly_updates, time=time_to_run)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 Bot is live on Render!")
    app.run_polling()

if __name__ == '__main__':
    main()
