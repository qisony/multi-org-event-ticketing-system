# admin_handlers.py (ПОЛНЫЙ НОВЫЙ КОД)

import os
import uuid
import openpyxl
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, InputFile
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, \
    CommandHandler
from db_utils import *
from utils import escape_html, read_qr_code_from_image, cancel_global, ROLE_SUPER_ADMIN, ROLE_ORG_OWNER, ROLE_ORG_ADMIN, \
    hash_password
import io
import asyncio
from datetime import datetime

# Получаем ID супер-админа из .env
try:
    SUPER_ADMIN_ID = int(os.getenv("ADMIN_ID"))
except:
    SUPER_ADMIN_ID = 0

ORG_LIMIT_PER_OWNER = 2

# admin_handlers.py (Примерно строка 35)

# --- STATES ---
(
    LVL1_MAIN,
    LVL2_ORG_LIST,
    LVL3_ORG_MENU,
    LVL4_EVENT_LIST,
    LVL5_EVENT_MENU,
    LVL6_PROMO_MENU,  # Из предыдущего шага

    # Input/Action States
    INPUT_NEW_ORG_NAME,

    # ИЗМЕНЕНО: Замените INPUT_ADD_ADMIN_ID на INPUT_ADD_ADMIN_LOGIN
    INPUT_ADD_ADMIN_LOGIN,
    # ИЗМЕНЕНО: Замените INPUT_ADD_OWNER_ID на INPUT_ADD_OWNER_LOGIN
    INPUT_ADD_OWNER_LOGIN,

    INPUT_NEW_EVENT_NAME,
    INPUT_NEW_EVENT_DATE,
    INPUT_NEW_PROD_NAME,
    INPUT_NEW_PROD_PRICE,
    INPUT_NEW_PROD_LIMIT,
    INPUT_PROD_REFUND_STATUS,
    INPUT_CHECK_TICKET,
    INPUT_ORG_CARD,  # Для карты

    # Promo Inputs
    INPUT_PROMO_CODE,
    INPUT_PROMO_PERCENT,
    INPUT_PROMO_LIMIT,

    # Broadcast States
    BROADCAST_AUDIENCE,
    BROADCAST_TEXT,

    # Blacklist States
    GLOBAL_BLACKLIST_MENU,
    GLOBAL_BL_ID,
    GLOBAL_BL_REASON,

    # Delete States
    EVENT_DELETE_CONFIRM,
    ORG_DELETE_CONFIRM,

    # Сброс БД
    DB_RESET_CONFIRM
) = range(28)  # <-- Убедитесь, что число в range() соответствует общему количеству состояний.


# --- LEVEL 1: SUPER ADMIN MAIN MENU ---

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    is_super = (user_id == SUPER_ADMIN_ID)
    roles = get_admin_roles(user_id)

    if not is_super and not roles:
        msg_obj = update.callback_query.edit_message_text if update.callback_query else update.message.reply_text
        await msg_obj("❌ У вас нет прав администратора.")
        return ConversationHandler.END

    context.user_data.update({'roles': roles, 'is_super': is_super})

    keyboard = []

    if is_super:
        keyboard = [
            [InlineKeyboardButton("👥 Назначить Владельца", callback_data="add_org_owner")],
            [InlineKeyboardButton("🏢 Управление организациями", callback_data="goto_lvl2_all")],
            [InlineKeyboardButton("🚫 Общий Черный Список", callback_data="goto_global_bl")],
            [InlineKeyboardButton("📢 Общая рассылка", callback_data="start_global_broadcast")],
            [InlineKeyboardButton("🚪 Выход", callback_data="admin_exit")]
        ]
        text = "👑 <b>Панель Супер-Администратора</b>\nВыберите действие:"

    elif roles:
        return await list_orgs(update, context, direct_call=True)

    msg_obj = update.callback_query.edit_message_text if update.callback_query else update.message.reply_text

    if update.callback_query:
        await update.callback_query.answer()
        await msg_obj(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    elif update.message:
        await msg_obj(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    return LVL1_MAIN


# --- SUPER ADMIN: ADD ORG OWNER (ОБНОВЛЕНО) ---
async def ask_owner_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # Кнопка возврата в главное меню админа
    keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data="back_lvl1")]]

    await query.edit_message_text(
        "Введите Telegram ID пользователя (цифры) для назначения **Владельцем Организаций**:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return INPUT_ADD_OWNER_LOGIN


async def add_owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        new_owner_id = int(update.message.text)

        add_user(new_owner_id, None, None)

        success = set_user_as_org_creator(new_owner_id, ORG_LIMIT_PER_OWNER)

        if success:
            await update.message.reply_text(
                f"✅ Пользователь <code>{new_owner_id}</code> теперь может создавать организации (макс. {ORG_LIMIT_PER_OWNER}).\n\nЕму необходимо использовать команду /admin и кнопку 'Создать Организацию'.",
                parse_mode='HTML')
        else:
             await update.message.reply_text("❌ Ошибка базы данных при назначении прав владельца.")

    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
    except Exception as e:
        logging.error(f"Add owner error: {e}")
        await update.message.reply_text("❌ Непредвиденная ошибка при назначении владельца.")

    # Возврат в главное меню админа
    return await admin_start(update, context)

# --- LEVEL 2: ORG LIST ---

async def list_orgs(update: Update, context: ContextTypes.DEFAULT_TYPE, direct_call=False) -> int:
    query = None
    if not direct_call and update.callback_query:
        query = update.callback_query
        await query.answer()

    # --- ЛОГИКА ОПРЕДЕЛЕНИЯ РЕЖИМА (ИСПРАВЛЕНО) ---
    # По умолчанию берем 'my'
    mode = 'my'

    if direct_call:
        mode = 'my'
    elif query:
        # Если мы пришли из главного меню (например, "goto_lvl2_all")
        if query.data.startswith("goto_lvl2_"):
            mode = query.data.split('_')[-1]
            # Сохраняем режим в память
            context.user_data['view_mode'] = mode

        # Если нажали "Назад" (back_lvl2) или любую другую кнопку в этом списке
        # пытаемся восстановить режим из памяти
        else:
            mode = context.user_data.get('view_mode', 'my')

    # ---------------------------------------------

    conn = connect_db()
    cursor = conn.cursor()

    user_id = update.effective_user.id
    is_super = context.user_data.get('is_super')

    # Теперь mode гарантированно существует
    if is_super and mode == 'all':
        cursor.execute("SELECT id, name, owner_id FROM organizations ORDER BY id ASC")
        orgs = cursor.fetchall()
        can_create = True
    else:
        cursor.execute("""
            SELECT o.id, o.name, o.owner_id FROM organizations o 
            JOIN org_admins oa ON o.id = oa.org_id 
            WHERE oa.user_id = %s
        """, (user_id,))
        orgs = cursor.fetchall()

        # Проверка лимита для владельцев
        org_count = get_user_org_count(user_id)
        if org_count < ORG_LIMIT_PER_OWNER:
            can_create = True
        else:
            can_create = False

    conn.close()

    # Если орг всего одна и это прямой вызов (создали и вернулись) - заходим внутрь
    if len(orgs) == 1 and direct_call:
        context.user_data['curr_org_id'] = orgs[0][0]
        return await org_menu(update, context, direct_call=True)

    keyboard = []
    for org in orgs:
        owner_text = f" (Владелец: {org[2]})" if is_super and org[2] else ""
        safe_name = escape_html(org[1])
        keyboard.append([InlineKeyboardButton(f"🏢 {safe_name}{owner_text}", callback_data=f"sel_org_{org[0]}")])

    if can_create:
        keyboard.append([InlineKeyboardButton("➕ Создать Организацию", callback_data="create_org")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_lvl1")])

    text = "🏢 <b>Выбор Организации</b>\nВыберите организацию для управления:"

    # Универсальная отправка (фикс из прошлого ответа)
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.effective_chat.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    return LVL2_ORG_LIST


# --- WIZARD: CREATE ORGANIZATION (ОБНОВЛЕНО) ---
async def ask_new_org_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # Повторная проверка лимита
    user_id = query.from_user.id
    if get_user_org_count(user_id) >= ORG_LIMIT_PER_OWNER:
        await query.edit_message_text(
            f"❌ Достигнут лимит: Вы не можете создать больше {ORG_LIMIT_PER_OWNER} организаций.", parse_mode='HTML')
        return await list_orgs(update, context)

    # Добавлена кнопка отмены
    keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data="back_lvl2")]]

    await query.edit_message_text("Введите название новой организации:", reply_markup=InlineKeyboardMarkup(keyboard))
    return INPUT_NEW_ORG_NAME


