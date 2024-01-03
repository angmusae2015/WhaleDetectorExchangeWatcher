import asyncio
import time
from datetime import datetime, timedelta
from typing import List, Dict, TypedDict

import ccxt.pro as ccxt
from ccxt.base.types import Trade, OrderBook
from telebot.async_telebot import AsyncTeleBot

from database import Database

from .types import *
from cache import Cache
import functions


def get_exchange_name(exchange_id: int):
    return EXCHANGE_NAMES[exchange_id]


class TickInfo(TypedDict):
    is_condition_none: bool
    is_breakout: bool
    trade: Trade
    condition: TickCondition


class RsiInfo(TypedDict):
    is_condition_none: bool
    is_breakout: bool
    rsi: float
    trade: Trade
    condition: RsiCondition


class BollingerBandInfo(TypedDict):
    is_condition_none: bool
    is_over_upper_band: bool
    is_under_lower_band: bool
    is_breakout: bool
    upper_band: float
    lower_band: float
    trade: Trade
    condition: BollingerBandCondition


class Watcher:
    registered_alarms: Dict[AlarmId, Alarm] = {}
    # 전 사이클의 호가 정보를 저장하는 딕셔너리
    # 발견한 고래가 전과 중복되는 고래인지 확인하기 위함
    order_book_limit = 20


    def __init__(self, database: Database, bot: AsyncTeleBot):
        self.database = database
        self.bot = bot
        self.upbit = ccxt.upbit()
        self.binance = ccxt.binance()
        self.loop = asyncio.get_event_loop()
        self.cache = Cache()
        self.upbit.enableRateLimit = True
        self.binance.enableRateLimit = True


    def get_exchange(self, exchange_id: int):
        exchange = [self.upbit, self.binance][exchange_id - 1]
        return exchange


    def is_alarm_registered(self, alarm_id: int) -> bool:
        return alarm_id in self.registered_alarms


    def get_registered_markets(self) -> Dict[ExchangeId, List[Symbol]]:
        registered_markets = {
            UPBIT_ID: [],
            BINANCE_ID: []
        }
        for alarm in self.registered_alarms.values():
            exchange_id = alarm.exchange_id
            symbol = alarm.symbol
            registered_markets[exchange_id].append(symbol)
        return registered_markets


    # 데이터베이스의 condition 테이블에서 condition_id로 조회한 조건 정보를 Condition 객체로 리턴하는 함수
    def _load_condition(self, condition_id: int) -> Condition:
        result_set = self.database.select(table_name='condition', condition_id=condition_id)
        condition_dict = result_set[condition_id]
        return Condition(**condition_dict)


    # 데이터베이스의 alarm 테이블에서 조회한 각 알람 정보를 Alarm 객체로 리턴하는 함수
    def _row_to_alarm(self, alarm_dict: dict) -> Alarm:
        condition_id = alarm_dict['condition_id']
        condition = self._load_condition(condition_id)
        alarm_dict.pop('condition_id')
        return Alarm(condition=condition, **alarm_dict)

    
    def _load_enabled_alarms(self) -> List[Alarm]:
        columns = ['alarm_id', 'channel_id', 'exchange_id', 'base_symbol', 'quote_symbol', 'condition_id']
        result_set = self.database.select(table_name='alarm', columns=columns, is_enabled=True)
        alarms = [self._row_to_alarm(alarm_dict) for alarm_dict in result_set.values()]
        return alarms


    async def register_alarms(self):
        enabled_alarms = self._load_enabled_alarms()

        def is_alarm_unregistered(alarm_id):
            if [alarm for alarm in enabled_alarms if alarm.id == alarm_id]:
                return False
            else:
                return True

        new_alarms = [alarm for alarm in enabled_alarms if alarm.id not in self.registered_alarms]
        unregistered_alarm_ids = [alarm_id for alarm_id in self.registered_alarms if is_alarm_unregistered(alarm_id)]
        for alarm in new_alarms:
            exchange_id = alarm.exchange_id
            symbol = alarm.symbol
            await self.register_market(exchange_id, symbol)
            self.registered_alarms[alarm.id] = alarm
        for alarm_id in unregistered_alarm_ids:
            self.registered_alarms.pop(alarm_id)
        # 5초마다 반복
        await asyncio.sleep(5)
        await self.register_alarms()


    async def register_market(self, exchange_id: int, symbol: str):
        if symbol in self.get_registered_markets()[exchange_id]:
            return
        self.cache.register_market(exchange_id, symbol)
        exchange = self.get_exchange(exchange_id)
        for interval in ['1m', '1h', '1d']:
            ohlcvs = await exchange.fetch_ohlcv(symbol=symbol, timeframe=interval, limit=100)
            for ohlcv in ohlcvs:
                candle_datetime = datetime.fromtimestamp(ohlcv[0] / 1000)
                candle = Candle(
                    exchange_id=exchange_id,
                    symbol=symbol,
                    datetime=candle_datetime,
                    interval=interval,
                    open=ohlcv[1],
                    highest=ohlcv[2],
                    lowest=ohlcv[3],
                    closing=ohlcv[4],
                    volume=ohlcv[5]
                )
                self.cache.add_candle(candle)
        trade_watching_task = self.create_trade_watching_task(exchange_id, symbol)
        order_book_watching_task = self.create_order_book_watching_task(exchange_id, symbol)
        self.loop.create_task(trade_watching_task())
        self.loop.create_task(order_book_watching_task())
        # debug
        print("task created!")


    # 거래의 체결량을 감시하는 함수
    def check_tick(self, alarm: Alarm, trade: Trade) -> TickInfo:
        tick_info: TickInfo = {
            'is_condition_none': None,
            'is_breakout': None,
            'trade': trade,
            'condition': tick_condition
        }
        tick_condition = alarm.condition.tick
        if tick_condition is None:
            tick_info['is_condition_none'] = True
            return tick_info
        quantity = tick_condition['quantity']
        tick_info['is_condition_none'] = False
        tick_info['is_breakout'] = trade['amount'] >= quantity
        return tick_info


    # RSI 지표를 확인하는 함수
    def check_rsi(self, alarm: Alarm, trade: Trade) -> RsiInfo:
        rsi_info: RsiInfo = {
            'is_condition_none': None,
            'is_breakout': None,
            'rsi': None,
            'trade': trade,
            'condition': tick_condition
        }
        rsi_condition = alarm.condition.rsi
        if rsi_condition is None:
            rsi_info['is_condition_none'] = True
            return rsi_info
        exchange_id = alarm.exchange_id
        symbol = alarm.symbol
        interval = rsi_condition['interval']
        candles = self.cache.get_candles(exchange_id, symbol, interval)
        price_list = [candle.closing for candle in candles]
        price_list.append(trade['price'])
        rsi_value = functions.rsi(price_list, rsi_condition['length'])
        min_value = rsi_condition['min_value']
        max_value = rsi_condition['max_value']
        has_met_condition = min_value >= rsi_value or max_value <= rsi_value;;;;;
        is_overbought = max_value <= rsi_value if has_met_condition else None
        return (has_met_condition, rsi_value, is_overbought)

    
    # 볼린저 밴드 지표를 확인하는 함수
    # 리턴 값은 (돌파 여부, 저항선(상단선) 돌파 여부)
    # 지정된 조건이 없을 경우 (True, None) 리턴
    # 조건에 부합하지 않은 경우 저항선(상단선) 돌파 여부는 None 리턴
    def check_bollinger_band(self, alarm: Alarm, trade: Trade) -> tuple:
        bollinger_band_condition = alarm.condition.bollinger_band
        if bollinger_band_condition is None:
            return (True, None)
        exchange_id = alarm.exchange_id
        interval = bollinger_band_condition['interval']
        symbol = alarm.symbol
        candles = self.cache.get_candles(exchange_id, symbol, interval)
        price_list = [candle.closing for candle in candles]
        price_list.append(trade['price'])
        basis_band, upper_band, lower_band = functions.bollinger_band(price_list, bollinger_band_condition['coefficient'])
        is_breakout = lower_band >= trade['price'] or upper_band <= trade['price']
        is_over_upper_band = upper_band <= trade['price'] if is_breakout else None
        return (is_breakout, is_over_upper_band)


    def check_alarm(self, alarm: Alarm, trade: Trade) -> tuple:
        tick_info = self.check_tick(alarm, trade)
        bollinger_band_info = self.check_bollinger_band(alarm, trade)
        rsi_info = self.check_rsi(alarm, trade)
        # debug
        # if alarm.id == 16:
        #     print(f"알람 ID: {alarm.id} 종목: {alarm.symbol} 거래 ID: {trade['id']}")
        return tick_info, bollinger_band_info, rsi_info

    
    async def send_alarm(self, alarm: Alarm, trade: Trade):
        tick_info, bollinger_band_info, rsi_info = self.check_alarm(alarm, trade)
        if not (tick_info and bollinger_band_info[0] and rsi_info[0]):
            return
        exchange_id = alarm.exchange_id
        exchange_name = get_exchange_name(exchange_id)
        symbol = alarm.symbol
        msg = f"{exchange_name} {symbol} 조건 돌파!\n"
        base_symbol = alarm.base_symbol
        quote_symbol = alarm.quote_symbol
        price = trade['price']
        amount = trade['amount']
        cost = trade['cost']
        msg += f"가격: {price} {quote_symbol}\n거래량: {amount} {base_symbol}\n총 체결 금액: {cost} {quote_symbol}\n"
        is_over_upper_band = bollinger_band_info[1]
        if is_over_upper_band is not None:
            breaked_band = "저항선" if is_over_upper_band else "지지선"
            msg += f"볼린저밴드 {breaked_band} 돌파: "


    def create_trade_watching_task(self, exchange_id: int, symbol: str):
        exchange = self.get_exchange(exchange_id)
        async def task():
            while True:
                registered_markets = self.get_registered_markets()
                if symbol not in registered_markets[exchange_id]:
                    break
                trades: List[Trade] = await exchange.watch_trades(symbol)
                alarms = [
                    alarm for alarm in self.registered_alarms.values()
                    if alarm.exchange_id == exchange_id
                    and alarm.symbol == symbol
                ]
                for trade in trades:
                    for alarm in alarms:
                        self.check_alarm(alarm, trade)
                    self.cache.cache_trade(trade, exchange_id)
        return task

    
    # 고래 호가를 찾는 함수
    # 반환하는 딕셔너리는 매수 호가(bids), 매도 호가(asks) 두 가지 키가 있음
    def find_whale(self, alarm: Alarm, order_book: OrderBook) -> dict:
        whale_condition = alarm.condition.whale
        if whale_condition is None:
            return None
        exchange_id = alarm.exchange_id
        symbol = alarm.symbol
        # 호가 리스트에서 고래 필터링
        quantity = whale_condition['quantity']
        whales = functions.filter_whale(order_book, quantity)
        deduplicated_whales = {'bids': [], 'asks': []}
        cached_whales = self.cache.get_whales(exchange_id, symbol, alarm.id)
        for order_type in ['bids', 'asks']:
            cached_whale_prices = [unit[0] for unit in cached_whales[order_type]]
            for unit in whales[order_type]:
                price = unit[0]
                if price not in cached_whale_prices:
                    deduplicated_whales[order_type].append(unit)
        self.cache.cache_whales(whales, exchange_id, symbol, alarm.id)
        return deduplicated_whales


    def create_order_book_watching_task(self, exchange_id: int, symbol: str):
        exchange = self.get_exchange(exchange_id)
        async def task():
            while True:
                registered_markets = self.get_registered_markets()
                if symbol not in registered_markets[exchange_id]:
                    break
                order_book = await exchange.watch_order_book(symbol, self.order_book_limit)
                alarms = [
                    alarm for alarm in self.registered_alarms.values()
                    if alarm.exchange_id == exchange_id
                    and alarm.symbol == symbol
                ]
                for alarm in alarms:
                    whales = self.find_whale(alarm, order_book)
        return task