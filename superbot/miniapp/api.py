"""
FastAPI сервер для Mini App
Подключается к существующей базе данных бота
"""

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from contextlib import asynccontextmanager
import re
import sys
import os
import aiohttp
from io import BytesIO
import logging
import time
import httpx
import hashlib
import hmac
import asyncio
from urllib.parse import parse_qsl, unquote

ENABLE_PAYMENT_CHECKER = os.getenv("ENABLE_PAYMENT_CHECKER", "false").lower() == "true"

# Production режим - определяем по окружению
IS_PRODUCTION = os.getenv("PRODUCTION", "false").lower() == "true"

# Настройка логирования для production
LOG_LEVEL = logging.INFO if IS_PRODUCTION else logging.DEBUG
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'

logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/api_debug.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Добавляем родительскую директорию в путь для импорта database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import (
    get_user_full_stats,
    get_products_by_game_and_subcategory,
    get_product_by_id,
    create_order_without_balance,
    get_all_products_admin,
    get_or_create_user,
    get_user_uid,
    get_pending_payments,
    update_order_payment_status,
    save_payment_transaction,
    get_order_by_transaction_id,
    get_user_orders,
    get_order_by_id
)
from config import BOT_TOKEN, ADMIN_IDS, SUPPORT_URL


#============================================
#ФОНОВАЯ ЗАДАЧА ДЛЯ ПРОВЕРКИ ПЛАТЕЖЕЙ
#============================================

#Флаг для остановки фоновой задачи
payment_checker_running = False

async def check_pending_payments_task():
    """
    Фоновая задача для проверки статуса незавершённых платежей.
    Запускается каждые 60 секунд.

    Нужна на случай если webhook от wata.pro не дошёл.
    """
    global payment_checker_running
    payment_checker_running = True

    logger.info("Payment checker task started")

    while payment_checker_running:
        try:
            #Получаем список незавершённых платежей из базы
            pending = await get_pending_payments()

            if pending:
                logger.info(f"Checking {len(pending)} pending payments...")

                #Раскомментировать когда будет API токен wata.pro:
                #from wata_payment import WataPaymentClient
                #client = WataPaymentClient()
                #updated = await client.check_pending_payments(pending)
                #
                #for tx in updated:
                #    if tx["status"] == "Paid":
                #        #Обновляем статус заказа
                #        await update_order_payment_status(tx["order_id"], "paid")
                #        #Уведомляем админа (получить order info и отправить)
                #        logger.info(f"Order {tx['order_id']} marked as paid via checker")
                #    elif tx["status"] == "Declined":
                #        await update_order_payment_status(tx["order_id"], "payment_failed")
                #        logger.info(f"Order {tx['order_id']} payment declined")

        except Exception as e:
            logger.error(f"Payment checker error: {e}", exc_info=True)

        #Ждём 60 секунд до следующей проверки
        await asyncio.sleep(60)

    logger.info("Payment checker task stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if ENABLE_PAYMENT_CHECKER:
        logger.warning("⚠️ Payment checker ENABLED")
        task = asyncio.create_task(check_pending_payments_task())

        yield

        global payment_checker_running
        payment_checker_running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    else:
        logger.error("❌ PAYMENT CHECKER DISABLED — ENABLE_PAYMENT_CHECKER=false")
        logger.error("❌ SBP / payment webhooks are OFF")
        yield



app = FastAPI(title="SuperCell Shop Mini App API", lifespan=lifespan)


# ===== КЕШИРОВАНИЕ =====
class SimpleCache:
    """Простой in-memory кеш с TTL"""

    def __init__(self):
        self._cache = {}
        self._timestamps = {}

    def get(self, key: str, ttl: int = 300):
        """Получить значение из кеша (TTL в секундах)"""
        if key in self._cache:
            if time.time() - self._timestamps[key] < ttl:
                return self._cache[key]
            else:
                # Кеш устарел
                del self._cache[key]
                del self._timestamps[key]
        return None

    def set(self, key: str, value):
        """Сохранить значение в кеш"""
        self._cache[key] = value
        self._timestamps[key] = time.time()

    def invalidate(self, pattern: str = None):
        """Очистить кеш (весь или по паттерну)"""
        if pattern is None:
            self._cache.clear()
            self._timestamps.clear()
        else:
            keys_to_delete = [k for k in self._cache if pattern in k]
            for k in keys_to_delete:
                del self._cache[k]
                del self._timestamps[k]


# Глобальный кеш
cache = SimpleCache()
CACHE_TTL = int(os.getenv("PRODUCTS_CACHE_TTL", 300))  # 5 минут по умолчанию


# ===== ЗАЩИТА ОТ DDOS =====
class RateLimiter:
    """Rate limiter для защиты от DDoS"""

    def __init__(self, requests_per_minute: int = 60, burst_limit: int = 10):
        self._requests = {}  # IP -> список timestamps
        self._blocked = {}   # IP -> время блокировки
        self.rpm = requests_per_minute
        self.burst = burst_limit
        self.block_duration = 300  # 5 минут блокировки

    def is_allowed(self, ip: str) -> bool:
        """Проверить, разрешён ли запрос"""
        now = time.time()

        # Проверяем блокировку
        if ip in self._blocked:
            if now < self._blocked[ip]:
                return False
            else:
                del self._blocked[ip]

        # Очищаем старые записи
        if ip in self._requests:
            self._requests[ip] = [t for t in self._requests[ip] if now - t < 60]
        else:
            self._requests[ip] = []

        # Проверяем лимиты
        recent = self._requests[ip]

        # Burst check (слишком много запросов за секунду)
        last_second = [t for t in recent if now - t < 1]
        if len(last_second) >= self.burst:
            self._blocked[ip] = now + self.block_duration
            logger.warning(f"IP {ip} blocked for burst ({len(last_second)} req/sec)")
            return False

        # Rate limit check
        if len(recent) >= self.rpm:
            self._blocked[ip] = now + self.block_duration
            logger.warning(f"IP {ip} blocked for rate limit ({len(recent)} req/min)")
            return False

        # Записываем запрос
        self._requests[ip].append(now)
        return True

    def get_blocked_count(self) -> int:
        """Количество заблокированных IP"""
        now = time.time()
        return sum(1 for t in self._blocked.values() if t > now)


# Глобальный rate limiter
rate_limiter = RateLimiter(
    requests_per_minute=120,  # 120 запросов в минуту на IP
    burst_limit=20            # Не более 20 запросов в секунду
)


def validate_telegram_init_data(init_data: str):
    """
    Проверяет подпись initData от Telegram Web App.
    Возвращает данные пользователя если подпись валидна, иначе None.
    """
    try:
        # Парсим initData
        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))

        logger.debug(f"Parsed initData keys: {list(parsed_data.keys())}")

        if 'hash' not in parsed_data:
            logger.warning("No hash in initData")
            return None

        received_hash = parsed_data.pop('hash')

        # Создаём строку для проверки (ключи в алфавитном порядке)
        data_check_string = '\n'.join(
            f'{k}={v}' for k, v in sorted(parsed_data.items())
        )

        logger.debug(f"Data check string: {data_check_string[:100]}...")

        # Создаём secret_key = HMAC_SHA256("WebAppData", bot_token)
        # ВАЖНО: порядок аргументов - сначала "WebAppData" как ключ, затем bot_token как сообщение
        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        # Вычисляем hash
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        # Сравниваем хеши - PRODUCTION: строгая проверка
        if not hmac.compare_digest(calculated_hash, received_hash):
            logger.warning(f"Invalid Telegram hash: calculated {calculated_hash[:20]}..., received {received_hash[:20]}...")
            return None  # ВАЖНО: В production отклоняем невалидные запросы

        # Парсим user из initData
        import json
        if 'user' in parsed_data:
            user_data = json.loads(unquote(parsed_data['user']))
            logger.info(f"Validated user: {user_data.get('id')}")
            return user_data

        return parsed_data

    except Exception as e:
        logger.error(f"Error validating initData: {e}", exc_info=True)
        return None


