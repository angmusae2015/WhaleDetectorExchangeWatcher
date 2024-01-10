from typing import TYPE_CHECKING, Dict, Final

import ccxt.pro as ccxt

from telebot import asyncio_filters
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_handler_backends import State, StatesGroup
from telebot.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import Database


class AlarmAddingProcessStates(StatesGroup):
    channel_select = State()
    exchange_select = State()


def item_select_keyboard_markup(items: dict, page=0):
    ITEMS_PER_PAGE: Final[int] = 5
    markup = InlineKeyboardMarkup()
    labels = list(items.keys())

    # 요소들을 키보드로 만들어 마크업에 추가하는 함수
    # map 함수와 함께 이용함
    def add_keyboard(_label: str):
        callback_data = items[_label]
        button = InlineKeyboardButton(text=_label, callback_data=callback_data)
        markup.add(button, row_width=1)

    # 요소의 개수가 페이지 당 최대 요소 수(기본: 5) 이하일 경우
    if len(labels) <= ITEMS_PER_PAGE:
        # 버튼으로 만들어 마크업에 추가
        for label in labels:
            add_keyboard(label)
        return markup
    # 페이지에서 표시할 요소의 인덱스 범위
    start_index = page * ITEMS_PER_PAGE
    end_index = min(start_index + ITEMS_PER_PAGE, len(labels))
    # 해당 범위의 요소들을 버튼으로 만들어 마크업에 추가
    for label in labels[start_index:end_index]:
        add_keyboard(label)
    # 이전 페이지: 현재 페이지가 0일 경우 0
    previous_page = max(page - 1, 0)
    # 다음 페이지: 현재 페이지가 가장 마지막 페이지일 경우 마지막 페이지
    next_page = min(page, len(labels) - 1)
    # 현재 페이지를 보여주는 버튼과 그 텍스트
    page_navigator_text = f'{page + 1} / {len(labels) % ITEMS_PER_PAGE}'
    page_navigator_button = InlineKeyboardButton(text=page_navigator_text, callback_data='none')
    # 이전/이후 페이지 버튼
    previous_page_button = InlineKeyboardButton(text='<', callback_data=f'page_to:{previous_page}')
    next_page_button = InlineKeyboardButton(text='>', callback_data=f'page_to:{next_page}')
    # 이전/이후 페이지 버튼과 현재 페이지 표시 버튼을 마크업에 추가
    markup.add(previous_page_button, page_navigator_button, next_page_button, row_width=3)
    return markup


class CommandListner:
    bot: AsyncTeleBot
    database: Database
    memory = {}

    def __init__(self, bot: AsyncTeleBot, database: Database):
        self.bot = bot
        self.database = database
        self.bot.add_custom_filter(asyncio_filters.StateFilter(self.bot))
        self.upbit = ccxt.upbit()
        self.binance = ccxt.binance()
        self.register_commands()
        self.register_alarm_adding_process()

    def register_commands(self):
        @self.bot.message_handler(commands=['addalarm'])
        async def add_alarm(message: Message):
            user_id = message.from_user.id
            chat_id = message.chat.id
            result_set = self.database.select('Channel')
            channel_items = {row['channel_name']: str(row['channel_id']) for row in result_set.values()}
            markup = item_select_keyboard_markup(channel_items)
            await self.bot.set_state(user_id, AlarmAddingProcessStates.channel_select, chat_id)
            await self.bot.send_message(chat_id, "알람을 추가할 채널을 선택해주세요.", reply_markup=markup)

    def register_alarm_adding_process(self):
        @self.bot.callback_query_handler(func=None, state=AlarmAddingProcessStates.channel_select)
        async def ask_exchange_for_alarm(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            selected_channel_id = int(call.data)
            self.memory[chat_id] = {'channel_id': selected_channel_id}

            exchange_items = {'업비트': 'upbit', '바이낸스': 'binance'}
            markup = item_select_keyboard_markup(exchange_items)
            await self.bot.set_state(user_id, AlarmAddingProcessStates.exchange_select, chat_id)
            await self.bot.send_message(chat_id, "종목을 선택할 거래소를 선택해주세요.", reply_markup=markup)

        @self.bot.callback_query_handler(func=None, state = AlarmAddingProcessStates.exchange_select)
        async def ask_base_symbol_for_alarm(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            selected_exchange = call.data
            self.memory[chat_id]['exchange'] = selected_exchange

