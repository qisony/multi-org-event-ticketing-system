# db_utils.py

import os
import logging
import psycopg2
from datetime import datetime
from dotenv import load_dotenv
import hashlib

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


# --- БАЗОВЫЕ ФУНКЦИИ ---

def connect_db():
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logging.error(f"DB Connection Error: {e}")
        return None


def hash_password(password: str) -> str:
    """Хеширование пароля с использованием SHA256."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def create_tables():
    conn = connect_db()
    if conn is None: return
    cursor = conn.cursor()

    queries = [
        # 1. Пользователи
        """CREATE TABLE IF NOT EXISTS users (
            chat_id BIGINT PRIMARY KEY,
            username VARCHAR(100),
            first_name VARCHAR(100),
            login VARCHAR(50) UNIQUE,
            password_hash VARCHAR(64),
            is_authenticated BOOLEAN DEFAULT FALSE,
            org_owned_count INTEGER DEFAULT 0,
            joined_at TIMESTAMP DEFAULT NOW()
        );""",

        # 2. Организации
        """CREATE TABLE IF NOT EXISTS organizations (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            bank_card VARCHAR(50),
            owner_id BIGINT REFERENCES users(chat_id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );""",

        # 2.1. ОБНОВЛЕНИЕ СУЩЕСТВУЮЩЕЙ ТАБЛИЦЫ organizations (НОВЫЙ ЗАПРОС)
        """DO $$ BEGIN
            ALTER TABLE organizations ADD COLUMN IF NOT EXISTS bank_card VARCHAR(50);
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;""",

        # 3. Админы Организаций
        """CREATE TABLE IF NOT EXISTS org_admins (
            org_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
            user_id BIGINT REFERENCES users(chat_id) ON DELETE CASCADE,
            role VARCHAR(20) NOT NULL,
            PRIMARY KEY (org_id, user_id)
        );""",

        # 4. Черный список (Org)
        """CREATE TABLE IF NOT EXISTS org_blacklist (
            org_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
            user_id BIGINT REFERENCES users(chat_id) ON DELETE CASCADE,
            reason TEXT,
            PRIMARY KEY (org_id, user_id)
        );""",

        # 5. Глобальный черный список
        """CREATE TABLE IF NOT EXISTS global_blacklist (
            user_id BIGINT PRIMARY KEY REFERENCES users(chat_id) ON DELETE CASCADE,
            reason TEXT,
            blocked_by BIGINT
        );""",

        # 6. Мероприятия
        """CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            org_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            location VARCHAR(200),
            date_str VARCHAR(50),
            is_active BOOLEAN DEFAULT TRUE
        );""",

        # 7. Продукты/Тарифы (ОБНОВЛЕНО: добавлены лимиты)
        """CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            price INTEGER NOT NULL,
            quantity_limit INTEGER DEFAULT 0, -- 0 = безлимит
            quantity_sold INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );""",

        # 8. Билеты
        """CREATE TABLE IF NOT EXISTS tickets (
            ticket_id VARCHAR(50) PRIMARY KEY,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            buyer_chat_id BIGINT REFERENCES users(chat_id) ON DELETE CASCADE,
            buyer_name VARCHAR(100),
            buyer_email VARCHAR(100),
            final_price INTEGER NOT NULL,
            is_active BOOLEAN DEFAULT FALSE, 
            is_used BOOLEAN DEFAULT FALSE,   
            purchase_date TIMESTAMP DEFAULT NOW()
        );""",

        # 9. Промокоды
        """CREATE TABLE IF NOT EXISTS promocodes (
            code VARCHAR(50) PRIMARY KEY,
            event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
            discount_percent INTEGER NOT NULL,
            usage_limit INTEGER DEFAULT 0, 
            used_count INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE
        );"""
    ]

    try:
        for q in queries:
            cursor.execute(q)
        conn.commit()
        logging.info("DB Structure updated successfully.")
    except Exception as e:
        logging.error(f"Error creating tables: {e}")
    finally:
        cursor.close()
        conn.close()


# --- ФУНКЦИЯ СБРОСА (НОВАЯ) ---
def drop_all_tables() -> bool:
    """Полностью очищает базу данных (удаляет все таблицы)."""
    conn = connect_db()
    if conn is None: return False
    cursor = conn.cursor()
    try:
        # Получаем список таблиц
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE';
        """)
        tables = [f'"{row[0]}"' for row in cursor.fetchall()]

        if tables:
            drop_command = f"DROP TABLE {', '.join(tables)} CASCADE;"
            cursor.execute(drop_command)
            conn.commit()
        return True
    except Exception as e:
        logging.error(f"Error dropping tables: {e}")
        return False
    finally:
        cursor.close()
        conn.close()


