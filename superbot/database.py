import aiosqlite
from config import DB_NAME
from datetime import datetime
import random
import string
import asyncio
from contextlib import asynccontextmanager


@asynccontextmanager
async def get_db():
    """Получить подключение к БД с правильными настройками WAL и таймаутом"""
    db = await aiosqlite.connect(DB_NAME)
    try:
        await db.execute("PRAGMA busy_timeout=30000")  # 30 секунд таймаут
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        yield db
    finally:
        await db.close()

# Глобальный пул соединений
_db_pool = None
_pool_size = 20  # Количество соединений в пуле
_semaphore = None  # Семафор для ограничения одновременных подключений


class DBPool:
    """Пул соединений к базе данных"""
    def __init__(self, db_name: str, pool_size: int = 20):
        self.db_name = db_name
        self.pool_size = pool_size
        self.connections = asyncio.Queue(maxsize=pool_size)
        self.semaphore = asyncio.Semaphore(pool_size)
        self._initialized = False

    async def init_pool(self):
        """Инициализация пула соединений"""
        if self._initialized:
            return

        for _ in range(self.pool_size):
            conn = await aiosqlite.connect(self.db_name)
            # Включаем WAL режим для лучшей параллельной работы
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            # Увеличиваем таймаут для высоконагруженных операций (30 секунд)
            await conn.execute("PRAGMA busy_timeout=30000")
            await self.connections.put(conn)

        self._initialized = True

    async def get_connection(self):
        """Получить соединение из пула"""
        await self.semaphore.acquire()
        return await self.connections.get()

    async def return_connection(self, conn):
        """Вернуть соединение в пул"""
        await self.connections.put(conn)
        self.semaphore.release()

    async def close_pool(self):
        """Закрыть все соединения в пуле"""
        while not self.connections.empty():
            conn = await self.connections.get()
            await conn.close()


async def get_db_pool():
    """Получить или создать пул соединений"""
    global _db_pool
    if _db_pool is None:
        _db_pool = DBPool(DB_NAME, _pool_size)
        await _db_pool.init_pool()
    return _db_pool


# Кэш для часто запрашиваемых данных
_user_cache = {}
_product_cache = {}
_cache_ttl = 300  # Время жизни кэша в секундах (5 минут для production)


