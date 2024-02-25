import asyncio
from datetime import datetime
from typing import Dict, List, Optional

import ccxt.pro as ccxt
from ccxt import RequestTimeout
from ccxt.base.types import Trade, OrderBook
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_helper import ApiTelegramException

from database.database import Database
from database.definition import AlarmDict
from database.definition import BollingerBandCondition, Condition
from watcher import functions
from watcher.definition import UPBIT_ID, BINANCE_ID, WhaleInfo
from watcher.definition import Interval, Candle
from watcher.definition import TickInfo, RsiInfo, BollingerBandInfo
from watcher.cache import Cache
from watcher.monitor import Monitor


def get_exchange_name(exchange_id: int):
    exchange_name_dict = {
        UPBIT_ID: '업비트',
        BINANCE_ID: '바이낸스'
    }
    return exchange_name_dict[exchange_id]


class Alarm:
    def __init__(self, alarm: AlarmDict, condition: Condition):
        self.id = alarm['alarm_id']
        self.channel_id = alarm['channel_id']
        self.exchange_id = alarm['exchange_id']  # 업비트: 1, 바이낸스: 2
        self.base_symbol = alarm['base_symbol']
        self.quote_symbol = alarm['quote_symbol']
        self.symbol = f"{self.base_symbol}/{self.quote_symbol}"
        self.condition = condition
        self.alerted_candle_timestamp: int = 0  # 마지막으로 알람을 보낸 캔들의 타임스탬프

    # 조건으로 설정된 인터벌들
    @property
    def intervals_need_to_be_watched(self) -> List[Interval]:
        intervals: List[Interval] = []
        # RSI 조건의 인터벌
        rsi_condition = self.condition['rsi']
        if rsi_condition is not None:
            rsi_interval = Interval(**rsi_condition['interval'])
            if rsi_interval not in intervals:
                intervals.append(rsi_interval)
        # 볼린저밴드 조건의 인터벌
        bollinger_band_condition = self.condition['bollinger_band']
        if bollinger_band_condition is not None:
            bollinger_band_interval = Interval(**bollinger_band_condition['interval'])
            if bollinger_band_interval not in intervals:
                intervals.append(bollinger_band_interval)
        return intervals


