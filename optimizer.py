import optuna
from optuna.samplers import TPESampler
from optuna.pruners import MedianPruner
import pandas as pd
import logging
from typing import Optional, Dict
from datetime import datetime
from config import OPTUNA_SETTINGS, PARAM_GRID, MIN_TRADES, DATA_DAYS_DEPTH, ENABLE_OPTUNA_PLOTS, TRADES_DIR
from data_fetcher import fetch_data
from indicators import add_indicators
from backtester import generate_signals, backtest
from utils.visualizer import save_optuna_plots


def deviation_reporter_callback(study: optuna.study.Study, trial: optuna.trial.FrozenTrial):
    """
    (EN) "Deviation Analyst" Callback:
    1. Reports the parameters of each new leader.
    2. Shows the top 5 parameters where the leader DEVIATES most from the average.

    (RU) Callback "Аналитик Отклонений":
    1. Сообщает о параметрах каждого нового лидера.
    2. Показывает топ-5 параметров, по которым лидер сильнее всего ОТЛИЧАЕТСЯ от среднего.
    """
    # Проверяем, является ли текущий триал новым лучшим/Check if the current trial is the new best one
    if study.best_trial and study.best_trial.number == trial.number:

        print("\n" + "=" * 80)
        print(f"🚀 NEW LEADER [Trial #{trial.number}] | Score: {trial.value:.4f}")

        score = trial.value
        status = "UNKNOWN"
        if score == -2000.0:
            status = "FAILED: Insufficient trades (Filter 1)"
        elif score == -1000.0:
            status = "FAILED: Unprofitable (Filter 2)"
        elif score == -500.0:
            status = "FAILED: Not robust (Filter 3)"
        elif score == -100.0:
            status = "PROGRESS: Passed Profitability, FAILED Risk/Drawdown (Filter 4)"
        elif score == -50.0:
            status = "PROGRESS: Passed Risk, FAILED Profitability Quality (Filter 5/6)"
        elif score > 0:
            status = "SUCCESS: PASSED ALL FILTERS! ✅"

        print(f"STATUS: {status}")
        print("-" * 80)

        # --- БЛОК АНАЛИЗА ОТКЛОНЕНИЙ/DEVIATION ANALYSIS BLOCK ---
        # Собираем все предыдущие триалы, у которых были числовые параметры/Collect all previous trials that had numerical parameters
        previous_trials = [t for t in study.trials if t.number < trial.number]

        if len(previous_trials) > 1:
            # Создаем DataFrame из параметров предыдущих попыток/Create a DataFrame from the parameters of previous trials
            previous_params_df = pd.DataFrame([t.params for t in previous_trials])

            deviations = {}
            for param, leader_value in trial.params.items():
                # Работаем только с числовыми параметрами/Work only with numerical parameters
                if isinstance(leader_value, (int, float)):
                    # Считаем среднее и стандартное отклонение по предыдущим попыткам/Calculate the mean and standard deviation from previous trials
                    mean_val = previous_params_df[param].mean()
                    std_val = previous_params_df[param].std()
                    if std_val > 0:  # Избегаем деления на ноль
                        # Считаем Z-score - насколько лидер отклоняется от среднего в "сигмах"/Calculate Z-score - how much the leader deviates from the mean in "sigmas"
                        z_score = abs(leader_value - mean_val) / std_val
                        deviations[param] = z_score

            # Сортируем параметры по силе отклонения и берем топ-5/Sort parameters by deviation strength and take the top 5
            top_5_deviations = sorted(deviations.items(), key=lambda item: item[1], reverse=True)[:5]

            print("Top 5 Deviating Parameters (what makes this leader different):")
            for i, (param, z_score) in enumerate(top_5_deviations):
                leader_value = trial.params[param]
                mean_val = previous_params_df[param].mean()
                print(f"  {i + 1}. {param:<25} | Leader's Value: {leader_value:<10.4f} | Avg So Far: {mean_val:.4f}")

        else:
            print("Top 5 Deviating Parameters: [Not enough previous trials to compare]")

        print("-" * 80)
        print("Full parameters of this leader:")
        for param, value in trial.params.items():
            if isinstance(value, float):
                print(f"  - {param:<25}: {value:.4f}")
            else:
                print(f"  - {param:<25}: {value}")
        print("=" * 80 + "\n")


