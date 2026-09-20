import asyncio
import logging
import os

# aiogram requirements
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from database import (
    init_db,
    add_user,
    get_link_status,
    disable_link,
    enable_link,
    save_anonymous_message,
    get_anonymous_sender
)

# slowmode settings
import time

SLOWMODE_SECONDS = 9
last_message_time = {}

def get_slowmode_remaining(user_id: int):
    now = time.monotonic()
    last_time = last_message_time.get(user_id)

    if last_time is None:
        return 0

    remaining = SLOWMODE_SECONDS - (now - last_time)

    return max(0, remaining)

# preload TOKEN from .env
from dotenv import load_dotenv
load_dotenv()

API_TOKEN = os.getenv("TOKEN")
if not API_TOKEN:
    exit("Error: TOKEN not found in the .env file")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()


class AnonymousMessage(StatesGroup):
    waiting_for_message = State()

class AnonymousReply(StatesGroup):
    waiting_for_reply = State()

# inline-btns
stopsendbtn = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Больше писать этому пользователю",
                callback_data="stopsendmsgs"
            )
        ]
    ]
)

replybtn = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Ответить",
                callback_data="reply_anonymous"
            )
        ]
    ]
)

def link_control_keyboard(is_active: bool):
    if is_active:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отключить на 1 час",
                        callback_data="link_off_1h"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Отключить на 24 часа",
                        callback_data="link_off_24h"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Отключить до включения вручную",
                        callback_data="link_off_manual"
                    )
                ]
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Включить ссылку",
                    callback_data="link_on"
                )
            ]
        ]
    )


@dp.message(CommandStart())
async def startmsg(
    message: types.Message,
    command: CommandObject,
    state: FSMContext
):
    await add_user(message.from_user.id)
    me = await bot.get_me()

    if not command.args:
        is_active, _ = await get_link_status(message.from_user.id)

        link_message = await message.answer(
            f"👋 Добро пожаловать, {message.from_user.full_name}! \n"
            f"\n  Твоя персональная ссылка: t.me/{me.username}?start={message.from_user.id}",
            reply_markup=link_control_keyboard(is_active)
        )

        await bot.pin_chat_message(
            chat_id=message.chat.id,
            message_id=link_message.message_id,
            disable_notification=True
        )

    else:
        try:
            recipient_id = int(command.args)

        except ValueError:
            await message.answer("Некорректная ссылка.")
            return

        if recipient_id == message.from_user.id:
            await message.answer(
                "Нельзя отправлять анонимные сообщения самому себе."
            )
            return

        is_active, _ = await get_link_status(recipient_id)

        if is_active is None:
            await message.answer("Эта ссылка недействительна.")
            return

        if not is_active:
            await message.answer(
                "Пользователь сейчас не принимает сообщения."
            )
            return

        try:
            recipient_data = await bot.get_chat(recipient_id)

        except TelegramBadRequest:
            await message.answer(
                "Не удалось найти пользователя по этой ссылке."
            )
            return

        except TelegramForbiddenError:
            await message.answer(
                "Бот не может взаимодействовать с этим пользователем."
            )
            return

        await state.set_state(
            AnonymousMessage.waiting_for_message
        )

        await state.update_data(
            recipient_id=recipient_id
        )

        username = (
            f"(@{recipient_data.username})"
            if recipient_data.username
            else ""
        )

        await message.answer(
            f"Теперь ты можешь написать сообщение для "
            f"{recipient_data.first_name} {username}",
            reply_markup=stopsendbtn
        )

@dp.message(Command("reply"))
async def reply_command(message: types.Message, state: FSMContext):
    if not message.reply_to_message:
        await message.answer(
            "Используй /reply для ответа на анонимное сообщение."
        )
        return

    sender_id = await get_anonymous_sender(
        recipient_id=message.from_user.id,
        message_id=message.reply_to_message.message_id
    )

    if sender_id is None:
        await message.answer(
            "Не удалось найти отправителя этого сообщения."
        )
        return

    await state.update_data(
        reply_recipient_id=sender_id
    )

    await state.set_state(
        AnonymousReply.waiting_for_reply
    )

    await message.answer(
        "Напиши ответ. Для отмены используй /cancel."
    )

@dp.message(Command("cancel"))
async def cancel_command(message: types.Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Вы вышли из режима ответа."
    )

@dp.message(AnonymousReply.waiting_for_reply, F.text)
async def anonymous_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    reply_recipient_id = data.get("reply_recipient_id")

    if not reply_recipient_id:
        await message.answer(
            "Не удалось определить получателя ответа."
        )
        await state.clear()
        return

    sent_message = await bot.send_message(
        chat_id=reply_recipient_id,
        text=f"↩️ Ответ на твоё сообщение!\n\n— {message.text}"
    )

    await save_anonymous_message(
        recipient_id=reply_recipient_id,
        message_id=sent_message.message_id,
        sender_id=message.from_user.id
    )

    await state.clear()

    await message.answer(
        "Ответ успешно отправлен!"
    )

