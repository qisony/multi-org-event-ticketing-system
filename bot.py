# bot.py (ИСПРАВЛЕННЫЙ КОД)
import asyncio
import os
import logging
import sys
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from db_utils import create_tables #, add_bank_card_column, migrate_refund_system # Оставим только те, что используются
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

# Удаляем функцию set_up_webhook, ее логика переносится ниже.
# Удаляем синхронную функцию main(), ее логика также переносится.

# --- ЕДИНАЯ АСИНХРОННАЯ ТОЧКА ВХОДА ---
async def main_async():
    """
    Основная асинхронная функция для настройки и запуска бота.
    """
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN не найден.")
        return

    # 1. СИНХРОННАЯ ЧАСТЬ: Настройка БД
    create_tables()
    # add_bank_card_column() # Раскомментируйте, если нужно
    # migrate_refund_system() # Раскомментируйте, если нужно

    # 2. НАСТРОЙКА ПРИЛОЖЕНИЯ
    app = Application.builder().token(TOKEN).build()

    # Хендлеры (остаются прежними)
    app.add_handler(buy_handler)
    app.add_handler(admin_handler)
    app.add_handler(CommandHandler("stop_bot", stop_bot_handler))

    # Глобальный callback для админов (подтверждение оплаты)
    app.add_handler(CallbackQueryHandler(
        issue_ticket_from_admin_notification,
        pattern=r'^(adm_approve_|adm_reject_)[a-fA-F0-9]+$'
    ))

    app.add_handler(CommandHandler("cancel", cancel_global))

    logger.info("Bot started...")

    # 3. АСИНХРОННАЯ ЧАСТЬ: Настройка и запуск Webhook
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
    WEBHOOK_PATH = "webhook" # Используем простой путь
    PORT = int(os.environ.get("PORT", 10000)) # Порт, предоставленный Render

    if RENDER_URL:
        full_webhook_url = f"{RENDER_URL}/{WEBHOOK_PATH}"
        logger.info(f"Setting Webhook URL: {full_webhook_url} on port {PORT}")
        
        # Устанавливаем Webhook с использованием await (ВНУТРИ async функции)
        await app.bot.set_webhook(url=full_webhook_url)

        # Запускаем Webhook-сервер (ВНУТРИ async функции)
        logger.info("Launching Webhook server. Bot is now active!")
        
        # app.run_webhook — это awaitable функция
        await app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH
        )
    else:
        logger.critical("RENDER_EXTERNAL_URL не найден. Убедитесь, что вы развертываете на Render Web Service.")


if __name__ == '__main__':
    # ОДИН ЕДИНСТВЕННЫЙ ВЫЗОВ asyncio.run()
    try:
        asyncio.run(main_async())
    except Exception as e:
        logger.error(f"Fatal error during bot execution: {e}")
