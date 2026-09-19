import asyncio
import logging
import os

# aiogram requirements
from aiogram import Bot, Dispatcher, types
from aiogram.filters import *
from aiogram.filters import CommandStart, CommandObject

from aiogram.fsm.context import FSMContext

# load TOKEN from .env
from dotenv import load_dotenv
load_dotenv()

API_TOKEN = os.getenv("TOKEN")
if not API_TOKEN:
    exit("Error: TOKEN not found in the .env file")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def startmsg(message: types.Message, command: CommandObject, state: FSMContext):
    me = await bot.get_me()
    if not command.args:
        await message.answer(
        f"Добро пожаловать, {message.from_user.full_name}! \n"
        f"\n Твоя персональная ссылка: t.me/{me.username}?start={message.from_user.id}"
    )

    else:
        recipient_data = await bot.get_chat(int(command.args))

        await state.update_data(
            recipient_id=int(command.args)
        )

        username = f"(@{recipient_data.username})" if recipient_data.username else ""

        await message.answer(
            f"Теперь ты можешь написать сообщение для {recipient_data.first_name} {username}"
        )

@dp.message()
async def anonymous_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    recipient_id = data.get("recipient_id")

    if recipient_id:
        await bot.send_message(
            chat_id=recipient_id,
            text=f"Новое сообщение: {message.text}"
        )

        await message.answer("Сообщение успешно отправлено!")

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())