async def init_db():
    """Инициализация базы данных"""
    # Инициализируем пул соединений
    await get_db_pool()

    async with get_db() as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                uid INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                balance REAL DEFAULT 0,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                referral_code TEXT
            )
        """)

        # Миграция: добавляем uid если его нет
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]

        if 'uid' not in column_names:
            # Добавляем колонку uid без UNIQUE (ограничение добавим позже через индекс)
            await db.execute("ALTER TABLE users ADD COLUMN uid INTEGER")

            # Присваиваем uid всем существующим пользователям
            cursor = await db.execute("SELECT user_id FROM users ORDER BY registered_at")
            users = await cursor.fetchall()
            for idx, (user_id,) in enumerate(users, start=1):
                await db.execute("UPDATE users SET uid = ? WHERE user_id = ?", (idx, user_id))

            await db.commit()

            # Создаем уникальный индекс для uid
            try:
                await db.execute("CREATE UNIQUE INDEX idx_users_uid ON users(uid)")
                await db.commit()
            except:
                pass  # Индекс уже существует

        # Таблица товаров
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                game TEXT,
                subcategory TEXT,
                in_stock BOOLEAN DEFAULT 1,
                image_file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица заказов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product_id INTEGER,
                product_name TEXT,
                amount REAL,
                game TEXT,
                pickup_code TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        """)

        # Миграция: добавляем pickup_code если его нет
        cursor = await db.execute("PRAGMA table_info(orders)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]

        if 'pickup_code' not in column_names:
            await db.execute("ALTER TABLE orders ADD COLUMN pickup_code TEXT")
            await db.commit()

        # Миграции для платежей и Mini App
        if 'supercell_id' not in column_names:
            await db.execute("ALTER TABLE orders ADD COLUMN supercell_id TEXT")
            await db.commit()

        if 'transaction_id' not in column_names:
            await db.execute("ALTER TABLE orders ADD COLUMN transaction_id TEXT")
            await db.commit()

        # Миграция: добавляем image_path для поддержки статических изображений
        cursor = await db.execute("PRAGMA table_info(products)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]

        if 'image_path' not in column_names:
            await db.execute("ALTER TABLE products ADD COLUMN image_path TEXT")
            await db.commit()

        # Обновляем статус по умолчанию на pending для новых заказов
        # Старые заказы со статусом completed останутся как есть

        # Таблица реферальных ссылок
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referral_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица переходов по реферальным ссылкам
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referral_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referral_code TEXT NOT NULL,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        await db.commit()

        # ============================================
        # PRODUCTION INDEXES - добавляем индексы для оптимизации
        # ============================================
        indexes = [
            # Индекс для быстрого поиска заказов по статусу
            "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)",
            # Индекс для быстрого поиска заказов пользователя
            "CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)",
            # Композитный индекс для фильтрации товаров
            "CREATE INDEX IF NOT EXISTS idx_products_game_subcategory ON products(game, subcategory)",
            # Индекс для поиска товаров в наличии
            "CREATE INDEX IF NOT EXISTS idx_products_in_stock ON products(in_stock)",
            # Индекс для реферальных визитов
            "CREATE INDEX IF NOT EXISTS idx_referral_visits_code ON referral_visits(referral_code)",
            # Индекс для поиска по дате создания заказа
            "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)",
            # Индекс для transaction_id (платежи)
            "CREATE INDEX IF NOT EXISTS idx_orders_transaction_id ON orders(transaction_id)",
        ]

        for index_sql in indexes:
            try:
                await db.execute(index_sql)
            except Exception:
                pass  # Индекс уже существует

        await db.commit()


async def get_or_create_user(user_id: int, username: str = None, first_name: str = None):
    """Получить или создать пользователя (с retry для высокой нагрузки)"""
    max_retries = 5

    for attempt in range(max_retries):
        try:
            async with get_db() as db:
                # Проверяем существование пользователя
                async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                    user = await cursor.fetchone()

                if user:
                    # Обновляем последнюю активность
                    await db.execute(
                        "UPDATE users SET last_activity = datetime('now') WHERE user_id = ?",
                        (user_id,)
                    )
                    await db.commit()
                    _user_cache[user_id] = {'data': user, 'time': datetime.now()}
                    return user

                # Пользователя нет — создаём с retry на случай конфликта uid
                cursor = await db.execute("SELECT COALESCE(MAX(uid), 0) + 1 FROM users")
                next_uid = (await cursor.fetchone())[0]

                await db.execute(
                    """INSERT INTO users (user_id, uid, username, first_name, last_activity)
                       VALUES (?, ?, ?, ?, datetime('now'))""",
                    (user_id, next_uid, username, first_name)
                )
                await db.commit()

                # Инвалидируем кэш
                if user_id in _user_cache:
                    del _user_cache[user_id]

                # Возвращаем созданного пользователя
                async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                    result = await cursor.fetchone()
                    _user_cache[user_id] = {'data': result, 'time': datetime.now()}
                    return result

        except Exception as e:
            error_msg = str(e).lower()
            if "database is locked" in error_msg or "unique constraint" in error_msg:
                if attempt < max_retries - 1:
                    # Небольшая случайная задержка перед retry
                    await asyncio.sleep(0.1 * (attempt + 1) + random.random() * 0.1)
                    continue
            raise

    # Если все попытки исчерпаны, пробуем просто вернуть пользователя
    async with get_db() as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()


async def get_user_uid(user_id: int) -> int:
    """Получить UID пользователя (использует пул соединений)"""
    pool = await get_db_pool()
    db = await pool.get_connection()
    try:
        async with db.execute("SELECT uid FROM users WHERE user_id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None
    finally:
        await pool.return_connection(db)


async def search_user_by_uid(uid: int):
    """Найти пользователя по UID (использует пул соединений)"""
    pool = await get_db_pool()
    db = await pool.get_connection()
    try:
        cursor = await db.execute("SELECT user_id FROM users WHERE uid = ?", (uid,))
        result = await cursor.fetchone()
        return result[0] if result else None
    finally:
        await pool.return_connection(db)


async def get_user_balance(user_id: int) -> float:
    """Получить баланс пользователя (оптимизированная версия с кэшем)"""
    # Проверяем кэш
    if user_id in _user_cache:
        cache_entry = _user_cache[user_id]
        cache_age = (datetime.now() - cache_entry['time']).total_seconds()
        if cache_age < _cache_ttl:
            # Баланс находится по индексу 4 в кортеже пользователя
            return cache_entry['data'][4] if cache_entry['data'] else 0.0

    pool = await get_db_pool()
    db = await pool.get_connection()

    try:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else 0.0
    finally:
        await pool.return_connection(db)


async def get_user_orders(user_id: int):
    """Получить заказы пользователя"""
    async with get_db() as db:
        async with db.execute("""
            SELECT o.id, p.name, o.amount, o.status, o.created_at
            FROM orders o
            JOIN products p ON o.product_id = p.id
            WHERE o.user_id = ?
            ORDER BY o.created_at DESC
            LIMIT 10
        """, (user_id,)) as cursor:
            return await cursor.fetchall()


async def get_user_orders_stats(user_id: int):
    """Получить статистику заказов пользователя
    Возвращает: {'count': количество, 'total': общая сумма}
    Считает оплаченные и завершённые заказы (paid + completed)
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT COUNT(*), COALESCE(SUM(amount), 0)
            FROM orders
            WHERE user_id = ? AND status IN ('paid', 'completed')
        """, (user_id,)) as cursor:
            result = await cursor.fetchone()
            return {'count': result[0] if result else 0, 'total': result[1] if result else 0.0}


async def get_all_products(category: str = None):
    """Получить все товары или товары по legacy-категории."""
    async with get_db() as db:
        if category:
            # Legacy-режим: раньше использовалось поле category.
            # Поддерживаем старые callback'и через game/subcategory.
            query = """
                SELECT * FROM products
                WHERE in_stock = 1
                  AND (game = ? OR subcategory = ?)
            """
            async with db.execute(query, (category, category)) as cursor:
                return await cursor.fetchall()
        else:
            query = "SELECT * FROM products WHERE in_stock = 1"
            async with db.execute(query) as cursor:
                return await cursor.fetchall()


async def add_sample_products():
    """Добавить примеры товаров (для тестирования)"""
    async with get_db() as db:
        # Проверяем, есть ли уже товары
        async with db.execute("SELECT COUNT(*) FROM products") as cursor:
            count = await cursor.fetchone()
            if count[0] > 0:
                return

        # Добавляем примеры товаров
        products = [
            ("💎 Донат 100 руб", "Донат на сумму 100 рублей", 100, "legacy", "donate"),
            ("💎 Донат 500 руб", "Донат на сумму 500 рублей", 500, "legacy", "donate"),
            ("💎 Донат 1000 руб", "Донат на сумму 1000 рублей", 1000, "legacy", "donate"),
            ("🎮 Игровая валюта 100", "100 единиц игровой валюты", 50, "legacy", "currency"),
            ("🎮 Игровая валюта 500", "500 единиц игровой валюты", 200, "legacy", "currency"),
            ("🎁 Подарок #1", "Специальный подарок", 150, "legacy", "gifts"),
        ]

        await db.executemany(
            "INSERT INTO products (name, description, price, game, subcategory) VALUES (?, ?, ?, ?, ?)",
            products
        )
        await db.commit()


async def update_user_balance(user_id: int, amount: float):
    """Добавить сумму к балансу пользователя (использует пул соединений)"""
    pool = await get_db_pool()
    db = await pool.get_connection()
    try:
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await db.commit()
        # Инвалидируем кэш пользователя
        if user_id in _user_cache:
            del _user_cache[user_id]
    finally:
        await pool.return_connection(db)


async def get_product_by_id(product_id: int):
    """Получить товар по ID (оптимизированная версия с кэшем)"""
    # Проверяем кэш товаров
    if product_id in _product_cache:
        cache_entry = _product_cache[product_id]
        cache_age = (datetime.now() - cache_entry['time']).total_seconds()
        if cache_age < _cache_ttl:
            return cache_entry['data']

    pool = await get_db_pool()
    db = await pool.get_connection()

    try:
        async with db.execute("SELECT * FROM products WHERE id = ?", (product_id,)) as cursor:
            result = await cursor.fetchone()
            # Кэшируем товар
            _product_cache[product_id] = {'data': result, 'time': datetime.now()}
            return result
    finally:
        await pool.return_connection(db)


def generate_pickup_code() -> str:
    """Генерировать код получения формата XXX-XXX-XXX"""
    def random_segment():
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))

    return f"{random_segment()}-{random_segment()}-{random_segment()}"