async def create_org_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text
    user_id = update.effective_user.id

    if get_user_org_count(user_id) >= ORG_LIMIT_PER_OWNER:
        await update.message.reply_text(
            f"❌ Достигнут лимит: Вы не можете создать больше {ORG_LIMIT_PER_OWNER} организаций.", parse_mode='HTML')
    else:
        try:
            org_id = create_organization(name, user_id)
            if org_id:
                await update.message.reply_text(
                    f"✅ Организация '<b>{escape_html(name)}</b>' создана. Вы назначены владельцем.", parse_mode='HTML')
            else:
                raise Exception("DB failed to create org")
        except Exception as e:
            logging.error(f"Error creating org: {e}")
            await update.message.reply_text("❌ Произошла ошибка при создании организации.")

    # Возврат в список организаций
    return await list_orgs(update, context, direct_call=True)


# --- LEVEL 3: SPECIFIC ORG MENU ---

async def org_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, direct_call=False) -> int:
    if update.callback_query and update.callback_query.data.startswith("sel_org_"):
        query = update.callback_query
        await query.answer()
        org_id = int(query.data.split("_")[2])
        context.user_data['curr_org_id'] = org_id
    else:
        org_id = context.user_data.get('curr_org_id')
        if update.callback_query:
            await update.callback_query.answer()

    org_name = get_org_name(org_id)
    safe_org_name = escape_html(org_name)

    user_id = update.effective_user.id
    is_super = context.user_data.get('is_super')
    role_db = context.user_data.get('roles', {}).get(org_id)

    if is_super:
        role = ROLE_SUPER_ADMIN
    elif role_db:
        role = role_db
    else:
        role = "Пользователь"

    context.user_data['curr_role'] = role

    keyboard = [
        [InlineKeyboardButton("📅 Управление мероприятиями", callback_data="goto_events")],
        [InlineKeyboardButton("✅ Проверить билет (Org)", callback_data="check_ticket_org")]
    ]

    if role in [ROLE_SUPER_ADMIN, ROLE_ORG_OWNER]:
        keyboard.append([InlineKeyboardButton("👤 Управление Админами", callback_data="add_admin")])
        keyboard.append([InlineKeyboardButton("📢 Рассылка (Org)", callback_data="start_org_broadcast")])
        keyboard.append([InlineKeyboardButton("💳 Настроить Карту", callback_data="set_org_card")])
        keyboard.append([InlineKeyboardButton("🗑️ Удалить организацию", callback_data="start_delete_org")])
        
    keyboard.append([InlineKeyboardButton("🔙 Назад к списку", callback_data="back_lvl2")])

    text = f"⚙️ <b>Управление организацией:</b> <code>{safe_org_name}</code>\nВаша роль: <b>{role}</b>"

    if direct_call and update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    return LVL3_ORG_MENU


