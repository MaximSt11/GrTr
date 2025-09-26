LONG_PARAMS = {
    # === Основные параметры риска/позиции ===
    'symbol': 'SOL/USDT:USDT',
    'timeframe': '1h',
    'limit': 950000,
    'leverage': 10,
    'risk_per_trade': 0.066,
    'min_amount_precision': 0.1,
    'position_scaling': False,
    'max_position_multiplier': 2.6,

    # === ATR и стопы ===
    'atr_period': 7,
    'atr_stop_multiplier': 2.45,
    'breakeven_atr_multiplier': 1.49,
    'aggressive_breakout_stop_multiplier': 1.46,

    # --- ПАРАМЕТРЫ "ЗАМКА НА ПРИБЫЛЬ" ---
    'profit_lock_trigger_pct': 0.032, # Если установить 0.0 - Замок выключится
    'profit_lock_target_pct': 0.037,

    # === Трейлинг ===
    'trail_atr_multiplier': 6.25,
    'trail_early_activation_atr_multiplier': 0.59,
    'aggressive_trail_atr_multiplier': 1.58,
    'scale_add_atr_multiplier': 1.57,

    # === Take-profit (в ATR) ===
    'tp_atr_multiplier': 3.41,
    'partial_tp_levels': [1.0, 2.0, 3.0],
    'partial_tp_fraction': 0.38,

    # === Режим работы ===
    'partial_take_profit': True,
    'use_breakeven': True,  # <-- PROD (в бэктестере это управляется > 0)

    # === Фильтры ===
    'rsi_period': 23,
    'grid_upper_rsi': 77,
    'use_regime_filter': True,
    'regime_filter_period': 147,
    'macro_ema_period': 264,

    # === Время удержания ===
    'max_hold_hours': 144,
    'cooldown_period_candles': 6,
    'stagnation_atr_threshold': 4.01,
    'stagnation_profit_decay': 0.58,

    # === Режим стратегии (важно для generate_signals) ===
    'mode': 'long_only'
}