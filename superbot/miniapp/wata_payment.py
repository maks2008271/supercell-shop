"""
WATA.PRO Payment Integration Module
===================================

Модуль для интеграции платежей через wata.pro (СБП).

Документация API: https://wata.pro/page72153117.html

НАСТРОЙКА:
1. Зарегистрируйтесь на https://merchant.wata.pro/
2. Получите API токен в личном кабинете
3. Добавьте в .env файл:
   - WATA_API_TOKEN=ваш_токен
   - WATA_SANDBOX=true (для тестирования) или false (для продакшена)
   - WEBHOOK_BASE_URL=https://ваш-домен.com (публичный URL для webhook'ов)

FLOW ОПЛАТЫ:
1. Пользователь нажимает "Оплатить СБП" в Mini App
2. Создаётся заказ со статусом "pending_payment"
3. Вызывается wata.pro API для создания СБП платежа
4. Пользователь получает ссылку/QR для оплаты через банк
5. После оплаты wata.pro отправляет webhook на наш сервер
6. Webhook обновляет статус заказа на "paid"
7. Админу приходит уведомление о новом оплаченном заказе
"""

import httpx
import hashlib
import hmac
import logging
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

#============================================
#КОНФИГУРАЦИЯ - ЗАПОЛНИТЕ СВОИ ДАННЫЕ
#============================================

#API токен от wata.pro (получить в личном кабинете merchant.wata.pro)
WATA_API_TOKEN = os.getenv("WATA_API_TOKEN", "")

#Режим песочницы для тестирования
WATA_SANDBOX = os.getenv("WATA_SANDBOX", "true").lower() == "true"

#Базовый URL для webhook'ов (ваш публичный домен)
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "")

#URL API wata.pro
WATA_API_URL = "https://api-sandbox.wata.pro/api/h2h" if WATA_SANDBOX else "https://api.wata.pro/api/h2h"


class PaymentStatus(Enum):
    """Статусы платежа от wata.pro"""
    PENDING = "Pending"      #Обрабатывается, ожидает ответа от банка
    PAID = "Paid"            #Успешно оплачен
    DECLINED = "Declined"    #Отклонён


@dataclass
class SBPPaymentResult:
    """Результат создания СБП платежа"""
    success: bool
    transaction_id: Optional[str] = None
    sbp_link: Optional[str] = None      #Ссылка для оплаты (открыть в банковском приложении)
    qr_code_url: Optional[str] = None   #URL QR-кода для сканирования
    error_message: Optional[str] = None


