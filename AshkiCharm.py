# ======================= ИМПОРТЫ И НАСТРОЙКИ ======================= #
import os
import logging
import re
import pandas as pd
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import declarative_base, Session, sessionmaker, relationship
from sqlalchemy.sql import func
import datetime
import io
from dotenv import load_dotenv
load_dotenv()  # Загрузка переменных окружения

print("Текущая директория:", os.getcwd())
print("Содержимое текущей директории:", os.listdir())


BOT_TOKEN = os.getenv("BOT_TOKEN")
print(f"Загруженный токен: {BOT_TOKEN}")



# ======================= НАСТРОЙКА ЛОГГЕРА ======================= #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ======================= ИНИЦИАЛИЗАЦИЯ БОТА ======================= #

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Загрузка токена из переменных окружения
if not BOT_TOKEN:
    raise ValueError("Не найден токен бота. Укажите его в переменной окружения BOT_TOKEN.")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# ======================= БАЗА ДАННЫХ ======================= #
Base = declarative_base()

def get_database_url():
    return os.getenv("DATABASE_URL", "sqlite:///database.db")  # Возможность использовать PostgreSQL или другую СУБД

engine = create_engine(get_database_url())
Session = sessionmaker(bind=engine)

class AuthState(StatesGroup):
    enter_name = State()       # Состояние для ввода имени
    enter_password = State()   # Состояние для ввода пароля

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    purchase_price = Column(Float)
    sale_price = Column(Float)
    sale_price_2 = Column(Float)  # Новая цена за 2 шт
    flavors = relationship("Flavor", back_populates="product", cascade="all, delete-orphan")
    sales = relationship("Sale", back_populates="product")

class RecordDefectState(StatesGroup):
    select_product = State()
    select_flavor = State()
    enter_quantity = State()


class Flavor(Base):
    __tablename__ = "flavors"
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    quantity = Column(Integer)
    product_id = Column(Integer, ForeignKey("products.id"))
    product = relationship("Product", back_populates="flavors")
    sales = relationship("Sale", back_populates="flavor")

class EditSaleState(StatesGroup):
    select_customer = State()
    select_sale = State()
    select_action = State()
    select_product = State()
    select_flavor = State()
    enter_quantity = State()


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    date = Column(DateTime, default=datetime.datetime.now)  # Добавлено!
    sales = relationship("Sale", back_populates="customer")


class Sale(Base):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    flavor_id = Column(Integer, ForeignKey("flavors.id"))
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)  # Связь с покупателем
    quantity = Column(Integer)
    purchase_price = Column(Float)
    sale_price = Column(Float)
    date = Column(DateTime, default=datetime.datetime.now)

    product = relationship("Product", back_populates="sales")
    flavor = relationship("Flavor", back_populates="sales")
    customer = relationship("Customer", back_populates="sales")

class WorkerIncome(Base):
    __tablename__ = "worker_income"
    id = Column(Integer, primary_key=True)
    week_start = Column(DateTime)
    income = Column(Float)
    is_current = Column(Boolean, default=True)

# === Создаём таблицы только один раз ===
Base.metadata.create_all(engine)  # Теперь вызываем здесь

class RecordSaleState(StatesGroup):
    select_product = State()
    select_flavor = State()
    enter_quantity = State()
    enter_custom_quantity = State()
    confirm_more_items = State()  # Спрашиваем, добавить ли ещё товар
    enter_customer_name = State()







# ======================= СОСТОЯНИЯ FSM ======================= #
class AddProductState(StatesGroup):
    enter_name = State()
    enter_prices = State()  # Теперь ожидает 3 значения
    enter_flavors = State()

    class CancelState(StatesGroup):
        confirm_cancel = State()

class EditProductState(StatesGroup):
    select_product = State()
    select_action = State()
    update_prices = State()
    add_flavors = State()
    remove_flavors = State()
    update_flavor_quantity = State()  # ✅ Добавляем состояние!
    confirm_delete = State()
    select_flavor = State()


class FileUploadState(StatesGroup):
    waiting_file = State()


# ======================= УТИЛИТЫ ======================= #
def parse_flavor_line(line: str):
    """Парсинг строки с вкусом и количеством"""
    try:
        match = re.search(r'(.*?)\s+(\d+)$', line.strip())
        if not match:
            raise ValueError
        return match.group(1).strip(), int(match.group(2))
    except Exception:
        raise ValueError(f"Ошибка в строке: {line}")



# ======================= ОБРАБОТЧИКИ ======================= #

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("Добро пожаловать! Пожалуйста, введите ваше имя:")
    await state.set_state(AuthState.enter_name)

@dp.message(AuthState.enter_name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым. Введите, пожалуйста, ваше имя:")
        return
    await state.update_data(user_name=name)
    await message.answer(f"Привет, {name}! Теперь введите пароль:")
    await state.set_state(AuthState.enter_password)

@dp.message(AuthState.enter_password)
async def process_password(message: types.Message, state: FSMContext):
    correct_password = "5178"  # Замените на ваш пароль
    if message.text == correct_password:
        data = await state.get_data()
        user_name = data.get("user_name", "Пользователь")
        await state.update_data(authenticated=True)
        await message.answer(f"Добро пожаловать, {user_name}! Вы успешно авторизованы.")
        await send_main_menu(message)
        await state.clear()  # Сбрасываем состояние после авторизации
    else:
        await message.answer("❌ Неверный пароль. Попробуйте ещё раз или введите 'Отмена' для выхода:")

@dp.message(AuthState.enter_password, F.text == "Отмена")
async def cancel_auth(message: types.Message, state: FSMContext):
    await message.answer("Авторизация отменена. Возвращаю в главное меню.")
    await send_main_menu(message)
    await state.clear()

async def send_main_menu(message: types.Message):
    markup = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📦 Управление товарами"), types.KeyboardButton(text="💵 Записать продажу")],
            [types.KeyboardButton(text="✏️ Редактировать продажи"), types.KeyboardButton(text="📦 Показать товары")],
            [types.KeyboardButton(text="📊 Аналитика"), types.KeyboardButton(text="Актуальный прайс")]
        ],
        resize_keyboard=True
    )
    await message.answer("🏪 <b>Система управления товарами</b>\nВыберите действие:", reply_markup=markup)

async def save_sale(message: types.Message, state: FSMContext):
    """Сохранение продажи с привязкой к покупателю и корректным обновлением количества товара"""

    # Получаем данные из состояния
    data = await state.get_data()

    # 🛑 Проверяем, есть ли sales_list. Если нет – сообщаем об ошибке и выходим
    if "sales_list" not in data or not data["sales_list"]:
        await message.answer("❌ Ошибка: список продаж пуст! Попробуйте начать заново.")
        await state.clear()
        return

    # Извлекаем имя покупателя из состояния
    customer_name = data.get("customer_name", "Покупатель 1")  # По умолчанию, если имя не указано

    with Session() as session:
        # Проверяем, есть ли уже покупатель в БД
        customer = session.query(Customer).filter_by(name=customer_name).first()
        if not customer:
            customer = Customer(name=customer_name, date=datetime.datetime.now())
            session.add(customer)
            session.commit()

        total_revenue = 0
        total_profit = 0
        sale_texts = []
        insufficient_stock = []

        # 🔹 **Шаг 1: Проверяем, хватает ли товаров (без уменьшения количества)**
        for sale in data["sales_list"]:
            product = session.query(Product).filter_by(name=sale["product_name"]).first()
            flavor = session.query(Flavor).filter_by(name=sale["flavor_name"], product_id=product.id).first()

            if not flavor:
                insufficient_stock.append(f"❌ {sale['flavor_name']} (нет в наличии)")
                continue

            session.refresh(flavor)  # Обновляем данные из БД
            if flavor.quantity < sale["quantity"]:
                insufficient_stock.append(f"❌ {sale['flavor_name']} (в наличии: {flavor.quantity})")

        # Если товара не хватает, сообщаем об этом пользователю и прерываем продажу
        if insufficient_stock:
            await message.answer("❌ Ошибка: недостаточно товара!\n" + "\n".join(insufficient_stock))
            return

        # Вычисляем общие количества для каждого товара (суммируем по всем вкусам)
        product_totals = {}
        for sale in data["sales_list"]:
            product_totals[sale["product_name"]] = product_totals.get(sale["product_name"], 0) + sale["quantity"]

        # 🔹 **Шаг 2: Уменьшаем количество товаров и записываем продажу**
        for sale in data["sales_list"]:
            product = session.query(Product).filter_by(name=sale["product_name"]).first()
            flavor = session.query(Flavor).filter_by(name=sale["flavor_name"], product_id=product.id).first()

            # Проверяем, достаточно ли товара на складе
            if flavor.quantity < sale["quantity"]:
                insufficient_stock.append(f"❌ {sale['flavor_name']} (в наличии: {flavor.quantity})")
                continue

            # Выбираем цену в зависимости от общего количества проданного товара данного вида
            if product_totals[sale["product_name"]] >= 2:
                sale_price = product.sale_price_2  # Цена за 2 шт
            else:
                sale_price = product.sale_price  # Цена за 1 шт

            # Уменьшаем количество на складе
            new_quantity = flavor.quantity - sale["quantity"]
            session.query(Flavor).filter_by(id=flavor.id).update({"quantity": new_quantity})

            # Создаем запись о продаже
            sale_record = Sale(
                product=product,
                flavor=flavor,
                customer=customer,
                quantity=sale["quantity"],
                purchase_price=product.purchase_price,
                sale_price=sale_price  # Используем выбранную цену
            )
            session.add(sale_record)

            # Рассчитываем выручку и прибыль
            revenue = sale["quantity"] * sale_price
            profit = (sale_price - product.purchase_price) * sale["quantity"]
            total_revenue += revenue
            total_profit += profit

            # Добавляем информацию о продаже в итоговое сообщение
            sale_texts.append(
                f"📦 <b>{sale['product_name']}</b> - {sale['flavor_name']} - {sale['quantity']} шт. ({sale_price} ₽/шт)")

        # ✅ Сохраняем изменения в БД **одним коммитом**
        session.commit()

        # ✅ Формируем итоговое сообщение
        response_text = (
            f"✅ <b>Продажа завершена!</b>\n"
            f"📅 <b>Дата:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
            f"👤 <b>Покупатель:</b> {customer_name}\n\n"
            f"{'\n'.join(sale_texts)}\n"
            f"💰 <b>Общая выручка:</b> {total_revenue:.2f} ₽\n"
            f"📊 <b>Прибыль:</b> {total_profit:.2f} ₽"
        )

        await message.answer(response_text, parse_mode="HTML")

    await state.clear()  # ✅ Очищаем состояние, чтобы избежать ошибок "используйте кнопки меню"


@dp.message(F.text == "Брак")
async def start_defect_recording(message: types.Message, state: FSMContext):
    try:
        with Session() as session:
            # Выбираем только товары, по которым есть записи брака (customer is None)
            products = session.query(Product).join(Sale).filter(Sale.customer == None).distinct().all()
            if not products:
                markup = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="Добавить брак", callback_data="register_defect_new")]
                ])
                await message.answer("📭 Нет зарегистрированного брака за всё время.", reply_markup=markup)
                return
            product_buttons = [
                [types.InlineKeyboardButton(text=p.name, callback_data=f"defect_product_{p.id}")]
                for p in products
            ]
            # Добавляем дополнительную кнопку для регистрации брака и кнопку "🔙 Назад"
            product_buttons.append([types.InlineKeyboardButton(text="Добавить брак", callback_data="register_defect_new")])
            product_buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")])
            markup = types.InlineKeyboardMarkup(inline_keyboard=product_buttons)
            await message.answer("📋 Список товаров с зарегистрированным браком:", reply_markup=markup)
            await state.set_state(RecordDefectState.select_product)
    except Exception as e:
        logger.error(f"Ошибка при загрузке товаров для брака: {str(e)}")
        await message.answer("❌ Ошибка при загрузке товаров для брака")


@dp.callback_query(F.data.startswith("defect_product_"), RecordDefectState.select_product)
async def show_defect_history(callback: types.CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[-1])
    await state.update_data(product_id=product_id)
    with Session() as session:
        product = session.query(Product).get(product_id)
        defects = session.query(Sale).filter_by(product_id=product_id, customer=None).all()
        if not defects:
            defect_info = "Нет зарегистрированного брака."
        else:
            total_defect_qty = sum(defect.quantity for defect in defects)
            total_loss = product.purchase_price * total_defect_qty
            defect_info = (f"Общее количество брака: {total_defect_qty} шт.\n"
                           f"Убыток: {total_loss:.2f} ₽")
        markup = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Зарегистрировать новый брак", callback_data=f"register_defect_{product_id}")],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_defect_list")]
        ])
        await callback.message.edit_text(f"📌 Товар: {product.name}\n{defect_info}", reply_markup=markup)
        await state.set_state(RecordDefectState.select_product)

@dp.callback_query(F.data == "back_to_defect_list", RecordDefectState.select_product)
async def back_to_defect_list(callback: types.CallbackQuery, state: FSMContext):
    await start_defect_recording(callback.message, state)

