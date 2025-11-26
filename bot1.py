import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import random
import time
import threading
from datetime import datetime
import requests
import json
import os

# إعدادات البوت
TOKEN = "7679895284:AAE-_mwAKvJUqfonAxEn7Zj-1p6CtpAfxnw"
bot = telebot.TeleBot(TOKEN)

# قائمة الإيموجيات المدعومة في تفاعلات تليجرام
SUPPORTED_EMOJIS = ["👍", "❤️", "🔥", "👏", "😍", "🤩", "🎉", "🙌", "🚀", "⭐"]

# قاعدة البيانات
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('interactions.db', check_same_thread=False)
        self.setup_database()
    
    def setup_database(self):
        """إعداد قاعدة البيانات"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE,
                channel_username TEXT,
                owner_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_token TEXT UNIQUE,
                bot_username TEXT,
                channel_id TEXT,
                is_active BOOLEAN DEFAULT 1,
                added_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels (channel_id)
            )
        ''')
        
        self.conn.commit()
        print("✅ Database setup completed successfully!")

db = Database()

# نظام التحكم بالبوت
class BotController:
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.admins = []
        self.waiting_for_forward = {}  # تخزين المستخدمين المنتظرين لإعادة التوجيه
        self.interaction_thread = None  # thread واحد للتفاعلات
        
    def add_admin(self, user_id):
        if user_id not in self.admins:
            self.admins.append(user_id)
    
    def is_admin(self, user_id):
        return user_id in self.admins
    
    def set_waiting_for_forward(self, user_id, channel_id):
        """تعيين المستخدم في وضع انتظار إعادة توجيه المنشور"""
        self.waiting_for_forward[user_id] = channel_id
    
    def get_waiting_channel(self, user_id):
        """الحصول على القناة التي ينتظرها المستخدم"""
        return self.waiting_for_forward.get(user_id)
    
    def clear_waiting(self, user_id):
        """مسح حالة الانتظار للمستخدم"""
        if user_id in self.waiting_for_forward:
            del self.waiting_for_forward[user_id]
    
    def start_interaction_thread(self, target_func, args=()):
        """بدء thread تفاعل واحد فقط"""
        if self.interaction_thread and self.interaction_thread.is_alive():
            return False  # يوجد thread نشط بالفعل
        
        self.interaction_thread = threading.Thread(target=target_func, args=args, daemon=True)
        self.interaction_thread.start()
        return True

controller = BotController(bot)

# إضافة المطور كأدمن
DEVELOPER_ID = 1675396915 
controller.add_admin(DEVELOPER_ID)

# نظام التفاعل اليدوي
class ManualInteraction:
    def __init__(self):
        self.active_interactions = {}
        self.current_report_message_id = {}  # تخزين آخر رسالة تقرير لكل مستخدم
    
    def update_report_message(self, user_id, message_id):
        """تحديث رسالة التقرير الحالية للمستخدم"""
        self.current_report_message_id[user_id] = message_id
    
    def get_report_message_id(self, user_id):
        """الحصول على رسالة التقرير الحالية للمستخدم"""
        return self.current_report_message_id.get(user_id)
    
    def interact_with_forwarded_post(self, channel_id, message_id, user_id, original_message_id):
        """التفاعل مع منشور تم توجيهه"""
        cursor = db.conn.cursor()
        
        # جلب جميع البوتات النشطة لهذه القناة
        cursor.execute('''
            SELECT bot_token, bot_username, added_by FROM bots 
            WHERE channel_id = ? AND is_active = 1
        ''', (channel_id,))
        
        bots = cursor.fetchall()
        
        successful_interactions = []
        failed_interactions = []
        total_bots = len(bots)
        
        # تحديث الرسالة الأصلية لتظهر التقدم
        progress_message = self.create_progress_message(channel_id, message_id, 0, total_bots, successful_interactions, failed_interactions)
        bot.edit_message_text(
            progress_message,
            user_id,
            original_message_id,
            parse_mode='Markdown'
        )
        
        for index, bot_data in enumerate(bots):
            bot_token, bot_username, owner_id = bot_data
            
            # استخدام إيموجي عشوائي
            emoji = random.choice(SUPPORTED_EMOJIS)
            result = self.try_single_reaction(bot_token, channel_id, message_id, emoji)
            
            if result["success"]:
                successful_interactions.append(f"{bot_username} ({emoji})")
            else:
                failed_interactions.append(bot_username)
            
            # تحديث التقدم كل 5 بوتات أو عند الانتهاء
            if (index + 1) % 5 == 0 or (index + 1) == total_bots:
                progress = index + 1
                progress_message = self.create_progress_message(channel_id, message_id, progress, total_bots, successful_interactions, failed_interactions)
                bot.edit_message_text(
                    progress_message,
                    user_id,
                    original_message_id,
                    parse_mode='Markdown'
                )
            
            # وقت انتظار بين التفاعلات
            time.sleep(random.uniform(2, 5))
        
        # إرسال التقرير النهائي
        final_report = self.create_final_report(channel_id, message_id, successful_interactions, failed_interactions, total_bots)
        bot.edit_message_text(
            final_report,
            user_id,
            original_message_id,
            parse_mode='HTML'
        )
        
        return {
            "successful": successful_interactions,
            "failed": failed_interactions,
            "total_bots": total_bots
        }
    
    def create_progress_message(self, channel_id, message_id, progress, total, successful, failed):
        """إنشاء رسالة تقدم"""
        percentage = (progress / total) * 100 if total > 0 else 0
        
        progress_bar = "🟢" * int(percentage / 10) + "⚪" * (10 - int(percentage / 10))
        
        return f"""
