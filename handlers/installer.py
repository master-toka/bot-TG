from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import datetime

from database import async_session, User, Request, Refusal, GroupMessage, District
from keyboards.inline import get_complete_keyboard, get_installer_requests_keyboard, get_installer_all_requests_keyboard, get_request_action_keyboard

router = Router()

class CancelRequestState(StatesGroup):
    waiting_reason = State()

async def send_request_to_group(bot, request: Request, session: AsyncSession):
    """Отправка заявки в группу монтажников"""
    from config import GROUP_ID
    from keyboards.inline import get_request_action_keyboard
    
    # Получаем название района
    district = await session.get(District, request.district_id)
    
    # Формируем текст заявки
    text = (
        f"🔔 <b>Новая заявка №{request.id}</b>\n\n"
        f"👤 Клиент: {request.client.name}\n"
        f"📞 Телефон: {request.contact_phone}\n"
        f"📍 Район: {district.name}\n"
        f"🏠 Адрес: {request.address or 'Не указан'}\n"
        f"📝 Описание: {request.description}\n\n"
        f"Статус: 🆕 Новая"
    )
    
    # Отправляем сообщение с фото
    if request.photo_file_id:
        photo_ids = request.photo_file_id.split(',')
        if len(photo_ids) > 1:
            media_group = []
            for i, photo_id in enumerate(photo_ids):
                if i == 0:
                    media_group.append(
                        InputMediaPhoto(
                            media=photo_id,
                            caption=text
                        )
                    )
                else:
                    media_group.append(InputMediaPhoto(media=photo_id))
            
            messages = await bot.send_media_group(
                chat_id=GROUP_ID,
                media=media_group
            )
            main_message_id = messages[0].message_id
        else:
            msg = await bot.send_photo(
                chat_id=GROUP_ID,
                photo=photo_ids[0],
                caption=text,
                reply_markup=get_request_action_keyboard(request.id)
            )
            main_message_id = msg.message_id
    else:
        msg = await bot.send_message(
            chat_id=GROUP_ID,
            text=text,
            reply_markup=get_request_action_keyboard(request.id)
        )
        main_message_id = msg.message_id
    
    # Если есть координаты, отправляем их отдельно
    if request.latitude and request.longitude:
        await bot.send_location(
            chat_id=GROUP_ID,
            latitude=request.latitude,
            longitude=request.longitude,
            reply_to_message_id=main_message_id
        )
    
    # Сохраняем информацию о сообщении в группе
    group_msg = GroupMessage(
        request_id=request.id,
        group_chat_id=GROUP_ID,
        message_id=main_message_id
    )
    session.add(group_msg)

@router.callback_query(F.data.startswith("take_"))
async def take_request(callback: CallbackQuery):
    """Монтажник берет заявку"""
    request_id = int(callback.data.split("_")[1])
    
    async with async_session() as session:
        # Получаем заявку с предзагрузкой связанного клиента
        result = await session.execute(
            select(Request)
            .options(selectinload(Request.client))
            .where(Request.id == request_id)
        )
        request = result.scalar_one_or_none()
        
        if not request or request.status != 'new':
            await callback.answer("❌ Заявка уже недоступна", show_alert=True)
            return
        
        # Получаем монтажника
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        installer = result.scalar_one_or_none()
        
        if not installer or installer.role != 'installer':
            await callback.answer("❌ Вы не монтажник", show_alert=True)
            return
        
        # Назначаем монтажника
        request.status = 'in_progress'
        request.installer_id = installer.id
        request.assigned_at = datetime.now()
        
        # Обновляем сообщение в группе
        try:
            await callback.message.edit_caption(
                caption=f"{callback.message.caption}\n\n🔨 Взял: @{installer.username or installer.name}",
                reply_markup=None
            )
        except:
            try:
                await callback.message.edit_text(
                    text=f"{callback.message.text}\n\n🔨 Взял: @{installer.username or installer.name}",
                    reply_markup=None
                )
            except:
                pass
        
        # Уведомляем заказчика
        await callback.bot.send_message(
            chat_id=request.client.telegram_id,
            text=(
                f"🔔 <b>Заявка №{request.id} взята в работу!</b>\n\n"
                f"Монтажник: @{installer.username or installer.name}\n"
                f"Свяжитесь с ним для уточнения деталей."
            )
        )
        
        # Отправляем детали монтажнику в ЛС
        await send_request_details_to_installer(callback.bot, installer.telegram_id, request, session)
        
        await session.commit()
    
    await callback.answer("✅ Заявка взята в работу!")