# --- USER AUTH ---
def add_user(chat_id: int, username: str | None, first_name: str | None):
    conn = connect_db()
    if not conn: return
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (chat_id, username, first_name) VALUES (%s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name;
        """, (chat_id, username, first_name))
        conn.commit()
    except Exception as e:
        logging.error(f"Add user error: {e}")
    finally:
        cursor.close()
        conn.close()


def get_user_auth_status(chat_id: int) -> bool:
    conn = connect_db()
    if not conn: return False
    cursor = conn.cursor()
    cursor.execute("SELECT is_authenticated FROM users WHERE chat_id = %s", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else False


def get_user_by_login(login: str):
    conn = connect_db()
    if not conn: return None
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, password_hash, login, is_authenticated FROM users WHERE login = %s",
                   (login.lower(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'chat_id': row[0], 'hash': row[1], 'login': row[2], 'auth': row[3]}
    return None


def register_user_db(chat_id: int, login: str, password_hash: str):
    conn = connect_db()
    if not conn: return False
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE users SET login = %s, password_hash = %s, is_authenticated = TRUE
            WHERE chat_id = %s;
        """, (login.lower(), password_hash, chat_id))
        conn.commit()
        return True
    except psycopg2.errors.UniqueViolation:
        return False
    except Exception as e:
        logging.error(f"Register user error: {e}")
        return False
    finally:
        cursor.close()
        conn.close()


def authenticate_user_db(chat_id: int):
    conn = connect_db()
    if not conn: return
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_authenticated = TRUE WHERE chat_id = %s", (chat_id,))
    conn.commit()
    conn.close()


# --- ORG & EVENT LOGIC ---

def get_active_orgs():
    conn = connect_db()
    if not conn: return []
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM organizations ORDER BY id ASC;")
    rows = cursor.fetchall()
    conn.close()
    return [{'id': r[0], 'name': r[1]} for r in rows]


def get_org_events_public(org_id: int):
    conn = connect_db()
    if not conn: return []
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, date_str FROM events WHERE org_id = %s AND is_active = TRUE", (org_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{'id': r[0], 'name': r[1], 'date': r[2]} for r in rows]


