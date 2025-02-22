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

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    purchase_price = Column(Float)
    sale_price = Column(Float)
    flavors = relationship("Flavor", back_populates="product", cascade="all, delete-orphan")
    sales = relationship("Sale", back_populates="product")

class Flavor(Base):
    __tablename__ = "flavors"
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    quantity = Column(Integer)
    product_id = Column(Integer, ForeignKey("products.id"))
    product = relationship("Product", back_populates="flavors")
    sales = relationship("Sale", back_populates="flavor")



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
    enter_prices = State()
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

        # 🔹 **Шаг 2: Уменьшаем количество товаров и записываем продажу**
        for sale in data["sales_list"]:
            product = session.query(Product).filter_by(name=sale["product_name"]).first()
            flavor = session.query(Flavor).filter_by(name=sale["flavor_name"], product_id=product.id).first()

            session.refresh(flavor)  # Обновляем данные

            if flavor.quantity >= sale["quantity"]:
                new_quantity = flavor.quantity - sale["quantity"]

                # 🔴 Обновляем БД через запрос (исключаем множественное обновление)
                session.query(Flavor).filter_by(id=flavor.id).update({"quantity": new_quantity})

                # ✅ Записываем продажу
                sale_record = Sale(
                    product=product,
                    flavor=flavor,
                    customer=customer,
                    quantity=sale["quantity"],
                    purchase_price=product.purchase_price,
                    sale_price=product.sale_price
                )
                session.add(sale_record)

                revenue = sale["quantity"] * product.sale_price
                profit = (product.sale_price - product.purchase_price) * sale["quantity"]
                total_revenue += revenue
                total_profit += profit

                sale_texts.append(f"📦 <b>{sale['product_name']}</b> - {sale['flavor_name']} - {sale['quantity']} шт.")
            else:
                await message.answer(f"❌ Ошибка: не хватает {sale['flavor_name']}! Осталось {flavor.quantity}.")
                return

        # ✅ Сохраняем изменения в БД **одним коммитом**
        session.commit()

        # ✅ Формируем итоговое сообщение
        response_text = (
            f"✅ <b>Продажа завершена!</b>\n"
            f"📅 <b>Дата:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
            f"👤 <b>Покупатель:</b> {customer_name}\n\n"
            f"{chr(10).join(sale_texts)}\n\n"
            f"💰 <b>Общая выручка:</b> {total_revenue:.2f} ₽\n"
            f"📊 <b>Прибыль:</b> {total_profit:.2f} ₽"
        )

        await message.answer(response_text, parse_mode="HTML")

    await state.clear()  # ✅ Очищаем состояние, чтобы избежать ошибок "используйте кнопки меню"







@dp.callback_query(F.data == "add_more", RecordSaleState.confirm_more_items)
async def add_more_items(callback: types.CallbackQuery, state: FSMContext):
    """Начинаем выбор нового товара"""
    await start_sale_recording(callback.message, state)

@dp.callback_query(F.data == "finish_sale", RecordSaleState.confirm_more_items)
async def ask_for_customer_name(callback: types.CallbackQuery, state: FSMContext):
    """Спрашиваем, нужно ли вводить имя покупателя"""
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="enter_customer_name")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="skip_customer_name")]
    ])
    await callback.message.edit_text("Добавить имя покупателя?", reply_markup=markup)


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

    # Передаем сгенерированное имя в `save_sale`
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
            [types.KeyboardButton(text="📦 Показать товары"),
             types.KeyboardButton(text="📊 Аналитика")]
        ],
        resize_keyboard=True
    )
    await message.answer("🏪 <b>Система управления товарами</b>\nВыберите действие:", reply_markup=markup)

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
    await message.answer("Введите цены через пробел:\nФормат: <b>Закупочная Продажная</b>\nПример: 100 200")
    await state.set_state(AddProductState.enter_prices)

@dp.message(AddProductState.enter_prices)
async def enter_product_prices(message: types.Message, state: FSMContext):
    if message.text.lower() in ["отмена", "/cancel"]:
        await state.clear()
        await cmd_start(message)
        return

    try:
        purchase_price, sale_price = map(float, message.text.split())
        await state.update_data(purchase_price=purchase_price, sale_price=sale_price)
        await message.answer("Введите вкусы и количества (каждый с новой строки):\nПример:\nЯблоко 10\nБанан 5",
                            reply_markup=types.ReplyKeyboardRemove())
        await state.set_state(AddProductState.enter_flavors)
    except:
        await message.answer("❌ Неверный формат цен! Используйте: Закупочная Продажная")
        await state.set_state(AddProductState.enter_prices)

@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    markup = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📦 Управление товарами"),
             types.KeyboardButton(text="💵 Записать продажу")],
            [types.KeyboardButton(text="📦 Показать товары"),
             types.KeyboardButton(text="📊 Аналитика")]
        ],
        resize_keyboard=True
    )
    await message.answer("🏪 <b>Система управления товарами</b>\nВыберите действие:", reply_markup=markup)

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=types.ReplyKeyboardRemove())
    await cmd_start(message)




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