def suggest_params(trial: optuna.Trial) -> Dict:
    """
    (EN) Suggests parameters for an Optuna trial with explicit type checking
    to prevent errors.
    (RU) Определение параметров для попытки Optuna с явной проверкой типов
    для предотвращения ошибок.
    """
    params = {}
    for param_name, param_values in PARAM_GRID.items():
        # Если значение в конфиге - это список из двух ЧИСЕЛ (и не boolean)/If the value in the config is a list of two NUMBERS (and not boolean)
        if (isinstance(param_values, (list, tuple)) and len(param_values) == 2 and
                isinstance(param_values[0], (int, float)) and not isinstance(param_values[0], bool)):

            # Если оба числа целые - используем suggest_int/If both numbers are integers - use suggest_int
            if all(isinstance(i, int) for i in param_values):
                params[param_name] = trial.suggest_int(param_name, param_values[0], param_values[1])
            # Иначе (если есть хоть одно дробное) - используем suggest_float/Otherwise (if there is at least one float) - use suggest_float
            else:
                params[param_name] = trial.suggest_float(param_name, param_values[0], param_values[1])
        # Во всех остальных случаях (списки строк, bool'ов и т.д.) используем suggest_categorical/In all other cases (lists of strings, booleans, etc.) use suggest_categorical
        else:
            # Убеждаемся, что передаем в suggest_categorical именно список/Ensure we are passing a list to suggest_categorical
            choices = param_values if isinstance(param_values, list) else [param_values]
            params[param_name] = trial.suggest_categorical(param_name, choices)

    return params


def validate_params(params: Dict) -> bool:
    """
    (EN) Validates the correctness of parameters. Only relevant checks are kept.
    (RU) Проверка корректности параметров. Оставляем только актуальные проверки.
    """

    # Проверка базовой валидности/Basic validity check
    if params.get('atr_period', 0) <= 0:
        return False
    # Агрессивный трейлинг должен быть теснее стандартного/Aggressive trailing should be tighter than standard trailing
    if params.get('aggressive_trail_atr_multiplier', 999) >= params.get('trail_atr_multiplier', 0):
        return False
    # Убедимся, что порог на выход по RSI не ниже "верхнего" фильтра/Ensure the RSI exit threshold is not lower than the "upper" filter
    if params.get('rsi_exit_high', 1e9) < params.get('grid_upper_rsi', 0):
        return False

    return True


