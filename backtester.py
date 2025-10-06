import numpy as np
import pandas as pd
from config import TRADES_DIR, CAPITAL, COMMISSION, SLIPPAGE
import logging
from numba import jit, float64, int8, boolean, int64
from datetime import datetime

# Suppress Numba's verbose debug output
numba_logger = logging.getLogger('numba')
numba_logger.setLevel(logging.WARNING)


@jit(nopython=True)
def process_positions(signals, close, high, low, atr, rsi,
                      commission, partial_take_profit,
                      tp_atr_multiplier,
                      atr_stop_multiplier,
                      risk_per_trade, cooldown_period_candles,
                      breakeven_atr_multiplier, leverage, min_amount_precision, trail_atr_multiplier,
                      stagnation_atr_threshold, stagnation_profit_decay, trail_early_activation_atr_multiplier,
                      grid_upper_rsi, grid_lower_rsi, aggressive_trail_atr_multiplier, capital, slippage, partial_fraction,
                      n_partial_levels, partial_levels, position_scaling, max_position_multiplier,
                      scale_add_atr_multiplier,
                      profit_lock_trigger_pct, profit_lock_target_pct, aggressive_breakout_stop_multiplier):
    """
    (EN) Core backtesting loop, JIT-compiled with Numba for performance.
    Iterates through market data, managing position state (entry, exits, SL/TP, scaling)
    and calculating trade outcomes based on the provided signals and strategy parameters.

    (RU) Основной цикл бэктестинга, JIT-компилированный с помощью Numba для производительности.
    Итерируется по рыночным данным, управляя состоянием позиции (вход, выходы, SL/TP, пирамидинг)
    и рассчитывая результаты сделок на основе поданных сигналов и параметров стратегии.

    Args:
        signals (np.array): Array of trading signals (1: long, -1: short, 10: exit long, -10: exit short).
        close (np.array): Array of closing prices.
        high (np.array): Array of high prices.
        low (np.array): Array of low prices.
        atr (np.array): Array of ATR indicator values.
        rsi (np.array): Array of RSI indicator values.
        *args: Various float and int strategy parameters.

    Returns:
        tuple: A tuple of NumPy arrays containing details for each executed trade
               (entry/exit indices, prices, returns, sizes, exit reasons).
    """
    n = len(signals)
    max_positions = n * 5
    entry_indices = np.zeros(max_positions, dtype=int64)
    exit_indices = np.zeros(max_positions, dtype=int64)
    entry_prices = np.zeros(max_positions, dtype=float64)
    exit_prices = np.zeros(max_positions, dtype=float64)
    returns = np.zeros(max_positions, dtype=float64)
    position_sizes = np.zeros(max_positions, dtype=float64)
    large_trade_flags = np.zeros(max_positions, dtype=boolean)
    exit_reasons = np.zeros(max_positions, dtype=int8)
    pos_count = 0

    in_long_position = False
    in_short_position = False
    cooldown_until_index = 0
    entry_idx = 0
    entry_price = 0.0
    entry_time = 0
    max_price = 0.0
    min_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    current_size = 0.0
    initial_size = 0.0
    initial_entry_fee = 0.0
    max_pos_size = 0.0
    last_add_price = 0.0
    partial_levels_prices = np.empty(n_partial_levels if n_partial_levels > 0 else 1, dtype=float64)
    position_pnl = 0.0
    entry_fee = 0.0
    atr_at_entry = 0.0
    is_breakeven_set = False
    is_trailing_active = False
    max_pnl_in_trade = 0.0
    is_stagnation_armed = False

    taker_fee = commission
    current_capital = capital
    risk_capital_base = capital
    high_water_mark = capital

    for i in range(n):
        is_cooldown_override_trade = False
        if not in_long_position and not in_short_position:
            # --- БЛОК ВХОДА В ПОЗИЦИЮ/POSITION ENTRY BLOCK  ---
            if i < cooldown_until_index:
                if (signals[i] == 1 and i > 0 and close[i] > high[i - 1]):
                    is_cooldown_override_trade = True
                elif (signals[i] == -1 and i > 0 and close[i] < low[i - 1]):
                    is_cooldown_override_trade = True
                else:
                    continue

            current_drawdown = (high_water_mark - current_capital) / high_water_mark
            risk_governor_factor = 1.0
            if current_drawdown > 0.4:
                risk_governor_factor = 0.25
            elif current_drawdown > 0.3:
                risk_governor_factor = 0.35
            elif current_drawdown > 0.2:
                risk_governor_factor = 0.50
            elif current_drawdown > 0.1:
                risk_governor_factor = 0.75
            base_risk_amount = risk_capital_base * risk_per_trade
            risk_amount = base_risk_amount * risk_governor_factor

            if signals[i] == 1:
                if rsi[i] > grid_upper_rsi: continue
                in_long_position = True
                entry_idx = i
                entry_price = close[i] * (1 + slippage)
                atr_at_entry = atr[i]
                if aggressive_breakout_stop_multiplier > 0 and is_cooldown_override_trade:
                    distance_to_low = entry_price - low[i]
                    if distance_to_low > 0:
                        stop_loss_distance = distance_to_low * aggressive_breakout_stop_multiplier
                        stop_loss = entry_price - stop_loss_distance
                    else:  # Если low выше цены входа, используем стандартный стоп/If low is higher than entry price, use the standard stop
                        stop_loss_distance = atr_at_entry * atr_stop_multiplier
                        stop_loss = entry_price - stop_loss_distance
                else:
                    stop_loss_distance = atr_at_entry * atr_stop_multiplier
                    stop_loss = entry_price - stop_loss_distance

                if stop_loss_distance <= 0:
                    in_long_position = False
                    continue

                base_position_size = risk_amount / stop_loss_distance
                rounded_size = np.floor(base_position_size / min_amount_precision) * min_amount_precision
                if rounded_size < min_amount_precision:
                    in_long_position = False
                    continue

                # Инициализация всех переменных состояния для НОВОЙ LONG сделки/Initialize all state variables for a NEW LONG trade
                initial_size = rounded_size
                current_size = rounded_size
                max_pos_size = initial_size * max_position_multiplier
                initial_entry_fee = current_size * entry_price * taker_fee
                entry_fee = initial_entry_fee
                max_price = entry_price
                last_add_price = entry_price
                is_breakeven_set = False
                is_trailing_active = False
                max_pnl_in_trade = 0.0
                is_stagnation_armed = False
                take_profit = entry_price + (atr_at_entry * tp_atr_multiplier)
                for j in range(n_partial_levels):
                    partial_levels_prices[j] = entry_price + (atr_at_entry * partial_levels[j])
                continue

            elif signals[i] == -1:
                # --- ЛОГИКА ВХОДА В SHORT/SHORT ENTRY LOGIC ---
                if rsi[i] < grid_lower_rsi:
                    continue
                in_short_position = True
                entry_idx = i
                entry_price = close[i] * (1 - slippage)
                atr_at_entry = atr[i]
                if aggressive_breakout_stop_multiplier > 0 and is_cooldown_override_trade:
                    distance_to_high = high[i] - entry_price
                    if distance_to_high > 0:
                        stop_loss_distance = distance_to_high * aggressive_breakout_stop_multiplier
                        stop_loss = entry_price + stop_loss_distance
                    else:  # Если high ниже цены входа, используем стандартный стоп/If high is lower than entry price, use the standard stop
                        stop_loss_distance = atr_at_entry * atr_stop_multiplier
                        stop_loss = entry_price + stop_loss_distance
                else:
                    stop_loss_distance = atr_at_entry * atr_stop_multiplier
                    stop_loss = entry_price + stop_loss_distance
                if stop_loss_distance <= 0:
                    in_short_position = False
                    continue
                base_position_size = risk_amount / stop_loss_distance
                rounded_size = np.floor(base_position_size / min_amount_precision) * min_amount_precision
                if rounded_size < min_amount_precision:
                    in_short_position = False
                    continue
                # Инициализация всех переменных состояния для НОВОЙ SHORT сделки/Initialize all state variables for a NEW SHORT trade
                initial_size = rounded_size
                current_size = rounded_size
                max_pos_size = initial_size * max_position_multiplier
                initial_entry_fee = current_size * entry_price * taker_fee
                entry_fee = initial_entry_fee
                min_price = entry_price
                last_add_price = entry_price
                is_breakeven_set = False
                is_trailing_active = False
                max_pnl_in_trade = 0.0
                is_stagnation_armed = False
                take_profit = entry_price - (atr_at_entry * tp_atr_multiplier)
                for j in range(n_partial_levels):
                    partial_levels_prices[j] = entry_price - (atr_at_entry * partial_levels[j])
                continue

        # --- УПРАВЛЕНИЕ LONG ПОЗИЦИЕЙ/LONG POSITION MANAGEMENT ---
        if in_long_position:
            # 1. ЧАСТИЧНЫЕ ВЫХОДЫ/PARTIAL EXITS
            partial_exit_occurred = False
            if partial_take_profit and n_partial_levels > 0:
                for j in range(n_partial_levels):
                    if not np.isnan(partial_levels_prices[j]) and close[i] >= partial_levels_prices[j]:
                        closed_size = initial_size * partial_fraction
                        rounded_closed_size = np.floor(closed_size / min_amount_precision) * min_amount_precision

                        if rounded_closed_size >= min_amount_precision and current_size - rounded_closed_size > -min_amount_precision:
                            exit_price = close[i] * (1 - slippage)
                            entry_fee_part = initial_entry_fee * (rounded_closed_size / initial_size)
                            gross_pnl = (exit_price - entry_price) * rounded_closed_size
                            exit_fee = rounded_closed_size * exit_price * taker_fee
                            net_pnl = gross_pnl - entry_fee_part - exit_fee

                            entry_indices[pos_count], exit_indices[pos_count], entry_prices[pos_count], exit_prices[
                                pos_count], returns[pos_count], position_sizes[pos_count], exit_reasons[pos_count] = \
                                entry_idx, i, entry_price, exit_price, net_pnl / current_capital, rounded_closed_size, 3
                            pos_count += 1

                            current_capital += net_pnl
                            current_size -= rounded_closed_size
                            entry_fee -= entry_fee_part
                            partial_levels_prices[j] = np.nan
                            partial_exit_occurred = True

            if partial_exit_occurred:
                if current_size < min_amount_precision:
                    in_long_position = False
                    if current_capital > high_water_mark: high_water_mark = current_capital
                continue

            # 2. ПИРАМИДИНГ (если не было частичного выхода на этой свече)/PYRAMIDING (if no partial exit on this candle)
            if position_scaling and (is_breakeven_set or is_trailing_active) and signals[
                i] == 1 and current_size < max_pos_size:
                if close[i] >= last_add_price + (scale_add_atr_multiplier * atr[i]):
                    add_size = initial_size
                    max_add_allowed = max_pos_size - current_size
                    if add_size > max_add_allowed: add_size = max_add_allowed
                    rounded_add = np.floor(add_size / min_amount_precision) * min_amount_precision
                    if rounded_add >= min_amount_precision:
                        add_price = close[i] * (1 + slippage)
                        add_margin = (rounded_add * add_price) / leverage
                        add_fee = rounded_add * add_price * taker_fee
                        total_add_cost = (add_margin + add_fee) * 1.05  # Используем буфер 5%/Use a 5% buffer
                        # Если капитала достаточно, выполняем добавление/If capital is sufficient, execute the addition
                        if total_add_cost <= current_capital:
                            entry_value = (entry_price * current_size) + (add_price * rounded_add)
                            current_size += rounded_add
                            entry_price = entry_value / current_size  # Усредняем цену входа/Averaging the entry price
                            entry_fee += add_fee
                            initial_entry_fee += add_fee
                            max_price = max(max_price, add_price)
                            last_add_price = add_price
                        # Если капитала не хватает, добаление просто пропускается/If capital is insufficient, the addition is simply skipped

            # 3. УПРАВЛЕНИЕ ОСТАТКОМ И ПОЛНЫЕ ВЫХОДЫ/REMAINDER MANAGEMENT AND FULL EXITS
            if not is_breakeven_set and breakeven_atr_multiplier > 0:
                breakeven_trigger_price = entry_price + (atr_at_entry * breakeven_atr_multiplier)
                if close[i] >= breakeven_trigger_price:
                    total_commission_per_unit = (initial_entry_fee / initial_size) * 2
                    breakeven_plus_price = entry_price + total_commission_per_unit
                    stop_loss = breakeven_plus_price
                    is_breakeven_set = True

            # <-- ЗАМОК НА ПРИБЫЛЬ (PROFIT LOCK) -->
            if profit_lock_trigger_pct > 0 and not is_breakeven_set:
                trigger_price = entry_price * (1 + profit_lock_trigger_pct)
                if close[i] >= trigger_price:
                    target_stop_price = entry_price * (1 + profit_lock_target_pct)
                    if target_stop_price > stop_loss:
                        stop_loss = target_stop_price

            max_price = max(max_price, high[i])

            should_trail = is_breakeven_set or is_trailing_active
            if not should_trail and atr_at_entry > 0:
                trail_early_activation_price = entry_price + (atr_at_entry * trail_early_activation_atr_multiplier)
                if close[i] > trail_early_activation_price: should_trail = True

            if should_trail:
                if is_breakeven_set:
                    multiplier = aggressive_trail_atr_multiplier
                elif max_pnl_in_trade > (2.0 * atr_at_entry * initial_size):
                    multiplier = trail_atr_multiplier * 0.7
                else:
                    multiplier = trail_atr_multiplier
                chandelier_stop = max_price - (atr[i] * multiplier)
                if chandelier_stop > stop_loss:
                    stop_loss = chandelier_stop
                    is_trailing_active = True

            stagnation_exit = False
            current_pnl = (close[i] - entry_price) * current_size
            if current_pnl > max_pnl_in_trade: max_pnl_in_trade = current_pnl
            if not is_stagnation_armed and is_trailing_active and max_pnl_in_trade > (
                    atr_at_entry * stagnation_atr_threshold * initial_size):
                is_stagnation_armed = True
            if is_stagnation_armed and current_pnl < (max_pnl_in_trade * stagnation_profit_decay):
                stagnation_exit = True

            price_below_stop = close[i] < stop_loss
            price_above_tp = close[i] >= take_profit
            exit_by_signal = signals[i] == 10 and is_breakeven_set

            if price_below_stop or price_above_tp or exit_by_signal or stagnation_exit:
                exit_price = close[i] * (1 - slippage)
                closed_size = current_size
                entry_fee_part = entry_fee
                gross_pnl = (exit_price - entry_price) * closed_size
                exit_fee = closed_size * exit_price * taker_fee
                net_pnl = gross_pnl - entry_fee_part - exit_fee

                entry_indices[pos_count], exit_indices[pos_count], entry_prices[pos_count], exit_prices[pos_count], \
                returns[pos_count], position_sizes[pos_count] = \
                    entry_idx, i, entry_price, exit_price, net_pnl / current_capital, closed_size

                exit_reason_code = 6
                if price_below_stop:
                    if is_trailing_active:
                        exit_reason_code = 4
                    elif is_breakeven_set:
                        exit_reason_code = 7
                    else:
                        exit_reason_code = 1
                elif price_above_tp:
                    exit_reason_code = 2
                elif exit_by_signal:
                    exit_reason_code = 5
                exit_reasons[pos_count] = exit_reason_code
                pos_count += 1

                if exit_reason_code == 4 or exit_reason_code == 7:
                    cooldown_until_index = i + max(1, cooldown_period_candles)

                current_capital += net_pnl
                in_long_position = False
                if current_capital > high_water_mark:
                    high_water_mark = current_capital
                    risk_capital_base = high_water_mark

        elif in_short_position:
            # 1. ЧАСТИЧНЫЕ ВЫХОДЫ (ЗЕРКАЛЬНО)/PARTIAL EXITS (MIRRORED)
            partial_exit_occurred = False
            if partial_take_profit and n_partial_levels > 0:
                for j in range(n_partial_levels):
                    if not np.isnan(partial_levels_prices[j]) and close[i] <= partial_levels_prices[j]:
                        closed_size = initial_size * partial_fraction
                        rounded_closed_size = np.floor(closed_size / min_amount_precision) * min_amount_precision

                        if rounded_closed_size >= min_amount_precision and current_size - rounded_closed_size > -min_amount_precision:
                            exit_price = close[i] * (1 + slippage)
                            entry_fee_part = initial_entry_fee * (rounded_closed_size / initial_size)
                            gross_pnl = (entry_price - exit_price) * rounded_closed_size
                            exit_fee = rounded_closed_size * exit_price * taker_fee
                            net_pnl = gross_pnl - entry_fee_part - exit_fee

                            entry_indices[pos_count], exit_indices[pos_count], entry_prices[pos_count], exit_prices[
                                pos_count], returns[pos_count], position_sizes[pos_count], exit_reasons[pos_count] = \
                                entry_idx, i, entry_price, exit_price, net_pnl / current_capital, rounded_closed_size, 3
                            pos_count += 1

                            current_capital += net_pnl
                            current_size -= rounded_closed_size
                            entry_fee -= entry_fee_part
                            partial_levels_prices[j] = np.nan
                            partial_exit_occurred = True

            if partial_exit_occurred:
                if current_size < min_amount_precision:
                    in_short_position = False
                    if current_capital > high_water_mark: high_water_mark = current_capital
                continue

            # 2. ПИРАМИДИНГ (ЗЕРКАЛЬНО)/PYRAMIDING (MIRRORED)
            if position_scaling and (is_breakeven_set or is_trailing_active) and signals[
                i] == -1 and current_size < max_pos_size:
                if close[i] <= last_add_price - (scale_add_atr_multiplier * atr[i]):
                    add_size = initial_size
                    max_add_allowed = max_pos_size - current_size
                    if add_size > max_add_allowed: add_size = max_add_allowed
                    rounded_add = np.floor(add_size / min_amount_precision) * min_amount_precision
                    if rounded_add >= min_amount_precision:
                        add_price = close[i] * (
                                    1 + slippage)

                        add_margin = (rounded_add * add_price) / leverage
                        add_fee = rounded_add * add_price * taker_fee
                        total_add_cost = (add_margin + add_fee) * 1.05
                        # Если капитала достаточно, выполняем добавление/If capital is sufficient, execute the addition
                        if total_add_cost <= current_capital:
                            entry_value = (entry_price * current_size) + (add_price * rounded_add)
                            current_size += rounded_add
                            entry_price = entry_value / current_size
                            entry_fee += add_fee
                            initial_entry_fee += add_fee
                            min_price = min(min_price, add_price)
                            last_add_price = add_price

            # 3. УПРАВЛЕНИЕ ОСТАТКОМ И ПОЛНЫЕ ВЫХОДЫ (ЗЕРКАЛЬНО)/REMAINDER MANAGEMENT AND FULL EXITS (MIRRORED)
            if not is_breakeven_set and breakeven_atr_multiplier > 0:
                breakeven_trigger_price = entry_price - (atr_at_entry * breakeven_atr_multiplier)
                if close[i] <= breakeven_trigger_price:
                    total_commission_per_unit = (initial_entry_fee / initial_size) * 2
                    breakeven_plus_price = entry_price - total_commission_per_unit
                    stop_loss = breakeven_plus_price
                    is_breakeven_set = True

            # <-- ЗАМОК НА ПРИБЫЛЬ (PROFIT LOCK) ДЛЯ SHORT -->
            if profit_lock_trigger_pct > 0 and not is_breakeven_set:
                trigger_price = entry_price * (1 - profit_lock_trigger_pct)
                if close[i] <= trigger_price:
                    target_stop_price = entry_price * (1 - profit_lock_target_pct)
                    if target_stop_price < stop_loss:
                        stop_loss = target_stop_price

            min_price = min(min_price, low[i])

            should_trail = is_breakeven_set or is_trailing_active
            if not should_trail and atr_at_entry > 0:
                trail_early_activation_price = entry_price - (atr_at_entry * trail_early_activation_atr_multiplier)
                if close[i] < trail_early_activation_price: should_trail = True

            if should_trail:
                if is_breakeven_set:
                    multiplier = aggressive_trail_atr_multiplier
                elif max_pnl_in_trade > (2.0 * atr_at_entry * initial_size):
                    multiplier = trail_atr_multiplier * 0.7
                else:
                    multiplier = trail_atr_multiplier
                chandelier_stop = min_price + (atr[i] * multiplier)
                if chandelier_stop < stop_loss:
                    stop_loss = chandelier_stop
                    is_trailing_active = True

            stagnation_exit = False
            current_pnl = (entry_price - close[i]) * current_size
            if current_pnl > max_pnl_in_trade: max_pnl_in_trade = current_pnl
            if not is_stagnation_armed and is_trailing_active and max_pnl_in_trade > (
                    atr_at_entry * stagnation_atr_threshold * initial_size):
                is_stagnation_armed = True
            if is_stagnation_armed and current_pnl < (max_pnl_in_trade * stagnation_profit_decay):
                stagnation_exit = True

            price_above_stop = close[i] > stop_loss
            price_below_tp = close[i] <= take_profit
            exit_by_signal = signals[i] == -10 and is_breakeven_set

            if price_above_stop or price_below_tp or exit_by_signal or stagnation_exit:
                exit_price = close[i] * (1 + slippage)
                closed_size = current_size
                entry_fee_part = entry_fee
                gross_pnl = (entry_price - exit_price) * closed_size
                exit_fee = closed_size * exit_price * taker_fee
                net_pnl = gross_pnl - entry_fee_part - exit_fee

                entry_indices[pos_count], exit_indices[pos_count], entry_prices[pos_count], exit_prices[pos_count], \
                returns[pos_count], position_sizes[pos_count] = \
                    entry_idx, i, entry_price, exit_price, net_pnl / current_capital, closed_size

                exit_reason_code = 6
                if price_above_stop:
                    if is_trailing_active:
                        exit_reason_code = 4
                    elif is_breakeven_set:
                        exit_reason_code = 7
                    else:
                        exit_reason_code = 1
                elif price_below_tp:
                    exit_reason_code = 2
                elif exit_by_signal:
                    exit_reason_code = 5
                exit_reasons[pos_count] = exit_reason_code
                pos_count += 1

                if exit_reason_code == 4 or exit_reason_code == 7:
                    cooldown_until_index = i + max(1, cooldown_period_candles)

                current_capital += net_pnl
                in_short_position = False
                if current_capital > high_water_mark:
                    high_water_mark = current_capital
                    risk_capital_base = high_water_mark

    return (entry_indices[:pos_count], exit_indices[:pos_count],
            entry_prices[:pos_count], exit_prices[:pos_count],
            returns[:pos_count], position_sizes[:pos_count],
            large_trade_flags[:pos_count], exit_reasons[:pos_count])

