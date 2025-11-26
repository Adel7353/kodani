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
            (channel_id, channel_username or "", channel_title)
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
        
        if total_bots == 0:
            bot.edit_message_text(
                "❌ **لا توجد بوتات نشطة في هذه القناة.**",
                user_id,
                original_message_id
            )
            return {"successful": [], "failed": [], "total_bots": 0}
        
        # تحديث الرسالة الأصلية لتظهر التقدم
        progress_message = self.create_progress_message(channel_id, message_id, 0, total_bots, successful_interactions, failed_interactions)
        try:
            bot.edit_message_text(
                progress_message,
                user_id,
                original_message_id
            )
        except:
            pass
        
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
                try:
                    bot.edit_message_text(
                        progress_message,
                        user_id,
                        original_message_id
                    )
                except:
                    pass
            
            # وقت انتظار بين التفاعلات
            time.sleep(random.uniform(2, 5))
        
        # إرسال التقرير النهائي
        final_report = self.create_final_report(channel_id, message_id, successful_interactions, failed_interactions, total_bots)
        try:
            bot.edit_message_text(
                final_report,
                user_id,
                original_message_id
            )
        except:
            pass
        
        return {
            "successful": successful_interactions,
            "failed": failed_interactions,
            "total_bots": total_bots
        }
    
    def create_progress_message(self, channel_id, message_id, progress, total, successful, failed):
        """إنشاء رسالة تقدم"""
        percentage = (progress / total) * 100 if total > 0 else 0
        
        progress_bar = "🟢" * int(percentage / 10) + "⚪" * (10 - int(percentage / 10))
        
        return f"""🔄 جاري التفاعل مع المنشور...

🏷 القناة: {channel_id}
📝 المنشور: {message_id}

📊 التقدم: {progress}/{total} ({percentage:.1f}%)
{progress_bar}

✅ ناجحة: {len(successful)}
❌ فاشلة: {len(failed)}

⏰ الوقت: {datetime.now().strftime('%H:%M:%S')}"""
    
    def create_final_report(self, channel_id, message_id, successful, failed, total_bots):
        """إنشاء التقرير النهائي"""
        success_rate = (len(successful)/total_bots*100) if total_bots > 0 else 0
        
        report_message = f"""✅ تم الانتهاء من التفاعل!

🏷 القناة: {channel_id}
📝 المنشور: {message_id}

📊 النتائج النهائية:
• 🤖 إجمالي البوتات: {total_bots}
• ✅ ناجحة: {len(successful)}
• ❌ فاشلة: {len(failed)}
• 📈 نسبة النجاح: {success_rate:.1f}%"""
        
        if successful:
            report_message += f"\n\n🤖 البوتات الناجحة:\n" + "\n".join(['• ' + bot for bot in successful])
        
        if failed:
            report_message += f"\n\n🔧 البوتات الفاشلة:\n" + "\n".join(['• ' + bot for bot in failed])
        
        report_message += f"\n\n⏰ وقت الانتهاء: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
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
        subscription_message = "📢 يجب الاشتراك في القنوات التالية لاستخدام البوت:\n\n"
        
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
            reply_markup=keyboard
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
        "🛠 لوحة التحكم الإدارية\n\nاختر الإعداد الذي تريد تعديله:",
        reply_markup=keyboard
    )

# نظام إدارة القنوات - مصحح
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
        "📺 إدارة القنوات\n\nاختر الإجراء المطلوب:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data == "add_channel")
def add_channel_step1(call):
    msg = bot.send_message(
        call.message.chat.id,
        "📝 أرسل معرف القناة:\n\nمثال: @channel_username أو -1001234567890"
    )
    bot.register_next_step_handler(msg, add_channel_step2)

def add_channel_step2(message):
    try:
        channel_input = message.text.strip()
        
        # محاولة الحصول على معلومات القناة
        try:
            chat = bot.get_chat(channel_input)
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ لا يمكن الوصول إلى القناة: {str(e)}")
            return
        
        # تنظيف البيانات
        channel_id = str(chat.id)
        channel_username = getattr(chat, 'username', '')
        channel_title = getattr(chat, 'title', 'Unknown Channel')
        
        # إدخال في قاعدة البيانات
        cursor = db.conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO channels (channel_id, channel_username, channel_title, owner_id) VALUES (?, ?, ?, ?)',
            (channel_id, channel_username, channel_title, message.from_user.id)
        )
        db.conn.commit()
        
        bot.send_message(message.chat.id, f"✅ تمت إضافة القناة: {channel_title}")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ فشل في إضافة القناة: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "list_channels")
