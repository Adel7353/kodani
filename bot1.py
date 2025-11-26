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

DEVELOPER_ID = 1675396915

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
                channel_title TEXT,
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
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS forced_subscription (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT,
                channel_username TEXT,
                channel_title TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS welcome_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_text TEXT,
                is_active BOOLEAN DEFAULT 1,
                updated_by INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # إضافة رسالة ترحيب افتراضية
        cursor.execute('''
            INSERT OR IGNORE INTO welcome_messages (id, message_text, updated_by) 
            VALUES (1, 'مرحباً بك في البوت!', ?)
        ''', (DEVELOPER_ID,))
        
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

controller.add_admin(DEVELOPER_ID)

# نظام الاشتراك الإجباري
class ForcedSubscription:
    def __init__(self):
        self.subscription_channels = []
        self.load_subscription_channels()
    
    def load_subscription_channels(self):
        """تحميل قنوات الاشتراك الإجباري من قاعدة البيانات"""
        cursor = db.conn.cursor()
        cursor.execute('SELECT channel_id, channel_username, channel_title FROM forced_subscription WHERE is_active = 1')
        self.subscription_channels = cursor.fetchall()
    
    def add_subscription_channel(self, channel_id, channel_username, channel_title):
        """إضافة قناة للاشتراك الإجباري"""
        cursor = db.conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO forced_subscription (channel_id, channel_username, channel_title) VALUES (?, ?, ?)',
            (channel_id, channel_username, channel_title)
        )
        db.conn.commit()
        self.load_subscription_channels()
    
    def remove_subscription_channel(self, channel_id):
        """إزالة قناة من الاشتراك الإجباري"""
        cursor = db.conn.cursor()
        cursor.execute('DELETE FROM forced_subscription WHERE channel_id = ?', (channel_id,))
        db.conn.commit()
        self.load_subscription_channels()
    
    def check_user_subscription(self, user_id):
        """التحقق من اشتراك المستخدم في جميع القنوات"""
        if not self.subscription_channels:
            return True, []
        
        unsubscribed_channels = []
        
        for channel in self.subscription_channels:
            channel_id, channel_username, channel_title = channel
            try:
                chat_member = bot.get_chat_member(channel_id, user_id)
                if chat_member.status not in ['member', 'administrator', 'creator']:
                    unsubscribed_channels.append((channel_id, channel_username, channel_title))
            except Exception as e:
                print(f"Error checking subscription for channel {channel_id}: {e}")
                unsubscribed_channels.append((channel_id, channel_username, channel_title))
        
        return len(unsubscribed_channels) == 0, unsubscribed_channels

forced_subscription = ForcedSubscription()

# نظام رسائل الترحيب
class WelcomeMessages:
    def __init__(self):
        self.current_welcome_message = self.load_welcome_message()
    
    def load_welcome_message(self):
        """تحميل رسالة الترحيب من قاعدة البيانات"""
        cursor = db.conn.cursor()
        cursor.execute('SELECT message_text FROM welcome_messages WHERE is_active = 1 ORDER BY id DESC LIMIT 1')
        result = cursor.fetchone()
        return result[0] if result else "مرحباً بك في البوت!"
    
    def update_welcome_message(self, new_message, user_id):
        """تحديث رسالة الترحيب"""
        cursor = db.conn.cursor()
        cursor.execute(
            'UPDATE welcome_messages SET message_text = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1',
            (new_message, user_id)
        )
        db.conn.commit()
        self.current_welcome_message = new_message
        return True

