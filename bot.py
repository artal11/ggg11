from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.dispatcher.filters import Command
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
import sqlite3
import logging

API_TOKEN = '7111326832:AAH2M8UHYK1X2Mh_V_vwnO59vAx23ird6-U'
ADMIN_ID = 7139336638  # Замените на свой Telegram ID

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# --- База данных ---
conn = sqlite3.connect('guarant_bot.db')
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    referrer_id INTEGER DEFAULT NULL
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT,
    amount INTEGER,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# --- Состояния FSM ---
class WithdrawState(StatesGroup):
    waiting_for_wallet = State()
    waiting_for_amount = State()

# --- Команды ---
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username

    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        ref_id = message.get_args()
        cursor.execute("INSERT INTO users (id, username, referrer_id) VALUES (?, ?, ?)", 
                       (user_id, username, ref_id if ref_id.isdigit() else None))
        conn.commit()

    kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton("👤 Профиль", callback_data="profile"),
        InlineKeyboardButton("💸 Баланс", callback_data="balance"),
        InlineKeyboardButton("👥 Рефералы", callback_data="referrals"),
        InlineKeyboardButton("📜 Сделки", callback_data="history"),
        InlineKeyboardButton("📤 Вывод", callback_data="withdraw")
    )
    if user_id == ADMIN_ID:
        kb.add(InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin"))
    await message.answer("Добро пожаловать в Гарант-Бота!", reply_markup=kb)

# --- Обработчики кнопок ---
@dp.callback_query_handler(lambda c: c.data == "profile")
async def profile_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()

    if result is None:
        await callback.message.edit_text("❌ Пользователь не найден в базе.")
        return

    balance = result[0] if result[0] is not None else 0

    await callback.message.edit_text(
        f"👤 Ваш профиль:\nID: {user_id}\nБаланс: {balance}₽"
    )


@dp.callback_query_handler(lambda c: c.data == "balance")
async def balance_handler(callback: types.CallbackQuery):
    await callback.message.edit_text("💸 Баланс пополнить можно через админа. В будущем будет интеграция.")

@dp.callback_query_handler(lambda c: c.data == "referrals")
async def referral_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    await callback.message.edit_text(f"👥 Вы пригласили: {count} пользователей
Реферальная ссылка:
t.me/artalGARANT_bot?start={user_id}")

@dp.callback_query_handler(lambda c: c.data == "history")
async def history_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT action, amount, timestamp FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,))
    rows = cursor.fetchall()
    if not rows:
        text = "История пуста."
    else:
        text = "\n".join([f"{a} на {amt}₽ — {t}" for a, amt, t in rows])
    await callback.message.edit_text(f"📜 История сделок:
{text}")

# --- Вывод средств ---
@dp.callback_query_handler(lambda c: c.data == "withdraw")
async def withdraw_start(callback: types.CallbackQuery):
    await WithdrawState.waiting_for_wallet.set()
    await callback.message.edit_text("📤 Введите ваш кошелёк для вывода:")

@dp.message_handler(state=WithdrawState.waiting_for_wallet)
async def withdraw_wallet(message: types.Message, state: FSMContext):
    await state.update_data(wallet=message.text)
    await WithdrawState.next()
    await message.answer("Введите сумму для вывода:")

@dp.message_handler(state=WithdrawState.waiting_for_amount)
async def withdraw_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        user_id = message.from_user.id
        cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        balance = cursor.fetchone()[0]
        if amount > balance:
            await message.answer("❌ Недостаточно средств.")
        else:
            cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, user_id))
            cursor.execute("INSERT INTO history (user_id, action, amount) VALUES (?, ?, ?)", (user_id, "Вывод", amount))
            conn.commit()
            await message.answer("✅ Запрос на вывод отправлен администратору.")
    except:
        await message.answer("❌ Введите корректную сумму.")
    await state.finish()

# --- Админка ---
@dp.callback_query_handler(lambda c: c.data == "admin")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("⚙️ Админ-панель:
Команда для начисления: /addbalance user_id сумма")

@dp.message_handler(Command("addbalance"))
async def admin_add_balance(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, uid, amt = message.text.split()
        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (int(amt), int(uid)))
        cursor.execute("INSERT INTO history (user_id, action, amount) VALUES (?, ?, ?)", (int(uid), "Пополнение", int(amt)))
        conn.commit()
        await message.answer(f"✅ Пользователю {uid} начислено {amt}₽.")
    except:
        await message.answer("❌ Используй: /addbalance user_id сумма")

# --- Запуск ---
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
