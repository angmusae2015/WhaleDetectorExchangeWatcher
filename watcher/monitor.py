import os
from typing import Dict, List, TYPE_CHECKING

from ccxt.base.types import Trade

from database.database import Database
from database.definition import Condition
from watcher.watcher import Alarm

if TYPE_CHECKING:
    pass


class WatcherMonitor:
    def __init__(self):
        self.alarms: List[Alarm] = []
        self.check_results: Dict[int, dict] = {}

    def add_alarm(self, alarm: Alarm):
        

    def update_monitor(self):
        os.system('clear')
        for alarm in self.alarms:
            # 알람 정보
            alarm_info_message = self.alarm_info_message(alarm)
            # 알람 조건 정보
            condition_info_message = self.condition_info_message(alarm)
            # 거래 검사 결과 정보
            check_result = self.check_results[alarm.id]
            check_result_info_message = self.check_result_info_message(alarm, )

    @staticmethod
    def alarm_info_message(alarm: Alarm) -> str:
        msg = f"\n======== 알람 ID: {alarm.id} ========"
        msg += f"\n거래소: {alarm.exchange_id} | 종목: {alarm.symbol}"
        msg += f"\n채널: {alarm.channel_id}"
        return msg

    @staticmethod
    def condition_info_message(alarm: Alarm) -> str:
        condition = alarm.condition
        whale_condition = condition['whale']
        tick_condition = condition['tick']
        bollinger_band_condition = condition['bollinger_band']
        rsi_condition = condition['rsi']
        msg = "\n-------- 조건 --------"
        if whale_condition is not None:
            msg += f"\n고래: {whale_condition['quantity']:,} {alarm.quote_symbol} 이상"
        if tick_condition is not None:
            msg += f"\n체결량: {tick_condition['quantity']} {alarm.base_symbol} 이상 체결 시"
        if bollinger_band_condition is not None:
            msg += f"\n볼린저 밴드:"
            if bollinger_band_condition['on_over_upper_band']:
                msg += " 상향선"
            if bollinger_band_condition['on_under_lower_band']:
                msg += " 하향선"
        if rsi_condition is not None:
            msg += f"\nRSI: {rsi_condition['upper_bound']} 이상 / {rsi_condition['lower_bound']} 이하"
        return msg

    @staticmethod
    def check_result_info_message(alarm: Alarm, check_result: dict) -> str:
        trade: Trade = check_result['trade']
        trade_datetime = trade['datetime']
        trade_quantity = trade['amount']
        trade_price = trade['price']
        msg = "\n------ 검사 결과 ------"
        msg += f"\n일시: {trade_datetime}"
        msg += f"\n체결량: {trade_quantity} {alarm.base_symbol}"
        msg += f"\n가격: {trade_price} {alarm.quote_symbol}"
        if check_result['whales'] is not None:
            bids = len(check_result['whales']['bids'])
            asks = len(check_result['whales']['asks'])
            msg += f"\n고래: 매수({bids}) | 매도({asks})"
        if check_result['rsi'] is not None:
            rsi = check_result['rsi']
            msg += f"\nRSI: {rsi}"
        if check_result['crossed_band'] is not None:
            crossed_band = check_result['crossed_band']
            msg += f"\n볼린저 밴드: {crossed_band} 돌파"
        return msg
