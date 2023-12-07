import asyncio
import ccxt
import time
from typing import List

from database import Database

import functions


class Condition:
    whale = None
    tick = None
    bollinger_band = None
    rsi = None

    def __init__(self, condition_id: int, whale: dict, tick: dict, bollinger_band: dict, rsi: dict):
        self.id = id
        if whale != None:
            self.whale = {
                'quantity': whale['quantity']
            }

        if tick != None:
            self.tick = {
                'quantity': tick['quantity']
            }

        if bollinger_band != None:
            self.bollinger_band = {
                'length': bollinger_band['length'],
                'interval': bollinger_band['interval'],
                'coefficient': bollinger_band['coefficient']
            }

        if rsi != None:
            self.rsi = {
                'length': rsi['length'],
                'interval': rsi['interval'],
                'max_value': rsi['max_value'],
                'min_value': rsi['min_value']
            }


class Alarm:
    def __init__(self, alarm_id: int, channel_id: int, exchange_id: int, base_symbol: str, quote_symbol: str, condition: Condition):
        self.id = alarm_id
        self.channel_id = channel_id
        self.exchange_id = exchange_id  # 업비트: 1, 바이낸스: 2
        self.base_symbol = base_symbol
        self.quote_symbol = quote_symbol
        self.symbol = f"{base_symbol}/{quote_symbol}"
        self.condition = condition


class Candle:
    def __init__(self, exchange_id: int, symbol: str, timestamp: int, interval: str, open: float, highest: float, lowest: float, closing: float, volume: float):
        self.exchange_id = exchange_id
        self.symbol = symbol
        self.timestamp = timestamp
        self.interval = interval
        self.open = open
        self.highest = highest
        self.lowest = lowest
        self.closing = closing
        self.volume = volume


UPBIT_ID = 1
BINANCE_ID = 2
INTERVAL_SECOND_DICT = {
    '1s': 1,
    '1m': 60,
    '1h': 3600,
    '1d': 86400
}

