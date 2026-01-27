from aiogram import Router, F
from aiogram.types import CallbackQuery
from database import get_or_create_user, get_user_orders_stats, get_user_uid
from keyboards import get_back_to_menu

router = Router()


@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    """Показать профиль пользователя"""
    user_id = callback.from_user.id
    first_name = callback.from_user.first_name

    # Создаем или получаем пользователя
    username = callback.from_user.username or ""
    await get_or_create_user(user_id, username, first_name)

    # Получаем UID
    uid = await get_user_uid(user_id)

    # Получаем статистику заказов
    orders_stats = await get_user_orders_stats(user_id)

    # Формируем текст о заказах
    if orders_stats['count'] == 0:
        orders_text = "Нет заказов"
    else:
        orders_text = f"Заказов: {orders_stats['count']} на сумму {orders_stats['total']:.0f} ₽"

    text = f"Профиль\n\n" \
           f"UID: #{uid}\n\n" \
           f"{orders_text}"

    try:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=get_back_to_menu()
        )
    except:
        # Если нет caption, используем edit_text
        await callback.message.edit_text(
            text=text,
            reply_markup=get_back_to_menu()
        )
    await callback.answer()