@dp.callback_query(F.data.startswith("register_defect_"), RecordDefectState.select_product)
async def register_defect_start(callback: types.CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[-1])
    await state.update_data(product_id=product_id)
    with Session() as session:
        product = session.query(Product).get(product_id)
        if not product or not product.flavors:
            await callback.answer("❌ Нет доступных вкусов для этого товара!", show_alert=True)
            return
        flavor_buttons = [
            [types.InlineKeyboardButton(text=f"{flavor.name} ({flavor.quantity})", callback_data=f"defect_flavor_{flavor.id}")]
            for flavor in product.flavors if flavor.quantity > 0
        ]
        flavor_buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_defect_list")])
        markup = types.InlineKeyboardMarkup(inline_keyboard=flavor_buttons)
        await callback.message.edit_text("Выберите вкус для регистрации брака:", reply_markup=markup)
        await state.set_state(RecordDefectState.select_flavor)

@dp.callback_query(F.data == "back_to_defect_products", RecordDefectState.select_flavor)
async def back_to_defect_products(callback: types.CallbackQuery, state: FSMContext):
    with Session() as session:
        products = session.query(Product).all()
        if not products:
            await callback.message.answer("❌ Нет товаров для брака")
            return
        product_buttons = [
            [types.InlineKeyboardButton(text=p.name, callback_data=f"defect_product_{p.id}")]
            for p in products
        ]
        product_buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")])
        markup = types.InlineKeyboardMarkup(inline_keyboard=product_buttons)
        await callback.message.edit_text("Выберите товар для брака:", reply_markup=markup)
        await state.set_state(RecordDefectState.select_product)

@dp.callback_query(F.data.startswith("defect_flavor_"), RecordDefectState.select_flavor)
async def select_defect_flavor(callback: types.CallbackQuery, state: FSMContext):
    flavor_id = int(callback.data.split("_")[-1])
    await state.update_data(flavor_id=flavor_id)
    await callback.message.edit_text("Введите количество бракованных единиц:")
    await state.set_state(RecordDefectState.enter_quantity)

@dp.message(RecordDefectState.enter_quantity)
async def enter_defect_quantity(message: types.Message, state: FSMContext):
    try:
        quantity = int(message.text)
        if quantity <= 0:
            await message.answer("❌ Количество должно быть положительным!")
            return
        data = await state.get_data()
        with Session() as session:
            product = session.query(Product).get(data["product_id"])
            flavor = session.query(Flavor).get(data["flavor_id"])
            if flavor.quantity < quantity:
                await message.answer(f"❌ Недостаточно товара на складе! Осталось: {flavor.quantity}")
                return
            # Вычитаем брак из остатка
            flavor.quantity -= quantity

            # Регистрируем брак как запись в таблице продаж:
            sale_record = Sale(
                product=product,
                flavor=flavor,
                customer=None,  # для брака покупатель не нужен
                quantity=quantity,
                purchase_price=product.purchase_price,
                sale_price=0
            )
            session.add(sale_record)

            # Вычисляем сумму брака и обновляем доход рабочего:
            defective_amount = product.purchase_price * quantity
            today = datetime.datetime.now().date()
            current_week_start = datetime.datetime.combine(
                today - datetime.timedelta(days=today.weekday()),
                datetime.time.min
            )
            income_record = session.query(WorkerIncome).filter(WorkerIncome.week_start == current_week_start).first()
            if not income_record:
                income_record = WorkerIncome(
                    week_start=current_week_start,
                    income=0.0,
                    is_current=True
                )
                session.add(income_record)
            # Вычитается 30% убытка (рабочему вычтено 30%, магазин – 70%)
            income_record.income -= defective_amount * 0.3

            session.commit()
            await message.answer(
                f"✅ Брак зарегистрирован!\n"
                f"📦 Товар: {product.name}\n"
                f"🍏 Вкус: {flavor.name}\n"
                f"🔢 Количество: {quantity} шт.\n"
                f"💰 Убыток: {defective_amount:.2f} ₽ (из них рабочему вычтено: {defective_amount * 0.3:.2f} ₽)"
            )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное целое число!")
    except Exception as e:
        logger.error(f"Ошибка при регистрации брака: {str(e)}")
        await message.answer("❌ Ошибка при регистрации брака")
        await state.clear()

@dp.callback_query(F.data == "register_defect_new")

async def register_defect_new(callback: types.CallbackQuery, state: FSMContext):
    with Session() as session:
        products = session.query(Product).all()
        if not products:
            await callback.message.answer("❌ Нет товаров для брака")
            return
        product_buttons = [
            [types.InlineKeyboardButton(text=p.name, callback_data=f"defect_product_{p.id}")]
            for p in products
        ]
        product_buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")])
        markup = types.InlineKeyboardMarkup(inline_keyboard=product_buttons)
        await callback.message.edit_text("Выберите товар для регистрации брака:", reply_markup=markup)
        await state.set_state(RecordDefectState.select_product)





@dp.callback_query(F.data == "back_to_customers", EditSaleState.select_sale)
async def back_to_customers_list(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к списку покупателей"""
    await start_edit_sale(callback.message, state)


@dp.callback_query(F.data == "back_to_sales_list", EditSaleState.select_action)
async def back_to_sales_list(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к списку продаж покупателя"""
    data = await state.get_data()
    customer_id = data.get('customer_id')

    with Session() as session:
        customer = session.get(Customer, customer_id)
        sales = session.query(Sale).filter_by(customer_id=customer_id).all()

        buttons = [
            [InlineKeyboardButton(
                text=f"{sale.product.name} - {sale.flavor.name} ({sale.quantity} шт.)",
                callback_data=f"select_sale_{sale.id}"
            )] for sale in sales
        ]
        buttons.append([InlineKeyboardButton(text="🗑️ Удалить все продажи", callback_data="delete_all_sales")])
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_customers")])

        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(f"Продажи покупателя {customer.name}:", reply_markup=markup)
        await state.set_state(EditSaleState.select_sale)



@dp.callback_query(F.data == "add_more", RecordSaleState.confirm_more_items)
async def add_more_items(callback: types.CallbackQuery, state: FSMContext):
    """При нажатии кнопки 'Добавить ещё товар' удаляем старое сообщение и запускаем новый выбор товара."""
    try:
        # Удаляем предыдущее сообщение (со списком товаров, уже добавленных в продажу)
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")

    # Запускаем функцию выбора товара.
    # Можно использовать callback.message.chat.id для отправки нового сообщения.
    await start_sale_recording(callback.message, state)


@dp.callback_query(F.data == "finish_sale", RecordSaleState.confirm_more_items)
async def ask_for_customer_name(callback: types.CallbackQuery, state: FSMContext):
    """Спрашиваем, нужно ли вводить имя покупателя"""
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="enter_customer_name")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="skip_customer_name")]
    ])
    await callback.message.edit_text("Добавить имя покупателя?", reply_markup=markup)


@dp.message(F.text == "✏️ Редактировать продажи")
async def start_edit_sale(message: types.Message, state: FSMContext):
    """Начало процесса редактирования продажи"""
    with Session() as session:
        customers = session.query(Customer).order_by(Customer.id.desc()).all()
        if not customers:
            await message.answer("❌ Нет покупателей для редактирования")
            return

        buttons = [
            [InlineKeyboardButton(text=f"👤 {customer.name}", callback_data=f"edit_customer_{customer.id}")]
            for customer in customers
        ]
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Выберите покупателя:", reply_markup=markup)
        await state.set_state(EditSaleState.select_customer)


@dp.callback_query(F.data.startswith("edit_customer_"), EditSaleState.select_customer)
async def select_customer_sales(callback: types.CallbackQuery, state: FSMContext):
    """Выбор продажи конкретного покупателя"""
    customer_id = int(callback.data.split("_")[-1])
    await state.update_data(customer_id=customer_id)

    with Session() as session:
        customer = session.get(Customer, customer_id)
        sales = session.query(Sale).filter_by(customer_id=customer_id).all()

        if not sales:
            await callback.answer("❌ У этого покупателя нет продаж", show_alert=True)
            await state.clear()
            return

        buttons = [
            [InlineKeyboardButton(
                text=f"{sale.product.name} - {sale.flavor.name} ({sale.quantity} шт.)",
                callback_data=f"select_sale_{sale.id}"
            )] for sale in sales
        ]
        # Добавляем кнопку "Удалить все продажи" и "Назад"
        buttons.append([InlineKeyboardButton(text="🗑️ Удалить все продажи", callback_data="delete_all_sales")])
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_customers")])

        markup = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.edit_text(
            f"Продажи покупателя {customer.name}:",
            reply_markup=markup
        )
        await state.set_state(EditSaleState.select_sale)


@dp.callback_query(F.data == "delete_all_sales", EditSaleState.select_sale)
async def delete_all_sales_confirmation(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение удаления всех продаж покупателя"""
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete_all_sales")],
        [InlineKeyboardButton(text="❌ Нет, отмена", callback_data="cancel_delete_all_sales")]
    ])
    await callback.message.edit_text(
        "❗ Вы уверены, что хотите удалить ВСЕ продажи этого покупателя? Товары будут возвращены на склад.",
        reply_markup=markup
    )


@dp.callback_query(F.data == "confirm_delete_all_sales", EditSaleState.select_sale)
async def confirm_delete_all_sales(callback: types.CallbackQuery, state: FSMContext):
    """Удаление всех продаж покупателя с возвратом товаров на склад и удалением покупателя"""
    data = await state.get_data()
    customer_id = data.get('customer_id')

    with Session() as session:
        customer = session.get(Customer, customer_id)
        sales = session.query(Sale).filter_by(customer_id=customer_id).all()

        if not sales:
            await callback.answer("❌ Нет продаж для удаления", show_alert=True)
            return

        # Возвращаем товары на склад
        for sale in sales:
            sale.flavor.quantity += sale.quantity

        # Удаляем все продажи покупателя
        session.query(Sale).filter_by(customer_id=customer_id).delete()

        # Удаляем покупателя из списка
        session.delete(customer)
        session.commit()

        await callback.message.edit_text(
            f"✅ Все продажи покупателя {customer.name} удалены. Товары возвращены на склад. Покупатель удален из списка."
        )

    await state.clear()



@dp.callback_query(F.data == "cancel_delete_all_sales", EditSaleState.select_sale)
async def cancel_delete_all_sales(callback: types.CallbackQuery, state: FSMContext):
    """Отмена удаления всех продаж"""
    data = await state.get_data()
    customer_id = data.get('customer_id')

    with Session() as session:
        customer = session.get(Customer, customer_id)
        sales = session.query(Sale).filter_by(customer_id=customer_id).all()

        buttons = [
            [InlineKeyboardButton(
                text=f"{sale.product.name} - {sale.flavor.name} ({sale.quantity} шт.)",
                callback_data=f"select_sale_{sale.id}"
            )] for sale in sales
        ]
        buttons.append([InlineKeyboardButton(text="🗑️ Удалить все продажи", callback_data="delete_all_sales")])
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_customers")])

        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(f"Продажи покупателя {customer.name}:", reply_markup=markup)
        await state.set_state(EditSaleState.select_sale)





@dp.callback_query(F.data.startswith("select_sale_"), EditSaleState.select_sale)
async def select_sale_action(callback: types.CallbackQuery, state: FSMContext):
    """Выбор действия для выбранной продажи с отображением актуальной информации о товаре"""
    sale_id = int(callback.data.split("_")[-1])
    await state.update_data(sale_id=sale_id)

    with Session() as session:
        sale = session.get(Sale, sale_id)
        if not sale:
            await callback.answer("❌ Продажа не найдена", show_alert=True)
            return

        product = sale.product
        # Собираем информацию о товаре
        product_info = f"📌 <b>{product.name.upper()}</b>\n"
        product_info += f"Закуп: {int(product.purchase_price)}₽\n"
        product_info += f"Продажа: {int(product.sale_price)}₽\n"
        product_info += f"Акция (от 2 шт): {int(product.sale_price_2)}₽\n"
        product_info += "Остатки по вкусам:\n"
        for flavor in product.flavors:
            product_info += f" - {flavor.name}: {flavor.quantity} шт.\n"

        # Информация о текущей продаже
        sale_info = (
            f"\nТекущая продажа:\n"
            f"📦 Товар: {sale.product.name}\n"
            f"🍏 Вкус: {sale.flavor.name}\n"
            f"🔢 Количество: {sale.quantity} шт.\n\n"
            "Выберите действие:"
        )

        full_text = product_info + sale_info

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_sale")],
            [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product_to_sale")],
            [InlineKeyboardButton(text="🗑️ Удалить", callback_data="delete_sale")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_sales_list")]
        ])
        await callback.message.edit_text(full_text, reply_markup=markup, parse_mode="HTML")
        await state.set_state(EditSaleState.select_action)


@dp.callback_query(F.data == "add_product_to_sale", EditSaleState.select_action)
async def add_product_to_sale(callback: types.CallbackQuery, state: FSMContext):
    """Добавление товара в продажу"""
    with Session() as session:
        products = session.query(Product).all()
        buttons = [
            [InlineKeyboardButton(text=product.name, callback_data=f"add_product_{product.id}")]
            for product in products
        ]
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_sale_actions")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите товар для добавления в продажу:", reply_markup=markup)
        await state.set_state(EditSaleState.select_product)

@dp.callback_query(F.data.startswith("add_product_"), EditSaleState.select_product)
async def select_product_to_add(callback: types.CallbackQuery, state: FSMContext):
    """Выбор товара для добавления в продажу"""
    product_id = int(callback.data.split("_")[-1])
    await state.update_data(product_id=product_id)

    with Session() as session:
        product = session.get(Product, product_id)
        flavors = [flavor for flavor in product.flavors if flavor.quantity > 0]  # Убираем закончившиеся вкусы

        if not flavors:
            await callback.answer("❌ Нет доступных вкусов для этого товара!", show_alert=True)
            await add_product_to_sale(callback, state)
            return

        buttons = [
            [InlineKeyboardButton(text=f"{flavor.name} ({flavor.quantity} шт.)",
                                  callback_data=f"add_flavor_{flavor.id}")]
            for flavor in flavors
        ]
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_products_list")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите вкус для добавления в продажу:", reply_markup=markup)
        await state.set_state(EditSaleState.select_flavor)


@dp.callback_query(F.data.startswith("add_flavor_"), EditSaleState.select_flavor)
async def select_flavor_to_add(callback: types.CallbackQuery, state: FSMContext):
    """Выбор вкуса для добавления в продажу"""
    flavor_id = int(callback.data.split("_")[-1])
    await state.update_data(flavor_id=flavor_id)

    with Session() as session:
        flavor = session.get(Flavor, flavor_id)
        if flavor.quantity <= 0:
            await callback.answer("❌ Этот вкус закончился! Выберите другой.", show_alert=True)
            await select_product_to_add(callback, state)
            return

    await callback.message.edit_text("Введите количество для добавления:")
    await state.set_state(EditSaleState.enter_quantity)


@dp.message(EditSaleState.enter_quantity)
async def save_added_sale(message: types.Message, state: FSMContext):
    """Сохранение добавленного товара в продажу"""
    try:
        new_quantity = int(message.text)
        if new_quantity <= 0:
            raise ValueError

        data = await state.get_data()

        with Session() as session:
            # Получаем данные о покупателе
            customer = session.get(Customer, data['customer_id'])

            # Получаем новые данные
            new_product = session.get(Product, data['product_id'])
            new_flavor = session.get(Flavor, data['flavor_id'])

            # Проверяем доступное количество
            if new_flavor.quantity < new_quantity:
                await message.answer(f"❌ Недостаточно товара! Доступно: {new_flavor.quantity}")
                return

            # Создаем новую продажу
            new_sale = Sale(
                product_id=new_product.id,
                flavor_id=new_flavor.id,
                customer_id=customer.id,
                quantity=new_quantity,
                purchase_price=new_product.purchase_price,
                sale_price=new_product.sale_price
            )

            # Уменьшаем количество на складе
            new_flavor.quantity -= new_quantity

            session.add(new_sale)
            session.commit()

            await message.answer(
                f"✅ Товар добавлен в продажу!\n"
                f"📦 Товар: {new_product.name}\n"
                f"🍏 Вкус: {new_flavor.name}\n"
                f"🔢 Количество: {new_quantity}"
            )

    except ValueError:
        await message.answer("❌ Введите корректное положительное число!")
    finally:
        await state.clear()


@dp.callback_query(F.data == "back_to_sale_actions", EditSaleState.select_product)
async def back_to_sale_actions(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к действиям с продажей"""
    data = await state.get_data()
    sale_id = data.get('sale_id')

    with Session() as session:
        sale = session.get(Sale, sale_id)
        if not sale:
            await callback.answer("❌ Продажа не найдена", show_alert=True)
            return

        # Отображаем выбранный товар и вкус
        selected_text = (
            f"📦 Товар: {sale.product.name}\n"
            f"🍏 Вкус: {sale.flavor.name}\n"
            f"🔢 Количество: {sale.quantity} шт.\n\n"
            "Выберите действие:"
        )

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_sale")],
            [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product_to_sale")],
            [InlineKeyboardButton(text="🗑️ Удалить", callback_data="delete_sale")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_sales_list")]
        ])
        await callback.message.edit_text(selected_text, reply_markup=markup)
        await state.set_state(EditSaleState.select_action)


@dp.callback_query(F.data == "edit_sale", EditSaleState.select_action)
async def start_sale_editing(callback: types.CallbackQuery, state: FSMContext):
    """Начало редактирования продажи"""
    with Session() as session:
        products = session.query(Product).all()
        buttons = [
            [InlineKeyboardButton(text=product.name, callback_data=f"edit_product_{product.id}")]
            for product in products
        ]
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_sale_actions")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите новый товар:", reply_markup=markup)
        await state.set_state(EditSaleState.select_product)