async def create_order(user_id: int, product_id: int, amount: float, product_name: str = None, game: str = None, pickup_code: str = None, supercell_id: str = None):
    """Создать заказ"""
    if pickup_code is None:
        pickup_code = generate_pickup_code()

    async with get_db() as db:
        await db.execute(
            "INSERT INTO orders (user_id, product_id, product_name, amount, game, pickup_code, status, supercell_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, product_id, product_name, amount, game, pickup_code, "pending", supercell_id)
        )
        await db.commit()

        # Получаем ID созданного заказа
        cursor = await db.execute("SELECT last_insert_rowid()")
        order_id = (await cursor.fetchone())[0]

        return order_id, pickup_code


async def create_order_without_balance(user_id: int, product_id: int, supercell_id: str):
    """Создать заказ без списания баланса. Возвращает (success, message, order_id, pickup_code)"""
    # Получаем товар
    product = await get_product_by_id(product_id)
    if not product:
        return False, "Товар не найден", None, None

    # product: (id, name, description, price, game, subcategory, in_stock, created_at, image_file_id)
    product_name = product[1]
    price = product[3]
    game = product[4]

    # Создаем заказ
    order_id, pickup_code = await create_order(
        user_id, product_id, price, product_name, game, supercell_id=supercell_id
    )

    return True, "Заказ успешно создан!", order_id, pickup_code


