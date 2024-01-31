import json

from telebot.async_telebot import AsyncTeleBot

from database.database import Database
from watcher.watcher import Watcher


if __name__ == '__main__':
    with open('token.json', 'r') as file:
        tokens = json.load(file)
        database = Database(tokens['database_url'])
        telebot = AsyncTeleBot(tokens['telegram_bot_token'])
        watcher = Watcher(_database=database, bot=telebot)
        watcher.run()