@dp.callback_query(F.data.startswith("edit_product_"), EditSaleState.select_product)
async def select_product_for_edit(callback: types.CallbackQuery, state: FSMContext):
    """Выбор нового товара для редактирования"""
    product_id = int(callback.data.split("_")[-1])
    await state.update_data(product_id=product_id)

    with Session() as session:
        product = session.get(Product, product_id)
        flavors = [flavor for flavor in product.flavors if flavor.quantity > 0]  # Убираем закончившиеся вкусы

        if not flavors:
            await callback.answer("❌ Нет доступных вкусов для этого товара!", show_alert=True)
            await start_sale_editing(callback, state)
            return

        buttons = [
            [InlineKeyboardButton(text=f"{flavor.name} ({flavor.quantity} шт.)", callback_data=f"edit_flavor_{flavor.id}")]
            for flavor in flavors
        ]
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_products_list")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите новый вкус:", reply_markup=markup)
        await state.set_state(EditSaleState.select_flavor)


@dp.callback_query(F.data.startswith("edit_flavor_"), EditSaleState.select_flavor)
async def select_flavor_for_edit(callback: types.CallbackQuery, state: FSMContext):
    """Выбор нового вкуса для редактирования"""
    flavor_id = int(callback.data.split("_")[-1])
    await state.update_data(flavor_id=flavor_id)

    with Session() as session:
        flavor = session.get(Flavor, flavor_id)
        if flavor.quantity <= 0:
            await callback.answer("❌ Этот вкус закончился! Выберите другой.", show_alert=True)
            await select_product_for_edit(callback, state)
            return

    await callback.message.edit_text("Введите новое количество:")
    await state.set_state(EditSaleState.enter_quantity)


@dp.message(EditSaleState.enter_quantity)
async def save_edited_sale(message: types.Message, state: FSMContext):
    """Сохранение изменений в продаже"""
    try:
        new_quantity = int(message.text)
        if new_quantity <= 0:
            raise ValueError

        data = await state.get_data()

        with Session() as session:
            # Получаем оригинальную продажу
            original_sale = session.get(Sale, data['sale_id'])

            # Возвращаем оригинальное количество
            original_sale.flavor.quantity += original_sale.quantity

            # Получаем новые данные
            new_product = session.get(Product, data['product_id'])
            new_flavor = session.get(Flavor, data['flavor_id'])

            # Проверяем доступное количество
            if new_flavor.quantity < new_quantity:
                await message.answer(f"❌ Недостаточно товара! Доступно: {new_flavor.quantity}")
                return

            # Обновляем продажу
            new_flavor.quantity -= new_quantity
            original_sale.product_id = new_product.id
            original_sale.flavor_id = new_flavor.id
            original_sale.quantity = new_quantity

            session.commit()

            await message.answer(
                f"✅ Продажа обновлена!\n"
                f"📦 Новый товар: {new_product.name}\n"
                f"🍏 Новый вкус: {new_flavor.name}\n"
                f"🔢 Количество: {new_quantity}"
            )

    except ValueError:
        await message.answer("❌ Введите корректное положительное число!")
    finally:
        await state.clear()