async def purchase_with_balance(user_id: int, product_id: int):
    """Купить товар с баланса. Возвращает (success, message, order_id, pickup_code)"""
    # Получаем товар
    product = await get_product_by_id(product_id)
    if not product:
        return False, "Товар не найден", None, None

    # product: (id, name, description, price, game, subcategory, in_stock, created_at)
    product_name = product[1]
    price = product[3]
    game = product[4]

    # Получаем баланс пользователя
    balance = await get_user_balance(user_id)

    if balance < price:
        return False, f"Недостаточно средств. Нужно {price:.2f} ₽, у вас {balance:.2f} ₽", None, None

    pool = await get_db_pool()
    db = await pool.get_connection()

    try:
        # Снимаем деньги с баланса
        new_balance = balance - price
        await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        await db.commit()

        # Инвалидируем кэш пользователя
        if user_id in _user_cache:
            del _user_cache[user_id]

        # Создаем заказ
        order_id, pickup_code = await create_order(user_id, product_id, price, product_name, game)

        return True, "Покупка успешно завершена!", order_id, pickup_code
    finally:
        await pool.return_connection(db)


# === Функции для статистики ===

async def get_stats_users(period: str = "all") -> dict:
    """Получить статистику по пользователям
    period: 'today', 'yesterday', '7days', 'all'
    """
    async with get_db() as db:
        if period == "today":
            query = "SELECT COUNT(*) FROM users WHERE DATE(last_activity) = DATE('now')"
        elif period == "yesterday":
            query = "SELECT COUNT(*) FROM users WHERE DATE(last_activity) = DATE('now', '-1 day')"
        elif period == "7days":
            query = "SELECT COUNT(*) FROM users WHERE DATE(last_activity) >= DATE('now', '-7 days')"
        else:  # all
            query = "SELECT COUNT(*) FROM users"

        async with db.execute(query) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else 0


async def get_stats_revenue(period: str = "all") -> float:
    """Получить статистику по обороту
    period: 'today', 'yesterday', '7days', 'all'
    Считает ВСЕ заказы кроме cancelled и pending_payment (неоплаченных СБП)
    """
    async with get_db() as db:
        # Учитываем все заказы кроме отменённых и ожидающих оплаты СБП
        if period == "today":
            query = "SELECT SUM(amount) FROM orders WHERE DATE(created_at) = DATE('now') AND (status IS NULL OR status NOT IN ('cancelled', 'pending_payment'))"
        elif period == "yesterday":
            query = "SELECT SUM(amount) FROM orders WHERE DATE(created_at) = DATE('now', '-1 day') AND (status IS NULL OR status NOT IN ('cancelled', 'pending_payment'))"
        elif period == "7days":
            query = "SELECT SUM(amount) FROM orders WHERE DATE(created_at) >= DATE('now', '-7 days') AND (status IS NULL OR status NOT IN ('cancelled', 'pending_payment'))"
        else:  # all
            query = "SELECT SUM(amount) FROM orders WHERE status IS NULL OR status NOT IN ('cancelled', 'pending_payment')"

        async with db.execute(query) as cursor:
            result = await cursor.fetchone()
            return result[0] if result and result[0] else 0.0