def generate_signals(df, params):
    """
    (EN) Generates trading signals based on the strategy 'mode' specified in the params.

    (RU) Генерирует торговые сигналы на основе режима 'mode' стратегии, указанного в параметрах.

    Args:
        df (pd.DataFrame): DataFrame with OHLCV data and required indicators.
        params (dict): A dictionary containing strategy parameters, including the 'mode'
                       ('long_only', 'short_only', etc.).
    Returns:
        pd.DataFrame: The original DataFrame with an added 'signal' column.
    """
    try:
        df = df.copy()
        mode = params.get('mode', 'long_only')

        if 'close' not in df.columns:
            raise ValueError("DataFrame must contain 'close' column.")
        if mode in ['long_only'] and 'ema_regime' not in df.columns:
            raise ValueError(f"For mode '{mode}', DataFrame must contain 'ema_regime' column.")

        signals = np.zeros(len(df), dtype=np.int8)

        if mode == 'long_only':
            if 'ema_regime' not in df.columns or 'ema_macro' not in df.columns:
                raise ValueError("Для long_only необходимы индикаторы ema_regime и ema_macro.")
            is_tactical_bull = (df['close'] > df['ema_regime'])
            is_macro_bull = (df['close'] > df['ema_macro'])
            long_entry_state = is_tactical_bull & is_macro_bull
            signals[long_entry_state] = 1
            exit_rsi = params.get('grid_upper_rsi', 75)
            long_exit_event = (df['rsi'] > exit_rsi)
            signals[long_exit_event] = 10
        elif mode == 'short_only':
            required_indicators = ['ema_regime', 'ema_macro', 'rsi']
            if params.get('adx_period', 0) > 0:
                required_indicators.append('adx')
            if not all(col in df.columns for col in required_indicators):
                raise ValueError(f"Для short_only необходимы индикаторы: {required_indicators}.")
            is_tactical_bear = (df['close'] < df['ema_regime'])
            is_macro_bear = (df['close'] < df['ema_macro'])
            adx_threshold = params.get('adx_threshold', 25)
            is_strong_trend = (df['adx'] > adx_threshold) if 'adx' in df.columns else True
            short_entry_state = is_tactical_bear & is_macro_bear & is_strong_trend
            signals[short_entry_state] = -1
            exit_rsi_low = params.get('grid_lower_rsi', 25)
            short_exit_event = (df['rsi'] < exit_rsi_low)
            signals[short_exit_event] = -10
        elif mode == 'short_scalp':
            required = ['ema_medium', 'bb_upper', 'bb_middle', 'bb_lower']
            if not all(col in df.columns for col in required):
                raise ValueError("Для скальпинг-стратегии необходимы индикаторы ema_medium и Bollinger Bands.")
            long_entry = (df['close'] > df['ema_medium']) & (df['close'] < df['bb_lower'])
            signals[long_entry] = 1
            long_exit = (df['close'] > df['bb_middle'])
            signals[long_exit] = 10
            short_entry = (df['close'] < df['ema_medium']) & (df['close'] > df['bb_upper'])
            signals[short_entry] = -1
            short_exit = (df['close'] < df['bb_middle'])
            signals[short_exit] = -10

        df['signal'] = signals
        return df
    except Exception as e:
        logging.error(f"Error in generate_signals: {str(e)}", exc_info=True)
        raise


