from pathlib import Path
from datetime import datetime

# ====================== НАСТРОЙКИ ДАННЫХ ======================


class DataSettings:
    DATA_DAYS_DEPTH = 730
    CACHE_ENABLED = True
    CACHE_EXPIRE_MINUTES = 60
    DATE_FORMAT = "%Y-%m-%d"
    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# ====================== БАЗОВЫЕ НАСТРОЙКИ ======================


class Config:
    # Основное
    PROJECT_NAME = "Grisha"
    VERSION = "17.09.26"
    SYMBOLS = ['SOL/USDT']

    # Флаги модулей отчетности
    ENABLE_REPORTER = True
    ENABLE_VISUALIZER = True
    ENABLE_OPTUNA_PLOTS = True
    ENABLE_LOGGING = True

    # Переключатель режимов теста
    ENABLE_FIXED_PARAMS = True
    ENABLE_OPTUNA = True
    ACTIVE_STRATEGY_KEY = 'LONG' # Меняем ключ для тестирования соответствующего направления

    # Виды отчетов
    ENABLE_SUMMARY_REPORT = True # Устарел, пока в режиме подтягивания к текущей версии
    ENABLE_MINIMAL_REPORT = True
    ENABLE_SUCCESSFUL_TRIALS_REPORT = True # Устарел, пока в режиме подтягивания к текущей версии
    ENABLE_TOP_5_TRIALS_REPORT = True # Устарел, пока в режиме подтягивания к текущей версии

    # Ограничения
    MIN_SHARPE = 0.5
    MIN_WIN_RATE = 0.45
    MIN_TRADES = 30
    MAX_DRAWDOWN = -0.5

    # ==================================================================================
    # --- 1. БИБЛИОТЕКА КОНФИГУРАЦИЙ ---
    # ==================================================================================

    # --- СТРАТЕГИЯ LONG ---
    FIXED_PARAMS_LONG = {
        # === Основные параметры риска/позиции ===
        'timeframe': '1h',
        'limit': 950000,
        'leverage': 10,
        'risk_per_trade': 0.051,
        'min_amount_precision': 0.1,
        'position_scaling': False,
        'max_position_multiplier': 3.02,

        # === ATR и стопы ===
        'atr_period': 23,
        'atr_stop_multiplier': 3.83,
        'breakeven_atr_multiplier': 1.31,
        'aggressive_breakout_stop_multiplier': 1.95,

        # --- ПАРАМЕТРЫ "ЗАМКА НА ПРИБЫЛЬ" ---
        'profit_lock_trigger_pct': 0.055,
        'profit_lock_target_pct': 0.027,

        # === Трейлинг ===
        'trail_atr_multiplier': 4.65,
        'trail_early_activation_atr_multiplier': 1.73,
        'aggressive_trail_atr_multiplier': 0.36,
        'scale_add_atr_multiplier': 2.4,

        # === Take-profit (в ATR) ===
        'tp_atr_multiplier': 14.54,
        'partial_tp_fraction': 0.18,

        # === Режим работы ===
        'partial_take_profit': True,

        # === Фильтры ===
        'rsi_period': 22,
        'grid_upper_rsi': 85,
        'use_regime_filter': True,
        'regime_filter_period': 23,
        'macro_ema_period': 231,

        # === Время удержания ===
        'max_hold_hours': 48,
        'cooldown_period_candles': 0,
        'stagnation_atr_threshold': 5.7,
        'stagnation_profit_decay': 0.68,
    }

    PARAM_GRID_LONG = {
        # === Основные параметры риска/позиции ===
        'timeframe': ['1h'],
        'limit': [950000],
        'leverage': [10],
        'risk_per_trade': (0.01, 0.25),
        'min_amount_precision': [0.1],
        'position_scaling': [True, False],
        'max_position_multiplier': (1.2, 4.0),

        # === ATR и стопы ===
        'atr_period': (10, 25),
        'atr_stop_multiplier': (2.0, 4.0),
        'breakeven_atr_multiplier': (1.0, 2.5),
        'aggressive_breakout_stop_multiplier': (0.0, 2.0),

        # --- ПАРАМЕТРЫ "ЗАМКА НА ПРИБЫЛЬ" ---
        'profit_lock_trigger_pct': (0.00, 0.08),
        'profit_lock_target_pct': (0.01, 0.07),

        # === Трейлинг ===
        'trail_atr_multiplier': (0.5, 8.0),
        'trail_early_activation_atr_multiplier': (0.3, 3.0),
        'aggressive_trail_atr_multiplier': (0.3, 1.8),
        'scale_add_atr_multiplier': (0.2, 3.0),

        # === Take-profit (в ATR) ===
        'tp_atr_multiplier': (8.0, 20.0),
        'partial_tp_fraction': (0.10, 0.4),

        # === Режим работы ===
        'partial_take_profit': [True, False],


        # === Фильтры ===
        'rsi_period': (10, 28),
        'grid_upper_rsi': (75, 95),
        'use_regime_filter': [True],
        'regime_filter_period': (20, 200),
        'macro_ema_period': (100, 1200),

        # === Время удержания ===
        'max_hold_hours': [36, 48, 72, 144],
        'cooldown_period_candles': (0, 10),
        'stagnation_atr_threshold': (4.0, 7.0),
        'stagnation_profit_decay': (0.5, 0.75),
    }

    # --- СТРАТЕГИЯ SHORT ---
    FIXED_PARAMS_SHORT = {
        # === Основные параметры риска/позиции ===
        'timeframe': '30m',
        'limit': 950000,
        'leverage': 10,
        'risk_per_trade': 0.159,
        'min_amount_precision': 0.1,
        'position_scaling': True,
        'max_position_multiplier': 1.59,

        # === ATR и стопы ===
        'atr_period': 21,
        'atr_stop_multiplier': 2.63,
        'breakeven_atr_multiplier': 1.66,
        'aggressive_breakout_stop_multiplier': 0.3,

        # --- ПАРАМЕТРЫ "ЗАМКА НА ПРИБЫЛЬ" ---
        'profit_lock_trigger_pct': 0.0,
        'profit_lock_target_pct': 0.0,

        # === Трейлинг ===
        'trail_atr_multiplier': 6.0,
        'trail_early_activation_atr_multiplier': 0.72,
        'aggressive_trail_atr_multiplier': 0.45,
        'scale_add_atr_multiplier': 2.64,

        # === Take-profit ===
        'tp_atr_multiplier': 16.62,
        'partial_tp_fraction': 0.31,
        'partial_take_profit': False,

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
    }

    PARAM_GRID_SHORT = {
        # === Основные параметры риска/позиции ===
        'timeframe': ['30m', '1h'],
        'limit': [950000],
        'leverage': [10],
        'risk_per_trade': (0.01, 0.07),
        'min_amount_precision': [0.1],
        'position_scaling': [True, False],
        'max_position_multiplier': (1.2, 4.0),

        # === ATR и стопы ===
        'atr_period': (5, 25),
        'atr_stop_multiplier': (1.5, 5.0),
        'breakeven_atr_multiplier': (1.0, 2.5),
        'aggressive_breakout_stop_multiplier': (0.0, 2.0),

        # --- ПАРАМЕТРЫ "ЗАМКА НА ПРИБЫЛЬ" ---
        'profit_lock_trigger_pct': (0.00, 0.08),
        'profit_lock_target_pct': (0.01, 0.07),

        # === Трейлинг ===
        'trail_atr_multiplier': (0.5, 8.0),
        'trail_early_activation_atr_multiplier': (0.3, 3.0),
        'aggressive_trail_atr_multiplier': (0.3, 1.8),
        'scale_add_atr_multiplier': (0.2, 3.0),

        # === Take-profit ===
        'tp_atr_multiplier': (1.0, 20.0),
        'partial_tp_fraction': (0.10, 0.4),
        'partial_take_profit': [True, False],

        # === Фильтры ===
        'rsi_period': (10, 28),
        'grid_lower_rsi': (15, 35),
        'use_regime_filter': [True],
        'regime_filter_period': (20, 200),
        'macro_ema_period': (100, 1200),
        'adx_period': (10, 30),
        'adx_threshold': (28, 35),

        # === Время удержания ===
        'max_hold_hours': [36, 48, 72, 144],
        'cooldown_period_candles': (0, 10),
        'stagnation_atr_threshold': (4.0, 7.0),
        'stagnation_profit_decay': (0.5, 0.75),
    }

    #Тестирование
    PARAM_GRID_SCALP = {
        'timeframe': ['3m', '5m', '15m'],
        'limit': [1000000],

        # --- КЛЮЧЕВЫЕ ПАРАМЕТРЫ ---
        'medium_ema_period': (20, 100),
        'bb_period': (15, 80),
        'bb_dev': (2.0, 5.0),

        # --- ТЕХНИЧЕСКИЙ ПАРАМЕТР ДЛЯ СОВМЕСТИМОСТИ ---
        'rsi_period': [14],

        # --- ПАРАМЕТРЫ УПРАВЛЕНИЯ РИСКОМ ---
        'atr_period': (10, 30),
        'atr_stop_multiplier': (2.0, 7.0),
        'risk_per_trade': (0.01, 0.05),
        'tp_atr_multiplier': (2.0, 7.0),

        # --- ВСПОМОГАТЕЛЬНЫЕ ПАРАМЕТРЫ ---
        'leverage': [10],
        'min_amount_precision': [0.1],
        'partial_take_profit': [False],
        'position_scaling': [False],
        'breakeven_atr_multiplier': (1.0, 3.0),
        'max_hold_hours': [12, 24],
    }

    # --- 2. СЛОВАРЬ-РЕЕСТР СТРАТЕГИЙ ---
    STRATEGY_LIBRARY = {
        'LONG': {
            'param_grid': PARAM_GRID_LONG,
            'fixed_params': FIXED_PARAMS_LONG,
            'mode': 'long_only'
        },
        'SHORT': {
            'param_grid': PARAM_GRID_SHORT,
            'fixed_params': FIXED_PARAMS_SHORT,
            'mode': 'short_only'
        },
        'SCALP': {
            'param_grid': PARAM_GRID_SCALP,
            # Для скальпинга нет фиксированных параметров, ищем
            'fixed_params': {},
            'mode': 'short_scalp'
        }
    }


    # --- 4. ДИНАМИЧЕСКИЙ ВЫБОР И ЭКСПОРТ ---
    try:
        active_config = STRATEGY_LIBRARY[ACTIVE_STRATEGY_KEY]
    except KeyError:
        raise ValueError(f"Ошибка: Ключ стратегии '{ACTIVE_STRATEGY_KEY}' не найден в STRATEGY_LIBRARY.")

    PARAM_GRID = active_config['param_grid'].copy()
    FIXED_PARAMS = active_config['fixed_params'].copy()

    FIXED_PARAMS['mode'] = active_config['mode']
    PARAM_GRID['mode'] = [active_config['mode']]

    # Веса для objective с иерархическим фильтром не используются
    OBJECTIVE_WEIGHTS = {
        'cumulative_return': 0.5,
        'num_trades': 0.3,
        'profit_factor': 0.15,
        'max_drawdown': -0.15
    }
    OPTUNA_SETTINGS = {
        'n_trials': 3900,
        'timeout': 7200,
        'n_jobs': -1,
        'show_progress_bar': True
    }

    COMMISSION = 0.001
    SLIPPAGE = 0.0005
    CAPITAL = 150
