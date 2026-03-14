from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta

from database import async_session, User, Request, District, Refusal
from config import ADMIN_ID
from keyboards.inline import get_admin_keyboard, get_installer_requests_keyboard

router = Router()

# Фильтр для админа
async def is_admin(message: Message) -> bool:
    return message.from_user.id == ADMIN_ID

@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not await is_admin(message):
        await message.answer("❌ Доступ запрещён")
        return
    
    await message.answer(
        "👑 <b>Панель администратора</b>\n\n"
        "Выберите раздел:",
        reply_markup=get_admin_keyboard()
    )

@router.message(F.text == "👑 Админ панель")
async def admin_panel_button(message: Message):
    """Админ панель через кнопку"""
    if not await is_admin(message):
        await message.answer("❌ Доступ запрещён")
        return
    
    await message.answer(
        "👑 <b>Панель администратора</b>\n\n"
        "Выберите раздел:",
        reply_markup=get_admin_keyboard()
    )

@router.message(F.text == "📊 Общая статистика")
@router.callback_query(F.data == "admin_stats")
async def admin_stats(event: Message | CallbackQuery):
    """Общая статистика"""
    if isinstance(event, Message):
        if not await is_admin(event):
            await event.answer("❌ Доступ запрещён")
            return
        message = event
        is_callback = False
    else:
        message = event.message
        is_callback = True
    
    async with async_session() as session:
        # Общая статистика
        total = await session.scalar(select(func.count(Request.id))) or 0
        new = await session.scalar(
            select(func.count(Request.id)).where(Request.status == 'new')
        ) or 0
        in_progress = await session.scalar(
            select(func.count(Request.id)).where(Request.status == 'in_progress')
        ) or 0
        completed = await session.scalar(
            select(func.count(Request.id)).where(Request.status == 'completed')
        ) or 0
        
        # Статистика по отказам
        refusals = await session.scalar(select(func.count(Refusal.id))) or 0
        
        # Количество монтажников
        installers = await session.scalar(
            select(func.count(User.id)).where(User.role == 'installer')
        ) or 0
        
        # Количество клиентов
        clients = await session.scalar(
            select(func.count(User.id)).where(User.role == 'client')
        ) or 0
        
        text = (
            f"📊 <b>Общая статистика</b>\n\n"
            f"📌 Всего заявок: {total}\n"
            f"🆕 Новых: {new}\n"
            f"🔨 В работе: {in_progress}\n"
            f"✅ Завершено: {completed}\n"
            f"❌ Отказов: {refusals}\n"
            f"👷 Монтажников: {installers}\n"
            f"👤 Клиентов: {clients}\n"
        )
    
    if is_callback:
        await event.message.edit_text(text)
        await event.answer()
    else:
        await message.answer(text)

@router.message(F.text == "👷 Монтажники")
@router.callback_query(F.data == "admin_installers")
async def admin_installers(event: Message | CallbackQuery):
    """Список монтажников"""
    if isinstance(event, Message):
        if not await is_admin(event):
            await event.answer("❌ Доступ запрещён")
            return
        message = event
        is_callback = False
    else:
        message = event.message
        is_callback = True
    
    async with async_session() as session:
        # Получаем всех монтажников
        result = await session.execute(
            select(User).where(User.role == 'installer').order_by(User.id)
        )
        installers = result.scalars().all()
        
        if not installers:
            text = "👷 Нет зарегистрированных монтажников"
            if is_callback:
                await event.message.edit_text(text)
                await event.answer()
            else:
                await message.answer(text)
            return
        
        text = "👷 <b>Список монтажников</b>\n\n"
        
        # Создаем клавиатуру со списком монтажников
        buttons = []
        for installer in installers:
            # Получаем имя для отображения
            name = installer.name or installer.username or f"ID {installer.telegram_id}"
            if installer.username:
                display_name = f"@{installer.username}"
            else:
                display_name = name
            
            # Получаем количество активных заявок
            active = await session.scalar(
                select(func.count(Request.id)).where(
                    and_(Request.installer_id == installer.id, Request.status == 'in_progress')
                )
            ) or 0
            
            text += f"• {display_name} - активных: {active}\n"
            
            # Добавляем кнопку с монтажником
            buttons.append([
                InlineKeyboardButton(
                    text=f"{display_name} (активных: {active})",
                    callback_data=f"installer_details_{installer.id}"
                )
            ])
        
        # Добавляем кнопку "Назад"
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    if is_callback:
        await event.message.edit_text(text, reply_markup=keyboard)
        await event.answer()
    else:
        await message.answer(text, reply_markup=keyboard)

