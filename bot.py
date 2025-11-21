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


# --- АСИНХРОННАЯ ГЛАВНАЯ ФУНКЦИЯ ДЛЯ WEBHOOK ---
async def main_async():
    """
    Настраивает и запускает Telegram-бота через Webhook на Render.
    """
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN не найден. Проверьте переменные окружения.")
        return

    # Запуск синхронных задач (создание таблиц)
    create_tables()

    app = Application.builder().token(TOKEN).build()

    # --- Добавление Handler'ов ---
    app.add_handler(buy_handler)
    app.add_handler(admin_handler)
    app.add_handler(CommandHandler("stop_bot", stop_bot_handler))

    app.add_handler(CallbackQueryHandler(
        issue_ticket_from_admin_notification,
        pattern=r'^(adm_approve_|adm_reject_)[a-fA-F0-9]+$'
    ))
    app.add_handler(CommandHandler("cancel", cancel_global))
    # -----------------------------

    # Настройка Webhook
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
    PORT = int(os.environ.get("PORT", 10000))
    WEBHOOK_PATH = "webhook" # Используем простой и понятный путь

    if not RENDER_URL:
        # Если RENDER_EXTERNAL_URL не установлен (например, локальный запуск без него), 
        # лучше вернуться к Polling или вывести ошибку.
        logger.error("Переменная RENDER_EXTERNAL_URL не установлена. Запуск через Polling (для локальной отладки).")
        await app.run_polling(drop_pending_updates=True)
        return

    # 1. Установите Webhook на серверах Telegram (Требует await)
    logger.info(f"Установка Webhook URL: {RENDER_URL}/{WEBHOOK_PATH} на порт {PORT}")
    try:
        await app.bot.set_webhook(
            url=f"{RENDER_URL}/{WEBHOOK_PATH}"
        )
    except Exception as e:
        logger.critical(f"Не удалось установить Webhook: {e}")
        return

    # 2. Запустите Webhook-сервер (Требует await)
    logger.info("Запуск Webhook-сервера...")
    # listen="0.0.0.0" позволяет слушать все внешние IP-адреса, что нужно на Render
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
    )


# --- СИНХРОННАЯ ТОЧКА ВХОДА ---
if __name__ == '__main__':
    logger.info("Bot execution started...")
    
    # Запускаем главную асинхронную функцию
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную (KeyboardInterrupt).")
    except Exception as e:
        logger.critical(f"Критическая ошибка запуска приложения: {e}")