def backtest(df, params, trial_number=None, run_timestamp=None, period="unknown", save_trades=True):
    try:
        df = df.copy()
        signals = df['signal'].to_numpy(dtype=np.int8)
        close = df['close'].to_numpy(dtype=np.float64)
        high = df['high'].to_numpy(dtype=np.float64)
        low = df['low'].to_numpy(dtype=np.float64)
        atr = df['atr'].to_numpy(dtype=np.float64)
        rsi = df['rsi'].to_numpy(dtype=np.float64)

        cooldown_period_candles = max(1, int(params.get('cooldown_period_candles', 0)))
        breakeven_atr_multiplier = float(params.get('breakeven_atr_multiplier', 0))

        capital = CAPITAL
        commission = COMMISSION
        slippage = SLIPPAGE

        atr_stop_multiplier = params.get('atr_stop_multiplier', 4.0)
        partial_take_profit = params.get('partial_take_profit', True)
        risk_per_trade = params.get('risk_per_trade', 0.03)
        tp_atr_multiplier = params.get('tp_atr_multiplier', 8.0)
        leverage = params.get('leverage', 10)
        min_amount_precision = params.get('min_amount_precision', 0.1)
        trail_atr_multiplier = params.get('trail_atr_multiplier', 3.0)
        stagnation_atr_threshold = params.get('stagnation_atr_threshold', 3.0)
        stagnation_profit_decay = params.get('stagnation_profit_decay', 0.7)
        trail_early_activation_atr_multiplier = params.get('trail_early_activation_atr_multiplier', 1.0)
        grid_upper_rsi = params.get('grid_upper_rsi', 76)
        grid_lower_rsi = params.get('grid_lower_rsi', 24)
        aggressive_trail_atr_multiplier = params.get('aggressive_trail_atr_multiplier', 1.5)
        profit_lock_trigger_pct = params.get('profit_lock_trigger_pct', 0.0)
        profit_lock_target_pct = params.get('profit_lock_target_pct', 0.0)
        partial_fraction = params.get('partial_tp_fraction', 0.5)
        aggressive_breakout_stop_multiplier = params.get('aggressive_breakout_stop_multiplier', 0.0)

        # --- подготовка multi-level partial TP и scaling params/Prepare multi-level partial TP and scaling params ---
        partial_tp_levels_list = params.get('partial_tp_levels', [1.0, 2.0, 3.0])
        n_partial_levels = len(partial_tp_levels_list)
        partial_levels = np.array(partial_tp_levels_list, dtype=np.float64)
        position_scaling = bool(params.get('position_scaling', False))
        max_position_multiplier = float(params.get('max_position_multiplier', 2.0))
        scale_add_atr_multiplier = float(params.get('scale_add_atr_multiplier', 0.5))

        result = process_positions(
            signals, close, high, low, atr, rsi,
            commission, partial_take_profit,
            tp_atr_multiplier,
            atr_stop_multiplier,
            risk_per_trade, cooldown_period_candles,
            breakeven_atr_multiplier, leverage, min_amount_precision, trail_atr_multiplier,
            stagnation_atr_threshold, stagnation_profit_decay, trail_early_activation_atr_multiplier, grid_upper_rsi,
            grid_lower_rsi, aggressive_trail_atr_multiplier,
            capital, slippage, partial_fraction,
            n_partial_levels, partial_levels, position_scaling, max_position_multiplier, scale_add_atr_multiplier,
            profit_lock_trigger_pct, profit_lock_target_pct, aggressive_breakout_stop_multiplier
        )

        (entry_indices, exit_indices, entry_prices, exit_prices,
         returns, position_sizes, large_trade_flags, exit_reasons) = result

        if len(entry_indices) == 0:
            logging.debug("No trades executed")
            return None

        # --- СЛОВАРЬ ПРИЧИН ВЫХОДА/EXIT REASON DICTIONARY ---
        reason_map = {
            1: 'stop_loss',
            2: 'take_profit',
            3: 'partial_take_profit',
            4: 'trailing_stop',
            5: 'sell_signal',
            6: 'stagnation_exit',
            7: 'breakeven_stop'
        }

        exit_reasons_str = [reason_map.get(reason, 'unknown') for reason in exit_reasons]

        trades = pd.DataFrame({
            'entry_time': df.index[entry_indices],
            'exit_time': df.index[exit_indices],
            'entry_price': entry_prices,
            'exit_price': exit_prices,
            'returns': returns,
            'position_size': position_sizes,
            'large_trade': large_trade_flags,
            'exit_reason': exit_reasons_str
        })

        large_trades = trades[trades['large_trade']]
        for _, trade in large_trades.iterrows():
            logging.debug(f"Large trade return: {trade['returns']:.4f}, "
                          f"entry_price={trade['entry_price']:.2f}, "
                          f"exit_price={trade['exit_price']:.2f}, "
                          f"position_size={trade['position_size']:.2f}, "
                          f"entry_time={trade['entry_time']}, "
                          f"exit_time={trade['exit_time']}, "
                          f"exit_reason={trade['exit_reason']}")

        if save_trades:
            symbol = params.get('symbol', 'unknown').replace('/', '_')
            trial_id = f"trial_{trial_number}" if trial_number is not None else "fixed"
            timestamp = run_timestamp if run_timestamp else datetime.now().strftime('%Y%m%d_%H%M%S')
            trades_subdir = TRADES_DIR / timestamp
            trades_subdir.mkdir(parents=True, exist_ok=True)
            trades_filename = f"trades_{symbol}_{trial_id}_{period}.csv"
            trades_filepath = trades_subdir / trades_filename
            trades.to_csv(trades_filepath)
            logging.info(f"Trades for {period} ({len(trades)} total) saved to {trades_filepath}")

        num_trades = len(trades)
        win_rate = float(np.mean(returns > 0))
        profit_factor = float(np.sum(returns[returns > 0]) / (-np.sum(returns[returns < 0]) + 1e-10))

        # Метрики на основе fractional returns/Metrics based on fractional returns
        initial_capital = capital
        equity_per_trade = initial_capital * np.cumprod(1 + returns)

        # Аппроксимация daily equity/Daily equity approximation
        total_days = max((df.index[-1] - df.index[0]).days, 1)
        daily_equity_approx = np.zeros(total_days)
        daily_equity_approx[0] = initial_capital

        exit_days = (trades['exit_time'] - df.index[0]).dt.days.to_numpy()
        valid_indices = exit_days < total_days
        exit_days = exit_days[valid_indices]

        unique_exit_days, unique_indices = np.unique(exit_days, return_index=True)

        daily_equity_approx[unique_exit_days] = equity_per_trade[unique_indices]

        mask = daily_equity_approx == 0
        last_known_value = np.where(~mask, daily_equity_approx, 0)
        np.maximum.accumulate(last_known_value, out=last_known_value)
        daily_equity_approx[mask] = last_known_value[mask]

        final_capital = daily_equity_approx[-1]
        cumulative_return = (final_capital / initial_capital) - 1
        annualized_return = (1 + cumulative_return) ** (365.0 / total_days) - 1

        daily_returns_approx = np.diff(daily_equity_approx) / daily_equity_approx[:-1]

        annualized_volatility = np.std(daily_returns_approx) * np.sqrt(365)
        annualized_volatility = max(annualized_volatility, 1e-6)
        sharpe = annualized_return / annualized_volatility

        rolling_max = np.maximum.accumulate(daily_equity_approx)
        drawdowns = (daily_equity_approx - rolling_max) / rolling_max
        max_drawdown = np.min(drawdowns) if len(drawdowns) > 0 else 0.0

        period_days = total_days

        logging.debug(
            f"Backtest period={period}, trades={num_trades}, days={period_days}, "
            f"cumulative_return={cumulative_return:.4f}, sharpe={sharpe:.6f}")

        logging.debug(f"Backtest completed: trades={num_trades}, return={cumulative_return:.4f}, "
                      f"max_drawdown={max_drawdown:.4f}, max_hold_hours={params.get('max_hold_hours', 12):.2f}")

        logging.debug(f"Trade returns stats: {trades['returns'].describe().to_dict()}")

        result = {
            'trades': trades,
            'num_trades': num_trades,
            'cumulative_return': cumulative_return,
            'win_rate': win_rate,
            'sharpe': sharpe,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'final_capital': final_capital,
            'annualized_return': annualized_return,
            'params': params,
            'period_days': period_days
        }

        return result

    except Exception as e:
        logging.error(f"Error in backtest: {str(e)}", exc_info=True)
        return None
