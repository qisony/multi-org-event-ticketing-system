# user_handlers.py

import os
import uuid
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters, CallbackQueryHandler, \
    CommandHandler
from io import BytesIO
from datetime import datetime
import qrcode
import html  # Для escape_html

# Абсолютные импорты
from db_utils import get_active_orgs, get_org_events_public, get_event_products, get_product_info, find_promo, create_ticket_record, is_blacklisted, increment_promo_usage, add_user, activate_ticket_db, get_user_auth_status, register_user_db, get_user_by_login, authenticate_user_db, check_product_availability, get_org_card # <-- check_product_availability
from utils import cancel_global, escape_html, hash_password  # <-- hash_password

# Определяем состояния для ConversationHandler
(
    MAIN_MENU,
    # Auth States
    ASK_LOGIN_OR_REGISTER,
    INPUT_LOGIN,
    INPUT_PASSWORD,
    REGISTER_INPUT_LOGIN,
    REGISTER_INPUT_PASSWORD,

    # Buy States
    SELECT_ORG,
    SELECT_EVENT,
    SELECT_PRODUCT,
    ENTER_NAME,
    ENTER_EMAIL,
    ENTER_PROMO,
    CONFIRM_PAY,
    WAIT_APPROVAL
) = range(14)


# --- HELPERS ---
def generate_qr(data):
    """Генерирует QR-код."""
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отправляет главное меню аутентифицированному пользователю."""
    keyboard = [
        [InlineKeyboardButton("🎫 Купить билет", callback_data="buy_start")],
        [InlineKeyboardButton("🚪 Выход", callback_data="auth_exit")]
    ]
    text = "🚀 <b>Главное меню</b>\nВыберите действие:"

    if update.callback_query:
        # При возврате из диалогов, лучше отправить новое сообщение
        # и очистить старые кнопки, чтобы избежать ошибки "Message is not modified"
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(  # <--- ИСПОЛЬЗУЕМ reply_text
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        # Опционально: можно попытаться удалить старое сообщение,
        # но чаще всего достаточно отправить новое.

    else:  # Если это /start или прямой MessageUpdate
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    return MAIN_MENU


# --- START/AUTH FLOW ---

async def start_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    add_user(user_id, update.effective_user.username, update.effective_user.first_name)

    if get_user_auth_status(user_id):
        return await send_main_menu(update, context)

    text = "👋 Добро пожаловать!\nДля продолжения работы необходимо войти или зарегистрироваться."
    keyboard = [
        [InlineKeyboardButton("🔑 Войти", callback_data="auth_login")],
        [InlineKeyboardButton("📝 Регистрация", callback_data="auth_register")],
    ]

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    return ASK_LOGIN_OR_REGISTER


# --- LOGIN FLOW ---

async def ask_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    # Кнопка "Назад" (вернет к выбору Войти/Регистрация)
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="auth_exit")]]
    await query.edit_message_text("Введите ваш <b>Логин</b>:", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    return INPUT_LOGIN


async def process_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    login = update.message.text.strip().lower()

    user_data = get_user_by_login(login)

    if not user_data:
        await update.message.reply_text(
            "❌ Пользователь с таким логином не найден. Попробуйте снова или нажмите /cancel:")
        return INPUT_LOGIN

    context.user_data['temp_login'] = login

    await update.message.reply_text("Введите <b>Пароль</b>:", parse_mode='HTML')
    return INPUT_PASSWORD


async def process_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text.strip()
    login = context.user_data.get('temp_login')

    user_data = get_user_by_login(login)
    hashed_password = hash_password(password)

    if user_data and user_data['hash'] == hashed_password:
        authenticate_user_db(update.effective_user.id)
        await update.message.reply_text("✅ Авторизация успешна!", reply_markup=ReplyKeyboardRemove())
        return await send_main_menu(update, context)
    else:
        await update.message.reply_text("❌ Неверный пароль. Попробуйте снова или нажмите /cancel:")
        return INPUT_PASSWORD


# --- REGISTER FLOW ---

async def ask_register_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    # Кнопка "Назад"
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="auth_exit")]]
    text = "📝 <b>Регистрация</b>\n\nВведите желаемый <b>Логин</b>..."
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    return REGISTER_INPUT_LOGIN


async def process_register_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    login = update.message.text.strip().lower()

    if not re.match(r'^[a-z0-9]{3,20}$', login):
        await update.message.reply_text("❌ Логин не соответствует критериям. Попробуйте снова:")
        return REGISTER_INPUT_LOGIN

    if get_user_by_login(login):
        await update.message.reply_text("❌ Логин уже занят. Попробуйте другой:")
        return REGISTER_INPUT_LOGIN

    context.user_data['reg_login'] = login

    text = (
        "✅ Логин принят. Введите <b>Пароль</b>.\n"
        "<i>Критерии: от 6 символов, должен содержать хотя бы одну заглавную букву, одну строчную букву и одну цифру.</i>"
    )
    await update.message.reply_text(text, parse_mode='HTML')
    return REGISTER_INPUT_PASSWORD


async def process_register_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text.strip()

    if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{6,}$', password):
        await update.message.reply_text("❌ Пароль не соответствует критериям. Попробуйте снова:")
        return REGISTER_INPUT_PASSWORD

    login = context.user_data['reg_login']
    user_id = update.effective_user.id
    password_hash = hash_password(password)

    if register_user_db(user_id, login, password_hash):
        await update.message.reply_text("🎉 Регистрация успешна! Выполнен вход.", reply_markup=ReplyKeyboardRemove())
        return await send_main_menu(update, context)
    else:
        # Это должно быть невозможным, если логин проверен выше, но на всякий случай
        await update.message.reply_text("❌ Ошибка регистрации (логин занят). Начните сначала: /start")
        return ConversationHandler.END


# --- BUY FLOW (Unchanged, but now starts from MAIN_MENU) ---

async def start_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    orgs = get_active_orgs()
    if not orgs:
        await update.callback_query.edit_message_text("Нет доступных мероприятий.")
        return MAIN_MENU  # Возвращаемся в главное меню

    if len(orgs) == 1:
        context.user_data['buy_org_id'] = orgs[0]['id']
        return await show_events(update, context)

    keyboard = []
    for o in orgs:
        safe_name = escape_html(o['name'])
        keyboard.append([InlineKeyboardButton(safe_name, callback_data=f"buy_org_{o['id']}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="goto_main_menu")])

    await update.callback_query.edit_message_text("Выберите организатора:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_ORG


async def org_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    org_id = int(query.data.split('_')[2])

    if is_blacklisted(org_id, query.from_user.id):
        await query.edit_message_text("❌ Вы в черном списке этой организации или глобально.")
        return MAIN_MENU

    context.user_data['buy_org_id'] = org_id
    return await show_events(update, context)


async def show_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    org_id = context.user_data['buy_org_id']
    events = get_org_events_public(org_id)

    keyboard = []
    if not events:
        msg = "Нет активных мероприятий."
    else:
        msg = "Выберите мероприятие:"
        for e in events:
            safe_name = escape_html(e['name'])
            keyboard.append([InlineKeyboardButton(f"{safe_name} ({e['date']})", callback_data=f"buy_ev_{e['id']}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="buy_start")])  # К выбору организаций

    if update.callback_query and update.callback_query.data != "buy_start":
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        # Если пришло с buy_start, то edit_message_text уже был
        await context.bot.edit_message_text(chat_id=update.effective_chat.id,
                                            message_id=update.effective_message.message_id, text=msg,
                                            reply_markup=InlineKeyboardMarkup(keyboard))

    return SELECT_EVENT


async def event_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    ev_id = int(query.data.split('_')[2])
    context.user_data['buy_ev_id'] = ev_id

    products = get_event_products(ev_id)

    keyboard = []
    if not products:
        msg = "Билетов нет в продаже."
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="goto_events_list")])
    else:
        msg = "Выберите билет:"
        for p in products:
            safe_name = escape_html(p['name'])
            keyboard.append(
                [InlineKeyboardButton(f"{safe_name} - {p['price']} руб.", callback_data=f"buy_prod_{p['id']}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="goto_events_list")])  # К списку мероприятий


    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_PRODUCT


async def product_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    prod_id = int(query.data.split('_')[2])

    # ПРОВЕРКА ЛИМИТА
    available, remaining = check_product_availability(prod_id)

    if not available:
        await query.edit_message_text("❌ Извините, билеты этой категории **закончились**.", parse_mode='Markdown')
        # Возврат к списку (можно вызвать show_events или остаться)
        return SELECT_PRODUCT

    info = get_product_info(prod_id)
    context.user_data['buy_prod'] = info

    safe_name = escape_html(info['name'])

    rem_text = f" (Осталось: {remaining})" if remaining != -1 else ""

    # Кнопка отмены (вернет к списку товаров)
    # Важно: callback_data должна вести назад к списку товаров этого ивента
    ev_id = context.user_data.get('buy_ev_id')
    keyboard = [[InlineKeyboardButton("🔙 К выбору билетов", callback_data=f"buy_ev_{ev_id}")]]

    await query.edit_message_text(
        f"Выбрано: <b>{safe_name}</b>\nЦена: {info['price']} руб.{rem_text}\n\n"
        f"Введите ваше <b>ФИО</b>:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ENTER_NAME


async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['buy_name'] = update.message.text
    # Кнопка отмены (полный выход в меню)
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="buy_start")]]
    await update.message.reply_text("Введите <b>Email</b>:", parse_mode='HTML',
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return ENTER_EMAIL


async def enter_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['buy_email'] = update.message.text

    # Сразу предлагаем ввести промокод
    keyboard = [
        [InlineKeyboardButton("Нет промокода", callback_data="skip_promo")],
        [InlineKeyboardButton("❌ Отмена", callback_data="buy_start")]
    ]
    await update.message.reply_text(
        "У вас есть <b>Промокод</b>? Введите его сообщением или нажмите кнопку:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return ENTER_PROMO


async def process_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Обработка текста промокода
    code = update.message.text.strip()
    ev_id = context.user_data['buy_ev_id']

    promo_data = find_promo(code, ev_id)  # Нужна реализация в db_utils (см. ниже)

    if promo_data:
        # promo_data = {'code': '...', 'discount': 10, ...}
        context.user_data['applied_promo'] = promo_data
        await update.message.reply_text(f"✅ Промокод <b>{code}</b> применен! Скидка {promo_data['discount']}%.",
                                        parse_mode='HTML')
    else:
        await update.message.reply_text("❌ Промокод не найден или истек лимит. Продолжаем без него.")
        context.user_data['applied_promo'] = None

    return await show_payment_confirm(update, context)


async def skip_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['applied_promo'] = None
    return await show_payment_confirm(update, context)


async def show_payment_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Вспомогательная функция для отображения итога
    info = context.user_data['buy_prod']
    name = context.user_data['buy_name']
    promo = context.user_data.get('applied_promo')

    price = info['price']
    final_price = price

    promo_text = "Нет"
    if promo:
        discount = promo['discount']
        final_price = int(price * (100 - discount) / 100)
        promo_text = f"{promo['code']} (-{discount}%)"

    context.user_data['final_price'] = final_price

    txt = (
        f"<b>Подтверждение заказа:</b>\n"
        f"Ивент: {escape_html(info['event_name'])}\n"
        f"Билет: {escape_html(info['name'])}\n"
        f"Покупатель: {escape_html(name)}\n"
        f"Промокод: {promo_text}\n"
        f"-------------------\n"
        f"<b>К оплате: {final_price} руб.</b>"
    )

    keyboard = [
        [InlineKeyboardButton(f"💳 Оплатить {final_price} руб.", callback_data="do_pay")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_email")]  # Вернуться к вводу email
    ]

    # Определяем, откуда вызвали (кнопка или текст)
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(keyboard),
                                                      parse_mode='HTML')
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    return CONFIRM_PAY


# --- ФУНКЦИЯ ВОЗВРАТА (которая вызывала ошибку) ---
async def back_to_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="buy_start")]]
    await query.edit_message_text("Введите <b>Email</b>:", parse_mode='HTML',
                                  reply_markup=InlineKeyboardMarkup(keyboard))
    return ENTER_EMAIL


async def confirm_pay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    ref = uuid.uuid4().hex[:8].upper()
    context.user_data['pay_ref'] = ref
    final_price = context.user_data['final_price']
    org_id = context.user_data['buy_prod']['org_id']

    # Получаем карту из БД
    card = get_org_card(org_id)
    if not card:
        card = "УТОЧНИТЕ У ОРГАНИЗАТОРА"

    msg = (
        f"💳 **ПОДТВЕРЖДЕНИЕ ПОКУПКИ**\n\n"
        f"**Билет:** {escape_html(product_name)}\n"
        f"**Мероприятие:** {escape_html(event_name)}\n"
        f"**Цена:** {final_price:.2f} ₽\n"
        f"**Получатель (Номер карты):** `{card}`\n\n"
        f"❗ **ВАЖНОЕ ПРАВИЛО ОПЛАТЫ:**\n"
        f"**НЕ УКАЗЫВАЙТЕ НИКАКИХ КОММЕНТАРИЕВ К ПЛАТЕЖУ!**\n" # <--- НОВОЕ ПРЕДУПРЕЖДЕНИЕ
        f"Просто переведите сумму ({final_price:.2f} ₽) на указанную карту.\n"
        f"После оплаты нажмите кнопку **«Я оплатил»**.\n"
    )

    keyboard = [[InlineKeyboardButton("✅ Я оплатил", callback_data="paid_ok")]
    [InlineKeyboardButton("🔙 Назад к вводу email", callback_data="back_to_email")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return WAIT_APPROVAL


async def send_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    ref = context.user_data['pay_ref']
    prod = context.user_data['buy_prod']
    name = context.user_data['buy_name']
    email = context.user_data['buy_email']
    user_id = query.from_user.id

    ticket_id = f"T-{uuid.uuid4().hex[:8].upper()}"

    # --- Вызываем обновленную функцию, которая проверяет лимит и инкрементирует счетчик ---
    if create_ticket_record(ticket_id, prod['id'], user_id, name, email, prod['price']):
        admin_data = {
            'ref': ref,
            'ticket_id': ticket_id,
            'user_id': user_id,
            'amount': prod['price'],
            'buyer': name
        }

        context.application.bot_data[f"pay_{ref}"] = admin_data

    adm_id = os.getenv("ADMIN_ID")
    if adm_id:
        admin_msg = (
            f"💰 <b>Новая оплата</b>\n"
            f"Орг ID: {prod['org_id']}\n"
            f"Сумма: {prod['price']}\n"
            f"Ref: <code>{ref}</code>\n"
            f"Покупатель: {escape_html(name)}"
        )

        kb = [
            [InlineKeyboardButton("✅ Подтвердить", callback_data=f"adm_approve_{ref}")],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f"adm_reject_{ref}")]
        ]

        try:
            await context.bot.send_message(chat_id=adm_id, text=admin_msg, reply_markup=InlineKeyboardMarkup(kb),
                                           parse_mode='HTML')
        except Exception as e:
            logging.error(f"Failed to send admin notification: {e}")

        await query.edit_message_text("✅ Заявка отправлена! Ожидайте билет после проверки платежа.")
    else:
        # Если билеты закончились в момент отправки заявки
        await query.edit_message_text(
        "❌ Не удалось создать заявку. Билеты этой категории закончились. Попробуйте другую категорию.")


    return MAIN_MENU  # Возвращаемся в главное меню


async def issue_ticket_from_admin_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный хендлер для подтверждения/отклонения билета администратором."""
    query = update.callback_query
    await query.answer()
    data = query.data

    action, ref = data.split("_")[1], data.split("_")[2]
    key = f"pay_{ref}"
    pay_data = context.application.bot_data.get(key)

    if not pay_data:
        await query.edit_message_text("❌ Данные устарели.", parse_mode='HTML')
        return

    user_id = pay_data['user_id']
    ticket_id = pay_data['ticket_id']

    if action == 'approve':
        activate_ticket_db(ticket_id)

        qr_img = generate_qr(ticket_id)
        caption = f"✅ <b>ВАШ БИЛЕТ</b>\nID: <code>{ticket_id}</code>\nПокажите этот QR-код на входе."

        try:
            await context.bot.send_photo(chat_id=user_id, photo=InputFile(qr_img, filename=f'{ticket_id}.png'),
                                         caption=caption, parse_mode='HTML')
            await query.edit_message_text(
                f"✅ Билет <code>{ticket_id}</code> выдан пользователю (Ref: <code>{ref}</code>).", parse_mode='HTML')
        except Exception as e:
            await query.edit_message_text(
                f"⚠️ Билет активирован, но не отправлен (блок бота?). ID: <code>{ticket_id}</code>", parse_mode='HTML')
            logging.error(f"Failed to send ticket to {user_id}: {e}")

        reset_kb = [[InlineKeyboardButton("🏠 В главное меню", callback_data="user_reset_to_menu")]]

        await context.bot.send_message(
            chat_id=user_id,
            text="✅ Билет получен. Нажмите кнопку, чтобы вернуться в меню.",
            reply_markup=InlineKeyboardMarkup(reset_kb)
        )

    elif action == 'reject':
        try:
            await context.bot.send_message(chat_id=user_id,
                                           text=f"❌ Оплата по заявке <code>{ref}</code> отклонена администратором. Свяжитесь с поддержкой.",
                                           parse_mode='HTML')
            await query.edit_message_text(f"❌ Заявка <code>{ref}</code> отклонена.", parse_mode='HTML')
        except:
            await query.edit_message_text(f"❌ Заявка <code>{ref}</code> отклонена. Не удалось уведомить пользователя.",
                                          parse_mode='HTML')

    if key in context.application.bot_data:
        del context.application.bot_data[key]


