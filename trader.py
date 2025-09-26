import ccxt
import pandas as pd
import time
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from prod_config_long import LONG_PARAMS
from prod_config_short import SHORT_PARAMS
from indicators import add_indicators
from backtester import generate_signals

from trader_utils import (
    api_retry_wrapper,
    save_state,
    load_state,
    connect_to_bybit,
    log_initial_balance,
    WebSocketManager
)

# Настраиваем ротацию: лог будет "переезжать" в новый файл при достижении 5 МБ.
# Храним до 5 старых лог-файлов (trader.log.1, trader.log.2, ...).
log_handler = RotatingFileHandler('trader.log', maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
stream_handler = logging.StreamHandler()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        log_handler,
        stream_handler
    ]
)


def get_market_data(exchange, symbol, timeframe, params, limit=300):
    """Загружает свечи, добавляет индикаторы и сигналы."""
    try:
        ohlcv = api_retry_wrapper(exchange.fetch_ohlcv, symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df_indicators = add_indicators(df, params)
        df_signals = generate_signals(df_indicators, params)
        return df_signals
    except Exception as e:
        logging.error(f"Ошибка при получении или обработке рыночных данных: {e}")
        return None


# --- Основной торговый класс ---

class PositionManager:
    """
    Класс перестроен для независимого управления Long и Short позициями (Hedge Mode).
    """

    # --- 1. Инициализация и управление состоянием ---
    def __init__(self, exchange, symbol, long_params, short_params, ws_manager):
        self.exchange = exchange
        self.symbol = symbol
        self.long_params = long_params
        self.short_params = short_params
        self.ws_manager = ws_manager
        self.market = api_retry_wrapper(self.exchange.market, self.symbol)
        self.reconciliation_counter = 0
        self.RECONCILE_INTERVAL = 60

        self.state = load_state()
        self.sync_state_from_dict()

        # Устанавливаем плечо, только если нет активных позиций
        if self.long_status == 'idle' and self.short_status == 'idle':
            self.set_futures_leverage()
        else:
            logging.info("Обнаружена активная позиция. Пропускаю установку кредитного плеча.")

        if 'high_water_mark' not in self.state or 'risk_capital_base' not in self.state:
            logging.info("High-Water Mark не найден. Получение актуального капитала с биржи...")
            try:
                balance_data = api_retry_wrapper(self.exchange.fetch_total_balance)
                initial_capital = float(balance_data.get('USDT', 100.0))
                self.state['high_water_mark'] = initial_capital
                self.state['risk_capital_base'] = initial_capital
                logging.info(f"HWM инициализирован значением: {initial_capital:.2f} USDT")
            except Exception as e:
                logging.error(f"Не удалось получить начальный капитал для HWM: {e}.")
                self.state.setdefault('high_water_mark', 100.0)
                self.state.setdefault('risk_capital_base', 100.0)

        self.sync_state_from_dict()
        logging.info("Менеджер позиций: начальное состояние Long: %s", self.state.get('long_position', {}))
        logging.info("Менеджер позиций: начальное состояние Short: %s", self.state.get('short_position', {}))

        self.reconcile_state_with_exchange()

        self.last_log_time = 0
        self.last_data_fetch_time = 0
        self.DATA_FETCH_INTERVAL = 15

    def sync_state_from_dict(self):
        self.high_water_mark = self.state.get('high_water_mark', 100.0)
        self.risk_capital_base = self.state.get('risk_capital_base', 100.0)
        self.last_trade_pnl = self.state.get('last_trade_pnl', 0.0)

        long_state = self.state.get('long_position', {})
        short_state = self.state.get('short_position', {})

        def _parse_datetime(value):
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value)
                except (ValueError, TypeError):
                    return None
            return value if isinstance(value, datetime) else None

        # --- Состояние для LONG позиции ---
        self.long_status = long_state.get('status', 'idle')
        self.long_position_size = long_state.get('position_size', 0)
        self.long_initial_size = long_state.get('initial_size', 0)
        self.long_entry_price = long_state.get('entry_price', 0)
        self.long_last_add_price = long_state.get('last_add_price', 0)
        self.long_entry_time = _parse_datetime(long_state.get('entry_time'))
        self.long_last_tsl_exit_timestamp = _parse_datetime(long_state.get('last_tsl_exit_timestamp'))
        self.long_atr_at_entry = long_state.get('atr_at_entry', 0)
        self.long_max_price_since_entry = long_state.get('max_price_since_entry', 0)
        self.long_is_partially_closed = long_state.get('is_partially_closed', False)
        self.long_stop_loss_price = long_state.get('stop_loss_price', 0.0)
        self.long_partial_tp_order_id = long_state.get('partial_tp_order_id', None)
        self.long_entry_order_id = long_state.get('entry_order_id', None)
        self.long_entry_fee = long_state.get('entry_fee', 0.0)
        self.long_is_breakeven_set = long_state.get('is_breakeven_set', False)
        self.long_is_trailing_active = long_state.get('is_trailing_active', False)
        self.long_max_pnl_in_trade = long_state.get('max_pnl_in_trade', 0.0)
        self.long_is_stagnation_armed = long_state.get('is_stagnation_armed', False)
        self.long_partial_closes_count = long_state.get('partial_closes_count', 0)

        # --- Состояние для SHORT позиции ---
        self.short_status = short_state.get('status', 'idle')
        self.short_position_size = short_state.get('position_size', 0)
        self.short_initial_size = short_state.get('initial_size', 0)
        self.short_entry_price = short_state.get('entry_price', 0)
        self.short_last_add_price = short_state.get('last_add_price', 0)
        self.short_entry_time = _parse_datetime(short_state.get('entry_time'))
        self.short_last_tsl_exit_timestamp = _parse_datetime(short_state.get('last_tsl_exit_timestamp'))
        self.short_atr_at_entry = short_state.get('atr_at_entry', 0)
        self.short_min_price_since_entry = short_state.get('min_price_since_entry', 0)
        self.short_is_partially_closed = short_state.get('is_partially_closed', False)
        self.short_stop_loss_price = short_state.get('stop_loss_price', 0.0)
        self.short_partial_tp_order_id = short_state.get('partial_tp_order_id', None)
        self.short_entry_order_id = short_state.get('entry_order_id', None)
        self.short_entry_fee = short_state.get('entry_fee', 0.0)
        self.short_is_breakeven_set = short_state.get('is_breakeven_set', False)
        self.short_is_trailing_active = short_state.get('is_trailing_active', False)
        self.short_max_pnl_in_trade = short_state.get('max_pnl_in_trade', 0.0)
        self.short_is_stagnation_armed = short_state.get('is_stagnation_armed', False)
        self.short_partial_closes_count = short_state.get('partial_closes_count', 0)

    def update_and_save_state(self, side=None, **kwargs):
        """
        Обновляет состояние.
        Если 'side' указан ('long' или 'short'), обновляет вложенный словарь.
        Если 'side' не указан, обновляет глобальные ключи в state.
        """
        if side:
            if side not in ['long', 'short']:
                raise ValueError("Side должен быть 'long' или 'short'")
            state_key = f"{side}_position"

            # Убедимся, что вложенный словарь существует
            if state_key not in self.state:
                self.state[state_key] = {}

            self.state[state_key].update(kwargs)
        else:
            # Обновляем глобальные ключи
            self.state.update(kwargs)

        save_state(self.state)
        self.sync_state_from_dict()

    def reset_long_state(self, reason=""):
        logging.info(f"Сброс LONG состояния по причине: {reason}")
        self.update_and_save_state(
            'long',
            status='idle', position_size=0, initial_size=0, entry_price=0,
            last_add_price=0, entry_time=None, atr_at_entry=0,
            max_price_since_entry=0, is_partially_closed=False, stop_loss_price=0.0,
            partial_tp_order_id=None, entry_order_id=None, entry_fee=0.0,
            is_breakeven_set=False, is_trailing_active=False, max_pnl_in_trade=0.0,
            is_stagnation_armed=False, partial_closes_count=0
        )

    def reset_short_state(self, reason=""):
        logging.info(f"Сброс SHORT состояния по причине: {reason}")
        self.update_and_save_state(
            'short',
            status='idle', position_size=0, initial_size=0, entry_price=0,
            last_add_price=0, entry_time=None, atr_at_entry=0,
            min_price_since_entry=0, is_partially_closed=False, stop_loss_price=0.0,
            partial_tp_order_id=None, entry_order_id=None, entry_fee=0.0,
            is_breakeven_set=False, is_trailing_active=False, max_pnl_in_trade=0.0,
            is_stagnation_armed=False, partial_closes_count=0
        )

    def set_futures_leverage(self):
        leverage = self.long_params.get('leverage', 10)
        try:
            positions = api_retry_wrapper(self.exchange.fetch_positions, [self.symbol], {'category': 'linear'})
            open_position = next((p for p in positions if float(p.get('contracts', 0)) > 0), None)

            if open_position:
                logging.info(f"Обнаружена открытая позиция. Пропускаю установку кредитного плеча.")
                return

            logging.info(f"Устанавливаю кредитное плечо {leverage}x для фьючерса {self.symbol}...")
            api_retry_wrapper(self.exchange.set_leverage, leverage, self.symbol)
        except Exception as e:
            if "leverage not modified" in str(e) or "110043" in str(e):
                logging.info(f"Кредитное плечо уже установлено на {leverage}x.")
            elif "ab not enough for new leverage" in str(e):
                logging.warning(f"Не удалось изменить плечо, т.к. есть активная позиция. Продолжаю работу с текущим плечом.")
            else:
                logging.error(f"ОШИБКА: Не удалось установить кредитное плечо: {e}")

    def _update_hwm_and_risk_capital(self):
        """Обновляет High-Water Mark и базовый капитал для расчета риска."""
        try:
            logging.info("Обновление High-Water Mark...")
            balance_data = api_retry_wrapper(self.exchange.fetch_total_balance)
            current_capital = float(balance_data.get('USDT', self.risk_capital_base))

            if current_capital > self.high_water_mark:
                logging.info(f"🚀 НОВЫЙ MAX КАПИТАЛА! Старый: {self.high_water_mark:.2f}, Новый: {current_capital:.2f}")
                # Вызываем без 'side', чтобы обновить глобальные ключи
                self.update_and_save_state(side=None, high_water_mark=current_capital,
                                           risk_capital_base=current_capital)
            else:
                logging.info(
                    f"Капитал ({current_capital:.2f}) не превысил HWM ({self.high_water_mark:.2f}). База для риска остается прежней: {self.risk_capital_base:.2f}")

        except Exception as e:
            logging.error(f"Не удалось обновить HWM: {e}", exc_info=True)

    def check_and_manage_position(self):
        """
        1. Быстрая проверка SL по WebSocket на каждом тике.
        2. Редкая (раз в 15 сек) полная проверка данных с API.
        """
        now = time.time()

        # --- ШАГ 1: ЧАСТАЯ ПРОВЕРКА ЦЕНЫ ИЗ WEBSOCKET (КАЖДЫЕ 0.2 СЕК) ---
        latest_price = self.ws_manager.get_latest_price()
        if latest_price:
            # Быстрая проверка стоп-лосса для Long
            if self.long_status == 'in_position' and self.long_stop_loss_price > 0 and latest_price <= self.long_stop_loss_price:
                logging.warning(
                    f"!!! WS: ЦЕНА ({latest_price:.4f}) ПЕРЕСЕКЛА LONG СТОП ({self.long_stop_loss_price:.4f})! ИНИЦИИРУЮ ЗАКРЫТИЕ.")
                self.close_position('long', "Проактивное WS закрытие по стопу")
                return

            # Быстрая проверка стоп-лосса для Short
            if self.short_status == 'in_position' and self.short_stop_loss_price > 0 and latest_price >= self.short_stop_loss_price:
                logging.warning(
                    f"!!! WS: ЦЕНА ({latest_price:.4f}) ПЕРЕСЕКЛА SHORT СТОП ({self.short_stop_loss_price:.4f})! ИНИЦИИРУЮ ЗАКРЫТИЕ.")
                self.close_position('short', "Проактивное WS закрытие по стопу")
                return

        # --- ШАГ 2: РЕДКАЯ ПРОВЕРКА ПОЛНЫХ ДАННЫХ (КАЖДЫЕ 15 СЕК) ---
        if now - self.last_data_fetch_time < self.DATA_FETCH_INTERVAL:
            return  # Если еще не прошло 15 секунд, выходим, выполнив только быструю проверку

        self.last_data_fetch_time = now  # Сбрасываем таймер

        # Периодическая сверка состояния
        self.reconciliation_counter += 1
        if self.reconciliation_counter * self.DATA_FETCH_INTERVAL > self.RECONCILE_INTERVAL:
            logging.info(f"Плановая сверка состояния с биржей...")
            self.reconcile_state_with_exchange()
            self.reconciliation_counter = 0

        # Получаем полные данные для обеих стратегий
        long_data = get_market_data(self.exchange, self.symbol, self.long_params['timeframe'], self.long_params)
        short_data = get_market_data(self.exchange, self.symbol, self.short_params['timeframe'], self.short_params)

        if long_data is None or short_data is None:
            logging.warning("Нет данных для полного анализа.")
            return

        # Логика диспетчера для Long
        if self.long_status == 'in_position':
            self.manage_position('long', long_data)
        elif self.long_status == 'idle' and long_data['signal'].iloc[-1] == 1:
            self.execute_entry('long', long_data)

        # Логика диспетчера для Short
        if self.short_status == 'in_position':
            self.manage_position('short', short_data)
        elif self.short_status == 'idle' and short_data['signal'].iloc[-1] == -1:
            self.execute_entry('short', short_data)

        # Логирование простоя
        if self.long_status == 'idle' and self.short_status == 'idle':
            if now - self.last_log_time > 300:
                logging.info("Статус: IDLE. Сигналов на вход нет, ожидаю...")
                self.last_log_time = now

    def execute_entry(self, side, data):
        """
        УНИВЕРСАЛЬНАЯ и ПОЛНАЯ функция входа в позицию для Long или Short.
        """
        logging.info(f"===== НАЧАЛО ПРОЦЕДУРЫ ВХОДА В {side.upper()} ПОЗИЦИЮ =====")

        # --- Шаг 1: Определяем переменные в зависимости от стороны ---
        if side == 'long':
            params = self.long_params
            direction = 1
            positionIdx = 1
            side_str = 'buy'
            last_tsl_exit_timestamp = self.long_last_tsl_exit_timestamp
        elif side == 'short':
            params = self.short_params
            direction = -1
            positionIdx = 2
            side_str = 'sell'
            last_tsl_exit_timestamp = self.short_last_tsl_exit_timestamp
        else:
            logging.error(f"Получена неизвестная сторона '{side}' в execute_entry.")
            return

        current_price = data['close'].iloc[-1]
        current_atr = data['atr'].iloc[-1]

        # --- Шаг 2: Универсальные фильтры ---
        last_rsi = data['rsi'].iloc[-1]
        if side == 'long':
            rsi_threshold = params.get('grid_upper_rsi', 99)
            if last_rsi > rsi_threshold:
                logging.warning(
                    f"Long вход пропущен: рынок экстремально перекуплен (RSI={last_rsi:.2f} > {rsi_threshold}).")
                return
        elif side == 'short':
            rsi_threshold = params.get('grid_lower_rsi', 1)
            if last_rsi < rsi_threshold:
                logging.warning(
                    f"Short вход пропущен: рынок экстремально перепродан (RSI={last_rsi:.2f} < {rsi_threshold}).")
                return
            # Дополнительный ADX фильтр для шорта, если он есть в параметрах
            if 'adx_threshold' in params and 'adx' in data.columns:
                adx_threshold = params.get('adx_threshold', 100)
                last_adx = data['adx'].iloc[-1]
                if last_adx < adx_threshold:
                    logging.info(
                        f"Short вход пропущен: недостаточная сила тренда (ADX={last_adx:.2f} < {adx_threshold}).")
                    return

        is_cooldown_override_trade = False
        cooldown_candles = params.get('cooldown_period_candles', 0)
        if cooldown_candles > 0 and isinstance(last_tsl_exit_timestamp, datetime):
            if len(data) > 1:
                current_candle_timestamp = data.index[-1].to_pydatetime().replace(tzinfo=None)
                last_exit_candle_timestamp = last_tsl_exit_timestamp.replace(tzinfo=None)
                time_since_exit = current_candle_timestamp - last_exit_candle_timestamp
                timeframe_seconds = self.exchange.parse_timeframe(params['timeframe'])
                candles_passed = time_since_exit.total_seconds() / timeframe_seconds
                if candles_passed < cooldown_candles:
                    if (side == 'long' and data['close'].iloc[-1] > data['high'].iloc[-2]) or \
                            (side == 'short' and data['close'].iloc[-1] < data['low'].iloc[-2]):
                        is_cooldown_override_trade = True
                        logging.info(f"🔥 ОБНАРУЖЕН СИГНАЛ ПРОБОЯ {side.upper()}! Кулдаун будет прерван.")
                    else:
                        logging.info(
                            f"Вход в {side.upper()} пропущен. Активен период 'остывания'. Прошло ~{candles_passed:.1f} из {cooldown_candles} требуемых свечей.")
                        return
            else:
                logging.warning(f"Недостаточно данных для проверки кулдауна, вход в {side.upper()} отменен.")
                return

        logging.info(f"СИГНАЛ НА ВХОД В {side.upper()}. Цена: {current_price}, ATR: {current_atr}.")

        # --- Шаг 3: Универсальный расчет размера ---
        try:
            balance_data_total = api_retry_wrapper(self.exchange.fetch_total_balance)
            current_capital = float(balance_data_total.get('USDT', self.risk_capital_base))
            current_drawdown = (
                                           self.high_water_mark - current_capital) / self.high_water_mark if self.high_water_mark > 0 else 0
            risk_governor_factor = 1.0
            if current_drawdown > 0.4:
                risk_governor_factor = 0.25
            elif current_drawdown > 0.3:
                risk_governor_factor = 0.35
            elif current_drawdown > 0.2:
                risk_governor_factor = 0.50
            elif current_drawdown > 0.1:
                risk_governor_factor = 0.75
            if risk_governor_factor < 1.0:
                logging.warning(
                    f"!!! АКТИВИРОВАН ГУБЕРНАТОР РИСКА !!! Просадка: {current_drawdown:.2%}. Множитель риска: {risk_governor_factor}.")
        except Exception as e:
            logging.error(f"Ошибка в блоке Risk Governor: {e}. Используется стандартный риск.")
            risk_governor_factor = 1.0

        risk_per_trade = params.get('risk_per_trade', 0.02)
        final_risk_per_trade = risk_per_trade * risk_governor_factor
        risk_amount_usdt = self.risk_capital_base * final_risk_per_trade

        agg_stop_mult = params.get('aggressive_breakout_stop_multiplier', 0.0)
        if agg_stop_mult > 0 and is_cooldown_override_trade:
            extremum_price = data['low'].iloc[-1] if side == 'long' else data['high'].iloc[-1]
            distance_to_extremum = abs(current_price - extremum_price)
            if distance_to_extremum > 0:
                logging.info(f"Активирован АГРЕССИВНЫЙ стоп-лосс для сделки-пробоя {side.upper()}.")
                stop_loss_distance = distance_to_extremum * agg_stop_mult
            else:
                logging.warning("Не удалось рассчитать агрессивный стоп, используется стандартный.")
                stop_loss_distance = current_atr * params.get('atr_stop_multiplier', 4.0)
        else:
            logging.info(f"Установлен СТАНДАРТНЫЙ стоп-лосс на основе ATR для {side.upper()}.")
            stop_loss_distance = current_atr * params.get('atr_stop_multiplier', 4.0)

        if stop_loss_distance <= 0:
            logging.error("Ошибка расчета дистанции стоп-лосса (<= 0). Вход отменен.")
            return

        stop_loss_price = current_price - (stop_loss_distance * direction)

        base_position_size = risk_amount_usdt / stop_loss_distance

        try:
            rounded_size = float(self.exchange.amount_to_precision(self.symbol, base_position_size))
        except ccxt.InvalidOrder as e:
            logging.error(f"Ошибка приведения размера к точности: {e}. Вероятно, расчетный размер слишком мал.")
            return

        min_amount = float(self.market['limits']['amount']['min'])
        if rounded_size < min_amount:
            logging.warning(
                f"Вход пропущен: размер после округления ({rounded_size:.4f}) меньше минимально допустимого ({min_amount:.4f}).")
            return

        balance_data = api_retry_wrapper(self.exchange.fetch_balance)
        capital = float(balance_data.get('USDT', {}).get('free', 0.0))
        if not self._is_sufficient_margin(capital, rounded_size, current_price, side):
            return

        # --- Шаг 4: Отправка ордера и сохранение состояния ---
        sl_price_str = self.exchange.price_to_precision(self.symbol, stop_loss_price)

        order = self.open_atomic_position(side_str, rounded_size, 0, price=None, sl_price=sl_price_str)

        if not order or 'id' not in order:
            logging.error(f"Вход в позицию {side.upper()} не удался. Ордер не был создан.")
            return

        time.sleep(3)
        entry_fee_cost = 0.0
        try:
            trades = api_retry_wrapper(self.exchange.fetch_my_trades, self.symbol, limit=5)
            entry_trade = next((t for t in trades if t['order'] == order['id']), None)
            if entry_trade:
                entry_fee_cost = float(entry_trade.get('fee', {}).get('cost', 0.0))
                logging.info(f"Найдена сделка на вход, комиссия: {entry_fee_cost:.4f} USDT")
            else:
                logging.warning("Не удалось найти сделку на вход по ID ордера для сохранения комиссии.")
        except Exception as e:
            logging.error(f"Ошибка при поиске комиссии на вход: {e}")

        positions = api_retry_wrapper(self.exchange.fetch_positions, [self.symbol], {'category': 'linear'})
        open_position = next((p for p in positions if p.get('side') == side and float(p.get('contracts', 0)) > 0), None)

        if not open_position:
            logging.error(f"Позиция {side.upper()} не обнаружена на бирже после отправки ордера.")
            return

        entry_price = float(open_position['entryPrice'])
        final_position_size = float(open_position['contracts'])

        state_to_save = {
            'status': 'in_position', 'position_size': final_position_size, 'initial_size': final_position_size,
            'entry_price': entry_price, 'last_add_price': entry_price,
            'entry_time': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            'atr_at_entry': current_atr, 'stop_loss_price': float(sl_price_str), 'entry_order_id': order['id'],
            'entry_fee': entry_fee_cost, 'is_breakeven_set': False, 'is_trailing_active': False,
            'max_pnl_in_trade': 0.0, 'is_stagnation_armed': False, 'partial_closes_count': 0,
            'is_partially_closed': False, 'last_tsl_exit_timestamp': None
        }

        if side == 'long':
            state_to_save['max_price_since_entry'] = entry_price
        else:
            state_to_save['min_price_since_entry'] = entry_price

        self.update_and_save_state(side, **state_to_save)
        logging.info(f"===== {side.upper()} ПОЗИЦИЯ УСПЕШНО ОТКРЫТА (Idx={positionIdx}) =====")
        logging.info(f"Размер: {final_position_size}, Цена входа: {entry_price}, SL: {sl_price_str}")

        self._place_next_partial_tp(side)

    def manage_position(self, side, data):
        """
        УНИВЕРСАЛЬНАЯ и ПОЛНАЯ функция управления открытой позицией.
        """
        # --- Шаг 1: Установка контекста в зависимости от стороны ---
        if side == 'long':
            params = self.long_params;
            direction = 1;
            status = self.long_status
            position_size = self.long_position_size;
            initial_size = self.long_initial_size
            entry_price = self.long_entry_price;
            stop_loss_price = self.long_stop_loss_price
            atr_at_entry = self.long_atr_at_entry;
            is_breakeven_set = self.long_is_breakeven_set
            is_trailing_active = self.long_is_trailing_active;
            max_pnl_in_trade = self.long_max_pnl_in_trade
            is_stagnation_armed = self.long_is_stagnation_armed;
            entry_time = self.long_entry_time
            last_add_price = self.long_last_add_price;
            entry_fee = self.long_entry_fee
            price_tracker = self.long_max_price_since_entry;
            price_tracker_key = 'max_price_since_entry'
            exit_signal = 10;
            side_str = 'buy'
        elif side == 'short':
            params = self.short_params;
            direction = -1;
            status = self.short_status
            position_size = self.short_position_size;
            initial_size = self.short_initial_size
            entry_price = self.short_entry_price;
            stop_loss_price = self.short_stop_loss_price
            atr_at_entry = self.short_atr_at_entry;
            is_breakeven_set = self.short_is_breakeven_set
            is_trailing_active = self.short_is_trailing_active;
            max_pnl_in_trade = self.short_max_pnl_in_trade
            is_stagnation_armed = self.short_is_stagnation_armed;
            entry_time = self.short_entry_time
            last_add_price = self.short_last_add_price;
            entry_fee = self.short_entry_fee
            price_tracker = self.short_min_price_since_entry;
            price_tracker_key = 'min_price_since_entry'
            exit_signal = -10;
            side_str = 'sell'
        else:
            return

        # Если по какой-то причине функция вызвана для неактивной позиции, выходим
        if status != 'in_position' or position_size == 0:
            return

        current_price = data['close'].iloc[-1]
        current_atr = data['atr'].iloc[-1]
        last_signal = data['signal'].iloc[-1]

        # --- Шаг 2: Универсальные проверки и управление ---

        # ПРОВЕРКА СТОП-ЛОССА
        is_stop_triggered = (side == 'long' and current_price <= stop_loss_price) or \
                            (side == 'short' and current_price >= stop_loss_price)
        if stop_loss_price > 0 and is_stop_triggered:
            logging.warning(
                f"!!! ЦЕНА ({current_price:.4f}) ПЕРЕСЕКЛА СТОП ({stop_loss_price:.4f}) для {side.upper()}! ИНИЦИИРУЮ ЗАКРЫТИЕ.")
            self.close_position(side, f"Проактивное закрытие по стопу {side.upper()}")
            return

        # ПИРАМИДИНГ (POSITION SCALING)
        max_pos_mult = params.get('max_position_multiplier', 1.0)
        max_pos_size = initial_size * max_pos_mult
        if params.get('position_scaling', False) and (
                is_breakeven_set or is_trailing_active) and last_signal == direction and position_size < max_pos_size:
            scale_trigger_price = last_add_price + (
                        params.get('scale_add_atr_multiplier', 0.5) * current_atr * direction)
            should_add = (side == 'long' and current_price >= scale_trigger_price) or \
                         (side == 'short' and current_price <= scale_trigger_price)
            if should_add:
                logging.info(f"📈 СИГНАЛ НА ПИРАМИДИНГ для {side.upper()}!")
                add_size = initial_size
                max_add_allowed = max_pos_size - position_size
                if add_size > max_add_allowed:
                    add_size = max_add_allowed

                min_amount = float(self.market['limits']['amount']['min'])
                if add_size >= min_amount:
                    rounded_add_size = float(self.exchange.amount_to_precision(self.symbol, add_size))
                    if rounded_add_size >= min_amount:
                        balance_data = api_retry_wrapper(self.exchange.fetch_balance)
                        capital = float(balance_data.get('USDT', {}).get('free', 0.0))
                        if self._is_sufficient_margin(capital, rounded_add_size, current_price, side):
                            try:
                                add_order = api_retry_wrapper(self.exchange.create_market_order, self.symbol, side_str,
                                                              rounded_add_size,
                                                              {'positionIdx': 0})
                                time.sleep(3)
                                positions = api_retry_wrapper(self.exchange.fetch_positions, [self.symbol],
                                                              {'category': 'linear'})
                                open_position = next((p for p in positions if p.get('side') == side), None)
                                if open_position:
                                    new_total_size = float(open_position['contracts'])
                                    new_avg_price = float(open_position['entryPrice'])
                                    logging.info(
                                        f"УСПЕШНО ДОБАВЛЕНО. Новый размер: {new_total_size}, Новая средняя цена: {new_avg_price}")
                                    self.update_and_save_state(side, position_size=new_total_size,
                                                               entry_price=new_avg_price, last_add_price=current_price)
                            except Exception as e:
                                logging.error(f"Ошибка при добавлении к позиции {side.upper()}: {e}", exc_info=True)
                    else:
                        logging.warning(
                            f"Размер для добавления {side.upper()} ({add_size:.4f}) меньше минимального ({min_amount}). Пирамидинг отменен.")

        # ПЕРЕВОД В БЕЗУБЫТОК
        if not is_breakeven_set and atr_at_entry > 0:
            breakeven_trigger_price = entry_price + (
                        atr_at_entry * params.get('breakeven_atr_multiplier', 1.5) * direction)
            should_set_be = (side == 'long' and current_price >= breakeven_trigger_price) or \
                            (side == 'short' and current_price <= breakeven_trigger_price)
            if should_set_be:
                logging.info(
                    f"✅ ЦЕНА ({current_price:.4f}) ДОСТИГЛА УРОВНЯ Б/У ({breakeven_trigger_price:.4f}) для {side.upper()}.")
                total_commission_per_unit = (entry_fee / initial_size) * 2 if initial_size > 0 else 0
                breakeven_plus_price = entry_price + (total_commission_per_unit * direction)

                if self.set_protection_for_existing_position(side, breakeven_plus_price):
                    self.update_and_save_state(side, is_breakeven_set=True, stop_loss_price=breakeven_plus_price)
                    logging.info(
                        f"Стоп-лосс для {side.upper()} успешно перемещен в безубыток на {breakeven_plus_price:.4f}.")
                else:
                    logging.warning(f"Не удалось переместить стоп-лосс в безубыток для {side.upper()}.")

        # --- ЛОГИКА "ЗАМКА НА ПРИБЫЛЬ" ---
        trigger_pct = params.get('profit_lock_trigger_pct')
        target_pct = params.get('profit_lock_target_pct')
        if trigger_pct and target_pct and not is_breakeven_set:
            trigger_price = entry_price * (1 + (trigger_pct * direction))
            should_lock_profit = (side == 'long' and current_price >= trigger_price) or \
                                 (side == 'short' and current_price <= trigger_price)
            if should_lock_profit:
                target_stop_price = entry_price * (1 + (target_pct * direction))
                should_move_stop = (side == 'long' and target_stop_price > stop_loss_price) or \
                                   (side == 'short' and target_stop_price < stop_loss_price)
                if should_move_stop:
                    logging.info(
                        f"🎯 Сработал ЗАМОК НА ПРИБЫЛЬ для {side.upper()}. Фиксирую прибыль, перемещая стоп на {target_stop_price:.4f}")
                    self.set_protection_for_existing_position(side, target_stop_price)

        # ТРЕЙЛИНГ-СТОП
        if (side == 'long' and current_price > price_tracker) or \
                (side == 'short' and (
                        price_tracker == 0 or current_price < price_tracker)):  # price_tracker == 0 для первой инициализации шорта
            price_tracker = current_price
            self.update_and_save_state(side, **{price_tracker_key: price_tracker})

        should_trail = is_breakeven_set or is_trailing_active
        if not should_trail and atr_at_entry > 0:
            early_activation_mult = params.get('trail_early_activation_atr_multiplier', 1.0)
            trail_early_activation_price = entry_price + (atr_at_entry * early_activation_mult * direction)
            should_activate_early = (side == 'long' and current_price > trail_early_activation_price) or \
                                    (side == 'short' and current_price < trail_early_activation_price)
            if should_activate_early:
                should_trail = True
                if not is_trailing_active:
                    logging.info(f"Трейлинг-стоп для {side.upper()} предварительно активирован.")

        if should_trail:
            multiplier = params.get('aggressive_trail_atr_multiplier', 1.5) if is_breakeven_set else params.get(
                'trail_atr_multiplier', 3.0)
            chandelier_stop = price_tracker - (current_atr * multiplier * direction)
            should_move_trail = (side == 'long' and chandelier_stop > stop_loss_price) or \
                                (side == 'short' and chandelier_stop < stop_loss_price)

            if should_move_trail:
                final_stop_price = chandelier_stop
                if side == 'short':
                    # Добавляем буфер только для шорт-позиции, чтобы избежать "гонки условий"
                    tick_size = self.market.get('precision', {}).get('price', 0.01)
                    final_stop_price = chandelier_stop + (5 * tick_size)

                logging.info(
                    f"ТРЕЙЛИНГ-СТОП {side.upper()}: Перемещаю SL с {stop_loss_price:.4f} на {final_stop_price:.4f}")
                if self.set_protection_for_existing_position(side, final_stop_price):
                    self.update_and_save_state(side, is_trailing_active=True, stop_loss_price=final_stop_price)

        # ВЫХОД ПО СТАГНАЦИИ
        stagnation_exit = False
        current_pnl = (current_price - entry_price) * position_size * direction
        if current_pnl > max_pnl_in_trade:
            self.update_and_save_state(side, max_pnl_in_trade=current_pnl)
            max_pnl_in_trade = current_pnl  # Обновляем локальную переменную

        stagnation_trigger_pnl = (atr_at_entry * params.get('stagnation_atr_threshold', 3.0)) * initial_size
        if not is_stagnation_armed and is_trailing_active and current_pnl > stagnation_trigger_pnl:
            logging.info(f"Выход по стагнации для {side.upper()} 'взведен'.")
            self.update_and_save_state(side, is_stagnation_armed=True)
            is_stagnation_armed = True  # Обновляем локальную переменную

        if is_stagnation_armed and current_pnl < (max_pnl_in_trade * params.get('stagnation_profit_decay', 0.7)):
            stagnation_exit = True

        # --- ФИНАЛЬНЫЕ ПРОВЕРКИ НА ВЫХОД ---
        if atr_at_entry > 0:
            final_tp_price = entry_price + (atr_at_entry * params.get('tp_atr_multiplier', 8.0) * direction)
        else:
            final_tp_price = 0  # Для "спасенных" позиций TP не рассчитываем

        time_exceeded = False
        if entry_time:
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            time_exceeded = (now_utc - entry_time).total_seconds() > params['max_hold_hours'] * 3600

        # Проверяем TP, только если он был валидно рассчитан (больше нуля)
        price_reached_tp = False
        if final_tp_price > 0:
            price_reached_tp = (side == 'long' and current_price >= final_tp_price) or \
                               (side == 'short' and current_price <= final_tp_price)

        exit_by_signal = (last_signal == exit_signal and is_breakeven_set)

        if price_reached_tp:
            self.close_position(side, f"Достигнута цена финального TP ({final_tp_price:.4f})")
        elif time_exceeded:
            self.close_position(side, "Превышено время удержания")
        elif exit_by_signal:
            self.close_position(side, "Получен явный сигнал на выход (RSI)")
        elif stagnation_exit:  # Перемещаем проверку стагнации сюда же для единой логики
            self.close_position(side, f"Выход по стагнации (просадка с макс. прибыли {max_pnl_in_trade:.2f} USDT)")

        # --- ЛОГИРОВАНИЕ СОСТОЯНИЯ ПОЗИЦИИ ---
        now = time.time()
        if now - self.last_log_time > 15:  # Логируем не чаще раза в 15 сек
            pnl_string = f"PnL={current_pnl:.2f} (max PnL: {max_pnl_in_trade:.2f}) USDT"
            logging.info(
                f"Управление {side.upper()}: Цена={current_price:.4f} | SL={stop_loss_price:.4f} | TP={final_tp_price:.4f} | {pnl_string}")
            self.last_log_time = now

        elif stagnation_exit:
            self.close_position(side, f"Выход по стагнации (просадка с макс. прибыли {max_pnl_in_trade:.2f} USDT)")

    def close_position(self, side, reason="unknown"):
        logging.info(f"Начало полного закрытия {side.upper()} позиции по причине: {reason}.")

        # --- УМНАЯ АКТИВАЦИЯ КУЛДАУНА ---
        # Определяем переменные для анализа до сброса состояния
        params = self.long_params if side == 'long' else self.short_params
        entry_price = self.long_entry_price if side == 'long' else self.short_entry_price
        stop_loss_price = self.long_stop_loss_price if side == 'long' else self.short_stop_loss_price
        is_breakeven_set = self.long_is_breakeven_set if side == 'long' else self.short_is_breakeven_set

        # Проверяем, был ли стоп в зоне безубытка/прибыли
        is_tsl_closure = False
        if is_breakeven_set:  # Самый надежный признак
            is_tsl_closure = True
        elif side == 'long' and stop_loss_price > entry_price:  # Стоп был в зоне прибыли
            is_tsl_closure = True
        elif side == 'short' and stop_loss_price < entry_price:  # Стоп был в зоне прибыли
            is_tsl_closure = True

        if is_tsl_closure:
            cooldown_candles = params.get('cooldown_period_candles', 0)
            if cooldown_candles > 0:
                try:
                    data = get_market_data(self.exchange, self.symbol, params['timeframe'], params)
                    if data is not None and not data.empty:
                        last_candle_timestamp = data.index[-1].to_pydatetime()
                        logging.info(
                            f"Причина закрытия - прибыльный стоп. Активирую кулдаун для {side.upper()} на {cooldown_candles} свечи.")
                        # Сохраняем ВРЕМЕННО, перед полным сбросом
                        self.update_and_save_state(side, last_tsl_exit_timestamp=last_candle_timestamp.isoformat())
                except Exception as e:
                    logging.error(f"Не удалось получить данные для установки времени кулдауна: {e}")

        side_str_close = 'sell' if side == 'long' else 'buy'
        size_to_close = self.long_position_size if side == 'long' else self.short_position_size
        reset_state_func = self.reset_long_state if side == 'long' else self.reset_short_state
        order_id_to_cancel = self.long_partial_tp_order_id if side == 'long' else self.short_partial_tp_order_id

        try:
            if order_id_to_cancel:
                logging.info(f"Отмена отложенного ордера {order_id_to_cancel} для {side.upper()} стороны...")
                try:
                    api_retry_wrapper(self.exchange.cancel_order, order_id_to_cancel, self.symbol)
                    logging.info(f"Ордер {order_id_to_cancel} успешно отменен.")
                except ccxt.OrderNotFound:
                    logging.info(f"Ордер {order_id_to_cancel} не найден на бирже (возможно, уже исполнен или отменен).")
                except Exception as e:
                    logging.error(f"Не удалось отменить ордер {order_id_to_cancel}: {e}")
            else:
                logging.info(f"Нет активных отложенных ордеров для отмены на стороне {side.upper()}.")

            logging.info(f"Сброс SL/TP на {side.upper()} позиции перед закрытием...")
            self.set_protection_for_existing_position(side, sl_price='0', tp_price='0')
            time.sleep(1)

            positions = api_retry_wrapper(self.exchange.fetch_positions, [self.symbol], {'category': 'linear'})
            open_position = next((p for p in positions if p.get('side') == side and float(p.get('contracts', 0)) > 0),
                                 None)

            if open_position:
                current_size = float(open_position['contracts'])
                logging.info(f"Отправка Market ордера на закрытие {current_size} {self.symbol} ({side.upper()})...")
                params_close = {'reduceOnly': True, 'category': 'linear', 'positionIdx': 0}
                api_retry_wrapper(self.exchange.create_market_order, self.symbol, side_str_close, current_size,
                                  params=params_close)
                time.sleep(2)
            else:
                logging.info(f"Позиция {side.upper()} для закрытия не найдена на бирже (вероятно, уже закрыта).")

            logging.info(f"Запуск процедуры расчета итогового PnL для {side.upper()}...")
            self._calculate_and_log_pnl(side, size_to_close)

        except Exception as e:
            logging.error(f"Критическая ошибка при закрытии {side.upper()} позиции: {e}", exc_info=True)

        reset_state_func(f"Закрытие по причине: {reason}")

    def _is_sufficient_margin(self, free_balance, amount, price, side):
        """Теперь принимает 'side' для корректного расчета плеча."""
        try:
            # Выбираем правильный набор параметров
            params = self.long_params if side == 'long' else self.short_params

            leverage = params.get('leverage', 10)
            taker_fee = self.market.get('taker', 0.00055)

            initial_margin = (amount * price) / leverage
            estimated_fee = amount * price * taker_fee
            total_cost = (initial_margin + estimated_fee) * 1.05

            logging.info(
                f"Проверка маржи для {side.upper()}: Требуется ~$ {total_cost:.2f} (Маржа: ${initial_margin:.2f}, Комиссия: ${estimated_fee:.2f}). Доступно: ${free_balance:.2f}")

            if total_cost > free_balance:
                logging.warning(
                    f"НЕДОСТАТОЧНО СРЕДСТВ. Требуется ~$ {total_cost:.2f}, доступно только ${free_balance:.2f}. Вход отменен.")
                return False
            return True
        except Exception as e:
            logging.error(f"Ошибка при проверке маржи: {e}", exc_info=True)
            return False

    def open_atomic_position(self, side, amount, positionIdx, price=None, sl_price=None, tp_price=None):
        """
        Атомарно открывает позицию с одновременной установкой TP/SL через единый запрос.
        Теперь принимает positionIdx.
        """
        order_type = 'market' if price is None else 'limit'
        logging.info(
            f"Попытка атомарного открытия позиции {side} {amount} {self.symbol} с positionIdx={positionIdx}...")

        # Используем переданный positionIdx
        params = {'category': 'linear', 'positionIdx': positionIdx}

        if sl_price:
            params['stopLoss'] = str(self.exchange.price_to_precision(self.symbol, sl_price))
        if tp_price:
            params['takeProfit'] = str(self.exchange.price_to_precision(self.symbol, tp_price))

        try:
            order = api_retry_wrapper(self.exchange.create_order,
                                      symbol=self.symbol, type=order_type, side=side, amount=amount,
                                      price=str(price) if price else None, params=params
                                      )
            logging.info(f"Успешно создан атомарный ордер для {self.symbol}. ID: {order['id']}")
            return order
        except ccxt.ExchangeError as e:
            logging.error(f"Ошибка биржи при создании атомарного ордера: {e}")
            return None
        except Exception as e:
            logging.error(f"Непредвиденная ошибка при создании атомарного ордера: {e}")
            return None

    def set_protection_for_existing_position(self, side, sl_price, tp_price=None):
        sl_price_str = self.exchange.price_to_precision(self.symbol, sl_price) if sl_price and sl_price != '0' else '0'
        tp_price_str = self.exchange.price_to_precision(self.symbol, tp_price) if tp_price and tp_price != '0' else '0'
        logging.info(
            f"Попытка установить/изменить защиту для {side.upper()}: SL: {sl_price_str}, TP: {tp_price_str}...")

        params = {
            'category': 'linear',
            'symbol': self.symbol.split(':')[0].replace('/', ''),
            'stopLoss': str(sl_price_str),
            'tpslMode': 'Full',
            'slTriggerBy': 'MarkPrice',
            'positionIdx': 0  # <-- Всегда 0 для UTA
        }
        if tp_price_str != '0':
            params['takeProfit'] = str(tp_price_str)

        try:
            api_retry_wrapper(self.exchange.private_post_v5_position_trading_stop, params)
            logging.info(f"Успешно установлена/изменена защита для {side.upper()}.")
            return True
        except ccxt.ExchangeError as e:
            if '110025' in str(e):
                logging.info(f"Цена защиты для {side.upper()} не изменилась, пропуск установки.")
                return True
            logging.error(f"Ошибка биржи при установке защиты для {side.upper()}: {e}")
            return False
        except Exception as e:
            logging.error(f"Непредвиденная ошибка при установке защиты для {side.upper()}: {e}")
            return False

    def _calculate_and_log_pnl(self, side, size_to_close):
        """
        Корректно рассчитывает PnL для Long и Short.
        """
        try:
            logging.info(f"Начинаю финальный расчет PnL для {side.upper()} позиции...")
            time.sleep(3)

            entry_order_id = self.long_entry_order_id if side == 'long' else self.short_entry_order_id
            if not entry_order_id:
                logging.warning(
                    f"Ошибка: entry_order_id для {side.upper()} не найден. Расчет PnL невозможен.")
                return

            entry_side_str = 'buy' if side == 'long' else 'sell'
            exit_side_str = 'sell' if side == 'long' else 'buy'
            direction = 1 if side == 'long' else -1

            entry_trade = None
            for i in range(3):
                all_initial_trades = api_retry_wrapper(self.exchange.fetch_my_trades, self.symbol, limit=20)
                entry_trade = next((t for t in all_initial_trades if t.get('order') == entry_order_id), None)
                if entry_trade: break
                time.sleep(2)

            if not entry_trade:
                logging.warning("Ошибка: не удалось найти сделку на вход по ID. Расчет PnL невозможен.")
                return

            entry_timestamp_ms = entry_trade['timestamp']
            session_trades = api_retry_wrapper(self.exchange.fetch_my_trades, self.symbol, since=entry_timestamp_ms,
                                               limit=1000)

            if not any(t['id'] == entry_trade['id'] for t in session_trades):
                session_trades.append(entry_trade)

            entry_trades = [t for t in session_trades if t['side'] == entry_side_str]
            exit_trades = [t for t in session_trades if t['side'] == exit_side_str]

            if not exit_trades:
                logging.warning(
                    f"Ошибка: не найдено ни одной сделки на выход ({exit_side_str}) для этой сессии.")
                return

            logging.info(
                f"Найдено {len(entry_trades)} сделок на вход ({entry_side_str}) и {len(exit_trades)} на выход ({exit_side_str}).")

            total_entry_cost = sum(t['cost'] for t in entry_trades)
            total_entry_fees = sum(t.get('fee', {}).get('cost', 0.0) for t in entry_trades)
            total_exit_revenue = sum(t['cost'] for t in exit_trades)
            total_exit_fees = sum(t.get('fee', {}).get('cost', 0.0) for t in exit_trades)

            gross_pnl = (total_exit_revenue - total_entry_cost) * direction

            total_funding_fees = sum(float(t.get('info', {}).get('funding', '0.0')) for t in session_trades)
            final_pnl = gross_pnl - total_entry_fees - total_exit_fees + total_funding_fees

            emoji = "✅" if final_pnl > 0 else "❌"
            logging.info(f"{emoji} *ФИНАЛЬНЫЙ РАСЧЕТ PNL ({side.upper()}) ЗАВЕРШЕН*")
            logging.info(
                f"Gross PnL: {gross_pnl:.4f}, Total Entry Fees: {total_entry_fees:.4f}, Total Exit Fees: {total_exit_fees:.4f}, Funding: {total_funding_fees:.4f}")
            logging.info(f"ИТОГОВЫЙ PNL по сделке: {final_pnl:.4f} USDT")

            self.update_and_save_state(side=None, last_trade_pnl=final_pnl)
            self._update_hwm_and_risk_capital()

        except Exception as e:
            logging.warning(f"Ошибка при финальном расчете PnL для {side.upper()}: {e}", exc_info=True)

    def reconcile_state_with_exchange(self):
        logging.info("Сверка состояния с биржей для Long и Short...")
        try:
            params = {'category': 'linear'}
            positions = api_retry_wrapper(self.exchange.fetch_positions, [self.symbol], params)

            long_pos_exchange = next(
                (p for p in positions if p.get('side') == 'long' and float(p.get('contracts', 0)) > 0), None)
            short_pos_exchange = next(
                (p for p in positions if p.get('side') == 'short' and float(p.get('contracts', 0)) > 0), None)

            # --- БЛОК 1: СВЕРКА LONG ПОЗИЦИИ ---
            if not long_pos_exchange and self.long_status == 'in_position':
                logging.warning("!!! РАССИНХРОН LONG !!! На бирже НЕТ long позиции, а локально ЕСТЬ.")
                is_tsl_closure = False
                data = None
                try:
                    data = get_market_data(self.exchange, self.symbol, self.long_params['timeframe'], self.long_params)
                    if data is not None and not data.empty:
                        last_low_price = data['low'].iloc[-1]
                        if self.long_stop_loss_price > 0 and last_low_price <= self.long_stop_loss_price:
                            if self.long_stop_loss_price > self.long_entry_price:
                                is_tsl_closure = True
                                logging.info(
                                    "Обнаружено вероятное закрытие LONG по ТРЕЙЛИНГ-СТОПУ (в прибыли). Кулдаун будет активирован.")
                except Exception as e:
                    logging.warning(f"Не удалось проверить причину закрытия LONG: {e}")
                self._calculate_and_log_pnl('long', self.long_position_size)
                if is_tsl_closure:
                    cooldown_candles = self.long_params.get('cooldown_period_candles', 0)
                    if cooldown_candles > 0 and data is not None and not data.empty:
                        last_candle_timestamp = data.index[-1].to_pydatetime()
                        logging.info(f"Активирую кулдаун для LONG на {cooldown_candles} свечи.")
                        self.update_and_save_state('long', last_tsl_exit_timestamp=last_candle_timestamp.isoformat())
                self.reset_long_state("Рассинхронизация: позиция закрыта на бирже")

            elif long_pos_exchange and self.long_status == 'idle':
                logging.warning(
                    "!!! РАССИНХРОН LONG !!! На бирже ЕСТЬ long позиция, а локально НЕТ. ПОПЫТКА СПАСЕНИЯ...")
                live_entry_price = float(long_pos_exchange['entryPrice'])
                try:
                    data = get_market_data(self.exchange, self.symbol, self.long_params['timeframe'], self.long_params)
                    if data is not None and not data.empty:
                        current_atr = data['atr'].iloc[-1]
                        sl_dist = current_atr * self.long_params.get('atr_stop_multiplier', 4.0)
                        sl_price_to_set = live_entry_price - sl_dist
                        if self.set_protection_for_existing_position('long', sl_price_to_set):
                            logging.info("!!! ПОЗИЦИЯ LONG УСПЕШНО СПАСЕНА И ЗАЩИЩЕНА !!!")
                            self.update_and_save_state('long', status='in_position',
                                                       position_size=float(long_pos_exchange['contracts']),
                                                       entry_price=live_entry_price, stop_loss_price=sl_price_to_set)
                        else:
                            raise Exception("Не удалось установить защиту при спасении.")
                    else:
                        raise Exception("Нет данных для расчета спасательного SL.")
                except Exception as e:
                    logging.error(f"!!! ПРОВАЛ СПАСЕНИЯ LONG: {e}. Аварийное закрытие.")
                    self.close_position('long', "Провал спасения потерянной позиции")

            elif long_pos_exchange and self.long_status == 'in_position':
                if self.long_entry_time:
                    try:
                        since_ts = int(self.long_entry_time.timestamp() * 1000)
                        ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.long_params['timeframe'], since=since_ts)
                        if ohlcv:
                            df_hist = pd.DataFrame(ohlcv,
                                                   columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                            true_max_price = df_hist['high'].max()
                            if true_max_price > self.long_max_price_since_entry:
                                logging.info(
                                    f"Восстановление max_price_since_entry для LONG: старое={self.long_max_price_since_entry}, новое={true_max_price}")
                                self.update_and_save_state('long', max_price_since_entry=true_max_price)
                    except Exception as e:
                        logging.warning(f"Не удалось восстановить max_price_since_entry для LONG: {e}")
                exchange_size = float(long_pos_exchange.get('contracts', 0))
                if not (abs(exchange_size - self.long_position_size) < 1e-9):
                    logging.warning(
                        f"!!! РАССИНХРОН РАЗМЕРА LONG !!! Локально: {self.long_position_size}, На бирже: {exchange_size}. Синхронизация.")
                    self.update_and_save_state('long', position_size=exchange_size)
                sl_on_exchange = float(long_pos_exchange.get('info', {}).get('stopLoss', '0'))
                if sl_on_exchange == 0 and self.long_stop_loss_price > 0:
                    logging.warning(
                        f"!!! LONG ПОЗИЦИЯ НЕЗАЩИЩЕНА !!! Попытка восстановить SL на {self.long_stop_loss_price}")
                    self.set_protection_for_existing_position('long', self.long_stop_loss_price)

            # --- БЛОК 2: СВЕРКА SHORT ПОЗИЦИИ ---
            if not short_pos_exchange and self.short_status == 'in_position':
                logging.warning("!!! РАССИНХРОН SHORT !!! На бирже НЕТ short позиции, а локально ЕСТЬ.")
                is_tsl_closure = False
                data = None
                try:
                    data = get_market_data(self.exchange, self.symbol, self.short_params['timeframe'],
                                           self.short_params)
                    if data is not None and not data.empty:
                        last_high_price = data['high'].iloc[-1]
                        if self.short_stop_loss_price > 0 and last_high_price >= self.short_stop_loss_price:
                            if self.short_stop_loss_price < self.short_entry_price:
                                is_tsl_closure = True
                                logging.info(
                                    "Обнаружено вероятное закрытие SHORT по ТРЕЙЛИНГ-СТОПУ (в прибыли). Кулдаун будет активирован.")
                except Exception as e:
                    logging.warning(f"Не удалось проверить причину закрытия SHORT: {e}")
                self._calculate_and_log_pnl('short', self.short_position_size)
                if is_tsl_closure:
                    cooldown_candles = self.short_params.get('cooldown_period_candles', 0)
                    if cooldown_candles > 0 and data is not None and not data.empty:
                        last_candle_timestamp = data.index[-1].to_pydatetime()
                        logging.info(f"Активирую кулдаун для SHORT на {cooldown_candles} свечи.")
                        self.update_and_save_state('short', last_tsl_exit_timestamp=last_candle_timestamp.isoformat())
                self.reset_short_state("Рассинхронизация: позиция закрыта на бирже")

            elif short_pos_exchange and self.short_status == 'idle':
                logging.warning(
                    "!!! РАССИНХРОН SHORT !!! На бирже ЕСТЬ short позиция, а локально НЕТ. ПОПЫТКА СПАСЕНИЯ...")
                live_entry_price = float(short_pos_exchange['entryPrice'])
                try:
                    data = get_market_data(self.exchange, self.symbol, self.short_params['timeframe'],
                                           self.short_params)
                    if data is not None and not data.empty:
                        current_atr = data['atr'].iloc[-1]
                        sl_dist = current_atr * self.short_params.get('atr_stop_multiplier', 2.63)
                        sl_price_to_set = live_entry_price + sl_dist
                        if self.set_protection_for_existing_position('short', sl_price_to_set):
                            logging.info("!!! ПОЗИЦИЯ SHORT УСПЕШНО СПАСЕНА И ЗАЩИЩЕНА !!!")
                            self.update_and_save_state('short', status='in_position',
                                                       position_size=float(short_pos_exchange['contracts']),
                                                       entry_price=live_entry_price, stop_loss_price=sl_price_to_set)
                        else:
                            raise Exception("Не удалось установить защиту при спасении.")
                    else:
                        raise Exception("Нет данных для расчета спасательного SL.")
                except Exception as e:
                    logging.error(f"!!! ПРОВАЛ СПАСЕНИЯ SHORT: {e}. Аварийное закрытие.")
                    self.close_position('short', "Провал спасения потерянной позиции")

            elif short_pos_exchange and self.short_status == 'in_position':
                if self.short_entry_time:
                    try:
                        since_ts = int(self.short_entry_time.timestamp() * 1000)
                        ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.short_params['timeframe'], since=since_ts)
                        if ohlcv:
                            df_hist = pd.DataFrame(ohlcv,
                                                   columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                            true_min_price = df_hist['low'].min()
                            if self.short_min_price_since_entry == 0 or true_min_price < self.short_min_price_since_entry:
                                logging.info(
                                    f"Восстановление min_price_since_entry для SHORT: старое={self.short_min_price_since_entry}, новое={true_min_price}")
                                self.update_and_save_state('short', min_price_since_entry=true_min_price)
                    except Exception as e:
                        logging.warning(f"Не удалось восстановить min_price_since_entry для SHORT: {e}")
                exchange_size = float(short_pos_exchange.get('contracts', 0))
                if not (abs(exchange_size - self.short_position_size) < 1e-9):
                    logging.warning(
                        f"!!! РАССИНХРОН РАЗМЕРА SHORT !!! Локально: {self.short_position_size}, На бирже: {exchange_size}. Синхронизация.")
                    self.update_and_save_state('short', position_size=exchange_size)
                sl_on_exchange = float(short_pos_exchange.get('info', {}).get('stopLoss', '0'))
                if sl_on_exchange == 0 and self.short_stop_loss_price > 0:
                    logging.warning(
                        f"!!! SHORT ПОЗИЦИЯ НЕЗАЩИЩЕНА !!! Попытка восстановить SL на {self.short_stop_loss_price}")
                    self.set_protection_for_existing_position('short', self.short_stop_loss_price)

        except Exception as e:
            logging.error(f"Критическая ошибка во время сверки состояния: {e}", exc_info=True)

    def _place_next_partial_tp(self, side):
        """
        УНИВЕРСАЛЬНАЯ функция для установки следующего частичного тейк-профита.
        """
        # --- 1. Установка контекста ---
        if side == 'long':
            params = self.long_params
            closes_count = self.long_partial_closes_count
            initial_size = self.long_initial_size
            position_size = self.long_position_size
            entry_price = self.long_entry_price
            atr_at_entry = self.long_atr_at_entry
            direction = 1
            side_str_close = 'sell'
            positionIdx = 1
        elif side == 'short':
            params = self.short_params
            closes_count = self.short_partial_closes_count
            initial_size = self.short_initial_size
            position_size = self.short_position_size
            entry_price = self.short_entry_price
            atr_at_entry = self.short_atr_at_entry
            direction = -1
            side_str_close = 'buy'
            positionIdx = 2
        else:
            return

        # --- 2. Ваша оригинальная логика, адаптированная под контекст ---
        if not params.get('partial_take_profit', False):
            return

        levels = params.get('partial_tp_levels', [])

        if closes_count >= len(levels):
            logging.info(f"Все уровни частичного тейк-профита для {side.upper()} отработаны.")
            return

        try:
            min_amount = float(self.market['limits']['amount']['min'])
            partial_fraction = params.get('partial_tp_fraction', 0.5)
            desired_size = initial_size * partial_fraction
            size_to_close = 0.0

            if desired_size >= min_amount:
                size_to_close = desired_size
            else:
                logging.warning(
                    f"Желаемый размер для частичного ТП {side.upper()} ({desired_size:.4f}) меньше минимального. Будет использован минимальный лот биржи ({min_amount}).")
                size_to_close = min_amount

            if size_to_close > position_size * 0.99:
                logging.info(
                    f"Размер для частичной фиксации {side.upper()} ({size_to_close:.4f}) почти равен остатку позиции ({position_size:.4f}). Частичная фиксация отменена.")
                return

            rounded_partial_size = float(self.exchange.amount_to_precision(self.symbol, size_to_close))

            if rounded_partial_size < min_amount:
                logging.error(
                    f"Ошибка! Размер для частичного ТП {side.upper()} ({rounded_partial_size}) меньше минимального. Фиксация отменена.")
                return

            next_level_multiplier = levels[closes_count]
            # --- ИНВЕРСИЯ ---
            partial_tp_price_calc = entry_price + (atr_at_entry * next_level_multiplier * direction)
            partial_tp_price = self.exchange.price_to_precision(self.symbol, partial_tp_price_calc)

            logging.info(
                f"Установка частичного TP #{closes_count + 1} для {side.upper()}. Цена: {partial_tp_price}, Размер: {rounded_partial_size}")

            params_ptp = {'reduceOnly': True, 'category': 'linear', 'positionIdx': 0}
            ptp_order = api_retry_wrapper(self.exchange.create_limit_order, self.symbol, side_str_close,
                                          rounded_partial_size, partial_tp_price, params_ptp)

            self.update_and_save_state(side, partial_tp_order_id=ptp_order['id'])
            logging.info(
                f"Частичный TP ордер #{closes_count + 1} для {side.upper()} успешно установлен. ID: {ptp_order['id']}")

        except Exception as e:
            logging.error(f"Не удалось установить следующий частичный TP для {side.upper()}: {e}", exc_info=True)

    def handle_partial_close(self, side, exit_trade):
        """
        УНИВЕРСАЛЬНАЯ функция для обработки сработавшего частичного тейк-профита.
        """
        # --- 1. Установка контекста ---
        if side == 'long':
            entry_price = self.long_entry_price
            position_size = self.long_position_size
            entry_fee = self.long_entry_fee
            partial_closes_count = self.long_partial_closes_count
            direction = 1
        elif side == 'short':
            entry_price = self.short_entry_price
            position_size = self.short_position_size
            entry_fee = self.short_entry_fee
            partial_closes_count = self.short_partial_closes_count
            direction = -1
        else:
            return

        # --- 2. Оригинальная логика, адаптированная под контекст ---
        exit_price = float(exit_trade['price'])
        closed_size = float(exit_trade['amount'])
        exit_fee_cost = float(exit_trade.get('fee', {}).get('cost', 0.0))

        logging.info(f"ЧАСТИЧНЫЙ ТЕЙК-ПРОФИТ для {side.upper()} сработал: {closed_size} Qty по цене {exit_price}.")

        try:
            new_closes_count = partial_closes_count + 1
            full_position_size_before_partial = position_size + closed_size  # Восстанавливаем размер до закрытия

            if full_position_size_before_partial == 0:
                logging.error(f"Ошибка в handle_partial_close для {side.upper()}: размер позиции до закрытия равен 0.")
                return

            entry_fee_for_this_part = entry_fee * (closed_size / full_position_size_before_partial)

            # --- ИНВЕРСИЯ PNL ---
            net_pnl_partial = (
                                          exit_price - entry_price) * closed_size * direction - exit_fee_cost - entry_fee_for_this_part
            new_total_pnl = self.last_trade_pnl + net_pnl_partial

            self.update_and_save_state(
                side,
                is_partially_closed=True,
                last_trade_pnl=new_total_pnl,
                position_size=position_size - closed_size,
                entry_fee=entry_fee - entry_fee_for_this_part,
                partial_tp_order_id=None,
                partial_closes_count=new_closes_count
            )
            logging.info(
                f"PnL частичной фиксации ({side.upper()}): {net_pnl_partial:.4f} USDT. "
                f"Оставшийся размер: {self.long_position_size if side == 'long' else self.short_position_size:.4f}"
            )
            # Запускаем установку следующего ТП для той же стороны
            self._place_next_partial_tp(side)

        except Exception as e:
            logging.error(f"Ошибка перестройки позиции {side.upper()} после частичного ТП: {e}", exc_info=True)
            self.close_position(side, "Ошибка в handle_partial_close")


def main():
    """Главный цикл, который запускает и перезапускает бота."""
    exchange = connect_to_bybit()
    if not exchange: return

    log_initial_balance(exchange)

    if LONG_PARAMS.get('symbol') != SHORT_PARAMS.get('symbol'):
        logging.error("КРИТИЧЕСКАЯ ОШИБКА: Символы в long и short конфигах не совпадают!")
        return
    symbol = LONG_PARAMS.get('symbol')
    if not symbol:
        logging.error("КРИТИЧЕСКАЯ ОШИБКА: Символ не указан в файлах конфигурации!")
        return

    ws_manager = WebSocketManager(symbol)
    ws_manager.start()
    time.sleep(5)

    manager = PositionManager(exchange, symbol, LONG_PARAMS, SHORT_PARAMS, ws_manager)

    while True:
        try:
            # Вызываем главный контроллер
            manager.check_and_manage_position()
            # Быстрый цикл
            time.sleep(0.2)
        except KeyboardInterrupt:
            logging.info("Получен сигнал на остановку. Завершение работы...")
            if manager.long_status == 'in_position':
                manager.close_position('long', "Ручная остановка")
            if manager.short_status == 'in_position':
                manager.close_position('short', "Ручная остановка")
            break
        except Exception as e:
            logging.error(f"Критическая ошибка в главном цикле: {e}", exc_info=True)
            time.sleep(60)

    ws_manager.stop()


if __name__ == '__main__':
    main()
