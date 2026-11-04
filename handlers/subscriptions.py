from __future__ import annotations

import logging
import re
from datetime import date, datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import Database, Subscription

logger = logging.getLogger(__name__)
router = Router()

DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
AMOUNT_RE = re.compile(r"^\d+([.,]\d{1,2})?$")


class AddSub(StatesGroup):
    title = State()
    charge_date = State()
    amount = State()
    currency = State()


def format_sub(sub: Subscription) -> str:
    return (
        f"#{sub.id} · <b>{sub.title}</b>\n"
        f"📅 {sub.next_charge_date.strftime('%d.%m.%Y')} · "
        f"{sub.amount:g} {sub.currency}"
    )


def action_keyboard(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Оплатил", callback_data=f"paid:{sub_id}"),
                InlineKeyboardButton(text="Отложить", callback_data=f"postpone:{sub_id}"),
                InlineKeyboardButton(text="Отменить", callback_data=f"cancel:{sub_id}"),
            ]
        ]
    )


def parse_date(text: str) -> date | None:
    match = DATE_RE.match(text.strip())
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_amount(text: str) -> float | None:
    raw = text.strip().replace(",", ".")
    if not AMOUNT_RE.match(raw):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, state: FSMContext) -> None:
    await state.clear()
    await db.ensure_user(message.from_user.id)
    await message.answer(
        "Привет! Я менеджер подписок.\n\n"
        "Команды:\n"
        "/add — добавить подписку\n"
        "/list — активные подписки\n"
        "/cancel &lt;id&gt; — отменить подписку\n\n"
        "Напомню о списании заранее."
    )


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext) -> None:
    await state.set_state(AddSub.title)
    await message.answer("Название подписки? (например: Netflix)")


@router.message(AddSub.title)
async def add_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if len(title) < 1 or len(title) > 80:
        await message.answer("Название должно быть от 1 до 80 символов. Попробуй ещё раз.")
        return
    await state.update_data(title=title)
    await state.set_state(AddSub.charge_date)
    await message.answer("Дата следующего списания? Формат: <b>ДД.ММ.ГГГГ</b>", parse_mode="HTML")


@router.message(AddSub.charge_date)
async def add_date(message: Message, state: FSMContext) -> None:
    parsed = parse_date(message.text or "")
    if parsed is None:
        await message.answer(
            "Не понял дату. Введи в формате <b>ДД.ММ.ГГГГ</b>, например 15.11.2026",
            parse_mode="HTML",
        )
        return
    await state.update_data(charge_date=parsed.isoformat())
    await state.set_state(AddSub.amount)
    await message.answer("Сумма списания? (например: 599 или 9.99)")


@router.message(AddSub.amount)
async def add_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message.text or "")
    if amount is None:
        await message.answer(
            "Сумма должна быть положительным числом, например <b>599</b> или <b>9.99</b>",
            parse_mode="HTML",
        )
        return
    await state.update_data(amount=amount)
    await state.set_state(AddSub.currency)
    await message.answer("Валюта? (RUB, USD, EUR…)")


@router.message(AddSub.currency)
async def add_currency(message: Message, state: FSMContext, db: Database) -> None:
    currency = (message.text or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        await message.answer("Валюта — 3 буквы, например RUB или USD.")
        return

    data = await state.get_data()
    await state.clear()

    user_id = await db.ensure_user(message.from_user.id)
    charge_date = date.fromisoformat(data["charge_date"])
    sub_id = await db.add_subscription(
        user_id=user_id,
        title=data["title"],
        next_charge_date=charge_date,
        amount=float(data["amount"]),
        currency=currency,
    )
    await message.answer(
        f"Сохранил подписку #{sub_id}: <b>{data['title']}</b>\n"
        f"Следующее списание: {charge_date.strftime('%d.%m.%Y')} · "
        f"{float(data['amount']):g} {currency}",
        parse_mode="HTML",
    )


@router.message(Command("list"))
async def cmd_list(message: Message, db: Database, state: FSMContext) -> None:
    await state.clear()
    user_id = await db.ensure_user(message.from_user.id)
    subs = await db.list_active(user_id)
    if not subs:
        await message.answer("Активных подписок нет. Добавь через /add")
        return

    await message.answer(f"Активных подписок: {len(subs)}")
    for sub in subs:
        await message.answer(
            format_sub(sub),
            parse_mode="HTML",
            reply_markup=action_keyboard(sub.id),
        )


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message,
    command: CommandObject,
    db: Database,
    state: FSMContext,
) -> None:
    await state.clear()
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /cancel &lt;id&gt;\nID смотри в /list", parse_mode="HTML")
        return

    sub_id = int(command.args.strip())
    user_id = await db.ensure_user(message.from_user.id)
    ok = await db.cancel_subscription(sub_id, user_id=user_id)
    if ok:
        await message.answer(f"Подписка #{sub_id} отменена.")
    else:
        await message.answer("Не нашёл активную подписку с таким id.")


@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(callback: CallbackQuery, db: Database) -> None:
    sub_id = int(callback.data.split(":", 1)[1])
    if not await _owns_sub(callback, db, sub_id):
        return
    new_date = await db.mark_paid(sub_id)
    if new_date is None:
        await callback.answer("Подписка недоступна", show_alert=True)
        return
    await callback.message.edit_text(
        f"✅ Оплачено. Следующее списание: {new_date.strftime('%d.%m.%Y')}",
        reply_markup=None,
    )
    await callback.answer("Дата сдвинута на +1 месяц")


@router.callback_query(F.data.startswith("postpone:"))
async def cb_postpone(callback: CallbackQuery, db: Database) -> None:
    sub_id = int(callback.data.split(":", 1)[1])
    if not await _owns_sub(callback, db, sub_id):
        return
    new_date = await db.postpone(sub_id, days=3)
    if new_date is None:
        await callback.answer("Подписка недоступна", show_alert=True)
        return
    await callback.message.edit_text(
        f"⏳ Отложено. Новая дата: {new_date.strftime('%d.%m.%Y')}",
        reply_markup=None,
    )
    await callback.answer("Сдвинул на +3 дня")


@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(callback: CallbackQuery, db: Database) -> None:
    sub_id = int(callback.data.split(":", 1)[1])
    if not await _owns_sub(callback, db, sub_id):
        return
    user_id = await db.ensure_user(callback.from_user.id)
    ok = await db.cancel_subscription(sub_id, user_id=user_id)
    if not ok:
        await callback.answer("Уже отменена или не найдена", show_alert=True)
        return
    await callback.message.edit_text(f"❌ Подписка #{sub_id} отменена.", reply_markup=None)
    await callback.answer("Отменено")


async def _owns_sub(callback: CallbackQuery, db: Database, sub_id: int) -> bool:
    user_id = await db.ensure_user(callback.from_user.id)
    sub = await db.get_subscription(sub_id)
    if sub is None or sub.user_id != user_id:
        await callback.answer("Это не твоя подписка", show_alert=True)
        return False
    return True