def get_event_products(event_id: int):
    conn = connect_db()
    if not conn: return []
    cursor = conn.cursor()
    # Возвращаем лимиты и проданное количество
    cursor.execute(
        "SELECT id, name, description, price, quantity_limit, quantity_sold FROM products WHERE event_id = %s",
        (event_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{'id': r[0], 'name': r[1], 'desc': r[2], 'price': r[3], 'limit': r[4], 'sold': r[5]} for r in rows]


def get_product_info(product_id: int):
    conn = connect_db()
    if not conn: return None
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.name, p.price, e.name, e.org_id 
        FROM products p 
        JOIN events e ON p.event_id = e.id 
        WHERE p.id = %s
    """, (product_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'name': row[1], 'price': row[2], 'event_name': row[3], 'org_id': row[4]}
    return None


def check_product_availability(product_id: int) -> tuple[bool, int]:
    """Возвращает (доступно_ли, остаток). Если лимит 0, возвращает (True, -1)."""
    conn = connect_db()
    if not conn: return (False, 0)
    cursor = conn.cursor()
    cursor.execute("SELECT quantity_limit, quantity_sold FROM products WHERE id = %s", (product_id,))
    row = cursor.fetchone()
    conn.close()

    if not row: return (False, 0)

    limit, sold = row[0], row[1]
    if limit == 0: return (True, 9999)  # Безлимит

    remaining = limit - sold
    return (remaining > 0, remaining)


def create_ticket_record(ticket_id, product_id, chat_id, name, email, price):
    """Создает билет и увеличивает счетчик продаж."""
    conn = connect_db()
    if not conn: return False
    cursor = conn.cursor()
    try:
        # Проверка доступности еще раз внутри транзакции (для надежности)
        cursor.execute("SELECT quantity_limit, quantity_sold FROM products WHERE id = %s FOR UPDATE", (product_id,))
        row = cursor.fetchone()
        if not row: return False
        limit, sold = row[0], row[1]

        if limit > 0 and sold >= limit:
            return False  # Закончились

        cursor.execute("""
            INSERT INTO tickets (ticket_id, product_id, buyer_chat_id, buyer_name, buyer_email, final_price, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, FALSE)
        """, (ticket_id, product_id, chat_id, name, email, price))

        # Инкремент
        cursor.execute("UPDATE products SET quantity_sold = quantity_sold + 1 WHERE id = %s", (product_id,))

        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Create ticket error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# --- ADMIN/ORG UTILS ---
def create_organization(name: str, owner_id: int):
    conn = connect_db()
    if not conn: return None
    cursor = conn.cursor()
    try:
        # 1. Создаем организацию и получаем ID (в рамках текущей транзакции)
        cursor.execute("INSERT INTO organizations (name, owner_id) VALUES (%s, %s) RETURNING id", (name, owner_id))
        row = cursor.fetchone()
        if not row:
            raise Exception("Failed to insert organization")
        org_id = row[0]

        # 2. Сразу добавляем владельца в таблицу админов (используя ТОТ ЖЕ курсор)
        # Мы не вызываем add_org_admin(), чтобы не открывать новое соединение
        cursor.execute("""
            INSERT INTO org_admins (org_id, user_id, role) 
            VALUES (%s, %s, 'org_owner')
            ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role
        """, (org_id, owner_id))

        # 3. Увеличиваем счетчик (используя ТОТ ЖЕ курсор)
        cursor.execute("UPDATE users SET org_owned_count = org_owned_count + 1 WHERE chat_id = %s", (owner_id,))

        # 4. Фиксируем всё вместе
        conn.commit()
        return org_id
    except Exception as e:
        conn.rollback()
        logging.error(f"Create org error: {e}")
        return None
    finally:
        cursor.close()
        conn.close()


def add_org_admin(org_id, user_id, role):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        add_user(user_id, None, None)  # Ensure user exists
        cursor.execute("""
            INSERT INTO org_admins (org_id, user_id, role) 
            VALUES (%s, %s, %s)
            ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role
        """, (org_id, user_id, role))
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Add admin error: {e}")
        return False
    finally:
        cursor.close()
        conn.close()


def create_product(event_id: int, name: str, price: int, quantity_limit: int):
    conn = connect_db()
    if not conn: return None
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO products (event_id, name, price, quantity_limit) 
            VALUES (%s, %s, %s, %s) 
            RETURNING id
        """, (event_id, name, price, quantity_limit))
        prod_id = cursor.fetchone()[0]
        conn.commit()
        return prod_id
    except Exception as e:
        logging.error(f"Create product error: {e}")
        conn.rollback()
        return None
    finally:
        cursor.close()
        conn.close()


def delete_event(event_id: int) -> bool:
    conn = connect_db()
    if not conn: return False
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM events WHERE id = %s", (event_id,))
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Delete event error: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


def get_org_name(org_id: int) -> str:
    conn = connect_db()
    if not conn: return f"ID {org_id}"
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM organizations WHERE id = %s", (org_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else f"ID {org_id}"


