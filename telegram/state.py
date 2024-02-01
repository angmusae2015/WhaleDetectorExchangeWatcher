from telebot.asyncio_handler_backends import StatesGroup, State


class AlarmMenuStates(StatesGroup):
    menu = State()


class AlarmAddingProcessStates(StatesGroup):
    channel = State()
    exchange = State()
    currency = State()
    market = State()
    condition = State()


class AlarmEditingProcessStates(StatesGroup):
    channel = State()
    alarm = State()
    condition = State()


class TickConditionSettingProcessStates(StatesGroup):
    quantity = State()


class WhaleConditionSettingProcessStates(StatesGroup):
    quantity = State()


class RsiConditionSettingProcessStates(StatesGroup):
    length = State()
    interval = State()
    upper_bound = State()
    lower_bound = State()


class BollingerBandConditionSettingProcessStates(StatesGroup):
    length = State()
    interval = State()
    coefficient = State()
    band_to_alert = State()


class ChannelMenuStates(StatesGroup):
    menu = State()


class ChannelAddingProcessStates(StatesGroup):
    channel_name = State()
    channel_id = State()
