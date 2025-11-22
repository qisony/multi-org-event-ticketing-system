# bot.py (ИСПРАВЛЕННЫЙ)
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
# ... (логирование остается прежним)
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

# --- ГЛАВНАЯ АСИНХРОННАЯ ФУНКЦИЯ ---
async def run_bot_async():
    """
    Создает, настраивает и запускает бот в асинхронном режиме.
    """
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN не найден.")
        return

    # 1. Синхронная часть: Настройка БД
    create_tables()

    # 2. Настройка приложения
    app = Application.builder().token(TOKEN).build()

    # Хендлеры (Остаются прежними)
    app.add_handler(buy_handler)
    app.add_handler(admin_handler)
    app.add_handler(CommandHandler("stop_bot", stop_bot_handler))

    # Глобальный callback для админов 
    app.add_handler(CallbackQueryHandler(
        issue_ticket_from_admin_notification,
        pattern=r'^(adm_approve_|adm_reject_)[a-fA-F0-9]+$'
    ))

    app.add_handler(CommandHandler("cancel", cancel_global))

    logger.info("Bot started...")

    # 3. Асинхронная часть: Настройка и запуск Webhook
    # Render автоматически предоставляет эти переменные окружения
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
    WEBHOOK_PATH = "webhook"
    PORT = int(os.environ.get("PORT", 10000))
    
    # 3.1. Установите Webhook URL на серверах Telegram
    if RENDER_URL:
        full_webhook_url = f"{RENDER_URL}/{WEBHOOK_PATH}"
        logger.info(f"Setting Webhook URL: {full_webhook_url} on port {PORT}")
        await app.bot.set_webhook(url=full_webhook_url)

        # 3.2. Запустите Webhook-сервер (блокирует выполнение, пока сервер активен)
        logger.info("Launching Webhook server. Bot is now active!")
        await app.run_webhook(
            listen="0.0.0.0",
            port=PORT, 
            url_path=WEBHOOK_PATH
        )
    else:
        logger.critical("RENDER_EXTERNAL_URL не найден. Убедитесь, что вы развертываете на Render Web Service.")


# --- ТОЧКА ВХОДА (ОДИН ВЫЗОВ asyncio.run) ---
if __name__ == '__main__':
    try:
        asyncio.run(run_bot_async())
    except Exception as e:
        logger.error(f"Fatal error during bot execution: {e}")
        # Это не должно случиться с исправленным кодом, 
        # но обеспечивает чистое завершение в случае неожиданного сбоя.
