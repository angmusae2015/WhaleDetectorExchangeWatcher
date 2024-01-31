from typing import List

from statistics import mean as sma
from statistics import pstdev


PRICE, AMOUNT = 0, 1
ORDER_TYPE_LIST = ['bids', 'asks']  # [매수, 매도]


def filter_whale(order_book: dict, quantity: float) -> dict:
    # 고래를 판별하는 기준식
    whale_filter = lambda unit: unit[PRICE] * unit[AMOUNT] >= quantity

    # 매수와 매도에 있는 각 호가 중 고래인 호가만 필터링함
    return {
        order_type: [unit for unit in order_book[order_type] if whale_filter(unit)] for order_type in ORDER_TYPE_LIST
    }


def verify_new_whale(past_order_book: dict, current_whale_dict: dict, quantity: float):
    # 이전 사이클의 호가 리스트의 고래
    past_whale_dict = filter_whale(past_order_book, quantity)

    # 이전에 고래가 발견된 가격대 리스트
    past_whale_price_dict = {
        order_type: [unit[PRICE] for unit in past_whale_dict[order_type]] for order_type in ORDER_TYPE_LIST
    }

    return {
        order_type: [
            unit for unit in current_whale_dict[order_type] if unit[PRICE] not in past_whale_price_dict[order_type]
        ] for order_type in ORDER_TYPE_LIST
    }


# 지수이동평균(EMA) 계산
def ema(data: List[float], length) -> float:
    alpha = 2 / (1 + length)

    def f(t: int):
        if t == 1:
            return data[t - 1]
        
        return (alpha * data[t - 1]) + ((1 - alpha) * f(t - 1))

    return f(len(data))


# alpha 값이 1 / length 인 EMA 계산
def rma(data: List[float], length) -> float:
    alpha = 1 / length

    def f(t: int):
        if t == 1:
            return sma(data)
        return (data[t - 1] * alpha) + (f(t - 1) * (1 - alpha))

    return f(len(data))


# 볼린저 밴드 계산
def bollinger_band(closing_price_list: List[float], k=2.0):
    basis_band = sma(closing_price_list)
    stdev_value = pstdev(closing_price_list)

    upper_band = basis_band + (stdev_value * k)
    lower_band = basis_band - (stdev_value * k)

    return basis_band, upper_band, lower_band


# RSI 계산
def rsi(closing_price_list: List[float], length: int):
    ups = [max(closing_price_list[i] - closing_price_list[i - 1], 0) for i in range(1, len(closing_price_list))]
    downs = [max(closing_price_list[i - 1] - closing_price_list[i], 0) for i in range(1, len(closing_price_list))]

    average_up = rma(ups, length)
    average_down = rma(downs, length)

    _rsi = average_up / (average_up + average_down) * 100

    return _rsi
