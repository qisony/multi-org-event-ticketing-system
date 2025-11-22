# bot.py
import asyncio
import os
import logging
import sys
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from db_utils import create_tables # Предполагается, что эти модули существуют
from user_handlers import buy_handler, issue_ticket_from_admin_notification
from admin_handlers import admin_handler, stop_bot_handler
from utils import cancel_global

# --- Настройка логирования ---
LOG_FILE_NAME = "bot.log"

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


async def start_bot():
    """
    Основная асинхронная функция для настройки и запуска Webhook.
    Вся асинхронная логика должна быть здесь.
    """
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN не найден.")
        return

    # 1. Синхронная инициализация БД
    create_tables()
    logger.info("DB Structure initialized/updated successfully.")

    # 2. Создание приложения
    app = Application.builder().token(TOKEN).build()

    # 3. Добавление хендлеров
    app.add_handler(buy_handler)
    app.add_handler(admin_handler)
    app.add_handler(CommandHandler("stop_bot", stop_bot_handler))

    app.add_handler(CallbackQueryHandler(
        issue_ticket_from_admin_notification,
        pattern=r'^(adm_approve_|adm_reject_)[a-fA-F0-9]+$'
    ))
    app.add_handler(CommandHandler("cancel", cancel_global))
    
    # 4. Настройка и запуск Webhook (всё асинхронно с await)
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
    WEBHOOK_PATH = "webhook"
    PORT = int(os.environ.get("PORT", 10000))

    if RENDER_URL:
        full_webhook_url = f"{RENDER_URL}/{WEBHOOK_PATH}"
        
        logger.info("Bot started...")
        logger.info(f"Setting Webhook URL: {full_webhook_url} on port {PORT}")
        
        # Устанавливаем Webhook, используя **await**
        await app.bot.set_webhook(url=full_webhook_url)

        # Запускаем Webhook-сервер, используя **await**. Это блокирует выполнение
        # до тех пор, пока сервер не будет остановлен (но он должен работать постоянно).
        logger.info("Launching Webhook server. Bot is now active!")
        await app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
        )
    else:
        logger.critical("RENDER_EXTERNAL_URL не найден. Невозможно запустить Webhook-сервис.")


if __name__ == '__main__':
    # ОДИН ЕДИНСТВЕННЫЙ ВЫЗОВ asyncio.run() для запуска асинхронной функции
    try:
        asyncio.run(start_bot())
    except Exception as e:
        logger.error(f"Fatal error during bot execution: {e}")