def objective(trial: optuna.Trial, symbol: str, run_timestamp: str, dataframes: Dict[str, pd.DataFrame]) -> float:
    """
    (EN) The objective function. Does NOT load data, but takes it from a pre-loaded dictionary.
    (RU) Целевая функция. НЕ загружает данные, а берет их из готового словаря.
    """
    try:
        params = suggest_params(trial)
        params['symbol'] = symbol

        timeframe = params['timeframe']
        df = dataframes.get(timeframe)
        if df is None:
            # Этот таймфрейм не был загружен, пропускаем попытку/This timeframe was not loaded, skip the trial
            return float('-inf')

        # Разделение данных/Data splitting
        train_size = int(len(df) * 0.5)
        gap = int(len(df) * 0.15)
        df_train = df.iloc[:train_size]
        df_test = df.iloc[train_size + gap:]
        logging.debug(f"Trial {trial.number} split data: train={len(df_train)} rows, test={len(df_test)} rows")

        # Бэктесты/Backtests
        df_train = add_indicators(df_train, params)
        df_train = generate_signals(df_train, params)
        train_result = backtest(df_train, params, trial_number=trial.number, run_timestamp=run_timestamp, period="train", save_trades=False)

        if (not train_result or train_result['num_trades'] < MIN_TRADES // 4):
            return float('-inf')

        df_test = add_indicators(df_test, params)
        df_test = generate_signals(df_test, params)
        test_result = backtest(df_test, params, trial_number=trial.number, run_timestamp=run_timestamp, period="test", save_trades=False)

        # Фильтр 1: "Выживаемость". Проверяем, что бэктесты прошли и сделок достаточно/Filter 1: "Survival". Check if backtests ran and there are enough trades.
        if not train_result or not test_result or train_result.get('num_trades', 0) < MIN_TRADES or test_result.get(
                'num_trades', 0) < MIN_TRADES / 2:
            trial.set_user_attr('fail_reason', 'Insufficient trades')
            return -2000.0

        train_dd = train_result.get('max_drawdown', -1.0)
        test_dd = test_result.get('max_drawdown', -1.0)

        train_sharpe = train_result.get('sharpe', 0)
        test_sharpe = test_result.get('sharpe', 0)

        test_pf = test_result.get('profit_factor', 0.0)
        train_pf = train_result.get('profit_factor', 0.0)

        test_nt = test_result.get('num_trades', 0.0)
        train_nt = train_result.get('num_trades', 0.0)

        test_pd = test_result.get('period_days', 0.0)
        train_pd = test_result.get('period_days', 0.0)

        # Фильтр 2: "Прибыльность". Стратегия должна быть прибыльной на обоих периодах/Filter 2: "Profitability". The strategy must be profitable in both periods.
        if train_pf < 1.25 or test_pf < 1.25:
            trial.set_user_attr('fail_reason', 'Unprofitable')
            return -1000.0

        # --- ФИЛЬТР 3/FILTER 3 ---
        # Защита от деления на ноль или очень малые значения, если train_sharpe почти нулевой/Protection against division by zero or very small values if train_sharpe is almost zero
        train_sharpe_safe = max(abs(train_sharpe), 0.1)
        sharpe_ratio = test_sharpe / train_sharpe_safe

        # Провалом считаем, если Шарп на тесте упал более чем на 70%
        # ИЛИ вырос более чем в 4 раза (показатель дикого переобучения)
        # Failure is considered if the test Sharpe drops by more than 70%
        # OR grows by more than 4 times (an indicator of wild overfitting)
        if sharpe_ratio < 0.3 or sharpe_ratio > 4.0:
            trial.set_user_attr('fail_reason', f'Not robust (Sharpe ratio train/test is {sharpe_ratio:.2f})')
            return -500.0

        # Фильтр 4: "Управление риском". Просадка не должна быть катастрофической/Filter 4: "Risk Management". Drawdown must not be catastrophic.
        if train_dd < -0.4 or test_dd < -0.4:
            trial.set_user_attr('fail_reason', 'Too risky')
            return -100.0

        # ФИЛЬТР 5: "Минимальная доходность"/FILTER 5: "Minimum Return"
        min_required_return = 0.5
        test_ar = test_result.get('annualized_return', 0)
        if test_ar < min_required_return:
            trial.set_user_attr('fail_reason', 'Profitability too low')
            return -50.0

        # ФИЛЬТР 6: "КАЧЕСТВО ПРИБЫЛИ" (Calmar Ratio)/FILTER 6: "PROFIT QUALITY" (Calmar Ratio)
        train_ar = train_result.get('annualized_return', 0)
        test_ar = test_result.get('annualized_return', 0)

        # abs() нужен, так как просадка отрицательная/abs() is needed as drawdown is negative
        train_calmar = train_ar / (abs(train_dd) + 1e-6)  # +1e-6 для избежания деления на 0/ +1e-6 to avoid division by 0
        test_calmar = test_ar / (abs(test_dd) + 1e-6)

        # Требуем, чтобы Calmar был не меньше 1 (зарабатываем на просадку хотя бы столько же)
        # и чтобы он не сильно падал на тесте.
        # We require Calmar to be at least 1 (earn at least as much as the drawdown)
        # and for it not to drop significantly on the test set.
        if train_calmar < 0.5:
            trial.set_user_attr('fail_reason', 'Low Calmar Ratio')
            return -40.0  # Используем тот же код, что и для низкой доходности

        # ФИЛЬТР 7: "КОЛИЧЕСТВО СДЕЛОК"/FILTER 7: "NUMBER OF TRADES"
        min_required_freq = test_nt / test_pd
        if min_required_freq < 0.1:
            trial.set_user_attr('fail_reason', 'Too low Frequency')
            return -25.0

        # Штрафуем, если тейк-профит ближе стоп-лосса (R:R < 1)/Penalize if take-profit is closer than stop-loss (R:R < 1)
        if params['tp_atr_multiplier'] < params['atr_stop_multiplier']:
            return -3000.0  # Присваиваем очень большой штраф/Assign a very large penalty

        if params['breakeven_atr_multiplier'] >= params['tp_atr_multiplier']:
            return -4000.0  # Безубыток никогда не сработает/Breakeven will never trigger

        # --- ФИЛЬТР "НА РЕАЛИСТИЧНОСТЬ"/"REALISM" FILTER ---
        # Отсекаем аномально высокие значения, которые являются 100% переобучением/Filter out abnormally high values that are 100% overfitting
        MAX_REALISTIC_SHARPE = 25  # Шарп выше 25 на 40-дневном тесте - это почти всегда стат. аномалия/A Sharpe above 25 on a 40-day test is almost always a stat. anomaly

        if test_result.get('sharpe', 0) > MAX_REALISTIC_SHARPE:
            trial.set_user_attr('fail_reason', f'Anomalous Sharpe > {MAX_REALISTIC_SHARPE}')
            return -6000.0

        # Штрафуем итоговую оценку на величину разрыва между train и test
        # Чем больше разрыв, тем ниже будет итоговая оценка
        # Penalize the final score by the magnitude of the gap between train and test
        # The larger the gap, the lower the final score will be
        final_score = test_sharpe - abs(train_sharpe - test_sharpe)

        train_exit_reasons = train_result['trades']['exit_reason'].value_counts(normalize=True).to_dict()
        train_exit_reasons = {k: float(v * 100) for k, v in train_exit_reasons.items()}
        test_exit_reasons = test_result['trades']['exit_reason'].value_counts(normalize=True).to_dict()
        test_exit_reasons = {k: float(v * 100) for k, v in test_exit_reasons.items()}

        logging.debug(
            f"Trial {trial.number} PASSED ALL FILTERS. Final score (Test Profit Factor): {final_score:.4f}, "
            f"train_return={train_result['cumulative_return']:.2%}, test_return={test_result['cumulative_return']:.2%}, "
            f"train_pf={train_result['profit_factor']:.2f}, test_pf={test_result['profit_factor']:.2f}")

        trial.set_user_attr('train_sharpe', float(train_result['sharpe']))
        trial.set_user_attr('train_win_rate', float(train_result['win_rate']))
        trial.set_user_attr('train_profit_factor', float(train_result['profit_factor']))
        trial.set_user_attr('train_cumulative_return', float(train_result['cumulative_return']))
        trial.set_user_attr('train_annualized_return', float(train_result['annualized_return']))
        trial.set_user_attr('train_num_trades', int(train_result['num_trades']))
        trial.set_user_attr('train_max_drawdown', float(train_result['max_drawdown']))
        trial.set_user_attr('train_final_capital', float(train_result['final_capital']))
        trial.set_user_attr('train_trades', train_result['trades'].to_dict('records'))
        trial.set_user_attr('train_exit_reasons', train_exit_reasons)
        trial.set_user_attr('test_sharpe', float(test_result['sharpe']))
        trial.set_user_attr('test_win_rate', float(test_result['win_rate']))
        trial.set_user_attr('test_profit_factor', float(test_result['profit_factor']))
        trial.set_user_attr('test_cumulative_return', float(test_result['cumulative_return']))
        trial.set_user_attr('test_annualized_return', float(test_result['annualized_return']))
        trial.set_user_attr('test_num_trades', int(test_result['num_trades']))
        trial.set_user_attr('test_max_drawdown', float(test_result['max_drawdown']))
        trial.set_user_attr('test_final_capital', float(test_result['final_capital']))
        trial.set_user_attr('test_trades', test_result['trades'].to_dict('records'))
        trial.set_user_attr('test_exit_reasons', test_exit_reasons)
        trial.set_user_attr('data_days_depth', DATA_DAYS_DEPTH)
        trial.set_user_attr('train_period_days', int(train_result['period_days']))
        trial.set_user_attr('test_period_days', int(test_result['period_days']))

        stagnation_pct = test_exit_reasons.get('stagnation_exit', 0)
        partial_take_profit = test_exit_reasons.get('partial_take_profit', 0)
        trailing_stop = test_exit_reasons.get('trailing_stop', 0)

        if stagnation_pct > 20:
            final_score -= 0.3
        if partial_take_profit > 40 and trailing_stop > 15:
            final_score += 0.3

        return float(final_score)

    except Exception as e:
        logging.error(f"Trial {trial.number} failed for {symbol}: {str(e)}", exc_info=True)
        return float('-inf')


def optimize_strategy(symbol: str, run_timestamp: str) -> Optional[tuple]:
    """
    (EN) Optimizes the strategy. Loads data ONCE before starting.
    (RU) Оптимизация стратегии. Загружает данные ОДИН РАЗ перед запуском.
    """
    try:
        logging.info(f"Starting optimization for {symbol} with {OPTUNA_SETTINGS['n_trials']} trials")

        logging.info(f"Pre-loading data for all timeframes...")
        timeframes_to_load = PARAM_GRID.get('timeframe', ['1h'])  # Получаем список таймфреймов из конфига/Get the list of timeframes from the config
        dataframes = {}
        for tf in timeframes_to_load:
            limit = max(PARAM_GRID.get('limit', [555000]))
            df = fetch_data(symbol, tf, limit)
            if df is not None and not df.empty:
                dataframes[tf] = df
            else:
                logging.warning(f"Failed to load data for timeframe {tf}, it will be skipped.")

        if not dataframes:
            logging.error(f"Failed to load data for any timeframe for symbol {symbol}. Stopping.")
            return None

        study = optuna.create_study(
            direction='maximize',
            sampler=TPESampler(seed=42, n_startup_trials=20, multivariate=True),
            pruner=MedianPruner(n_warmup_steps=10, n_min_trials=5)
        )

        study.optimize(
            lambda trial: objective(trial, symbol, run_timestamp, dataframes),
            n_trials=OPTUNA_SETTINGS['n_trials'],
            timeout=OPTUNA_SETTINGS['timeout'],
            n_jobs=-1,
            show_progress_bar=OPTUNA_SETTINGS['show_progress_bar'],
            gc_after_trial=True,
            callbacks=[deviation_reporter_callback],
        )

        successful_trials = len([t for t in study.trials if t.value != float('-inf')])
        logging.info(f"Optimization for {symbol}: {successful_trials}/{OPTUNA_SETTINGS['n_trials']} trials were successful")

        if not study.best_trial or study.best_trial.value == float('-inf'):
            logging.warning(f"No successful trials for {symbol}")
            return None

        best_result = {
            'train_sharpe': study.best_trial.user_attrs['train_sharpe'],
            'train_win_rate': study.best_trial.user_attrs['train_win_rate'],
            'train_profit_factor': study.best_trial.user_attrs['train_profit_factor'],
            'train_cumulative_return': study.best_trial.user_attrs['train_cumulative_return'],
            'train_annualized_return': study.best_trial.user_attrs['train_annualized_return'],
            'train_num_trades': study.best_trial.user_attrs['train_num_trades'],
            'train_period_days': study.best_trial.user_attrs.get('train_period_days'),
            'train_max_drawdown': study.best_trial.user_attrs['train_max_drawdown'],
            'train_final_capital': study.best_trial.user_attrs['train_final_capital'],
            'train_trades': pd.DataFrame(study.best_trial.user_attrs['train_trades']),
            'train_exit_reasons': study.best_trial.user_attrs['train_exit_reasons'],
            'test_sharpe': study.best_trial.user_attrs['test_sharpe'],
            'test_win_rate': study.best_trial.user_attrs['test_win_rate'],
            'test_profit_factor': study.best_trial.user_attrs['test_profit_factor'],
            'test_cumulative_return': study.best_trial.user_attrs['test_cumulative_return'],
            'test_annualized_return': study.best_trial.user_attrs['test_annualized_return'],
            'test_num_trades': study.best_trial.user_attrs['test_num_trades'],
            'test_period_days': study.best_trial.user_attrs.get('test_period_days'),
            'test_max_drawdown': study.best_trial.user_attrs['test_max_drawdown'],
            'test_final_capital': study.best_trial.user_attrs['test_final_capital'],
            'test_trades': pd.DataFrame(study.best_trial.user_attrs['test_trades']),
            'test_exit_reasons': study.best_trial.user_attrs['test_exit_reasons'],
            'params': study.best_params,
            'data_days_depth': DATA_DAYS_DEPTH
        }

        try:
            best_trial_number = study.best_trial.number
            trial_id = f"trial_{best_trial_number}"
            timestamp = run_timestamp if run_timestamp else datetime.now().strftime('%Y%m%d_%H%M%S')
            trades_subdir = TRADES_DIR / timestamp
            trades_subdir.mkdir(parents=True, exist_ok=True)

            # Сохранение сделок для train/Saving train trades
            train_trades_df = best_result['train_trades']
            train_filename = f"trades_{symbol.replace('/', '_')}_{trial_id}_train.csv"
            train_filepath = trades_subdir / train_filename
            train_trades_df.to_csv(train_filepath, index=False)
            logging.info(f"Best trial train trades ({len(train_trades_df)} total) saved to {train_filepath}")

            # Сохранение сделок для test/Saving test trades
            test_trades_df = best_result['test_trades']
            test_filename = f"trades_{symbol.replace('/', '_')}_{trial_id}_test.csv"
            test_filepath = trades_subdir / test_filename
            test_trades_df.to_csv(test_filepath, index=False)
            logging.info(f"Best trial test trades ({len(test_trades_df)} total) saved to {test_filepath}")

        except Exception as e:
            logging.error(f"Failed to save best trial trades for {symbol}: {str(e)}")

        returns = best_result['train_trades']['returns'].values
        best_result['train_avg_return'] = returns.mean() if len(returns) > 0 else 0
        returns = best_result['test_trades']['returns'].values
        best_result['test_avg_return'] = returns.mean() if len(returns) > 0 else 0

        if ENABLE_OPTUNA_PLOTS:
            save_optuna_plots(study, symbol)

        logging.info(f"Оптимизация для {symbol} успешно завершена: "
                     f"train_sharpe={best_result['train_sharpe']:.2f}, "
                     f"test_sharpe={best_result['test_sharpe']:.2f}, "
                     f"train_trades={best_result['train_num_trades']}, "
                     f"test_trades={best_result['test_num_trades']}, "
                     f"train_max_drawdown={best_result['train_max_drawdown']:.4f}, "
                     f"test_max_drawdown={best_result['test_max_drawdown']:.4f}, "
                     f"train_cumulative_return={best_result['train_cumulative_return']:.2%}, "
                     f"test_cumulative_return={best_result['test_cumulative_return']:.2%}, "
                     f"train_final_capital={best_result['train_final_capital']:.2f}, "
                     f"test_final_capital={best_result['test_final_capital']:.2f}, "
                     f"train_exit_reasons={best_result['train_exit_reasons']}, "
                     f"test_exit_reasons={best_result['test_exit_reasons']}, "
                     f"params={best_result['params']}")

        return best_result, study

    except Exception as e:
        logging.error(f"Optimization failed for {symbol}: {str(e)}", exc_info=True)
        return None