@router.callback_query(F.data.startswith("refuse_"))
async def refuse_request(callback: CallbackQuery, state: FSMContext):
    """Монтажник отказывается от заявки (из группы)"""
    request_id = int(callback.data.split("_")[1])
    
    await state.update_data(refuse_request_id=request_id)
    await callback.message.answer(
        "❓ Укажите причину отказа (отправьте текстовое сообщение):"
    )
    await state.set_state("waiting_refuse_reason")
    await callback.answer()

@router.message(F.state == "waiting_refuse_reason")
async def process_refuse_reason(message: Message, state: FSMContext):
    """Обработка причины отказа из группы"""
    data = await state.get_data()
    request_id = data['refuse_request_id']
    reason = message.text
    
    async with async_session() as session:
        # Получаем монтажника
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        installer = result.scalar_one()
        
        # Получаем заявку
        result = await session.execute(
            select(Request).where(Request.id == request_id)
        )
        request = result.scalar_one_or_none()
        
        if request and request.status == 'new':
            # Сохраняем отказ
            refusal = Refusal(
                request_id=request_id,
                installer_id=installer.id,
                reason=reason
            )
            session.add(refusal)
            
            # Обновляем сообщение в группе
            result = await session.execute(
                select(GroupMessage).where(GroupMessage.request_id == request_id)
            )
            group_msg = result.scalar_one_or_none()
            
            if group_msg:
                try:
                    await message.bot.edit_message_caption(
                        chat_id=group_msg.group_chat_id,
                        message_id=group_msg.message_id,
                        caption=f"{group_msg.caption}\n\n⚠️ Отказ от @{installer.username}: {reason}"
                    )
                except:
                    try:
                        await message.bot.edit_message_text(
                            chat_id=group_msg.group_chat_id,
                            message_id=group_msg.message_id,
                            text=f"{group_msg.text}\n\n⚠️ Отказ от @{installer.username}: {reason}"
                        )
                    except:
                        pass
            
            await session.commit()
            await message.answer("✅ Отказ зарегистрирован")
        else:
            await message.answer("❌ Заявка уже недоступна для отказа")
    
    await state.clear()

@router.callback_query(F.data.startswith("cancel_request_"))
async def cancel_own_request(callback: CallbackQuery, state: FSMContext):
    """Монтажник отменяет свою заявку (возврат в статус new)"""
    request_id = int(callback.data.split("_")[2])
    
    await state.update_data(cancel_request_id=request_id)
    await callback.message.answer(
        "❓ Укажите причину отмены заявки (отправьте текстовое сообщение):"
    )
    await state.set_state(CancelRequestState.waiting_reason)
    await callback.answer()

@router.message(CancelRequestState.waiting_reason)
async def process_cancel_reason(message: Message, state: FSMContext):
    """Обработка причины отмены заявки"""
    data = await state.get_data()
    request_id = data['cancel_request_id']
    reason = message.text
    
    async with async_session() as session:
        # Получаем монтажника
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        installer = result.scalar_one()
        
        # Получаем заявку
        result = await session.execute(
            select(Request)
            .options(selectinload(Request.client))
            .where(Request.id == request_id)
        )
        request = result.scalar_one_or_none()
        
        if not request or request.installer_id != installer.id or request.status != 'in_progress':
            await message.answer("❌ Нельзя отменить эту заявку")
            await state.clear()
            return
        
        # Сохраняем отказ
        refusal = Refusal(
            request_id=request_id,
            installer_id=installer.id,
            reason=f"Отмена: {reason}"
        )
        session.add(refusal)
        
        # Возвращаем заявку в статус new
        request.status = 'new'
        request.installer_id = None
        request.assigned_at = None
        
        # Обновляем сообщение в группе - делаем заявку снова доступной
        result = await session.execute(
            select(GroupMessage).where(GroupMessage.request_id == request_id)
        )
        group_msg = result.scalar_one_or_none()
        
        if group_msg:
            # Получаем район для обновленного сообщения
            district = await session.get(District, request.district_id)
            
            # Формируем текст заявки
            text = (
                f"🔔 <b>Новая заявка №{request.id}</b>\n\n"
                f"👤 Клиент: {request.client.name}\n"
                f"📞 Телефон: {request.contact_phone}\n"
                f"📍 Район: {district.name}\n"
                f"🏠 Адрес: {request.address or 'Не указан'}\n"
                f"📝 Описание: {request.description}\n\n"
                f"⚠️ Отменена предыдущим монтажником. Снова доступна!"
            )
            
            try:
                await message.bot.edit_message_caption(
                    chat_id=group_msg.group_chat_id,
                    message_id=group_msg.message_id,
                    caption=text,
                    reply_markup=get_request_action_keyboard(request.id)
                )
            except:
                try:
                    await message.bot.edit_message_text(
                        chat_id=group_msg.group_chat_id,
                        message_id=group_msg.message_id,
                        text=text,
                        reply_markup=get_request_action_keyboard(request.id)
                    )
                except:
                    pass
        
        # Уведомляем заказчика
        await message.bot.send_message(
            chat_id=request.client.telegram_id,
            text=(
                f"⚠️ <b>Заявка №{request.id} отменена монтажником</b>\n\n"
                f"Причина: {reason}\n"
                f"Заявка снова доступна для других монтажников."
            )
        )
        
        await session.commit()
    
    await message.answer("✅ Заявка отменена и возвращена в общий список")
    await state.clear()