@dp.callback_query(F.data == "back_to_products", EditProductState.select_action)
async def back_to_products_list(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await start_editing_product(callback.message, state)

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
    await message.answer("Введите цены через пробел:\nФормат: <b>Закупочная Продажная</b>\nПример: 100 200")
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
        await message.answer("❌ Неверный формат цен! Повторите ввод в формате:\n<b>Закупочная Продажная</b>\nПример: 100 200")
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
                sale_price=data['sale_price']
            )
            session.add(product)
            session.commit()

        flavors = []
        errors = []

        for line in message.text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                name, quantity = parse_flavor_line(line)

                # Нормализация имени
                normalized_name = name.strip().lower()

                # Проверка на дубликат с учётом регистра и пробелов
                existing_flavor = session.query(Flavor).filter(
                    Flavor.product_id == product.id,
                    func.lower(func.trim(Flavor.name)) == normalized_name
                ).first()

                if existing_flavor:
                    errors.append(f"❌ Вкус '{name}' уже существует (учтены регистр и пробелы)!")
                    continue

                flavors.append(Flavor(name=name.strip(), quantity=quantity, product=product))
            except ValueError:
                errors.append(f"❌ Ошибка в строке: {line}")

        if errors:
            await message.answer("⚠️ Ошибки в строках:\n" + "\n".join(errors[:5]) +
                                 "\n\n🔄 Введите вкусы и количества снова (каждый с новой строки):")
            return

        if flavors:
            session.add_all(flavors)
            session.commit()
            await message.answer(f"✅ Товар <b>{product.name}</b> добавлен!\n🍏 Вкусов: {len(flavors)}")
            await state.clear()
            await cmd_start(message)
        else:
            await message.answer("❌ Не добавлено ни одного вкуса! Введите данные заново:")


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

    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✏️ Изменить цены", callback_data="edit_prices"),
         types.InlineKeyboardButton(text="➕ Добавить вкусы", callback_data="add_flavors")],
        [types.InlineKeyboardButton(text="➖ Удалить вкусы", callback_data="remove_flavors"),
         types.InlineKeyboardButton(text="✏️ Редактировать количество", callback_data="edit_flavor_quantity")],
        [types.InlineKeyboardButton(text="🗑️ Удалить товар", callback_data="delete_product")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_products")]
    ])

    await callback.message.edit_text("Выберите действие:", reply_markup=markup)
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
        purchase_price, sale_price = map(float, message.text.split())
        data = await state.get_data()

        with Session() as session:
            product = session.query(Product).get(data['product_id'])
            product.purchase_price = purchase_price
            product.sale_price = sale_price
            session.commit()

        await message.answer("✅ Цены успешно обновлены!")
        await state.clear()
    except:
        await message.answer(
            "❌ Неверный формат ввода! Повторите ввод в формате:\n<b>Закупочная Продажная</b>\nПример: 100 200")
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

            flavors = []
            errors = []

            for line in message.text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    name, quantity = parse_flavor_line(line)

                    # Нормализация имени
                    normalized_name = name.strip().lower()

                    # Проверка на дубликат
                    existing_flavor = session.query(Flavor).filter(
                        Flavor.product_id == product.id,
                        func.lower(func.trim(Flavor.name)) == normalized_name
                    ).first()

                    if existing_flavor:
                        errors.append(f"❌ Вкус '{name}' уже существует (учтены регистр и пробелы)!")
                        continue

                    flavors.append(Flavor(name=name.strip(), quantity=quantity, product=product))
                except ValueError:
                    errors.append(f"❌ Ошибка в строке: {line}")

            if errors:
                await message.answer("⚠️ Ошибки в строках:\n" + "\n".join(errors[:5]) +
                                     "\n\n🔄 Введите вкусы и количества снова (каждый с новой строки):")
                return

            if flavors:
                session.add_all(flavors)
                session.commit()
                await message.answer(f"✅ Добавлено {len(flavors)} новых вкусов в {product.name}!")
                await state.clear()
            else:
                await message.answer("❌ Не добавлено ни одного вкуса! Введите данные заново.")
                return

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
    """Выбор количества"""
    quantity = int(callback.data.split("_")[1])

    # Получаем текущие данные из состояния
    data = await state.get_data()

    # 🛑 Проверяем, что необходимые данные есть в состоянии
    if "product_id" not in data or "flavor_id" not in data:
        await callback.message.answer("❌ Ошибка: данные о товаре не найдены. Попробуйте начать заново.")
        await state.clear()
        return

    with Session() as session:
        product = session.query(Product).get(data["product_id"])
        flavor = session.query(Flavor).get(data["flavor_id"])

        if not product or not flavor:
            await callback.message.answer("❌ Ошибка: товар или вкус не найдены. Попробуйте снова.")
            await state.clear()
            return

        # 🛑 Проверяем, есть ли `sales_list`, если нет — создаем
        if "sales_list" not in data:
            data["sales_list"] = []

        # ✅ Добавляем текущий товар в список продаж
        data["sales_list"].append({
            "product_name": product.name,
            "flavor_name": flavor.name,
            "quantity": quantity
        })

        # Обновляем состояние
        await state.update_data(sales_list=data["sales_list"])

        # Спрашиваем, добавить ли еще товар
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить ещё товар", callback_data="add_more")],
            [InlineKeyboardButton(text="✅ Завершить продажу", callback_data="finish_sale")]
        ])

        await callback.message.edit_text(
            f"✅ Количество выбрано: {quantity} шт.\n"
            f"➕ Хотите добавить еще один товар?",
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