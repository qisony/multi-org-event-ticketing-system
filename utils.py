# utils.py

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
import io
import html
import logging
from typing import Final
import hashlib
import numpy as np
import cv2  # OpenCV

# --- КОНСТАНТЫ ПРАВ (для админ-хендлеров) ---
ROLE_SUPER_ADMIN: Final[str] = 'super_admin'  # <-- Добавлено
ROLE_ORG_OWNER: Final[str] = 'org_owner'
ROLE_ORG_ADMIN: Final[str] = 'org_admin'
STATUS_ACTIVE: Final[str] = 'active'
STATUS_PENDING: Final[str] = 'pending'


# --- ХЕЛПЕРЫ ---

def hash_password(password: str) -> str:
    """Хеширование пароля с использованием SHA256."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def escape_html(text: str) -> str:
    """Экранирование HTML-символов в тексте."""
    return html.escape(text)


def read_qr_code_from_image(image_bytes: bytes) -> str | None:
    """
    Читает QR-код с изображения с помощью OpenCV.
    Не требует установки системных драйверов zbar.
    """
    try:
        # Конвертируем байты в массив numpy
        nparr = np.frombuffer(image_bytes, np.uint8)

        # Декодируем изображение
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            logging.error("❌ OpenCV не смог декодировать изображение.")
            return None

        # Инициализируем детектор
        detector = cv2.QRCodeDetector()

        # Детектируем и декодируем
        data, bbox, _ = detector.detectAndDecode(image)

        if data:
            logging.info(f"✅ QR код успешно прочитан: {data}")
            return data.strip().upper()

        logging.warning("⚠️ QR код не найден на изображении.")
        return None

    except Exception as e:
        logging.error(f"❌ Ошибка OpenCV при чтении QR: {e}")
        return None


async def cancel_global(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Общий откат для всех диалогов.
    """
    context.user_data.clear()

    text = "❌ Операция отменена. Используйте меню или введите /start (для юзеров) или /admin (для админов)."

    if update.callback_query:
        await update.callback_query.answer()
        # Отправляем новое сообщение, удаляя старую клавиатуру
        await update.callback_query.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())

    # Возвращаем END, чтобы завершить текущий ConversationHandler и разблокировать команду /admin
    return ConversationHandler.END