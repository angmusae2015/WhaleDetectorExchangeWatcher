from typing import Final, List, Optional, TypedDict
from datetime import datetime

from ccxt.base.types import Trade, OrderBook

from database.definition import WhaleCondition, TickCondition, RsiCondition, BollingerBandCondition

UPBIT_ID: Final[int] = 1
BINANCE_ID: Final[int] = 2


class WhaleInfo(TypedDict):
    is_condition_none: bool
    has_whale: Optional[bool]
    whales_in_bids: List[List[float]]
    whales_in_asks: List[List[float]]
    order_book: OrderBook


# 거래량 조건을 확인한 결과를 저장할 딕셔너리
class TickInfo(TypedDict):
    is_condition_none: bool
    is_breakout: Optional[bool]
    trade: Trade
    condition: Optional[TickCondition]


# RSI 조건을 확인한 결과를 저장할 딕셔너리
class RsiInfo(TypedDict):
    is_condition_none: bool
    is_over_upper_bound: Optional[bool]
    is_under_lower_bound: Optional[bool]
    rsi: Optional[float]
    trade: Trade
    condition: Optional[RsiCondition]


# 볼린저 밴드 조건을 확인한 결과를 저장할 딕셔너리
class BollingerBandInfo(TypedDict):
    is_condition_none: bool
    is_over_upper_band: Optional[bool]
    is_under_lower_band: Optional[bool]
    upper_band: Optional[float]
    lower_band: Optional[float]
    trade: Trade
    condition: Optional[BollingerBandCondition]


# 인터벌
class Interval:
    def __init__(self, length: int = None, timeframe: str = None, string: Optional[str] = None):
        if string is not None:
            self.length = int(string[:-1])   # 길이
            self.timeframe = string[-1:]    # 타임프레임
        else:
            self.length = length  # 길이
            self.timeframe = timeframe  # 타임프레임

    def __str__(self):
        return f'{self.length}{self.timeframe}'

    def __repr__(self):
        return f"Interval(length={self.length}, range={self.timeframe})"

    def __eq__(self, other: 'Interval'):
        return other.__str__() == self.__str__()

    def __lt__(self, other):
        return self.to_second < other.to_second

    def __le__(self, other):
        return self.to_second <= other.to_second

    def __gt__(self, other):
        return self.to_second > other.to_second

    def __ge__(self, other):
        return self.to_second >= other.to_second

    def __hash__(self):
        return hash(self.__str__())

    # 인터벌을 초 단위로 변환
    @property
    def to_second(self) -> int:
        interval_second_dict = {
            's': 1,
            'm': 60,
            'h': 3600,
            'd': 86400,
            'w': 604800
        }
        second = self.length * interval_second_dict[self.timeframe]
        return second

    @property
    def korean(self) -> str:
        timeframe_dict = {
            's': '초', 'm': '분', 'h': '시간', 'd': '일', 'w': '주', 'M': '달'
        }
        korean_timeframe = timeframe_dict[self.timeframe]
        return f'{self.length}{korean_timeframe}'

    @property
    def dict(self) -> dict:
        return {
            'length': self.length,
            'timeframe': self.timeframe
        }


class Candle:
    def __init__(self, exchange_id: int, symbol: str, _datetime: datetime, interval: Interval):
        self.exchange_id: int = exchange_id
        self.symbol: str = symbol
        self.datetime: datetime = _datetime
        self.interval: Interval = interval
        self.trades: List[Trade] = []
        self._open: Optional[float] = None
        self._high: Optional[float] = None
        self._low: Optional[float] = None
        self._close: Optional[float] = None

    @property
    def open(self) -> float:
        if len(self.trades) == 0:
            return self._open
        first_trade = self.trades[0]
        return first_trade['price']

    @property
    def high(self) -> float:
        if len(self.trades) == 0:
            return self._high
        prices = [trade['price'] for trade in self.trades]
        return max(prices)

    @property
    def low(self) -> float:
        if len(self.trades) == 0:
            return self._low
        prices = [trade['price'] for trade in self.trades]
        return min(prices)

    @property
    def close(self) -> float:
        if len(self.trades) == 0:
            return self._close
        last_trade = self.trades[-1]
        return last_trade['price']

    @open.setter
    def open(self, _open: float):
        self._open = _open

    @high.setter
    def high(self, high: float):
        self._high = high

    @low.setter
    def low(self, low: float):
        self._low = low

    @close.setter
    def close(self, close: float):
        self._close = close

    @property
    def time_limit(self) -> int:
        candle_timestamp = int(self.datetime.timestamp())
        candle_interval_in_second = self.interval.to_second
        return candle_timestamp + candle_interval_in_second

    def add_trade(self, trade: Trade):
        self.trades.append(trade)

    def clear_trade(self):
        self._open = self.open
        self._high = self.high
        self._low = self.low
        self._close = self.close
        self.trades = []
