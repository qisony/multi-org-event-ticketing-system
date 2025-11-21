# bot.py
import asyncio
import os
import logging
import sys
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from db_utils import create_tables, add_bank_card_column, migrate_refund_system
from user_handlers import buy_handler, issue_ticket_from_admin_notification
from admin_handlers import admin_handler, stop_bot_handler
from utils import cancel_global

# --- Настройка логирования ---
LOG_FILE_NAME = "bot.log"

# Очистка логов при перезапуске
if os.path.exists(LOG_FILE_NAME):
    try:
        with open(LOG_FILE_NAME, 'w', encoding='utf-8') as f:
            f.truncate(0)
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE_NAME, mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
# Используем заглушки для импортов, чтобы код был запускаемым
# В реальном коде вам нужно убедиться, что они импортируются корректно
try:
    from db_utils import create_tables
    from user_handlers import buy_handler, issue_ticket_from_admin_notification
    from admin_handlers import admin_handler, stop_bot_handler
    from utils import cancel_global
except ImportError as e:
    logger.warning(f"Ошибка импорта локальных модулей (это нормально, если вы просто тестируете): {e}")
    # Используем заглушки, чтобы код не падал, но в вашем случае они должны быть реальными
    def create_tables(): pass
    def buy_handler(): pass
    def admin_handler(): pass
    def stop_bot_handler(): pass
    def issue_ticket_from_admin_notification(): pass
    def cancel_global(): pass


# ... (начало файла bot.py)

# --- АСИНХРОННАЯ ФУНКЦИЯ ДЛЯ УСТАНОВКИ WEBHOOK ---
async def set_webhook_only(app: Application):
    """
    Выполняет только асинхронный вызов set_webhook.
    """
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
    WEBHOOK_PATH = "webhook" 
    
    if not RENDER_URL:
        logger.error("Переменная RENDER_EXTERNAL_URL не установлена.")
        return

    logger.info(f"Установка Webhook URL: {RENDER_URL}/{WEBHOOK_PATH}")
    await app.bot.set_webhook(
        url=f"{RENDER_URL}/{WEBHOOK_PATH}"
    )

# --- ГЛАВНАЯ СИНХРОННАЯ ТОЧКА ВХОДА ---
def main():
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN не найден.")
        return

    # 1. СИНХРОННЫЕ ДЕЙСТВИЯ (создание таблиц)
    create_tables()

    app = Application.builder().token(TOKEN).build()

    # --- Добавление Handler'ов (то же самое) ---
    app.add_handler(buy_handler)
    app.add_handler(admin_handler)
    # ... (другие хендлеры)
    # ------------------------------------

    # 2. АСИНХРОННОЕ ДЕЙСТВИЕ (установка Webhook)
    try:
        # Используем asyncio.run() только для ОДНОГО асинхронного вызова set_webhook
        asyncio.run(set_webhook_only(app))
        logger.info("Webhook успешно установлен.")
    except Exception as e:
        logger.critical(f"Критическая ошибка при установке Webhook: {e}")
        return

    # 3. ЗАПУСК WEBHOOK-СЕРВЕРА (СИНХРОННЫЙ, блокирующий вызов)
    PORT = int(os.environ.get("PORT", 10000))
    WEBHOOK_PATH = "webhook"

    logger.info(f"Запуск Webhook-сервера на порту {PORT}...")
    try:
        # run_webhook должен быть вызван синхронно в главном потоке, 
        # чтобы он начал блокировать выполнение и принимать HTTP-запросы.
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            # drop_pending_updates=True # опционально
        )
    except Exception as e:
        logger.critical(f"Критическая ошибка запуска Webhook-сервера: {e}")


if __name__ == '__main__':
    logger.info("Bot execution started...")
    main()
