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

class Sale(Base):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    flavor_id = Column(Integer, ForeignKey("flavors.id"))
    quantity = Column(Integer)
    purchase_price = Column(Float)
    sale_price = Column(Float)
    date = Column(DateTime, default=datetime.datetime.now)

    product = relationship("Product", back_populates="sales")
    flavor = relationship("Flavor", back_populates="sales")
class WorkerIncome(Base):
    __tablename__ = "worker_income"
    id = Column(Integer, primary_key=True)
    week_start = Column(DateTime)
    income = Column(Float)
    is_current = Column(Boolean, default=True)

Base.metadata.create_all(engine)

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
    confirm_delete = State()

class FileUploadState(StatesGroup):
    waiting_file = State()

class RecordSaleState(StatesGroup):
    select_product = State()
    select_flavor = State()
    enter_quantity = State()

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
@dp.message(AddProductState.enter_name)
async def enter_product_name(message: types.Message, state: FSMContext):
    if message.text.lower() in ["отмена", "/cancel"]:
        await state.clear()
        await cmd_start(message)
        return

    name = message.text.strip()
    with Session() as session:
        if session.query(Product).filter_by(name=name).first():
            await message.answer("❌ Товар с таким именем уже существует!")
            return
    await state.update_data(name=name)
    await message.answer("Введите цены через пробел (Закупочная Продажная):",
                        reply_markup=types.ReplyKeyboardRemove())
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
        return

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
            flavors_info = []
            for flavor in product.flavors:
                if flavor.quantity == 0:
                    emoji = "🔴"
                elif flavor.quantity == 1:
                    emoji = "🟡"
                else:
                    emoji = "🟢"

                flavors_info.append(f"├ {flavor.name} - {flavor.quantity} шт {emoji}")

            product_text = [
                f"📌 {product.name} З-{int(product.purchase_price)}₽ / П-{int(product.sale_price)}₽",
                "🍏 Вкусы:"
            ] + flavors_info

            await message.answer("\n".join(product_text))
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
        return

@dp.message(AddProductState.enter_flavors)
async def enter_product_flavors(message: types.Message, state: FSMContext):
    if message.text in ["📦 Управление товарами", "💵 Записать продажу", "📦 Показать товары", "📊 Аналитика", "🔙 Назад"]:
        await state.clear()
        await cmd_start(message)
        return

    try:
        data = await state.get_data()
        with Session() as session:
            product = Product(
                name=data['name'],
                purchase_price=data['purchase_price'],
                sale_price=data['sale_price']
            )
            session.add(product)
            session.commit()

            flavors = []
            errors = []
            for line in message.text.split('\n'):
                line = line.strip()
                if not line: continue
                try:
                    name, quantity = parse_flavor_line(line)
                    flavors.append(Flavor(name=name, quantity=quantity, product=product))
                except Exception as e:
                    errors.append(f"❌ {line}")

            if errors:
                await message.answer("⚠️ Ошибки в строках:\n" + "\n".join(errors[:5]) + ("\n..." if len(errors) > 5 else ""))

            if flavors:
                session.add_all(flavors)
                session.commit()
                await message.answer(f"✅ Товар <b>{product.name}</b> добавлен!\n🍏 Вкусов: {len(flavors)}")
                await cmd_start(message)  # Возврат в меню
            else:
                session.delete(product)
                session.commit()
                await message.answer("❌ Не добавлено ни одного вкуса!")
                await cmd_start(message)  # Возврат в меню
    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        await message.answer("❌ Ошибка при создании товара!")
    finally:
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

    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✏️ Изменить цены", callback_data="edit_prices"),
         types.InlineKeyboardButton(text="➕ Добавить вкусы", callback_data="add_flavors")],
        [types.InlineKeyboardButton(text="➖ Удалить вкусы", callback_data="remove_flavors"),
         types.InlineKeyboardButton(text="🗑️ Удалить товар", callback_data="delete_product")]
    ])

    await callback.message.edit_text("Выберите действие:", reply_markup=markup)
    await state.set_state(EditProductState.select_action)