async def get_stats_sales_by_game(game: str, period: str = "all") -> dict:
    """Получить статистику продаж по игре
    game: 'brawlstars', 'clashroyale', 'clashofclans'
    period: 'today', 'yesterday', '7days', 'all'
    Возвращает {'count': количество, 'revenue': сумма}
    """
    async with get_db() as db:
        if period == "today":
            date_filter = "AND DATE(created_at) = DATE('now')"
        elif period == "yesterday":
            date_filter = "AND DATE(created_at) = DATE('now', '-1 day')"
        elif period == "7days":
            date_filter = "AND DATE(created_at) >= DATE('now', '-7 days')"
        else:  # all
            date_filter = ""

        # Считаем все заказы кроме отменённых и ожидающих оплаты
        query_count = f"SELECT COUNT(*) FROM orders WHERE game = ? AND (status IS NULL OR status NOT IN ('cancelled', 'pending_payment')) {date_filter}"
        query_revenue = f"SELECT SUM(amount) FROM orders WHERE game = ? AND (status IS NULL OR status NOT IN ('cancelled', 'pending_payment')) {date_filter}"

        async with db.execute(query_count, (game,)) as cursor:
            count = await cursor.fetchone()
            count = count[0] if count else 0

        async with db.execute(query_revenue, (game,)) as cursor:
            revenue = await cursor.fetchone()
            revenue = revenue[0] if revenue and revenue[0] else 0.0

        return {'count': count, 'revenue': revenue}


async def get_orders_stats_debug() -> dict:
    """Получить отладочную статистику по всем заказам - разбивка по статусам"""
    async with get_db() as db:
        # Общее количество и сумма всех заказов
        async with db.execute("SELECT COUNT(*), SUM(amount) FROM orders") as cursor:
            result = await cursor.fetchone()
            total_count = result[0] if result else 0
            total_sum = result[1] if result and result[1] else 0

        # Разбивка по статусам
        async with db.execute("""
            SELECT
                COALESCE(status, 'NULL') as status,
                COUNT(*) as cnt,
                SUM(amount) as total
            FROM orders
            GROUP BY status
            ORDER BY cnt DESC
        """) as cursor:
            rows = await cursor.fetchall()
            by_status = {row[0]: {'count': row[1], 'sum': row[2] or 0} for row in rows}

        # Разбивка по играм
        async with db.execute("""
            SELECT
                COALESCE(game, 'NULL') as game,
                COUNT(*) as cnt,
                SUM(amount) as total
            FROM orders
            WHERE status IS NULL OR status NOT IN ('cancelled', 'pending_payment')
            GROUP BY game
        """) as cursor:
            rows = await cursor.fetchall()
            by_game = {row[0]: {'count': row[1], 'sum': row[2] or 0} for row in rows}

        return {
            'total_count': total_count,
            'total_sum': total_sum,
            'by_status': by_status,
            'by_game': by_game
        }


async def get_all_users_ids():
    """Получить ID всех пользователей для рассылки"""
    async with get_db() as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
            return [user[0] for user in users]

# === Функции для управления товарами ===

async def add_product(name: str, description: str, price: float, game: str, subcategory: str, image_file_id: str = None):
    """Добавить новый товар"""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO products (name, description, price, game, subcategory, in_stock, image_file_id) VALUES (?, ?, ?, ?, ?, 1, ?)",
            (name, description, price, game, subcategory, image_file_id)
        )
        await db.commit()

        # Возвращаем ID созданного товара
        async with db.execute("SELECT last_insert_rowid()") as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None


async def get_products_by_game_and_subcategory(game: str = None, subcategory: str = None):
    """Получить товары по игре и подкатегории"""
    async with get_db() as db:
        if game and subcategory:
            query = "SELECT * FROM products WHERE game = ? AND subcategory = ? AND in_stock = 1"
            async with db.execute(query, (game, subcategory)) as cursor:
                return await cursor.fetchall()
        elif game:
            query = "SELECT * FROM products WHERE game = ? AND in_stock = 1"
            async with db.execute(query, (game,)) as cursor:
                return await cursor.fetchall()
        else:
            query = "SELECT * FROM products WHERE in_stock = 1"
            async with db.execute(query) as cursor:
                return await cursor.fetchall()