welcome_messages = WelcomeMessages()

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
    
    # التحقق من الاشتراك الإجباري
    is_subscribed, unsubscribed_channels = forced_subscription.check_user_subscription(user_id)
    
    if not is_subscribed:
        # إرسال رسالة الاشتراك الإجباري
        subscription_message = "📢 **يجب الاشتراك في القنوات التالية لاستخدام البوت:**\n\n"
        
        keyboard = InlineKeyboardMarkup()
        
        for channel in unsubscribed_channels:
            channel_id, channel_username, channel_title = channel
            if channel_username:
                channel_url = f"https://t.me/{channel_username}"
                keyboard.add(InlineKeyboardButton(f"📺 {channel_title}", url=channel_url))
            else:
                # إذا لم يكن هناك معرف، نستخدم الرابط بالمعرف الرقمي
                channel_url = f"https://t.me/c/{channel_id.replace('-100', '')}"
                keyboard.add(InlineKeyboardButton(f"📺 {channel_title}", url=channel_url))
        
        keyboard.add(InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subscription"))
        
        bot.send_message(
            message.chat.id,
            subscription_message,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        return
    
    # إذا كان المستخدم مشترك في جميع القنوات
    if controller.is_admin(user_id):
        show_admin_panel(message)
    else:
        # إرسال رسالة الترحيب للمستخدمين العاديين
        welcome_text = welcome_messages.current_welcome_message
        bot.reply_to(message, welcome_text)

@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def check_subscription_callback(call):
    user_id = call.from_user.id
    is_subscribed, unsubscribed_channels = forced_subscription.check_user_subscription(user_id)
    
    if is_subscribed:
        bot.delete_message(call.message.chat.id, call.message.message_id)
        if controller.is_admin(user_id):
            show_admin_panel(call.message)
        else:
            welcome_text = welcome_messages.current_welcome_message
            bot.send_message(call.message.chat.id, welcome_text)
    else:
        bot.answer_callback_query(call.id, "❌ لم تشترك في جميع القنوات المطلوبة بعد!")

def show_admin_panel(message):
    keyboard = InlineKeyboardMarkup()
    
    buttons = [
        [InlineKeyboardButton("📊 إحصائيات", callback_data="stats")],
        [InlineKeyboardButton("📺 إدارة القنوات", callback_data="manage_channels")],
        [InlineKeyboardButton("🤖 إدارة البوتات", callback_data="manage_bots")],
        [InlineKeyboardButton("🔄 تفاعل يدوي", callback_data="manual_interact")],
        [InlineKeyboardButton("📢 الاشتراك الإجباري", callback_data="forced_subscription")],
        [InlineKeyboardButton("👋 رسالة الترحيب", callback_data="welcome_message")]
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
        parse_mode='HTML'
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
            'INSERT OR IGNORE INTO channels (channel_id, channel_username, channel_title, owner_id) VALUES (?, ?, ?, ?)',
            (str(chat.id), getattr(chat, 'username', None), chat.title, message.from_user.id)
        )
        db.conn.commit()
        
        bot.send_message(message.chat.id, f"✅ **تمت إضافة القناة:** {chat.title}")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ **فشل في إضافة القناة:** {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "list_channels")
def list_channels(call):
    cursor = db.conn.cursor()
    cursor.execute('SELECT channel_id, channel_username, channel_title FROM channels')
    channels = cursor.fetchall()
    
    if not channels:
        bot.edit_message_text(
            "❌ **لا توجد قنوات مضافة.**",
            call.message.chat.id,
            call.message.message_id
        )
        return
    
    channels_text = "📺 **قائمة القنوات:**\n\n"
    
    for index, channel in enumerate(channels, 1):
        channel_id, channel_username, channel_title = channel
        username_display = f"@{channel_username}" if channel_username else "لا يوجد معرف"
        channels_text += f"{index}. **{channel_title}**\n"
        channels_text += f"   🆔: `{channel_id}`\n"
        channels_text += f"   👤: {username_display}\n\n"
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔙 رجوع", callback_data="manage_channels"))
    
    bot.edit_message_text(
        channels_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

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
    cursor.execute('SELECT channel_id, channel_username, channel_title FROM channels')
    channels = cursor.fetchall()
    
    if not channels:
        bot.answer_callback_query(call.id, "❌ لا توجد قنوات مضافة. أضف قناة أولاً.")
        return
    
    keyboard = InlineKeyboardMarkup()
    for channel in channels:
        channel_id, username, title = channel
        name = f"{title} (@{username})" if username else f"{title} (ID: {channel_id})"
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

@bot.callback_query_handler(func=lambda call: call.data == "list_bots")
def list_bots(call):
    cursor = db.conn.cursor()
    cursor.execute('''
        SELECT b.bot_username, b.channel_id, b.is_active, c.channel_title 
        FROM bots b 
        LEFT JOIN channels c ON b.channel_id = c.channel_id
    ''')
    bots = cursor.fetchall()
    
    if not bots:
        bot.edit_message_text(
            "❌ **لا توجد بوتات مضافة.**",
            call.message.chat.id,
            call.message.message_id
        )
        return
    
    bots_text = "🤖 **قائمة البوتات:**\n\n"
    
    for index, bot_data in enumerate(bots, 1):
        bot_username, channel_id, is_active, channel_title = bot_data
        status = "🟢 نشط" if is_active else "🔴 غير نشط"
        bots_text += f"{index}. **@{bot_username}**\n"
        bots_text += f"   📺: {channel_title or channel_id}\n"
        bots_text += f"   🏷: `{channel_id}`\n"
        bots_text += f"   📊: {status}\n\n"
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔙 رجوع", callback_data="manage_bots"))
    
    bot.edit_message_text(
        bots_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

# نظام الاشتراك الإجباري
@bot.callback_query_handler(func=lambda call: call.data == "forced_subscription")
def manage_forced_subscription(call):
    keyboard = InlineKeyboardMarkup()
    
    buttons = [
        [InlineKeyboardButton("➕ إضافة قناة إجبارية", callback_data="add_forced_channel")],
        [InlineKeyboardButton("📋 قنوات الاشتراك", callback_data="list_forced_channels")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
    ]
    
    for row in buttons:
        keyboard.row(*row)
    
    bot.edit_message_text(
        "📢 **إدارة الاشتراك الإجباري**\n\nاختر الإجراء المطلوب:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data == "add_forced_channel")
def add_forced_channel_step1(call):
    msg = bot.send_message(
        call.message.chat.id,
        "📝 **أرسل معرف القناة للإشتراك الإجباري:**\n\nمثال: @channel_username أو -1001234567890",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, add_forced_channel_step2)

def add_forced_channel_step2(message):
    try:
        channel_id = message.text.strip()
        chat = bot.get_chat(channel_id)
        
        forced_subscription.add_subscription_channel(
            str(chat.id), 
            getattr(chat, 'username', None), 
            chat.title
        )
        
        bot.send_message(
            message.chat.id, 
            f"✅ **تمت إضافة القناة للإشتراك الإجباري:** {chat.title}"
        )
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ **فشل في إضافة القناة:** {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "list_forced_channels")
def list_forced_channels(call):
    channels = forced_subscription.subscription_channels
    
    if not channels:
        bot.edit_message_text(
            "❌ **لا توجد قنوات اشتراك إجباري.**",
            call.message.chat.id,
            call.message.message_id
        )
        return
    
    channels_text = "📢 **قنوات الاشتراك الإجباري:**\n\n"
    
    for index, channel in enumerate(channels, 1):
        channel_id, channel_username, channel_title = channel
        username_display = f"@{channel_username}" if channel_username else "لا يوجد معرف"
        channels_text += f"{index}. **{channel_title}**\n"
        channels_text += f"   🆔: `{channel_id}`\n"
        channels_text += f"   👤: {username_display}\n\n"
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔙 رجوع", callback_data="forced_subscription"))
    
    bot.edit_message_text(
        channels_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

# نظام رسائل الترحيب
@bot.callback_query_handler(func=lambda call: call.data == "welcome_message")
def manage_welcome_message(call):
    keyboard = InlineKeyboardMarkup()
    
    buttons = [
        [InlineKeyboardButton("✏️ تعديل رسالة الترحيب", callback_data="edit_welcome_message")],
        [InlineKeyboardButton("👀 عرض رسالة الترحيب", callback_data="view_welcome_message")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
    ]
    
    for row in buttons:
        keyboard.row(*row)
    
    bot.edit_message_text(
        "👋 **إدارة رسالة الترحيب**\n\nاختر الإجراء المطلوب:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data == "edit_welcome_message")
def edit_welcome_message_step1(call):
    msg = bot.send_message(
        call.message.chat.id,
        "📝 **أرسل رسالة الترحيب الجديدة:**\n\nيمكنك استخدام Markdown للتنسيق.",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, edit_welcome_message_step2)

def edit_welcome_message_step2(message):
    try:
        new_welcome_message = message.text
        success = welcome_messages.update_welcome_message(new_welcome_message, message.from_user.id)
        
        if success:
            bot.send_message(
                message.chat.id,
                "✅ **تم تحديث رسالة الترحيب بنجاح!**\n\n"
                f"📝 **الرسالة الجديدة:**\n{new_welcome_message}"
            )
        else:
            bot.send_message(message.chat.id, "❌ **فشل في تحديث رسالة الترحيب.**")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ **حدث خطأ:** {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "view_welcome_message")
def view_welcome_message(call):
    welcome_text = welcome_messages.current_welcome_message
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("✏️ تعديل", callback_data="edit_welcome_message"))
    keyboard.add(InlineKeyboardButton("🔙 رجوع", callback_data="welcome_message"))
    
    bot.edit_message_text(
        f"👋 **رسالة الترحيب الحالية:**\n\n{welcome_text}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

# التفاعل اليدوي
@bot.callback_query_handler(func=lambda call: call.data == "manual_interact")
def manual_interact(call):
    cursor = db.conn.cursor()
    cursor.execute('SELECT channel_id, channel_username, channel_title FROM channels')
    channels = cursor.fetchall()
    
    if not channels:
        bot.answer_callback_query(call.id, "❌ لا توجد قنوات مضافة. أضف قناة أولاً.")
        return
    
    keyboard = InlineKeyboardMarkup()
    for channel in channels:
        channel_id, username, title = channel
        name = f"{title} (@{username})" if username else f"{title} (ID: {channel_id})"
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
    
    cursor.execute('SELECT COUNT(*) FROM forced_subscription WHERE is_active = 1')
    forced_channels_count = cursor.fetchone()[0]
    
    stats_text = f"""
📊 **إحصائيات البوت:**

📺 **عدد القنوات:** {channels_count}
🤖 **البوتات النشطة:** {active_bots}
🤖 **إجمالي البوتات:** {total_bots}
📢 **قنوات الاشتراك الإجباري:** {forced_channels_count}
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
    print("📢 Forced subscription system activated")
    print("👋 Welcome message system activated")
    
    while True:
        try:
            bot.infinity_polling(timeout=30,long_polling_timeout=20,skip_pending=True)
        except Exception as e:
            print(f"🔴 Polling error: {e}")
            print("🔄 Restarting bot in 5 seconds...")
            time.sleep(5)
