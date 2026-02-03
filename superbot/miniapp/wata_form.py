"""
Wata.pro Payment Integration
============================

Создаёт Payment Links через H2H API wata.pro.
Payment Link — это ссылка на hosted payment page wata.pro.

Flow:
1. Создаём Payment Link через POST /api/h2h/links
2. Получаем URL платёжной формы
3. Пользователь переходит, оплачивает
4. Wata.pro отправляет webhook на /webhook/wata
5. Wata.pro редиректит на Success/Fail Page

Настройки в ЛК wata.pro (merchant.wata.pro):
- Webhook URL: https://supercellshop.xyz/webhook/wata
- Success Page: https://supercellshop.xyz/payment/success
- Fail Page: https://supercellshop.xyz/payment/fail
"""

import os
import logging
import httpx
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

# JWT токен от wata.pro (из ЛК мерчанта)
WATA_API_TOKEN = os.getenv("WATA_API_TOKEN", "")

# Режим песочницы
WATA_SANDBOX = os.getenv("WATA_SANDBOX", "false").lower() == "true"

# Base URL для API
WATA_API_BASE = "https://api-sandbox.wata.pro" if WATA_SANDBOX else "https://api.wata.pro"

# Базовый URL нашего сервера
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://supercellshop.xyz").rstrip("/")


@dataclass
class PaymentFormResult:
    """Результат создания ссылки на платёжную форму"""
    success: bool
    payment_url: Optional[str] = None
    link_id: Optional[str] = None
    order_id: Optional[str] = None
    error: Optional[str] = None


async def create_payment_link_via_api(
    amount: float,
    order_id: str,
    description: str = ""
) -> PaymentFormResult:
    """
    Создаёт Payment Link через H2H API wata.pro.

    Payment Link — это ссылка на hosted payment page,
    где пользователь выбирает способ оплаты и платит.

    Args:
        amount: Сумма в рублях
        order_id: ID заказа (строка, например "order_123")
        description: Описание платежа

    Returns:
        PaymentFormResult с payment_url или ошибкой
    """
    if not WATA_API_TOKEN:
        logger.error("WATA_API_TOKEN не установлен!")
        return PaymentFormResult(
            success=False,
            error="API токен wata.pro не настроен. Добавьте WATA_API_TOKEN в .env"
        )

    # URL'ы для редиректа — простые URL без параметров
    # Wata.pro сам добавит параметры (orderId, transactionId) при редиректе
    success_url = f"{WEBHOOK_BASE_URL}/payment/success"
    fail_url = f"{WEBHOOK_BASE_URL}/payment/fail"

    payload = {
        "amount": round(amount, 2),
        "currency": "RUB",
        "orderId": order_id,
        "description": description or f"Оплата заказа {order_id}",
        "successRedirectUrl": success_url,
        "failRedirectUrl": fail_url,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WATA_API_TOKEN}"
    }

    logger.info(f"Creating payment link: order_id={order_id}, amount={amount}")
    logger.debug(f"API URL: {WATA_API_BASE}/api/h2h/links")
    logger.debug(f"Payload: {payload}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{WATA_API_BASE}/api/h2h/links",
                headers=headers,
                json=payload
            )

            logger.info(f"Wata API response status: {response.status_code}")
            logger.debug(f"Wata API response: {response.text}")

            if response.status_code == 200:
                data = response.json()
                # Ищем URL в разных возможных полях ответа
                payment_url = data.get("url") or data.get("paymentUrl") or data.get("link")
                link_id = data.get("id") or data.get("linkId")

                if payment_url:
                    logger.info(f"Payment link created successfully: {payment_url[:60]}...")
                    return PaymentFormResult(
                        success=True,
                        payment_url=payment_url,
                        link_id=link_id,
                        order_id=order_id
                    )
                else:
                    logger.error(f"No payment URL in response: {data}")
                    return PaymentFormResult(
                        success=False,
                        error="Не получена ссылка на оплату от wata.pro"
                    )

            elif response.status_code == 401:
                logger.error("Wata API: Unauthorized (401) - неверный токен")
                return PaymentFormResult(
                    success=False,
                    error="Неверный API токен wata.pro. Проверьте WATA_API_TOKEN в .env"
                )

            elif response.status_code == 403:
                logger.error("Wata API: Forbidden (403) - нет доступа")
                return PaymentFormResult(
                    success=False,
                    error="Нет доступа к API. Обратитесь в поддержку wata.pro."
                )

            elif response.status_code == 400:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("message") or error_data.get("error") or response.text
                logger.error(f"Wata API: Bad Request (400): {error_msg}")
                return PaymentFormResult(
                    success=False,
                    error=f"Ошибка запроса: {error_msg}"
                )

            else:
                logger.error(f"Wata API unexpected error: {response.status_code} - {response.text}")
                return PaymentFormResult(
                    success=False,
                    error=f"Ошибка API wata.pro: HTTP {response.status_code}"
                )

    except httpx.TimeoutException:
        logger.error("Wata API timeout")
        return PaymentFormResult(
            success=False,
            error="Таймаут соединения с wata.pro. Попробуйте позже."
        )
    except Exception as e:
        logger.error(f"Wata API exception: {e}", exc_info=True)
        return PaymentFormResult(
            success=False,
            error=f"Ошибка: {str(e)}"
        )


