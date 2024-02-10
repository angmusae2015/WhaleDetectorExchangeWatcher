from typing import Optional, TypedDict


class Chat(TypedDict):
    chat_id: int


class Channel(TypedDict):
    channel_id: int
    channel_name: str
    chat_id: int


class IntervalDict(TypedDict):
    length: int
    timeframe: str


class WhaleCondition(TypedDict):
    quantity: float


class TickCondition(TypedDict):
    quantity: float


class RsiCondition(TypedDict):
    length: int
    upper_bound: float
    lower_bound: float
    interval: IntervalDict


class BollingerBandCondition(TypedDict):
    length: int
    coefficient: float
    on_over_upper_band: bool
    on_under_lower_band: bool
    interval: IntervalDict


class Condition(TypedDict):
    alarm_id: int
    whale: Optional[WhaleCondition]
    tick: Optional[TickCondition]
    bollinger_band: Optional[BollingerBandCondition]
    rsi: Optional[RsiCondition]


class AlarmDict(TypedDict):
    alarm_id: int
    channel_id: int
    exchange_id: int
    base_symbol: str
    quote_symbol: str
    is_enabled: bool