async def update_product(product_id: int, name: str = None, description: str = None, price: float = None, image_file_id: str = None):
    """Обновить товар"""
    async with get_db() as db:
        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if price is not None:
            updates.append("price = ?")
            params.append(price)
        if image_file_id is not None:
            updates.append("image_file_id = ?")
            params.append(image_file_id)

        if updates:
            query = f"UPDATE products SET {', '.join(updates)} WHERE id = ?"
            params.append(product_id)
            await db.execute(query, params)
            await db.commit()
            return True
        return False


async def delete_product(product_id: int):
    """Удалить товар (мягкое удаление - устанавливаем in_stock = 0)"""
    async with get_db() as db:
        await db.execute("UPDATE products SET in_stock = 0 WHERE id = ?", (product_id,))
        await db.commit()
        return True


async def get_all_products_admin():
    """Получить все товары для админа (включая удаленные)"""
    async with get_db() as db:
        query = "SELECT * FROM products ORDER BY game, subcategory, name"
        async with db.execute(query) as cursor:
            return await cursor.fetchall()


# === Функции для работы с реферальными ссылками ===

async def create_referral_link(code: str, name: str):
    """Создать реферальную ссылку"""
    async with get_db() as db:
        try:
            await db.execute(
                "INSERT INTO referral_links (code, name) VALUES (?, ?)",
                (code, name)
            )
            await db.commit()
            return True
        except:
            return False


async def get_all_referral_links():
    """Получить все реферальные ссылки"""
    async with get_db() as db:
        async with db.execute("SELECT code, name, created_at FROM referral_links ORDER BY created_at DESC") as cursor:
            return await cursor.fetchall()


async def get_referral_link_by_code(code: str):
    """Получить реферальную ссылку по коду"""
    async with get_db() as db:
        async with db.execute("SELECT code, name, created_at FROM referral_links WHERE code = ?", (code,)) as cursor:
            return await cursor.fetchone()


async def delete_referral_link(code: str):
    """Удалить реферальную ссылку"""
    async with get_db() as db:
        await db.execute("DELETE FROM referral_links WHERE code = ?", (code,))
        await db.commit()
        return True


async def register_referral_visit(referral_code: str, user_id: int):
    """Зарегистрировать переход по реферальной ссылке"""
    async with get_db() as db:
        # Проверяем, есть ли уже запись для этого пользователя с этим кодом
        async with db.execute(
            "SELECT id FROM referral_visits WHERE referral_code = ? AND user_id = ?",
            (referral_code, user_id)
        ) as cursor:
            existing = await cursor.fetchone()

        if not existing:
            await db.execute(
                "INSERT INTO referral_visits (referral_code, user_id) VALUES (?, ?)",
                (referral_code, user_id)
            )
            await db.commit()

        # Сохраняем код в профиле пользователя
        await db.execute(
            "UPDATE users SET referral_code = ? WHERE user_id = ?",
            (referral_code, user_id)
        )
        await db.commit()