def create_payment_form_url(
    amount: float,
    order_id: str,
    description: str = ""
) -> PaymentFormResult:
    """
    Синхронная обёртка для создания ссылки на платёжную форму.
    Используется в endpoint'ах FastAPI.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # Внутри async контекста — нужен другой подход
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                create_payment_link_via_api(amount, order_id, description)
            )
            return future.result(timeout=35)
    else:
        return asyncio.run(
            create_payment_link_via_api(amount, order_id, description)
        )


async def create_payment_form_url_async(
    amount: float,
    order_id: str,
    description: str = ""
) -> PaymentFormResult:
    """
    Async версия для прямого использования в async endpoint'ах.
    """
    return await create_payment_link_via_api(amount, order_id, description)


# ============================================
# СТАТУСЫ ПЛАТЕЖА
# ============================================

class PaymentStatus:
    """Статусы платежа от wata.pro webhook"""
    PENDING = "Pending"
    PAID = "Paid"
    DECLINED = "Declined"
    EXPIRED = "Expired"
    REFUNDED = "Refunded"


# ============================================
# ПРОВЕРКА ПОДПИСИ WEBHOOK
# ============================================

import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature

# Кэш для публичного ключа wata.pro
_wata_public_key = None
_wata_public_key_fetched = False


async def get_wata_public_key():
    """Получает публичный ключ wata.pro для верификации webhook"""
    global _wata_public_key, _wata_public_key_fetched

    if _wata_public_key_fetched:
        return _wata_public_key

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{WATA_API_BASE}/api/h2h/public-key")

            if response.status_code == 200:
                data = response.json()
                pem_key = data.get("publicKey") or data.get("key")

                if pem_key:
                    # Загружаем PEM ключ
                    _wata_public_key = serialization.load_pem_public_key(
                        pem_key.encode(),
                        backend=default_backend()
                    )
                    logger.info("Wata.pro public key loaded successfully")

        _wata_public_key_fetched = True
        return _wata_public_key

    except Exception as e:
        logger.error(f"Failed to fetch wata.pro public key: {e}")
        _wata_public_key_fetched = True
        return None


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """
    Проверяет подпись webhook'а от wata.pro.
    wata.pro подписывает webhooks RSA-SHA512.

    Args:
        body: Тело запроса (bytes)
        signature: Base64-encoded подпись из заголовка X-Signature

    Returns:
        True если подпись валидна, False иначе
    """
    if not signature:
        logger.warning("No signature in webhook request")
        return False  # В production отклоняем без подписи

    if not _wata_public_key:
        logger.warning("Wata.pro public key not available, skipping verification")
        return True  # Если ключ недоступен, пропускаем (но логируем)

    try:
        # Декодируем подпись из base64
        signature_bytes = base64.b64decode(signature)

        # Верифицируем подпись RSA-SHA512
        _wata_public_key.verify(
            signature_bytes,
            body,
            padding.PKCS1v15(),
            hashes.SHA512()
        )

        logger.debug("Webhook signature verified successfully")
        return True

    except InvalidSignature:
        logger.warning("Invalid webhook signature")
        return False
    except Exception as e:
        logger.error(f"Webhook signature verification error: {e}")
        return False


async def verify_webhook_signature_async(body: bytes, signature: str) -> bool:
    """Async версия верификации с автоматической загрузкой ключа"""
    global _wata_public_key

    if not _wata_public_key:
        await get_wata_public_key()

    return verify_webhook_signature(body, signature)