# --- ADMIN MANAGEMENT (ОБНОВЛЕНО) ---
async def ask_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # Кнопка возврата в меню организации
    keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data="back_menu_org")]]

    await query.edit_message_text(
        "Введите Telegram ID пользователя (цифры) для назначения админом (роль 'org_admin'):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return INPUT_ADD_ADMIN_ID


async def add_admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        new_admin_id = int(update.message.text)
        org_id = context.user_data['curr_org_id']

        if add_org_admin(org_id, new_admin_id, ROLE_ORG_ADMIN):
            await update.message.reply_text(f"✅ Админ <code>{new_admin_id}</code> добавлен с ролью '{ROLE_ORG_ADMIN}'.",
                                            parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Ошибка добавления. Пользователь должен был запустить бота (/start).")
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
    except Exception as e:
        logging.error(f"Add admin error: {e}")
        await update.message.reply_text("❌ Непредвиденная ошибка при добавлении админа.")

    # Возврат в меню организации
    return await org_menu(update, context, direct_call=True)


# --- LEVEL 4/5 & OTHER HANDLERS (ОБНОВЛЕНО) ---

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE, direct_call=False) -> int:
    # 1. Определяем, откуда пришел вызов (кнопка или текст)
    query = update.callback_query
    if query:
        await query.answer()

    org_id = context.user_data['curr_org_id']
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM events WHERE org_id = %s", (org_id,))
    events = cursor.fetchall()
    conn.close()

    keyboard = []
    for ev in events:
        safe_name = escape_html(ev[1])
        keyboard.append([InlineKeyboardButton(f"🎉 {safe_name}", callback_data=f"sel_ev_{ev[0]}")])

    role = context.user_data['curr_role']
    if role in [ROLE_SUPER_ADMIN, ROLE_ORG_OWNER]:
        keyboard.append([InlineKeyboardButton("➕ Создать Мероприятие", callback_data="create_event")])
        keyboard.append([InlineKeyboardButton("🗑 Удалить Мероприятие", callback_data="start_delete_event")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_lvl3")])

    text = "📅 <b>Список Мероприятий</b>:"

    # 2. Логика отправки: Редактируем старое сообщение ИЛИ отправляем новое
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        # Если вызов был после ввода текста (прямой вызов)
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    return LVL4_EVENT_LIST


async def start_create_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()

    # Кнопка отмены (возврат к списку мероприятий)
    keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data="goto_events")]]

    await update.callback_query.edit_message_text(
        "Введи <b>Название</b> мероприятия:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return INPUT_NEW_EVENT_NAME


async def input_event_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_ev_name'] = update.message.text

    # Кнопка отмены (возврат в меню организации)
    keyboard = [[InlineKeyboardButton("❌ Отмена создания", callback_data="back_menu_org")]]

    await update.message.reply_text(
        "Введите <b>Дату</b> (текстом, например '25.12.2025 18:00'):",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return INPUT_NEW_EVENT_DATE


async def input_event_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_ev_date'] = update.message.text

    org_id = context.user_data['curr_org_id']
    name = context.user_data['new_ev_name']
    date = context.user_data['new_ev_date']

    conn = connect_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO events (org_id, name, date_str) VALUES (%s, %s, %s)", (org_id, name, date))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ Мероприятие <b>{escape_html(name)}</b> создано!", parse_mode='HTML')
    # Возврат к списку мероприятий
    return await list_events(update, context, direct_call=True)


async def event_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query

    # 1. Если есть query, обрабатываем данные из кнопки
    if query:
        await query.answer()
        if query.data.startswith("sel_ev_"):
            ev_id = int(query.data.split("_")[2])
            context.user_data['curr_ev_id'] = ev_id
        else:
            ev_id = context.user_data.get('curr_ev_id')
    else:
        # Если query нет (пришли из текстового ввода), берем ID из памяти
        ev_id = context.user_data.get('curr_ev_id')

    text = f"🎉 <b>Меню Мероприятия #{ev_id}</b>"

    keyboard = [
        [InlineKeyboardButton("📝 Тарифы/Билеты (Остаток)", callback_data="list_products")],
        [InlineKeyboardButton("🎟 Промокоды", callback_data="list_promos")],
        [InlineKeyboardButton("✅ Проверить билет", callback_data="check_ticket_ev")],
        [InlineKeyboardButton("📊 Отчет (Excel)", callback_data="report_excel")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_lvl4")]
    ]

    # 2. Отправка сообщения
    if query:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    else:
        # Для текстового ввода отправляем новое сообщение
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    return LVL5_EVENT_MENU


async def list_products_with_quantities(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    ev_id = context.user_data['curr_ev_id']

    products = get_event_products(ev_id)

    msg = "🎫 <b>Список Тарифов</b>\n\n"
    keyboard = []

    for p in products:
        if p['limit'] == 0:
            limit_text = "Без ограничений"
        else:
            remaining = p['limit'] - p['sold']
            limit_text = f"Осталось: {remaining} из {p['limit']}"

        msg += f"• <b>{escape_html(p['name'])}</b> ({p['price']} руб.)\n"
        msg += f"  <i>Продано: {p['sold']} | {limit_text}</i>\n"

    keyboard.append([InlineKeyboardButton("➕ Добавить Тариф", callback_data="add_product")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_menu_ev")])

    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return LVL5_EVENT_MENU


# --- СБРОС БАЗЫ ДАННЫХ (остается без изменений) ---

async def start_db_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрос подтверждения сброса БД."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("✅ ПОДТВЕРДИТЬ СБРОС", callback_data="db_reset_confirm")],
        [InlineKeyboardButton("🔙 Отмена", callback_data="back_lvl1")]
    ]

    await query.edit_message_text(
        "🔥 <b>ВНИМАНИЕ! Вы собираетесь полностью очистить базу данных!</b>\n"
        "Это приведет к **безвозвратному удалению** всех пользователей, билетов, мероприятий и настроек.\n"
        "Подтвердите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return DB_RESET_CONFIRM


async def confirm_db_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выполнение сброса БД и инициирование перезапуска."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text("⏳ Идет очистка базы данных...")

    if drop_all_tables():
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ База данных успешно очищена!\n\n🤖 **Инициирую перезапуск бота...**\n",
            parse_mode='HTML'
        )

        logging.warning("DB reset completed. Initiating system exit for bot restart.")
        os._exit(0)

    else:
        await query.edit_message_text("❌ Ошибка при очистке базы данных. Операция отменена. Проверьте логи.")
        return await admin_start(update, context)


# --- WIZARD: CREATE PRODUCT (ОБНОВЛЕНО) ---

async def create_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()

    # Кнопка отмены (возврат в меню ивента)
    keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data="back_menu_ev")]]

    await update.callback_query.edit_message_text(
        "<b>Название Тарифа</b> (например, 'VIP'):",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return INPUT_NEW_PROD_NAME


async def input_prod_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_prod_name'] = update.message.text

    # Кнопка отмены (возврат в меню ивента)
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="back_menu_ev")]]

    await update.message.reply_text(
        "<b>Цена</b> (число):",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return INPUT_NEW_PROD_PRICE


async def input_prod_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="back_menu_ev")]]

    try:
        context.user_data['new_prod_price'] = int(update.message.text)
        await update.message.reply_text(
            "<b>Максимальное количество билетов</b> (введите 0 для безлимита):",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return INPUT_NEW_PROD_LIMIT
    except ValueError:
        await update.message.reply_text(
            "❌ Цена должна быть целым числом. Повторите ввод цены:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return INPUT_NEW_PROD_PRICE


# admin_handlers.py

async def input_prod_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        limit = int(update.message.text)
        if limit < 0: raise ValueError

        # --- ВАЖНО: СОХРАНЯЕМ ЛИМИТ В ПАМЯТЬ ---
        context.user_data['new_prod_limit'] = limit
        # ---------------------------------------

        # Теперь спрашиваем про возвратность
        keyboard = [
            [InlineKeyboardButton("✅ Да, возвратный", callback_data="refund_yes")],
            [InlineKeyboardButton("❌ Нет, невозвратный", callback_data="refund_no")],
            [InlineKeyboardButton("🔙 Отмена", callback_data="back_menu_ev")]
        ]

        await update.message.reply_text(
            f"Лимит установлен: <b>{limit if limit > 0 else 'Безлимит'}</b>.\n\n"
            "Теперь выберите: <b>Можно ли вернуть этот билет?</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        return INPUT_PROD_REFUND_STATUS

    except ValueError:
        await update.message.reply_text("❌ Количество должно быть целым числом (0 или больше). Повторите ввод:")
        return INPUT_NEW_PROD_LIMIT


# admin_handlers.py

async def save_new_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # Определяем возвратность из нажатой кнопки
    is_refundable = (query.data == "refund_yes")

    # Достаем ВСЕ данные из памяти
    ev_id = context.user_data['curr_ev_id']
    name = context.user_data['new_prod_name']
    price = context.user_data['new_prod_price']

    # --- ДОСТАЕМ ЛИМИТ ---
    limit = context.user_data['new_prod_limit']
    # ---------------------

    # Сохраняем в БД (функция create_product должна принимать 5 аргументов!)
    # Убедитесь, что вы обновили db_utils.py из прошлого ответа
    prod_id = create_product(ev_id, name, price, limit, is_refundable)

    refund_text = "✅ Возвратный" if is_refundable else "❌ Невозвратный"
    limit_text = "Безлимит" if limit == 0 else str(limit)

    if prod_id:
        await query.edit_message_text(
            f"✅ Тариф создан!\n\n"
            f"🏷 <b>{escape_html(name)}</b>\n"
            f"💰 Цена: {price} руб.\n"
            f"🔢 Лимит: {limit_text}\n"
            f"🔄 Тип: {refund_text}",
            parse_mode='HTML'
        )
    else:
        await query.edit_message_text("❌ Ошибка при сохранении тарифа.")

    return await event_menu(update, context)  # Возврат в меню ивента



# --- НОВОЕ: УДАЛЕНИЕ МЕРОПРИЯТИЯ (остается без изменений) ---

async def start_delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    org_id = context.user_data['curr_org_id']

    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM events WHERE org_id = %s", (org_id,))
    events = cursor.fetchall()
    conn.close()

    if not events:
        await query.edit_message_text("Нет мероприятий для удаления.")
        return await list_events(update, context)

    keyboard = []
    for ev in events:
        safe_name = escape_html(ev[1])
        keyboard.append([InlineKeyboardButton(f"🗑 {safe_name}", callback_data=f"del_ev_select_{ev[0]}")])

    keyboard.append([InlineKeyboardButton("🔙 Отмена", callback_data="back_lvl4")])

    await query.edit_message_text(
        "⚠️ **Удаление Мероприятия**\nВыберите, какое мероприятие удалить (удалятся все билеты и тарифы!):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return EVENT_DELETE_CONFIRM


async def confirm_delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    ev_id = int(query.data.split("_")[3])
    # Получаем название для сообщения
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM events WHERE id = %s", (ev_id,))
    event_name = cursor.fetchone()[0] if cursor.rowcount > 0 else f"#{ev_id}"
    conn.close()

    if delete_event(ev_id):
        await query.edit_message_text(f"✅ Мероприятие **{escape_html(event_name)}** и все связанные данные удалены.",
                                      parse_mode='HTML')
    else:
        await query.edit_message_text("❌ Ошибка при удалении мероприятия.")

    return await list_events(update, context)


async def generate_excel_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer("Генерирую отчет, пожалуйста, подождите...")

    ev_id = context.user_data['curr_ev_id']

    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT t.ticket_id, t.buyer_name, t.buyer_email, t.final_price, t.is_used, t.purchase_date, p.name
        FROM tickets t
        JOIN products p ON t.product_id = p.id
        WHERE p.event_id = %s AND t.is_active = TRUE
    """, (ev_id,))
    rows = cur.fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ID", "Name", "Email", "Price", "Used", "Date", "Type"])

    for r in rows:
        ws.append(
            [r[0], r[1], r[2], r[3], "YES" if r[4] else "NO", r[5].strftime("%Y-%m-%d %H:%M:%S") if r[5] else 'N/A',
             r[6]])

    bio = io.BytesIO()
    filename = f"report_event_{ev_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    wb.save(bio)
    bio.seek(0)

    await context.bot.send_document(chat_id=query.message.chat_id, document=InputFile(bio, filename=filename))

    return LVL5_EVENT_MENU


# --- CHECK TICKET (ОБНОВЛЕНО) ---

async def start_check_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()

    # Определяем, куда возвращаться (меню ивента или меню организации)
    if 'curr_ev_id' in context.user_data:
        back_data = "back_menu_ev"
        back_text = "🔙 Закончить проверку (Ивент)"
    else:
        back_data = "back_menu_org"
        back_text = "🔙 Закончить проверку (Орг)"

    keyboard = [[InlineKeyboardButton(back_text, callback_data=back_data)]]

    # Использование edit_message_text вместо ReplyKeyboardRemove
    await update.callback_query.edit_message_text(
        "📸 Отправьте фото QR-кода или введите ID билета:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return INPUT_CHECK_TICKET


async def process_ticket_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ticket_id = None
    if update.message.photo:
        # Скачиваем фото
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = io.BytesIO()
        await photo_file.download_to_memory(photo_bytes)
        # Читаем через OpenCV (utils.py)
        ticket_id = read_qr_code_from_image(photo_bytes.getvalue())
    elif update.message.text:
        ticket_id = update.message.text.strip().upper()

    back_data = "back_menu_ev" if 'curr_ev_id' in context.user_data else "back_menu_org"
    kb = [[InlineKeyboardButton("🔙 Назад", callback_data=back_data)]]

    if not ticket_id:
        await update.message.reply_text("❌ Код не распознан (OpenCV). Попробуйте четче или введите ID вручную:", reply_markup=InlineKeyboardMarkup(kb))
        return INPUT_CHECK_TICKET

    info = get_ticket_details(ticket_id)
    if not info:
        await update.message.reply_text("❌ Билет не найден в БД.", reply_markup=InlineKeyboardMarkup(kb))
        return INPUT_CHECK_TICKET

    curr_org = context.user_data.get('curr_org_id')
    # Проверка, что билет принадлежит нужной организации (или супер-админ)
    if curr_org and info['org_id'] != curr_org and not context.user_data.get('is_super'):
        await update.message.reply_text(
            "❌ Билет от другой организации!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return INPUT_CHECK_TICKET

    status = "✅ АКТИВЕН" if (info['active'] and not info['used']) else "❌ НЕАКТИВЕН"

    action_kb = []
    if info['active'] and not info['used']:
        action_kb.append([InlineKeyboardButton("✅ ПРОПУСТИТЬ", callback_data=f"use_{ticket_id}")])
    action_kb.append([InlineKeyboardButton("🔙 Назад", callback_data=back_data)])

    await update.message.reply_text(
        f"🔎 <b>Билет:</b> {info['id']}\nИвент: {info['event']}\nПокупатель: {info['buyer']}\nСтатус: {status}",
        reply_markup=InlineKeyboardMarkup(action_kb), parse_mode='HTML'
    )
    return INPUT_CHECK_TICKET


async def confirm_use_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    mark_ticket_used(query.data.split('_')[1])
    back_data = "back_menu_ev" if 'curr_ev_id' in context.user_data else "back_menu_org"
    await query.edit_message_text(f"✅ Билет погашен. Жду следующий...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=back_data)]]))
    return INPUT_CHECK_TICKET


# --- GLOBAL BLACKLIST (ОБНОВЛЕНО) ---

async def start_global_bl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    blacklist = get_global_blacklist()
    msg = "🚫 <b>Глобальный Черный Список</b>\n\n"
    if blacklist:
        msg += "<b>ID | Причина</b>\n"
        for user_id, reason in blacklist:
            msg += f"<code>{user_id}</code> | {escape_html(reason) or 'Нет'}\n"
    else:
        msg += "Список пуст."

    keyboard = [
        [InlineKeyboardButton("➕ Добавить пользователя", callback_data="add_global_bl")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_lvl1")]
    ]

    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return GLOBAL_BLACKLIST_MENU


async def ask_global_bl_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()

    keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data="goto_global_bl")]]

    await update.callback_query.edit_message_text(
        "Введите Telegram ID пользователя (число) для блокировки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return GLOBAL_BL_ID


async def ask_global_bl_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = int(update.message.text.strip())
        context.user_data['bl_user_id'] = user_id

        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="goto_global_bl")]]

        await update.message.reply_text(
            "Введите причину блокировки:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return GLOBAL_BL_REASON
    except ValueError:
        keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data="goto_global_bl")]]
        await update.message.reply_text(
            "❌ ID должен быть числом. Повторите ввод ID:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return GLOBAL_BL_ID


async def process_global_bl_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reason = update.message.text.strip()
    user_id = context.user_data['bl_user_id']
    admin_id = update.effective_user.id

    if add_to_global_blacklist(user_id, reason, admin_id):
        await update.message.reply_text(f"✅ Пользователь с ID <code>{user_id}</code> добавлен в Глобальный ЧС.",
                                        parse_mode='HTML')
    else:
        await update.message.reply_text(f"❌ Пользователь с ID <code>{user_id}</code> уже в списке.", parse_mode='HTML')

    return await start_global_bl(update, context)


# --- BROADCAST FLOW (ОБНОВЛЕНО) ---

async def select_broadcast_audience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    mode = query.data.split('_')[1]  # 'global' or 'org'
    context.user_data['broadcast_mode'] = mode

    org_id = context.user_data.get('curr_org_id')

    keyboard = [
        [InlineKeyboardButton("👥 Всем пользователям бота", callback_data="audience_all")],
    ]

    if mode == 'org':
        org_name = escape_html(get_org_name(org_id))
        keyboard.append([InlineKeyboardButton(f"💳 Покупателям {org_name}", callback_data="audience_buyers")])
        back_data = "back_menu_org"
    else:
        back_data = "back_lvl1"

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=back_data)])

    await query.edit_message_text("📢 Выберите аудиторию для рассылки:", reply_markup=InlineKeyboardMarkup(keyboard))
    return BROADCAST_AUDIENCE


async def ask_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    audience = query.data.split('_')[1]  # 'all' or 'buyers'
    context.user_data['broadcast_audience'] = audience

    # Кнопка отмены
    mode = context.user_data['broadcast_mode']
    back_data = "back_menu_org" if mode == 'org' else "back_lvl1"
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data=back_data)]]

    await query.edit_message_text(
        "Введите текст сообщения для рассылки (можно с HTML-разметкой):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BROADCAST_TEXT


async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message_text = update.message.text

    mode = context.user_data['broadcast_mode']
    audience = context.user_data['broadcast_audience']
    org_id = context.user_data.get('curr_org_id')

    if audience == 'all':
        user_ids = get_all_user_ids()
        target_name = "всем пользователям"
    elif audience == 'buyers' and mode == 'org':
        user_ids = get_org_buyer_ids(org_id)
        target_name = f"покупателям {escape_html(get_org_name(org_id))}"
    else:
        await update.message.reply_text("❌ Неверная аудитория.")
        return await admin_start(update, context)

    success_count = 0
    total_count = len(user_ids)

    await update.message.reply_text(f"🚀 Начинаю рассылку для {target_name} ({total_count} получателей)...")

    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=message_text, parse_mode='HTML')
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await update.message.reply_text(f"✅ Рассылка завершена! Отправлено {success_count} из {total_count} сообщений.")

    if mode == 'global':
        return await admin_start(update, context)
    else:
        return await org_menu(update, context, direct_call=True)


# --- DUMMY LOGS (остается без изменений) ---
async def view_logs_dummy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    log_content = (
        "<b>📜 Последние 50 записей логов:</b>\n\n"
        "<i>(Функция чтения файла логов не реализована.)</i>"
    )

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_lvl1")]]

    await query.edit_message_text(log_content, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return LVL1_MAIN


# --- PROMO CODE LOGIC ---

async def list_promos(update: Update, context: ContextTypes.DEFAULT_TYPE, direct_call=False) -> int:
    query = None
    if not direct_call and update.callback_query:
        query = update.callback_query
        await query.answer()

    ev_id = context.user_data['curr_ev_id']
    promos = get_event_promos(ev_id)  # Из шага 1

    msg = f"🎟 <b>Промокоды мероприятия #{ev_id}</b>\n\n"

    keyboard = []
    if not promos:
        msg += "Список пуст."
    else:
        for p in promos:
            limit_txt = f"{p['used']}/{p['limit']}" if p['limit'] > 0 else f"{p['used']}/∞"
            row_txt = f"{p['code']} (-{p['discount']}%) [{limit_txt}]"
            # Кнопка для удаления конкретного промокода
            keyboard.append([InlineKeyboardButton(f"🗑 {row_txt}", callback_data=f"del_promo_{p['code']}")])

    keyboard.append([InlineKeyboardButton("➕ Создать промокод", callback_data="create_promo")])
    keyboard.append([InlineKeyboardButton("🔙 Назад в меню", callback_data="back_menu_ev")])

    if query:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.effective_chat.send_message(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    return LVL6_PROMO_MENU


async def start_create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    kb = [[InlineKeyboardButton("🔙 Отмена", callback_data="back_promo_list")]]
    await update.callback_query.edit_message_text(
        "Введите <b>КОД</b> (латиница, цифры):",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb)
    )
    return INPUT_PROMO_CODE


async def input_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_promo_code'] = update.message.text.strip()
    kb = [[InlineKeyboardButton("🔙 Отмена", callback_data="back_promo_list")]]
    await update.message.reply_text("Введите <b>Процент скидки</b> (1-100):", reply_markup=InlineKeyboardMarkup(kb),
                                    parse_mode='HTML')
    return INPUT_PROMO_PERCENT


async def input_promo_percent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        val = int(update.message.text)
        if not (1 <= val <= 100): raise ValueError
        context.user_data['new_promo_perc'] = val

        kb = [[InlineKeyboardButton("🔙 Отмена", callback_data="back_promo_list")]]
        await update.message.reply_text("Введите <b>Лимит использования</b> (0 = безлимит):",
                                        reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
        return INPUT_PROMO_LIMIT
    except ValueError:
        await update.message.reply_text("❌ Введите число от 1 до 100.")
        return INPUT_PROMO_PERCENT


async def input_promo_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        limit = int(update.message.text)
        code = context.user_data['new_promo_code']
        perc = context.user_data['new_promo_perc']
        ev_id = context.user_data['curr_ev_id']

        if create_promo_db(code, ev_id, perc, limit):
            await update.message.reply_text(f"✅ Промокод <b>{code}</b> создан!", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Ошибка: возможно, такой код уже есть.")

        return await list_promos(update, context, direct_call=True)
    except ValueError:
        await update.message.reply_text("❌ Введите целое число.")
        return INPUT_PROMO_LIMIT


async def delete_promo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    code = query.data.split('_')[2]
    delete_promo_db(code)  # Из шага 1
    # Возвращаемся в список без смены состояния, но обновляем текст
    return await list_promos(update, context, direct_call=True)  # direct_call=True сработает как рефреш


async def ask_org_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    org_id = context.user_data['curr_org_id']
    curr_card = get_org_card(org_id) or "Не установлена"

    kb = [[InlineKeyboardButton("🔙 Отмена", callback_data="back_menu_org")]]

    await query.edit_message_text(
        f"Текущая карта: <code>{curr_card}</code>\n\nВведите новый номер карты (или телефона) для приема переводов:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='HTML'
    )
    return INPUT_ORG_CARD


async def save_org_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    card = update.message.text.strip()
    org_id = context.user_data['curr_org_id']

    update_org_card(org_id, card)  # Из db_utils

    await update.message.reply_text(f"✅ Карта обновлена: <code>{card}</code>", parse_mode='HTML')
    return await org_menu(update, context, direct_call=True)


async def start_delete_org(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    org_id = context.user_data['curr_org_id']
    org_name = get_org_name(org_id)  # Предполагается, что эта функция есть в db_utils

    keyboard = [
        [InlineKeyboardButton("🗑 ДА, УДАЛИТЬ ВСЁ", callback_data="confirm_del_org")],
        [InlineKeyboardButton("🔙 НЕТ, ОТМЕНА", callback_data="back_menu_org")]
    ]

    await query.edit_message_text(
        f"🔥 <b>УДАЛЕНИЕ ОРГАНИЗАЦИИ '{escape_html(org_name)}'</b> 🔥\n\n"
        f"Вы собираетесь удалить организацию и ВСЕ её мероприятия, билеты и настройки.\n"
        f"<b>Это действие необратимо!</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return ORG_DELETE_CONFIRM  # <-- Должно быть определено в range()


async def confirm_delete_org(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Важно: эта функция использует delete_organization_db из db_utils
    query = update.callback_query
    await query.answer()
    org_id = context.user_data['curr_org_id']

    # Предполагается, что delete_organization_db(org_id) определена в db_utils
    from db_utils import delete_organization_db
    if delete_organization_db(org_id):
        await query.edit_message_text("✅ Организация успешно удалена.")
    else:
        await query.edit_message_text("❌ Ошибка при удалении.")

    # Возврат к списку организаций
    return await list_orgs(update, context, direct_call=True)


# --- MAIN HANDLER (ОБНОВЛЕНО) ---

admin_handler = ConversationHandler(
    entry_points=[CommandHandler("admin", admin_start)],
    states={
        LVL1_MAIN: [
            CallbackQueryHandler(ask_owner_id, pattern="^add_org_owner$"),
            CallbackQueryHandler(list_orgs, pattern="^goto_lvl2_all$"),
            CallbackQueryHandler(start_global_bl, pattern="^goto_global_bl$"),
            CallbackQueryHandler(view_logs_dummy, pattern="^view_logs_dummy$"),
            CallbackQueryHandler(select_broadcast_audience, pattern="^start_global_broadcast$"),
            CallbackQueryHandler(admin_start, pattern="^back_lvl1"),
            CallbackQueryHandler(cancel_global, pattern="^admin_exit"),
            CallbackQueryHandler(start_db_reset, pattern=r'^db_reset_start$'),
        ],
        # ДОБАВЛЕН CallbackQueryHandler для отмены ввода
        INPUT_ADD_OWNER_LOGIN: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, add_owner_handler),
            CallbackQueryHandler(admin_start, pattern="^back_lvl1")
        ],

        LVL2_ORG_LIST: [
            CallbackQueryHandler(org_menu, pattern="^sel_org_"),
            CallbackQueryHandler(ask_new_org_name, pattern="^create_org"),
            CallbackQueryHandler(admin_start, pattern="^back_lvl1"),
            CallbackQueryHandler(list_orgs, pattern="^back_lvl2")  # Для возврата из ask_new_org_name
        ],
        # ДОБАВЛЕН CallbackQueryHandler для отмены ввода
        INPUT_NEW_ORG_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_org_handler),
            CallbackQueryHandler(list_orgs, pattern="^back_lvl2")
        ],

        LVL3_ORG_MENU: [
            CallbackQueryHandler(list_events, pattern="^goto_events"),
            CallbackQueryHandler(ask_admin_id, pattern="^add_admin"),
            CallbackQueryHandler(start_check_ticket, pattern="^check_ticket_org"),
            CallbackQueryHandler(select_broadcast_audience, pattern="^start_org_broadcast$"),
            CallbackQueryHandler(ask_org_card, pattern="^set_org_card$"),
            CallbackQueryHandler(list_orgs, pattern="^back_lvl2"),
            CallbackQueryHandler(org_menu, pattern="^back_menu_org")
        ],

        INPUT_ADD_ADMIN_LOGIN: [ # LOGIN
             MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_handler),
             CallbackQueryHandler(org_menu, pattern="^back_menu_org")
        ],

        INPUT_ORG_CARD: [
        MessageHandler(filters.TEXT & ~filters.COMMAND, save_org_card),
        CallbackQueryHandler(org_menu, pattern="^back_menu_org")
        ],

        ORG_DELETE_CONFIRM: [ # DELETE
             CallbackQueryHandler(confirm_delete_org, pattern="^confirm_del_org$"),
             CallbackQueryHandler(org_menu, pattern="^back_menu_org")
        ],

        # ДОБАВЛЕН CallbackQueryHandler для отмены ввода
        INPUT_ADD_ADMIN_LOGIN: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_handler),
            CallbackQueryHandler(org_menu, pattern="^back_menu_org")
        ],

        LVL4_EVENT_LIST: [
            CallbackQueryHandler(event_menu, pattern="^sel_ev_"),
            CallbackQueryHandler(start_create_event, pattern="^create_event"),
            CallbackQueryHandler(start_delete_event, pattern="^start_delete_event"),
            CallbackQueryHandler(org_menu, pattern="^back_lvl3")
        ],
        EVENT_DELETE_CONFIRM: [
            CallbackQueryHandler(confirm_delete_event, pattern="^del_ev_select_"),
            CallbackQueryHandler(list_events, pattern="^back_lvl4")
        ],
        # ДОБАВЛЕН CallbackQueryHandler для отмены ввода
        INPUT_NEW_EVENT_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, input_event_name),
            CallbackQueryHandler(list_events, pattern="^goto_events")
        ],
        # ДОБАВЛЕН CallbackQueryHandler для отмены ввода
        INPUT_NEW_EVENT_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, input_event_date),
            CallbackQueryHandler(org_menu, pattern="^back_menu_org")
        ],

        LVL5_EVENT_MENU: [
            CallbackQueryHandler(list_products_with_quantities, pattern="^list_products$"),
            CallbackQueryHandler(create_product_start, pattern="^add_product"),
            CallbackQueryHandler(list_promos, pattern="^list_promos$"),
            CallbackQueryHandler(generate_excel_report, pattern="^report_excel"),
            CallbackQueryHandler(start_check_ticket, pattern="^check_ticket_ev"),
            CallbackQueryHandler(list_events, pattern="^back_lvl4"),
            CallbackQueryHandler(event_menu, pattern="^back_menu_ev")
        ],

        # --- НОВЫЙ БЛОК ДЛЯ ПРОМОКОДОВ ---
        LVL6_PROMO_MENU: [
            CallbackQueryHandler(start_create_promo, pattern="^create_promo$"),
            CallbackQueryHandler(delete_promo_handler, pattern="^del_promo_"),
            CallbackQueryHandler(event_menu, pattern="^back_menu_ev$"),  # Назад в меню ивента
            # Если вы используете "direct_call", иногда нужен обработчик "refresh":
            CallbackQueryHandler(list_promos, pattern="^back_promo_list$")
        ],

        INPUT_PROMO_CODE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, input_promo_code),
            CallbackQueryHandler(list_promos, pattern="^back_promo_list$")
        ],
        INPUT_PROMO_PERCENT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, input_promo_percent),
            CallbackQueryHandler(list_promos, pattern="^back_promo_list$")
        ],
        INPUT_PROMO_LIMIT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, input_promo_limit),
            CallbackQueryHandler(list_promos, pattern="^back_promo_list$")
        ],
        # ---------------------------------


        # ДОБАВЛЕН CallbackQueryHandler для отмены ввода
        INPUT_NEW_PROD_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, input_prod_name),
            CallbackQueryHandler(event_menu, pattern="^back_menu_ev")
        ],
        # ДОБАВЛЕН CallbackQueryHandler для отмены ввода
        INPUT_NEW_PROD_PRICE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, input_prod_price),
            CallbackQueryHandler(event_menu, pattern="^back_menu_ev")
        ],
        # ДОБАВЛЕН CallbackQueryHandler для отмены ввода
        # admin_handlers.py (в конце файла)

        # ...
        INPUT_NEW_PROD_LIMIT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, input_prod_limit),
            CallbackQueryHandler(event_menu, pattern="^back_menu_ev")
        ],

        # НОВОЕ СОСТОЯНИЕ
        INPUT_PROD_REFUND_STATUS: [
            CallbackQueryHandler(save_new_product, pattern="^refund_"),
            CallbackQueryHandler(event_menu, pattern="^back_menu_ev")
        ],
        # ...

        # BROADCAST STATES (ОБНОВЛЕНО)
        BROADCAST_AUDIENCE: [
            CallbackQueryHandler(ask_broadcast_text, pattern="^audience_"),
            CallbackQueryHandler(admin_start, pattern="^back_lvl1$"),
            CallbackQueryHandler(org_menu, pattern="^back_menu_org$"),
        ],
        BROADCAST_TEXT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, execute_broadcast),
            # Обработка отмены рассылки (отправляет обратно в меню, из которого начали)
            CallbackQueryHandler(admin_start, pattern="^back_lvl1$"),
            CallbackQueryHandler(org_menu, pattern="^back_menu_org$"),
        ],

        # GLOBAL BLACKLIST STATES (ОБНОВЛЕНО)
        GLOBAL_BLACKLIST_MENU: [
            CallbackQueryHandler(ask_global_bl_id, pattern="^add_global_bl"),
            CallbackQueryHandler(admin_start, pattern="^back_lvl1"),
            CallbackQueryHandler(start_global_bl, pattern="^goto_global_bl")
        ],
        GLOBAL_BL_ID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, ask_global_bl_reason),
            CallbackQueryHandler(start_global_bl, pattern="^goto_global_bl")
        ],
        GLOBAL_BL_REASON: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_global_bl_add),
            CallbackQueryHandler(start_global_bl, pattern="^goto_global_bl")
        ],

        # CHECK TICKET STATES (ОБНОВЛЕНО)
        INPUT_CHECK_TICKET: [
            MessageHandler(filters.PHOTO | filters.TEXT, process_ticket_check),
            CallbackQueryHandler(confirm_use_ticket, pattern="^use_"),
            # Обработка кнопки "Закончить проверку"
            CallbackQueryHandler(org_menu, pattern="^back_menu_org"),
            CallbackQueryHandler(event_menu, pattern="^back_menu_ev"),
        ],

        DB_RESET_CONFIRM: [
            CallbackQueryHandler(confirm_db_reset, pattern="^db_reset_confirm$"),
            CallbackQueryHandler(admin_start, pattern="^back_lvl1")
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_global), CallbackQueryHandler(cancel_global, pattern='^cancel_global')]

)

