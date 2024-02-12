from typing import List, Optional

import ccxt.pro as ccxt
from telebot import asyncio_filters
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_helper import ApiTelegramException
from telebot.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import database.database
from database.database import Database
from database.definition import IntervalDict, Condition
from database.definition import WhaleCondition, TickCondition, RsiCondition, BollingerBandCondition
from telegram import callback
from telegram.state import *
from telegram.keyboard_layout import ItemSelectKeyboardLayout, KeypadKeyboardLayout, PeriodInputKeyboardLayout
from telegram.keyboard_layout import ToggleMenuKeyboardLayout


class CallbackTypeFilter(asyncio_filters.AdvancedCustomFilter):
    key = 'callback_type'

    async def check(self, message, text: str):
        if isinstance(message, CallbackQuery):
            return message.data.startswith(text)


# 선택이 끝난 후 비활성화된 마크업을 반환하는 함수
def disabled_markup(text: str):
    markup = InlineKeyboardMarkup()
    diabled_button = InlineKeyboardButton(text, callback_data=callback.ignore)
    markup.add(diabled_button)
    return markup


class CommandListner:
    bot: AsyncTeleBot
    database: Database

    currency_items_per_page = 9

    _condition_types = ['whale', 'tick', 'rsi', 'bollinger_band']
    _condition_type_names = ['고래', '거래 체결량', 'RSI', '볼린저 밴드', '설정 완료']
    _alarm_parameters = ['channel_id', 'exchange_id', 'base_symbol', 'quote_symbol', 'condition']

    _alarm_menus = ['알람 추가', '알람 수정']
    _channel_menus = ['채널 추가']

    # _channel_menus = ['채널 확인하기', '채널 알람 켜기/끄기', '채널 추가', '채널 삭제']

    def __init__(self, bot: AsyncTeleBot, _database: Database):
        self.bot = bot
        self.database = _database
        self.bot.add_custom_filter(asyncio_filters.StateFilter(self.bot))
        self.bot.add_custom_filter(CallbackTypeFilter())
        self.upbit = ccxt.upbit()
        self.binance = ccxt.binance()
        self.memory = {}

    async def setup(self):
        await self.upbit.load_markets()
        print("업비트 종목 불러오기 완료")
        await self.binance.load_markets()
        print("바이낸스 종목 불러오기 완료")

        # 커맨드 등록
        self.register_commands()
        # 무시/취소 콜백 등록
        self.register_ignore_callback()
        self.register_cancel_callback()
        # 레이아웃 관련 콜백 등록
        self.register_pagination_markup_callback()
        self.register_keypad_markup_callback()
        self.register_period_input_markup_callback()
        self.register_toggle_markup_callback()
        # 알람 추가 과정의 콜백 등록
        self.register_alarm_adding_process()
        # 알람 수정 과정의 콜백 등록
        self.register_alarm_editing_process()
        # 조건 설정 과정의 콜백 등록
        self.register_condition_setting_process()
        # 채널 등록 과정의 콜백 등록
        self.register_channel_adding_process()

    def get_exchange(self, exchange_id: int) -> ccxt.upbit | ccxt.binance:
        return [self.upbit, self.binance][exchange_id - 1]

    async def compare_state(self, user_id: int, chat_id: int, state: State) -> bool:
        current_state = await self.bot.get_state(user_id=user_id, chat_id=chat_id)
        return current_state == state.name

    # 해당 채팅의 state가 주어진 valid_state들 중에 포함되는지 여부
    def state_filter(self, valid_states: List[State]) -> callable:
        async def _filter(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            for state in valid_states:
                if await self.compare_state(user_id=user_id, chat_id=chat_id, state=state):
                    return True
            return False

        return _filter

    async def disable_markup(self, message: Message, text: str):
        chat_id = message.chat.id
        message_id = message.id
        markup = disabled_markup(text)
        await self.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=markup)

    # 명령어 등록
    def register_commands(self):
        @self.bot.message_handler(commands=['alarms'])
        async def show_alarm_menus(message: Message):
            user_id = message.from_user.id
            chat_id = message.chat.id

            keyboard_layout = ItemSelectKeyboardLayout(self._alarm_menus)
            markup = keyboard_layout.make_markup()
            await self.bot.set_state(user_id, AlarmMenuStates.menu, chat_id)
            await self.bot.send_message(chat_id, "메뉴를 선택해주세요.", reply_markup=markup)

        @self.bot.message_handler(commands=['channels'])
        async def show_channel_menus(message: Message):
            user_id = message.from_user.id
            chat_id = message.chat.id

            # 채팅 ID의 메모리 초기화
            def init_chat_memory():
                self.memory[chat_id] = {
                    'channel_id': None,
                    'channel_name': None
                }

            init_chat_memory()
            keyboard_layout = ItemSelectKeyboardLayout(self._channel_menus)
            markup = keyboard_layout.make_markup()
            await self.bot.set_state(user_id, ChannelMenuStates.menu, chat_id)
            await self.bot.send_message(chat_id, "메뉴를 선택해주세요.", reply_markup=markup)

    # 콜백 데이터가 'none' 일 경우 아무 행동도 하지 않음
    def register_ignore_callback(self):
        @self.bot.callback_query_handler(func=None, callback_type=callback.ignore)
        async def ignore(call: CallbackQuery):
            pass

    def register_cancel_callback(self):
        @self.bot.callback_query_handler(func=None, callback_type=callback.cancel)
        async def cancel(call: CallbackQuery):
            user_id = call.message.from_user.id
            chat_id = call.message.chat.id
            message_id = call.message.id
            text = "취소됨"
            markup = disabled_markup(text)
            await self.bot.set_state(user_id=user_id, state='', chat_id=chat_id)
            await self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=markup)

    # 선택 마크업에서 페이지 이동 동작에 관련된 쿼리 핸들러 등록
    def register_pagination_markup_callback(self):
        def move_currency_page(exchange_id: int, page: int) -> InlineKeyboardMarkup:
            # 거래소에서 종목 리스트를 불러옴
            exchange = self.get_exchange(exchange_id)
            currencies = exchange.currencies
            currency_symbols = [code for code in currencies]  # 종목 코드 리스트
            keyboard_layout = ItemSelectKeyboardLayout(labels=currency_symbols,
                                                       items_per_page=self.currency_items_per_page)
            markup = keyboard_layout.make_markup(page=page)
            return markup

        def move_market_page(exchange_id: int, currency: str, page: int):
            # 거래소에서 해당 종목의 거래 화폐 리스트를 불러옴
            exchange = self.get_exchange(exchange_id)
            # 화폐 코드 리스트
            markets = [market['quote'] for market in exchange.markets.values() if market['base'] == currency]
            market_symbols = [code for code in markets]
            keyboard_layout = ItemSelectKeyboardLayout(labels=market_symbols,
                                                       items_per_page=self.currency_items_per_page)
            markup = keyboard_layout.make_markup(page)
            return markup

        @self.bot.callback_query_handler(func=None, state=AlarmAddingProcessStates.currency,
                                         callback_type=callback.page_to)
        async def move_currency_select_page(call: CallbackQuery):
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            selected_exchange_id = chat_memory['exchange_id']
            # 콜백 데이터 파싱
            callback_type, page_to = call.data.split(':')
            # 문자열로 주어진 데이터를 정수형으로 변환
            page_to = int(page_to)
            markup = move_currency_page(exchange_id=selected_exchange_id, page=page_to)
            await self.bot.edit_message_reply_markup(chat_id, call.message.id, reply_markup=markup)

        @self.bot.callback_query_handler(func=None, state=AlarmAddingProcessStates.market,
                                         callback_type=callback.page_to)
        async def move_market_select_page(call: CallbackQuery):
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            selected_exchange_id = chat_memory['exchange_id']
            selected_currency = chat_memory['base_symbol']
            # 콜백 데이터 파싱
            callback_type, page_to = call.data.split(':')
            # 문자열로 주어진 데이터를 정수형으로 변환
            page_to = int(page_to)
            markup = move_market_page(exchange_id=selected_exchange_id, currency=selected_currency, page=page_to)
            await self.bot.edit_message_reply_markup(chat_id, call.message.id, reply_markup=markup)

    # 키패드 마크업 동작에 관련된 쿼리 핸들러 등록
    def register_keypad_markup_callback(self):
        # 콜백으로 전달받은 값으로 마크업 수정
        @self.bot.callback_query_handler(func=None, callback_type=callback.keypad)
        async def edit_keypad_markup(call: CallbackQuery):
            chat_id = call.message.chat.id
            message_id = call.message.id
            markup = KeypadKeyboardLayout.update_markup(call)
            await self.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=markup)

    # 기간 스피너 마크업 동작에 관련된 쿼리 핸들러 등록
    def register_period_input_markup_callback(self):
        # 콜백으로 전달받은 값으로 스피너 마크업 수정
        @self.bot.callback_query_handler(func=None, callback_type=callback.period)
        async def edit_period_input_markup(call: CallbackQuery):
            chat_id = call.message.chat.id
            message_id = call.message.id
            markup = PeriodInputKeyboardLayout.update_markup(call)
            await self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=markup)

    def register_toggle_markup_callback(self):
        @self.bot.callback_query_handler(func=None, callback_type=callback.toggle)
        async def edit_toggle_markup(call: CallbackQuery):
            chat_id = call.message.chat.id
            message_id = call.message.id
            markup = ToggleMenuKeyboardLayout.update_markup(call)
            await self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=markup)

    # 알람 추가 과정에 관련된 쿼리 핸들러 등록
    def register_alarm_adding_process(self):
        # 알람 메뉴 중 첫 번째 메뉴 '알람 추가' 선택 시 알람을 추가할 채널을 질문
        @self.bot.callback_query_handler(func=None, state=AlarmMenuStates.menu,
                                         callback_type="confirm:0")
        async def ask_channel_for_alarm(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            # 알람 메뉴 선택 키보드 비활성화
            await self.disable_markup(message=call.message, text="알람 추가")

            # 채팅 ID의 메모리 초기화
            def init_chat_memory():
                self.memory[chat_id] = {key: None for key in self._alarm_parameters}

            init_chat_memory()
            # 데이터베이스에서 채널 리스트를 불러옴
            result_set = self.database.select('Channel', chat_id=chat_id)
            # 채팅의 채널 정보를 메모리에 저장
            self.memory[chat_id]['channels'] = list(result_set.values())  # 채팅의 채널 목록을 메모리에 저장
            channel_names = result_set.column('channel_name')  # 채널 이름 리스트
            keyboard_layout = ItemSelectKeyboardLayout(channel_names)  # 키보드 레이아웃
            markup = keyboard_layout.make_markup(page=0)  # 키보드 레이아웃으로 만든 인라인 키보드
            await self.bot.set_state(user_id, AlarmAddingProcessStates.channel, chat_id)
            await self.bot.send_message(chat_id, "알람을 추가할 채널을 선택해주세요.", reply_markup=markup)

        # 채널 선택 시 거래소를 질문하는 과정
        @self.bot.callback_query_handler(func=None, state=AlarmAddingProcessStates.channel)
        async def ask_exchange_for_alarm(call: CallbackQuery):
            # 해당 채팅 ID의 메모리에 선택한 채널 ID 저장
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            # 콜백 데이터 파싱
            callback_type, index = call.data.split(':')
            # 문자열로 주어진 데이터를 정수형으로 변환
            index = int(index)
            channels: list = chat_memory['channels']  # 채팅의 채널 정보 리스트
            selected_channel = channels[index]  # 선택한 인덱스의 채널 정보
            # 채팅의 메모리에 선택한 채널의 ID를 저장
            chat_memory['channel_id'] = selected_channel['channel_id']
            # 채널 선택 마크업 비활성화
            message = call.message
            selected_channel_name = selected_channel['channel_name']
            await self.disable_markup(message=message, text=selected_channel_name)
            # 선택할 거래소를 질문
            exchange_names = ['업비트', '바이낸스']  # 거래소 이름 리스트
            keyboard_layout = ItemSelectKeyboardLayout(labels=exchange_names)
            markup = keyboard_layout.make_markup()
            await self.bot.set_state(user_id, AlarmAddingProcessStates.exchange, chat_id)
            await self.bot.send_message(chat_id, "종목을 선택할 거래소를 선택해주세요.", reply_markup=markup)

        # 거래소 선택 시 종목을 질문하는 과정
        @self.bot.callback_query_handler(func=None, state=AlarmAddingProcessStates.exchange)
        async def ask_currency_for_alarm(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            # 콜백 데이터 파싱
            callback_type, index = call.data.split(':')
            # 문자열로 주어진 데이터를 정수형으로 변환
            index = int(index)  # 선택한 버튼의 인덱스
            exchange_id = index + 1  # 선택한 거래소 ID
            # 채팅의 메모리에 선택한 거래소의 ID(선택한 인덱스 + 1)를 저장
            chat_memory['exchange_id'] = exchange_id
            # 거래소 선택 마크업 비활성화
            exchange_names = ['업비트', '바이낸스']  # 거래소 이름 리스트
            selected_exchange_name = exchange_names[index]
            message = call.message
            await self.disable_markup(message=message, text=selected_exchange_name)
            # 선택한 거래소의 종목을 불러와 질문
            exchange = self.get_exchange(exchange_id)
            currencies = exchange.currencies
            currency_codes = [code for code in currencies]  # 종목 코드 리스트
            keyboard_layout = ItemSelectKeyboardLayout(labels=currency_codes,
                                                       items_per_page=self.currency_items_per_page)
            markup = keyboard_layout.make_markup()
            await self.bot.set_state(user_id, AlarmAddingProcessStates.currency, chat_id)
            await self.bot.send_message(chat_id, "종목을 선택해주세요.", reply_markup=markup)

        @self.bot.callback_query_handler(func=None, state=AlarmAddingProcessStates.currency)
        async def ask_market_for_alarm(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            # 콜백 데이터 파싱
            selected_currency_code = ItemSelectKeyboardLayout.parse_confirm_callback(call)
            # 채팅의 메모리에 선택한 종목 코드를 저장
            chat_memory['base_symbol'] = selected_currency_code
            # 종목 선택 마크업 비활성화
            message = call.message
            await self.disable_markup(message=message, text=selected_currency_code)
            # 선택한 거래소를 메모리에서 불러옴
            selected_exchange_id = self.memory[chat_id]['exchange_id']
            exchange = self.get_exchange(selected_exchange_id)
            # 선택한 종목의 거래 화폐 리스트를 불러와 질문
            markets = [market['quote'] for market in exchange.markets.values()
                       if market['base'] == selected_currency_code]
            market_codes = [code for code in markets]  # 거래 화폐 코드 리스트
            keyboard_layout = ItemSelectKeyboardLayout(labels=market_codes,
                                                       items_per_page=self.currency_items_per_page)
            markup = keyboard_layout.make_markup()
            await self.bot.set_state(user_id, AlarmAddingProcessStates.market, chat_id)
            await self.bot.send_message(chat_id, "거래 화폐를 선택해주세요.", reply_markup=markup)

        def is_alarm_exists(channel_id: int, base_symbol: str, quote_symbol: str):
            alarms = self.database.select("alarm",
                                          channel_id=channel_id,
                                          base_symbol=base_symbol,
                                          quote_symbol=quote_symbol)
            return len(alarms.list) != 0

        @self.bot.callback_query_handler(func=None, state=AlarmAddingProcessStates.market)
        async def ask_condition_to_set(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            # 콜백 데이터 파싱
            selected_market_code = ItemSelectKeyboardLayout.parse_confirm_callback(call)
            chat_memory['quote_symbol'] = selected_market_code
            # 거래 화폐 선택 마크업 비활성화
            message = call.message
            await self.disable_markup(message=message, text=selected_market_code)
            # 등록 가능한 알람인지 확인: 같은 이름의 종목에 대한 알람을 한 채널에 두 개 이상 설정할 수 없음
            channel_id = chat_memory['channel_id']
            base_symbol = chat_memory['base_symbol']
            quote_symbol = chat_memory['quote_symbol']
            if is_alarm_exists(channel_id, base_symbol, quote_symbol):
                # text = "한 채널에 같은 이름의 종목에 대한 알람을 여러 개 설정할 수 없습니다. 이미 존재하는 알람의 조건을 수정하거나"
                # await self.bot.send_message(chat_id, )
                pass
            # 조건을 저장할 딕셔너리 공간 확보
            chat_memory['condition'] = {condition_type: None for condition_type in self._condition_types}
            # 채팅 ID의 메모리에 현재 state 저장
            chat_memory['state'] = AlarmAddingProcessStates.condition
            # 설정할 조건을 질문 ('설정 완료'는 포함하지 않음)
            keyboard_layout = ItemSelectKeyboardLayout(labels=self._condition_type_names[:-1])
            markup = keyboard_layout.make_markup()
            await self.bot.set_state(user_id, AlarmAddingProcessStates.condition, chat_id)
            await self.bot.send_message(chat_id, "설정할 조건을 선택해주세요.", reply_markup=markup)

        @self.bot.callback_query_handler(func=None, state=AlarmAddingProcessStates.condition,
                                         callback_type='confirm:4')
        async def set_alarm(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            message_id = call.message.id
            chat_memory = self.memory[chat_id]

            # 데이터베이스에 조건 저장
            def add_condition_to_database() -> int:
                condition_memory = chat_memory['condition']
                tick_condition = condition_memory['tick']
                whale_condition = condition_memory['whale']
                rsi_condition = condition_memory['rsi']
                bollinger_band_condition = condition_memory['bollinger_band']
                condition_id = self.database.insert(table_name='condition', tick=tick_condition,
                                                    whale=whale_condition, rsi=rsi_condition,
                                                    bollinger_band=bollinger_band_condition)
                return condition_id

            # 데이터베이스에 알람 저장
            def add_alarm_to_database() -> int:
                condition_id = add_condition_to_database()
                channel_id = chat_memory['channel_id']
                exchange_id = chat_memory['exchange_id']
                base_symbol = chat_memory['base_symbol']
                quote_symbol = chat_memory['quote_symbol']
                alarm_id = self.database.insert(table_name='alarm', channel_id=channel_id, exchange_id=exchange_id,
                                                base_symbol=base_symbol, quote_symbol=quote_symbol,
                                                condition_id=condition_id, is_enabled=True)
                return alarm_id

            add_alarm_to_database()
            text = "알람이 저장되었습니다."
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=None)
            # state 초기화
            await self.bot.set_state(user_id=user_id, state='', chat_id=chat_id)
            # 메모리 초기화
            self.memory.pop(chat_id)

    def register_alarm_editing_process(self):
        # 알람 메뉴 중 두 번째 메뉴 '알람 수정' 선택 시 알람을 추가할 채널을 질문
        @self.bot.callback_query_handler(func=None, state=AlarmMenuStates.menu,
                                         callback_type="confirm:1")
        async def ask_channel_for_alarm(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            # 알람 메뉴 선택 키보드 비활성화
            await self.disable_markup(message=call.message, text="알람 수정")

            # 채팅 ID의 메모리 초기화
            def init_chat_memory():
                self.memory[chat_id] = {
                    'channels': [],  # 채팅의 채널 리스트
                    'channel_id': None,  # 선택한 채널 ID
                    'alarms': [],  # 채널의 알람 리스트
                    'alarm_id': None,  # 선택한 알람 ID
                    'exchange_id': None,
                    'base_symbol': None,
                    'quote_symbol': None,
                    'condition': None  # 수정한 알람 조건
                }

            init_chat_memory()
            # 데이터베이스에서 채널 리스트를 불러옴
            result_set = self.database.select('channel', chat_id=chat_id)
            # 채팅의 채널 리스트을 메모리에 저장
            self.memory[chat_id]['channels'] = result_set.list
            # 선택할 채널을 질문
            channel_names = result_set.column('channel_name')  # 채널 이름 리스트
            keyboard_layout = ItemSelectKeyboardLayout(channel_names)  # 키보드 레이아웃
            markup = keyboard_layout.make_markup()  # 키보드 레이아웃으로 만든 인라인 키보드
            await self.bot.set_state(user_id, AlarmEditingProcessStates.channel, chat_id)
            await self.bot.send_message(chat_id, "알람을 수정할 채널을 선택해주세요.", reply_markup=markup)

        # 콜백으로 전송된 데이터로 선택한 채널 ID 저장
        async def set_channel_id(call: CallbackQuery):
            # 해당 채팅 ID의 메모리에 선택한 채널 ID 저장
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            # 콜백 데이터 파싱
            callback_type, index = call.data.split(':')
            # 문자열로 주어진 데이터를 정수형으로 변환
            index = int(index)
            channels: List[database.definition.Channel] = chat_memory['channels']  # 채팅의 채널 정보 리스트
            selected_channel = channels[index]  # 선택한 인덱스의 채널 정보
            # 채팅의 메모리에 선택한 채널의 ID를 저장
            chat_memory['channel_id'] = selected_channel['channel_id']
            # 채널 선택 키보드 비활성화
            selected_channel_name = selected_channel['channel_name']
            await self.disable_markup(message=call.message, text=selected_channel_name)

        @self.bot.callback_query_handler(func=None, state=AlarmEditingProcessStates.channel)
        async def ask_alarm_to_edit(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]
            # 선택한 채널 ID 저장
            await set_channel_id(call)
            # 데이터베이스에서 알람 리스트를 불러옴
            channel_id = chat_memory['channel_id']
            result_set = self.database.select('alarm', channel_id=channel_id)
            # 채널의 알람 리스트를 메모리에 저장
            chat_memory['alarms'] = result_set.list
            # 선택할 알람을 질문
            alarm_labels = []  # 알람 레이블 리스트
            for alarm_dict in result_set.list:
                base_symbol = alarm_dict['base_symbol']
                quote_symbol = alarm_dict['quote_symbol']
                alarm_labels.append(f"{base_symbol}/{quote_symbol}")
            keyboard_layout = ItemSelectKeyboardLayout(alarm_labels)  # 키보드 레이아웃
            markup = keyboard_layout.make_markup()  # 키보드 레이아웃으로 만든 인라인 키보드
            await self.bot.set_state(user_id, AlarmEditingProcessStates.alarm)
            await self.bot.send_message(chat_id, "수정할 알람을 선택해주세요.", reply_markup=markup)

        async def set_alarm_id(call: CallbackQuery):
            # 해당 채팅 ID의 메모리에 선택한 채널 ID 저장
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            # 콜백 데이터 파싱
            callback_type, index = call.data.split(':')
            # 문자열로 주어진 데이터를 정수형으로 변환
            index = int(index)
            alarms: List[database.definition.AlarmDict] = chat_memory['alarms']  # 채널의 알람 정보 리스트
            selected_alarm = alarms[index]
            # 채팅의 메모리에 선택한 알람의 ID를 저장
            exchange_id = selected_alarm['exchange_id']
            base_symbol = selected_alarm['base_symbol']
            quote_symbol = selected_alarm['quote_symbol']
            chat_memory['alarm_id'] = selected_alarm['alarm_id']
            chat_memory['exchange_id'] = exchange_id
            chat_memory['base_symbol'] = base_symbol
            chat_memory['quote_symbol'] = quote_symbol
            # 알람 선택 키보드 비활성화
            selected_alarm_label = f"{base_symbol}/{quote_symbol}"
            await self.disable_markup(message=call.message, text=selected_alarm_label)

        @self.bot.callback_query_handler(func=None, state=AlarmEditingProcessStates.alarm)
        async def ask_condition_to_edit(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            # 선택한 알람 ID 저장
            await set_alarm_id(call)
            # 선택한 알람의 조건을 불러옴
            condition_id = chat_memory['alarm_id']
            result_set = self.database.select('condition', condition_id=condition_id)
            condition: Condition = result_set[condition_id]
            chat_memory['condition'] = condition.copy()
            # 채팅 ID의 메모리에 현재 state 저장
            chat_memory['state'] = AlarmEditingProcessStates.condition
            # 설정할 조건을 질문 ('설정 완료'는 포함하지 않음)
            keyboard_layout = ItemSelectKeyboardLayout(labels=self._condition_type_names[:-1])
            markup = keyboard_layout.make_markup()
            await self.bot.set_state(user_id, AlarmEditingProcessStates.condition, chat_id)
            await self.bot.send_message(chat_id, "설정할 조건을 선택해주세요.", reply_markup=markup)

        @self.bot.callback_query_handler(func=None, state=AlarmEditingProcessStates.condition,
                                         callback_type='confirm:4')
        async def edit_alarm(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            message_id = call.message.id
            chat_memory = self.memory[chat_id]

            # 데이터베이스에 조건 업데이트
            def update_condition_to_database():
                condition_memory = chat_memory['condition']
                condition_id = condition_memory['condition_id']
                tick_condition = condition_memory['tick']
                whale_condition = condition_memory['whale']
                rsi_condition = condition_memory['rsi']
                bollinger_band_condition = condition_memory['bollinger_band']
                self.database.update(table_name='condition', primary_key=condition_id,
                                     tick=tick_condition,
                                     whale=whale_condition, rsi=rsi_condition,
                                     bollinger_band=bollinger_band_condition)

            update_condition_to_database()
            text = "알람이 수정되었습니다."
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=None)
            # state 초기화
            await self.bot.set_state(user_id=user_id, state='', chat_id=chat_id)
            # 메모리 초기화
            self.memory.pop(chat_id)

    # 알람 조건 설정 과정에 관련된 쿼리 핸들러 등록
    def register_condition_setting_process(self):
        tick_state_group = TickConditionSettingProcessStates()
        whale_state_group = WhaleConditionSettingProcessStates()
        rsi_state_group = RsiConditionSettingProcessStates()
        bollinger_band_state_group = BollingerBandConditionSettingProcessStates()

        # 현재 state가 조건 설정 state인지 확인하는 함수
        condition_state_filter = self.state_filter(
            [AlarmAddingProcessStates.condition,
             AlarmEditingProcessStates.condition]
        )

        # 채팅의 state가 각 state group에 속하는 state인지 확인하는 함수
        # 쿼리 핸들러의 필터 함수로 사용
        tick_state_filter = self.state_filter(tick_state_group.state_list)
        whale_state_filter = self.state_filter(whale_state_group.state_list)
        rsi_state_filter = self.state_filter(rsi_state_group.state_list)
        bollinger_band_state_filter = self.state_filter(bollinger_band_state_group.state_list)

        @self.bot.callback_query_handler(func=condition_state_filter)
        async def ask_condition(call: CallbackQuery):
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            condition_memory = chat_memory['condition']  # 채팅의 알람 조건 메모리 공간
            # 콜백 데이터 파싱
            callback_type, index = call.data.split(':')
            selected_condition_index = int(index)  # 선택한 조건의 인덱스
            condition_type = self._condition_types[selected_condition_index]  # 선택한 조건
            # 선택한 조건이 고래('whale')일 경우
            if condition_type == self._condition_types[0]:
                # 알람 조건 메모리에서 저장된 고래 조건을 불러옴
                whale_condition: Optional[WhaleCondition] = condition_memory[condition_type]
                # 설정한 고래 조건이 없을 경우 초기화된 설정값 저장
                if whale_condition is None:
                    condition_memory[condition_type] = WhaleCondition(quantity=0)
                await ask_whale_condition(call)
            # 선택한 조건이 거래 체결량('tick')일 경우
            elif condition_type == self._condition_types[1]:
                tick_condition: Optional[TickCondition] = condition_memory[condition_type]
                # 설정한 거래 체결량 조건이 없을 경우 초기화된 설정값 저장
                if tick_condition is None:
                    condition_memory[condition_type] = TickCondition(quantity=0)
                await ask_tick_condition(call)
            # 선택한 조건이 RSI('rsi')일 경우
            elif condition_type == self._condition_types[2]:
                rsi_condition: Optional[RsiCondition] = condition_memory[condition_type]
                # 설정한 RSI 조건이 없을 경우 초기화된 설정값 저장
                if rsi_condition is None:
                    interval = IntervalDict(length=1, timeframe='m')
                    condition_memory[condition_type] = RsiCondition(length=14,
                                                                    upper_bound=70.0, lower_bound=30.0,
                                                                    interval=interval)
                await ask_rsi_condition_period(call)
            # 선택한 조건이 볼린저 밴드('bollinger_band')일 경우
            elif condition_type == self._condition_types[3]:
                bollinger_band_condition: Optional[BollingerBandCondition] = condition_memory[condition_type]
                # 설정한 볼린저 밴드 조건이 없을 경우 초기화된 설정값 저장
                if bollinger_band_condition is None:
                    interval = IntervalDict(length=1, timeframe='m')
                    condition_memory[condition_type] = BollingerBandCondition(length=20, coefficient=2,
                                                                              on_over_upper_band=True,
                                                                              on_under_lower_band=True,
                                                                              interval=interval)
                await ask_bollinger_band_condition_period(call)

        async def ask_whale_condition(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            message_id = call.message.id
            # 조건 입력 키패드 마크업으로 메시지 수정
            text = "고래 설정\n알림을 원하는 값을 입력해주세요."
            symbol = self.memory[chat_id]['quote_symbol']
            whale_condition_memory = self.memory[chat_id]['condition']['whale']
            quantity: float = whale_condition_memory['quantity']
            # 키패드 마크업
            displayed_number = str(quantity)
            keyboard_layout = KeypadKeyboardLayout(displayed_number=displayed_number, symbol=symbol)
            markup = keyboard_layout.make_markup()
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            # state 설정
            state = whale_state_group.quantity
            await self.bot.set_state(user_id=user_id, state=state, chat_id=chat_id)

        # 고래 조건 선택 시 조건을 입력할 수 있는 키패드 마크업으로 메시지를 수정
        @self.bot.callback_query_handler(func=None, state=whale_state_group.quantity, callback_type='confirm')
        async def set_whale_condition(call: CallbackQuery):
            chat_id = call.message.chat.id
            condition_type = self._condition_types[0]  # 'whale'
            # 콜백 데이터 파싱
            quantity = KeypadKeyboardLayout.parse_confirm_callback(call)
            # 고래 조건 저장
            whale_condition_memory = self.memory[chat_id]['condition'][condition_type]
            whale_condition_memory['quantity'] = quantity
            # 알람 조건 선택 메뉴로 돌아감
            await back_to_condition_select(call)

        # 고래 조건을 입력하면 메모리에 저장 후 조건 선택 메뉴로 돌아감
        @self.bot.callback_query_handler(func=whale_state_filter, callback_type=callback.delete_condition)
        async def delete_whale_condition(call: CallbackQuery):
            chat_id = call.message.chat.id
            self.memory[chat_id]['condition']['whale'] = None
            await back_to_condition_select(call)

        # 고래 조건 삭제 시 메모리에서 해당 조건을 None으로 초기화
        # 거래 체결량 조건 선택 시 조건을 입력할 수 있는 키패드 마크업으로 메시지를 수정
        async def ask_tick_condition(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            message_id = call.message.id
            # 조건 입력 키패드 마크업으로 메시지 수정
            text = "거래 체결량 설정\n알림을 원하는 값을 입력해주세요."
            symbol = self.memory[chat_id]['base_symbol']
            tick_condition_memory: TickCondition = self.memory[chat_id]['condition']['tick']
            quantity: float = tick_condition_memory['quantity']
            # 키패드 마크업
            displayed_number = str(quantity)
            keyboard_layout = KeypadKeyboardLayout(displayed_number=displayed_number, symbol=symbol)
            markup = keyboard_layout.make_markup()
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            # state 설정
            state = tick_state_group.quantity
            await self.bot.set_state(user_id=user_id, state=state, chat_id=chat_id)

        # 거래 체결량 조건을 입력하면 메모리에 저장 후 조건 선택 메뉴로 돌아감
        @self.bot.callback_query_handler(func=None, state=tick_state_group.quantity, callback_type='confirm')
        async def set_tick_condition(call: CallbackQuery):
            chat_id = call.message.chat.id
            condition_type = self._condition_types[1]  # 'tick'
            # 콜백 데이터 파싱
            quantity = KeypadKeyboardLayout.parse_confirm_callback(call)
            # 거래 체결량 조건 저장
            tick_condition_memory = self.memory[chat_id]['condition'][condition_type]
            tick_condition_memory['quantity'] = quantity
            # 알람 조건 선택 메뉴로 돌아감
            await back_to_condition_select(call)

        # 거래 체결량 조건 삭제 시 메모리에서 해당 조건을 None으로 초기화
        @self.bot.callback_query_handler(func=tick_state_filter, callback_type=callback.delete_condition)
        async def delete_tick_condition(call: CallbackQuery):
            chat_id = call.message.chat.id
            self.memory[chat_id]['condition']['tick'] = None
            await back_to_condition_select(call)

        async def ask_rsi_condition_period(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            message_id = call.message.id
            # RSI 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['rsi']
            # 조건 입력 키패드 마크업으로 메시지 수정
            text = "RSI 설정\n기간을 입력해주세요."
            exchange_id = self.memory[chat_id]['exchange_id']
            length: int = condition_memory['length']
            interval_dict: IntervalDict = condition_memory['interval']
            interval = f"{interval_dict['length']}{interval_dict['timeframe']}"
            # 키보드 마크업
            keyboard_layout = PeriodInputKeyboardLayout(length=length, exchange_id=exchange_id, interval=interval)
            markup = keyboard_layout.make_markup()
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            # state 설정
            state = rsi_state_group.interval
            await self.bot.set_state(user_id=user_id, state=state, chat_id=chat_id)

        @self.bot.callback_query_handler(func=None, state=rsi_state_group.interval, callback_type='confirm')
        async def set_rsi_condition_period(call: CallbackQuery):
            chat_id = call.message.chat.id
            # RSI 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['rsi']
            # 콜백 데이터 파싱
            length, interval = PeriodInputKeyboardLayout.parse_confirm_callback(call)
            # 입력한 기간 저장
            condition_memory['length'] = length
            condition_memory['interval'] = interval.dict
            await ask_rsi_condition_upper_bound(call)

        async def ask_rsi_condition_upper_bound(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            message_id = call.message.id
            # RSI 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['rsi']
            # 조건 입력 키패드 마크업으로 메시지 수정
            text = "RSI 설정\n상향 돌파 기준값을 입력해주세요.\n*상향 돌파 기준을 입력하지 않으려면 100을 입력"
            upper_bound: float = condition_memory['upper_bound']
            # 키패드 마크업
            displayed_number: str = str(upper_bound)
            keyboard_layout = KeypadKeyboardLayout(displayed_number=displayed_number, symbol="이상 돌파 시 알림",
                                                   limit=100)
            markup = keyboard_layout.make_markup()
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            # state 설정
            state = rsi_state_group.upper_bound
            await self.bot.set_state(user_id=user_id, state=state, chat_id=chat_id)

        @self.bot.callback_query_handler(func=None, state=rsi_state_group.upper_bound, callback_type='confirm')
        async def set_rsi_condition_upper_bound(call: CallbackQuery):
            chat_id = call.message.chat.id
            # RSI 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['rsi']
            # 콜백 데이터 파싱
            upper_bound = KeypadKeyboardLayout.parse_confirm_callback(call)
            # 입력한 값 저장
            condition_memory['upper_bound'] = upper_bound
            await ask_rsi_condition_lower_bound(call)

        async def ask_rsi_condition_lower_bound(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            message_id = call.message.id
            # RSI 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['rsi']
            # 조건 입력 키패드 마크업으로 메시지 수정
            text = "RSI 설정\n하향 돌파 기준값을 입력해주세요.\n*하향 돌파 기준을 입력하지 않으려면 0을 입력"
            upper_bound: float = condition_memory['upper_bound']
            lower_bound: float = condition_memory['lower_bound']
            # 키패드 마크업
            displayed_number: str = str(lower_bound)
            keyboard_layout = KeypadKeyboardLayout(displayed_number=displayed_number, symbol="이하 돌파 시 알림",
                                                   limit=upper_bound)
            markup = keyboard_layout.make_markup()
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            # state 설정
            state = rsi_state_group.lower_bound
            await self.bot.set_state(user_id=user_id, state=state, chat_id=chat_id)

        @self.bot.callback_query_handler(func=None, state=rsi_state_group.lower_bound, callback_type='confirm')
        async def set_rsi_condition_lower_bound(call: CallbackQuery):
            chat_id = call.message.chat.id
            # RSI 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['rsi']
            # 콜백 데이터 파싱
            lower_bound = KeypadKeyboardLayout.parse_confirm_callback(call)
            # 입력한 값 저장
            condition_memory['lower_bound'] = lower_bound
            await back_to_condition_select(call)

        # RSI 조건 삭제 시 메모리에서 해당 조건을 None으로 초기화
        @self.bot.callback_query_handler(func=rsi_state_filter, callback_type=callback.delete_condition)
        async def delete_rsi_condition(call: CallbackQuery):
            chat_id = call.message.chat.id
            self.memory[chat_id]['condition']['rsi'] = None
            await back_to_condition_select(call)

        async def ask_bollinger_band_condition_period(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            message_id = call.message.id
            # 볼린저 밴드 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['bollinger_band']
            # 조건 입력 키패드 마크업으로 메시지 수정
            text = "볼린저 밴드 설정\n이동평균선 기간을 입력해주세요."
            exchange_id = self.memory[chat_id]['exchange_id']
            length: int = condition_memory['length']
            interval_dict: IntervalDict = condition_memory['interval']
            interval = f"{interval_dict['length']}{interval_dict['timeframe']}"
            # 키보드 마크업
            keyboard_layout = PeriodInputKeyboardLayout(length=length, exchange_id=exchange_id, interval=interval)
            markup = keyboard_layout.make_markup()
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            # state 설정
            state = bollinger_band_state_group.interval
            await self.bot.set_state(user_id=user_id, state=state, chat_id=chat_id)

        @self.bot.callback_query_handler(func=None, state=bollinger_band_state_group.interval, callback_type='confirm')
        async def set_bollinger_band_condition_period(call: CallbackQuery):
            chat_id = call.message.chat.id
            # 볼린저 밴드 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['bollinger_band']
            # 콜백 데이터 파싱
            length, interval = PeriodInputKeyboardLayout.parse_confirm_callback(call)
            # 입력한 기간 저장
            condition_memory['length'] = length
            condition_memory['interval'] = interval.dict
            await ask_bollinger_band_condition_coefficient(call)

        async def ask_bollinger_band_condition_coefficient(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            message_id = call.message.id
            # 볼린저 밴드 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['bollinger_band']
            # 조건 입력 키패드 마크업으로 메시지 수정
            text = "볼린저밴드 설정\n상단선/하단선 표준편차를 입력해주세요."
            coefficient: float = condition_memory['coefficient']
            # 키패드 마크업
            displayed_number: str = str(coefficient)
            keyboard_layout = KeypadKeyboardLayout(displayed_number=displayed_number)
            markup = keyboard_layout.make_markup()
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            # state 설정
            state = bollinger_band_state_group.coefficient
            await self.bot.set_state(user_id=user_id, state=state, chat_id=chat_id)

        @self.bot.callback_query_handler(func=None, state=bollinger_band_state_group.coefficient,
                                         callback_type='confirm')
        async def set_bollinger_band_condition_coefficient(call: CallbackQuery):
            chat_id = call.message.chat.id
            # 볼린저 밴드 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['bollinger_band']
            # 콜백 데이터 파싱
            coefficient = KeypadKeyboardLayout.parse_confirm_callback(call)
            # 입력한 값 저장
            condition_memory['coefficient'] = coefficient
            await ask_which_bollinger_band_to_alert(call)

        async def ask_which_bollinger_band_to_alert(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            message_id = call.message.id
            # 볼린저 밴드 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['bollinger_band']
            on_over_upper_band = condition_memory['on_over_upper_band']
            on_under_lower_band = condition_memory['on_under_lower_band']
            # 메시지 수정
            text = "볼린저밴드 설정\n돌파 시 알림을 받을 밴드를 모두 선택해주세요."
            items = [("상단선", on_over_upper_band), ("하단선", on_under_lower_band)]
            keyboard_layout = ToggleMenuKeyboardLayout(items=items)
            markup = keyboard_layout.make_markup()
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            # state 설정
            state = bollinger_band_state_group.band_to_alert
            await self.bot.set_state(user_id=user_id, state=state, chat_id=chat_id)

        @self.bot.callback_query_handler(func=None, state=bollinger_band_state_group.band_to_alert,
                                         callback_type='confirm')
        async def set_bollinger_bands_to_alert(call: CallbackQuery):
            chat_id = call.message.chat.id
            # 볼린저 밴드 조건 메모리
            condition_memory = self.memory[chat_id]['condition']['bollinger_band']
            # 콜백 데이터 파싱
            items = ToggleMenuKeyboardLayout.parse_confirm_callback(call)
            on_over_upper_band = items[0][1]
            on_under_lower_band = items[1][1]
            # 입력한 값 저장
            condition_memory['on_over_upper_band'] = on_over_upper_band
            condition_memory['on_under_lower_band'] = on_under_lower_band
            await back_to_condition_select(call)

        # 볼린저밴드 조건 삭제 시 메모리에서 해당 조건을 None으로 초기화
        @self.bot.callback_query_handler(func=bollinger_band_state_filter,
                                         callback_type=callback.delete_condition)
        async def delete_bollinger_band_condition(call: CallbackQuery):
            chat_id = call.message.chat.id
            self.memory[chat_id]['condition']['bollinger_band'] = None
            await back_to_condition_select(call)

        # 각 알람 조건 설정에서 알람 조건 선택 마크업으로 돌아감
        async def back_to_condition_select(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            # state 설정
            state = chat_memory['state']  # 조건을 설정하기 전 원래의 state
            await self.bot.set_state(user_id, state, chat_id)
            # 알람 조건 선택 마크업으로 수정
            message_id = call.message.id
            text = "설정할 조건을 선택해주세요."
            keyboard_layout = ItemSelectKeyboardLayout(labels=self._condition_type_names)
            markup = keyboard_layout.make_markup()
            await self.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, reply_markup=markup)

    def register_channel_adding_process(self):
        @self.bot.callback_query_handler(func=None, state=ChannelMenuStates.menu, callback_type='confirm:0')
        async def ask_channel_name(call: CallbackQuery):
            user_id = call.from_user.id
            chat_id = call.message.chat.id
            # 채널 메뉴 선택 키보드 비활성화
            await self.disable_markup(message=call.message, text="채널 추가")
            # state 설정
            state = ChannelAddingProcessStates.channel_name
            await self.bot.set_state(user_id, state, chat_id)
            # 채널 이름 질문
            text = "추가할 채널을 뭐라고 부를까요?"
            keyboard_layout = ItemSelectKeyboardLayout(labels=[])  # 취소 버튼만 있는 빈 키보드
            markup = keyboard_layout.make_markup()
            await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)

        async def set_channel_name(message: Message):
            chat_id = message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            # 메시지로 온 채널 이름을 메모리에 저장
            channel_name = message.text
            chat_memory['channel_name'] = channel_name

        @self.bot.message_handler(state=ChannelAddingProcessStates.channel_name)
        async def ask_channel_id(message: Message):
            await set_channel_name(message)
            user_id = message.from_user.id
            chat_id = message.chat.id
            # state 설정
            state = ChannelAddingProcessStates.channel_id
            await self.bot.set_state(user_id, state, chat_id)
            # 채널 링크 질문
            text = "먼저 채널에 저를 초대하고 관리자 권한으로 승격해주세요. 그 뒤 채널을 공개로 설정하고 변경한 링크를 보내주세요.\n링크의 예) https://t.me/0000"
            keyboard_layout = ItemSelectKeyboardLayout(labels=[])  # 취소 버튼만 있는 빈 키보드
            markup = keyboard_layout.make_markup()
            await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)

        async def set_channel_id(message: Message):
            chat_id = message.chat.id
            chat_memory = self.memory[chat_id]  # 채팅의 메모리
            # 메시지로 온 채널 링크에서 채널 ID 파싱
            channel_link = f"@{message.text.replace('https://t.me/', '')}"
            # 채널에 메시지를 보내 ID를 확인
            try:
                sended_message = await self.bot.send_message(channel_link, "채널 확인을 위한 메시지입니다.")
            except ApiTelegramException as e:
                await self.bot.send_message(chat_id=chat_id, text="잘못된 링크입니다. 링크를 확인하고 다시 보내주세요.")
                return
            # ID가 정상적으로 확인되면 해당 ID를 저장
            channel_id = sended_message.chat.id
            chat_memory['channel_id'] = channel_id

        def add_channel_to_database(chat_id: int):
            chat_memory = self.memory[chat_id]
            # 데이터베이스에 채널 저장
            channel_id = chat_memory['channel_id']
            channel_name = chat_memory['channel_name']
            self.database.insert('channel', channel_id=channel_id, channel_name=channel_name,
                                 chat_id=chat_id)

        @self.bot.message_handler(state=ChannelAddingProcessStates.channel_id)
        async def set_channel(message: Message):
            await set_channel_id(message)
            user_id = message.from_user.id
            chat_id = message.chat.id
            # 채널 저장
            add_channel_to_database(chat_id)
            # 메모리 초기화
            self.memory.pop(chat_id)
            # state 설정
            await self.bot.set_state(user_id, '', chat_id)
            # 안내 메시지 발송
            await self.bot.send_message(chat_id=chat_id, text="채널이 등록되었습니다.")
