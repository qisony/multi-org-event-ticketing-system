# bot.py
import asyncio
import os
import logging
import sys
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
# Импорт ваших модулей. Используем try/except для заглушек
# (как в вашем коде, чтобы не падало, если модули не найдены)
try:
    from db_utils import create_tables
    from user_handlers import buy_handler, issue_ticket_from_admin_notification
    from admin_handlers import admin_handler, stop_bot_handler
    from utils import cancel_global
except ImportError as e:
    # Заглушки для вашего кода:
    logger.warning(f"Ошибка импорта локальных модулей: {e}. Используем заглушки.")
    def create_tables(): pass
    def buy_handler(): pass
    def admin_handler(): pass
    def stop_bot_handler(): pass
    def issue_ticket_from_admin_notification(): pass
    def cancel_global(): pass

# --- Настройка логирования ---
LOG_FILE_NAME = "bot.log"
# Очистка логов при перезапуске (оставляем, как у вас)
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

# Загрузка переменных окружения и токена
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")


# --- ГЛАВНАЯ АСИНХРОННАЯ ФУНКЦИЯ ДЛЯ WEBHOOK ---
async def main_async():
    """
    Настраивает и запускает Telegram-бота через Webhook на Render
    в рамках единого цикла событий.
    """
    logger.info("Вход в main_async для инициализации бота.") 
    
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN не найден. Проверьте переменные окружения на Render.")
        return # Выход, если токен пуст.

    logger.info("Токен успешно загружен. Создание Application.") 
    app = Application.builder().token(TOKEN).build()

    # --- ДОБАВЛЕНИЕ ВСЕХ HANDLER'ОВ ---
    app.add_handler(buy_handler)
    app.add_handler(admin_handler)
    app.add_handler(CommandHandler("stop_bot", stop_bot_handler))

    app.add_handler(CallbackQueryHandler(
        issue_ticket_from_admin_notification,
        pattern=r'^(adm_approve_|adm_reject_)[a-fA-F0-9]+$'
    ))
    app.add_handler(CommandHandler("cancel", cancel_global))
    # ---------------------------------

    # Настройка Webhook-параметров
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
    PORT = int(os.environ.get("PORT", 10000))
    WEBHOOK_PATH = "webhook"

    if not RENDER_URL:
        # Если RENDER_EXTERNAL_URL не установлен (локально), запускаем Polling
        logger.error("Переменная RENDER_EXTERNAL_URL не установлена. Запуск через Polling (для локальной отладки).")
        await app.run_polling(drop_pending_updates=True)
        return

    # 1. Установка Webhook (Требует await)
    logger.info(f"Установка Webhook URL: {RENDER_URL}/{WEBHOOK_PATH} на порт {PORT}")
    try:
        await app.bot.set_webhook(
            url=f"{RENDER_URL}/{WEBHOOK_PATH}"
        )
    except Exception as e:
        logger.critical(f"Не удалось установить Webhook: {e}")
        return

    # 2. Запуск Webhook-сервера (Требует await и БЛОКИРУЕТ выполнение)
    logger.info("Запуск Webhook-сервера. Бот теперь активен!")
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
    )


# --- СИНХРОННАЯ ТОЧКА ВХОДА ---
if __name__ == '__main__':
    logger.info("Bot execution started...")
    
    # 1. СИНХРОННЫЕ ОПЕРАЦИИ (создание таблиц)
    try:
        create_tables() 
    except Exception as e:
        logger.critical(f"Ошибка синхронной инициализации (DB): {e}")
        # sys.exit(1)
        
    # 2. АСИНХРОННАЯ ОПЕРАЦИЯ (запуск бота)
    try:
        # Запускаем главную асинхронную функцию
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")
    except Exception as e:
        logger.critical(f"Критическая ошибка запуска приложения: {e}")
