# api/webhook.py

import os
import logging
from fastapi import FastAPI, Request

# Убедитесь, что bot.py, db_utils.py и т.д. находятся на том же уровне
# или доступны для импорта (в Vercel все файлы в корне проекта)
try:
    from bot import setup_application
    from db_utils import create_tables
except ImportError:
    # Для локального тестирования
    import sys

    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from bot import setup_application
    from db_utils import create_tables

# --- Инициализация ---

# Токен берется из переменной окружения Vercel
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logging.critical("TELEGRAM_TOKEN не найден в окружении Vercel.")

# Инициализируем приложение Telegram
app_telegram = setup_application(TELEGRAM_TOKEN)
app_telegram.set_sync_processing(False)  # Асинхронная обработка

# Инициализация FastAPI
app = FastAPI()

# Создаем таблицы при старте Vercel (вызывается 1 раз при холодном старте)
create_tables()
logging.info("База данных инициализирована.")


# --- Обработчик Webhook ---

@app.post("/")
async def telegram_webhook(request: Request):
    """Основная точка входа для Webhook Telegram."""
    try:
        # Получаем тело запроса
        update_json = await request.json()

        # Обрабатываем обновление с помощью Application
        await app_telegram.process_update(update_json)

        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Ошибка обработки Webhook: {e}")
        return {"status": "error", "message": str(e)}, 500