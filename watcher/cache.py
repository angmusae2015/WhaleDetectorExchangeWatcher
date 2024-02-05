import asyncio
from datetime import datetime
from typing import List, Dict, TypedDict

from ccxt.base.types import Trade, OrderBook

from watcher.definition import UPBIT_ID, BINANCE_ID
from watcher.definition import Interval, Candle


class Cache:
    def __init__(self):
        self.candles = {
            UPBIT_ID: {},
            BINANCE_ID: {}
        }

        self.order_books = {
            UPBIT_ID: {},
            BINANCE_ID: {}
        }

    # 캐시 공간 확보
    def create_cache_storage(self, exchange_id: int, symbol: str, interval: Interval):
        candle_storage_for_exchange = self.candles[exchange_id]     # 거래소에 대한 캔들 저장소
        # 해당 종목에 대한 공간이 확보되어 있지 않을 경우 공간 확보
        if symbol not in candle_storage_for_exchange:
            candle_storage_for_exchange[symbol] = {}

        candle_storage_for_symbol = candle_storage_for_exchange[symbol]     # 종목에 대한 캔들 저장소
        # 해당 인터벌에 대한 공간이 확보되어 있지 않을 경우 공간 확보
        if interval not in candle_storage_for_symbol:
            candle_storage_for_symbol[interval] = []

        order_book_storage_for_exchange = self.order_books[exchange_id]
        if symbol not in order_book_storage_for_exchange:
            order_book_storage_for_exchange[symbol] = {}

    # 호가 정보를 캐시함
    def cache_order_book(self, order_book: OrderBook, exchange_id: int, symbol: str):
        storage = self.order_books[exchange_id]
        storage[symbol] = order_book

    # 캔들에 거래를 캐시함
    def cache_trade(self, trade: Trade, exchange_id: int):
        symbol: str = trade['symbol'].split(':')[0]
        # 마이크로초 단위로 주어진 타임스탬프를 초 단위 타임스탬프로 변환
        trade_timestamp: int = int(trade['timestamp'] / 1000)
        candle_cache: Dict[Interval, List[Candle]] = self.candles[exchange_id][symbol]
        intervals: List[Interval] = list(candle_cache.keys())

        for interval in intervals:
            if len(candle_cache[interval]) == 0:
                continue
            candle: Candle = candle_cache[interval][-1]
            candle.add_trade(trade)

    # 해당 조건에 부합하는 캔들 리스트를 불러옴
    def get_candles(self, exchange_id: int, symbol: str, interval: Interval, since: int = None,
                    limit: int = None) -> List[Candle]:
        if symbol not in self.candles[exchange_id]:
            return []

        if interval not in self.candles[exchange_id][symbol]:
            return []

        candles = self.candles[exchange_id][symbol][interval]
        if since is not None:
            candles = [candle for candle in candles if candle.datetime.timestamp() >= since]
        if limit is not None:
            candles = [candle for candle in candles if candle.datetime.timestamp() < limit]
        return candles

    # 이미 캔들이 존재하는지 여부를 반환함
    def is_candle_exists(self, candle: Candle):
        exchange_id = candle.exchange_id
        symbol = candle.symbol
        interval = candle.interval
        # 같은 조건(거래소, 종목, 인터벌)의 캔들 리스트를 불러옴
        candles = self.get_candles(exchange_id, symbol, interval)
        # 불러온 캔들들의 타임스탬프 리스트
        timestamps = [_candle.datetime.timestamp() for _candle in candles]
        # 검색하는 캔들의 타임스탬프
        candle_timestamp = candle.datetime.timestamp()
        # 같은 타임스탬프가 리스트에 존재하는지 여부를 반환함
        return candle_timestamp in timestamps

    # 캔들을 리스트에 추가함
    def add_candle(self, candle: Candle):
        exchange_id = candle.exchange_id
        symbol = candle.symbol
        interval = candle.interval
        # 해당 캔들이 존재하는 경우 캔들을 추가하지 않고 리턴
        if self.is_candle_exists(candle):
            return False
        candle_storage: List[Candle] = self.candles[exchange_id][symbol][interval]
        if len(candle_storage) >= 100:
            candle_storage.pop(0)
        candle_storage.append(candle)
        return True

    # 현재 시간에 해당하는 새로운 캔들을 생성해 저장함
    def build_new_candle(self):
        for exchange_id in self.candles:
            symbol_cache = self.candles[exchange_id]
            for symbol in symbol_cache:
                interval_cache: Dict[Interval, List[Candle]] = symbol_cache[symbol]
                for interval in interval_cache:
                    current_datetime: datetime = datetime.now().replace(microsecond=0)
                    current_timestamp: int = int(current_datetime.timestamp())
                    # 현재 타임스탬프가 인터벌의 초 길이로 나누어 떨어지면 새 캔들을 생성
                    if current_timestamp % interval.to_second != 0:
                        continue
                    # 공간 확보를 위해 기록이 끝난 캔들의 거래 정보를 삭제함
                    last_candle = self.get_candles(exchange_id, symbol, interval)[-1]
                    last_candle.clear_trade()
                    # 새 캔들을 생성하고 캐시
                    new_candle = Candle(exchange_id, symbol, current_datetime, interval)
                    self.add_candle(new_candle)

    # 일정 시간마다 시간을 확인하고 새 캔들을 추가하는 태스크를 반환함
    def candle_update_task(self, period: float = 0.01):
        async def task():
            # 마지막으로 확인한 시간의 초
            last_check_second = datetime.now().second
            while True:
                current_second = datetime.now().second
                if last_check_second != current_second:
                    self.build_new_candle()
                last_check_second = current_second
                await asyncio.sleep(period)

        return task

    @staticmethod
    def merge_candle(candles: List[Candle], target_interval: Interval):
        exchange_id = candles[0].exchange_id
        symbol = candles[0].symbol
        _datetime = candles[0].datetime
        new_candle = Candle(exchange_id, symbol, _datetime, target_interval)
        # 주어진 캔들들의 거래를 new_candle의 거래 리스트에 추가함
        for candle in candles:
            new_candle.trades += candle.trades
        return new_candle