@dp.message(AnonymousMessage.waiting_for_message, F.text)
async def anonymous_message(
    message: types.Message,
    state: FSMContext
):
    data = await state.get_data()
    recipient_id = data.get("recipient_id")

    if not recipient_id:
        await message.answer(
            "Сообщение не было отправлено – не удалось определить получателя."
        )
        return

    remaining = get_slowmode_remaining(message.from_user.id)

    if remaining > 0:
        await message.answer(
            f"Подожди ещё {int(remaining) + 1} сек. перед следующим сообщением."
        )
        return

    last_message_time[message.from_user.id] = time.monotonic()

    if recipient_id:
        sent_message = await bot.send_message(
            chat_id=recipient_id,
            text=f"✨ Новое сообщение! \n\n— {message.text}",
            reply_markup=replybtn
        )

        await save_anonymous_message(
            recipient_id=recipient_id,
            message_id=sent_message.message_id,
            sender_id=message.from_user.id
        )

        await message.answer("Сообщение успешно отправлено!")

@dp.message(AnonymousMessage.waiting_for_message, F.photo)
async def anonymous_message_with_photo(
    message: types.Message,
    state: FSMContext
):
    data = await state.get_data()
    recipient_id = data.get("recipient_id")

    if not recipient_id:
        await message.answer(
            "Сообщение не было отправлено – не удалось определить получателя."
        )
        return

    remaining = get_slowmode_remaining(message.from_user.id)

    if remaining > 0:
        await message.answer(
            f"Подожди ещё {int(remaining) + 1} сек. перед следующим сообщением."
        )
        return

    last_message_time[message.from_user.id] = time.monotonic()

    photo = message.photo[-1]

    if recipient_id:
        sent_message = await bot.send_photo(
            chat_id=recipient_id,
            photo=photo.file_id,
            caption=f"✨ Новое сообщение! \n\n{message.caption or ''}",
            has_spoiler=True,
            reply_markup=replybtn
        )

        await save_anonymous_message(
            recipient_id=recipient_id,
            message_id=sent_message.message_id,
            sender_id=message.from_user.id
        )

        await message.answer("Сообщение успешно отправлено!")

@dp.message(AnonymousMessage.waiting_for_message)
async def unsupported_message(message: types.Message):
    await message.answer(
        "Можно отправлять только текст и фотографии."
    )

@dp.callback_query(F.data == "reply_anonymous")
async def reply_button(callback: CallbackQuery, state: FSMContext):
    sender_id = await get_anonymous_sender(
        recipient_id=callback.from_user.id,
        message_id=callback.message.message_id
    )

    if sender_id is None:
        await callback.answer(
            "Не удалось найти отправителя.",
            show_alert=True
        )
        return

    await state.update_data(
        reply_recipient_id=sender_id
    )

    await state.set_state(
        AnonymousReply.waiting_for_reply
    )

    await callback.answer()

    await callback.message.answer(
        "Напиши ответ. Для отмены используй /cancel."
    )

@dp.callback_query(F.data == "stopsendmsgs")
async def stop_sending(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()

    try:
        await callback.message.edit_reply_markup(
            reply_markup=None
        )
    except TelegramBadRequest:
        pass

    await callback.answer()

    await callback.message.answer(
        f"Отправка сообщений пользователю прекращена."
    )


@dp.callback_query(F.data == "link_off_1h")
async def link_off_1h(callback: CallbackQuery):
    await disable_link(
        callback.from_user.id,
        60 * 60
    )

    try:
        await callback.message.edit_reply_markup(
            reply_markup=link_control_keyboard(False)
        )
    except TelegramBadRequest:
        pass

    await callback.answer(
        "Ссылка отключена на 1 час."
    )


@dp.callback_query(F.data == "link_off_24h")
async def link_off_24h(callback: CallbackQuery):
    await disable_link(
        callback.from_user.id,
        24 * 60 * 60
    )

    try:
        await callback.message.edit_reply_markup(
            reply_markup=link_control_keyboard(False)
        )
    except TelegramBadRequest:
        pass

    await callback.answer(
        "Ссылка отключена на 24 часа."
    )


@dp.callback_query(F.data == "link_off_manual")
async def link_off_manual(callback: CallbackQuery):
    await disable_link(callback.from_user.id)

    try:
        await callback.message.edit_reply_markup(
            reply_markup=link_control_keyboard(False)
        )
    except TelegramBadRequest:
        pass

    await callback.answer(
        "Ссылка отключена."
    )


@dp.callback_query(F.data == "link_on")
async def link_on(callback: CallbackQuery):
    await enable_link(callback.from_user.id)

    try:
        await callback.message.edit_reply_markup(
            reply_markup=link_control_keyboard(True)
        )
    except TelegramBadRequest:
        pass

    await callback.answer(
        "Ссылка снова активна."
    )


@dp.message()
async def message_not_sent(message: types.Message):
    if message.pinned_message:
        return

    await message.answer(
        "Сообщение не было отправлено – не удалось определить получателя."
    )


async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())