def list_channels(call):
    cursor = db.conn.cursor()
    cursor.execute('SELECT channel_id, channel_username, channel_title FROM channels')
    channels = cursor.fetchall()
    
    if not channels:
        bot.edit_message_text(
            "❌ لا توجد قنوات مضافة.",
            call.message.chat.id,
            call.message.message_id
        )
        return
    
    channels_text = "📺 قائمة القنوات:\n\n"
    
    for index, channel in enumerate(channels, 1):
        channel_id, channel_username, channel_title = channel
        username_display = f"@{channel_username}" if channel_username else "لا يوجد معرف"
        channels_text += f"{index}. {channel_title}\n"
        channels_text += f"   🆔: {channel_id}\n"
        channels_text += f"   👤: {username_display}\n\n"
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔙 رجوع", callback_data="manage_channels"))
    
    bot.edit_message_text(
        channels_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )

# باقي الكود يبقى كما هو مع إزالة parse_mode='Markdown' من جميع الرسائل
# ... [الكود المتبقي بدون تغيير]

# معالجة المنشورات الموجهة - مصحح
@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice'])
def handle_forwarded_message(message):
    user_id = message.from_user.id
    
    # التحقق إذا كان المستخدم ينتظر توجيه منشور
    channel_id = controller.get_waiting_channel(user_id)
    if not channel_id:
        return
    
    # التحقق إذا كانت الرسالة موجهة من قناة
    if not message.forward_from_chat:
        bot.reply_to(message, "❌ يجب توجيه منشور من قناة وليس من مستخدم.")
        controller.clear_waiting(user_id)
        return
    
    # التحقق من وجود معرف الرسالة
    if not hasattr(message, 'forward_from_message_id') or not message.forward_from_message_id:
        bot.reply_to(message, "❌ لا يمكن الحصول على معرف المنشور. حاول توجيه منشور آخر.")
        controller.clear_waiting(user_id)
        return
    
    forwarded_channel_id = str(message.forward_from_chat.id)
    forwarded_message_id = message.forward_from_message_id
    
    # التحقق إذا كانت القناة الموجه منها هي نفس القناة المختارة
    if forwarded_channel_id != channel_id:
        bot.reply_to(message, f"❌ هذا المنشور ليس من القناة المختارة.\nالقناة المختارة: {channel_id}\nقناة المنشور: {forwarded_channel_id}")
        controller.clear_waiting(user_id)
        return
    
    # إرسال رسالة بدء التفاعل
    start_msg = bot.send_message(
        message.chat.id,
        "🔄 جاري التفاعل مع المنشور بواسطة جميع البوتات..."
    )
    
    # تشغيل التفاعل في thread واحد
    if not controller.start_interaction_thread(
        run_interaction, 
        (channel_id, forwarded_message_id, user_id, start_msg.message_id)
    ):
        bot.edit_message_text(
            "⏳ يوجد عملية تفاعل قيد التنفيذ حالياً. يرجى الانتظار...",
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
        error_message = f"❌ حدث خطأ أثناء التفاعل: {str(e)}"
        try:
            bot.edit_message_text(
                error_message,
                user_id,
                original_message_id
            )
        except:
            pass
    
    finally:
        controller.clear_waiting(user_id)

if __name__ == "__main__":
    print("🤖 Bot is starting with conflict prevention...")
    
    # تنظيف أي عمليات سابقة
    try:
        bot.stop_polling()
    except:
        pass
    
    # انتظار لتفادي التعارض
    print("⏳ Waiting 10 seconds to avoid conflicts...")
    time.sleep(10)
    
    # إعدادات خاصة للاستضافة السحابية
    import os
    
    # استخدام skip_pending لتخطي التحديثات القديمة
    while True:
        try:
            print("🔄 Starting bot polling with skip_pending...")
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=30,
                skip_pending=True,  # تخطي التحديثات القديمة
                allowed_updates=['message', 'callback_query']  # تحديثات محددة فقط
            )
        except Exception as e:
            print(f"🔴 Polling error: {e}")
            print("🔄 Restarting in 15 seconds...")
            time.sleep(15)
