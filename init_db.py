import asyncio
from database import init_db

if __name__ == "__main__":
    asyncio.run(init_db())
    print("✅ База данных инициализирована")
