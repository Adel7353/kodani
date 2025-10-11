from flask import Flask, jsonify, request
from pymongo import MongoClient
import os

app = Flask(__name__)

# 🔒 قراءة رابط قاعدة البيانات من متغير البيئة (Environment Variable)
MONGO_URI = os.environ.get("MONGO_URI")

if not MONGO_URI:
    raise ValueError("❌ MONGO_URI not found in environment variables")

# إنشاء الاتصال بقاعدة البيانات
client = MongoClient(MONGO_URI)
db = client["myDB"]
collection = db["users"]

# ✅ مسار لجلب جميع المستخدمين
@app.route("/api/get_users", methods=["GET"])
def get_users():
    data = list(collection.find({}, {"_id": 0}))
    return jsonify(data)

# ✅ مسار لإضافة مستخدم جديد
@app.route("/api/add_user", methods=["POST"])
def add_user():
    data = request.get_json(force=True)
    name = data.get("name")
    amount = data.get("amount")
    date = data.get("date")

    if not name or amount is None or not date:
        return jsonify({"error": "name, amount, and date are required"}), 400

    collection.insert_one({
        "name": name,
        "amount": amount,
        "date": date
    })

    return jsonify({"message": "User added successfully"}), 200


# ⚙️ مطلوب فقط للتجريب المحلي (Vercel يتجاهله)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
    print("runing")