class Watcher:
    order_book_limit = 20

    def __init__(self, _database: Database, bot: AsyncTeleBot):
        self.database = _database
        self.bot = bot
        self.loop = asyncio.get_event_loop()
        self.cache = Cache()
        # 활성화된 알람 리스트
        self.registered_alarms: Dict[int, Alarm] = {}
        # self.monitor = Monitor()

    @property
    def registered_markets(self) -> Dict[int, List[str]]:
        registered_market_dict: Dict[int, List[str]] = {
            UPBIT_ID: [],
            BINANCE_ID: []
        }
        registered_alarms: List[Alarm] = list(self.registered_alarms.values())
        for alarm in registered_alarms:
            exchange_id = alarm.exchange_id
            symbol = alarm.symbol
            registered_market_dict[exchange_id].append(symbol)
        return registered_market_dict

    def run(self):
        self.loop.create_task(self.update_registered_alarms())
        self.loop.create_task(self.cache.candle_update_task(period=0.3))
        self.loop.create_task(self.cache_cleaning_task())
        self.loop.run_forever()

    @staticmethod
    def get_exchange(exchange_id: int):
        if exchange_id == 1:
            exchange = ccxt.upbit()
            exchange.timeframes['10m'] = 'minutes'
        elif exchange_id == 2:
            exchange = ccxt.binance()
        else:
            raise ValueError

        exchange.enableRateLimit = True
        return exchange

    def get_alarms(self, exchange_id: int, symbol: str, interval: Optional[Interval] = None) -> List[Alarm]:
        alarms = [
            alarm for alarm in self.registered_alarms.values()
            if alarm.exchange_id == exchange_id
            and alarm.symbol == symbol
        ]
        if interval is not None:
            alarms = [
                alarm for alarm in alarms
                if interval in alarm.intervals_need_to_be_watched
            ]
        return alarms

    def is_alarm_running(self, alarm_id: int) -> bool:
        return alarm_id in self.registered_alarms

    # 데이터베이스의 condition 테이블에서 alarm_id로 조회한 조건 정보를 Condition 객체로 리턴하는 함수
    def load_condition(self, alarm_id: int) -> Condition:
        result_set = self.database.select(table_name='condition', alarm_id=alarm_id)
        condition: Condition = result_set[alarm_id]
        return condition

    # 데이터베이스의 alarm 테이블에서 조회한 각 알람 정보를 Alarm 객체로 리턴하는 함수
    def row_to_alarm(self, alarm_dict: AlarmDict) -> Alarm:
        alarm_id = alarm_dict['alarm_id']
        condition = self.load_condition(alarm_id)
        return Alarm(alarm=alarm_dict, condition=condition)

    def load_enabled_alarms(self) -> List[Alarm]:
        result_set = self.database.select(table_name='alarm', is_enabled=True)
        alarms = [self.row_to_alarm(alarm_row) for alarm_row in result_set.values()]
        return alarms

    async def update_alarm_condition(self, edited_alarm: Alarm):
        alarm = self.registered_alarms[edited_alarm.id]
        exchange_id = alarm.exchange_id
        symbol = alarm.symbol
        if alarm.condition == edited_alarm.condition:
            return
        alarm.condition = edited_alarm.condition.copy()
        # self.monitor.update_alarm(edited_alarm)
        # 캐시 공간 확보
        for interval in edited_alarm.intervals_need_to_be_watched:
            self.cache.create_candle_storage(exchange_id, symbol, interval)
        await self.fetch_pre_data(alarm)

    async def register_alarm(self, alarm: Alarm):
        exchange_id = alarm.exchange_id
        symbol = alarm.symbol
        # 캐시 공간 확보
        for interval in alarm.intervals_need_to_be_watched:
            self.cache.create_candle_storage(exchange_id, symbol, interval)
        self.cache.create_order_book_storage(exchange_id, symbol)
        # 알람 조건 검사에 필요한 캔들 데이터 캐시
        await self.fetch_pre_data(alarm)
        # 이미 해당 종목에 대한 조건 검사 태스크가 실행 중이면 다음 알람으로 넘어감
        if symbol in self.registered_markets[exchange_id]:
            self.registered_alarms[alarm.id] = alarm  # 활성화된 알람 리스트에 알람 등록
            # self.monitor.update_alarm(alarm)
            return
        # 활성화된 알람 리스트에 알람 등록
        self.registered_alarms[alarm.id] = alarm
        # self.monitor.update_alarm(alarm)
        # 해당 종목에 대한 거래 조건 검사 태스크를 이벤트 루프에 등록함
        self.loop.create_task(self.order_book_watching_task(exchange_id, symbol))
        self.loop.create_task(self.trade_watching_task(exchange_id, symbol))

    def unregister_alarm(self, alarm_id: int):
        self.registered_alarms.pop(alarm_id)
        # self.monitor.remove_alarm(alarm_id)

    # 활성화된 알람을 최신화함
    async def update_registered_alarms(self):
        while True:
            enabled_alarms = self.load_enabled_alarms()

            def is_alarm_enabled(alarm_id):
                enabled_alarm_ids = [_alarm.id for _alarm in enabled_alarms]
                return alarm_id in enabled_alarm_ids

            for alarm in enabled_alarms:
                # 이미 등록된 알람일 경우
                if alarm.id in self.registered_alarms:
                    await self.update_alarm_condition(alarm)
                # 등록되지 않은 새로운 알람일 경우 알람 등록
                else:
                    await self.register_alarm(alarm)
            # 비활성화된 알람들의 ID 리스트
            unregistered_alarm_ids = [alarm_id for alarm_id in self.registered_alarms if not is_alarm_enabled(alarm_id)]
            # 등록된 알람 리스트에서 비활성화된 알람 삭제
            for unregistered_alarm_id in unregistered_alarm_ids:
                self.unregister_alarm(unregistered_alarm_id)
            # 5초마다 반복
            await asyncio.sleep(5)

    # 알람을 등록했을 때 조건 검사를 위해서 필요한 과거 데이터를 불러옴
    async def fetch_pre_data(self, alarm: Alarm):
        exchange_id = alarm.exchange_id
        exchange = self.get_exchange(alarm.exchange_id)
        symbol = alarm.symbol

        # 과거의 캔들 데이터를 요청해 캔들 리스트로 반환함
        async def fetch_candles(_interval: Interval, limit: int = 100) -> List[Candle]:
            _candles: List[Candle] = []
            candle_raw_list = await exchange.fetch_ohlcv(symbol=symbol, timeframe=str(_interval), limit=limit)
            for candle_raw in candle_raw_list:
                candle_datetime = datetime.fromtimestamp(candle_raw[0] / 1000)
                _candle = Candle(exchange_id, symbol, candle_datetime, _interval)
                _candle.open, _candle.high, _candle.low, _candle.close = candle_raw[1:5]
                _candles.append(_candle)
            return _candles

        # 캔들 데이터 요청
        intervals = alarm.intervals_need_to_be_watched
        for interval in intervals:
            candles = await fetch_candles(interval)
            added_candles_count = 0
            for candle in candles:
                if self.cache.add_candle(candle):
                    added_candles_count += 1
        # 호가 데이터 요청
        order_books = await exchange.fetch_order_book(symbol, limit=20)
        self.cache.cache_order_book(order_books, exchange_id, symbol)
        # 거래소 연결 종료
        await exchange.close()

    # 거래를 감시하고 조건을 검사한 뒤 알람을 전송하는 태스크
    async def trade_watching_task(self, exchange_id: int, symbol: str):
        def last_candle_timestamp(alarm: Alarm) -> float:
            """
            alarm의 조건(거래소, 종목, 최소 인터벌)에 해당하는 캔들 중 가장 최신의 캔들의 타임스탬프를 반환함
            :param alarm: Alarm, 찾으려는 캔들을 참조하는 알람
            :return: int, 가장 최신의 캔들의 타임스탬프
            """
            shortest_interval = min(alarm.intervals_need_to_be_watched)  # 알람의 조건의 인터벌 중 가장 짧은 인터벌
            last_candle = self.cache.get_candles(exchange_id, symbol,  # 마지막으로 거래를 캐시한 캔들
                                                 shortest_interval)[-1]  # 캔들의 인터벌은 알람의 조건의 인터벌 중 가장 짧은 인터벌
            timestamp = last_candle.datetime.timestamp()  # 마지막으로 거래를 캐시한 캔들의 타임스탬프
            return timestamp

        def is_alarm_alerted(alarm: Alarm) -> bool:
            """
            alarm이 현재 캔들에서 알림이 이미 전송되었는지 여부를 반환함
            :param alarm: Alarm, 알림 전송 여부를 확인할 알람
            :return: bool, 알림 전송 여부
            """
            last_alerted_candle_timestamp = alarm.alerted_candle_timestamp  # 알람이 마지막으로 전송된 캔들의 타임스탬프
            return last_alerted_candle_timestamp == last_candle_timestamp(alarm)

        exchange = self.get_exchange(exchange_id)
        # 거래 감시
        while True:
            # 감시해야 하는 종목 리스트
            registered_markets = self.registered_markets
            # 감시해야 하는 종목 리스트에 해당 종목이 더 이상 존재하지 않을 경우 태스크 종료
            if symbol not in registered_markets[exchange_id]:
                # 해당 종목의 캔들 캐시 삭제
                self.cache.candles[exchange_id].pop(symbol)
                await exchange.close()
                break
            # 거래 리스트 요청
            try:
                trades: List[Trade] = await exchange.watch_trades(symbol)
            except RequestTimeout:
                # 거래소 연결 종료 후 재연결
                await exchange.close()
                exchange = self.get_exchange(exchange_id)
                continue
            # 해당 종목에 대한 알람 리스트
            alarms = [
                alarm for alarm in self.registered_alarms.values()
                if alarm.exchange_id == exchange_id
                and alarm.symbol == symbol
            ]
            # 각 거래마다 알람 조건에 부합하는지 확인 후 조건에 맞을 시 알람을 전송함
            for trade in trades:
                # 거래를 캔들에 캐시함
                self.cache.cache_trade(trade, exchange_id)
                for alarm in alarms:
                    # 알람에 캔들을 조회해야 하는 조건이 존재하고 이미 알림이 전송된 알람이라면 다음 알람으로 진행
                    try:
                        if alarm.intervals_need_to_be_watched and is_alarm_alerted(alarm):
                            continue
                    except IndexError:
                        pass
                    # 알람 조건 확인 결과
                    try:
                        check_result = self.check_alarm(alarm, trade)
                    except IndexError:
                        continue
                    is_alarm_triggered = check_result['is_alarm_triggered']
                    # 알람 모니터에 조건 업데이트
                    # self.monitor.update_check_result(alarm.id, check_result)
                    # 거래가 알람 조건에 맞지 않으면 다음 알람으로 진행
                    if not is_alarm_triggered:
                        continue
                    # 조건에 맞을 경우 알람 전송
                    try:
                        await self.send_alarm(alarm, check_result)
                    except ApiTelegramException:
                        pass
                    else:
                        # 마지막으로 알람을 전송한 캔들의 타임스탬프 갱신
                        if alarm.intervals_need_to_be_watched:
                            alarm.alerted_candle_timestamp = last_candle_timestamp(alarm)

    # 캐시 저장소 공간에서 필요없는 공간을 정리하는 태스크
    async def cache_cleaning_task(self):
        # 프로그램 시작 후 10분 뒤부터 태스크 실행
        await asyncio.sleep(600)
        while True:
            for exchange_id in (1, 2):
                # 캔들 저장소 정리
                exchange_candle_storage = self.cache.candles[exchange_id]  # 거래소의 캔들 저장소
                for symbol in exchange_candle_storage.copy():
                    # 해당 종목을 감시하는 알람이 없을 경우 해당 종목의 캔들 저장소 삭제
                    if not self.get_alarms(exchange_id, symbol):
                        exchange_candle_storage.pop(symbol)
                        continue
                    symbol_candle_storage = exchange_candle_storage[symbol]  # 종목의 캔들 저장소
                    # 해당 언터벌을 감시하는 알람이 없을 경우 해당 인터벌의 캔들 저장소 삭제
                    for interval in symbol_candle_storage.copy():
                        if not self.get_alarms(exchange_id, symbol, interval):
                            symbol_candle_storage.pop(interval)
                # 호가 저장소 정리
                exchange_order_book_storage = self.cache.order_books[exchange_id]  # 거래소의 호가 저장소
                for symbol in exchange_order_book_storage.copy():
                    # 해당 종목을 감시하는 알람이 없을 경우 해당 종목의 호가 저장소 삭제
                    if not self.get_alarms(exchange_id, symbol):
                        exchange_order_book_storage.pop(symbol)
            # 300초마다 반복
            await asyncio.sleep(300)

    async def order_book_watching_task(self, exchange_id: int, symbol: str):
        exchange = self.get_exchange(exchange_id)
        # 호가 감시
        while True:
            try:
                # 현재 호가 정보 요청
                await exchange.watch_order_book(symbol=symbol, limit=20)
            except RequestTimeout:
                # 거래소 연결 종료 후 재연결
                await exchange.close()
                exchange = self.get_exchange(exchange_id)
                continue
            # 감시해야 하는 종목 리스트
            registered_markets = self.registered_markets
            # 감시해야 하는 종목 리스트에 해당 종목이 더 이상 존재하지 않을 경우 태스크 종료
            if symbol not in registered_markets[exchange_id]:
                # 해당 종목의 호가 캐시 삭제
                self.cache.order_books[exchange_id].pop(symbol)
                await exchange.close()
                break
            # 호가 정보를 캐시함
            order_book = exchange.orderbooks[symbol]
            self.cache.cache_order_book(order_book, exchange_id, symbol)
            await asyncio.sleep(0.1)

    # 호가에서 고래를 감시하는 함수
    def check_whale(self, alarm: Alarm):
        whale_condition = alarm.condition['whale']
        is_condition_none = whale_condition is None
        # 호가 불러오기
        exchange_id = alarm.exchange_id
        symbol = alarm.symbol
        order_book: OrderBook = self.cache.order_books[exchange_id][symbol]
        whale_info = WhaleInfo(
            is_condition_none=is_condition_none,
            has_whale=None,
            whales_in_bids=[],
            whales_in_asks=[],
            order_book=order_book
        )
        if is_condition_none:
            return whale_info
        whale_info['has_whale'] = False
        # 호가에서 고래를 확인함
        quantity = whale_condition['quantity']
        # 매도 호가에서 고래 확인
        for order_unit in order_book['bids']:
            order_unit: List[float]
            price, amount = order_unit
            if price * amount >= quantity:
                whale_info['has_whale'] = True
                whale_info['whales_in_bids'].append(order_unit.copy())
        # 매수 호가에서 고래 확인
        for order_unit in order_book['asks']:
            order_unit: List[float]
            price, amount = order_unit
            if price * amount >= quantity:
                whale_info['has_whale'] = True
                whale_info['whales_in_asks'].append(order_unit.copy())
        return whale_info

    # 거래의 체결량을 감시하는 함수
    @staticmethod
    def check_tick(alarm: Alarm, trade: Trade):
        tick_condition = alarm.condition['tick']
        is_condition_none = tick_condition is None
        tick_info = TickInfo(
            is_condition_none=is_condition_none,
            is_breakout=None,
            trade=trade,
            condition=tick_condition
        )
        if is_condition_none:
            return tick_info
        quantity = tick_condition['quantity']
        # 거래량 조건 확인
        tick_info['is_breakout'] = trade['amount'] >= quantity
        return tick_info

    # RSI 지표를 확인하는 함수
    def check_rsi(self, alarm: Alarm, trade: Trade):
        rsi_condition = alarm.condition['rsi']
        is_condition_none = rsi_condition is None
        rsi_info = RsiInfo(
            is_condition_none=is_condition_none,
            is_over_upper_bound=None,
            is_under_lower_bound=None,
            rsi=None,
            trade=trade,
            condition=rsi_condition
        )
        if is_condition_none:
            return rsi_info
        exchange_id = alarm.exchange_id
        symbol = alarm.symbol
        interval = Interval(**rsi_condition['interval'])
        rsi_length = rsi_condition['length']
        since = int(datetime.now().timestamp() - rsi_length * 86400)
        candles = self.cache.get_candles(exchange_id, symbol, interval, since)
        # 캔들의 종가 리스트
        price_list = [candle.close for candle in candles]
        # RSI 값 계산
        rsi_value = functions.rsi(price_list, rsi_length)
        rsi_info['rsi'] = rsi_value
        # RSI 조건 확인
        upper_bound = rsi_condition['upper_bound']
        rsi_info['is_over_upper_bound'] = upper_bound <= rsi_value
        lower_bound = rsi_condition['lower_bound']
        rsi_info['is_under_lower_bound'] = lower_bound >= rsi_value
        return rsi_info

    # 볼린저 밴드 지표를 확인하는 함수
    def check_bollinger_band(self, alarm: Alarm, trade: Trade):
        bollinger_band_condition = alarm.condition['bollinger_band']
        is_condition_none = bollinger_band_condition is None
        bollinger_band_info = BollingerBandInfo(
            is_condition_none=is_condition_none,
            is_over_upper_band=None,
            is_under_lower_band=None,
            upper_band=None,
            lower_band=None,
            trade=trade,
            condition=bollinger_band_condition
        )
        if is_condition_none:
            return bollinger_band_info
        exchange_id = alarm.exchange_id
        symbol = alarm.symbol
        # 조건의 인터벌
        interval = Interval(**bollinger_band_condition['interval'])
        # 조건의 길이
        length = bollinger_band_condition['length']
        # 해당 인터벌의 캔들 리스트
        candles = self.cache.get_candles(exchange_id, symbol, interval)[-length:]
        # 캔들의 종가 리스트
        price_list = [candle.close for candle in candles]
        # 조건의 표준편차
        coefficient = bollinger_band_condition['coefficient']
        # 볼린저 밴드 계산
        basis_band, upper_band, lower_band = functions.bollinger_band(price_list, coefficient)
        bollinger_band_info['upper_band'] = upper_band  # 상단선
        bollinger_band_info['lower_band'] = lower_band  # 하단선
        # 볼린저 밴드 조건 확인
        is_over_upper_band = upper_band <= trade['price']
        bollinger_band_info['is_over_upper_band'] = is_over_upper_band
        is_under_lower_band = lower_band >= trade['price']
        bollinger_band_info['is_under_lower_band'] = is_under_lower_band
        return bollinger_band_info

    def check_alarm(self, alarm: Alarm, trade: Trade) -> dict:
        check_result = {
            'is_alarm_triggered': False,  # 알람 조건 달성 여부
            'whales': None,  # 발견한 고래, 지정된 고래 조건이 있고 고래가 발견될 경우 업데이트됨
            'rsi': None,  # RSI 값, 지정된 RSI 조건이 있고 해당 조건을 달성한 경우 값이 업데이트됨
            'crossed_band': None,  # 돌파한 볼린저 밴드 이름, 지정된 볼린저 밴드 조건이 있고 조건을 달성한 경우 해당 밴드의 이름이 업데이트됨
            # 상단선 돌파 시: 'upper_band'
            # 하단선 돌파 시: 'lower_band'
            'trade': trade  # 검사한 거래 정보
        }
        # 지정된 고래 조건이 있을 경우 검사
        whale_info = self.check_whale(alarm)
        if not whale_info['is_condition_none']:
            # 발견된 고래가 없을 경우 검사 종료
            if not whale_info['has_whale']:
                return check_result
            # 발견된 고래를 검사 결과에 업데이트
            check_result['whales'] = {
                'bids': whale_info['whales_in_bids'].copy(),
                'asks': whale_info['whales_in_asks'].copy()
            }
        # 지정된 거래량 조건이 있을 경우 검사
        tick_info = self.check_tick(alarm, trade)
        if not tick_info['is_condition_none']:
            # 조건에 맞지 않는 경우 검사 종료
            if not tick_info['is_breakout']:
                return check_result
        # 지정된 RSI 조건이 있을 경우 검사
        rsi_info = self.check_rsi(alarm, trade)
        if not rsi_info['is_condition_none']:
            is_over_upper_bound = rsi_info['is_over_upper_bound']  # 상향 돌파 여부
            is_under_lower_bound = rsi_info['is_under_lower_bound']  # 하향 돌파 여부
            # 두 기준 모두 돌파하지 못했을 경우 검사 종료
            if not (is_over_upper_bound or is_under_lower_bound):
                return check_result
            # RSI 조건 통과 시 검사 결과 딕셔너리에 RSI 값 추가
            rsi_value = rsi_info['rsi']
            check_result['rsi'] = rsi_value
        # 지정된 볼린저 밴드 조건이 있을 경우 검사
        bollinger_band_info = self.check_bollinger_band(alarm, trade)
        if not bollinger_band_info['is_condition_none']:
            # 볼린저 밴드 알람 조건
            bollinger_band_condition: BollingerBandCondition = bollinger_band_info['condition']
            on_over_upper_band = bollinger_band_condition['on_over_upper_band']  # 상단선 돌파 시 알람 여부
            # 상단선 돌파 시 알람 여부와 상단선 돌파 여부가 모두 참일 경우 검사 결과 딕셔너리에 기록
            if on_over_upper_band:
                is_over_upper_band = bollinger_band_info['is_over_upper_band']  # 상단선 돌파 여부
                if is_over_upper_band:
                    check_result['crossed_band'] = 'upper_band'
            on_under_lower_band = bollinger_band_condition['on_under_lower_band']  # 하단선 돌파 시 알람 여부
            # 하단선 돌파 시 알람 여부와 하단선 돌파 여부가 모두 참일 경우 검사 결과 딕셔너리에 기록
            if on_under_lower_band:
                is_under_lower_band = bollinger_band_info['is_under_lower_band']  # 하단선 돌파 여부
                if is_under_lower_band:
                    check_result['crossed_band'] = 'lower_band'
            # 돌파한 밴드가 없을 경우 검사 종료
            if check_result['crossed_band'] is None:
                return check_result
        # 검사를 모두 통과한 경우 check_result 딕셔너리의 'is_alarm_triggered' 키의 값을 True로 변경
        check_result['is_alarm_triggered'] = True
        return check_result

    async def send_alarm(self, alarm: Alarm, check_result: dict):
        exchange_id = alarm.exchange_id
        exchange_name = get_exchange_name(exchange_id)
        symbol = alarm.symbol
        trade = check_result['trade']
        msg = f"{exchange_name} {symbol} 조건 돌파!\n"
        base_symbol = alarm.base_symbol
        quote_symbol = alarm.quote_symbol
        price = trade['price']
        amount = trade['amount']
        cost = trade['cost']
        # 거래 정보
        msg += f"가격: {price:,} {quote_symbol}\n거래량: {amount:,.4f} {base_symbol}\n총 체결 금액: {cost:,.2f} {quote_symbol}\n"
        # RSI 정보
        rsi_value: Optional[float] = check_result['rsi']
        if rsi_value is not None:
            msg += f"RSI: {rsi_value:.2f}\n"
        # 볼린저 밴드 정보
        crossed_band: Optional[str] = check_result['crossed_band']
        if crossed_band is not None:
            band_name = {
                'upper_band': '상단선',
                'lower_band': '하단선'
            }
            breaked_band = band_name[crossed_band]
            msg += f"볼린저 밴드 {breaked_band} 돌파!"
        await self.bot.send_message(alarm.channel_id, msg)
        # 고래 정보 알림
        whales = check_result['whales']
        if whales is not None:
            msg = f"고래 정보\n"
            msg += "=============\n매도벽\n"
            for order_unit in whales['asks'][::-1]:
                price, amount = order_unit
                msg += f"{amount:,.2f} {alarm.base_symbol}@{price:,.2f} {alarm.quote_symbol} / 총액: {price * amount:,.2f} {alarm.quote_symbol}\n"
            msg += "=============\n매수벽\n"
            for order_unit in whales['bids']:
                price, amount = order_unit
                msg += f"{amount:,.2f} {alarm.base_symbol}@{price:,.2f} {alarm.quote_symbol} / 총액: {price * amount:,.2f} {alarm.quote_symbol}\n"
            await self.bot.send_message(alarm.channel_id, msg)
