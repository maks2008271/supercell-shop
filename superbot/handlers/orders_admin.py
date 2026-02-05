from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from database import (
    get_pending_orders, get_order_by_id, confirm_order, cancel_order,
    get_user_full_stats, get_user_uid
)

router = Router()

# Количество заказов на странице
ORDERS_PER_PAGE = 5


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in ADMIN_IDS


@router.callback_query(F.data == "admin_orders")
async def show_orders_menu(callback: CallbackQuery):
    """Главное меню заказов с категориями"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    orders = await get_pending_orders()

    if not orders:
        keyboard = [[InlineKeyboardButton(text="« Назад", callback_data="admin_panel")]]
        await callback.message.edit_text(
            "📋 Заказы\n\nНет незакрытых заказов",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await callback.answer()
        return

    # Считаем по категориям
    paid_orders = [o for o in orders if o[6] in ("paid", "pending")]
    unpaid_orders = [o for o in orders if o[6] == "pending_payment"]

    # Сумма оплаченных заказов
    paid_sum = sum(o[3] for o in paid_orders)

    keyboard = [
        [InlineKeyboardButton(
            text=f"✅ Оплаченные ({len(paid_orders)}) — {paid_sum:.0f}₽",
            callback_data="orders_paid_0"
        )],
        [InlineKeyboardButton(
            text=f"⏳ Ожидают оплаты ({len(unpaid_orders)})",
            callback_data="orders_unpaid_0"
        )],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")]
    ]

    text = (
        f"📋 Заказы\n\n"
        f"Всего незакрытых: {len(orders)}\n\n"
        f"✅ Оплачено и готово к выдаче: {len(paid_orders)}\n"
        f"⏳ Ожидают оплаты: {len(unpaid_orders)}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("orders_paid_"))
async def show_paid_orders(callback: CallbackQuery):
    """Показать оплаченные заказы с пагинацией"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    page = int(callback.data.replace("orders_paid_", ""))
    orders = await get_pending_orders()

    # Фильтруем только оплаченные
    paid_orders = [o for o in orders if o[6] in ("paid", "pending")]

    if not paid_orders:
        keyboard = [[InlineKeyboardButton(text="« Назад", callback_data="admin_orders")]]
        await callback.message.edit_text(
            "✅ Оплаченные заказы\n\nНет оплаченных заказов",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await callback.answer()
        return

    # Пагинация
    total_pages = (len(paid_orders) + ORDERS_PER_PAGE - 1) // ORDERS_PER_PAGE
    start_idx = page * ORDERS_PER_PAGE
    end_idx = start_idx + ORDERS_PER_PAGE
    page_orders = paid_orders[start_idx:end_idx]

    keyboard = []
    for order in page_orders:
        order_id, user_id, product_name, amount, pickup_code, created_at, status = order
        status_icon = "💰" if status == "paid" else "📦"
        keyboard.append([InlineKeyboardButton(
            text=f"{status_icon} #{order_id} | {amount:.0f}₽ | {product_name[:20]}",
            callback_data=f"vieword_paid_{order_id}"
        )])

    # Навигация по страницам
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"orders_paid_{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"orders_paid_{page + 1}"))

    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton(text="« Назад к категориям", callback_data="admin_orders")])

    # Сумма на странице
    page_sum = sum(o[3] for o in page_orders)
    total_sum = sum(o[3] for o in paid_orders)

    text = (
        f"✅ Оплаченные заказы\n"
        f"Готовы к выдаче!\n\n"
        f"Всего: {len(paid_orders)} на сумму {total_sum:.0f}₽\n"
        f"На странице: {len(page_orders)} на {page_sum:.0f}₽"
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("orders_unpaid_"))
async def show_unpaid_orders(callback: CallbackQuery):
    """Показать неоплаченные заказы с пагинацией"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    page = int(callback.data.replace("orders_unpaid_", ""))
    orders = await get_pending_orders()

    # Фильтруем только неоплаченные
    unpaid_orders = [o for o in orders if o[6] == "pending_payment"]

    if not unpaid_orders:
        keyboard = [[InlineKeyboardButton(text="« Назад", callback_data="admin_orders")]]
        await callback.message.edit_text(
            "⏳ Ожидают оплаты\n\nНет неоплаченных заказов",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await callback.answer()
        return

    # Пагинация
    total_pages = (len(unpaid_orders) + ORDERS_PER_PAGE - 1) // ORDERS_PER_PAGE
    start_idx = page * ORDERS_PER_PAGE
    end_idx = start_idx + ORDERS_PER_PAGE
    page_orders = unpaid_orders[start_idx:end_idx]

    keyboard = []
    for order in page_orders:
        order_id, user_id, product_name, amount, pickup_code, created_at, status = order
        keyboard.append([InlineKeyboardButton(
            text=f"⏳ #{order_id} | {amount:.0f}₽ | {product_name[:20]}",
            callback_data=f"vieword_unpaid_{order_id}"
        )])

    # Навигация по страницам
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"orders_unpaid_{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"orders_unpaid_{page + 1}"))

    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton(text="« Назад к категориям", callback_data="admin_orders")])

    text = (
        f"⏳ Ожидают оплаты\n\n"
        f"Всего: {len(unpaid_orders)} заказов\n"
        f"На странице: {len(page_orders)}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    """Пустой обработчик для кнопки с номером страницы"""
    await callback.answer()


@router.callback_query(F.data.startswith("vieword_"))
async def view_order_details(callback: CallbackQuery):
    """Показать детали заказа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    # Парсим: vieword_paid_123 или vieword_unpaid_123
    parts = callback.data.split("_")
    category = parts[1]  # paid или unpaid
    order_id = int(parts[2])

    order = await get_order_by_id(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    # order: (id, user_id, product_id, product_name, amount, game, pickup_code, status, created_at)
    user_id = order[1]
    product_name = order[3]
    amount = order[4]
    pickup_code = order[6]
    status = order[7]
    created_at = order[8]

    # Получаем UID пользователя
    user_uid = await get_user_uid(user_id)

    # Статус оплаты
    if status == "pending_payment":
        status_text = "⏳ НЕ ОПЛАЧЕН"
        status_hint = "Ожидает оплаты через СБП"
    elif status == "paid":
        status_text = "💰 ОПЛАЧЕН (СБП)"
        status_hint = "Готов к выдаче!"
    else:
        status_text = "📦 ОПЛАЧЕН (баланс)"
        status_hint = "Готов к выдаче!"

    text = (
        f"{'='*24}\n"
        f"  {status_text}\n"
        f"  {status_hint}\n"
        f"{'='*24}\n\n"
        f"Заказ: #{order_id}\n"
        f"Товар: {product_name}\n"
        f"Сумма: {amount:.0f} ₽\n\n"
        f"Покупатель: UID #{user_uid}\n"
        f"Telegram: {user_id}\n"
        f"Код: {pickup_code}\n"
        f"Дата: {created_at}"
    )

    # Определяем куда возвращаться
    back_callback = f"orders_{category}_0"

    keyboard = [
        [InlineKeyboardButton(text="👤 Пользователь", callback_data=f"usrord_{category}_{user_id}_{order_id}")],
        [
            InlineKeyboardButton(text="✅ Выполнен", callback_data=f"conford_{category}_{order_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancord_{category}_{order_id}")
        ],
        [InlineKeyboardButton(text="« Назад", callback_data=back_callback)]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


# Сохраняем совместимость со старым callback
@router.callback_query(F.data.startswith("view_order_"))
async def view_order_details_legacy(callback: CallbackQuery):
    """Показать детали заказа (старый формат)"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    order_id = int(callback.data.replace("view_order_", ""))

    order = await get_order_by_id(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    status = order[7]
    category = "unpaid" if status == "pending_payment" else "paid"

    # Перенаправляем на новый формат
    callback.data = f"vieword_{category}_{order_id}"
    await view_order_details(callback)


@router.callback_query(F.data.startswith("usrord_"))
async def admin_goto_user(callback: CallbackQuery, state: FSMContext):
    """Перейти к пользователю (показать его профиль)"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    # usrord_paid_123456_789
    parts = callback.data.split("_")
    category = parts[1]
    user_id = int(parts[2])
    order_id = int(parts[3])

    # Получаем полную статистику пользователя
    user_stats = await get_user_full_stats(user_id)

    if not user_stats:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    # Формируем текст
    username = f"@{user_stats['username']}" if user_stats['username'] else "Нет"
    ref_code = user_stats['referral_code'] if user_stats['referral_code'] else "Нет"

    text = (
        f"👤 Пользователь\n\n"
        f"UID: #{user_stats['uid']}\n"
        f"Telegram: {user_stats['user_id']}\n"
        f"Имя: {user_stats['first_name']}\n"
        f"Username: {username}\n"
        f"Баланс: {user_stats['balance']:.0f} ₽\n"
        f"Заказов: {user_stats['orders_count']}\n"
        f"Потрачено: {user_stats['total_spent']:.0f} ₽\n"
        f"Рег-ция: {user_stats['registered_at']}"
    )

    keyboard = [
        [InlineKeyboardButton(text="« Назад к заказу", callback_data=f"vieword_{category}_{order_id}")]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


# Сохраняем совместимость со старым callback
@router.callback_query(F.data.startswith("admin_goto_user_"))
async def admin_goto_user_legacy(callback: CallbackQuery, state: FSMContext):
    """Перейти к пользователю (старый формат)"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    user_id = int(callback.data.replace("admin_goto_user_", ""))

    user_stats = await get_user_full_stats(user_id)

    if not user_stats:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    username = f"@{user_stats['username']}" if user_stats['username'] else "Нет"

    text = (
        f"👤 Пользователь\n\n"
        f"UID: #{user_stats['uid']}\n"
        f"Telegram: {user_stats['user_id']}\n"
        f"Имя: {user_stats['first_name']}\n"
        f"Username: {username}\n"
        f"Баланс: {user_stats['balance']:.0f} ₽\n"
        f"Заказов: {user_stats['orders_count']}\n"
        f"Потрачено: {user_stats['total_spent']:.0f} ₽"
    )

    keyboard = [
        [InlineKeyboardButton(text="« Назад к заказам", callback_data="admin_orders")]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("conford_"))
async def ask_confirm_order(callback: CallbackQuery):
    """Запросить подтверждение выполнения заказа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    parts = callback.data.split("_")
    category = parts[1]
    order_id = int(parts[2])

    keyboard = [
        [InlineKeyboardButton(text="✅ Да, выполнен", callback_data=f"confyes_{category}_{order_id}")],
        [InlineKeyboardButton(text="« Отмена", callback_data=f"vieword_{category}_{order_id}")]
    ]

    await callback.message.edit_text(
        f"Подтвердить заказ #{order_id}?\n\n"
        f"Заказ будет помечен как выполненный.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


# Совместимость со старым форматом
@router.callback_query(F.data.startswith("admin_confirm_order_"))
async def ask_confirm_order_legacy(callback: CallbackQuery):
    order_id = int(callback.data.replace("admin_confirm_order_", ""))
    callback.data = f"conford_paid_{order_id}"
    await ask_confirm_order(callback)


@router.callback_query(F.data.startswith("confyes_"))
async def confirm_order_final(callback: CallbackQuery):
    """Финальное подтверждение заказа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    parts = callback.data.split("_")
    category = parts[1]
    order_id = int(parts[2])

    await confirm_order(order_id)

    await callback.answer("Заказ выполнен!", show_alert=True)

    # Возвращаемся к списку
    callback.data = f"orders_{category}_0"
    if category == "paid":
        await show_paid_orders(callback)
    else:
        await show_unpaid_orders(callback)


# Совместимость
@router.callback_query(F.data.startswith("confirm_yes_"))
async def confirm_order_final_legacy(callback: CallbackQuery):
    order_id = int(callback.data.replace("confirm_yes_", ""))
    callback.data = f"confyes_paid_{order_id}"
    await confirm_order_final(callback)


@router.callback_query(F.data.startswith("cancord_"))
async def ask_cancel_order(callback: CallbackQuery):
    """Запросить подтверждение отмены заказа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    parts = callback.data.split("_")
    category = parts[1]
    order_id = int(parts[2])

    keyboard = [
        [InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"cancyes_{category}_{order_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"vieword_{category}_{order_id}")]
    ]

    await callback.message.edit_text(
        f"Отменить заказ #{order_id}?\n\n"
        f"Деньги будут возвращены на баланс.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


# Совместимость
@router.callback_query(F.data.startswith("admin_cancel_order_"))
async def ask_cancel_order_legacy(callback: CallbackQuery):
    order_id = int(callback.data.replace("admin_cancel_order_", ""))
    callback.data = f"cancord_paid_{order_id}"
    await ask_cancel_order(callback)


@router.callback_query(F.data.startswith("cancyes_"))
async def cancel_order_final(callback: CallbackQuery):
    """Финальная отмена заказа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    parts = callback.data.split("_")
    category = parts[1]
    order_id = int(parts[2])

    success = await cancel_order(order_id)

    if success:
        await callback.answer("Заказ отменён, деньги возвращены!", show_alert=True)
    else:
        await callback.answer("Ошибка отмены", show_alert=True)

    # Возвращаемся к списку
    callback.data = f"orders_{category}_0"
    if category == "paid":
        await show_paid_orders(callback)
    else:
        await show_unpaid_orders(callback)


# Совместимость
@router.callback_query(F.data.startswith("cancel_yes_"))
async def cancel_order_final_legacy(callback: CallbackQuery):
    order_id = int(callback.data.replace("cancel_yes_", ""))
    callback.data = f"cancyes_paid_{order_id}"
    await cancel_order_final(callback)
