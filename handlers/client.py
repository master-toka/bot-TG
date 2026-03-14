from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto, ReplyKeyboardRemove
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import async_session, User, Request, District, GroupMessage
from keyboards.inline import districts_keyboard, get_geo_choice_keyboard, get_confirm_address_keyboard
from config import GROUP_ID
from utils.geocoder import reverse_geocode

# Импортируем функции из installer.py для обработки кнопок монтажника
from handlers.installer import my_requests as installer_my_requests
from handlers.installer import my_all_requests as installer_my_all_requests
from handlers.installer import show_my_profile as installer_show_profile
from handlers.installer import stats_button as installer_stats

router = Router()

class RequestForm(StatesGroup):
    description = State()
    photos = State()
    address_choice = State()
    manual_address = State()
    location = State()
    phone = State()
    district = State()

# Клавиатура для заказчика
def get_client_main_keyboard():
    """Главная клавиатура заказчика"""
    buttons = [
        [KeyboardButton(text="📝 Новая заявка")],
        [KeyboardButton(text="📋 Мои заявки"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="❓ Помощь")]
    ]
    keyboard = ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )
    return keyboard

# Клавиатура для монтажника
def get_installer_main_keyboard():
    """Главная клавиатура монтажника"""
    buttons = [
        [KeyboardButton(text="📋 Активные заявки"), KeyboardButton(text="📊 Все мои заявки")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="❓ Помощь")]
    ]
    keyboard = ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )
    return keyboard

# Клавиатура для администратора
def get_admin_main_keyboard():
    """Главная клавиатура администратора"""
    buttons = [
        [KeyboardButton(text="👑 Админ панель")],
        [KeyboardButton(text="📊 Общая статистика"), KeyboardButton(text="👷 Монтажники")],
        [KeyboardButton(text="👤 Клиенты"), KeyboardButton(text="🏘 Районы")],
        [KeyboardButton(text="❓ Помощь")]
    ]
    keyboard = ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )
    return keyboard

