# bot.py

import os
import logging
import sys
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from db_utils import create_tables, add_bank_card_column, migrate_refund_system
from user_handlers import buy_handler, issue_ticket_from_admin_notification
from admin_handlers import admin_handler
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


def main():
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN не найден.")
        return

    create_tables()

    app = Application.builder().token(TOKEN).build()

    # Хендлеры
    app.add_handler(buy_handler)
    app.add_handler(admin_handler)

    # Глобальный callback для админов (подтверждение оплаты)
    app.add_handler(CallbackQueryHandler(
        issue_ticket_from_admin_notification,
        pattern=r'^(adm_approve_|adm_reject_)[a-fA-F0-9]+$'
    ))

    app.add_handler(CommandHandler("cancel", cancel_global))

    logger.info("Bot started...")
    app.run_polling()


if __name__ == '__main__':
    main()