class Watcher:
    enabled_alarm_dict = {}

    # 한 알람 사이클을 돌면서 확인한 종목 주가 정보를 캐싱한 딕셔너리
    # 같은 종목의 다른 알림이 있을 경우 효율적으로 주가 정보를 확인하기 위해 캐싱
    # 각 거래소 ID 키에 해당하는 종목 주가 정보들의 딕셔너리가 저장됨
    # 각 주가 정보는 symbol을 키로 하고 아래 구조를 따름
    """ 
    {
        symbol: {
            order_book: {},
            tick: {},
            ohlcv: []
        },
        ...
    }
    """
    cache = {
        UPBIT_ID: {},
        BINANCE_ID: {}
    }

    candle_cache: List[Candle] = []

    # 전 사이클의 호가 정보를 저장하는 딕셔너리
    # 발견한 고래가 전과 중복되는 고래인지 확인하기 위함
    order_book_before = {
        UPBIT_ID: {},
        BINANCE_ID: {}
    }

    CYCLE_MILLISECOND = 5000


    def __init__(self, database: Database):
        self.database = database

        self.upbit = ccxt.upbit()
        self.binance = ccxt.binance()

        self.upbit.enableRateLimit = True
        self.binance.enableRateLimit = True


    async def load_enabled_alarms(self):
        # 데이터베이스의 condition 테이블에서 condition_id로 조회한 조건 정보를 Condition 객체로 리턴하는 함수
        # row_to_alarm 함수에서 조건 정보를 불러오기 위해 선언함
        def load_condition(condition_id: int) -> Condition:
            result_set = self.database.select(table_name='condition', condition_id=condition_id)
            condition_dict = result_set[condition_id]

            return Condition(**condition_dict)

        # 데이터베이스의 alarm 테이블에서 조회한 각 알람 정보를 Alarm 객체로 리턴하는 함수
        def row_to_alarm(alarm_dict: dict):
            condition_id = alarm_dict['condition_id']
            condition = load_condition(condition_id)

            # condition은 불러왔으므로 Alarm 객체 선언 시 전달할 파라미터에서 condition_id는 제외
            alarm_dict.pop('condition_id')

            return Alarm(condition=condition, **alarm_dict)

        column_list = ['alarm_id', 'channel_id', 'exchange_id', 'base_symbol', 'quote_symbol', 'condition_id']

        result_set = self.database.select(table_name='alarm', columns=column_list, is_enabled=True)
        selected_alarm_dict = {
            alarm_dict['alarm_id']: row_to_alarm(alarm_dict) for alarm_dict in result_set.values()
        }

        # 데이터베이스에서 조회한 알람이 캐시되지 않은 새로운 알람일 경우 알람 캐시 딕셔너리에 추가
        for alarm_id in selected_alarm_dict:
            if alarm_id not in self.enabled_alarm_dict:
                self.enabled_alarm_dict[alarm_id] = selected_alarm_dict[alarm_id]

                # 필요한 과거의 캔들 데이터를 캐시
                await self.cache_past_candle(selected_alarm_dict[alarm_id])

        # 캐시된 알람이 데이터베이스에서 조회되지 않았을 경우 알람 캐시 딕셔너리에서 삭제
        for alarm_id in self.enabled_alarm_dict.copy():
            if alarm_id not in selected_alarm_dict:
                self.enabled_alarm_dict.pop(alarm_id)


    # 알람 조건을 최초로 감시하기 위해 필요한 과거의 캔들 데이터를 캐시하는 함수
    async def cache_past_candle(self, alarm: Alarm):
        exchange = [self.upbit, self.binance][alarm.exchange_id - 1]

        fetched_candle_list_cache = []
        
        for condition_dict in [alarm.condition.bollinger_band, alarm.condition.rsi]:
            # 해당 조건이 설정되어 있지 않으면 다음 조건으로 넘어감
            if condition_dict == None:
                continue

            # 메모리 캐시에서 조건에 맞는 캔들 데이터를 조회
            cached_candle_list = [
                candle for candle in self.candle_cache
                if candle.exchange_id == alarm.exchange_id 
                and candle.symbol == alarm.symbol
                and candle.interval == condition_dict['interval']
            ]

            # 이미 같은 조건의 캔들을 조회했다면 다음 조건으로 넘어감
            if condition_dict['interval'] in fetched_candle_list_cache:
                continue
            
            fetched_candle_list = exchange.fetch_ohlcv(symbol=alarm.symbol, timeframe=condition_dict['interval'], limit=100)
            # 요청한 캔들 중 실시간 데이터인 마지막 캔들을 제외한 나머지 캔들을 돌면서 해당 캔들의 타임스탬프의 캔들이 캐시된 캔들인지 확인
            for fetched_candle in fetched_candle_list[:-1]:
                if [candle for candle in cached_candle_list if candle.timestamp * 1000 == fetched_candle[0]]:
                    continue

                # 해당 타임스탬프의 캔들이 캐시되어 있지 않은 경우 Candle 객체로 캐시
                self.candle_cache.append(Candle(
                    exchange_id=alarm.exchange_id,
                    symbol=alarm.symbol,
                    timestamp=int(fetched_candle[0] / 1000),    # 밀리초 단위의 타임스탬프를 초 단위로 환산하여 캐시
                    interval=condition_dict['interval'],
                    open=fetched_candle[1],
                    highest=fetched_candle[2],
                    lowest=fetched_candle[3],
                    closing=fetched_candle[4],
                    volume=fetched_candle[5]
                ))

            fetched_candle_list_cache.append(condition_dict['interval'])


    # 고래 호가를 찾는 함수
    # 반환하는 딕셔너리는 매수 호가(bids), 매도 호가(asks) 두 가지 키가 있음
    def find_whale(self, alarm: Alarm) -> dict:
        whale_dict = {'bids': [], 'asks': []}

        if alarm.condition.whale == None:
            return whale_dict

        order_book = self.cache[alarm.exchange_id][alarm.symbol]['order_book']

        # 호가 리스트에서 고래 필터링
        quantity = alarm.condition.whale['quantity']
        whale_dict = functions.filter_whale(order_book, quantity)

        # 이전 사이클의 호가 정보가 있는지 확인
        if alarm.symbol in self.order_book_before[alarm.exchange_id].keys():   
            order_book_before = self.order_book_before[alarm.exchange_id][alarm.symbol]

            # 이전 호가 정보가 있을 경우 이전 정보와 비교하여 새로운 고래만 저장
            whale_dict = functions.verify_new_whale(order_book_before, whale_dict, quantity)

        return whale_dict


    # 거래의 체결량을 감시하는 함수
    # 조건 이상의 체결량의 거래 리스트를 리턴
    def check_tick(self, alarm: Alarm) -> list:
        if alarm.condition.tick == None:
            return []

        tick_list = self.cache[alarm.exchange_id][alarm.symbol]['tick']

        # 거래 정보 리스트에서 조건에 맞는 거래만 필터링하여 리턴
        quantity = alarm.condition.tick['quantity']
        return [tick for tick in tick_list if tick['amount'] >= quantity]


    # RSI 지표를 확인하는 함수
    # 리턴 값은 (조건 부합 여부, RSI 값, 과매수(True)/과매도(False) 여부)
    # 지정된 조건이 없을 경우 (True, None, None) 리턴
    # 조건에 부합하지 않은 경우 과매수/과매도 여부는 None 리턴
    async def check_rsi(self, alarm: Alarm, recent_trade_dict: dict) -> tuple:
        if alarm.condition.rsi == None:
            return (True, None, None)

        length = alarm.condition.rsi['length']
        interval = alarm.condition.rsi['interval']

        candle_cache = [
            candle for candle in self.candle_cache
            if candle.exchange_id == alarm.exchange_id
            and candle.symbol == alarm.symbol
            and candle.interval == interval
        ][-99:]

        price_list = [candle.closing for candle in candle_cache].append(recent_trade_dict['price'])

        rsi_value = functions.rsi(price_list, length)
        max_value = alarm.condition.rsi['max_value']
        min_value = alarm.condition.rsi['min_value']

        has_met_condition = min_value >= rsi_value or max_value <= rsi_value
        is_overbought = max_value <= rsi_value if has_met_condition else None

        return (has_met_condition, rsi_value, is_overbought)

    
    # 볼린저 밴드 지표를 확인하는 함수
    # 리턴 값은 (조건 부합 여부, 과매수(True)/과매도(False) 여부)
    # 지정된 조건이 없을 경우 (True, None) 리턴
    # 조건에 부합하지 않은 경우 과매수/과매도 여부는 None 리턴
    def check_bollinger_band(self, alarm: Alarm, recent_trade_dict: dict) -> tuple:
        if alarm.condition.bollinger_band == None:
            return (True, None)
        
        length = alarm.condition.bollinger_band['length']
        interval = alarm.condition.bollinger_band['interval']

        candle_cache = [
            candle for candle in self.candle_cache
            if candle.exchange_id == alarm.exchange_id
            and candle.symbol == alarm.symbol
            and candle.interval == interval
        ][-99:]

        price_list = [candle.closing for candle in candle_cache].append(recent_trade_dict['price'])
        coefficient = alarm.condition.bollinger_band['coefficient']
        basis_band, upper_band, lower_band = functions.bollinger_band(price_list, coefficient)

        current_price = price_list[-1]
        has_met_condition = lower_band >= current_price or upper_band <= current_price
        is_overbought = upper_band <= current_price if has_met_condition else None

        return (has_met_condition, is_overbought)


    def save_to_order_book_before(self):
        for exchange_id in self.cache:
            for symbol in self.cache[exchange_id]:
                self.order_book_before[exchange_id][symbol] = self.cache[exchange_id][symbol]['order_book']


    async def check_alarm(self, alarm: Alarm):
        exchange = [self.upbit, self.binance][alarm.exchange_id - 1]
        while True:
            trade = (await exchange.watch_trades(alarm.symbol))[0]

            for alarm in alarm_list:
                # whale_dict = self.find_whale(alarm)
                # tick_list = self.check_tick(alarm)
                bollinger_band_info = self.check_bollinger_band(alarm, trade)
                rsi_info = self.check_rsi(alarm, trade)

                # 테스트용 코드
                # print('whale: ', whale_dict)
                # print('tick: ', tick_list)
                print('bollinger_band: ', bollinger_band_info)
                print('rsi: ', rsi_info)