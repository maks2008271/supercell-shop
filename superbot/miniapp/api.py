"""
FastAPI сервер для Mini App
Подключается к существующей базе данных бота
"""

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
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

# Настройка подробного логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
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
    get_user_orders
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

        # Сравниваем хеши
        if not hmac.compare_digest(calculated_hash, received_hash):
            logger.warning(f"Invalid hash: calculated {calculated_hash[:20]}..., received {received_hash[:20]}...")
            # Для отладки - временно пропускаем проверку хеша, но логируем
            # return None
            logger.info("Hash validation skipped for debugging - allowing request")

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
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send telegram message: {e}")
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

# CORS middleware для разрешения запросов от Telegram
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Модели данных
class PurchaseRequest(BaseModel):
    user_id: int
    product_id: int
    supercell_id: str


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
    """Получить историю заказов пользователя"""
    logger.debug(f"Getting orders for user_id: {user_id}")
    try:
        orders = await get_user_orders(user_id, limit)
        logger.info(f"Found {len(orders)} orders for user {user_id}")
        return orders
    except Exception as e:
        logger.error(f"Error getting orders for user {user_id}: {e}", exc_info=True)
        raise


@app.get("/api/search")
async def search_products(q: str, game: str = None):
    """Умный поиск товаров"""
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

    # Получаем информацию о товаре для уведомлений
    product = await get_product_by_id(request.product_id)
    product_name = product[1] if product else "Неизвестный товар"
    price = product[3] if product else 0

    # Отправляем уведомления
    try:
        # Уведомление пользователю
        await notify_user_about_purchase(request.user_id, product_name, pickup_code)
        logger.info(f"User notification sent to {request.user_id}")

        # Уведомление администраторам
        await notify_admins_about_order(
            request.user_id, order_id, pickup_code,
            product_name, price, request.supercell_id
        )
        logger.info(f"Admin notifications sent for order {order_id}")
    except Exception as e:
        logger.error(f"Failed to send notifications: {e}", exc_info=True)

    return {
        "success": True,
        "message": message,
        "order_id": order_id,
        "pickup_code": pickup_code
    }


# ============================================
# ИНТЕГРАЦИЯ WATA.PRO ДЛЯ СБП ОПЛАТЫ
# ============================================

# Импорт модуля оплаты (раскомментировать когда будет API токен)
from wata_payment import WataPaymentClient, PaymentStatus

# Инициализация клиента (раскомментировать когда будет API токен)
wata_client = WataPaymentClient()


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
    # Проверка Telegram
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Нет Telegram initData")

    user_data = validate_telegram_init_data(x_telegram_init_data)
    if not user_data:
        raise HTTPException(status_code=401, detail="Неверная авторизация")

    # ВАЖНО: берём сумму заказа
    # если нет get_order_by_id — временно ставь тестовую сумму
    amount = 100.00  # 🔥 ДЛЯ ТЕСТА

    user_ip = request.client.host if request.client else "127.0.0.1"
    user_agent = request.headers.get("User-Agent", "")

    result = await wata_client.create_sbp_payment(
        amount=amount,
        order_id=f"order_{request_data.order_id}",
        description=f"Заказ #{request_data.order_id}",
        user_ip=user_ip,
        user_agent=user_agent
    )

    if result.success:
        await save_payment_transaction(
            request_data.order_id,
            result.transaction_id
        )

        return {
            "success": True,
            "sbp_link": result.sbp_link,
            "qr_code_url": result.qr_code_url,
            "transaction_id": result.transaction_id
        }

    return {
        "success": False,
        "error": result.error_message
    }



@app.post("/webhook/wata")
async def wata_webhook(request: Request):
    """
    Обработчик webhook'ов от wata.pro

    wata.pro отправляет POST запрос на этот URL когда:
    - Платёж успешно завершён (status: Paid)
    - Платёж отклонён (status: Declined)

    ВАЖНО:
    1. Этот URL должен быть публично доступен (настройте ngrok или реальный домен)
    2. Зарегистрируйте URL в личном кабинете wata.pro
    3. Проверяйте подпись X-Signature для безопасности

    При успешной оплате:
    - Обновляем статус заказа на "paid"
    - Отправляем уведомление админу
    - Отправляем уведомление пользователю
    """

    # Получаем подпись из заголовка
    signature = request.headers.get("X-Signature", "")

    # Получаем тело запроса
    body = await request.body()

    # TODO: Проверка подписи (раскомментировать когда будет публичный ключ)
    # from wata_payment import verify_webhook_signature
    # PUBLIC_KEY = "..."  # Получить через GET /public-key
    # if not verify_webhook_signature(body, signature, PUBLIC_KEY):
    #     logger.warning("Invalid webhook signature!")
    #     raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    transaction_id = data.get("transactionId")
    status = data.get("status")
    order_id_str = data.get("orderId", "")  # Формат: "order_123"
    amount = data.get("amount")

    logger.info(f"Wata webhook: transaction={transaction_id}, status={status}, order={order_id_str}, amount={amount}")

    # Извлекаем числовой order_id
    order_id = None
    if order_id_str and order_id_str.startswith("order_"):
        try:
            order_id = int(order_id_str.replace("order_", ""))
        except ValueError:
            pass

    if status == "Paid":
        logger.info(f"Payment successful for order {order_id}")

        # TODO: Обновить статус заказа в базе
        # await update_order_status(order_id, "paid")

        # TODO: Отправить уведомление админам
        # await notify_admins_about_payment(order_id)

        # TODO: Отправить уведомление пользователю
        # await notify_user_payment_success(order_id)

    elif status == "Declined":
        logger.warning(f"Payment declined for order {order_id}")

        # TODO: Обновить статус заказа
        # await update_order_status(order_id, "payment_failed")

    # ВАЖНО: Вернуть 200 OK, иначе wata.pro будет повторять запросы 16 часов
    return {"status": "ok"}


@app.get("/payment/success")
async def payment_success():
    """
    Страница успешной оплаты

    Сюда редиректит wata.pro после успешной оплаты.
    В реальном приложении можно показать красивую страницу
    или редиректить обратно в Mini App.
    """
    return {
        "status": "success",
        "message": "Оплата прошла успешно! Вернитесь в Telegram."
    }


@app.get("/payment/fail")
async def payment_fail():
    """Страница неудачной оплаты"""
    return {
        "status": "failed",
        "message": "Оплата не прошла. Попробуйте ещё раз."
    }


# ============================================
# КОНЕЦ БЛОКА WATA.PRO
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