@dp.callback_query(F.data == "back_to_flavors", RecordSaleState.enter_quantity)
async def back_to_flavors(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает пользователя к выбору вкуса"""
    data = await state.get_data()
    product_id = data.get("product_id")

    if not product_id:
        await callback.message.answer("❌ Ошибка: данные о товаре утеряны. Попробуйте заново.")
        await state.clear()
        return

    with Session() as session:
        product = session.query(Product).get(product_id)

        if not product or not product.flavors:
            await callback.message.answer("❌ Ошибка: товар или вкусы не найдены. Попробуйте снова.")
            await state.clear()
            return

        # Формируем клавиатуру для выбора вкуса
        flavor_buttons = [
            [InlineKeyboardButton(text=f"{flavor.name} ({flavor.quantity})", callback_data=f"flavor_{flavor.id}")]
            for flavor in product.flavors
        ]

        # Добавляем кнопку "Назад" к списку вкусов
        flavor_buttons.append([InlineKeyboardButton(text="🔙 Назад к товарам", callback_data="back_to_products")])

        markup = InlineKeyboardMarkup(inline_keyboard=flavor_buttons)

        # Редактируем текущее сообщение, заменяя его на выбор вкуса
        await callback.message.edit_text("Выберите вкус:", reply_markup=markup)
        await state.set_state(RecordSaleState.select_flavor)  # 🔄 Переключаем состояние назад


@dp.message(F.text == "📥 Скачать отчет за месяц")
async def download_month_report(message: types.Message):
    with Session() as session:
        try:
            today = datetime.date.today()
            first_day = datetime.date(today.year, today.month, 1)
            last_day = datetime.date(
                today.year + (today.month // 12),
                (today.month % 12) + 1, 1
            ) - datetime.timedelta(days=1)

            date_range = pd.date_range(start=first_day, end=last_day)

            report_data = []
            for single_date in date_range:
                sales = session.query(Sale).filter(
                    func.date(Sale.date) == single_date.date()
                ).all()

                total_sales = len(sales)
                total_revenue = sum(s.sale_price * s.quantity for s in sales)
                total_profit = sum((s.sale_price - s.purchase_price) * s.quantity for s in sales)
                lena_income = total_profit * 0.3

                report_data.append({
                    "Дата": single_date.strftime("%d.%m.%Y"),
                    "Продажи": total_sales,
                    "Доход": total_revenue,
                    "Прибыль": total_profit,
                    "Доход Лёни": lena_income
                })

            df = pd.DataFrame(report_data)
            totals = pd.DataFrame([{
                "Дата": "ИТОГО:",
                "Продажи": df["Продажи"].sum(),
                "Доход": df["Доход"].sum(),
                "Прибыль": df["Прибыль"].sum(),
                "Доход Лёни": df["Доход Лёни"].sum()
            }])

            df = pd.concat([df, totals], ignore_index=True)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Отчет')

                workbook = writer.book
                worksheet = writer.sheets['Отчет']

                num_format = workbook.add_format({'num_format': '#,##0.00₽'})
                date_format = workbook.add_format({'num_format': 'dd.mm.yyyy'})

                worksheet.set_column('A:A', 12, date_format)
                worksheet.set_column('B:E', 15, num_format)

                totals_format = workbook.add_format({
                    'bold': True,
                    'bg_color': '#FFFF00',
                    'num_format': '#,##0.00₽'
                })

                last_row = len(df)
                for col in range(4):
                    worksheet.write(last_row, col + 1, df.iloc[-1, col + 1], totals_format)

            output.seek(0)

            await message.answer_document(
                types.BufferedInputFile(output.read(), filename="month_report.xlsx"),
                caption=f"📊 Отчет за {today.strftime('%B %Y')}"
            )

        except Exception as e:
            logger.error(f"Ошибка генерации отчета: {str(e)}")
            await message.answer("❌ Ошибка при генерации отчета")



@dp.callback_query(F.data == "enter_customer_name")
async def request_customer_name(callback: types.CallbackQuery, state: FSMContext):
    """Просим ввести имя покупателя"""
    await callback.message.edit_text("Введите имя покупателя:")
    await state.set_state(RecordSaleState.enter_customer_name)


@dp.message(RecordSaleState.enter_customer_name)
async def enter_customer_name(message: types.Message, state: FSMContext):
    """Обработчик ввода имени покупателя"""
    customer_name = message.text.strip()

    if not customer_name:
        await message.answer("❌ Имя покупателя не может быть пустым! Введите имя снова:")
        return

    # Сохраняем имя покупателя в состоянии
    await state.update_data(customer_name=customer_name)

    # Переходим к сохранению продажи
    await save_sale(message, state)

@dp.callback_query(F.data == "skip_customer_name")
async def skip_customer_name(callback: types.CallbackQuery, state: FSMContext):
    """Если пользователь нажал 'Нет' при вводе имени покупателя – создаем стандартное имя."""
    with Session() as session:
        # Находим последнего покупателя
        last_customer = session.query(Customer).order_by(Customer.id.desc()).first()
        # Генерируем следующее имя
        next_customer_id = (last_customer.id + 1) if last_customer else 1
        customer_name = f"Покупатель {next_customer_id}"

    # Сохраняем имя покупателя в состоянии
    await state.update_data(customer_name=customer_name)

    # Передаем сгенерированное имя в save_sale
    await save_sale(callback.message, state)


@dp.message(F.text == "📊 Аналитика")
async def show_analytics(message: types.Message):
    markup = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📊 Текущая статистика"),
             types.KeyboardButton(text="📜 Покупатели")],
            [types.KeyboardButton(text="📥 Скачать отчет за месяц"),
             types.KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    await message.answer("📊 Выберите тип аналитики:", reply_markup=markup)

@dp.message(F.text == "📜 Покупатели")
async def show_customers(message: types.Message):
    """Вывод списка покупателей за сегодня и предложение скачать таблицу за месяц"""
    try:
        with Session() as session:
            today = datetime.datetime.now().date()

            # Получаем покупателей за сегодня
            customers_today = session.query(Customer).filter(
                func.DATE(Customer.date) == today
            ).order_by(Customer.id.desc()).all()

            if not customers_today:
                await message.answer("📭 Нет покупателей за сегодня.")
            else:
                response = ["👤 <b>Покупатели за сегодня:</b>"]
                for customer in customers_today:
                    sales = session.query(Sale).filter(
                        Sale.customer_id == customer.id,
                        func.DATE(Sale.date) == today
                    ).all()

                    sales_text = "\n".join(
                        f"📦 {s.product.name} - {s.flavor.name} - {s.quantity} шт."
                        for s in sales
                    )

                    response.append(
                        f"👤 <b>{customer.name}</b>\n"
                        f"{sales_text}\n"
                        f"— — — — —"
                    )

                await message.answer("\n".join(response), parse_mode="HTML")

            # Предложение скачать таблицу за месяц
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Скачать таблицу за месяц", callback_data="download_customers_month")]
            ])
            await message.answer("Хотите скачать таблицу покупателей за текущий месяц?", reply_markup=markup)

    except Exception as e:
        logger.error(f"Ошибка при загрузке покупателей: {str(e)}")
        await message.answer("❌ Ошибка при загрузке данных о покупателях.")

        


@dp.callback_query(F.data == "download_customers_month")
async def download_customers_month(callback: types.CallbackQuery):
    """Скачивание таблицы покупателей за текущий месяц"""
    try:
        with Session() as session:
            today = datetime.datetime.now().date()
            first_day_of_month = datetime.date(today.year, today.month, 1)
            last_day_of_month = datetime.date(
                today.year + (today.month // 12),
                (today.month % 12) + 1, 1
            ) - datetime.timedelta(days=1)

            # Получаем покупателей за текущий месяц
            customers = session.query(Customer).filter(
                Customer.date >= first_day_of_month,
                Customer.date <= last_day_of_month
            ).order_by(Customer.date).all()

            if not customers:
                await callback.answer("❌ Нет данных о покупателях за текущий месяц.", show_alert=True)
                return

            # Создаем DataFrame для таблицы
            data = []
            for customer in customers:
                sales = session.query(Sale).filter(Sale.customer_id == customer.id).all()
                for sale in sales:
                    data.append({
                        "Дата": customer.date.strftime("%d.%m.%Y"),
                        "Покупатель": customer.name,
                        "Товар": sale.product.name,
                        "Вкус": sale.flavor.name,
                        "Количество": sale.quantity,
                        "Цена продажи": sale.sale_price,
                        "Выручка": sale.quantity * sale.sale_price
                    })

            df = pd.DataFrame(data)

            # Генерация Excel-файла
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Покупатели')

                workbook = writer.book
                worksheet = writer.sheets['Покупатели']

                # Форматирование колонок
                worksheet.set_column('A:A', 12)  # Дата
                worksheet.set_column('B:B', 25)  # Покупатель
                worksheet.set_column('C:C', 20)  # Товар
                worksheet.set_column('D:D', 20)  # Вкус
                worksheet.set_column('E:E', 12)  # Количество
                worksheet.set_column('F:F', 15)  # Цена продажи
                worksheet.set_column('G:G', 15)  # Выручка

            output.seek(0)

            # Отправка файла пользователю
            await callback.message.answer_document(
                types.BufferedInputFile(output.read(), filename="customers_month.xlsx"),
                caption=f"📊 Покупатели за {today.strftime('%B %Y')}"
            )
            await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при генерации таблицы: {str(e)}")
        await callback.answer("❌ Ошибка при создании таблицы.", show_alert=True)

@dp.callback_query(F.data == "quantity_other", RecordSaleState.enter_quantity)
async def select_other_quantity(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для выбора 'Другое' в количестве товара"""
    await callback.message.answer("Введите количество вручную:")
    await state.set_state(RecordSaleState.enter_custom_quantity)  # Новое состояние для ручного ввода

@dp.message(RecordSaleState.enter_custom_quantity)
async def enter_custom_quantity(message: types.Message, state: FSMContext):
    """Обработчик для ручного ввода количества"""
    try:
        quantity = int(message.text)  # Пытаемся преобразовать ввод в число
        if quantity <= 0:
            await message.answer("❌ Количество должно быть больше 0! Введите снова:")
            return

        # Получаем данные из состояния
        data = await state.get_data()

        # Проверяем, есть ли необходимые данные в состоянии
        if "product_id" not in data or "flavor_id" not in data:
            await message.answer("❌ Ошибка: данные о товаре не найдены. Попробуйте начать заново.")
            await state.clear()
            return

        with Session() as session:
            flavor = session.query(Flavor).get(data["flavor_id"])
            if not flavor:
                await message.answer("❌ Ошибка: вкус не найден. Попробуйте снова.")
                await state.clear()
                return

            # Проверяем, достаточно ли товара на складе
            if flavor.quantity < quantity:
                await message.answer(f"❌ Недостаточно товара! Осталось: {flavor.quantity}")
                return

            # Обновляем данные в состоянии
            if "sales_list" not in data:
                data["sales_list"] = []

            product = session.query(Product).get(data["product_id"])
            data["sales_list"].append({
                "product_name": product.name,
                "flavor_name": flavor.name,
                "quantity": quantity
            })

            await state.update_data(sales_list=data["sales_list"])

            # Спрашиваем, добавить ли еще товар
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить ещё товар", callback_data="add_more")],
                [InlineKeyboardButton(text="✅ Завершить продажу", callback_data="finish_sale")]
            ])

            await message.answer(
                f"✅ Количество выбрано: {quantity} шт.\n"
                f"➕ Хотите добавить еще один товар?",
                reply_markup=markup
            )

            await state.set_state(RecordSaleState.confirm_more_items)

    except ValueError:
        await message.answer("❌ Введите целое число!")
    except Exception as e:
        logger.error(f"Ошибка при обработке количества: {str(e)}")
        await message.answer("❌ Ошибка при обработке. Попробуйте снова.")

@dp.callback_query(F.data == "change_quantity")
async def change_quantity(callback: types.CallbackQuery, state: FSMContext):
    """Изменение количества после отказа от подтверждения"""
    data = await state.get_data()

    with Session() as session:
        flavor = session.get(Flavor, data['flavor_id'])

        # Определяем максимальное количество (макс 10)
        max_quantity = min(flavor.quantity, 10)

        # Создаем кнопки 2 ряда (1–5, 6–10)
        quantity_buttons = [
            [InlineKeyboardButton(text=str(i), callback_data=f"quantity_{i}") for i in
             range(1, min(6, max_quantity + 1))],
            [InlineKeyboardButton(text=str(i), callback_data=f"quantity_{i}") for i in
             range(6, max_quantity + 1)]
        ]

        # Если количество больше 10, добавляем кнопку "Другое"
        if flavor.quantity > 10:
            quantity_buttons.append(
                [InlineKeyboardButton(text="🔢 Другое", callback_data="quantity_other")])

        # Добавляем кнопку "Назад"
        quantity_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_flavors")])

        markup = InlineKeyboardMarkup(inline_keyboard=quantity_buttons)

        await callback.message.edit_text("📦 Выберите новое количество:", reply_markup=markup)
        await state.set_state(RecordSaleState.confirm_more_items)

@dp.callback_query(F.data == "channel_all")
async def channel_all_products(callback: types.CallbackQuery):
    session = Session()
    try:
        products = session.query(Product).order_by(Product.name).all()
        if not products:
            await callback.message.edit_text("Нет товаров для отображения.")
            return

        lines = []
        for product in products:
            product_line = f"• {product.name} {int(product.sale_price)}"
            lines.append(product_line)
            for flavor in product.flavors:
                if flavor.quantity == 0:
                    line = f"<blockquote>- <s>{flavor.name}</s></blockquote>"
                else:
                    line = f"<blockquote>- {flavor.name}</blockquote>"
                lines.append(line)
            lines.append("")
        text = "\n".join(lines)
        # Кнопка "🔙 Назад" для возврата в меню актуального прайса
        markup = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_actual_price")]
        ])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        await callback.answer("Актуальный прайс обновлён: весь прайс.")
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")
    finally:
        session.close()


@dp.callback_query(F.data.startswith("channel_prod_"))
async def channel_product_details(callback: types.CallbackQuery):
    prod_id = int(callback.data.split("_")[-1])
    session = Session()
    try:
        product = session.query(Product).get(prod_id)
        if not product:
            await callback.message.edit_text("Товар не найден.")
            return

        lines = [f"• {product.name} {int(product.sale_price)}"]
        for flavor in product.flavors:
            if flavor.quantity == 0:
                line = f"<blockquote>- <s>{flavor.name}</s></blockquote>"
            else:
                line = f"<blockquote>- {flavor.name}</blockquote>"
            lines.append(line)

        # Изменяем кнопку "Назад" на возврат к выбору товара
        markup = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="channel_select")]
        ])

        await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=markup)
        await callback.answer("Прайс товара обновлён.")
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}")
    finally:
        session.close()



@dp.message(F.text == "📦 Показать товары")
async def show_products_menu(message: types.Message):
    with Session() as session:
        products = session.query(Product).all()

        if not products:
            await message.answer("📭 Нет товаров в базе")
            return

        for product in products:
            # Рассчитываем доход с 1 штуки
            profit_per_unit = int(product.sale_price - product.purchase_price)

            # Считаем общее количество товара (по всем вкусам)
            total_quantity = sum(flavor.quantity for flavor in product.flavors)

            # Функция для обрезки длинных названий вкусов
            def shorten_text(text, max_length=28):
                return text if len(text) <= max_length else text[:max_length - 3] + "..."

            # Формируем список вкусов
            flavors_info = [
                f"<blockquote>{'<s>' if flavor.quantity == 0 else ''}{shorten_text(flavor.name)} - {flavor.quantity} шт "
                f"{'🟢' if flavor.quantity > 1 else '🟡' if flavor.quantity == 1 else '🔴'}{'</s>' if flavor.quantity == 0 else ''}</blockquote>"
                for flavor in product.flavors
            ]

            # Финальный текст товара с добавлением цены по акции
            product_text = [
                "- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - ",
                f"📌 <b><u>{product.name.upper()}</u></b> | {total_quantity} шт",
                f"Закуп: {int(product.purchase_price)}₽",
                f"Продажа: {int(product.sale_price)}₽",
                f"Акция (от 2 шт): {int(product.sale_price_2)}₽",
                f"Доход с 1 шт: {profit_per_unit}₽",
                "",
                "🍏 <b>Вкусы:</b>"
            ] + flavors_info + ["- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - "]

            # Отправляем сообщение
            await message.answer("\n".join(product_text), parse_mode="HTML")

    # Меню действий – добавляем кнопку "Обновить канал"
    markup = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📥 Скачать таблицу"),
             types.KeyboardButton(text="📤 Загрузить таблицу")],
            [types.KeyboardButton(text="Обновить канал")],
            [types.KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    await message.answer("📦 <b>Выберите действие с таблицей:</b>", reply_markup=markup)




@dp.message(F.text == "Обновить канал")
async def update_channel_menu(message: types.Message):
    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Показать список всех товаров", callback_data="channel_all")],
        [types.InlineKeyboardButton(text="Выбор товара для показа вкусов", callback_data="channel_select")]
    ])
    await message.answer("Выберите способ обновления канала:", reply_markup=markup)



@dp.callback_query(F.data == "channel_all")
async def channel_all_products(callback: types.CallbackQuery):
    session = Session()
    try:
        products = session.query(Product).order_by(Product.name).all()
        if not products:
            await callback.message.edit_text("Нет товаров для отображения.")
            return

        lines = []
        for product in products:
            # Вывод товара: "• Название Цена"
            product_line = f"• {product.name} {int(product.sale_price)}"
            lines.append(product_line)
            # Перебор вкусов
            for flavor in product.flavors:
                if flavor.quantity == 0:
                    line = f"- <s>{flavor.name}</s> 🔴"
                elif flavor.quantity == 1:
                    line = f"- {flavor.name} 🟡"
                else:
                    line = f"- {flavor.name} 🟢"
                lines.append(line)
            lines.append("")  # пустая строка между товарами

        text = "\n".join(lines)
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer("Канал обновлён: список всех товаров.")
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")
    finally:
        session.close()


@dp.callback_query(F.data == "channel_select")
async def channel_select_product(callback: types.CallbackQuery):
    session = Session()
    try:
        products = session.query(Product).order_by(Product.name).all()
        if not products:
            await callback.message.edit_text("Нет товаров для выбора.")
            return

        buttons = []
        for product in products:
            buttons.append([types.InlineKeyboardButton(text=product.name, callback_data=f"channel_prod_{product.id}")])

        # Добавляем кнопку "Назад" для возврата в меню актуального прайса
        buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_actual_price")])

        markup = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите товар:", reply_markup=markup)
        await callback.answer()
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")
    finally:
        session.close()

