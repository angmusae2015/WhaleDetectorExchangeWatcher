import asyncio
import ccxt
from typing import List

from database import Database


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
                'period': bollinger_band['period'],
                'standard_deviation': bollinger_band['standard_deviation']
            }

        if rsi != None:
            self.rsi = {
                'period': rsi['period'],
                'quantity': rsi['quantity']
            }


class Alarm:
    def __init__(self, alarm_id: int, channel_id: int, base_symbol: str, quote_symbol: str, condition: Condition):
        self.id = alarm_id
        self.channel_id = channel_id
        self.base_symbol = base_symbol
        self.quote_symbol = quote_symbol
        self.condition = condition


class Watcher:
    enabled_upbit_alarm_list = []
    enabled_binance_alarm_list = []


    def __init__(self, database: Database):
        self.database = database

        self.upbit = ccxt.upbit()
        self.binance = ccxt.binance()

        self.upbit.enableRateLimit = True
        self.binance.enableRateLimit = True


    def load_enabled_alarms(self):
        def row_to_alarm(alarm_dict: dict):
            condition_id = alarm_dict['condition_id']
            condition = self.load_condition(condition_id)

            alarm_dict.pop('condition_id')

            return Alarm(condition=condition, **alarm_dict)

        column_list = ['alarm_id', 'channel_id', 'base_symbol', 'quote_symbol', 'condition_id']

        # 업비트 알림을 불러옴
        result_set = self.database.select(table_name='alarm', columns=column_list, exchange_id=1, is_enabled=True)
        self.enabled_upbit_alarm_list = [
            row_to_alarm(alarm_dict) for alarm_dict in result_set.values()
        ]

        # 바이낸스 알림을 불러옴
        result_set = self.database.select(table_name='alarm', columns=column_list, exchange_id=2, is_enabled=True)
        self.enabled_binance_alarm_list = [
            row_to_alarm(alarm_dict) for alarm_dict in result_set.values()
        ]


    def load_condition(self, condition_id: int):
        result_set = self.database.select(table_name='condition', condition_id=condition_id)
        condition_dict = result_set[condition_id]

        return Condition(**condition_dict)




