from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import (
    get_product_by_id, purchase_with_balance, get_user_balance, get_user_uid,
    create_order_without_balance, update_order_payment_status
)
from keyboards import get_product_categories
from config import ADMIN_IDS, SUPPORT_URL
import sys
import os
import re
import logging

logger = logging.getLogger(__name__)

# Добавляем путь к miniapp для импорта wata_form
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'miniapp'))
from wata_form import create_payment_form_url_async

router = Router()


class PurchaseStates(StatesGroup):
    """Состояния для процесса покупки через СБП"""
    waiting_for_email = State()


@router.callback_query(F.data.startswith("buy_product_"))
async def buy_product(callback: CallbackQuery):
    """Обработчик покупки товара"""
    product_id = int(callback.data.replace("buy_product_", ""))
    user_id = callback.from_user.id

    # Получаем информацию о товаре
    product = await get_product_by_id(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    # product: (id, name, description, price, game, subcategory, in_stock, image_file_id, created_at)
    description = product[2]  # Текст товара
    price = product[3]
    game = product[4]
    subcategory = product[5]
    image_file_id = product[7] if len(product) > 7 else None

    # Показываем информацию о товаре
    # Если товар из категории "all", возвращаемся на страницу игры, иначе на страницу категории
    back_callback = f"category_{game}" if subcategory == "all" else f"{game}_{subcategory}"
    keyboard = [
        [InlineKeyboardButton(text="💳 Купить", callback_data=f"confirm_buy_{product_id}")],
        [InlineKeyboardButton(text="Назад", callback_data=back_callback)]
    ]

    # Описание + цена (без .00)
    caption = f"{description}\n\nЦена: {price:.0f} ₽"

    # Если есть изображение товара - показываем его
    if image_file_id:
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=image_file_id, caption=caption),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
        except:
            await callback.message.edit_caption(
                caption=caption,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
    else:
        await callback.message.edit_caption(
            caption=caption,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_buy_"))
async def confirm_buy_product(callback: CallbackQuery, state: FSMContext):
    """Выбор способа оплаты"""
    # Очищаем состояние FSM при возврате к выбору оплаты
    await state.clear()
    product_id = int(callback.data.replace("confirm_buy_", ""))
    user_id = callback.from_user.id

    # Получаем информацию о товаре и балансе
    product = await get_product_by_id(product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    price = product[3]
    balance = await get_user_balance(user_id)

    # Формируем клавиатуру с вариантами оплаты
    keyboard = []

    # Если достаточно средств на балансе, показываем опцию оплаты с баланса
    if balance >= price:
        keyboard.append([InlineKeyboardButton(text=f"💰 С баланса ({balance:.0f} ₽)", callback_data=f"pay_balance_{product_id}")])

    # Всегда показываем опцию оплаты через СБП
    keyboard.append([InlineKeyboardButton(text="💳 СБП (РФ)", callback_data=f"pay_sbp_{product_id}")])

    # Кнопка назад
    keyboard.append([InlineKeyboardButton(text="Назад", callback_data=f"buy_product_{product_id}")])

    await callback.message.edit_caption(
        caption=f"Выберите способ оплаты\n\nСумма к оплате: {price:.0f} ₽\nВаш баланс: {balance:.0f} ₽",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay_balance_"))
async def pay_with_balance(callback: CallbackQuery):
    """Оплата с баланса"""
    product_id = int(callback.data.replace("pay_balance_", ""))
    user_id = callback.from_user.id

    # Пытаемся купить товар
    success, message, order_id, pickup_code = await purchase_with_balance(user_id, product_id)

    if success:
        # Получаем информацию о товаре
        product = await get_product_by_id(product_id)
        product_name = product[1]
        price = product[3]

        # Получаем UID пользователя
        user_uid = await get_user_uid(user_id)

        # Отправляем сообщение покупателю
        support_button = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Поддержка", url=SUPPORT_URL)]
        ])

        purchase_message = (
            f"Поздравляем с покупкой!\n\n"
            f"Ваш товар: {product_name}\n"
            f"Код получения: {pickup_code}\n\n"
            f"⚠️ Важно: никому не передавайте код получения.\n\n"
            f"Для получения товара отправьте данный код поддержке"
        )

        await callback.bot.send_message(
            user_id,
            purchase_message,
            reply_markup=support_button
        )

        # Отправляем уведомление администраторам
        admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Перейти к пользователю", callback_data=f"admin_goto_user_{user_id}")],
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_confirm_order_{order_id}"),
                InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_cancel_order_{order_id}")
            ]
        ])

        admin_message = (
            f"Новая продажа!\n\n"
            f"Название товара: {product_name}\n"
            f"Сумма: {price:.0f} ₽\n"
            f"Покупатель: UID #{user_uid}\n"
            f"Код получения: {pickup_code}"
        )

        for admin_id in ADMIN_IDS:
            try:
                await callback.bot.send_message(
                    admin_id,
                    admin_message,
                    reply_markup=admin_keyboard
                )
            except:
                pass

        await callback.answer("Покупка успешно завершена!", show_alert=True)
        # Возвращаем в магазин
        await callback.message.edit_caption(
            caption="✅ Покупка успешно завершена!\n\nПроверьте личные сообщения для получения кода.\n\nВыберите категорию 👇",
            reply_markup=get_product_categories()
        )
    else:
        await callback.answer(message, show_alert=True)


