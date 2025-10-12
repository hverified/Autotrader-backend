# app/database.py
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

client = AsyncIOMotorClient(settings.MONGO_URI)
db = client[settings.MONGO_DB]
trades_collection = db[settings.MONGO_COLLECTION]
users_collection = db["users"]


async def init_db():
    """Initialize database indexes"""
    await users_collection.create_index("email", unique=True)
    await users_collection.create_index("username", unique=True)
    await users_collection.create_index("created_at")

    print("✅ Database indexes created successfully")