@dp.callback_query(F.data == "back_to_actual_price")
async def back_to_actual_price(callback: types.CallbackQuery):
    # Возвращаемся в меню актуального прайса
    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Весь прайс", callback_data="channel_all")],
        [types.InlineKeyboardButton(text="Прайс товара", callback_data="channel_select")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")]
    ])
    await callback.message.edit_text("Выберите способ отображения прайса:", reply_markup=markup)
    await callback.answer()



@dp.callback_query(F.data.startswith("channel_prod_"))
async def channel_product_details(callback: types.CallbackQuery):
    prod_id = int(callback.data.split("_")[-1])
    session = Session()
    try:
        product = session.query(Product).get(prod_id)
        if not product:
            await callback.message.edit_text("Товар не найден.")
            return

        lines = [f"• {product.name} {int(product.sale_price)}"]
        for flavor in product.flavors:
            if flavor.quantity == 0:
                line = f"- <s>{flavor.name}</s> 🔴"
            elif flavor.quantity == 1:
                line = f"- {flavor.name} 🟡"
            else:
                line = f"- {flavor.name} 🟢"
            lines.append(line)
        text = "\n".join(lines)
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer("Информация о товаре обновлена.")
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}")
    finally:
        session.close()







@dp.callback_query(F.data == "cancel_sale")
async def cancel_sale(callback: types.CallbackQuery, state: FSMContext):
    """Отмена продажи"""
    await state.clear()
    await callback.message.edit_text("🚫 Запись продажи отменена.")



def is_navigation_command(text: str) -> bool:
    """Функция определяет, является ли сообщение командой перехода в другой раздел"""
    return text in ["📦 Управление товарами", "💵 Записать продажу", "📦 Показать товары", "📊 Аналитика", "🔙 Назад"]

async def check_navigation(message: types.Message, state: FSMContext):
    """Если пользователь выбрал другой раздел, сбрасываем состояние и возвращаем True"""
    if is_navigation_command(message.text):
        await state.clear()  # Очищаем текущее состояние FSM
        await cmd_start(message)  # Возвращаем пользователя в главное меню
        return True
    return False

@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    markup = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📦 Управление товарами"),
             types.KeyboardButton(text="💵 Записать продажу")],
            [types.KeyboardButton(text="✏️ Редактировать продажи"),
             types.KeyboardButton(text="📦 Показать товары")],
            [types.KeyboardButton(text="📊 Аналитика"),
             types.KeyboardButton(text="Актуальный прайс")],
            [types.KeyboardButton(text="Брак")]
        ],
        resize_keyboard=True
    )
    await message.answer("🏪 <b>Система управления товарами</b>\nВыберите действие:", reply_markup=markup)



@dp.message(lambda message: message.text == "Актуальный прайс")
async def actual_price_menu(message: types.Message):
    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Весь прайс", callback_data="channel_all")],
        [types.InlineKeyboardButton(text="Прайс товара", callback_data="channel_select")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")]
    ])
    await message.answer("Выберите способ отображения прайса:", reply_markup=markup)

@dp.callback_query(F.data == "back_to_product_selection")
async def back_to_product_selection(callback: types.CallbackQuery, state: FSMContext):
    session = Session()
    try:
        products = session.query(Product).order_by(Product.name).all()
        if not products:
            await callback.message.edit_text("Нет товаров для выбора.")
            return

        buttons = []
        for product in products:
            buttons.append([types.InlineKeyboardButton(text=product.name, callback_data=f"channel_prod_{product.id}")])
        # Добавляем кнопку "🔙 Назад" для возврата в главное меню актуального прайса
        buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_actual_price")])
        markup = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите товар:", reply_markup=markup)
        await callback.answer()
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}")
    finally:
        session.close()



@dp.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_callback(callback: types.CallbackQuery):
    # Удаляем текущее inline-сообщение
    await callback.message.delete()
    # Переходим в главное меню
    await cmd_start(callback.message)



@dp.message(AddProductState.enter_name)
async def enter_product_name(message: types.Message, state: FSMContext):
    if await check_navigation(message, state):
        return

    name = message.text.strip()

    if not name:
        await message.answer("❌ Имя товара не может быть пустым! Введите название товара снова:")
        return

    with Session() as session:
        existing_product = session.query(Product).filter_by(name=name).first()
        if existing_product:
            await message.answer("❌ Товар с таким именем уже существует! Введите другое название:")
            return  # Не меняем состояние, даем повторно ввести

    await state.update_data(name=name)
    await message.answer("Введите цены через пробел:\nФормат: <b>Закупочная Продажная Акция</b>\nПример: 100 200 150")
    await state.set_state(AddProductState.enter_prices)

@dp.message(AddProductState.enter_prices)
async def enter_product_prices(message: types.Message, state: FSMContext):
    if message.text.lower() in ["отмена", "/cancel"]:
        await state.clear()
        await cmd_start(message)
        return

    try:
        # Парсим 3 значения вместо 2
        purchase_price, sale_price, sale_price_2 = map(float, message.text.split())
        await state.update_data(
            purchase_price=purchase_price,
            sale_price=sale_price,
            sale_price_2=sale_price_2
        )
        await message.answer("Введите вкусы и количества (каждый с новой строки):\nПример:\nЯблоко 10\nБанан 5",
                            reply_markup=types.ReplyKeyboardRemove())
        await state.set_state(AddProductState.enter_flavors)
    except:
        await message.answer("❌ Неверный формат цен! Используйте: Закупочная Продажа_1шт Продажа_2шт\nПример: 100 200 150")
        await state.set_state(AddProductState.enter_prices)



# ======================= УПРАВЛЕНИЕ ТОВАРАМИ ======================= #
async def confirm_sale(message, quantity, state):
    """Подтверждение продажи"""
    data = await state.get_data()

    with Session() as session:
        flavor = session.get(Flavor, data['flavor_id'])
        product = session.get(Product, data['product_id'])

        if flavor.quantity < quantity:
            await message.answer(f"❌ Недостаточно товара! Осталось: {flavor.quantity}")
            return

        await state.update_data(quantity=quantity)

        # Создаем кнопки подтверждения
        confirm_buttons = [
            [InlineKeyboardButton(text="✅ Да, подтвердить", callback_data="confirm_sale")],
            [InlineKeyboardButton(text="🔄 Изменить количество", callback_data="change_quantity")],
            [InlineKeyboardButton(text="🔙 Выйти в меню", callback_data="cancel_sale")]
        ]
        markup = InlineKeyboardMarkup(inline_keyboard=confirm_buttons)

        await message.edit_text(
            f"Вы выбрали:\n"
            f"📦 <b>Товар:</b> {product.name}\n"
            f"🍏 <b>Вкус:</b> {flavor.name}\n"
            f"📦 <b>Количество:</b> {quantity} шт.\n\n"
            f"Все верно?",
            reply_markup=markup,
            parse_mode="HTML"
        )



@dp.callback_query(F.data == "cancel_delete", EditProductState.confirm_delete)
async def cancel_delete_product(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    product_id = data['product_id']

    with Session() as session:
        product = session.get(Product, product_id)
        if product:
            markup = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="✏️ Изменить цены", callback_data="edit_prices"),
                 types.InlineKeyboardButton(text="➕ Добавить вкусы", callback_data="add_flavors")],
                [types.InlineKeyboardButton(text="➖ Удалить вкусы", callback_data="remove_flavors"),
                 types.InlineKeyboardButton(text="🗑️ Удалить товар", callback_data="delete_product")],
                [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_products")]
            ])
            await callback.message.edit_text(
                f"❌ Удаление отменено. Товар: {product.name}",
                reply_markup=markup
            )
            await state.set_state(EditProductState.select_action)
        else:
            await callback.answer("Товар не найден!")
            await state.clear()
            await cmd_start(callback.message)