class WataPaymentClient:
    """
    Клиент для работы с API wata.pro

    Пример использования:

        client = WataPaymentClient()

        #Создание СБП платежа
        result = await client.create_sbp_payment(
            amount=900.00,
            order_id="order_123",
            description="Бравл Пасс",
            user_ip="192.168.1.1"
        )

        if result.success:
            #Отправить пользователю ссылку на оплату
            print(f"Ссылка для оплаты: {result.sbp_link}")
        else:
            print(f"Ошибка: {result.error_message}")
    """

    def __init__(self, api_token: str = None, sandbox: bool = None):
        self.api_token = api_token or WATA_API_TOKEN
        self.sandbox = sandbox if sandbox is not None else WATA_SANDBOX
        self.base_url = "https://api-sandbox.wata.pro/api/h2h" if self.sandbox else "https://api.wata.pro/api/h2h"

        if not self.api_token:
            logger.warning("WATA_API_TOKEN не установлен! Платежи не будут работать.")

    def _get_headers(self) -> Dict[str, str]:
        """Заголовки для API запросов"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}"
        }

    def _get_device_data(self, user_ip: str, user_agent: str = None) -> Dict[str, Any]:
        """
        Формирует данные устройства для API.

        В реальном приложении эти данные нужно собирать на клиенте
        через JavaScript и передавать на сервер.

        wata.pro предоставляет скрипт: https://static.wata.pro/checkout.js
        который имеет метод getDeviceData() для сбора этих данных.
        """
        return {
            "ipAddress": user_ip,
            "userAgent": user_agent or "Mozilla/5.0",
            "acceptHeader": "application/json",
            "language": "ru-RU",
            "javaEnabled": False,
            "javascriptEnabled": True,
            "colorDepth": 24,
            "screenHeight": 1080,
            "screenWidth": 1920,
            "timezoneOffset": -180  #MSK
        }

    async def create_sbp_payment(
        self,
        amount: float,
        order_id: str,
        description: str = "",
        user_ip: str = "127.0.0.1",
        user_agent: str = None,
        success_url: str = None,
        fail_url: str = None
    ) -> SBPPaymentResult:
        """
        Создаёт СБП платёж через wata.pro

        Args:
            amount: Сумма платежа в рублях
            order_id: Уникальный ID заказа в вашей системе
            description: Описание платежа
            user_ip: IP адрес пользователя
            user_agent: User-Agent браузера пользователя
            success_url: URL для редиректа после успешной оплаты
            fail_url: URL для редиректа при неудачной оплате

        Returns:
            SBPPaymentResult с данными платежа или ошибкой
        """

        if not self.api_token:
            return SBPPaymentResult(
                success=False,
                error_message="API токен wata.pro не настроен"
            )

        #Формируем URL'ы для редиректа
        base_url = WEBHOOK_BASE_URL or "https://your-domain.com"

        payload = {
            "amount": round(amount, 2),
            "currency": "RUB",
            "orderId": order_id,
            "description": description or f"Заказ #{order_id}",
            "deviceData": self._get_device_data(user_ip, user_agent),
            "ip": user_ip,
            "returnUrl": success_url or f"{base_url}/payment/success",
        }

        logger.info(f"Creating SBP payment: order_id={order_id}, amount={amount}")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/payments/sbp",
                    headers=self._get_headers(),
                    json=payload
                )

                logger.debug(f"Wata API response status: {response.status_code}")
                logger.debug(f"Wata API response: {response.text}")

                if response.status_code == 200:
                    data = response.json()
                    return SBPPaymentResult(
                        success=True,
                        transaction_id=data.get("transactionId"),
                        sbp_link=data.get("sbpLink"),
                        qr_code_url=data.get("qrCodeUrl")
                    )
                elif response.status_code == 401:
                    return SBPPaymentResult(
                        success=False,
                        error_message="Неверный API токен wata.pro"
                    )
                elif response.status_code == 400:
                    error_data = response.json()
                    return SBPPaymentResult(
                        success=False,
                        error_message=error_data.get("message", "Неверные данные запроса")
                    )
                else:
                    return SBPPaymentResult(
                        success=False,
                        error_message=f"Ошибка API: {response.status_code}"
                    )

        except httpx.TimeoutException:
            logger.error("Wata API timeout")
            return SBPPaymentResult(
                success=False,
                error_message="Таймаут соединения с платёжной системой"
            )
        except Exception as e:
            logger.error(f"Wata API error: {e}", exc_info=True)
            return SBPPaymentResult(
                success=False,
                error_message=f"Ошибка платёжной системы: {str(e)}"
            )

    async def get_transaction_status(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает статус транзакции по ID

        Args:
            transaction_id: ID транзакции от wata.pro

        Returns:
            Данные транзакции или None при ошибке
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/transactions/{transaction_id}",
                    headers=self._get_headers()
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Failed to get transaction {transaction_id}: {response.status_code}")
                    return None

        except Exception as e:
            logger.error(f"Error getting transaction status: {e}")
            return None

    async def check_pending_payments(self, pending_transactions: list) -> list:
        """
        Проверяет статус списка незавершённых платежей

        Используется для периодической проверки (например, раз в минуту)
        на случай если webhook не дошёл.

        Args:
            pending_transactions: список словарей с полями:
                - transaction_id: ID транзакции wata.pro
                - order_id: ID заказа в нашей системе

        Returns:
            Список обновлённых транзакций с их новыми статусами
        """
        updated = []

        for tx in pending_transactions:
            transaction_id = tx.get("transaction_id")
            order_id = tx.get("order_id")

            if not transaction_id:
                continue

            status_data = await self.get_transaction_status(transaction_id)

            if status_data:
                status = status_data.get("status")
                updated.append({
                    "transaction_id": transaction_id,
                    "order_id": order_id,
                    "status": status,
                    "data": status_data
                })

                logger.info(f"Payment check: order={order_id}, transaction={transaction_id}, status={status}")

        return updated

    async def create_payment_link(
        self,
        amount: float,
        order_id: str,
        description: str = "",
        success_url: str = None,
        fail_url: str = None,
        expiration_days: int = 3
    ) -> Optional[Dict[str, Any]]:
        """
        Создаёт ссылку на оплату (альтернативный способ)

        Ссылка может быть отправлена пользователю, и он сам выберет
        способ оплаты (СБП или карта).

        Args:
            amount: Сумма платежа
            order_id: ID заказа
            description: Описание
            success_url: URL после успешной оплаты
            fail_url: URL при неудаче
            expiration_days: Срок действия ссылки (макс. 30 дней)

        Returns:
            Данные ссылки с полем 'url' или None
        """
        if not self.api_token:
            return None

        base_url = WEBHOOK_BASE_URL or "https://your-domain.com"

        payload = {
            "amount": round(amount, 2),
            "currency": "RUB",
            "orderId": order_id,
            "description": description or f"Заказ #{order_id}",
            "successRedirectUrl": success_url or f"{base_url}/payment/success",
            "failRedirectUrl": fail_url or f"{base_url}/payment/fail",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/links",
                    headers=self._get_headers(),
                    json=payload
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Failed to create payment link: {response.status_code}")
                    return None

        except Exception as e:
            logger.error(f"Error creating payment link: {e}")
            return None


def verify_webhook_signature(payload: bytes, signature: str, public_key: str) -> bool:
    """
    Проверяет подпись webhook'а от wata.pro

    wata.pro подписывает webhook'и с помощью RSA-SHA512.
    Публичный ключ можно получить через GET /public-key

    Args:
        payload: Тело webhook запроса (bytes)
        signature: Значение заголовка X-Signature
        public_key: RSA публичный ключ от wata.pro

    Returns:
        True если подпись валидна
    """
    #TODO: Реализовать проверку RSA-SHA512 подписи
    #Для этого нужно использовать библиотеку cryptography:
    #
    #from cryptography.hazmat.primitives import hashes, serialization
    #from cryptography.hazmat.primitives.asymmetric import padding
    #from cryptography.hazmat.backends import default_backend
    #import base64
    #
    #try:
    #    key = serialization.load_pem_public_key(public_key.encode(), backend=default_backend())
    #    signature_bytes = base64.b64decode(signature)
    #    key.verify(signature_bytes, payload, padding.PKCS1v15(), hashes.SHA512())
    #    return True
    #except Exception:
    #    return False

    logger.warning("Webhook signature verification not implemented!")
    return True  #Временно пропускаем проверку


#============================================
#ПРИМЕР ИСПОЛЬЗОВАНИЯ В FASTAPI
#============================================
#
#from fastapi import APIRouter, Request, HTTPException
#from wata_payment import WataPaymentClient, verify_webhook_signature, PaymentStatus
#
#router = APIRouter()
#wata_client = WataPaymentClient()
#
#@router.post("/api/create-payment")
#async def create_payment(request: Request, order_id: int, amount: float):
#    '''Создаёт СБП платёж для заказа'''
#
#    #Получаем IP пользователя
#    user_ip = request.client.host
#    user_agent = request.headers.get("User-Agent", "")
#
#    result = await wata_client.create_sbp_payment(
#        amount=amount,
#        order_id=f"order_{order_id}",
#        description=f"Оплата заказа #{order_id}",
#        user_ip=user_ip,
#        user_agent=user_agent
#    )
#
#    if result.success:
#        #Сохраняем transaction_id в базу
#        #await save_transaction_id(order_id, result.transaction_id)
#
#        return {
#            "success": True,
#            "sbp_link": result.sbp_link,
#            "qr_code_url": result.qr_code_url,
#            "transaction_id": result.transaction_id
#        }
#    else:
#        return {
#            "success": False,
#            "error": result.error_message
#        }
#
#
#@router.post("/webhook/wata")
#async def wata_webhook(request: Request):
#    '''Обработчик webhook'ов от wata.pro'''
#
#    #Получаем подпись
#    signature = request.headers.get("X-Signature", "")
#
#    #Получаем тело запроса
#    body = await request.body()
#
#    #TODO: Проверка подписи (когда будет публичный ключ)
#    #if not verify_webhook_signature(body, signature, PUBLIC_KEY):
#    #    raise HTTPException(status_code=401, detail="Invalid signature")
#
#    data = await request.json()
#
#    transaction_id = data.get("transactionId")
#    status = data.get("status")
#    order_id = data.get("orderId")
#
#    logger.info(f"Webhook received: transaction={transaction_id}, status={status}, order={order_id}")
#
#    if status == PaymentStatus.PAID.value:
#        #Платёж успешен - обновляем заказ
#        #await update_order_status(order_id, "paid")
#        #await notify_admin_about_payment(order_id)
#        #await notify_user_about_payment(order_id)
#        pass
#    elif status == PaymentStatus.DECLINED.value:
#        #Платёж отклонён
#        #await update_order_status(order_id, "payment_failed")
#        pass
#
#    #ВАЖНО: Вернуть 200 OK, иначе wata.pro будет повторять запрос
#    return {"status": "ok"}