@router.message(F.text == "👤 Клиенты")
@router.callback_query(F.data == "admin_clients")
async def admin_clients(event: Message | CallbackQuery):
    """Список клиентов"""
    if isinstance(event, Message):
        if not await is_admin(event):
            await event.answer("❌ Доступ запрещён")
            return
        message = event
        is_callback = False
    else:
        message = event.message
        is_callback = True
    
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.role == 'client').order_by(User.created_at.desc()).limit(10)
        )
        clients = result.scalars().all()
        
        if not clients:
            text = "👤 Нет зарегистрированных клиентов"
            if is_callback:
                await event.message.edit_text(text)
                await event.answer()
            else:
                await message.answer(text)
            return
        
        text = "👤 <b>Последние 10 клиентов</b>\n\n"
        
        # Создаем клавиатуру со списком клиентов
        buttons = []
        for client in clients:
            name = client.name or client.username or f"ID {client.telegram_id}"
            if client.username:
                display_name = f"@{client.username}"
            else:
                display_name = name
            
            requests_count = await session.scalar(
                select(func.count(Request.id)).where(Request.client_id == client.id)
            ) or 0
            
            text += f"• {display_name} - заявок: {requests_count}\n"
            
            # Добавляем кнопку с клиентом
            buttons.append([
                InlineKeyboardButton(
                    text=f"{display_name} (заявок: {requests_count})",
                    callback_data=f"client_details_{client.id}"
                )
            ])
        
        # Добавляем кнопку "Назад"
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    if is_callback:
        await event.message.edit_text(text, reply_markup=keyboard)
        await event.answer()
    else:
        await message.answer(text, reply_markup=keyboard)

@router.message(F.text == "🏘 Районы")
@router.callback_query(F.data == "admin_districts")
async def admin_districts(event: Message | CallbackQuery):
    """Статистика по районам"""
    if isinstance(event, Message):
        if not await is_admin(event):
            await event.answer("❌ Доступ запрещён")
            return
        message = event
        is_callback = False
    else:
        message = event.message
        is_callback = True
    
    async with async_session() as session:
        districts = await session.execute(select(District).order_by(District.name))
        districts = districts.scalars().all()
        
        text = "🏘 <b>Статистика по районам</b>\n\n"
        
        for district in districts:
            total = await session.scalar(
                select(func.count(Request.id)).where(Request.district_id == district.id)
            ) or 0
            completed = await session.scalar(
                select(func.count(Request.id)).where(
                    and_(Request.district_id == district.id, Request.status == 'completed')
                )
            ) or 0
            in_progress = await session.scalar(
                select(func.count(Request.id)).where(
                    and_(Request.district_id == district.id, Request.status == 'in_progress')
                )
            ) or 0
            
            text += (
                f"• <b>{district.name}</b>\n"
                f"  Всего: {total} | ✅ {completed} | 🔨 {in_progress}\n"
            )
    
    if is_callback:
        await event.message.edit_text(text)
        await event.answer()
    else:
        await message.answer(text)