@dp.callback_query(F.data == "back_to_products_list", EditSaleState.select_flavor)
async def back_to_products_list(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к списку товаров"""
    await start_sale_editing(callback, state)

@dp.message(F.text == "📦 Управление товарами")
async def products_menu(message: types.Message):
    markup = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🆕 Создать товар"),
             types.KeyboardButton(text="✏️ Редактировать товар")],
            [types.KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    await message.answer("📦 <b>Меню управления товарами</b>", reply_markup=markup)


@dp.callback_query(F.data == "channel_all")
async def channel_all_products(callback: types.CallbackQuery):
    session = Session()
    try:
        products = session.query(Product).order_by(Product.name).all()
        if not products:
            await callback.message.edit_text("Нет товаров для отображения.")
            return

        lines = []
        for product in products:
            # Отображаем товар как "• Название Цена"
            product_line = f"• {product.name} {int(product.sale_price)}"
            lines.append(product_line)
            # Перебор вкусов: если количество равно 0 – оборачиваем название в <s>...</s>,
            # иначе выводим просто название.
            for flavor in product.flavors:
                if flavor.quantity == 0:
                    line = f"- <s>{flavor.name}</s>"
                else:
                    line = f"- {flavor.name}"
                lines.append(line)
            lines.append("")  # пустая строка между товарами

        text = "\n".join(lines)
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer("Канал обновлён: список всех товаров.")
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")
    finally:
        session.close()


@dp.callback_query(F.data.startswith("channel_prod_"))
async def channel_product_details(callback: types.CallbackQuery):
    prod_id = int(callback.data.split("_")[-1])
    session = Session()
    try:
        product = session.query(Product).get(prod_id)
        if not product:
            await callback.message.edit_text("Товар не найден.")
            return

        lines = [f"• {product.name} {int(product.sale_price)}"]
        for flavor in product.flavors:
            if flavor.quantity == 0:
                line = f"- <s>{flavor.name}</s>"
            else:
                line = f"- {flavor.name}"
            lines.append(line)
        text = "\n".join(lines)
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer("Информация о товаре обновлена.")
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}")
    finally:
        session.close()



@dp.message(F.text == "📦 Показать товары")
async def show_products_menu(message: types.Message):
    with Session() as session:
        products = session.query(Product).all()

        if not products:
            await message.answer("📭 Нет товаров в базе")
            return

        for product in products:
            # Рассчитываем доход с 1 штуки
            profit_per_unit = int(product.sale_price - product.purchase_price)

            # Считаем общее количество товара (по всем вкусам)
            total_quantity = sum(flavor.quantity for flavor in product.flavors)

            # Функция для обрезки длинных названий вкусов
            def shorten_text(text, max_length=28):
                return text if len(text) <= max_length else text[:max_length - 3] + "..."

            # Формируем список вкусов
            flavors_info = [
                f"<blockquote>{'<s>' if flavor.quantity == 0 else ''}{shorten_text(flavor.name)} - {flavor.quantity} шт "
                f"{'🟢' if flavor.quantity > 1 else '🟡' if flavor.quantity == 1 else '🔴'}{'</s>' if flavor.quantity == 0 else ''}</blockquote>"
                for flavor in product.flavors
            ]

            # Финальный текст товара
            product_text = [
                "- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - ",
                f"📌 <b><u>{product.name.upper()}</u></b> | {total_quantity} шт",  # Заголовок жирный и подчеркнутый
                f"Закуп: {int(product.purchase_price)}₽",
                f"Продажа: {int(product.sale_price)}₽",
                f"Доход с 1 шт: {profit_per_unit}₽",
                "",
                "🍏 <b>Вкусы:</b>"
            ] + flavors_info + ["- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - "]

            # Отправляем сообщение
            await message.answer("\n".join(product_text), parse_mode="HTML")

    # Меню действий
    markup = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📥 Скачать таблицу"),
             types.KeyboardButton(text="📤 Загрузить таблицу")],
            [types.KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    await message.answer("📦 <b>Выберите действие с таблицей:</b>", reply_markup=markup)






@dp.message(F.text == "🔙 Назад")
async def back_to_main(message: types.Message):
    await cmd_start(message)

@dp.message(F.text == "🆕 Создать товар")
async def start_adding_product(message: types.Message, state: FSMContext):
    await state.set_state(AddProductState.enter_name)
    await message.answer("Введите название товара:", reply_markup=types.ReplyKeyboardRemove())


@dp.message(AddProductState.enter_name)
async def enter_product_name(message: types.Message, state: FSMContext):
    if message.text in ["📦 Управление товарами", "💵 Записать продажу", "📦 Показать товары", "📊 Аналитика", "🔙 Назад"]:
        await state.clear()
        await cmd_start(message)
        return


    name = message.text.strip()
    if not name:
        await message.answer("❌ Имя товара не может быть пустым!")
        return
    await state.update_data(name=name)
    await message.answer("Введите цены через пробел:\nФормат: <b>Закупочная Продажная Акция</b>\nПример: 100 200 150")
    await state.set_state(AddProductState.enter_prices)


@dp.message(AddProductState.enter_prices)
async def enter_product_prices(message: types.Message, state: FSMContext):
    # Проверяем, не нажал ли пользователь кнопку главного меню или "Назад"
    if message.text in ["📦 Управление товарами", "💵 Записать продажу", "📦 Показать товары", "📊 Аналитика", "🔙 Назад"]:
        await state.clear()  # Очищаем текущее состояние
        await cmd_start(message)  # Возвращаем пользователя в главное меню
        return

    # Основная логика обработчика
    try:
        purchase_price, sale_price = map(float, message.text.split())
        await state.update_data(purchase_price=purchase_price, sale_price=sale_price)
        await message.answer("Введите вкусы и количества (каждый с новой строки):\nПример:\nЯблоко 10\nБанан 5")
        await state.set_state(AddProductState.enter_flavors)
    except:
        await message.answer("❌ Неверный формат цен! Повторите ввод в формате:\n<b>Закупочная Продажная Акция</b>\nПример: 100 200 150")
        await state.set_state(AddProductState.enter_prices)


@dp.message(AddProductState.enter_flavors)
async def enter_product_flavors(message: types.Message, state: FSMContext):
    if await check_navigation(message, state):
        return

    data = await state.get_data()
    with Session() as session:
        product = session.query(Product).filter_by(name=data['name']).first()
        if not product:
            product = Product(
                name=data['name'],
                purchase_price=data['purchase_price'],
                sale_price=data['sale_price'],
                sale_price_2=data['sale_price_2']
            )
            session.add(product)
            session.commit()

        dup_list = []   # Список для вкусов-дубликатов
        new_list = []   # Список для новых вкусов
        errors = []

        for line in message.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                flavor_name, qty = parse_flavor_line(line)
                norm_name = flavor_name.lower().strip()
                existing = session.query(Flavor).filter(
                    Flavor.product_id == product.id,
                    func.lower(func.trim(Flavor.name)) == norm_name
                ).first()
                if existing:
                    dup_list.append({"id": existing.id, "name": flavor_name, "quantity": qty})
                else:
                    new_list.append({"name": flavor_name, "quantity": qty})
            except ValueError as e:
                errors.append(str(e))

        if errors:
            await message.answer("Обнаружены ошибки:\n" + "\n".join(errors[:5]) +
                                 "\nПожалуйста, введите данные вкусов снова:")
            return

        if dup_list:
            # Сохраняем данные о дубликатах и новых вкусах в состоянии
            await state.update_data(duplicate_flavors=dup_list, new_flavors=new_list, product_id=product.id)
            dup_names = ", ".join([dup["name"] for dup in dup_list])
            markup = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="Да", callback_data="sum_duplicates_yes"),
                 types.InlineKeyboardButton(text="Нет", callback_data="sum_duplicates_no")]
            ])
            await message.answer(f"Вкусы {dup_names} уже существуют. Суммировать их количества?", reply_markup=markup)
            return
        else:
            if new_list:
                for nf in new_list:
                    new_flavor = Flavor(name=nf["name"], quantity=nf["quantity"], product=product)
                    session.add(new_flavor)
                session.commit()
                await message.answer(f"✅ Товар <b>{product.name}</b> добавлен!\nНовых вкусов: {len(new_list)}")
                await state.clear()
                await cmd_start(message)
            else:
                await message.answer("❌ Не добавлено ни одного вкуса! Повторите ввод:")

@dp.callback_query(F.data == "sum_duplicates_yes")
async def sum_duplicates_yes(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    dup_list = data.get("duplicate_flavors", [])
    new_list = data.get("new_flavors", [])
    product_id = data.get("product_id")
    with Session() as session:
        product = session.get(Product, product_id)
        # Обновляем количество для дубликатов
        for dup in dup_list:
            flavor = session.get(Flavor, dup["id"])
            if flavor:
                flavor.quantity += dup["quantity"]
        # Добавляем новые вкусы
        for nf in new_list:
            new_flavor = Flavor(name=nf["name"], quantity=nf["quantity"], product=product)
            session.add(new_flavor)
        session.commit()
        await callback.message.answer(
            f"✅ Товар <b>{product.name}</b> обновлён!\n"
            f"Количество для дубликатов суммировано, новых вкусов добавлено: {len(new_list)}"
        )
    await state.clear()
    await cmd_start(callback.message)

@dp.callback_query(F.data == "sum_duplicates_no")
async def sum_duplicates_no(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Пожалуйста, введите вкусы и количества заново:")
    await state.clear()


# Команда "✏️ Редактировать товар"
@dp.message(F.text == "✏️ Редактировать товар")
async def start_editing_product(message: types.Message, state: FSMContext):
    with Session() as session:
        products = session.query(Product).filter(Product.name.isnot(None)).all()

        if not products:
            await message.answer("❌ Нет товаров для редактирования")
            return

        buttons = []
        for product in products:
            buttons.append([types.InlineKeyboardButton(
                text=product.name,
                callback_data=f"edit_{product.id}"
            )])

        markup = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Выберите товар для редактирования:", reply_markup=markup)
        await state.set_state(EditProductState.select_product)


# Обработчик выбора товара из списка
@dp.callback_query(F.data.startswith("edit_"), EditProductState.select_product)
async def select_product_to_edit(callback: types.CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[1])
    await state.update_data(product_id=product_id)

    with Session() as session:
        product = session.get(Product, product_id)
        product_info = f"📌 <b>{product.name.upper()}</b>\n"
        product_info += f"Закуп: {int(product.purchase_price)}₽\n"
        product_info += f"Продажа: {int(product.sale_price)}₽\n"
        product_info += f"Акция (от 2 шт): {int(product.sale_price_2)}₽\n"
        product_info += "Остатки по вкусам:\n"
        for flavor in product.flavors:
            product_info += f" - {flavor.name}: {flavor.quantity} шт.\n"

    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✏️ Изменить цены", callback_data="edit_prices"),
         types.InlineKeyboardButton(text="➕ Добавить вкусы", callback_data="add_flavors")],
        [types.InlineKeyboardButton(text="➖ Удалить вкусы", callback_data="remove_flavors"),
         types.InlineKeyboardButton(text="✏️ Редактировать количество", callback_data="edit_flavor_quantity")],
        [types.InlineKeyboardButton(text="🗑️ Удалить товар", callback_data="delete_product")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_products")]
    ])

    full_text = product_info + "\nВыберите действие:"
    await callback.message.edit_text(full_text, reply_markup=markup, parse_mode="HTML")
    await state.set_state(EditProductState.select_action)



@dp.callback_query(F.data == "edit_flavor_quantity", EditProductState.select_action)
async def select_flavor_for_editing(callback: types.CallbackQuery, state: FSMContext):
    """Выбор вкуса, количество которого нужно изменить"""
    data = await state.get_data()
    product_id = data.get("product_id")

    with Session() as session:
        product = session.get(Product, product_id)
        if not product or not product.flavors:
            await callback.message.answer("❌ Ошибка: товар или вкусы не найдены.")
            return

        # Создаем кнопки выбора вкусов
        flavor_buttons = [
            [types.InlineKeyboardButton(text=f"{flavor.name} ({flavor.quantity})", callback_data=f"edit_quantity_{flavor.id}")]
            for flavor in product.flavors
        ]

        # Добавляем кнопку "Назад"
        flavor_buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_edit_product")])

        markup = types.InlineKeyboardMarkup(inline_keyboard=flavor_buttons)

        await callback.message.edit_text("Выберите вкус для редактирования количества:", reply_markup=markup)
        await state.set_state(EditProductState.select_action)


@dp.callback_query(F.data.startswith("edit_quantity_"), EditProductState.select_action)
async def request_new_quantity(callback: types.CallbackQuery, state: FSMContext):
    """Запрос на ввод нового количества"""
    flavor_id = int(callback.data.split("_")[2])
    await state.update_data(flavor_id=flavor_id)

    await callback.message.answer("Введите новое количество для выбранного вкуса:")
    await state.set_state(EditProductState.update_flavor_quantity)


@dp.message(EditProductState.update_flavor_quantity)
async def update_flavor_quantity(message: types.Message, state: FSMContext):
    """Обновление количества вкуса в базе"""
    try:
        new_quantity = int(message.text)
        if new_quantity < 0:
            await message.answer("❌ Количество не может быть отрицательным. Введите снова:")
            return

        data = await state.get_data()
        flavor_id = data.get("flavor_id")

        with Session() as session:
            flavor = session.get(Flavor, flavor_id)
            if not flavor:
                await message.answer("❌ Ошибка: вкус не найден.")
                return

            # ✅ Обновляем количество
            flavor.quantity = new_quantity
            session.commit()

            # ❗️ Теперь повторно получаем объект из БД
            session.refresh(flavor)

            await message.answer(f"✅ Количество для {flavor.name} обновлено: {new_quantity} шт.")
            await state.clear()

    except ValueError:
        await message.answer("❌ Введите корректное число!")
    except Exception as e:
        logger.error(f"Ошибка при обновлении количества: {str(e)}")
        await message.answer("❌ Произошла ошибка, попробуйте снова.")


@dp.callback_query(F.data == "back_to_edit_product", EditProductState.select_flavor)
async def back_to_edit_product(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает пользователя к выбору товара для редактирования"""
    data = await state.get_data()
    product_id = data.get("product_id")

    if not product_id:
        await callback.message.answer("❌ Ошибка: данные о товаре утеряны. Попробуйте заново.")
        await state.clear()
        return

    with Session() as session:
        product = session.query(Product).get(product_id)

        if not product:
            await callback.message.answer("❌ Ошибка: товар не найден. Попробуйте снова.")
            await state.clear()
            return

        # Формируем клавиатуру для редактирования товара
        markup = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="✏️ Изменить цены", callback_data="edit_prices"),
             types.InlineKeyboardButton(text="➕ Добавить вкусы", callback_data="add_flavors")],
            [types.InlineKeyboardButton(text="➖ Удалить вкусы", callback_data="remove_flavors"),
             types.InlineKeyboardButton(text="🔄 Изменить количество вкуса", callback_data="edit_flavor_quantity")],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_products")]
        ])

        # Редактируем предыдущее сообщение
        await callback.message.edit_text(f"Выберите действие для товара <b>{product.name}</b>:",
                                         reply_markup=markup, parse_mode="HTML")
        await state.set_state(EditProductState.select_action)









@dp.callback_query(F.data == "delete_product", EditProductState.select_action)
async def delete_product_handler(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    product_id = data.get('product_id')

    with Session() as session:
        product = session.get(Product, product_id)
        if product:
            markup = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_delete_{product_id}")],
                [types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_delete")]
            ])
            await callback.message.edit_text(
                f"❗ Вы уверены, что хотите удалить товар <b>{product.name}</b>?",
                reply_markup=markup
            )
            await state.set_state(EditProductState.confirm_delete)
        else:
            await callback.answer("Товар не найден!", show_alert=True)
            await state.clear()
            await cmd_start(callback.message)



@dp.callback_query(EditProductState.select_action)
async def handle_edit_action(callback: types.CallbackQuery, state: FSMContext):
    # Проверяем, не нажал ли пользователь кнопку "Назад" или из главного меню
    if callback.data in ["📦 Управление товарами", "💵 Записать продажу", "📦 Показать товары", "📊 Аналитика", "🔙 Назад"]:
        await state.clear()  # Сбрасываем текущее состояние
        await cmd_start(callback.message)  # Возвращаем пользователя в главное меню
        return

    # Основная логика обработчика
    action = callback.data
    data = await state.get_data()

    if action == "edit_prices":
        await callback.message.answer("Введите новые цены через пробел:\nФормат: <b>Закупочная Продажная</b>")
        await state.set_state(EditProductState.update_prices)

    elif action == "add_flavors":
        await callback.message.answer("Введите новые вкусы и количества (каждый с новой строки):")
        await state.set_state(EditProductState.add_flavors)

    elif action == "remove_flavors":
        with Session() as session:
            product = session.query(Product).get(data['product_id'])
            markup = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=f.name, callback_data=f"remove_{f.id}")]
                for f in product.flavors
            ])
            await callback.message.answer("Выберите вкусы для удаления:", reply_markup=markup)
            await state.set_state(EditProductState.remove_flavors)


@dp.message(EditProductState.update_prices)
async def update_prices(message: types.Message, state: FSMContext):
    try:
        # Ожидаем 3 значения
        purchase_price, sale_price, sale_price_2 = map(float, message.text.split())
        data = await state.get_data()

        with Session() as session:
            product = session.query(Product).get(data['product_id'])
            product.purchase_price = purchase_price
            product.sale_price = sale_price
            product.sale_price_2 = sale_price_2  # Обновляем новое поле
            session.commit()

        await message.answer("✅ Цены успешно обновлены!")
        await state.clear()
    except:
        await message.answer("❌ Неверный формат ввода! Используйте: Закупочная Продажа_1шт Продажа_2шт\nПример: 100 200 150")
        return


