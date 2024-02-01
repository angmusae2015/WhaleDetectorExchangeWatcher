import json
import asyncio

from telebot.async_telebot import AsyncTeleBot

from database.database import Database
from telegram.telegram import CommandListner


async def task():
    db = Database(tokens['database_url'])
    bot = AsyncTeleBot(tokens['telegram_bot_token'])
    cl = CommandListner(bot, db)
    await cl.setup()
    await cl.bot.polling(non_stop=True)


if __name__ == '__main__':
    with open('token.json', 'r') as file:
        tokens = json.load(file)
        database = Database(tokens['database_url'])
        telebot = AsyncTeleBot(tokens['telegram_bot_token'])
        asyncio.run(task())
