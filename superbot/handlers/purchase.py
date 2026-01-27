from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from database import get_product_by_id, purchase_with_balance, get_user_balance, get_user_uid
from keyboards import get_product_categories
from config import ADMIN_IDS, SUPPORT_URL

router = Router()


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
    keyboard = [
        [InlineKeyboardButton(text="💳 Купить", callback_data=f"confirm_buy_{product_id}")],
        [InlineKeyboardButton(text="Назад", callback_data=f"{game}_{subcategory}")]
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
async def confirm_buy_product(callback: CallbackQuery):
    """Выбор способа оплаты"""
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
async def pay_with_sbp(callback: CallbackQuery):
    """Оплата через СБП"""
    product_id = int(callback.data.replace("pay_sbp_", ""))

    # Получаем информацию о товаре
    product = await get_product_by_id(product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    price = product[3]

    # Здесь будет интеграция с платежной системой
    await callback.answer(f"Интеграция платежной системы будет добавлена позже.\nСумма: {price:.0f} ₽", show_alert=True)