@router.callback_query(F.data.startswith("pay_sbp_"))
async def pay_with_sbp(callback: CallbackQuery, state: FSMContext):
    """Оплата через СБП - запрос email"""
    product_id = int(callback.data.replace("pay_sbp_", ""))

    # Получаем информацию о товаре
    product = await get_product_by_id(product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    price = product[3]
    product_name = product[1]

    # Сохраняем product_id в состояние
    await state.update_data(sbp_product_id=product_id)
    await state.set_state(PurchaseStates.waiting_for_email)

    keyboard = [
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"confirm_buy_{product_id}")]
    ]

    await callback.message.edit_caption(
        caption=(
            f"Оплата через СБП\n\n"
            f"Товар: {product_name}\n"
            f"Сумма: {price:.0f} ₽\n\n"
            f"Для завершения покупки введите email вашего Supercell ID\n"
            f"(это почта, на которую привязан аккаунт в игре)"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.message(PurchaseStates.waiting_for_email)
async def process_sbp_email(message: Message, state: FSMContext):
    """Обработка введённого email и создание платежа"""
    email = message.text.strip().lower()

    # Проверяем формат email
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        await message.answer(
            "Некорректный формат email. Пожалуйста, введите корректный email:\n"
            "(например: example@gmail.com)"
        )
        return

    # Получаем сохранённый product_id
    data = await state.get_data()
    product_id = data.get('sbp_product_id')

    if not product_id:
        await state.clear()
        await message.answer("Произошла ошибка. Пожалуйста, начните покупку заново.")
        return

    # Получаем товар
    product = await get_product_by_id(product_id)
    if not product:
        await state.clear()
        await message.answer("Товар не найден. Пожалуйста, начните покупку заново.")
        return

    product_name = product[1]
    price = product[3]
    user_id = message.from_user.id

    # Создаём заказ без списания баланса
    success, msg, order_id, pickup_code = await create_order_without_balance(
        user_id, product_id, email
    )

    if not success:
        await state.clear()
        await message.answer(f"Ошибка создания заказа: {msg}")
        return

    # Устанавливаем статус "ожидает оплаты"
    await update_order_payment_status(order_id, "pending_payment")

    # Создаём ссылку на оплату через wata.pro
    try:
        result = await create_payment_form_url_async(
            amount=price,
            order_id=f"order_{order_id}",
            description=f"Заказ #{order_id}: {product_name}"
        )

        if not result.success:
            logger.error(f"Failed to create payment URL: {result.error}")
            await message.answer(
                f"Ошибка создания платежа: {result.error}\n\n"
                f"Заказ #{order_id} создан, но требуется оплата.\n"
                f"Попробуйте позже или обратитесь в поддержку."
            )
            await state.clear()
            return

        # Очищаем состояние
        await state.clear()

        # Отправляем кнопку для оплаты
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=result.payment_url)],
            [InlineKeyboardButton(text="📞 Поддержка", url=SUPPORT_URL)]
        ])

        await message.answer(
            f"Заказ #{order_id} создан!\n\n"
            f"Товар: {product_name}\n"
            f"Сумма к оплате: {price:.0f} ₽\n"
            f"Supercell ID: {email}\n\n"
            f"Нажмите кнопку «Оплатить» для перехода к оплате.\n"
            f"После оплаты вы получите уведомление с кодом получения.",
            reply_markup=keyboard
        )

        logger.info(f"SBP payment created for order {order_id}, user {user_id}, product {product_id}")

    except Exception as e:
        logger.error(f"Error creating SBP payment: {e}", exc_info=True)
        await state.clear()
        await message.answer(
            f"Произошла ошибка при создании платежа.\n\n"
            f"Заказ #{order_id} создан.\n"
            f"Пожалуйста, обратитесь в поддержку для завершения оплаты."
        )
