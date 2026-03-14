import os
from dotenv import load_dotenv
from pathlib import Path

# Загружаем .env
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

# Получаем переменные
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID_STR = os.getenv("GROUP_ID")
ADMIN_ID_STR = os.getenv("ADMIN_ID")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///montazh_bot.db")
GEOCODER_API_KEY = os.getenv("GEOCODER_API_KEY")

# Список районов
DISTRICTS = [
    "Советский",
    "Железнодорожный", 
    "Октябрьский",
    "Иволгинский",
    "Тарбагатайский",
    "Заиграевский"
]

# Проверяем и преобразуем
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env файле!")

if not GROUP_ID_STR:
    raise ValueError("❌ GROUP_ID не найден в .env файле!")

if not ADMIN_ID_STR:
    raise ValueError("❌ ADMIN_ID не найден в .env файле!")

try:
    GROUP_ID = int(GROUP_ID_STR)
    ADMIN_ID = int(ADMIN_ID_STR)
except ValueError as e:
    raise ValueError(f"❌ Ошибка преобразования ID: {e}")

print("✅ Конфигурация загружена успешно!")