@router.callback_query(F.data.startswith("installer_details_"))
async def installer_details(callback: CallbackQuery):
    """Детальная информация о монтажнике"""
    installer_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        # Получаем монтажника
        installer = await session.get(User, installer_id)
        if not installer:
            await callback.answer("❌ Монтажник не найден", show_alert=True)
            return
        
        # Получаем все заявки монтажника
        requests_result = await session.execute(
            select(Request).where(Request.installer_id == installer_id)
        )
        all_requests = requests_result.scalars().all()
        
        # Статистика по статусам
        completed = sum(1 for r in all_requests if r.status == 'completed')
        in_progress = sum(1 for r in all_requests if r.status == 'in_progress')
        
        # Получаем отказы
        refusals_result = await session.execute(
            select(Refusal).where(Refusal.installer_id == installer_id)
        )
        refusals = refusals_result.scalars().all()
        
        # Формируем текст
        name = installer.name or installer.username or f"ID {installer.telegram_id}"
        
        text = (
            f"👷 <b>Профиль монтажника</b>\n\n"
            f"📋 <b>Основная информация:</b>\n"
            f"• Имя: {installer.name or 'Не указано'}\n"
            f"• Username: @{installer.username if installer.username else 'нет'}\n"
            f"• Telegram ID: <code>{installer.telegram_id}</code>\n"
            f"• Телефон: {installer.phone or 'Не указан'}\n"
            f"• Дата регистрации: {installer.created_at.strftime('%d.%m.%Y')}\n\n"
            
            f"📊 <b>Статистика:</b>\n"
            f"• Всего заявок взято: {len(all_requests)}\n"
            f"• В работе: {in_progress}\n"
            f"• Выполнено: {completed}\n"
            f"• Отказов: {len(refusals)}\n\n"
            
            f"✅ <b>Процент выполнения:</b> "
            f"{int(completed/len(all_requests)*100) if all_requests else 0}%\n"
            f"⭐ <b>Рейтинг:</b> {completed - len(refusals)}\n"
        )
        
        # Кнопки для действий
        buttons = []
        
        # Кнопка для открытия профиля в Telegram
        if installer.username:
            buttons.append([
                InlineKeyboardButton(
                    text="📱 Открыть профиль в Telegram",
                    url=f"https://t.me/{installer.username}"
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    text="📱 Написать сообщение",
                    url=f"tg://user?id={installer.telegram_id}"
                )
            ])
        
        # Добавляем информацию о заявках
        if in_progress > 0:
            buttons.append([
                InlineKeyboardButton(
                    text=f"🔨 Заявки в работе ({in_progress})",
                    callback_data=f"installer_requests_{installer_id}_in_progress"
                )
            ])
        
        if completed > 0:
            buttons.append([
                InlineKeyboardButton(
                    text=f"✅ Выполненные заявки ({completed})",
                    callback_data=f"installer_requests_{installer_id}_completed"
                )
            ])
        
        if len(refusals) > 0:
            buttons.append([
                InlineKeyboardButton(
                    text=f"❌ Отказы ({len(refusals)})",
                    callback_data=f"installer_refusals_{installer_id}"
                )
            ])
        
        buttons.append([
            InlineKeyboardButton(text="⬅️ К списку монтажников", callback_data="admin_installers")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    await callback.answer()

@router.callback_query(F.data.startswith("client_details_"))
async def client_details(callback: CallbackQuery):
    """Детальная информация о клиенте"""
    client_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        # Получаем клиента
        client = await session.get(User, client_id)
        if not client:
            await callback.answer("❌ Клиент не найден", show_alert=True)
            return
        
        # Получаем все заявки клиента
        requests_result = await session.execute(
            select(Request)
            .where(Request.client_id == client_id)
            .order_by(Request.created_at.desc())
        )
        all_requests = requests_result.scalars().all()
        
        # Статистика по заявкам
        total_requests = len(all_requests)
        completed = sum(1 for r in all_requests if r.status == 'completed')
        in_progress = sum(1 for r in all_requests if r.status == 'in_progress')
        new = sum(1 for r in all_requests if r.status == 'new')
        
        # Формируем текст
        name = client.name or client.username or f"ID {client.telegram_id}"
        
        text = (
            f"👤 <b>Профиль клиента</b>\n\n"
            f"📋 <b>Основная информация:</b>\n"
            f"• Имя: {client.name or 'Не указано'}\n"
            f"• Username: @{client.username if client.username else 'нет'}\n"
            f"• Telegram ID: <code>{client.telegram_id}</code>\n"
            f"• Телефон: {client.phone or 'Не указан'}\n"
            f"• Дата регистрации: {client.created_at.strftime('%d.%m.%Y')}\n\n"
            
            f"📊 <b>Статистика заявок:</b>\n"
            f"• Всего заявок: {total_requests}\n"
            f"• Активных: {in_progress}\n"
            f"• Выполнено: {completed}\n"
            f"• Новых: {new}\n\n"
        )
        
        # Кнопки для действий
        buttons = []
        
        # Кнопка для открытия профиля в Telegram
        if client.username:
            buttons.append([
                InlineKeyboardButton(
                    text="📱 Открыть профиль в Telegram",
                    url=f"https://t.me/{client.username}"
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    text="📱 Написать сообщение",
                    url=f"tg://user?id={client.telegram_id}"
                )
            ])
        
        # Кнопка для просмотра заявок клиента
        if total_requests > 0:
            buttons.append([
                InlineKeyboardButton(
                    text=f"📋 Все заявки клиента ({total_requests})",
                    callback_data=f"client_requests_{client_id}"
                )
            ])
        
        buttons.append([
            InlineKeyboardButton(text="⬅️ К списку клиентов", callback_data="admin_clients")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    await callback.answer()

@router.callback_query(F.data.startswith("client_requests_"))
async def client_requests_list(callback: CallbackQuery):
    """Список заявок клиента"""
    client_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        # Получаем клиента
        client = await session.get(User, client_id)
        
        # Получаем заявки клиента
        result = await session.execute(
            select(Request)
            .where(Request.client_id == client_id)
            .order_by(Request.created_at.desc())
        )
        requests = result.scalars().all()
        
        if not requests:
            await callback.answer("❌ Заявки не найдены", show_alert=True)
            return
        
        text = f"📋 <b>Заявки клиента</b> {client.name or client.username}\n\n"
        
        for req in requests[:10]:  # Показываем только первые 10
            # Получаем статус
            status_emoji = "✅" if req.status == 'completed' else "🔨" if req.status == 'in_progress' else "🆕"
            date_str = req.created_at.strftime('%d.%m.%Y')
            
            text += (
                f"━━━━━━━━━━━━━━━\n"
                f"{status_emoji} <b>Заявка №{req.id}</b> от {date_str}\n"
                f"📍 Адрес: {req.address}\n"
                f"📊 Статус: {req.status}\n"
            )
            
            # Если есть монтажник, показываем его
            if req.installer_id:
                installer = await session.get(User, req.installer_id)
                if installer:
                    text += f"👷 Монтажник: @{installer.username if installer.username else installer.name}\n"
        
        if len(requests) > 10:
            text += f"\n... и еще {len(requests) - 10} заявок"
        
        buttons = [[
            InlineKeyboardButton(
                text="⬅️ Назад к клиенту",
                callback_data=f"client_details_{client_id}"
            )
        ]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    await callback.answer()

@router.callback_query(F.data.startswith("installer_requests_"))
async def installer_requests_list(callback: CallbackQuery):
    """Список заявок монтажника по статусу"""
    parts = callback.data.split("_")
    installer_id = int(parts[2])
    status = parts[3]  # in_progress или completed
    
    async with async_session() as session:
        # Получаем монтажника
        installer = await session.get(User, installer_id)
        
        # Получаем заявки
        result = await session.execute(
            select(Request)
            .where(
                and_(Request.installer_id == installer_id, Request.status == status)
            )
            .order_by(Request.created_at.desc())
        )
        requests = result.scalars().all()
        
        if not requests:
            await callback.answer("❌ Заявки не найдены", show_alert=True)
            return
        
        status_text = "в работе" if status == "in_progress" else "выполненных"
        text = f"📋 <b>{status_text.capitalize()} заявки</b> монтажника {installer.name or installer.username}\n\n"
        
        for req in requests[:10]:  # Показываем только первые 10
            date_str = req.created_at.strftime('%d.%m.%Y %H:%M')
            text += (
                f"━━━━━━━━━━━━━━━\n"
                f"📌 <b>Заявка №{req.id}</b> от {date_str}\n"
                f"📍 Адрес: {req.address}\n"
                f"📞 Телефон: {req.contact_phone}\n"
            )
            
            if req.completed_at and status == 'completed':
                complete_date = req.completed_at.strftime('%d.%m.%Y %H:%M')
                text += f"✅ Завершена: {complete_date}\n"
        
        if len(requests) > 10:
            text += f"\n... и еще {len(requests) - 10} заявок"
        
        buttons = [[
            InlineKeyboardButton(
                text="⬅️ Назад к монтажнику",
                callback_data=f"installer_details_{installer_id}"
            )
        ]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    await callback.answer()

@router.callback_query(F.data.startswith("installer_refusals_"))
async def installer_refusals_list(callback: CallbackQuery):
    """Список отказов монтажника"""
    installer_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        # Получаем монтажника
        installer = await session.get(User, installer_id)
        
        # Получаем отказы
        result = await session.execute(
            select(Refusal)
            .where(Refusal.installer_id == installer_id)
            .order_by(Refusal.created_at.desc())
        )
        refusals = result.scalars().all()
        
        if not refusals:
            await callback.answer("❌ Отказы не найдены", show_alert=True)
            return
        
        text = f"❌ <b>Отказы</b> монтажника {installer.name or installer.username}\n\n"
        
        for refusal in refusals[:10]:
            date_str = refusal.created_at.strftime('%d.%m.%Y %H:%M')
            text += (
                f"━━━━━━━━━━━━━━━\n"
                f"📌 <b>Заявка №{refusal.request_id}</b>\n"
                f"📅 Дата: {date_str}\n"
                f"📝 Причина: {refusal.reason}\n"
            )
        
        if len(refusals) > 10:
            text += f"\n... и еще {len(refusals) - 10} отказов"
        
        buttons = [[
            InlineKeyboardButton(
                text="⬅️ Назад к монтажнику",
                callback_data=f"installer_details_{installer_id}"
            )
        ]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    await callback.answer()

@router.callback_query(F.data == "admin_period")
async def admin_period(callback: CallbackQuery):
    """Статистика за последние 7 дней"""
    async with async_session() as session:
        week_ago = datetime.now() - timedelta(days=7)
        
        # Заявки за неделю
        new_week = await session.scalar(
            select(func.count(Request.id)).where(
                and_(Request.status == 'new', Request.created_at >= week_ago)
            )
        ) or 0
        
        completed_week = await session.scalar(
            select(func.count(Request.id)).where(
                and_(Request.status == 'completed', Request.completed_at >= week_ago)
            )
        ) or 0
        
        # Активные монтажники (те, кто взял заявки за неделю)
        active_installers = await session.scalar(
            select(func.count(func.distinct(Request.installer_id))).where(
                and_(Request.installer_id.isnot(None), Request.assigned_at >= week_ago)
            )
        ) or 0
        
        # Активные клиенты (те, кто создал заявки за неделю)
        active_clients = await session.scalar(
            select(func.count(func.distinct(Request.client_id))).where(
                Request.created_at >= week_ago
            )
        ) or 0
        
        # Топ монтажников за неделю
        top_installers_result = await session.execute(
            select(Request.installer_id, func.count(Request.id).label('count'))
            .where(
                and_(
                    Request.installer_id.isnot(None),
                    Request.status == 'completed',
                    Request.completed_at >= week_ago
                )
            )
            .group_by(Request.installer_id)
            .order_by(func.count(Request.id).desc())
            .limit(3)
        )
        top_installers = top_installers_result.all()
        
        text = (
            f"📅 <b>Статистика за последние 7 дней</b>\n\n"
            f"🆕 Новых заявок: {new_week}\n"
            f"✅ Выполнено заявок: {completed_week}\n"
            f"👷 Активных монтажников: {active_installers}\n"
            f"👤 Активных клиентов: {active_clients}\n"
        )
        
        if top_installers:
            text += "\n🏆 <b>Топ монтажников недели:</b>\n"
            for i, (installer_id, count) in enumerate(top_installers, 1):
                installer = await session.get(User, installer_id)
                name = installer.name or installer.username or f"ID {installer_id}"
                text += f"{i}. {name} - {count} заявок\n"
    
    buttons = [[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery):
    """Возврат в админ-панель"""
    await callback.message.edit_text(
        "👑 <b>Панель администратора</b>\n\n"
        "Выберите раздел:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()