@router.message(F.text == "📋 Активные заявки")
@router.message(Command("my_requests"))
async def my_requests(message: Message):
    """Список активных заявок монтажника"""
    async with async_session() as session:
        # Получаем монтажника
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        installer = result.scalar_one_or_none()
        
        if not installer or installer.role != 'installer':
            await message.answer("❌ Эта функция доступна только монтажникам")
            return
        
        # Получаем активные заявки
        result = await session.execute(
            select(Request)
            .options(selectinload(Request.client))
            .where(
                Request.installer_id == installer.id,
                Request.status == 'in_progress'
            )
        )
        requests = result.scalars().all()
        
        if not requests:
            await message.answer("📭 У вас нет активных заявок")
            return
        
        # Показываем количество активных заявок
        await message.answer(
            f"📋 <b>Ваши активные заявки ({len(requests)})</b>\n\n"
            f"Выберите заявку для просмотра деталей:",
            reply_markup=get_installer_requests_keyboard(requests)
        )

@router.message(F.text == "📊 Все мои заявки")
@router.message(Command("my_all_requests"))
async def my_all_requests(message: Message):
    """Все заявки монтажника"""
    async with async_session() as session:
        # Получаем монтажника
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        installer = result.scalar_one_or_none()
        
        if not installer or installer.role != 'installer':
            await message.answer("❌ Эта функция доступна только монтажникам")
            return
        
        # Получаем все заявки монтажника
        result = await session.execute(
            select(Request)
            .options(selectinload(Request.client))
            .where(Request.installer_id == installer.id)
            .order_by(Request.created_at.desc())
        )
        all_requests = result.scalars().all()
        
        if not all_requests:
            await message.answer("📭 У вас ещё нет взятых заявок")
            return
        
        # Статистика
        completed = sum(1 for r in all_requests if r.status == 'completed')
        in_progress = sum(1 for r in all_requests if r.status == 'in_progress')
        
        text = (
            f"📊 <b>Все ваши заявки</b>\n\n"
            f"📋 Всего взято заявок: {len(all_requests)}\n"
            f"🔨 В работе: {in_progress}\n"
            f"✅ Выполнено: {completed}\n\n"
            f"Выберите заявку для просмотра деталей:"
        )
        
        keyboard = await get_installer_all_requests_keyboard(installer.id)
        await message.answer(text, reply_markup=keyboard)

@router.message(F.text == "📊 Статистика")
async def stats_button(message: Message):
    """Статистика монтажника"""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or user.role != 'installer':
            await message.answer("❌ Эта функция доступна только монтажникам")
            return
        
        # Получаем статистику
        requests_result = await session.execute(
            select(Request).where(Request.installer_id == user.id)
        )
        all_requests = requests_result.scalars().all()
        completed = sum(1 for r in all_requests if r.status == 'completed')
        in_progress = sum(1 for r in all_requests if r.status == 'in_progress')
        
        refusals_result = await session.execute(
            select(Refusal).where(Refusal.installer_id == user.id)
        )
        refusals = refusals_result.scalars().all()
        
        # Получаем рейтинг
        rating = completed - len(refusals)
        
        text = (
            f"📊 <b>Ваша статистика</b>\n\n"
            f"📋 Всего заявок взято: {len(all_requests)}\n"
            f"🔨 В работе: {in_progress}\n"
            f"✅ Выполнено: {completed}\n"
            f"❌ Отказов: {len(refusals)}\n"
            f"⭐ Рейтинг: {rating}\n\n"
            f"📈 <b>Процент выполнения:</b> "
            f"{int(completed/len(all_requests)*100) if all_requests else 0}%"
        )
        
        await message.answer(text)

