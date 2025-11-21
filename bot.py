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

async def main_async():
    logger.info("Вход в main_async для инициализации бота.")
    """
    Настраивает и запускает Telegram-бота через Webhook на Render
    в рамках единого цикла событий.
    """
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN не найден. Проверьте переменные окружения.")
        return

    # Синхронные операции, которые могут быть здесь (например, миграции, 
    # если они не используют тяжелые блокирующие IO, или лучше вынести их ДО main_async)
    # create_tables()  <-- Внимание! Лучше вызвать это в синхронном main()

    app = Application.builder().token(TOKEN).build()


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

    # Настройка Webhook
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
    PORT = int(os.environ.get("PORT", 10000))
    WEBHOOK_PATH = "webhook"

    if not RENDER_URL:
        logger.error("Переменная RENDER_EXTERNAL_URL не установлена. Запуск через Polling.")
        # Для локальной отладки, если нет URL
        await app.run_polling(drop_pending_updates=True)
        return

    # 1. Установка Webhook (await в рамках цикла)
    logger.info(f"Установка Webhook URL: {RENDER_URL}/{WEBHOOK_PATH} на порт {PORT}")
    await app.bot.set_webhook(
        url=f"{RENDER_URL}/{WEBHOOK_PATH}"
    )

    # 2. Запуск Webhook-сервера (await в рамках цикла, блокирует)
    logger.info("Запуск Webhook-сервера...")
    # Поскольку мы в async-функции, run_webhook должен быть вызван с await.
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
    )
    # Примечание: Эта строка кода не будет достигнута, пока Webhook-сервер работает.


# --- СИНХРОННАЯ ТОЧКА ВХОДА ---
if __name__ == '__main__':
    logger.info("Bot execution started...")
    
    # Вызываем синхронные операции перед входом в async-контекст
    try:
        # Ваш синхронный вызов здесь!
        create_tables() 
    except Exception as e:
        logger.critical(f"Ошибка синхронной инициализации (DB): {e}")
        # sys.exit(1) # Опционально, если вы хотите, чтобы приложение падало при ошибке DB
        
    # Запускаем всю асинхронную часть одним вызовом
    try:
        # ПРАВИЛЬНЫЙ ВЫЗОВ: запускаем асинхронную функцию main_async
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")
    except Exception as e:
        # Эта критическая ошибка может быть связана с Render, 
        # но теперь она должна быть корректно поймана.
        logger.critical(f"Критическая ошибка запуска приложения: {e}")



