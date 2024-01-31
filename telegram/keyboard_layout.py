import math
from typing import List, Optional, Tuple

from telebot.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from watcher.definition import UPBIT_ID, BINANCE_ID, Interval

from telegram import callback


cancel_button = InlineKeyboardButton(text='취소', callback_data=callback.cancel)
delete_condition_button = InlineKeyboardButton(text='조건 삭제', callback_data=callback.delete_condition)


class KeyboardLayout:
    def __init__(self):
        self._markup = InlineKeyboardMarkup()

    @staticmethod
    def parse_confirm_callback(call: CallbackQuery):
        pass


class ItemSelectKeyboardLayout(KeyboardLayout):
    def __init__(self, labels: List[str], items_per_page: int = 5):
        super().__init__()
        self.labels = labels
        self.items_per_page = items_per_page

    @property
    def last_page_index(self) -> int:
        last_page_index = math.ceil(len(self.labels) / self.items_per_page) - 1
        return last_page_index

    def make_markup(self, page: int = 0) -> InlineKeyboardMarkup:
        # 마크업 초기화
        self._markup = InlineKeyboardMarkup()
        # 요소의 개수가 페이지 당 최대 요소 수(기본: 5) 이하일 경우 모든 요소를 키보드에 추가
        labels_length = len(self.labels)
        if labels_length <= self.items_per_page:
            labels_to_add = self.labels
        else:
            labels_to_add = self.get_page(page=page)
        self.add_buttons_to_keyboard(labels=labels_to_add)
        # 요소 개수가 페이지 당 최대 요소 수(기본: 5) 초과일 경우 페이지 이동 버튼을 키보드에 추가
        if labels_length > self.items_per_page:
            navigation_row = [self.previous_page_button(page), self.navigator_button(page), self.next_page_button(page)]
            self._markup.add(*navigation_row)
        self._markup.add(cancel_button)
        return self._markup

    def get_page(self, page: int) -> List[str]:
        labels_length = len(self.labels)
        # 페이지에서 표시할 요소의 인덱스 범위
        start_index = page * self.items_per_page
        end_index = min(start_index + self.items_per_page, labels_length)
        return self.labels[start_index:end_index]

    def add_buttons_to_keyboard(self, labels: [str]):
        for index in range(len(labels)):
            label = labels[index]
            callback_data = f"{callback.confirm}:{index}"
            button = InlineKeyboardButton(text=label, callback_data=callback_data)
            self._markup.add(button)

    def previous_page_button(self, page: int) -> InlineKeyboardButton:
        previous_page_index = page - 1 if page != 0 else self.last_page_index
        text = '<'
        callback_data = f"{callback.page_to}:{previous_page_index}"
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    def navigator_button(self, page: int) -> InlineKeyboardButton:
        text = f"{page + 1} / {self.last_page_index + 1}"
        callback_data = callback.ignore
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    def next_page_button(self, page: int) -> InlineKeyboardButton:
        next_page_index = page + 1 if page != self.last_page_index else 0
        text = '>'
        callback_data = f"{callback.page_to}:{next_page_index}"
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    @staticmethod
    def parse_confirm_callback(call: CallbackQuery) -> str:
        # 콜백 데이터 파싱
        callback_type, index = call.data.split(':')
        # 문자열로 전송된 인덱스 값을 정수형으로 변환
        index = int(index)
        inline_keyboard_rows = call.message.json['reply_markup']['inline_keyboard']
        selected_button = inline_keyboard_rows[index][0]    # 누른 버튼
        selected_label = selected_button['text']    # 누른 버튼의 텍스트
        return selected_label