async def get_referral_stats(referral_code: str):
    """Получить статистику по реферальной ссылке"""
    async with get_db() as db:
        # Получаем количество переходов
        async with db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM referral_visits WHERE referral_code = ?",
            (referral_code,)
        ) as cursor:
            result = await cursor.fetchone()
            total_users = result[0] if result else 0

        # Получаем переходы за сегодня
        async with db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM referral_visits WHERE referral_code = ? AND DATE(created_at) = DATE('now')",
            (referral_code,)
        ) as cursor:
            result = await cursor.fetchone()
            today_users = result[0] if result else 0

        # Получаем переходы за 7 дней
        async with db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM referral_visits WHERE referral_code = ? AND DATE(created_at) >= DATE('now', '-7 days')",
            (referral_code,)
        ) as cursor:
            result = await cursor.fetchone()
            week_users = result[0] if result else 0

        # Получаем статистику по заказам пользователей, пришедших по этой ссылке
        async with db.execute("""
            SELECT COUNT(*), COALESCE(SUM(o.amount), 0)
            FROM orders o
            JOIN users u ON o.user_id = u.user_id
            WHERE u.referral_code = ? AND o.status = 'completed'
        """, (referral_code,)) as cursor:
            result = await cursor.fetchone()
            total_orders = result[0] if result else 0
            total_revenue = result[1] if result else 0.0

        # Получаем заказы за сегодня
        async with db.execute("""
            SELECT COUNT(*), COALESCE(SUM(o.amount), 0)
            FROM orders o
            JOIN users u ON o.user_id = u.user_id
            WHERE u.referral_code = ? AND o.status = 'completed' AND DATE(o.created_at) = DATE('now')
        """, (referral_code,)) as cursor:
            result = await cursor.fetchone()
            today_orders = result[0] if result else 0
            today_revenue = result[1] if result else 0.0

        # Получаем заказы за 7 дней
        async with db.execute("""
            SELECT COUNT(*), COALESCE(SUM(o.amount), 0)
            FROM orders o
            JOIN users u ON o.user_id = u.user_id
            WHERE u.referral_code = ? AND o.status = 'completed' AND DATE(o.created_at) >= DATE('now', '-7 days')
        """, (referral_code,)) as cursor:
            result = await cursor.fetchone()
            week_orders = result[0] if result else 0
            week_revenue = result[1] if result else 0.0

        return {
            'users_total': total_users,
            'users_today': today_users,
            'users_week': week_users,
            'orders_total': total_orders,
            'orders_today': today_orders,
            'orders_week': week_orders,
            'revenue_total': total_revenue,
            'revenue_today': today_revenue,
            'revenue_week': week_revenue
        }


# ===== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ =====

async def get_all_users(limit=50, offset=0):
    """Получить список всех пользователей с пагинацией"""
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT user_id, username, first_name, balance, registered_at
            FROM users
            ORDER BY registered_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        return await cursor.fetchall()


async def get_users_count():
    """Получить общее количество пользователей"""
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def search_user_by_id(user_id):
    """Найти пользователя по ID"""
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT user_id, username, first_name, balance, registered_at
            FROM users
            WHERE user_id = ?
        """, (user_id,))
        return await cursor.fetchone()


async def get_user_full_stats(user_id):
    """Получить полную статистику пользователя"""
    async with get_db() as db:
        # Получаем информацию о пользователе
        cursor = await db.execute("""
            SELECT user_id, uid, username, first_name, balance, registered_at, referral_code
            FROM users
            WHERE user_id = ?
        """, (user_id,))
        user = await cursor.fetchone()

        if not user:
            return None

        # Получаем статистику заказов
        cursor = await db.execute("""
            SELECT COUNT(*), COALESCE(SUM(amount), 0)
            FROM orders
            WHERE user_id = ?
        """, (user_id,))
        orders_data = await cursor.fetchone()

        return {
            'user_id': user[0],
            'uid': user[1],
            'username': user[2],
            'first_name': user[3],
            'balance': user[4],
            'registered_at': user[5],
            'referral_code': user[6],
            'orders_count': orders_data[0] if orders_data else 0,
            'total_spent': orders_data[1] if orders_data else 0
        }


async def set_user_balance(user_id: int, new_balance: float):
    """Установить баланс пользователя (абсолютное значение)"""
    pool = await get_db_pool()
    db = await pool.get_connection()
    try:
        await db.execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (new_balance, user_id)
        )
        await db.commit()
        # Инвалидируем кэш пользователя
        if user_id in _user_cache:
            del _user_cache[user_id]
    finally:
        await pool.return_connection(db)


async def add_to_user_balance(user_id, amount):
    """Добавить к балансу пользователя"""
    async with get_db() as db:
        await db.execute("""
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
        """, (amount, user_id))
        await db.commit()



# === Функции для работы с заказами ===

async def get_user_orders(user_id: int, limit: int = 20):
    """Получить заказы пользователя для истории"""
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT id, product_name, amount, status, pickup_code, supercell_id, created_at, game
            FROM orders
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit))
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "product_name": row[1],
                "amount": row[2],
                "status": row[3],
                "pickup_code": row[4],
                "supercell_id": row[5],
                "created_at": row[6],
                "game": row[7]
            }
            for row in rows
        ]


async def get_pending_orders():
    """Получить все незакрытые заказы (pending, pending_payment, paid)"""
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT id, user_id, product_name, amount, pickup_code, created_at, status
            FROM orders
            WHERE status IN ('pending', 'pending_payment', 'paid')
            ORDER BY created_at DESC
        """)
        return await cursor.fetchall()