@dp.callback_query(F.data.startswith("confirm_delete_"))
async def confirm_delete_product(callback: types.CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[-1])

    with Session() as session:
        product = session.get(Product, product_id)
        if product:
            session.delete(product)
            session.commit()
            await callback.message.edit_text(f"✅ Товар <b>{product.name}</b> удален!")
            await state.clear()
            await cmd_start(callback.message)
        else:
            await callback.answer("Товар не найден!", show_alert=True)

            @dp.callback_query(F.data == "cancel_delete", EditProductState.confirm_delete)
            async def cancel_delete_product(callback: types.CallbackQuery, state: FSMContext):
                data = await state.get_data()
                product_id = data['product_id']

                with Session() as session:
                    product = session.get(Product, product_id)
                    if product:
                        markup = types.InlineKeyboardMarkup(inline_keyboard=[
                            [types.InlineKeyboardButton(text="✏️ Изменить цены", callback_data="edit_prices"),
                             types.InlineKeyboardButton(text="➕ Добавить вкусы", callback_data="add_flavors")],
                            [types.InlineKeyboardButton(text="➖ Удалить вкусы", callback_data="remove_flavors"),
                             types.InlineKeyboardButton(text="🗑️ Удалить товар", callback_data="delete_product")]
                        ])

                        await callback.message.edit_text(
                            f"❌ Удаление отменено. Товар: {product.name}",
                            reply_markup=markup
                        )
                        await state.set_state(EditProductState.select_action)
                    else:
                        await callback.answer("Товар не найден!")
                        await state.clear()
                        await cmd_start(callback.message)

                @dp.callback_query(F.data == "remove_flavors", EditProductState.select_action)
                async def select_flavors_to_remove(callback: types.CallbackQuery, state: FSMContext):
                    data = await state.get_data()
                    product_id = data['product_id']

                    with Session() as session:
                        product = session.get(Product, product_id)
                        if product and product.flavors:
                            markup = types.InlineKeyboardMarkup(inline_keyboard=[
                                                                                    [types.InlineKeyboardButton(
                                                                                        text=f"❌ {flavor.name}",
                                                                                        callback_data=f"remove_{flavor.id}")]
                                                                                    for flavor in product.flavors
                                                                                ] + [
                                                                                    [types.InlineKeyboardButton(
                                                                                        text="🔙 Назад",
                                                                                        callback_data="back_to_actions")]
                                                                                ])

                            await callback.message.edit_text(
                                "Выберите вкусы для удаления:",
                                reply_markup=markup
                            )
                            await state.set_state(EditProductState.remove_flavors)
                        else:
                            await callback.answer("Нет доступных вкусов!", show_alert=True)

                @dp.callback_query(F.data.startswith("remove_"), EditProductState.remove_flavors)
                async def remove_flavor_handler(callback: types.CallbackQuery, state: FSMContext):
                    flavor_id = int(callback.data.split("_")[1])

                    with Session() as session:
                        flavor = session.get(Flavor, flavor_id)
                        if flavor:
                            product_name = flavor.product.name
                            session.delete(flavor)
                            session.commit()
                            await callback.message.edit_text(
                                f"✅ Вкус {flavor.name} удален из {product_name}"
                            )
                            await select_flavors_to_remove(callback, state)
                        else:
                            await callback.answer("Вкус не найден!", show_alert=True)

                @dp.callback_query(F.data == "back_to_actions", EditProductState.remove_flavors)
                async def back_to_actions_menu(callback: types.CallbackQuery, state: FSMContext):
                    await select_product_to_edit(callback, state)