# Устанавливаем состояние для следующего шага






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
            for line in message.text.split('\\n'):
                line = line.strip()
                if not line:
                    continue
                try:
                    name, quantity = parse_flavor_line(line)
                    flavors.append(Flavor(name=name, quantity=quantity, product=product))
                except Exception as e:
                    errors.append(f"❌ {line}")

            if errors:
                await message.answer("⚠️ Ошибки в строках:\\n" + "\\n".join(errors[:5]))

            if flavors:
                session.add_all(flavors)
                session.commit()
                await message.answer(f"✅ Добавлено {len(flavors)} новых вкусов!")
    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        await message.answer("❌ Ошибка при добавлении вкусов!")
    finally:
        await state.clear()

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

            markup = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=f"{p.name}", callback_data=f"product_{p.id}")]
                for p in products
            ])
            await message.answer("Выберите товар:", reply_markup=markup)
            await state.set_state(RecordSaleState.select_product)
    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        await message.answer("❌ Ошибка при загрузке товаров")

# Разместить здесь ↓
@dp.callback_query(F.data == "cancel_sale", RecordSaleState.select_product)
async def cancel_sale(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Запись продажи отменена.")
    await cmd_start(callback.message)


@dp.callback_query(F.data.startswith("product_"), RecordSaleState.select_product)
async def select_product(callback: types.CallbackQuery, state: FSMContext):
    # Проверяем, не нажал ли пользователь кнопку "Назад" или из главного меню
    if callback.data in ["📦 Управление товарами", "💵 Записать продажу", "📦 Показать товары", "📊 Аналитика", "🔙 Назад"]:
        await state.clear()  # Сбрасываем текущее состояние
        await cmd_start(callback.message)  # Возвращаем пользователя в главное меню
        return

    # Основная логика обработчика
    product_id = int(callback.data.split("_")[1])
    with Session() as session:
        product = session.query(Product).get(product_id)
        markup = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=f"{flavor.name} ({flavor.quantity})", callback_data=f"flavor_{flavor.id}")]
            for flavor in product.flavors
        ])
        await callback.message.answer("Выберите вкус:", reply_markup=markup)
        await state.update_data(product_id=product_id)
        await state.set_state(RecordSaleState.select_flavor)


@dp.callback_query(F.data.startswith("flavor_"), RecordSaleState.select_flavor)
async def select_flavor(callback: types.CallbackQuery, state: FSMContext):
    flavor_id = int(callback.data.split("_")[1])
    await state.update_data(flavor_id=flavor_id)
    await callback.message.answer("Введите количество:")
    await state.set_state(RecordSaleState.enter_quantity)

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

            current_week_start = datetime.datetime.combine(
                today - datetime.timedelta(days=today.weekday()),
                datetime.time.min
            )

            current_week_income = session.query(WorkerIncome).filter(
                WorkerIncome.week_start == current_week_start
            ).first()

            daily_sales = session.query(Sale).filter(func.date(Sale.date) == today).all()
            monthly_sales = session.query(Sale).filter(
                func.extract('month', Sale.date) == today.month,
                func.extract('year', Sale.date) == today.year
            ).all()

            def calculate_stats(sales):
                revenue = sum(s.sale_price * s.quantity for s in sales)
                profit = sum((s.sale_price - s.purchase_price) * s.quantity for s in sales)
                lena = profit * 0.3
                return revenue, profit, lena

            daily_revenue, daily_profit, daily_lena = calculate_stats(daily_sales)
            monthly_revenue, monthly_profit, monthly_lena = calculate_stats(monthly_sales)

            current_week_income_value = current_week_income.income if current_week_income else 0.0

            last_week_start = current_week_start - datetime.timedelta(weeks=1)
            last_week_income = session.query(WorkerIncome).filter_by(week_start=last_week_start).first()

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

                f"\n📆 <u>Текущая неделя ({current_week_start.strftime('%d.%m')}):</u>",
                f"└ Доход Лёни: {current_week_income_value:.2f} ₽",
            ]

            if last_week_income:
                response.append(f"\n⏮ <u>Прошлая неделя:</u>\n└ Доход Лёни: {last_week_income.income:.2f} ₽")

            await message.answer("\n".join(response))

    except Exception as e:
        logger.error(f"Ошибка аналитики: {str(e)}")
        await message.answer("❌ Ошибка при расчете аналитики")
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