# ====================== ПУТИ СОХРАНЕНИЯ ======================


class Paths:
    BASE_DIR = Path(__file__).parent
    DATA_DIR = BASE_DIR / 'data'
    RESULTS_DIR = BASE_DIR / 'results'
    LOGS_DIR = RESULTS_DIR / 'logs'
    PLOTS_DIR = RESULTS_DIR / 'plots'
    STRATEGIES_DIR = RESULTS_DIR / 'strategies'
    OPTUNA_DIR = RESULTS_DIR / 'optuna'
    # BACKTESTS_DIR = RESULTS_DIR / 'backtests' что то из прошлого
    CACHE_DIR = DATA_DIR / 'cache'
    TRADES_DIR = RESULTS_DIR / 'trades'
    for dir in [DATA_DIR, RESULTS_DIR, LOGS_DIR, PLOTS_DIR,
                STRATEGIES_DIR, OPTUNA_DIR, CACHE_DIR, TRADES_DIR]:
        dir.mkdir(parents=True, exist_ok=True)


# ====================== ЭКСПОРТ НАСТРОЕК ======================
ENABLE_REPORTER = Config.ENABLE_REPORTER
ENABLE_VISUALIZER = Config.ENABLE_VISUALIZER
ENABLE_OPTUNA_PLOTS = Config.ENABLE_OPTUNA_PLOTS
ENABLE_LOGGING = Config.ENABLE_LOGGING
ENABLE_FIXED_PARAMS = Config.ENABLE_FIXED_PARAMS
ENABLE_OPTUNA = Config.ENABLE_OPTUNA
ENABLE_SUMMARY_REPORT = Config.ENABLE_SUMMARY_REPORT
ENABLE_MINIMAL_REPORT = Config.ENABLE_MINIMAL_REPORT
ENABLE_SUCCESSFUL_TRIALS_REPORT = Config.ENABLE_SUCCESSFUL_TRIALS_REPORT
ENABLE_TOP_5_TRIALS_REPORT = Config.ENABLE_TOP_5_TRIALS_REPORT
MIN_SHARPE = Config.MIN_SHARPE
MIN_WIN_RATE = Config.MIN_WIN_RATE
MIN_TRADES = Config.MIN_TRADES
MAX_DRAWDOWN = Config.MAX_DRAWDOWN
FIXED_PARAMS = Config.FIXED_PARAMS
PARAM_GRID = Config.PARAM_GRID
COMMISSION = Config.COMMISSION
SLIPPAGE = Config.SLIPPAGE
CAPITAL = Config.CAPITAL
OBJECTIVE_WEIGHTS = Config.OBJECTIVE_WEIGHTS
OPTUNA_SETTINGS = Config.OPTUNA_SETTINGS
SYMBOLS = Config.SYMBOLS
LOG_DIR = Paths.LOGS_DIR
PLOT_DIR = Paths.PLOTS_DIR
STRATEGY_DIR = Paths.STRATEGIES_DIR
OPTUNA_DIR = Paths.OPTUNA_DIR
# BACKTESTS_DIR = Paths.BACKTESTS_DIR
CACHE_DIR = Paths.CACHE_DIR
RESULTS_DIR = Paths.RESULTS_DIR
TRADES_DIR = Paths.TRADES_DIR
DATA_DAYS_DEPTH = DataSettings.DATA_DAYS_DEPTH
CACHE_ENABLED = DataSettings.CACHE_ENABLED
CACHE_EXPIRE_MINUTES = DataSettings.CACHE_EXPIRE_MINUTES
TODAY = datetime.now().strftime(DataSettings.DATE_FORMAT)
NOW = datetime.now().strftime(DataSettings.DATETIME_FORMAT)


