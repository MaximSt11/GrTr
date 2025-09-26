SHORT_PARAMS = {
    # === Основные параметры риска/позиции ===
    'symbol': 'SOL/USDT:USDT',
    'timeframe': '30m',
    'limit': 950000,
    'leverage': 10,
    'risk_per_trade': 0.159, #0.059
    'min_amount_precision': 0.1,
    'position_scaling': True,
    'max_position_multiplier': 1.59,

    # === ATR и стопы ===
    'atr_period': 21,
    'atr_stop_multiplier': 2.63,
    'breakeven_atr_multiplier': 1.66,
    'aggressive_breakout_stop_multiplier': 0.3,

    # --- ПАРАМЕТРЫ "ЗАМКА НА ПРИБЫЛЬ" ---
    'profit_lock_trigger_pct': 0.0,  # Если установить 0.0 - Замок выключится
    'profit_lock_target_pct': 0.0,

    # === Трейлинг ===
    'trail_atr_multiplier': 6.0,
    'trail_early_activation_atr_multiplier': 0.72,
    'aggressive_trail_atr_multiplier': 0.45,
    'scale_add_atr_multiplier': 2.64,

    # === Take-profit (в ATR) ===
    'tp_atr_multiplier': 16.62,
    'partial_tp_levels': [1.0, 2.0, 3.0],
    'partial_tp_fraction': 0.31,

    # === Режим работы ===
    'partial_take_profit': False,
    'use_breakeven': True,  # <-- PROD (в бэктестере это управляется > 0)

    # === Фильтры ===
    'rsi_period': 28,
    'grid_lower_rsi': 33,
    'use_regime_filter': True,
    'regime_filter_period': 196,
    'macro_ema_period': 867,
    'adx_period': 20,
    'adx_threshold': 34,

    # === Время удержания ===
    'max_hold_hours': 48,
    'cooldown_period_candles': 2,
    'stagnation_atr_threshold': 6.94,
    'stagnation_profit_decay': 0.52,

    # === Режим стратегии (важно для generate_signals) ===
    'mode': 'short_only'
}