buy_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start_auth)],
    states={
        # --- AUTH STATES ---
        ASK_LOGIN_OR_REGISTER: [
            CallbackQueryHandler(ask_login, pattern="^auth_login$"),
            CallbackQueryHandler(ask_register_login, pattern="^auth_register$"),
        ],
        INPUT_LOGIN: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_login),
            CallbackQueryHandler(start_auth, pattern="^auth_exit$")  # <-- Назад к старту
        ],
        INPUT_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_password)],
        REGISTER_INPUT_LOGIN: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_register_login),
            CallbackQueryHandler(start_auth, pattern="^auth_exit$")  # <-- Назад к старту
        ],
        REGISTER_INPUT_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_register_password)],

        # --- MAIN MENU ---
        MAIN_MENU: [
            CallbackQueryHandler(start_buy, pattern="^buy_start$"),
            CallbackQueryHandler(send_main_menu, pattern="^user_reset_to_menu$"),
            CallbackQueryHandler(start_auth, pattern="^auth_exit$"),  # Выход - это снова /start
            CallbackQueryHandler(send_main_menu, pattern="^goto_main_menu$"),
        ],

        # --- BUY STATES ---
        SELECT_ORG: [
            CallbackQueryHandler(org_selected, pattern="^buy_org_"),
            CallbackQueryHandler(start_buy, pattern="^buy_start$"),  # Назад к выбору
        ],
        SELECT_EVENT: [
            CallbackQueryHandler(event_selected, pattern="^buy_ev_"),
            CallbackQueryHandler(start_buy, pattern="^buy_start$"),  # Назад к выбору организаций
        ],
        SELECT_PRODUCT: [
            CallbackQueryHandler(product_selected, pattern="^buy_prod_"),
            CallbackQueryHandler(show_events, pattern="^goto_events_list$"),  # Назад к выбору мероприятий
        ],
        ENTER_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name),
            # Обработка кнопки "К выбору билетов", которая была отправлена в product_selected
            CallbackQueryHandler(event_selected, pattern="^buy_ev_")
        ],

        ENTER_EMAIL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, enter_email),
            CallbackQueryHandler(product_selected, pattern="^back_to_prod_select$"),
            CallbackQueryHandler(start_buy, pattern="^buy_start$")  # <-- Отмена покупки
        ],

        ENTER_PROMO: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_promo),
            CallbackQueryHandler(skip_promo, pattern="^skip_promo$"),
            CallbackQueryHandler(start_buy, pattern="^buy_start$")
        ],

        CONFIRM_PAY: [
            CallbackQueryHandler(confirm_pay, pattern="^do_pay"),
            CallbackQueryHandler(back_to_email, pattern="^back_to_email"),
        ],
        WAIT_APPROVAL: [CallbackQueryHandler(send_approval, pattern="^paid_ok")]
    },
    fallbacks=[CommandHandler("cancel", cancel_global), CallbackQueryHandler(cancel_global, pattern='^cancel_global')]
)