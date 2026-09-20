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
    enable_link
)

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


@dp.message(AnonymousMessage.waiting_for_message, F.text)
async def anonymous_message(
    message: types.Message,
    state: FSMContext
):
    data = await state.get_data()
    recipient_id = data.get("recipient_id")

    if recipient_id:
        await bot.send_message(
            chat_id=recipient_id,
            text=f"✨ Новое сообщение! \n\n— {message.text}"
        )

        await message.answer("Сообщение успешно отправлено!")

    else:
        await message.answer(
            "Не удалось определить получателя сообщения."
        )


@dp.message(AnonymousMessage.waiting_for_message, F.photo)
async def anonymous_message_with_photo(
    message: types.Message,
    state: FSMContext
):
    data = await state.get_data()
    recipient_id = data.get("recipient_id")

    photo = message.photo[-1]

    if recipient_id:
        await bot.send_photo(
            chat_id=recipient_id,
            photo=photo.file_id,
            caption=f"✨ Новое сообщение! \n\n{message.caption or ''}",
            has_spoiler=True
        )

        await message.answer("Сообщение успешно отправлено!")


@dp.message(AnonymousMessage.waiting_for_message)
async def unsupported_message(message: types.Message):
    await message.answer(
        "Можно отправлять только текст и фотографии."
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