def get_location_keyboard():
    """Клавиатура для отправки геолокации"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    return keyboard

def get_cancel_keyboard():
    """Клавиатура с кнопкой отмены"""
    buttons = [[KeyboardButton(text="❌ Отменить создание заявки")]]
    keyboard = ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True
    )
    return keyboard

def get_role_keyboard():
    """Клавиатура выбора роли"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton(text="👤 Я заказчик", callback_data="role_client")],
        [InlineKeyboardButton(text="🔧 Я монтажник", callback_data="role_installer")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def show_client_menu(message: Message, user=None):
    """Показать меню заказчика с кнопками"""
    if not user:
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()
    
    await message.answer(
        f"👋 <b>Добро пожаловать, {user.name or 'заказчик'}!</b>\n\n"
        f"Выберите действие:",
        reply_markup=get_client_main_keyboard()
    )

async def show_installer_menu(message: Message, user=None):
    """Показать меню монтажника с кнопками"""
    if not user:
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()
    
    await message.answer(
        f"🔧 <b>Добро пожаловать, {user.name or 'монтажник'}!</b>\n\n"
        f"Выберите действие:",
        reply_markup=get_installer_main_keyboard()
    )

async def show_admin_menu(message: Message, user=None):
    """Показать меню администратора с кнопками"""
    if not user:
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()
    
    await message.answer(
        f"👑 <b>Добро пожаловать, Администратор!</b>\n\n"
        f"Выберите действие:",
        reply_markup=get_admin_main_keyboard()
    )

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()
    
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            # Новый пользователь - предлагаем выбрать роль
            await message.answer(
                "👋 Добро пожаловать в бот для заказа монтажных работ!\n\n"
                "Выберите вашу роль:",
                reply_markup=get_role_keyboard()
            )
        else:
            # Существующий пользователь - показываем соответствующее меню с кнопками
            if user.is_admin:
                await show_admin_menu(message, user)
            elif user.role == 'client':
                await show_client_menu(message, user)
            elif user.role == 'installer':
                await show_installer_menu(message, user)

@router.callback_query(F.data.startswith("role_"))
async def process_role(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора роли при регистрации"""
    role = callback.data.split("_")[1]
    
    async with async_session() as session:
        # Проверяем, может это админ
        from config import ADMIN_ID
        is_admin = (callback.from_user.id == ADMIN_ID)
        
        user = User(
            telegram_id=callback.from_user.id,
            role=role,
            name=callback.from_user.full_name,
            username=callback.from_user.username,
            is_admin=is_admin
        )
        session.add(user)
        await session.commit()
        
        # Получаем созданного пользователя для передачи в меню
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one()
    
    await callback.message.delete()
    
    if is_admin:
        await show_admin_menu(callback.message, user)
    elif role == 'client':
        await show_client_menu(callback.message, user)
    else:
        await show_installer_menu(callback.message, user)
    
    await callback.answer()

@router.message(F.text == "📝 Новая заявка")
async def cmd_new_request(message: Message, state: FSMContext):
    """Создание новой заявки через кнопку"""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or user.role != 'client':
            await message.answer("❌ Эта функция доступна только заказчикам.")
            return
    
    # Сбрасываем состояние на всякий случай
    await state.clear()
    
    await message.answer(
        "📝 Опишите, что нужно сделать:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(RequestForm.description)

@router.message(Command("new_request"))
async def cmd_new_request_command(message: Message, state: FSMContext):
    """Создание новой заявки через команду"""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or user.role != 'client':
            await message.answer("❌ Эта команда доступна только заказчикам.")
            return
    
    # Сбрасываем состояние на всякий случай
    await state.clear()
    
    await message.answer(
        "📝 Опишите, что нужно сделать:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(RequestForm.description)

@router.message(F.text == "❌ Отменить создание заявки")
async def cancel_request(message: Message, state: FSMContext):
    """Отмена создания заявки"""
    await state.clear()
    
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user.role == 'client':
            await show_client_menu(message, user)
        elif user.role == 'installer':
            await show_installer_menu(message, user)
        elif user.is_admin:
            await show_admin_menu(message, user)

@router.message(RequestForm.description)
async def process_description(message: Message, state: FSMContext):
    """Обработка описания заявки"""
    # Сохраняем описание
    await state.update_data(description=message.text)
    
    # Переходим к следующему шагу
    await message.answer(
        "📸 Теперь отправьте фотографию (можно несколько).\n"
        "Когда закончите, отправьте /done или нажмите кнопку ниже:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="✅ Готово /done")]],
            resize_keyboard=True
        )
    )
    await state.set_state(RequestForm.photos)
    await state.update_data(photos=[])

@router.message(RequestForm.photos, F.photo)
async def process_photo(message: Message, state: FSMContext):
    """Обработка фотографий"""
    data = await state.get_data()
    photos = data.get('photos', [])
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f"✅ Фото добавлено. Всего: {len(photos)}. Отправьте ещё или /done")

@router.message(RequestForm.photos, Command("done"))
@router.message(RequestForm.photos, F.text == "✅ Готово /done")
async def photos_done(message: Message, state: FSMContext):
    """Завершение загрузки фотографий"""
    data = await state.get_data()
    if not data.get('photos'):
        await message.answer("❌ Нужно отправить хотя бы одно фото!")
        return
    
    await message.answer(
        "📍 Выберите способ указания адреса:",
        reply_markup=get_geo_choice_keyboard()
    )
    await state.set_state(RequestForm.address_choice)

@router.callback_query(F.data == "send_geo")
async def address_choice_geo(callback: CallbackQuery, state: FSMContext):
    """Выбор отправки геолокации"""
    await callback.message.delete()
    await callback.message.answer(
        "📍 Отправьте вашу геолокацию, нажав на кнопку ниже:",
        reply_markup=get_location_keyboard()
    )
    await state.set_state(RequestForm.location)
    await callback.answer()

@router.callback_query(F.data == "manual_address")
async def address_choice_manual(callback: CallbackQuery, state: FSMContext):
    """Выбор ручного ввода адреса"""
    await callback.message.delete()
    await callback.message.answer(
        "✍️ Введите адрес текстом:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(RequestForm.manual_address)
    await callback.answer()

@router.message(RequestForm.location, F.location)
async def process_location(message: Message, state: FSMContext):
    """Обработка полученной геолокации"""
    latitude = message.location.latitude
    longitude = message.location.longitude
    
    await state.update_data(
        latitude=latitude,
        longitude=longitude
    )
    
    processing_msg = await message.answer("🔄 Получаем адрес по координатам...")
    
    address = await reverse_geocode(latitude, longitude)
    
    await processing_msg.delete()
    
    if address:
        await state.update_data(
            address=address,
            location_address=address
        )
        
        await message.answer(
            f"📍 Найден адрес:\n<code>{address}</code>\n\n"
            f"Всё верно?",
            reply_markup=get_confirm_address_keyboard()
        )
    else:
        await message.answer(
            "❌ Не удалось определить адрес по координатам.\n"
            "Пожалуйста, введите адрес вручную:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(RequestForm.manual_address)

@router.callback_query(F.data == "confirm_address")
async def confirm_address(callback: CallbackQuery, state: FSMContext):
    """Подтверждение адреса"""
    await callback.message.delete()
    await callback.message.answer(
        "✅ Адрес подтвержден.\n"
        "📞 Теперь введите номер телефона для связи:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(RequestForm.phone)
    await callback.answer()

@router.callback_query(F.data == "edit_address")
async def edit_address(callback: CallbackQuery, state: FSMContext):
    """Редактирование адреса"""
    await callback.message.delete()
    await callback.message.answer(
        "✍️ Введите правильный адрес текстом:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(RequestForm.manual_address)
    await callback.answer()

@router.message(RequestForm.manual_address)
async def process_manual_address(message: Message, state: FSMContext):
    """Обработка ручного ввода адреса"""
    await state.update_data(address=message.text)
    await message.answer(
        "📞 Введите ваш номер телефона для связи:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(RequestForm.phone)

@router.message(RequestForm.phone)
async def process_phone(message: Message, state: FSMContext):
    """Обработка номера телефона"""
    phone = message.text
    await state.update_data(phone=phone)
    
    await message.answer(
        "🏘 Выберите район:",
        reply_markup=await districts_keyboard()
    )
    await state.set_state(RequestForm.district)

@router.callback_query(RequestForm.district, F.data.startswith("district_"))
async def process_district(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора района и создание заявки"""
    district_id = int(callback.data.split("_")[1])
    data = await state.get_data()
    
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one()
        
        request = Request(
            client_id=user.id,
            description=data['description'],
            photo_file_id=','.join(data['photos']),
            address=data.get('address') or data.get('location_address'),
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
            location_address=data.get('location_address'),
            contact_phone=data['phone'],
            district_id=district_id
        )
        session.add(request)
        await session.flush()
        
        from handlers.installer import send_request_to_group
        await send_request_to_group(callback.bot, request, session)
        
        await session.commit()
    
    await callback.message.edit_text(
        f"✅ Заявка №{request.id} создана и отправлена монтажникам!\n"
        "Мы уведомим вас, когда её возьмут в работу."
    )
    await state.clear()
    
    # Возвращаем главное меню
    await show_client_menu(callback.message, user)
    await callback.answer()

@router.message(F.text == "📋 Мои заявки")
async def my_requests_client(message: Message):
    """Просмотр заявок клиента через кнопку"""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or user.role != 'client':
            await message.answer("❌ Эта функция доступна только заказчикам.")
            return
        
        # Получаем все заявки клиента
        result = await session.execute(
            select(Request)
            .options(selectinload(Request.installer))
            .where(Request.client_id == user.id)
            .order_by(Request.created_at.desc())
        )
        requests = result.scalars().all()
        
        if not requests:
            await message.answer("📭 У вас пока нет заявок.")
            return
        
        # Формируем сообщение со списком заявок
        text = "📋 <b>Ваши заявки:</b>\n\n"
        
        for req in requests[:5]:  # Показываем последние 5
            status_emoji = "✅" if req.status == 'completed' else "🔨" if req.status == 'in_progress' else "🆕"
            date_str = req.created_at.strftime('%d.%m.%Y')
            installer_name = f"@{req.installer.username}" if req.installer and req.installer.username else "Не назначен"
            
            text += (
                f"{status_emoji} <b>Заявка №{req.id}</b> от {date_str}\n"
                f"📍 {req.address[:50]}...\n"
                f"👷 Монтажник: {installer_name}\n"
                f"📊 Статус: {req.status}\n\n"
            )
        
        if len(requests) > 5:
            text += f"... и еще {len(requests) - 5} заявок"
        
        await message.answer(text)

@router.message(Command("my_requests"))
async def my_requests_command(message: Message):
    """Просмотр заявок через команду (обрабатываем в зависимости от роли)"""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Вы не зарегистрированы. Используйте /start")
            return
        
        if user.role == 'client':
            # Для клиента - показываем его заявки
            result = await session.execute(
                select(Request)
                .options(selectinload(Request.installer))
                .where(Request.client_id == user.id)
                .order_by(Request.created_at.desc())
            )
            requests = result.scalars().all()
            
            if not requests:
                await message.answer("📭 У вас пока нет заявок.")
                return
            
            text = "📋 <b>Ваши заявки:</b>\n\n"
            
            for req in requests[:5]:
                status_emoji = "✅" if req.status == 'completed' else "🔨" if req.status == 'in_progress' else "🆕"
                date_str = req.created_at.strftime('%d.%m.%Y')
                installer_name = f"@{req.installer.username}" if req.installer and req.installer.username else "Не назначен"
                
                text += (
                    f"{status_emoji} <b>Заявка №{req.id}</b> от {date_str}\n"
                    f"📍 {req.address[:50]}...\n"
                    f"👷 Монтажник: {installer_name}\n"
                    f"📊 Статус: {req.status}\n\n"
                )
            
            if len(requests) > 5:
                text += f"... и еще {len(requests) - 5} заявок"
            
            await message.answer(text)
            
        elif user.role == 'installer':
            # Для монтажника - перенаправляем на его обработчик
            await installer_my_requests(message)
        else:
            await message.answer("❌ Неизвестная роль")

@router.message(F.text == "👤 Мой профиль")
async def show_profile_button(message: Message):
    """Показать профиль через кнопку"""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Вы не зарегистрированы. Используйте /start")
            return
        
        if user.role == 'client':
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
            
            await message.answer(text)
        
        elif user.role == 'installer':
            # Для монтажника - используем его обработчик профиля
            await installer_show_profile(message)

@router.message(F.text == "❓ Помощь")
async def help_button(message: Message):
    """Помощь через кнопку"""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
    
    if not user:
        await message.answer("❓ Используйте /start для начала работы")
        return
    
    if user.role == 'client':
        text = (
            "❓ <b>Помощь для заказчика</b>\n\n"
            "📝 <b>Новая заявка</b> - создание заявки на монтажные работы\n"
            "📋 <b>Мои заявки</b> - просмотр ваших заявок\n"
            "👤 <b>Мой профиль</b> - информация о вашем профиле\n\n"
            "Также доступны команды:\n"
            "/start - главное меню\n"
            "/new_request - создать заявку\n"
            "/profile - мой профиль"
        )
    elif user.role == 'installer':
        text = (
            "❓ <b>Помощь для монтажника</b>\n\n"
            "📋 <b>Активные заявки</b> - заявки в работе\n"
            "📊 <b>Все мои заявки</b> - история ваших заявок\n"
            "👤 <b>Мой профиль</b> - информация о вашем профиле\n"
            "📊 <b>Статистика</b> - ваша статистика\n\n"
            "Также доступны команды:\n"
            "/start - главное меню\n"
            "/profile - мой профиль"
        )
    elif user.is_admin:
        text = (
            "❓ <b>Помощь для администратора</b>\n\n"
            "👑 <b>Админ панель</b> - панель управления\n"
            "📊 <b>Общая статистика</b> - статистика по боту\n"
            "👷 <b>Монтажники</b> - список монтажников\n"
            "👤 <b>Клиенты</b> - список клиентов\n"
            "🏘 <b>Районы</b> - статистика по районам\n\n"
            "Команда /admin - админ панель"
        )
    
    await message.answer(text)

# Добавляем обработчики для кнопок монтажника
@router.message(F.text == "📋 Активные заявки")
async def active_requests_handler(message: Message):
    """Активные заявки монтажника"""
    await installer_my_requests(message)

@router.message(F.text == "📊 Все мои заявки")
async def all_requests_handler(message: Message):
    """Все заявки монтажника"""
    await installer_my_all_requests(message)

@router.message(F.text == "📊 Статистика")
async def stats_handler(message: Message):
    """Статистика монтажника"""
    await installer_stats(message)

# Добавляем обработчики для кнопок администратора
@router.message(F.text == "👑 Админ панель")
async def admin_panel_handler(message: Message):
    """Админ панель"""
    from handlers.admin import admin_panel
    await admin_panel(message)

@router.message(F.text == "📊 Общая статистика")
async def admin_stats_handler(message: Message):
    """Общая статистика"""
    from handlers.admin import admin_stats
    await admin_stats(message)

@router.message(F.text == "👷 Монтажники")
async def admin_installers_handler(message: Message):
    """Список монтажников"""
    from handlers.admin import admin_installers
    await admin_installers(message)

@router.message(F.text == "👤 Клиенты")
async def admin_clients_handler(message: Message):
    """Список клиентов"""
    from handlers.admin import admin_clients
    await admin_clients(message)

@router.message(F.text == "🏘 Районы")
async def admin_districts_handler(message: Message):
    """Статистика по районам"""
    from handlers.admin import admin_districts
    await admin_districts(message)

@router.message()
async def handle_unknown(message: Message, state: FSMContext):
    """Обработка неизвестных сообщений"""
    current_state = await state.get_state()
    
    if current_state:
        # Если пользователь в процессе создания заявки, игнорируем
        return
    
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
    
    if user:
        if user.role == 'client':
            await message.answer(
                "❌ Неизвестная команда. Используйте кнопки меню:",
                reply_markup=get_client_main_keyboard()
            )
        elif user.role == 'installer':
            await message.answer(
                "❌ Неизвестная команда. Используйте кнопки меню:",
                reply_markup=get_installer_main_keyboard()
            )
        elif user.is_admin:
            await message.answer(
                "❌ Неизвестная команда. Используйте кнопки меню:",
                reply_markup=get_admin_main_keyboard()
            )
    else:
        await message.answer(
            "❓ Используйте /start для начала работы"
        )