🔄 **جاري التفاعل مع المنشور...**

🏷 **القناة:** `{channel_id}`
📝 **المنشور:** `{message_id}`

📊 **التقدم:** {progress}/{total} ({percentage:.1f}%)
{progress_bar}

✅ **ناجحة:** {len(successful)}
❌ **فاشلة:** {len(failed)}

⏰ **الوقت:** {datetime.now().strftime('%H:%M:%S')}
        """
    
    def create_final_report(self, channel_id, message_id, successful, failed, total_bots):
        """إنشاء التقرير النهائي"""
        report_message = f"""
✅ **تم الانتهاء من التفاعل!**

🏷 **القناة:** `{channel_id}`
📝 **المنشور:** `{message_id}`

📊 **النتائج النهائية:**
• 🤖 **إجمالي البوتات:** {total_bots}
• ✅ **ناجحة:** {len(successful)}
• ❌ **فاشلة:** {len(failed)}
• 📈 **نسبة النجاح:** {(len(successful)/total_bots*100):.1f}%
        """
        
        if successful:
            report_message += f"\n🤖 **البوتات الناجحة:**\n{chr(10).join(['• ' + bot for bot in successful])}"
        
        if failed:
            report_message += f"\n\n🔧 **البوتات الفاشلة:**\n{chr(10).join(['• ' + bot for bot in failed])}"
        
        report_message += f"\n\n⏰ **وقت الانتهاء:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return report_message
    
    def try_single_reaction(self, bot_token, channel_id, message_id, emoji):
        """محاولة إضافة تفاعل بإيموجي واحد"""
        try:
            url = f"https://api.telegram.org/bot{bot_token}/setMessageReaction"
            payload = {
                "chat_id": str(channel_id),
                "message_id": int(message_id),
                "reaction": [{"type": "emoji", "emoji": emoji}]
            }
            
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            
            return {"success": result.get("ok", False)}
                
        except Exception as e:
            print(f"🚫 Error for emoji {emoji}: {str(e)}")
            return {"success": False}

# إنشاء نظام التفاعل اليدوي
manual_interaction = ManualInteraction()

# الأوامر الرئيسية
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    
    if controller.is_admin(user_id):
        show_admin_panel(message)
    else:
        bot.reply_to(message, "مرحباً! هذا البوت مخصص لإدارة التفاعلات التلقائية.")

def show_admin_panel(message):
    keyboard = InlineKeyboardMarkup()
    
    buttons = [
        [InlineKeyboardButton("📊 إحصائيات", callback_data="stats")],
        [InlineKeyboardButton("📺 إدارة القنوات", callback_data="manage_channels")],
        [InlineKeyboardButton("🤖 إدارة البوتات", callback_data="manage_bots")],
        [InlineKeyboardButton("🔄 تفاعل يدوي", callback_data="manual_interact")],
        [InlineKeyboardButton("⚡ تفاعل فوري", callback_data="instant_interact")]
    ]
    
    for row in buttons:
        keyboard.row(*row)
    
    bot.send_message(
        message.chat.id,
        "🛠 **لوحة التحكم الإدارية**\n\nاختر الإعداد الذي تريد تعديله:",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

# نظام إدارة القنوات
@bot.callback_query_handler(func=lambda call: call.data == "manage_channels")
def manage_channels(call):
    keyboard = InlineKeyboardMarkup()
    
    buttons = [
        [InlineKeyboardButton("➕ إضافة قناة", callback_data="add_channel")],
        [InlineKeyboardButton("📋 قائمة القنوات", callback_data="list_channels")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
    ]
    
    for row in buttons:
        keyboard.row(*row)
    
    bot.edit_message_text(
        "📺 **إدارة القنوات**\n\nاختر الإجراء المطلوب:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data == "add_channel")
def add_channel_step1(call):
    msg = bot.send_message(
        call.message.chat.id,
        "📝 **أرسل معرف القناة:**\n\nمثال: @channel_username أو -1001234567890",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, add_channel_step2)

def add_channel_step2(message):
    try:
        channel_id = message.text.strip()
        chat = bot.get_chat(channel_id)
        
        cursor = db.conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO channels (channel_id, channel_username, owner_id) VALUES (?, ?, ?)',
            (str(chat.id), getattr(chat, 'username', None), message.from_user.id)
        )
        db.conn.commit()
        
        bot.send_message(message.chat.id, f"✅ **تمت إضافة القناة:** {chat.title}")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ **فشل في إضافة القناة:** {str(e)}")

# نظام إدارة البوتات
@bot.callback_query_handler(func=lambda call: call.data == "manage_bots")
def manage_bots(call):
    keyboard = InlineKeyboardMarkup()
    
    buttons = [
        [InlineKeyboardButton("➕ إضافة بوت", callback_data="add_bot")],
        [InlineKeyboardButton("📋 قائمة البوتات", callback_data="list_bots")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
    ]
    
    for row in buttons:
        keyboard.row(*row)
    
    bot.edit_message_text(
        "🤖 **إدارة البوتات**\n\nاختر الإجراء المطلوب:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data == "add_bot")
def add_bot_step1(call):
    cursor = db.conn.cursor()
    cursor.execute('SELECT channel_id, channel_username FROM channels')
    channels = cursor.fetchall()
    
    if not channels:
        bot.answer_callback_query(call.id, "❌ لا توجد قنوات مضافة. أضف قناة أولاً.")
        return
    
    keyboard = InlineKeyboardMarkup()
    for channel in channels:
        channel_id, username = channel
        name = f"@{username}" if username else f"ID: {channel_id}"
        keyboard.add(InlineKeyboardButton(name, callback_data=f"select_channel_{channel_id}"))
    
    keyboard.add(InlineKeyboardButton("🔙 رجوع", callback_data="manage_bots"))
    
    bot.edit_message_text(
        "📺 **اختر القناة لإضافة البوت لها:**",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("select_channel_"))
def add_bot_step2(call):
    channel_id = call.data.replace("select_channel_", "")
    
    msg = bot.send_message(
        call.message.chat.id,
        f"🔐 **أرسل توكن البوت** لإضافته للقناة `{channel_id}`:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, add_bot_step3, channel_id)

def add_bot_step3(message, channel_id):
    try:
        bot_token = message.text.strip()
        test_bot = telebot.TeleBot(bot_token)
        bot_info = test_bot.get_me()
        
        cursor = db.conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO bots (bot_token, bot_username, channel_id, added_by) VALUES (?, ?, ?, ?)',
            (bot_token, bot_info.username, channel_id, message.from_user.id)
        )
        db.conn.commit()
        
        bot.send_message(
            message.chat.id,
            f"✅ **تمت إضافة البوت:** @{bot_info.username}\n"
            f"📺 **للقناة:** {channel_id}"
        )
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ **فشل في إضافة البوت:** {str(e)}")

# التفاعل اليدوي
@bot.callback_query_handler(func=lambda call: call.data == "manual_interact")
def manual_interact(call):
    cursor = db.conn.cursor()
    cursor.execute('SELECT channel_id, channel_username FROM channels')
    channels = cursor.fetchall()
    
    if not channels:
        bot.answer_callback_query(call.id, "❌ لا توجد قنوات مضافة. أضف قناة أولاً.")
        return
    
    keyboard = InlineKeyboardMarkup()
    for channel in channels:
        channel_id, username = channel
        name = f"@{username}" if username else f"ID: {channel_id}"
        keyboard.add(InlineKeyboardButton(name, callback_data=f"interact_channel_{channel_id}"))
    
    keyboard.add(InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
    
    bot.edit_message_text(
        "🔄 **اختر القناة للتفاعل مع منشوراتها:**",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("interact_channel_"))
def select_channel_for_interaction(call):
    channel_id = call.data.replace("interact_channel_", "")
    
    # حفظ حالة الانتظار للمستخدم
    controller.set_waiting_for_forward(call.from_user.id, channel_id)
    
    bot.edit_message_text(
        f"📨 **تم اختيار القناة:** `{channel_id}`\n\n"
        f"⏳ **الآن قم بتوجيه المنشور الذي تريد التفاعل عليه من القناة إلى هذا البوت...**\n\n"
        f"💡 **طريقة الاستخدام:**\n"
        f"1. اذهب إلى القناة المطلوبة\n"
        f"2. اختر المنشور الذي تريد التفاعل عليه\n"
        f"3. اضغط على زر Forward (إعادة إرسال)\n"
        f"4. اختر هذا البوت كوجهة الإرسال",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown'
    )

# معالجة المنشورات الموجهة
@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice'])
def handle_forwarded_message(message):
    user_id = message.from_user.id
    
    # التحقق إذا كان المستخدم ينتظر توجيه منشور
    channel_id = controller.get_waiting_channel(user_id)
    if not channel_id:
        return
    
    # التحقق إذا كانت الرسالة موجهة من قناة
    if not message.forward_from_chat:
        bot.reply_to(message, "❌ **يجب توجيه منشور من قناة وليس من مستخدم.**")
        controller.clear_waiting(user_id)
        return
    
    forwarded_channel_id = str(message.forward_from_chat.id)
    forwarded_message_id = message.forward_from_message_id
    
    # التحقق إذا كانت القناة الموجه منها هي نفس القناة المختارة
    if forwarded_channel_id != channel_id:
        bot.reply_to(message, f"❌ **هذا المنشور ليس من القناة المختارة.**\n"
                             f"**القناة المختارة:** `{channel_id}`\n"
                             f"**قناة المنشور:** `{forwarded_channel_id}`")
        controller.clear_waiting(user_id)
        return
    
    # إرسال رسالة بدء التفاعل
    start_msg = bot.send_message(
        message.chat.id,
        "🔄 **جاري التفاعل مع المنشور بواسطة جميع البوتات...**"
    )
    
    # تشغيل التفاعل في thread واحد
    if not controller.start_interaction_thread(
        run_interaction, 
        (channel_id, forwarded_message_id, user_id, start_msg.message_id)
    ):
        bot.edit_message_text(
            "⏳ **يوجد عملية تفاعل قيد التنفيذ حالياً. يرجى الانتظار...**",
            user_id,
            start_msg.message_id
        )

def run_interaction(channel_id, message_id, user_id, original_message_id):
    """تشغيل عملية التفاعل في thread منفصل"""
    try:
        result = manual_interaction.interact_with_forwarded_post(
            channel_id, message_id, user_id, original_message_id
        )
        
    except Exception as e:
        error_message = f"❌ **حدث خطأ أثناء التفاعل:** {str(e)}"
        try:
            bot.edit_message_text(
                error_message,
                user_id,
                original_message_id,
                parse_mode='Markdown'
            )
        except:
            pass
    
    finally:
        controller.clear_waiting(user_id)

# التفاعل الفوري
@bot.callback_query_handler(func=lambda call: call.data == "instant_interact")
def instant_interact(call):
    cursor = db.conn.cursor()
    cursor.execute('SELECT channel_id, channel_username FROM channels')
    channels = cursor.fetchall()
    
    if not channels:
        bot.answer_callback_query(call.id, "❌ لا توجد قنوات مضافة.")
        return
    
    keyboard = InlineKeyboardMarkup()
    for channel in channels:
        channel_id, username = channel
        name = f"@{username}" if username else f"ID: {channel_id}"
        keyboard.add(InlineKeyboardButton(name, callback_data=f"instant_channel_{channel_id}"))
    
    keyboard.add(InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
    
    bot.edit_message_text(
        "⚡ **اختر القناة للتفاعل الفوري:**",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("instant_channel_"))
def instant_interact_channel(call):
    channel_id = call.data.replace("instant_channel_", "")
    
    bot.edit_message_text(
        f"⚡ **جاري التفاعل الفوري مع آخر منشور في القناة:** `{channel_id}`",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown'
    )
    
    # هنا يمكن إضافة نظام التفاعل الفوري مع آخر منشور
    bot.answer_callback_query(call.id, "🔄 جاري التفاعل الفوري...")

# الإحصائيات
@bot.callback_query_handler(func=lambda call: call.data == "stats")
def show_stats(call):
    cursor = db.conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM channels')
    channels_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM bots WHERE is_active = 1')
    active_bots = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM bots')
    total_bots = cursor.fetchone()[0]
    
    stats_text = f"""
📊 **إحصائيات البوت:**

📺 **عدد القنوات:** {channels_count}
🤖 **البوتات النشطة:** {active_bots}
🤖 **إجمالي البوتات:** {total_bots}
⏰ **آخر تحديث:** {datetime.now().strftime('%H:%M:%S')}
    """
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔄 تحديث", callback_data="stats"))
    keyboard.add(InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
    
    bot.edit_message_text(
        stats_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

# الرجوع للقائمة الرئيسية
@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main(call):
    show_admin_panel(call.message)

# معالجة جميع الرسائل الأخرى
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    if message.text and message.text.startswith('/'):
        bot.reply_to(message, "⚠️ **الأمر غير معروف. استخدم** /start **للبدء.**", parse_mode='Markdown')

# تشغيل البوت
if __name__ == "__main__":
    print("🤖 Bot is running with SINGLE THREAD system...")
    print("📨 Users can forward posts for interaction")
    print("🔄 Using edit_message_text to reduce messages")
    
    while True:
        try:
            bot.infinity_polling(timeout=30,long_polling_timeout=20,skip_pending=True)
        except Exception as e:
            print(f"🔴 Polling error: {e}")
            print("🔄 Restarting bot in 5 seconds...")
            time.sleep(5)