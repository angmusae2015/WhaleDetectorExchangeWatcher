from typing import Union, List, Optional, Any, TypedDict, Literal, Dict, Final, Tuple
from datetime import datetime

UPBIT_ID: Final[int] = 1
BINANCE_ID: Final[int] = 2
ExchangeId = Literal[1, 2]
EXCHANGE_NAMES = ["업비트", "바이낸스"]

AlarmId = int
Symbol = str

Interval = Literal['1s', '1m', '1h', '1d']
VALID_INTERVALS = ('1s', '1m', '1h', '1d')
INTERVAL_SECOND_DICT = {
    '1s': 1,
    '1m': 60,
    '1h': 3600,
    '1d': 86400
}


def index_of_interval(interval: Interval) -> int:
    return VALID_INTERVALS.index(interval)


class Candle:
    def __init__(self, exchange_id: ExchangeId, symbol: Symbol, datetime: datetime, interval: Interval, open: float,
                 highest: float, lowest: float, closing: float, volume: float):
        self.exchange_id = exchange_id
        self.symbol = symbol
        self.datetime = datetime
        self.interval = interval
        self.open = open
        self.highest = highest
        self.lowest = lowest
        self.closing = closing
        self.volume = volume

    def convert_datetime(self, interval: Interval) -> datetime:
        keywords = ('microsecond', 'second', 'minute', 'hour')
        interval_index = index_of_interval(interval)
        kwargs = {keyword: 0 for keyword in keywords[:interval_index + 1]}
        converted_datetime = self.datetime.replace(**kwargs)
        return converted_datetime

    def is_second_changed(self, candle: 'Candle') -> bool:
        return self.datetime.second != candle.datetime.second

    def is_minute_changed(self, candle: 'Candle') -> bool:
        return self.datetime.minute != candle.datetime.minute

    def is_hour_changed(self, candle: 'Candle') -> bool:
        return self.datetime.hour != candle.datetime.hour

    def is_day_changed(self, candle: 'Candle') -> bool:
        return self.datetime.day != candle.datetime.day

    def is_time_changed(self, candle: 'Candle', interval: Interval) -> bool:
        time_lambda: callable
        if interval == '1s':
            time_lambda = lambda _candle: _candle.datetime.second
        elif interval == '1m':
            time_lambda = lambda _candle: _candle.datetime.minute
        elif interval == '1h':
            time_lambda = lambda _candle: _candle.datetime.hour
        elif interval == '1d':
            time_lambda = lambda _candle: _candle.datetime.day
        return time_lambda(self) != time_lambda(candle)


class WhaleCondition(TypedDict):
    quantity: float


class TickCondition(TypedDict):
    quantity: float


class BollingerBandCondition(TypedDict):
    length: int
    interval: Interval
    coefficient: float


class RsiCondition(TypedDict):
    length: int
    interval: Interval
    max_value: float
    min_value: float


class Condition:
    def __init__(
            self,
            condition_id: int,
            whale: Optional[WhaleCondition],
            tick: Optional[TickCondition],
            bollinger_band: Optional[BollingerBandCondition],
            rsi: Optional[RsiCondition]
    ):
        self.id = condition_id
        self.whale = whale
        self.tick = tick
        self.bollinger_band = bollinger_band
        self.rsi = rsi


class Alarm:
    def __init__(self, alarm_id: int, channel_id: int, exchange_id: ExchangeId, base_symbol: str, quote_symbol: str,
                 condition: Condition):
        self.id = alarm_id
        self.channel_id = channel_id
        self.exchange_id = exchange_id  # 업비트: 1, 바이낸스: 2
        self.base_symbol = base_symbol
        self.quote_symbol = quote_symbol
        self.symbol = f"{base_symbol}/{quote_symbol}"
        self.condition = condition


class Whale(TypedDict):
    bids: List[float]
    asks: List[float]