if __name__ == '__main__':
    print(f"Конфигурация проекта {Config.PROJECT_NAME} v{Config.VERSION}")
    print(f"Режимы работы:")
    print(f"  Отчеты: {'ВКЛ' if ENABLE_REPORTER else 'ВЫКЛ'}")
    print(f"  Визуализация: {'ВКЛ' if ENABLE_VISUALIZER else 'ВЫКЛ'}")
    print(f"  Графики Optuna: {'ВКЛ' if ENABLE_OPTUNA_PLOTS else 'ВЫКЛ'}")
    print(f"  Логирование: {'ВКЛ' if ENABLE_LOGGING else 'ВЫКЛ'}")
    print(f"  Фиксированные параметры: {'ВКЛ' if ENABLE_FIXED_PARAMS else 'ВЫКЛ'}")
    print(f"  Оптимизация Optuna: {'ВКЛ' if ENABLE_OPTUNA else 'ВЫКЛ'}")
    print(f"  Summary Report: {'ВКЛ' if ENABLE_SUMMARY_REPORT else 'ВЫКЛ'}")
    print(f"  Minimal Report: {'ВКЛ' if ENABLE_MINIMAL_REPORT else 'ВЫКЛ'}")
    print(f"  Successful Trials Report: {'ВКЛ' if ENABLE_SUCCESSFUL_TRIALS_REPORT else 'ВЫКЛ'}")
    print(f"  Top 5 Trials Report: {'ВКЛ' if ENABLE_TOP_5_TRIALS_REPORT else 'ВЫКЛ'}")
    print(f"Базовая директория: {Paths.BASE_DIR}")
    print(f"Директория результатов: {Paths.RESULTS_DIR}")
