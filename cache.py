from typing import List, Dict, TypedDict

from ccxt.base.types import Trade

from .types import *

CandleCache = Dict[
    ExchangeId, Dict[
        Interval, Dict[
            Symbol, List[Candle]
        ]
    ]
]

TradeCache = Dict[
    ExchangeId, Dict[
        Symbol, List[Trade]
    ]
]

WhaleCache = Dict[
    ExchangeId, Dict[
        Symbol, Dict[
            AlarmId, Whale
        ]
    ]
]


def index_of_interval(interval: Interval) -> int:
    return VALID_INTERVALS.index(interval)


def get_upper_interval(interval: Interval) -> Interval:
    interval_index = index_of_interval(interval)
    upper_interval = VALID_INTERVALS[interval_index + 1]
    return upper_interval


def is_interval_unified(candles: List[Candle]) -> bool:
    sample_interval = candles[0].interval
    same_intervals = [candle.interval for candle in candles if candle.interval == sample_interval]
    return len(candles) == len(same_intervals)


def downsample_candles(candles: List[Candle]) -> Candle:
    if not is_interval_unified(candles):
        raise ValueError("Interval of candles cannot be different.")
    if len(candles) == 0:
        raise ValueError("Empty candle list is given.")
    first_candle = candles[0]
    last_candle = candles[-1]
    exchange_id = first_candle.exchange_id
    symbol = first_candle.symbol
    interval = get_upper_interval(first_candle.interval)
    c_datetime = first_candle.convert_datetime(interval)
    c_open = first_candle.open
    c_highest = max([candle.highest for candle in candles])
    c_lowest = min([candle.lowest for candle in candles])
    c_closing = last_candle.closing
    c_volume = 0
    for candle in candles:
        c_volume += candle.volume
    return Candle(exchange_id, symbol, c_datetime, interval, c_open, c_highest, c_lowest, c_closing, c_volume)


class Cache:
    candles: CandleCache = {
        UPBIT_ID: {
            '1s': {},
            '1m': {},
            '1h': {},
            '1d': {}
        },
        BINANCE_ID: {
            '1s': {},
            '1m': {},
            '1h': {},
            '1d': {}
        }
    }
    trades: TradeCache = {
        UPBIT_ID: {},
        BINANCE_ID: {}
    }
    whales: WhaleCache = {
        UPBIT_ID: {},
        BINANCE_ID: {}
    }

    def get_candles(self, exchange_id: ExchangeId, symbol: str, interval: Interval, since: int=None, limit: int=None) -> List[Candle]:
        if symbol not in self.candles[exchange_id][interval]:
            return []
        candles = self.candles[exchange_id][interval][symbol]
        if since is not None:
            candles = [candle for candle in candles if candle.datetime.timestamp() >= since]
        if limit is not None:
            candles = [candle for candle in candles if candle.datetime.timestamp() < limit]
        return candles

    
    def add_candle(self, candle: Candle):
        exchange_id = candle.exchange_id
        symbol = candle.symbol
        interval = candle.interval
        self.candles[exchange_id][interval][symbol].append(candle)
        if len(self.get_candles(exchange_id, symbol, interval)) > 100:
            self.candles[exchange_id][interval][symbol].pop(0)

    
    def get_trades(self, exchange_id: ExchangeId, symbol: str) -> List[Trade]:
        if symbol not in self.trades[exchange_id]:
            return []
        return self.trades[exchange_id][symbol]

    
    def add_trade(self, exchange_id: ExchangeId, symbol: str, trade: Trade):
        self.trades[exchange_id][symbol].append(trade)


    def get_whales(self, exchange_id: ExchangeId, symbol: str, alarm_id: int) -> dict:
        whales = {'bids': [], 'asks': []}
        if symbol not in self.whales[exchange_id]:
            return whales
        if alarm_id not in self.whales[exchange_id][symbol]:
            return whales
        whales = self.whales[exchange_id][symbol][alarm_id]
        return whales


    def clear_trade(self, exchange_id: ExchangeId, symbol: str):
        self.trades[exchange_id][symbol] = []

    
    def last_cached_candle(self, exchange_id: ExchangeId, symbol: str, interval: Interval) -> Candle:
        try:
            cached_candles = self.get_candles(exchange_id, symbol, interval)
            return cached_candles[-1]
        except KeyError as e:
            return None
        except IndexError as e:
            return None


    def register_market(self, exchange_id: ExchangeId, symbol: str):
        if symbol not in self.candles[exchange_id]['1s']:
            for interval in VALID_INTERVALS:
                self.candles[exchange_id][interval][symbol] = []
        if symbol not in self.trades[exchange_id]:
            self.trades[exchange_id][symbol] = []
        if symbol not in self.whales[exchange_id]:
            self.whales[exchange_id][symbol] = {}


    def build_second_candle(self, exchange_id: ExchangeId, symbol: str) -> Candle:
        trades = self.get_trades(exchange_id, symbol)
        first_trade = trades[0]
        last_trade = trades[-1]
        timestamp = first_trade['timestamp'] / 1000
        candle_datetime = datetime.fromtimestamp(timestamp).replace(microsecond=0)
        t_open = first_trade['price']
        t_highest = max([trade['price'] for trade in trades])
        t_lowest = min([trade['price'] for trade in trades])
        t_closing = last_trade['price']
        t_volume = 0
        for trade in trades:
            t_volume += trade['amount']
        return Candle(exchange_id, symbol, candle_datetime, '1s', t_open, t_highest, t_lowest, t_closing, t_volume)

        
    def build_upper_candle_from_cache(self, exchange_id: ExchangeId, symbol: str, interval_from: Interval) -> Candle:
        interval_to = get_upper_interval(interval_from)
        last_candle = self.last_cached_candle(exchange_id, symbol, interval_from)
        since = last_candle.convert_datetime(interval_to).timestamp()
        candles = self.get_candles(exchange_id, symbol, interval_from, since)
        new_candle = downsample_candles(candles)
        return new_candle


    def cache_candle(self, exchange_id: ExchangeId, symbol: str):
        new_candle = self.build_second_candle(exchange_id, symbol)
        last_candle: Candle
        for interval in VALID_INTERVALS[:-1]:
            last_candle = self.last_cached_candle(exchange_id, symbol, interval)
            self.add_candle(new_candle)
            if last_candle is None:
                return
            upper_interval = get_upper_interval(interval)
            if not last_candle.is_time_changed(new_candle, upper_interval):
                return
            new_candle = self.build_upper_candle_from_cache(exchange_id, symbol, interval)


    def cache_trade(self, trade: Trade, exchange_id: ExchangeId):
        symbol = trade['symbol'].split(':')[0]
        trade_datetime = datetime.fromtimestamp(trade['timestamp'] / 1000)
        trades = self.get_trades(exchange_id, symbol)
        try:
            last_cached_trade = trades[-1]
        except IndexError as e:
            pass
        else:
            last_cache_datetime = datetime.fromtimestamp(last_cached_trade['timestamp'] / 1000)
            if trade_datetime.second != last_cache_datetime.second:
                self.cache_candle(exchange_id, symbol)
                self.clear_trade(exchange_id, symbol)
        finally:
            self.add_trade(exchange_id, symbol, trade)


    def cache_whales(self, whales: Whale, exchange_id: ExchangeId, symbol: str, alarm_id: int):
        self.whales[exchange_id][symbol][alarm_id] = whales