class KeypadKeyboardLayout(KeyboardLayout):
    callback = callback.keypad

    def __init__(self, displayed_number: str, symbol: str = '', limit: Optional[float] = None):
        super().__init__()
        self.displayed_number = displayed_number
        self.symbol = symbol
        self.limit = limit

    def make_markup(self) -> InlineKeyboardMarkup:
        # 마크업 초기화
        self._markup = InlineKeyboardMarkup()
        # 디스플레이 버튼 추가
        self._markup.add(self.display_button)
        # 초기화 버튼 / 삭제 버튼 추가
        self._markup.add(self.clear_button, self.backspace_button)
        # 숫자 키 추가
        self.add_number_keys()
        # 000, 0, . 키 추가
        self._markup.add(self.triple_zero_button, self.single_zero_button, self.point_button)
        # 조건 삭제 버튼 / 입력 버튼 추가
        self._markup.add(delete_condition_button, self.confirm_button)
        return self._markup

    def add_number_keys(self):
        number_arrangement = [[7, 8, 9], [4, 5, 6], [1, 2, 3]]
        for row in number_arrangement:
            button_row = [self.number_button(number) for number in row]
            self._markup.add(*button_row)

    @property
    def display_button(self):
        text = f"{self.displayed_number} {self.symbol}"
        button = InlineKeyboardButton(text=text, callback_data=callback.ignore)
        return button

    @property
    def clear_button(self) -> InlineKeyboardButton:
        text = 'C'
        if self.displayed_number == '0':
            callback_data = callback.ignore
        else:
            callback_data = self.callback_data('0')
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    @property
    def backspace_button(self) -> InlineKeyboardButton:
        text = '<-'
        if self.displayed_number == '0':
            callback_data = callback.ignore
        elif len(self.displayed_number) == 1:
            callback_data = self.callback_data('0')
        else:
            callback_data = self.callback_data(self.displayed_number[:-1])
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    @property
    def triple_zero_button(self) -> InlineKeyboardButton:
        return self.zero_button(number_of_zeros=3)

    @property
    def single_zero_button(self) -> InlineKeyboardButton:
        return self.zero_button(number_of_zeros=1)

    @property
    def point_button(self) -> InlineKeyboardButton:
        text = '.'
        if text in self.displayed_number:
            callback_data = callback.ignore
        else:
            callback_data = self.callback_data(self.displayed_number + text)
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    @property
    def confirm_button(self) -> InlineKeyboardButton:
        text = '입력'
        callback_data = f"{callback.confirm}:{self.displayed_number}"
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    def zero_button(self, number_of_zeros: int) -> InlineKeyboardButton:
        text = '0' * number_of_zeros
        if self.limit is not None:
            if float(self.displayed_number + text) > self.limit:
                callback_data = callback.ignore
                button = InlineKeyboardButton(text=text, callback_data=callback_data)
                return button
        if self.displayed_number == '0':
            callback_data = callback.ignore
        else:
            callback_data = self.callback_data(self.displayed_number + text)
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    def number_button(self, number: int) -> InlineKeyboardButton:
        text = str(number)
        if self.limit is not None:
            if float(self.displayed_number + text) > self.limit:
                callback_data = callback.ignore
                button = InlineKeyboardButton(text=text, callback_data=callback_data)
                return button
        if self.displayed_number == '0':
            callback_data = self.callback_data(text)
        else:
            callback_data = self.callback_data(self.displayed_number + text)
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    def callback_data(self, number: str):
        if self.limit is None:
            limit_text = ''
        else:
            limit_text = str(self.limit)
        return f"{self.callback}:{number}:{self.symbol}:{limit_text}"

    @classmethod
    def update_markup(cls, call: CallbackQuery) -> InlineKeyboardMarkup:
        # 콜백 데이터 파싱
        callback_type, number, symbol, limit_text = call.data.split(':')
        limit = None
        if limit_text != '':
            limit = float(limit_text)
        keyboard_layout = cls(number, symbol, limit)
        return keyboard_layout.make_markup()

    @staticmethod
    def parse_confirm_callback(call: CallbackQuery) -> float:
        # 콜백 데이터 파싱
        callback_type, number = call.data.split(':')
        # 문자열로 전달된 숫자를 실수형으로 변환
        number = float(number)
        return number


