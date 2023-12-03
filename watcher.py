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


UPBIT_ID = 1
BINANCE_ID = 2

class Watcher:
    enabled_upbit_alarm_list = []
    enabled_binance_alarm_list = []

    # 한 알람 사이클을 돌면서 확인한 종목 주가 정보를 캐싱한 딕셔너리
    # 같은 종목의 다른 알림이 있을 경우 효율적으로 주가 정보를 확인하기 위해 캐싱
    # 각 거래소 ID 키에 해당하는 종목 주가 정보들의 딕셔너리가 저장됨
    # 각 주가 정보는 symbol을 키로 하고 아래 구조를 따름
    """ 
    {
        symbol: {
            order_book: {},
            tick: {}
        },
        ...
    }
    """
    cache = {
        UPBIT_ID: {},
        BINANCE_ID: {}
    }

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


    # 데이터베이스에서 활성화된 알람을 조회해 각 거래소 별로 enabled_upbit_alarm_list/enabled_binance_alarm_list 요소에 Alarm 객체의 리스트로 저장하는 함수
    def load_enabled_alarms(self):
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

        # 업비트 알림을 불러옴
        result_set = self.database.select(table_name='alarm', columns=column_list, exchange_id=UPBIT_ID, is_enabled=True)
        self.enabled_upbit_alarm_list = [
            row_to_alarm(alarm_dict) for alarm_dict in result_set.values()
        ]

        # 바이낸스 알림을 불러옴
        result_set = self.database.select(table_name='alarm', columns=column_list, exchange_id=BINANCE_ID, is_enabled=True)
        self.enabled_binance_alarm_list = [
            row_to_alarm(alarm_dict) for alarm_dict in result_set.values()
        ]


    # 종목 데이터를 요청하고 cache 요소에 캐싱하는 함수
    def cache_market_info(self, alarm: Alarm):
        exchange = [self.upbit, self.binance][alarm.exchange_id - 1]
        symbol = alarm.symbol

        # 이미 해당 종목 데이터가 캐싱되어 있을 경우 함수를 종료
        if symbol in self.cache[alarm.exchange_id]:
            return

        # 호가 정보를 저장하는 딕셔너리
        # 딕셔너리의 구조는 다음 참조: https://docs.ccxt.com/#/?id=order-book
        order_book = exchange.fetch_order_book(symbol)

        # 체결 거래 정보 목록을 저장하는 리스트
        # 리스트 구조는 다음 참조: https://docs.ccxt.com/#/?id=public-trades
        current_timestamp = int(time.time() * 1000)
        tick = exchange.fetch_trades(symbol=symbol, since=current_timestamp - self.CYCLE_MILLISECOND)
        
        # 일 단위 OHCLV 정보를 저장하는 리스트
        # 리스트 구조는 다음 참조: https://docs.ccxt.com/#/?id=ohlcv-structure
        ohclv = exchange.fetch_ohlcv(symbol=symbol, timeframe='1d')

        self.cache[alarm.exchange_id][symbol] = {
            'order_book': order_book,
            'tick': tick,
            'ohclv': {'1d': ohclv}
        }


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
    def check_rsi(self, alarm: Alarm) -> tuple:
        if alarm.condition.rsi == None:
            return (True, None, None)

        length = alarm.condition.rsi['length']
        interval = alarm.condition.rsi['interval']

        # 해당 인터벌에 해당하는 OHCLV 데이터가 캐싱되어 있지 않은 경우 요청 후 캐싱
        if interval not in self.cache[alarm.exchange_id][alarm.symbol]['ohclv']:
            exchange = [self.upbit, self.binance][alarm.exchange_id - 1]
            ohclv_list = exchange.fetch_ohlcv(symbol=alarm.symbol, timeframe=interval)

            self.cache[alarm.exchange_id][alarm.symbol]['ohclv'][interval] = ohclv_list

        ohclv_list = self.cache[alarm.exchange_id][alarm.symbol]['ohclv'][interval]
        closing_price_list = [ohclv[4] for ohclv in ohclv_list]

        rsi_value = functions.rsi(closing_price_list, length)
        max_value = alarm.condition.rsi['max_value']
        min_value = alarm.condition.rsi['min_value']

        has_met_condition = min_value >= rsi_value or max_value <= rsi_value
        is_overbought = max_value <= rsi_value if has_met_condition else None

        return (has_met_condition, rsi_value, is_overbought)

    
    # 볼린저 밴드 지표를 확인하는 함수
    # 리턴 값은 (조건 부합 여부, 과매수(True)/과매도(False) 여부)
    # 지정된 조건이 없을 경우 (True, None) 리턴
    # 조건에 부합하지 않은 경우 과매수/과매도 여부는 None 리턴
    def check_bollinger_band(self, alarm: Alarm) -> tuple:
        if alarm.condition.bollinger_band == None:
            return (True, None)
        
        length = alarm.condition.bollinger_band['length']
        interval = alarm.condition.bollinger_band['interval']

        # 해당 인터벌에 해당하는 OHCLV 데이터가 캐싱되어 있지 않은 경우 요청 후 캐싱
        if interval not in self.cache[alarm.exchange_id][alarm.symbol]['ohclv']:
            exchange = [self.upbit, self.binance][alarm.exchange_id - 1]
            ohclv_list = exchange.fetch_ohlcv(symbol=alarm.symbol, timeframe=interval)

            self.cache[alarm.exchange_id][alarm.symbol]['ohclv'][interval] = ohclv_list

        # 길이만큼의 데이터만 불러옴
        ohclv_list = self.cache[alarm.exchange_id][alarm.symbol]['ohclv'][interval][-length:]
        closing_price_list = [ohclv[4] for ohclv in ohclv_list]

        coefficient = alarm.condition.bollinger_band['coefficient']
        basis_band, upper_band, lower_band = functions.bollinger_band(closing_price_list, coefficient)

        current_price = closing_price_list[-1]
        has_met_condition = lower_band >= current_price or upper_band <= current_price
        is_overbought = upper_band <= current_price if has_met_condition else None

        return (has_met_condition, is_overbought)


    def clear_cache(self):
        self.cache = {1: {}, 2: {}}


    def save_to_order_book_before(self):
        for exchange_id in self.cache:
            for symbol in self.cache[exchange_id]:
                self.order_book_before[exchange_id][symbol] = self.cache[exchange_id][symbol]['order_book']


    def alarm_check_cycle(self):
        self.load_enabled_alarms()

        for alarm_list in [self.enabled_upbit_alarm_list, self.enabled_binance_alarm_list]:
            for alarm in alarm_list:
                start = time.time()
                self.cache_market_info(alarm)
                print(f'Market info loaded: {time.time() - start}')

                whale_dict = self.find_whale(alarm)
                tick_list = self.check_tick(alarm)
                bollinger_band_info = self.check_bollinger_band(alarm)
                rsi_info = self.check_rsi(alarm)

                # 테스트용 코드
                print('whale: ', whale_dict)
                print('tick: ', tick_list)
                print('bollinger_band: ', bollinger_band_info)
                print('rsi: ', rsi_info)

        self.save_to_order_book_before()
        self.clear_cache()