@dp.message(EditProductState.add_flavors)
async def add_flavors(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        with Session() as session:
            product = session.query(Product).get(data['product_id'])
            if not product:
                await message.answer("❌ Товар не найден!")
                return

            # Обновляем объект product, чтобы список вкусов был актуальным
            session.refresh(product)

            updated_count = 0
            new_count = 0
            errors = []

            # Перебираем каждую строку ввода
            for line in message.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    # Разбираем строку, например "Яблоко 10"
                    name, quantity = parse_flavor_line(line)
                    norm_name = name.strip().lower()

                    # Ищем уже существующий вкус среди связанных с продуктом
                    found_flavor = None
                    for flavor in product.flavors:
                        if flavor.name.strip().lower() == norm_name:
                            found_flavor = flavor
                            break

                    if found_flavor:
                        # Если нашли – суммируем количество
                        found_flavor.quantity += quantity
                        updated_count += 1
                    else:
                        # Если нет – создаём новый вкус
                        new_flavor = Flavor(name=name.strip(), quantity=quantity, product=product)
                        session.add(new_flavor)
                        new_count += 1

                except ValueError:
                    errors.append(f"❌ Ошибка в строке: {line}")

            if errors:
                await message.answer("⚠️ Обнаружены ошибки:\n" + "\n".join(errors[:5]) +
                                     "\n\n🔄 Введите данные снова (каждый с новой строки):")
                return

            session.commit()
            await message.answer(
                f"✅ Товар <b>{product.name}</b> обновлён!\n"
                f"Новых вкусов добавлено: {new_count}\n"
                f"Количество обновлено для: {updated_count} вкусов."
            )
            await state.clear()

    except Exception as e:
        logger.error(f"Ошибка при добавлении вкусов: {str(e)}")
        await message.answer("❌ Ошибка при обработке. Попробуйте снова.")





@dp.callback_query(F.data.startswith("remove_"), EditProductState.remove_flavors)
async def remove_flavor(callback: types.CallbackQuery, state: FSMContext):
    flavor_id = int(callback.data.split("_")[1])
    data = await state.get_data()

    with Session() as session:
        flavor = session.query(Flavor).get(flavor_id)
        session.delete(flavor)
        session.commit()

    await callback.message.answer("✅ Вкус успешно удален!")
    await state.clear()
# ======================= Работа с таблицей товара ======================= #
@dp.message(F.text == "📥 Скачать таблицу")
async def download_products_table(message: types.Message):
    with Session() as session:
        products = session.query(Product).order_by(Product.name).all()

        # Создаем структуру данных
        data = []
        for product in products:
            item = {
                'Товар': product.name,
                'Закупочная цена': product.purchase_price,
                'Цена продажи': product.sale_price,
                'Вкусы': [{'name': f.name, 'quantity': f.quantity} for f in product.flavors]
            }
            data.append(item)

        # Создаем плоский DataFrame
        rows = []
        for item in data:
            if not item['Вкусы']:
                rows.append({
                    'Товар': item['Товар'],
                    'Закупочная цена': item['Закупочная цена'],
                    'Цена продажи': item['Цена продажи'],
                    'Вкус': 'Нет вкусов',
                    'Количество': 0
                })
            else:
                for i, flavor in enumerate(item['Вкусы']):
                    rows.append({
                        'Товар': item['Товар'] if i == 0 else '',  # Заполняем только для первой строки
                        'Закупочная цена': item['Закупочная цена'] if i == 0 else '',
                        'Цена продажи': item['Цена продажи'] if i == 0 else '',
                        'Вкус': flavor['name'],
                        'Количество': flavor['quantity']
                    })

        df = pd.DataFrame(rows)

        # Генерация Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Товары', startrow=0)

            workbook = writer.book
            worksheet = writer.sheets['Товары']

            # Формат для объединенных ячеек
            merge_format = workbook.add_format({
                'valign': 'top',
                'border': 1,
                'text_wrap': True
            })

            # Формат для последней строки товара (жирная линия)
            border_format = workbook.add_format({
                'bottom': 2,  # Жирная нижняя граница
                'valign': 'top',
                'border': 1,
                'text_wrap': True
            })

            # Объединение ячеек для строк с несколькими вкусами
            row_idx = 1
            for product in data:
                flavor_count = len(product['Вкусы']) or 1  # Количество вкусов или 1 (если их нет)

                if flavor_count == 1:
                    # Если один вкус, выделяем строку жирной линией
                    worksheet.write(row_idx, 0, product['Товар'], border_format)
                    worksheet.write(row_idx, 1, product['Закупочная цена'], border_format)
                    worksheet.write(row_idx, 2, product['Цена продажи'], border_format)
                    worksheet.write(row_idx, 3, product['Вкусы'][0]['name'] if product['Вкусы'] else 'Нет вкусов', border_format)
                    worksheet.write(row_idx, 4, product['Вкусы'][0]['quantity'] if product['Вкусы'] else 0, border_format)
                else:
                    # Если несколько вкусов, объединяем ячейки для товара
                    worksheet.merge_range(row_idx, 0, row_idx + flavor_count - 1, 0, product['Товар'], merge_format)
                    worksheet.merge_range(row_idx, 1, row_idx + flavor_count - 1, 1, product['Закупочная цена'], merge_format)
                    worksheet.merge_range(row_idx, 2, row_idx + flavor_count - 1, 2, product['Цена продажи'], merge_format)

                    # Форматируем строки для вкусов
                    for flavor_idx in range(flavor_count):
                        current_row = row_idx + flavor_idx
                        if flavor_idx == flavor_count - 1:  # Последняя строка товара
                            worksheet.write(current_row, 3, product['Вкусы'][flavor_idx]['name'], border_format)
                            worksheet.write(current_row, 4, product['Вкусы'][flavor_idx]['quantity'], border_format)
                        else:  # Обычные строки вкусов без жирной линии
                            worksheet.write(current_row, 3, product['Вкусы'][flavor_idx]['name'], merge_format)
                            worksheet.write(current_row, 4, product['Вкусы'][flavor_idx]['quantity'], merge_format)

                # Увеличиваем индекс строки
                row_idx += flavor_count

            # Автоподбор ширины колонок
            for i, width in enumerate([25, 15, 15, 30, 15]):
                worksheet.set_column(i, i, width)

        output.seek(0)
        await message.answer_document(
            types.BufferedInputFile(output.read(), filename="products.xlsx"),
            caption="📦 Таблица товаров"
        )



# ======================= Запись продажи ======================= #
@dp.message(F.text == "💵 Записать продажу")
async def start_sale_recording(message: types.Message, state: FSMContext):
    try:
        with Session() as session:
            products = session.query(Product).all()
            if not products:
                await message.answer("❌ Нет товаров для продажи")
                return

            # Создаем кнопки для товаров
            product_buttons = [
                [types.InlineKeyboardButton(text=f"{p.name}", callback_data=f"product_{p.id}")]
                for p in products
            ]

            # Добавляем кнопку "Назад"
            product_buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")])

            markup = types.InlineKeyboardMarkup(inline_keyboard=product_buttons)
            await message.answer("Выберите товар:", reply_markup=markup)
            await state.set_state(RecordSaleState.select_product)
    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        await message.answer("❌ Ошибка при загрузке товаров")

@dp.callback_query(F.data == "back_to_main_menu", RecordSaleState.select_product)
async def back_to_main_menu(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Назад' при выборе товара"""
    try:
        # Удаляем сообщение с выбором товара
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {str(e)}")

    await state.clear()  # Очищаем текущее состояние
    await cmd_start(callback.message)  # Возвращаем пользователя в главное меню




# Разместить здесь ↓
@dp.callback_query(F.data == "cancel_sale", RecordSaleState.select_product)
async def cancel_sale(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Запись продажи отменена.")
    await cmd_start(callback.message)


@dp.callback_query(F.data.startswith("product_"), RecordSaleState.select_product)
async def select_product(callback: types.CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[1])
    await state.update_data(product_id=product_id)

    with Session() as session:
        product = session.query(Product).get(product_id)

        # Получаем данные о текущей продаже
        data = await state.get_data()
        sales_list = data.get("sales_list", [])

        # Получаем список уже добавленных вкусов для текущего товара
        added_flavors = [sale["flavor_name"] for sale in sales_list if sale["product_name"] == product.name]

        # Формируем список доступных вкусов, исключая уже добавленные
        available_flavors = [f for f in product.flavors if f.name not in added_flavors]

        if not available_flavors:
            await callback.answer("❌ Все доступные вкусы уже добавлены!", show_alert=True)
            return

        # Создаем кнопки для доступных вкусов
        flavor_buttons = [
            [types.InlineKeyboardButton(text=f"{flavor.name} ({flavor.quantity})", callback_data=f"flavor_{flavor.id}")]
            for flavor in available_flavors
        ]

        # Добавляем кнопку "Назад"
        flavor_buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_products")])

        markup = types.InlineKeyboardMarkup(inline_keyboard=flavor_buttons)

        await callback.message.edit_text("Выберите вкус:", reply_markup=markup)
        await state.set_state(RecordSaleState.select_flavor)


from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


@dp.callback_query(F.data == "back_to_products", RecordSaleState.select_flavor)
async def back_to_products(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к списку товаров"""
    try:
        with Session() as session:
            products = session.query(Product).all()
            if not products:
                await callback.message.answer("❌ Нет товаров для продажи")
                return

            # Создаем кнопки для товаров
            product_buttons = [
                [InlineKeyboardButton(text=f"{p.name}", callback_data=f"product_{p.id}")]
                for p in products
            ]

            # Добавляем кнопку "Назад" к списку товаров
            product_buttons.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main_menu")])

            markup = InlineKeyboardMarkup(inline_keyboard=product_buttons)

            # Редактируем текущее сообщение, заменяя его на выбор товара
            await callback.message.edit_text("Выберите товар:", reply_markup=markup)
            await state.set_state(RecordSaleState.select_product)  # Возвращаемся к выбору товара
    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        await callback.message.answer("❌ Ошибка при загрузке товаров")


@dp.callback_query(F.data.startswith("flavor_"), RecordSaleState.select_flavor)
async def select_flavor(callback: types.CallbackQuery, state: FSMContext):
    """Выбор вкуса и генерация кнопок выбора количества"""
    flavor_id = int(callback.data.split("_")[1])
    await state.update_data(flavor_id=flavor_id)

    with Session() as session:
        flavor = session.get(Flavor, flavor_id)
        if not flavor:
            await callback.answer("❌ Ошибка: Вкус не найден!", show_alert=True)
            return

        # Получаем данные о текущей продаже
        data = await state.get_data()
        sales_list = data.get("sales_list", [])

        # Получаем список уже добавленных вкусов для текущего товара
        added_flavors = [sale["flavor_name"] for sale in sales_list if sale["product_name"] == flavor.product.name]

        # Формируем список доступных вкусов, исключая уже добавленные
        available_flavors = [f for f in flavor.product.flavors if f.name not in added_flavors]

        if not available_flavors:
            await callback.answer("❌ Все доступные вкусы уже добавлены!", show_alert=True)
            return

        max_quantity = min(flavor.quantity, 10)  # Ограничение на 10

        # Формируем кнопки выбора количества
        quantity_buttons = [
            [InlineKeyboardButton(text=str(i), callback_data=f"quantity_{i}") for i in range(1, min(6, max_quantity + 1))],
            [InlineKeyboardButton(text=str(i), callback_data=f"quantity_{i}") for i in range(6, max_quantity + 1)]
        ]

        # Если больше 10, добавляем кнопку "Другое"
        if flavor.quantity > 10:
            quantity_buttons.append([InlineKeyboardButton(text="🔢 Другое", callback_data="quantity_other")])

        # Добавляем кнопку "Назад"
        quantity_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_flavors")])

        markup = InlineKeyboardMarkup(inline_keyboard=quantity_buttons)

        await callback.message.edit_text(f"📦 Вкус: <b>{flavor.name}</b>\nВыберите количество:",
                                        reply_markup=markup, parse_mode="HTML")
        await state.set_state(RecordSaleState.enter_quantity)  # ✅ ОБЯЗАТЕЛЬНО ОБНОВЛЯЕМ СОСТОЯНИЕ




@dp.callback_query(F.data.startswith("quantity_"), RecordSaleState.enter_quantity)
async def select_quantity(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора количества с обновлением списка товаров в продаже."""
    # Извлекаем выбранное количество из callback data
    try:
        quantity = int(callback.data.split("_")[1])
    except ValueError:
        await callback.answer("Неверное значение количества!", show_alert=True)
        return

    # Получаем текущее состояние
    data = await state.get_data()
    # Если списка ещё нет – создаём его
    if "sales_list" not in data:
        data["sales_list"] = []

    # Получаем объект товара и вкуса из БД
    with Session() as session:
        product = session.query(Product).get(data["product_id"])
        flavor = session.query(Flavor).get(data["flavor_id"])

    # Добавляем новую запись о продаже в список
    data["sales_list"].append({
        "product_name": product.name,
        "flavor_name": flavor.name,
        "quantity": quantity
    })
    await state.update_data(sales_list=data["sales_list"])

    # Формируем текст, который будет показывать все товары, добавленные в продажу
    sale_items = "\n".join(
        f"• {item['product_name']} – {item['flavor_name']} – {item['quantity']} шт."
        for item in data["sales_list"]
    )

    # Готовим клавиатуру для дальнейших действий
    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Добавить ещё товар", callback_data="add_more")],
        [types.InlineKeyboardButton(text="✅ Завершить продажу", callback_data="finish_sale")]
    ])

    # Редактируем сообщение, чтобы показать весь список добавленных товаров
    await callback.message.edit_text(
        f"✅ Товары в продаже:\n{sale_items}\n\nВыберите действие:",
        reply_markup=markup
    )
    await state.set_state(RecordSaleState.confirm_more_items)









@dp.message(RecordSaleState.enter_quantity)
async def enter_sale_quantity(message: types.Message, state: FSMContext):
    try:
        quantity = int(message.text)
        await process_sale(message, quantity, state)
    except ValueError:
        await message.answer("❌ Введите целое число!")


async def process_sale(message, quantity, state):
    """Функция для обработки продажи (общая для callback и message)"""
    data = await state.get_data()

    with Session() as session:
        flavor = session.query(Flavor).get(data['flavor_id'])
        product = session.query(Product).get(data['product_id'])

        if flavor.quantity < quantity:
            await message.answer(f"❌ Недостаточно! Осталось: {flavor.quantity}")
            return

        flavor.quantity -= quantity

        sale = Sale(
            product=product,
            flavor=flavor,
            quantity=quantity,
            purchase_price=product.purchase_price,
            sale_price=product.sale_price
        )
        session.add(sale)

        profit = (sale.sale_price - sale.purchase_price) * quantity
        lena_income = profit * 0.3

        today = datetime.datetime.now().date()
        current_week_start = datetime.datetime.combine(
            today - datetime.timedelta(days=today.weekday()),
            datetime.time.min
        )
        income_record = session.query(WorkerIncome).filter(
            WorkerIncome.week_start == current_week_start
        ).first()

        if not income_record:
            income_record = WorkerIncome(
                week_start=current_week_start,
                income=0.0,
                is_current=True
            )
            session.add(income_record)

        income_record.income += lena_income

        session.query(WorkerIncome).filter(
            WorkerIncome.week_start != current_week_start
        ).update({WorkerIncome.is_current: False})

        session.commit()

        await message.answer(
            f"✅ <b>Продажа оформлена!</b>\n"
            f"📦 <b>Товар:</b> {product.name}\n"
            f"🍏 <b>Вкус:</b> {flavor.name}\n"
            f"📦 <b>Продано:</b> {quantity} шт.\n"
            f"💰 <b>Выручка:</b> {quantity * product.sale_price} ₽\n"
            f"👨💼 <b>Доход Лёни:</b> {lena_income:.2f} ₽",
            parse_mode="HTML"
        )
    await state.clear()



@dp.message(RecordSaleState.enter_quantity)
async def enter_sale_quantity(message: types.Message, state: FSMContext):
    try:
        quantity = int(message.text)
        await process_sale(message, quantity, state)
    except ValueError:
        await message.answer("❌ Введите целое число!")


async def process_sale(event, quantity, state):
    """Функция для обработки продажи (общая для callback и message)"""
    data = await state.get_data()

    with Session() as session:
        flavor = session.query(Flavor).get(data['flavor_id'])
        product = session.query(Product).get(data['product_id'])

        if flavor.quantity < quantity:
            await event.answer(f"❌ Недостаточно! Осталось: {flavor.quantity}")
            return

        flavor.quantity -= quantity

        sale = Sale(
            product=product,
            flavor=flavor,
            quantity=quantity,
            purchase_price=product.purchase_price,
            sale_price=product.sale_price
        )
        session.add(sale)

        profit = (sale.sale_price - sale.purchase_price) * quantity
        lena_income = profit * 0.3

        today = datetime.datetime.now().date()
        current_week_start = datetime.datetime.combine(
            today - datetime.timedelta(days=today.weekday()),
            datetime.time.min
        )
        income_record = session.query(WorkerIncome).filter(
            WorkerIncome.week_start == current_week_start
        ).first()

        if not income_record:
            income_record = WorkerIncome(
                week_start=current_week_start,
                income=0.0,
                is_current=True
            )
            session.add(income_record)

        income_record.income += lena_income

        session.query(WorkerIncome).filter(
            WorkerIncome.week_start != current_week_start
        ).update({WorkerIncome.is_current: False})

        session.commit()

        await event.answer(
            f"✅ Продажа оформлена!\n"
            f"📦 Товар: {product.name}\n"
            f"🍏 Вкус: {flavor.name}\n"
            f"📦 Продано: {quantity} шт.\n"
            f"💰 Выручка: {quantity * product.sale_price} ₽\n"
            f"👨💼 Доход Лёни: {lena_income:.2f} ₽"
        )
    await state.clear()


@dp.message(RecordSaleState.enter_quantity)
async def enter_sale_quantity(message: types.Message, state: FSMContext):
    try:
        quantity = int(message.text)
        data = await state.get_data()

        with Session() as session:
            flavor = session.query(Flavor).get(data['flavor_id'])
            product = session.query(Product).get(data['product_id'])

            if flavor.quantity < quantity:
                await message.answer(f"❌ Недостаточно! Осталось: {flavor.quantity}")
                return

            flavor.quantity -= quantity

            sale = Sale(
                product=product,
                flavor=flavor,
                quantity=quantity,
                purchase_price=product.purchase_price,
                sale_price=product.sale_price
            )
            session.add(sale)

            profit = (sale.sale_price - sale.purchase_price) * quantity
            lena_income = profit * 0.3

            today = datetime.datetime.now().date()
            current_week_start = datetime.datetime.combine(
                today - datetime.timedelta(days=today.weekday()),
                datetime.time.min
            )
            income_record = session.query(WorkerIncome).filter(
                WorkerIncome.week_start == current_week_start
            ).first()

            if not income_record:
                income_record = WorkerIncome(
                    week_start=current_week_start,
                    income=0.0,
                    is_current=True
                )
                session.add(income_record)

            income_record.income += lena_income

            session.query(WorkerIncome).filter(
                WorkerIncome.week_start != current_week_start
            ).update({WorkerIncome.is_current: False})

            session.commit()

            await message.answer(
                f"✅ Продажа оформлена!\n"
                f"📦 Товар: {product.name}\n"
                f"🍏 Вкус: {flavor.name}\n"
                f"📦 Продано: {quantity} шт.\n"
                f"💰 Выручка: {quantity * product.sale_price} ₽\n"
                f"👨💼 Доход Лёни: {lena_income:.2f} ₽"
            )
    except ValueError:
        await message.answer("❌ Введите целое число!")
    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        await message.answer("❌ Ошибка при обработке")
    finally:
        await state.clear()

# ======================= Аналитика ======================= #
@dp.message(F.text == "📊 Аналитика")
async def show_analytics(message: types.Message):
    markup = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📊 Текущая статистика"),
             types.KeyboardButton(text="📥 Скачать отчет за месяц")],
            [types.KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    await message.answer("📊 Выберите тип аналитики:", reply_markup=markup)


@dp.message(F.text == "📊 Текущая статистика")
async def show_current_stats(message: types.Message):
    try:
        with Session() as session:
            today = datetime.date.today()

            # Рассчет дат для текущей недели
            current_week_start = datetime.datetime.combine(
                today - datetime.timedelta(days=today.weekday()),
                datetime.time.min
            )
            current_week_end = current_week_start + datetime.timedelta(days=6)

            # Получаем данные за текущую неделю
            current_week_sales = session.query(Sale).filter(
                Sale.date >= current_week_start,
                Sale.date <= current_week_end
            ).all()

            # Получаем данные за сегодня
            daily_sales = session.query(Sale).filter(func.date(Sale.date) == today).all()

            # Получаем данные за текущий месяц
            monthly_sales = session.query(Sale).filter(
                func.extract('month', Sale.date) == today.month,
                func.extract('year', Sale.date) == today.year
            ).all()

            # Функция для расчета показателей
            def calculate_stats(sales):
                revenue = sum(s.sale_price * s.quantity for s in sales)
                profit = sum((s.sale_price - s.purchase_price) * s.quantity for s in sales)
                lena = profit * 0.3
                return revenue, profit, lena

            # Рассчитываем все показатели
            daily_revenue, daily_profit, daily_lena = calculate_stats(daily_sales)
            weekly_revenue, weekly_profit, weekly_lena = calculate_stats(current_week_sales)
            monthly_revenue, monthly_profit, monthly_lena = calculate_stats(monthly_sales)

            # Формируем ответ
            response = [
                "📊 <b>Аналитика продаж</b>",
                f"\n🕒 <u>Сегодня ({today.strftime('%d.%m.%Y')}):</u>",
                f"├ Выручка: {daily_revenue:.2f} ₽",
                f"├ Прибыль: {daily_profit:.2f} ₽",
                f"└ Доход Лёни: {daily_lena:.2f} ₽",

                f"\n📅 <u>Текущий месяц:</u>",
                f"├ Выручка: {monthly_revenue:.2f} ₽",
                f"├ Прибыль: {monthly_profit:.2f} ₽",
                f"└ Доход Лёни: {monthly_lena:.2f} ₽",

                f"\n📆 <u>Текущая неделя ({current_week_start.strftime('%d.%m')}-{current_week_end.strftime('%d.%m')}):</u>",
                f"├ Выручка: {weekly_revenue:.2f} ₽",
                f"├ Прибыль: {weekly_profit:.2f} ₽",
                f"└ Доход Лёни: {weekly_lena:.2f} ₽",
            ]

            # Добавляем данные за прошлую неделю
            last_week_start = current_week_start - datetime.timedelta(weeks=1)
            last_week_income = session.query(WorkerIncome).filter_by(week_start=last_week_start).first()
            if last_week_income:
                response.append(f"\n⏮ <u>Прошлая неделя:</u>\n└ Доход Лёни: {last_week_income.income:.2f} ₽")

            await message.answer("\n".join(response))

    except Exception as e:
        logger.error(f"Ошибка аналитики: {str(e)}")
        await message.answer("❌ Ошибка при расчете аналитики")




# ======================= ОБРАБОТКА ОШИБОК ======================= #
@dp.message()
async def handle_unknown(message: types.Message):
    await message.answer("❌ Используйте кнопки меню или /start")

@dp.callback_query()
async def handle_unknown_callback(callback: types.CallbackQuery):
    await callback.answer("⚠️ Действие недоступно", show_alert=True)




# ======================= ЗАПУСК ======================= #

if __name__ == "__main__":
    import asyncio

    logger.info("Бот запущен")
    asyncio.run(dp.start_polling(bot))