async def send_request_details_to_installer(bot, installer_id: int, request: Request, session: AsyncSession):
    """Отправка деталей заявки монтажнику в ЛС с кнопками"""
    # Получаем район и клиента
    district = await session.get(District, request.district_id)
    client = await session.get(User, request.client_id)
    
    text = (
        f"🔨 <b>Заявка №{request.id} (в работе)</b>\n\n"
        f"📝 <b>Описание:</b> {request.description}\n"
        f"📍 <b>Район:</b> {district.name}\n"
        f"🏠 <b>Адрес:</b> {request.address}\n"
        f"📞 <b>Телефон клиента:</b> {request.contact_phone}\n"
        f"👤 <b>Клиент:</b> {client.name or 'Не указано'}\n"
        f"📅 <b>Взята в работу:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
    )
    
    # Создаем клавиатуру с действиями
    keyboard_buttons = []
    
    # Кнопка для связи с клиентом (написать)
    if client and client.username:
        keyboard_buttons.append([
            InlineKeyboardButton(
                text="💬 Написать клиенту",
                url=f"https://t.me/{client.username}"
            )
        ])
    elif client:
        keyboard_buttons.append([
            InlineKeyboardButton(
                text="💬 Написать клиенту",
                url=f"tg://user?id={client.telegram_id}"
            )
        ])
    
    # Кнопка для открытия на карте
    if request.latitude and request.longitude:
        keyboard_buttons.append([
            InlineKeyboardButton(
                text="🗺 Открыть на карте",
                url=f"https://yandex.ru/maps/?pt={request.longitude},{request.latitude}&z=17&l=map"
            )
        ])
    
    # Кнопка для звонка
    phone = request.contact_phone
    if phone:
        # Очищаем номер от лишних символов
        clean_phone = ''.join(filter(str.isdigit, phone))
        if clean_phone:
            # Добавляем + если его нет
            if not clean_phone.startswith('7') and not clean_phone.startswith('8'):
                clean_phone = '7' + clean_phone
            tel_url = f"tel:+{clean_phone}"
            
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text="📞 Позвонить клиенту",
                    url=tel_url
                )
            ])
    
    # Кнопка завершения заявки
    keyboard_buttons.append([
        InlineKeyboardButton(text="✅ Завершить заявку", callback_data=f"complete_{request.id}")
    ])
    
    # Кнопка отмены заявки (возврат в статус new)
    keyboard_buttons.append([
        InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_request_{request.id}")
    ])
    
    # Создаем клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    # Отправляем фото если есть
    if request.photo_file_id:
        photo_ids = request.photo_file_id.split(',')
        try:
            # Отправляем первое фото с подписью и клавиатурой
            await bot.send_photo(
                chat_id=installer_id,
                photo=photo_ids[0],
                caption=text,
                reply_markup=keyboard
            )
            # Отправляем остальные фото без клавиатуры
            for i, photo_id in enumerate(photo_ids[1:], 2):
                await bot.send_photo(
                    chat_id=installer_id,
                    photo=photo_id,
                    caption=f"Фото {i} к заявке №{request.id}"
                )
        except Exception as e:
            print(f"Ошибка при отправке фото: {e}")
            # Если не получилось отправить фото, отправляем только текст
            await bot.send_message(
                chat_id=installer_id,
                text=text,
                reply_markup=keyboard
            )
    else:
        await bot.send_message(
            chat_id=installer_id,
            text=text,
            reply_markup=keyboard
        )