def get_user_org_count(user_id: int) -> int:
    conn = connect_db()
    if not conn: return 0
    cursor = conn.cursor()
    cursor.execute("SELECT org_owned_count FROM users WHERE chat_id = %s", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0


def increment_user_org_count(user_id: int, increment: int = 1):
    conn = connect_db()
    if not conn: return
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET org_owned_count = org_owned_count + %s WHERE chat_id = %s", (increment, user_id))
    conn.commit()
    conn.close()


def get_admin_roles(user_id: int):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT org_id, role FROM org_admins WHERE user_id = %s", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def is_blacklisted(org_id: int, user_id: int) -> bool:
    conn = connect_db()
    if not conn: return False
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM org_blacklist WHERE org_id = %s AND user_id = %s", (org_id, user_id))
    if cursor.fetchone():
        conn.close()
        return True
    cursor.execute("SELECT 1 FROM global_blacklist WHERE user_id = %s", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None


def activate_ticket_db(ticket_id: str):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET is_active = TRUE WHERE ticket_id = %s", (ticket_id,))
    conn.commit()
    conn.close()


def get_ticket_details(ticket_id: str):
    conn = connect_db()
    if not conn: return None
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.ticket_id, t.buyer_name, t.final_price, t.is_active, t.is_used, 
               p.name as product_name, e.name as event_name, e.org_id
        FROM tickets t
        JOIN products p ON t.product_id = p.id
        JOIN events e ON p.event_id = e.id
        WHERE t.ticket_id = %s
    """, (ticket_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            'id': row[0], 'buyer': row[1], 'price': row[2],
            'active': row[3], 'used': row[4],
            'product': row[5], 'event': row[6], 'org_id': row[7]
        }
    return None


def mark_ticket_used(ticket_id: str):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET is_used = TRUE WHERE ticket_id = %s", (ticket_id,))
    conn.commit()
    conn.close()


def add_to_global_blacklist(user_id: int, reason: str, admin_id: int):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO global_blacklist (user_id, reason, blocked_by) 
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING;
        """, (user_id, reason, admin_id))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()


def get_global_blacklist():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, reason FROM global_blacklist")
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_all_user_ids():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM users WHERE is_authenticated = TRUE;")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_org_buyer_ids(org_id: int):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT t.buyer_chat_id 
        FROM tickets t
        JOIN products p ON t.product_id = p.id
        JOIN events e ON p.event_id = e.id
        WHERE e.org_id = %s AND t.is_active = TRUE
    """, (org_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def increment_promo_usage(code):
    """Увеличивает счетчик использования промокода."""
    conn = connect_db()
    if not conn: return
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = %s", (code,))
        conn.commit()
    except Exception as e:
        logging.error(f"Promo usage increment error: {e}")
    finally:
        cursor.close()
        conn.close()


# --- db_utils.py (ДОБАВИТЬ В КОНЕЦ) ---

def get_event_promos(event_id: int):
    conn = connect_db()
    if not conn: return []
    cursor = conn.cursor()
    cursor.execute("""
        SELECT code, discount_percent, usage_limit, used_count 
        FROM promocodes 
        WHERE event_id = %s
    """, (event_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{'code': r[0], 'discount': r[1], 'limit': r[2], 'used': r[3]} for r in rows]

def create_promo_db(code: str, event_id: int, discount: int, limit: int):
    conn = connect_db()
    if not conn: return False
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO promocodes (code, event_id, discount_percent, usage_limit)
            VALUES (%s, %s, %s, %s)
        """, (code.upper(), event_id, discount, limit))
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Create promo error: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def delete_promo_db(code: str):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM promocodes WHERE code = %s", (code,))
    conn.commit()
    conn.close()

def add_bank_card_column():
    """Добавляет колонку bank_card, если её нет."""
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS bank_card VARCHAR(50) DEFAULT NULL;")
        conn.commit()
    except Exception as e:
        logging.error(f"Migration error: {e}")
    finally:
        conn.close()

def update_org_card(org_id: int, card_number: str):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE organizations SET bank_card = %s WHERE id = %s", (card_number, org_id))
    conn.commit()
    conn.close()

def get_org_card(org_id: int):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT bank_card FROM organizations WHERE id = %s", (org_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def find_promo(code: str, event_id: int):
    conn = connect_db()
    if not conn: return None
    cursor = conn.cursor()
    # Проверяем: совпадает код, id ивента, и (лимит=0 ИЛИ использовано < лимит)
    cursor.execute("""
        SELECT code, discount_percent 
        FROM promocodes 
        WHERE code = %s AND event_id = %s 
        AND (usage_limit = 0 OR used_count < usage_limit)
    """, (code.upper(), event_id))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {'code': row[0], 'discount': row[1]}
    return None

# db_utils.py (ДОБАВИТЬ В КОНЕЦ ФАЙЛА или к функциям администрирования)

def delete_organization_db(org_id: int) -> bool:
    """Удаляет организацию и все связанные данные (каскадно)."""
    conn = connect_db()
    if not conn: return False
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM organizations WHERE id = %s", (org_id,))
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Delete Org Error: {e}")
        return False
    finally:
        cursor.close()
        conn.close()


# db_utils.py (ДОБАВИТЬ ЭТИ ФУНКЦИИ)

def set_org_card(org_id: int, card_number: str) -> bool:
    """Устанавливает номер карты для организации."""
    conn = connect_db()
    if not conn: return False
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE organizations SET bank_card = %s WHERE id = %s", (card_number, org_id))
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Set Org Card Error: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def get_org_card(org_id: int) -> str | None:
    """Получает номер карты для организации."""
    conn = connect_db()
    if not conn: return None
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT bank_card FROM organizations WHERE id = %s", (org_id,))
        result = cursor.fetchone()
        return result[0] if result and result[0] else None
    except Exception as e:
        logging.error(f"Get Org Card Error: {e}")
        return None
    finally:
        cursor.close()
        conn.close()