async def get_validated_user(x_telegram_init_data: str = Header(None, alias="X-Telegram-Init-Data")) -> dict:
    """
    Dependency для проверки авторизации через Telegram.
    """
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Missing Telegram initData")

    user_data = validate_telegram_init_data(x_telegram_init_data)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram initData")

    return user_data


async def send_telegram_message(chat_id: int, text: str, reply_markup: dict = None):
    """Отправить сообщение через Telegram Bot API"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        # При использовании json=payload, reply_markup передаётся как dict
        # httpx автоматически сериализует всё в JSON
        payload["reply_markup"] = reply_markup

    logger.info(f"Sending Telegram message to {chat_id}, text length: {len(text)}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, json=payload)
            response_text = response.text[:500] if response.text else ""

            if response.status_code != 200:
                logger.error(f"Telegram API error: {response.status_code} - {response_text}")
                return False

            logger.info(f"Telegram message sent successfully to {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send telegram message to {chat_id}: {e}")
            return False


async def notify_admins_about_order(user_id: int, order_id: int, pickup_code: str, product_name: str, price: float, supercell_id: str):
    """Отправить уведомление администраторам о новом заказе"""
    user_uid = await get_user_uid(user_id)

    admin_message = (
        f"🛒 <b>Новая продажа (Mini App)!</b>\n\n"
        f"📦 Товар: {product_name}\n"
        f"💰 Сумма: {price:.0f} ₽\n"
        f"👤 Покупатель: UID #{user_uid}\n"
        f"🎮 Supercell ID: {supercell_id}\n"
        f"🔑 Код получения: {pickup_code}"
    )

    reply_markup = {
        "inline_keyboard": [
            [{"text": "👤 Перейти к пользователю", "callback_data": f"admin_goto_user_{user_id}"}],
            [
                {"text": "✅ Подтвердить", "callback_data": f"admin_confirm_order_{order_id}"},
                {"text": "❌ Отменить", "callback_data": f"admin_cancel_order_{order_id}"}
            ]
        ]
    }

    for admin_id in ADMIN_IDS:
        await send_telegram_message(admin_id, admin_message, reply_markup)


async def notify_user_about_purchase(user_id: int, product_name: str, pickup_code: str):
    """Отправить уведомление пользователю о покупке"""
    purchase_message = (
        f"🎉 <b>Поздравляем с покупкой!</b>\n\n"
        f"📦 Ваш товар: {product_name}\n"
        f"🔑 Код получения: <code>{pickup_code}</code>\n\n"
        f"⚠️ Важно: никому не передавайте код получения.\n\n"
        f"Для получения товара отправьте данный код поддержке"
    )

    reply_markup = {
        "inline_keyboard": [
            [{"text": "📞 Поддержка", "url": SUPPORT_URL}]
        ]
    }

    await send_telegram_message(user_id, purchase_message, reply_markup)

# Middleware для логирования и защиты от DDoS


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"

    # Rate limiting check
    if not rate_limiter.is_allowed(client_ip):
        logger.warning(f"⛔ BLOCKED {request.method} {request.url.path} from {client_ip}")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please try again later."}
        )

    logger.info(f"→ {request.method} {request.url.path} from {client_ip}")

    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.info(f"← {request.method} {request.url.path} - Status: {response.status_code} - Time: {process_time:.3f}s")
        return response
    except Exception as e:
        logger.error(f"✗ {request.method} {request.url.path} - Error: {e}", exc_info=True)
        raise

# CORS middleware - PRODUCTION: ограничиваем origins
# Разрешаем только Telegram Web App и наш домен
ALLOWED_ORIGINS = [
    "https://web.telegram.org",
    "https://t.me",
    "https://supercellshop.xyz",
    "https://www.supercellshop.xyz",
    # Для локальной разработки (убрать в production)
    # "http://localhost:8000",
    # "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data", "Authorization"],
    max_age=86400,  # Кэш preflight запросов на 24 часа
)

# GZip сжатие для ответов > 500 байт
app.add_middleware(GZipMiddleware, minimum_size=500)


# ============================================
# ГЛОБАЛЬНЫЕ ОБРАБОТЧИКИ ОШИБОК
# ============================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Глобальный обработчик необработанных исключений"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    # В production не раскрываем детали ошибки
    error_message = "Внутренняя ошибка сервера" if IS_PRODUCTION else str(exc)
    return JSONResponse(
        status_code=500,
        content={"error": error_message, "success": False}
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Обработчик HTTP исключений"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "success": False}
    )


from pydantic import ValidationError

@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """Обработчик ошибок валидации Pydantic"""
    logger.warning(f"Validation error: {exc}")
    return JSONResponse(
        status_code=422,
        content={"error": "Ошибка валидации данных", "details": exc.errors(), "success": False}
    )

# Модели данных с валидацией
class PurchaseRequest(BaseModel):
    user_id: int = Field(..., gt=0, description="Telegram user ID")
    product_id: int = Field(..., gt=0, description="Product ID")
    supercell_id: str = Field(..., min_length=5, max_length=100, description="Supercell account email")

    @field_validator('supercell_id')
    @classmethod
    def validate_email(cls, v: str) -> str:
        # Проверка формата email
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        v = v.strip()
        if not re.match(email_pattern, v):
            raise ValueError('Некорректный формат email')
        return v.lower()


# ===== ROUTES =====

@app.get("/")
async def root():
    """Главная страница Mini App"""
    return FileResponse("templates/index.html")


@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
    """Получить информацию о пользователе"""
    logger.debug(f"Getting user stats for user_id: {user_id}")
    try:
        user_stats = await get_user_full_stats(user_id)

        if not user_stats:
            logger.warning(f"User {user_id} not found")
            raise HTTPException(status_code=404, detail="User not found")

        logger.debug(f"User {user_id} stats: orders={user_stats['orders_count']}")
        return {
            "uid": user_stats['uid'],
            "orders_count": user_stats['orders_count'],
            "total_spent": user_stats['total_spent']
        }
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}", exc_info=True)
        raise


@app.get("/api/user/{user_id}/orders")
async def get_user_orders_api(user_id: int, limit: int = 20):
    """Получить историю заказов пользователя

    ВАЖНО: pickup_code возвращается ТОЛЬКО для оплаченных заказов (paid, completed).
    Для неоплаченных заказов pickup_code скрыт для предотвращения мошенничества.
    """
    logger.debug(f"Getting orders for user_id: {user_id}")
    try:
        orders = await get_user_orders(user_id, limit)

        # БЕЗОПАСНОСТЬ: Скрываем pickup_code для неоплаченных заказов
        # Код получения показывается ТОЛЬКО после подтверждения оплаты
        safe_statuses = ['paid', 'completed']

        for order in orders:
            if order.get('status') not in safe_statuses:
                # Скрываем код для неоплаченных заказов
                order['pickup_code'] = None

        logger.info(f"Found {len(orders)} orders for user {user_id}")
        return orders
    except Exception as e:
        logger.error(f"Error getting orders for user {user_id}: {e}", exc_info=True)
        raise


@app.get("/api/search")
async def search_products(q: str, game: str = None):
    """Умный поиск товаров с санитизацией входных данных"""
    # SECURITY: Санитизация и ограничение длины запроса
    q = q.strip()[:100]  # Максимум 100 символов
    q = re.sub(r'[<>"\';\\]', '', q)  # Удаляем опасные символы

    if game:
        game = game.strip()[:50]
        # Валидация game - только разрешённые значения
        allowed_games = ['brawlstars', 'clashroyale', 'clashofclans']
        if game not in allowed_games:
            game = None

    logger.debug(f"Search query: '{q}', game: {game}")

    if len(q) < 2:
        return []

    try:
        #Получаем все товары
        all_products = await get_products_by_game_and_subcategory(game, None)

        q_lower = q.lower()
        results = []

        for p in all_products:
            product_name = (p[1] or "").lower()
            product_desc = (p[2] or "").lower()
            product_game = (p[4] or "").lower()

            #Вычисляем релевантность
            score = 0

            #Точное совпадение в названии
            if q_lower in product_name:
                score += 100
                if product_name.startswith(q_lower):
                    score += 50

            #Совпадение в описании
            if q_lower in product_desc:
                score += 30

            #Совпадение по игре
            game_names = {
                "brawl": "brawlstars",
                "браул": "brawlstars",
                "бравл": "brawlstars",
                "clash": "clashroyale",
                "клеш": "clashroyale",
                "royale": "clashroyale",
                "рояль": "clashroyale",
                "coc": "clashofclans",
                "кок": "clashofclans",
                "clans": "clashofclans"
            }
            for keyword, game_id in game_names.items():
                if keyword in q_lower and product_game == game_id:
                    score += 40

            #Поиск по ключевым словам
            keywords = {
                "гем": ["gems", "гемы"],
                "gem": ["gems", "гемы"],
                "пасс": ["bp", "pass"],
                "pass": ["bp", "pass"],
                "акци": ["akcii", "акция"],
                "скидк": ["akcii", "скидка"]
            }
            for kw, subcats in keywords.items():
                if kw in q_lower:
                    product_subcat = (p[5] or "").lower()
                    if product_subcat in subcats or any(s in product_name for s in subcats):
                        score += 25

            if score > 0:
                results.append({
                    "id": p[0],
                    "name": p[1],
                    "description": p[2],
                    "price": p[3],
                    "game": p[4],
                    "subcategory": p[5],
                    "image_file_id": p[7] if len(p) > 7 else None,
                    "image_path": p[8] if len(p) > 8 else None,
                    "score": score
                })

        #Сортируем по релевантности
        results.sort(key=lambda x: x["score"], reverse=True)

        #Убираем score из результата
        for r in results:
            del r["score"]

        logger.info(f"Search '{q}' found {len(results)} results")
        return results[:20]  #Максимум 20 результатов

    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        return []


@app.get("/api/products")
async def get_products(game: str = None, subcategory: str = None):
    """Получить список товаров (с кешированием)"""
    cache_key = f"products:{game}:{subcategory}"

    # Проверяем кеш
    cached = cache.get(cache_key, CACHE_TTL)
    if cached is not None:
        logger.debug(f"Cache HIT for {cache_key}")
        return cached

    logger.debug(f"Cache MISS for {cache_key}")

    try:
        products = await get_products_by_game_and_subcategory(game, subcategory)
        logger.info(f"Found {len(products)} products for game={game}, subcategory={subcategory}")

        result = [
            {
                "id": p[0],
                "name": p[1],
                "description": p[2],
                "price": p[3],
                "game": p[4],
                "subcategory": p[5],
                "in_stock": p[6],
                "image_file_id": p[7] if len(p) > 7 else None,
                "image_path": p[8] if len(p) > 8 else None,
            }
            for p in products
        ]

        # Сохраняем в кеш
        cache.set(cache_key, result)
        logger.debug(f"Cached {len(result)} products")

        return result
    except Exception as e:
        logger.error(f"Error getting products: {e}", exc_info=True)
        raise


@app.get("/api/product/{product_id}")
async def get_product(product_id: int):
    """Получить информацию о товаре"""
    product = await get_product_by_id(product_id)

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return {
        "id": product[0],
        "name": product[1],
        "description": product[2],
        "price": product[3],
        "game": product[4],
        "subcategory": product[5],
        "in_stock": product[6],
        "image_file_id": product[7] if len(product) > 7 else None,
        "image_path": product[8] if len(product) > 8 else None
    }


@app.post("/api/purchase")
async def purchase_product(
    request: PurchaseRequest,
    x_telegram_init_data: str = Header(None, alias="X-Telegram-Init-Data")
):
    """Создать заказ на товар (требует авторизации через Telegram)"""
    # Проверяем авторизацию через Telegram
    if not x_telegram_init_data:
        logger.warning("Purchase attempt without Telegram initData")
        raise HTTPException(status_code=401, detail="Требуется авторизация через Telegram")

    user_data = validate_telegram_init_data(x_telegram_init_data)
    if not user_data:
        logger.warning("Purchase attempt with invalid Telegram initData")
        raise HTTPException(status_code=401, detail="Неверная авторизация Telegram")

    # Проверяем, что user_id в запросе совпадает с user_id из initData
    telegram_user_id = user_data.get('id')
    if telegram_user_id and telegram_user_id != request.user_id:
        logger.warning(f"User ID mismatch: request={request.user_id}, telegram={telegram_user_id}")
        raise HTTPException(status_code=403, detail="Несоответствие пользователя")

    logger.info(f"Purchase request (verified): user_id={request.user_id}, product_id={request.product_id}, supercell_id={request.supercell_id}")

    success, message, order_id, pickup_code = await create_order_without_balance(
        request.user_id,
        request.product_id,
        request.supercell_id
    )

    if not success:
        logger.warning(f"Purchase failed: {message}")
        return {
            "success": False,
            "message": message
        }

    # Сразу устанавливаем статус "pending_payment" - ожидает оплаты
    await update_order_payment_status(order_id, "pending_payment")
    logger.info(f"Order {order_id} created with status pending_payment")

    # ВАЖНО: Уведомления НЕ отправляются здесь!
    # Они будут отправлены только после подтверждения оплаты через webhook
    # или при ручном подтверждении админом.
    # Код получения (pickup_code) также НЕ показывается до оплаты.

    return {
        "success": True,
        "message": "Заказ создан. Ожидает оплаты.",
        "order_id": order_id,
        "payment_required": True
        # pickup_code НЕ возвращаем - он будет отправлен после оплаты
    }


# ============================================
# ИНТЕГРАЦИЯ WATA.PRO — PAYMENT FORM (БЕЗ H2H API)
# ============================================
#
# ВАЖНО: H2H API недоступен, webhooks не работают.
# Используем ТОЛЬКО редирект на платёжную форму.
# Подтверждение оплаты — через админа вручную.
#
# ============================================

from wata_form import (
    create_payment_form_url_async,
    WATA_API_TOKEN,
)
from fastapi.responses import HTMLResponse, RedirectResponse

# URL для возврата в Mini App
MINIAPP_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://supercellshop.xyz")


@app.get("/api/wata-status")
async def wata_status():
    """
    Диагностика конфигурации wata.pro.
    Проверяет наличие токена и настройки.
    """
    token = WATA_API_TOKEN
    token_set = bool(token and token != "ВСТАВЬ_ТОКЕН_СЮДА" and len(token) > 20)

    return {
        "token_configured": token_set,
        "token_length": len(token) if token else 0,
        "token_preview": f"{token[:20]}..." if token and len(token) > 20 else "(not set or invalid)",
        "sandbox_mode": os.getenv("WATA_SANDBOX", "false"),
        "webhook_base_url": os.getenv("WEBHOOK_BASE_URL", "not set"),
        "api_base": "https://api-sandbox.wata.pro" if os.getenv("WATA_SANDBOX", "false").lower() == "true" else "https://api.wata.pro"
    }


class CreatePaymentRequest(BaseModel):
    """Запрос на создание платежа"""
    order_id: int
    user_id: int


@app.post("/api/create-sbp-payment")
async def create_sbp_payment(
    request_data: CreatePaymentRequest,
    request: Request,
    x_telegram_init_data: str = Header(None, alias="X-Telegram-Init-Data")
):
    """
    Создаёт ссылку на платёжную форму wata.pro.

    БЕЗ H2H API — просто генерируем URL для редиректа.
    """
    # Проверка Telegram
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Нет Telegram initData")

    user_data = validate_telegram_init_data(x_telegram_init_data)
    if not user_data:
        raise HTTPException(status_code=401, detail="Неверная авторизация")

    # Получаем заказ из БД
    order = await get_order_by_id(request_data.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    # order: (id, user_id, product_id, product_name, amount, game, pickup_code, status, created_at)
    order_id = order[0]
    amount = order[4]
    product_name = order[3] or "Товар"

    # Генерируем ссылку на платёжную форму через API wata.pro
    result = await create_payment_form_url_async(
        amount=amount,
        order_id=f"order_{order_id}",
        description=f"Заказ #{order_id}: {product_name}"
    )

    if not result.success:
        logger.error(f"Failed to create payment URL: {result.error}")
        return {
            "success": False,
            "error": result.error or "Не удалось создать ссылку на оплату"
        }

    logger.info(f"Payment URL created for order {order_id}: {result.payment_url[:50]}...")

    # Обновляем статус заказа на "pending_payment"
    await update_order_payment_status(order_id, "pending_payment")

    return {
        "success": True,
        "payment_url": result.payment_url,  # Ссылка на форму wata.pro
        "order_id": order_id
    }


# ============================================
# SUCCESS / FAIL PAGES
# ============================================
# В ЛК wata.pro указываем простые URL без параметров:
# Success Page: https://supercellshop.xyz/payment/success
# Fail Page: https://supercellshop.xyz/payment/fail
#
# Wata.pro сам добавит параметры при редиректе (orderId, transactionId и т.д.)
# ============================================

@app.get("/payment/success")
async def payment_success(
    orderId: str = None,
    order_id: str = None,
    transactionId: str = None,
    amount: float = None
):
    """
    Страница успешной оплаты.

    Wata.pro редиректит сюда после успешной оплаты.
    Параметры могут быть: orderId, transactionId, amount
    """
    # Пробуем получить order_id из разных параметров
    order_id_value = orderId or order_id

    logger.info(f"Payment success page: orderId={orderId}, order_id={order_id}, transactionId={transactionId}")

    # Извлекаем числовой order_id
    numeric_order_id = None
    if order_id_value:
        if order_id_value.startswith("order_"):
            try:
                numeric_order_id = int(order_id_value.replace("order_", ""))
            except ValueError:
                pass
        else:
            try:
                numeric_order_id = int(order_id_value)
            except ValueError:
                pass

    # ВАЖНО: НЕ обновляем статус заказа здесь!
    # Статус обновляется ТОЛЬКО через webhook от wata.pro
    # Success page может быть открыта напрямую или без реальной оплаты
    # Доверяем только webhook для подтверждения платежа
    if numeric_order_id:
        logger.info(f"Success page visited for order {numeric_order_id} (status NOT changed, waiting for webhook)")

    html = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Платёж обрабатывается</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
                color: white;
            }}
            .container {{
                background: rgba(255,255,255,0.1);
                border-radius: 20px;
                padding: 40px 30px;
                max-width: 400px;
                width: 100%;
                text-align: center;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255,255,255,0.2);
            }}
            .icon {{ font-size: 64px; margin-bottom: 20px; }}
            h1 {{ font-size: 24px; margin-bottom: 15px; color: #f59e0b; }}
            .info {{
                color: rgba(255,255,255,0.8);
                margin-bottom: 25px;
                font-size: 15px;
                line-height: 1.5;
            }}
            .order-id {{
                background: rgba(255,255,255,0.1);
                padding: 12px 20px;
                border-radius: 10px;
                margin-bottom: 25px;
                font-family: monospace;
                font-size: 14px;
            }}
            .btn {{
                display: inline-block;
                padding: 14px 28px;
                background: linear-gradient(135deg, #3b82f6, #2563eb);
                border: none;
                border-radius: 12px;
                color: white;
                font-size: 16px;
                font-weight: 600;
                text-decoration: none;
                transition: transform 0.2s;
            }}
            .btn:hover {{ transform: scale(1.02); }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">⏳</div>
            <h1>Платёж обрабатывается</h1>
            <p class="info">
                Ваш платёж отправлен на проверку.<br>
                После подтверждения оплаты вы получите<br>
                <b>уведомление с кодом получения в Telegram</b>.
            </p>
            {"<div class='order-id'>Заказ: #" + str(numeric_order_id) + "</div>" if numeric_order_id else ""}
            <a href="https://t.me" class="btn">Вернуться в Telegram</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/payment/fail")
async def payment_fail(
    orderId: str = None,
    order_id: str = None,
    error: str = None
):
    """
    Страница неуспешной оплаты.
    """
    order_id_value = orderId or order_id

    logger.info(f"Payment fail page: orderId={orderId}, order_id={order_id}, error={error}")

    # Извлекаем числовой order_id
    numeric_order_id = None
    if order_id_value:
        if order_id_value.startswith("order_"):
            try:
                numeric_order_id = int(order_id_value.replace("order_", ""))
            except ValueError:
                pass
        else:
            try:
                numeric_order_id = int(order_id_value)
            except ValueError:
                pass

    # Обновляем статус заказа
    if numeric_order_id:
        await update_order_payment_status(numeric_order_id, "payment_failed")

    html = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Оплата не прошла</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
                color: white;
            }}
            .container {{
                background: rgba(255,255,255,0.1);
                border-radius: 20px;
                padding: 40px 30px;
                max-width: 400px;
                width: 100%;
                text-align: center;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255,255,255,0.2);
            }}
            .icon {{ font-size: 64px; margin-bottom: 20px; }}
            h1 {{ font-size: 24px; margin-bottom: 15px; color: #ef4444; }}
            .info {{
                color: rgba(255,255,255,0.8);
                margin-bottom: 25px;
                font-size: 15px;
                line-height: 1.5;
            }}
            .btn {{
                display: inline-block;
                padding: 14px 28px;
                background: linear-gradient(135deg, #3b82f6, #2563eb);
                border: none;
                border-radius: 12px;
                color: white;
                font-size: 16px;
                font-weight: 600;
                text-decoration: none;
                transition: transform 0.2s;
            }}
            .btn:hover {{ transform: scale(1.02); }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">❌</div>
            <h1>Оплата не прошла</h1>
            <p class="info">
                К сожалению, платёж не был завершён.<br>
                Вы можете попробовать ещё раз.
            </p>
            <a href="https://t.me" class="btn">Вернуться в Telegram</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


# ============================================
# ТЕСТИРОВАНИЕ БЕЗ РЕАЛЬНЫХ ПЛАТЕЖЕЙ
# ============================================

@app.get("/api/simulate-payment/{order_id}")
async def simulate_payment(order_id: int, admin_key: str = None, status: str = "Paid"):
    """
    Симулирует webhook от wata.pro для тестирования БЕЗ реальных денег.

    Использование:
    GET /api/simulate-payment/123?admin_key=YOUR_KEY&status=Paid

    status может быть: Paid, Declined, Pending
    admin_key = первые 10 символов BOT_TOKEN
    """
    expected_key = BOT_TOKEN[:10] if BOT_TOKEN else "test"
    if admin_key != expected_key:
        return {
            "error": "Invalid admin key",
            "hint": "Use first 10 chars of BOT_TOKEN as admin_key",
            "example": f"/api/simulate-payment/{order_id}?admin_key=YOUR_KEY&status=Paid"
        }

    # Проверяем что заказ существует
    order = await get_order_by_id(order_id)
    if not order:
        return {"error": f"Order {order_id} not found"}

    # Имитируем данные webhook
    fake_webhook_data = {
        "transactionId": f"TEST_{order_id}_{int(time.time())}",
        "status": status,
        "orderId": f"order_{order_id}",
        "amount": order[4]  # amount из заказа
    }

    logger.info(f"🧪 SIMULATING webhook for order {order_id} with status={status}")
    logger.info(f"Fake webhook data: {fake_webhook_data}")

    # Извлекаем данные
    transaction_id = fake_webhook_data["transactionId"]
    order_id_str = fake_webhook_data["orderId"]
    amount = fake_webhook_data["amount"]
    status_normalized = status.lower()

    # order: (id, user_id, product_id, product_name, amount, game, pickup_code, status, ...)
    user_id = order[1]
    product_name = order[3] or "Товар"
    pickup_code = order[6]

    results = {"order_id": order_id, "simulated_status": status, "actions": []}

    if status_normalized == "paid":
        # Обновляем статус заказа
        await update_order_payment_status(order_id, "paid")
        results["actions"].append("Order status updated to 'paid'")

        # Сохраняем transaction_id
        await save_payment_transaction(order_id, transaction_id)
        results["actions"].append(f"Transaction saved: {transaction_id}")

        # Уведомляем пользователя
        user_message = (
            f"✅ <b>Оплата получена!</b>\n\n"
            f"📦 Товар: {product_name}\n"
            f"🔑 Код получения: <code>{pickup_code}</code>\n\n"
            f"Администратор обработает ваш заказ в ближайшее время.\n"
            f"Вы получите уведомление когда товар будет готов."
        )
        user_result = await send_telegram_message(user_id, user_message)
        results["actions"].append(f"User notification sent: {user_result}")
        results["user_notified"] = user_result

        # Уведомляем админов
        user_uid = await get_user_uid(user_id)
        admin_message = (
            f"💰 <b>ОПЛАТА ПОЛУЧЕНА!</b> (ТЕСТ)\n\n"
            f"📦 Заказ: #{order_id}\n"
            f"📦 Товар: {product_name}\n"
            f"💰 Сумма: {amount} ₽\n"
            f"👤 Покупатель: UID #{user_uid}\n"
            f"🔑 Код получения: {pickup_code}\n"
            f"🆔 Transaction: {transaction_id}"
        )
        reply_markup = {
            "inline_keyboard": [
                [{"text": "👤 Перейти к пользователю", "callback_data": f"admin_goto_user_{user_id}"}],
                [
                    {"text": "✅ Выполнен", "callback_data": f"admin_confirm_order_{order_id}"},
                    {"text": "❌ Отменить", "callback_data": f"admin_cancel_order_{order_id}"}
                ]
            ]
        }
        admin_results = []
        for admin_id in ADMIN_IDS:
            result = await send_telegram_message(admin_id, admin_message, reply_markup)
            admin_results.append({"admin_id": admin_id, "success": result})
        results["actions"].append(f"Admin notifications sent")
        results["admin_notifications"] = admin_results

    elif status_normalized == "declined":
        await update_order_payment_status(order_id, "payment_failed")
        results["actions"].append("Order status updated to 'payment_failed'")

        user_message = (
            f"❌ <b>Оплата отклонена</b> (ТЕСТ)\n\n"
            f"К сожалению, платёж за заказ #{order_id} не прошёл.\n"
            f"Вы можете попробовать оплатить ещё раз."
        )
        user_result = await send_telegram_message(user_id, user_message)
        results["actions"].append(f"User notification sent: {user_result}")

    results["success"] = True
    return results


# ============================================
# WEBHOOK ОТ WATA.PRO
# ============================================
# URL настроен в ЛК wata.pro: https://supercellshop.xyz/webhook/wata
# Wata.pro отправляет POST запрос когда платёж:
# - Успешно завершён (status: Paid)
# - Отклонён (status: Declined)
# ============================================

@app.get("/webhook/wata")
async def wata_webhook_check():
    """
    GET endpoint для проверки доступности webhook URL.
    Wata.pro может использовать для проверки что URL доступен.
    """
    logger.info("Webhook URL check (GET request)")
    return {"status": "ok", "message": "Webhook endpoint is accessible", "method": "GET"}


@app.get("/api/test-notification/{order_id}")
async def test_notification(order_id: int, admin_key: str = None):
    """
    Тестовый endpoint для проверки отправки уведомлений.
    Используется для диагностики - имитирует получение webhook.

    ВНИМАНИЕ: Только для тестирования! Не меняет статус заказа.
    """
    # Простая защита - требуем ключ
    expected_key = BOT_TOKEN[:10] if BOT_TOKEN else "test"
    if admin_key != expected_key:
        return {"error": "Invalid admin key", "hint": "Use first 10 chars of BOT_TOKEN"}

    order = await get_order_by_id(order_id)
    if not order:
        return {"error": f"Order {order_id} not found"}

    user_id = order[1]
    product_name = order[3] or "Товар"
    pickup_code = order[6]

    # Тестовое сообщение пользователю
    test_message = (
        f"🔔 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ</b>\n\n"
        f"Это тест системы уведомлений.\n"
        f"📦 Товар: {product_name}\n"
        f"🔑 Код: {pickup_code}\n\n"
        f"Если вы видите это сообщение - уведомления работают!"
    )

    user_result = await send_telegram_message(user_id, test_message)

    # Тестовое сообщение админам
    admin_results = []
    for admin_id in ADMIN_IDS:
        admin_msg = f"🔔 Тест уведомлений для заказа #{order_id}\nUser: {user_id}\nResult: {user_result}"
        result = await send_telegram_message(admin_id, admin_msg)
        admin_results.append({"admin_id": admin_id, "success": result})

    return {
        "status": "test_sent",
        "order_id": order_id,
        "user_id": user_id,
        "user_notification": user_result,
        "admin_notifications": admin_results,
        "bot_token_set": bool(BOT_TOKEN),
        "admin_ids": list(ADMIN_IDS)
    }


@app.get("/api/debug/logs")
async def get_debug_logs(admin_key: str = None, lines: int = 100):
    """
    Просмотр последних логов API для диагностики.
    Требует admin_key (первые 10 символов BOT_TOKEN).
    """
    expected_key = BOT_TOKEN[:10] if BOT_TOKEN else "test"
    if admin_key != expected_key:
        return {"error": "Invalid admin key"}

    try:
        with open('/tmp/api_debug.log', 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            # Возвращаем последние N строк
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            # Фильтруем строки с webhook для удобства
            webhook_lines = [l for l in recent_lines if 'webhook' in l.lower() or 'wata' in l.lower()]
            return {
                "total_lines": len(all_lines),
                "returned_lines": len(recent_lines),
                "webhook_related": len(webhook_lines),
                "logs": recent_lines,
                "webhook_logs": webhook_lines
            }
    except FileNotFoundError:
        return {"error": "Log file not found", "path": "/tmp/api_debug.log"}
    except Exception as e:
        return {"error": str(e)}


@app.post("/webhook/wata")
async def wata_webhook(request: Request):
    """
    Обработчик webhook'ов от wata.pro.

    Wata.pro отправляет уведомление когда статус платежа меняется.
    Это РЕАЛЬНОЕ подтверждение оплаты (в отличие от redirect на success_url).
    """
    # Получаем подпись из заголовка
    signature = request.headers.get("X-Signature", "")

    # Получаем тело запроса
    body = await request.body()

    logger.info(f"Webhook received from wata.pro, body length: {len(body)}")

    # PRODUCTION: Проверяем подпись webhook
    from wata_form import verify_webhook_signature_async
    if IS_PRODUCTION:
        is_valid = await verify_webhook_signature_async(body, signature)
        if not is_valid:
            logger.warning("Invalid webhook signature - rejecting request!")
            raise HTTPException(status_code=401, detail="Invalid signature")
    elif signature:
        # В dev режиме логируем, но не блокируем
        is_valid = await verify_webhook_signature_async(body, signature)
        if not is_valid:
            logger.warning("Invalid webhook signature (dev mode - allowing)")

    try:
        data = await request.json()
        # ВСЕГДА логируем полные данные webhook для отладки
        logger.info(f"Wata webhook FULL DATA: {data}")
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Извлекаем данные из webhook
    # wata.pro может использовать разные названия полей
    transaction_id = data.get("transactionId") or data.get("transaction_id") or data.get("id")
    status = data.get("status") or data.get("state") or data.get("paymentStatus")
    order_id_str = data.get("orderId") or data.get("order_id") or data.get("merchantOrderId") or ""
    amount = data.get("amount") or data.get("sum") or data.get("total")

    logger.info(f"Wata webhook: transaction={transaction_id}, status={status}, order={order_id_str}, amount={amount}")

    # Нормализуем статус (wata.pro может присылать разные варианты)
    status_normalized = status.lower() if status else ""
    # Маппинг возможных статусов от wata.pro
    if status_normalized in ("success", "completed", "approved", "confirmed"):
        status_normalized = "paid"
    elif status_normalized in ("failed", "rejected", "cancelled", "canceled", "error"):
        status_normalized = "declined"
    logger.info(f"Normalized status: '{status}' -> '{status_normalized}'")

    # Извлекаем числовой order_id
    numeric_order_id = None
    if order_id_str:
        if order_id_str.startswith("order_"):
            try:
                numeric_order_id = int(order_id_str.replace("order_", ""))
            except ValueError:
                pass
        else:
            try:
                numeric_order_id = int(order_id_str)
            except ValueError:
                pass

    if not numeric_order_id:
        logger.error(f"Could not parse order_id from webhook: {order_id_str}")
        return {"status": "ok", "message": "order_id not parsed"}

    # Получаем заказ из БД
    order = await get_order_by_id(numeric_order_id)
    if not order:
        logger.error(f"Order {numeric_order_id} not found")
        return {"status": "ok", "message": "order not found"}

    # order: (id, user_id, product_id, product_name, amount, game, pickup_code, status, ...)
    user_id = order[1]
    product_name = order[3] or "Товар"
    pickup_code = order[6]

    if status_normalized == "paid":
        logger.info(f"Payment CONFIRMED for order {numeric_order_id}")

        # Обновляем статус заказа на "paid"
        await update_order_payment_status(numeric_order_id, "paid")

        # Сохраняем transaction_id если есть
        if transaction_id:
            await save_payment_transaction(numeric_order_id, transaction_id)

        # Уведомляем пользователя об успешной оплате
        try:
            user_message = (
                f"✅ <b>Оплата получена!</b>\n\n"
                f"📦 Товар: {product_name}\n"
                f"🔑 Код получения: <code>{pickup_code}</code>\n\n"
                f"Администратор обработает ваш заказ в ближайшее время.\n"
                f"Вы получите уведомление когда товар будет готов."
            )
            result = await send_telegram_message(user_id, user_message)
            logger.info(f"Payment notification sent to user {user_id}: success={result}")
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")

        # Уведомляем админов
        try:
            user_uid = await get_user_uid(user_id)
            admin_message = (
                f"💰 <b>ОПЛАТА ПОЛУЧЕНА!</b>\n\n"
                f"📦 Заказ: #{numeric_order_id}\n"
                f"📦 Товар: {product_name}\n"
                f"💰 Сумма: {amount} ₽\n"
                f"👤 Покупатель: UID #{user_uid}\n"
                f"🔑 Код получения: {pickup_code}\n"
                f"🆔 Transaction: {transaction_id or 'N/A'}"
            )
            reply_markup = {
                "inline_keyboard": [
                    [{"text": "👤 Перейти к пользователю", "callback_data": f"admin_goto_user_{user_id}"}],
                    [
                        {"text": "✅ Выполнен", "callback_data": f"admin_confirm_order_{numeric_order_id}"},
                        {"text": "❌ Отменить", "callback_data": f"admin_cancel_order_{numeric_order_id}"}
                    ]
                ]
            }
            for admin_id in ADMIN_IDS:
                result = await send_telegram_message(admin_id, admin_message, reply_markup)
                logger.info(f"Admin notification to {admin_id}: success={result}")
            logger.info(f"Admin notifications sent for paid order {numeric_order_id}")
        except Exception as e:
            logger.error(f"Failed to notify admins: {e}")

    elif status_normalized == "declined":
        logger.warning(f"Payment DECLINED for order {numeric_order_id}")

        # Обновляем статус заказа
        await update_order_payment_status(numeric_order_id, "payment_failed")

        # Уведомляем пользователя
        try:
            user_message = (
                f"❌ <b>Оплата отклонена</b>\n\n"
                f"К сожалению, платёж за заказ #{numeric_order_id} не прошёл.\n"
                f"Вы можете попробовать оплатить ещё раз."
            )
            await send_telegram_message(user_id, user_message)
        except Exception as e:
            logger.error(f"Failed to notify user about declined payment: {e}")

    elif status_normalized == "pending":
        logger.info(f"Payment PENDING for order {numeric_order_id}")
        # Ничего не делаем, ждём финального статуса

    else:
        logger.warning(f"Unknown payment status: {status}")

    # ВАЖНО: Вернуть 200 OK, иначе wata.pro будет повторять запросы
    return {"status": "ok"}


# ============================================
# КОНЕЦ БЛОКА WATA.PRO PAYMENT
# ============================================


@app.get("/api/user/{user_id}/avatar")
async def get_user_avatar(user_id: int):
    """Получить аватарку пользователя через Telegram Bot API"""
    try:
        async with aiohttp.ClientSession() as session:
            # Получаем фото профиля пользователя
            async with session.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos?user_id={user_id}&limit=1"
            ) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=404, detail="Avatar not found")

                data = await resp.json()
                if not data.get("ok") or data["result"]["total_count"] == 0:
                    raise HTTPException(status_code=404, detail="No avatar")

                # Берём самый маленький размер (первый в массиве)
                photo = data["result"]["photos"][0][0]
                file_id = photo["file_id"]

            # Получаем file_path
            async with session.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
            ) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=404, detail="File not found")

                file_data = await resp.json()
                if not file_data.get("ok"):
                    raise HTTPException(status_code=404, detail="File not found")

                file_path = file_data["result"]["file_path"]

            # Скачиваем файл
            async with session.get(
                f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            ) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=404, detail="Failed to download")

                image_data = await resp.read()

                return StreamingResponse(
                    BytesIO(image_data),
                    media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=3600"}  # Кэш на 1 час
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading avatar for user {user_id}: {e}")
        raise HTTPException(status_code=404, detail="Avatar not found")


@app.get("/api/product-image/{file_id}")
async def get_product_image(file_id: str):
    """Получить изображение товара через Telegram Bot API"""
    try:
        # Получаем информацию о файле
        async with aiohttp.ClientSession() as session:
            # Получаем file_path
            async with session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}") as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=404, detail="Image not found")

                data = await resp.json()
                if not data.get("ok"):
                    raise HTTPException(status_code=404, detail="Image not found")

                file_path = data["result"]["file_path"]

            # Скачиваем файл
            async with session.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}") as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=404, detail="Failed to download image")

                image_data = await resp.read()

                # Возвращаем изображение
                return StreamingResponse(
                    BytesIO(image_data),
                    media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"}  # Кэш на 24 часа
                )
    except Exception as e:
        print(f"Error loading image {file_id}: {e}")
        raise HTTPException(status_code=404, detail="Image not found")


# Монтируем статичные файлы
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    print("Starting Mini App API server...")
    print("Access at: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