@router.callback_query(F.data.startswith("view_"))
async def view_request(callback: CallbackQuery):
    """Просмотр деталей заявки"""
    request_id = int(callback.data.split("_")[1])
    
    async with async_session() as session:
        # Получаем заявку с предзагрузкой связанных объектов
        result = await session.execute(
            select(Request)
            .options(selectinload(Request.client))
            .where(Request.id == request_id)
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return
        
        district = await session.get(District, request.district_id)
        client = request.client
        
        # Получаем текущего пользователя
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        current_user = result.scalar_one_or_none()
        
        text = (
            f"🔨 <b>Заявка №{request.id}</b>\n\n"
            f"📝 <b>Описание:</b> {request.description}\n"
            f"📍 <b>Район:</b> {district.name}\n"
            f"🏠 <b>Адрес:</b> {request.address}\n"
            f"📞 <b>Телефон клиента:</b> {request.contact_phone}\n"
            f"👤 <b>Клиент:</b> {client.name or 'Не указано'}\n"
            f"📊 <b>Статус:</b> {request.status}\n"
            f"📅 <b>Создана:</b> {request.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        )
        
        if request.assigned_at:
            text += f"📅 <b>Взята в работу:</b> {request.assigned_at.strftime('%d.%m.%Y %H:%M')}\n"
        if request.completed_at:
            text += f"📅 <b>Завершена:</b> {request.completed_at.strftime('%d.%m.%Y %H:%M')}\n"
        
        keyboard_buttons = []
        
        # Кнопка для связи с клиентом (всегда показываем, если есть клиент)
        if client:
            if client.username:
                keyboard_buttons.append([
                    InlineKeyboardButton(
                        text="💬 Написать клиенту",
                        url=f"https://t.me/{client.username}"
                    )
                ])
            else:
                keyboard_buttons.append([
                    InlineKeyboardButton(
                        text="💬 Написать клиенту",
                        url=f"tg://user?id={client.telegram_id}"
                    )
                ])
        
        # Кнопка для открытия на карте
        if request.latitude and request.longitude:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text="🗺 Открыть на карте",
                    url=f"https://yandex.ru/maps/?pt={request.longitude},{request.latitude}&z=17&l=map"
                )
            ])
        
        # Кнопка для звонка
        phone = request.contact_phone
        if phone:
            clean_phone = ''.join(filter(str.isdigit, phone))
            if clean_phone:
                if not clean_phone.startswith('7') and not clean_phone.startswith('8'):
                    clean_phone = '7' + clean_phone
                tel_url = f"tel:+{clean_phone}"
                keyboard_buttons.append([
                    InlineKeyboardButton(
                        text="📞 Позвонить клиенту",
                        url=tel_url
                    )
                ])
        
        # Кнопки для активных заявок текущего монтажника
        if request.status == 'in_progress' and current_user and current_user.id == request.installer_id:
            keyboard_buttons.append([
                InlineKeyboardButton(text="✅ Завершить заявку", callback_data=f"complete_{request.id}")
            ])
            keyboard_buttons.append([
                InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_request_{request.id}")
            ])
        
        # Кнопка назад
        keyboard_buttons.append([
            InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="back_to_list")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        # Отправляем сообщение
        if request.photo_file_id:
            photo_ids = request.photo_file_id.split(',')
            try:
                # Пробуем отредактировать существующее сообщение
                await callback.message.delete()
                await callback.bot.send_photo(
                    chat_id=callback.from_user.id,
                    photo=photo_ids[0],
                    caption=text,
                    reply_markup=keyboard
                )
            except:
                # Если не получается, отправляем новое
                await callback.message.answer(text, reply_markup=keyboard)
        else:
            try:
                await callback.message.edit_text(text, reply_markup=keyboard)
            except:
                await callback.message.answer(text, reply_markup=keyboard)
    
    await callback.answer()

@router.callback_query(F.data.startswith("complete_"))
async def complete_request(callback: CallbackQuery):
    """Завершение заявки"""
    request_id = int(callback.data.split("_")[1])
    
    async with async_session() as session:
        # Получаем заявку с предзагрузкой клиента
        result = await session.execute(
            select(Request)
            .options(selectinload(Request.client))
            .where(Request.id == request_id)
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return
        
        # Проверяем, что это заявка текущего монтажника
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        current_user = result.scalar_one_or_none()
        
        if not current_user or current_user.id != request.installer_id:
            await callback.answer("❌ Это не ваша заявка", show_alert=True)
            return
        
        if request.status != 'in_progress':
            await callback.answer("❌ Заявка не в работе", show_alert=True)
            return
        
        request.status = 'completed'
        request.completed_at = datetime.now()
        
        # Уведомляем заказчика
        await callback.bot.send_message(
            chat_id=request.client.telegram_id,
            text=(
                f"✅ <b>Заявка №{request.id} выполнена!</b>\n\n"
                f"Монтажник завершил работу.\n"
                f"Спасибо за обращение!"
            )
        )
        
        # Обновляем сообщение в группе
        result = await session.execute(
            select(GroupMessage).where(GroupMessage.request_id == request_id)
        )
        group_msg = result.scalar_one_or_none()
        
        if group_msg:
            try:
                await callback.bot.edit_message_caption(
                    chat_id=group_msg.group_chat_id,
                    message_id=group_msg.message_id,
                    caption=f"{group_msg.caption}\n\n✅ Заявка выполнена!",
                    reply_markup=None
                )
            except:
                try:
                    await callback.bot.edit_message_text(
                        chat_id=group_msg.group_chat_id,
                        message_id=group_msg.message_id,
                        text=f"{group_msg.text}\n\n✅ Заявка выполнена!",
                        reply_markup=None
                    )
                except:
                    pass
        
        await session.commit()
    
    await callback.message.edit_text(
        f"✅ Заявка №{request_id} успешно завершена!"
    )
    await callback.answer("✅ Заявка завершена")

@router.callback_query(F.data == "back_to_list")
async def back_to_list(callback: CallbackQuery, state: FSMContext):
    """Возврат к списку заявок"""
    await state.clear()
    
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        installer = result.scalar_one()
        
        result = await session.execute(
            select(Request)
            .options(selectinload(Request.client))
            .where(
                Request.installer_id == installer.id,
                Request.status == 'in_progress'
            )
        )
        requests = result.scalars().all()
        
        try:
            await callback.message.delete()
        except:
            pass
        
        if requests:
            await callback.message.answer(
                f"📋 <b>Ваши активные заявки ({len(requests)})</b>\n\n"
                f"Выберите заявку для просмотра деталей:",
                reply_markup=get_installer_requests_keyboard(requests)
            )
        else:
            await callback.message.answer("📭 У вас нет активных заявок")
    
    await callback.answer()

@router.message(Command("profile"))
@router.message(F.text == "👤 Мой профиль")
async def show_my_profile(message: Message):
    """Показать свой профиль"""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Вы не зарегистрированы. Используйте /start")
            return
        
        if user.role == 'installer':
            # Статистика для монтажника
            requests_result = await session.execute(
                select(Request).where(Request.installer_id == user.id)
            )
            all_requests = requests_result.scalars().all()
            completed = sum(1 for r in all_requests if r.status == 'completed')
            in_progress = sum(1 for r in all_requests if r.status == 'in_progress')
            
            refusals_result = await session.execute(
                select(Refusal).where(Refusal.installer_id == user.id)
            )
            refusals = refusals_result.scalars().all()
            
            text = (
                f"👷 <b>Ваш профиль монтажника</b>\n\n"
                f"📋 <b>Информация:</b>\n"
                f"• Имя: {user.name or 'Не указано'}\n"
                f"• Username: @{user.username if user.username else 'нет'}\n"
                f"• Телефон: {user.phone or 'Не указан'}\n"
                f"• Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}\n\n"
                
                f"📊 <b>Статистика:</b>\n"
                f"• Всего заявок взято: {len(all_requests)}\n"
                f"• В работе: {in_progress}\n"
                f"• Выполнено: {completed}\n"
                f"• Отказов: {len(refusals)}\n"
                f"• Рейтинг: {completed - len(refusals)}\n"
            )
            
        elif user.role == 'client':
            # Статистика для клиента
            requests_result = await session.execute(
                select(Request).where(Request.client_id == user.id)
            )
            all_requests = requests_result.scalars().all()
            completed = sum(1 for r in all_requests if r.status == 'completed')
            in_progress = sum(1 for r in all_requests if r.status == 'in_progress')
            
            text = (
                f"👤 <b>Ваш профиль клиента</b>\n\n"
                f"📋 <b>Информация:</b>\n"
                f"• Имя: {user.name or 'Не указано'}\n"
                f"• Username: @{user.username if user.username else 'нет'}\n"
                f"• Телефон: {user.phone or 'Не указан'}\n"
                f"• Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}\n\n"
                
                f"📊 <b>Статистика заявок:</b>\n"
                f"• Всего заявок: {len(all_requests)}\n"
                f"• Активных: {in_progress}\n"
                f"• Выполнено: {completed}\n"
            )
        else:
            text = "❌ Неизвестная роль"
        
        # Кнопка для открытия профиля в Telegram
        buttons = []
        if user.username:
            buttons.append([
                InlineKeyboardButton(
                    text="📱 Мой профиль в Telegram",
                    url=f"https://t.me/{user.username}"
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    text="📱 Мой ID",
                    callback_data="show_my_id"
                )
            ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        
        await message.answer(text, reply_markup=keyboard)

@router.callback_query(F.data == "show_my_id")
async def show_my_id(callback: CallbackQuery):
    """Показать свой Telegram ID"""
    await callback.message.answer(
        f"📱 <b>Ваш Telegram ID:</b>\n<code>{callback.from_user.id}</code>"
    )
    await callback.answer()