class PeriodInputKeyboardLayout(KeyboardLayout):
    available_intervals = {
        UPBIT_ID: ['1s', '1m', '3m', '5m', '10m', '15m', '30m', '1h', '4h', '1d', '1w', '1M'],
        BINANCE_ID: ['1s', '1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']
    }
    callback = callback.period

    def __init__(self, length: int, exchange_id: int, interval: str):
        super().__init__()
        self.length = length
        self.exchange_id = exchange_id
        self.interval_index = self.available_intervals[exchange_id].index(interval)

    @property
    def selected_interval(self) -> str:
        return self.available_intervals[self.exchange_id][self.interval_index]

    # 해당 거래소에서 사용가능한 인터벌의 최대 인덱스
    @property
    def maximum_interval_index(self) -> int:
        return len(self.available_intervals[self.exchange_id]) - 1

    def make_markup(self) -> InlineKeyboardMarkup:
        # 마크업 초기화
        self._markup = InlineKeyboardMarkup()
        void_button = InlineKeyboardButton(text=' ', callback_data=callback.ignore)     # 빈 버튼
        # 길이 +10 버튼 / 빈 버튼 추가
        add_10_to_length_button = self.add_length_button(10)
        self._markup.add(add_10_to_length_button, void_button)
        # 길이 +1 버튼 / 인터벌 상승 버튼 추가
        add_1_to_length_button = self.add_length_button(1)
        self._markup.add(add_1_to_length_button, self.upper_interval_button)
        # 길이 / 인터벌 표시 버튼 추가
        self._markup.add(self.length_display_button, self.interval_display_button)
        # 길이 -1 버튼 / 인터벌 하강 버튼 추가
        sub_1_from_length_button = self.sub_length_button(1)
        self._markup.add(sub_1_from_length_button, self.lower_interval_button)
        # 길이 -10 버튼 / 빈 버튼 추가
        sub_10_from_length_button = self.sub_length_button(10)
        self._markup.add(sub_10_from_length_button, void_button)
        # 조건 삭제 버튼 / 입력 버튼 추가
        self._markup.add(delete_condition_button, self.confirm_button)
        return self._markup

    def add_length_button(self, addition: int) -> InlineKeyboardButton:
        text = f"+{addition}"
        added_length = self.length + addition
        if added_length > 28:
            if self.length == 28:
                callback_data = callback.ignore
            else:
                callback_data = self.callback_data(28, self.interval_index)
        else:
            callback_data = self.callback_data(added_length, self.interval_index)
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    def sub_length_button(self, subtraction: int) -> InlineKeyboardButton:
        text = f"-{subtraction}"
        subtracted_length = self.length - subtraction
        if subtracted_length < 0:
            if self.length == 0:
                callback_data = callback.ignore
            else:
                callback_data = self.callback_data(0, self.interval_index)
        else:
            callback_data = self.callback_data(subtracted_length, self.interval_index)
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    @property
    def upper_interval_button(self) -> InlineKeyboardButton:
        text = "🔼"
        if self.interval_index == self.maximum_interval_index:
            callback_data = self.callback_data(self.length, 0)
        else:
            callback_data = self.callback_data(self.length, self.interval_index + 1)
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    @property
    def lower_interval_button(self) -> InlineKeyboardButton:
        text = "🔽"
        if self.interval_index == 0:
            callback_data = self.callback_data(self.length, self.maximum_interval_index)
        else:
            callback_data = self.callback_data(self.length, self.interval_index - 1)
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    @property
    def length_display_button(self) -> InlineKeyboardButton:
        text = f"{self.length}"
        button = InlineKeyboardButton(text=text, callback_data=callback.ignore)
        return button

    @property
    def interval_display_button(self) -> InlineKeyboardButton:
        text = Interval(string=self.selected_interval).korean
        button = InlineKeyboardButton(text=text, callback_data=callback.ignore)
        return button

    @property
    def confirm_button(self) -> InlineKeyboardButton:
        text = '입력'
        callback_data = f"{callback.confirm}:{self.length}:{self.selected_interval}"
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    def callback_data(self, length: int, interval_index: int):
        return f"{self.callback}:{length}:{self.exchange_id}:{interval_index}"

    @classmethod
    def update_markup(cls, call: CallbackQuery) -> InlineKeyboardMarkup:
        # 콜백 데이터 파싱
        callback_type, length, exchange_id, interval_index = call.data.split(':')
        # 문자열로 전송된 데이터를 정수형으로 변환
        length = int(length)
        exchange_id = int(exchange_id)
        interval_index = int(interval_index)
        interval = cls.available_intervals[exchange_id][interval_index]
        # 마크업 수정
        keyboard_layout = cls(length=length, exchange_id=exchange_id, interval=interval)
        markup = keyboard_layout.make_markup()
        return markup

    @staticmethod
    def parse_confirm_callback(call: CallbackQuery) -> Tuple[int, Interval]:
        # 콜백 데이터 파싱
        callback_type, length, interval_str = call.data.split(':')
        length = int(length)
        interval = Interval(string=interval_str)
        return length, interval


