from flask import Flask, jsonify, request
from pymongo import MongoClient
import os

app = Flask(__name__)

# 🔒 نقرأ مفتاح الاتصال من متغير بيئة (وليس مكتوب داخل الكود)
# MONGO_URI = os.environ.get("MONGO_URI")
MONGO_URI = "mongodb+srv://adel735377527_db_user:<db_password>@cluster0.9qxwu8d.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
# إنشاء الاتصال مع قاعدة البيانات
client = MongoClient(MONGO_URI)
db = client["myDB"]
collection = db["users"]

# 🔹 مثال: API لإرجاع جميع المستخدمين
@app.route("/get_users", methods=["GET"])
def get_users():
    data = list(collection.find({}, {"_id": 0}))  # لا نرجع الـ _id
    return jsonify(data)

# 🔹 مثال: API لإضافة مستخدم
@app.route("/add_user", methods=["POST"])
def add_user():
    name = request.json.get("name")
    age = request.json.get("age")
    if not name or not age:
        return jsonify({"error": "name and age required"}), 400
    collection.insert_one({"name": name, "age": age})
    return jsonify({"message": "user added successfully"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