async def get_order_by_id(order_id: int):
    """Получить заказ по ID"""
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT id, user_id, product_id, product_name, amount, game, pickup_code, status, created_at
            FROM orders
            WHERE id = ?
        """, (order_id,))
        return await cursor.fetchone()


async def confirm_order(order_id: int):
    """Подтвердить заказ"""
    async with get_db() as db:
        await db.execute("""
            UPDATE orders
            SET status = 'completed'
            WHERE id = ?
        """, (order_id,))
        await db.commit()


async def cancel_order(order_id: int):
    """Отменить заказ и вернуть деньги пользователю"""
    async with get_db() as db:
        # Получаем информацию о заказе
        cursor = await db.execute("""
            SELECT user_id, amount
            FROM orders
            WHERE id = ?
        """, (order_id,))
        order = await cursor.fetchone()

        if not order:
            return False

        user_id, amount = order

        # Возвращаем деньги на баланс
        await db.execute("""
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
        """, (amount, user_id))

        # Обновляем статус заказа
        await db.execute("""
            UPDATE orders
            SET status = 'cancelled'
            WHERE id = ?
        """, (order_id,))

        await db.commit()
        return True


#============================================
#ФУНКЦИИ ДЛЯ РАБОТЫ С ПЛАТЕЖАМИ WATA.PRO
#============================================

async def save_payment_transaction(order_id: int, transaction_id: str):
    """Сохраняет transaction_id от wata.pro для заказа"""
    async with get_db() as db:
        await db.execute("""
            UPDATE orders
            SET
                transaction_id = ?,
                status = CASE
                    WHEN status IN ('paid', 'completed', 'cancelled') THEN status
                    ELSE 'pending_payment'
                END
            WHERE id = ?
        """, (transaction_id, order_id))
        await db.commit()


async def get_pending_payments():
    """Получает список заказов с незавершёнными платежами"""
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT id, transaction_id, user_id, product_name, amount
            FROM orders
            WHERE status = 'pending_payment' AND transaction_id IS NOT NULL
        """)
        rows = await cursor.fetchall()
        return [
            {
                "order_id": row[0],
                "transaction_id": row[1],
                "user_id": row[2],
                "product_name": row[3],
                "amount": row[4]
            }
            for row in rows
        ]


async def update_order_payment_status(order_id: int, status: str):
    """
    Обновляет статус платежа заказа

    status: 'paid', 'payment_failed', 'pending_payment'
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        async with get_db() as db:
            # Сначала проверим текущий статус
            cursor = await db.execute("SELECT status FROM orders WHERE id = ?", (order_id,))
            old_status = await cursor.fetchone()
            logger.info(f"[UPDATE_STATUS] Order {order_id}: OLD status = {old_status}")

            # Обновляем
            await db.execute("""
                UPDATE orders
                SET status = ?
                WHERE id = ?
            """, (status, order_id))
            await db.commit()

            # Проверим что обновилось
            cursor = await db.execute("SELECT status FROM orders WHERE id = ?", (order_id,))
            new_status = await cursor.fetchone()
            logger.info(f"[UPDATE_STATUS] Order {order_id}: NEW status = {new_status}")

            if new_status and new_status[0] == status:
                logger.info(f"[UPDATE_STATUS] Order {order_id} successfully updated to '{status}'")
            else:
                logger.error(f"[UPDATE_STATUS] Order {order_id} UPDATE FAILED! Expected '{status}', got {new_status}")
    except Exception as e:
        logger.error(f"[UPDATE_STATUS] Exception updating order {order_id}: {e}", exc_info=True)
        raise


async def get_order_by_transaction_id(transaction_id: str):
    """Получает заказ по transaction_id от wata.pro"""
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT id, user_id, product_id, product_name, amount, status, pickup_code, supercell_id
            FROM orders
            WHERE transaction_id = ?
        """, (transaction_id,))
        row = await cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "user_id": row[1],
                "product_id": row[2],
                "product_name": row[3],
                "amount": row[4],
                "status": row[5],
                "pickup_code": row[6],
                "supercell_id": row[7]
            }
        return None