class ToggleMenuKeyboardLayout(KeyboardLayout):
    callback = callback.toggle

    def __init__(self, items: List[Tuple[str, bool]]):
        super().__init__()
        self.items = items

    def make_markup(self) -> InlineKeyboardMarkup:
        # 마크업 초기화
        self._markup = InlineKeyboardMarkup()
        # 레이블 버튼 / 토글 버튼 추가
        self.add_buttons_to_markup()
        # 조건 삭제 버튼 / 입력 버튼 추가
        self._markup.add(delete_condition_button, self.confirm_button)
        return self._markup

    def add_buttons_to_markup(self):
        for index in range(len(self.items)):
            label, is_enabled = self.items[index]
            # 요소의 레이블 버튼
            label_button = InlineKeyboardButton(text=label, callback_data=callback.ignore)
            # 토글 버튼
            if is_enabled:
                toggle_button_text = '🔔'
            else:
                toggle_button_text = '🔕'
            callback_data = self.callback_data(index=index)
            toggle_button = InlineKeyboardButton(text=toggle_button_text, callback_data=callback_data)
            self._markup.add(label_button, toggle_button)

    @property
    def confirm_button(self) -> InlineKeyboardButton:
        text = '입력'
        callback_data = callback.confirm
        button = InlineKeyboardButton(text=text, callback_data=callback_data)
        return button

    @classmethod
    def callback_data(cls, index: int):
        callback_data = f"{cls.callback}:{index}"
        return callback_data

    @classmethod
    def update_markup(cls, call: CallbackQuery) -> InlineKeyboardMarkup:
        # 콜백 데이터 파싱
        callback_type, index = call.data.split(':')
        # 문자열로 전송된 데이터를 정수형으로 변환
        index = int(index)
        # 토글된 레이블의 상태를 변경
        items = cls.parse_items_from_keyboard(call)
        toggled_label, is_enabled = items[index]
        toggled_item = (toggled_label, not is_enabled)
        items[index] = toggled_item
        # 마크업 수정
        keyboard_layout = cls(items)
        markup = keyboard_layout.make_markup()
        return markup

    @classmethod
    def parse_confirm_callback(cls, call: CallbackQuery) -> List[Tuple[str, bool]]:
        return cls.parse_items_from_keyboard(call)

    @staticmethod
    def parse_items_from_keyboard(call: CallbackQuery) -> List[Tuple[str, bool]]:
        inline_keyboard_rows = call.message.json['reply_markup']['inline_keyboard'][:-1]
        items = []
        for row in inline_keyboard_rows:
            label_button, toggle_button = row
            label = label_button['text']
            is_enabled = toggle_button['text'] == '🔔'
            items.append((label, is_enabled))
        return items


def toggle_markup(items: List[Tuple[str, bool]]) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    for index in range(len(items)):
        item = items[index]
        text, is_enabled = item
        label_button = InlineKeyboardButton(text=text, callback_data=callback.ignore)
        if is_enabled:
            toggle_button = InlineKeyboardButton(text="🔔", callback_data=f"toggle:to_off:{index}")
        else:
            toggle_button = InlineKeyboardButton(text="🔕", callback_data=f"toggle:to_on:{index}")
        markup.add(label_button, toggle_button)
    # 입력 완료 버튼
    confirm_button = InlineKeyboardButton(text='입력', callback_data=f"confirm")
    markup.add(confirm_button)
    return markup
