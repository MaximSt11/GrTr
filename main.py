import sys
import logging
from datetime import datetime
import numpy as np
import pandas as pd
from typing import Dict, Optional
from optimizer import optimize_strategy
from utils.logging import setup_logging
from utils.reporter import (
    save_minimal_results,
    save_successful_trials,
    save_top_5_trials,
    generate_summary_report
)
from data_fetcher import fetch_data
from indicators import add_indicators
from backtester import generate_signals, backtest
from sklearn.model_selection import TimeSeriesSplit
from config import (
    SYMBOLS,
    ENABLE_REPORTER,
    ENABLE_VISUALIZER,
    ENABLE_OPTUNA_PLOTS,
    ENABLE_LOGGING,
    ENABLE_FIXED_PARAMS,
    ENABLE_OPTUNA,
    ENABLE_SUMMARY_REPORT,
    ENABLE_MINIMAL_REPORT,
    ENABLE_SUCCESSFUL_TRIALS_REPORT,
    ENABLE_TOP_5_TRIALS_REPORT,
    FIXED_PARAMS,
    RESULTS_DIR
)

if ENABLE_REPORTER:
    from utils.reporter import log_best_strategy

if ENABLE_VISUALIZER or ENABLE_OPTUNA_PLOTS:
    from utils.visualizer import visualize_strategy


def run_optimization(symbol: str, run_timestamp: str) -> Optional[Dict]:
    """
    (EN) Runs the optimization for a single symbol using Optuna.
    (RU) Запускает оптимизацию для одного символа через Optuna.
    """
    try:
        logging.info(f"\n{'=' * 40}\nGrisha starts optimizing {symbol} with Optuna\n{'=' * 40}")
        logging.debug(f"Starting optimize_strategy for {symbol}")
        start_time = datetime.now()
        result, study = optimize_strategy(symbol, run_timestamp)
        if not result:
            logging.warning(f"No valid strategy found for {symbol}")
            return None
        required_keys = [
            'train_sharpe', 'train_win_rate', 'train_profit_factor', 'train_cumulative_return',
            'train_num_trades', 'train_max_drawdown', 'train_final_capital', 'train_exit_reasons',
            'test_sharpe', 'test_win_rate', 'test_profit_factor', 'test_cumulative_return',
            'test_num_trades', 'test_max_drawdown', 'test_final_capital', 'test_exit_reasons', 'params'
        ]
        if not all(key in result for key in required_keys):
            logging.warning(f"Invalid result for {symbol}: missing keys {set(required_keys) - set(result.keys())}")
            return None
        result['optimization_time'] = (datetime.now() - start_time).total_seconds()
        result['symbol'] = symbol
        if ENABLE_REPORTER:
            log_best_strategy(symbol, result)
        if ENABLE_VISUALIZER:
            visualize_strategy(result, symbol)
        return {'result': result, 'study': study}
    except Exception as e:
        logging.error(f"Error optimizing {symbol}: {str(e)}", exc_info=True)
        return None


def run_fixed_params_test(symbol: str, params: Dict, run_timestamp: str) -> Optional[Dict]:
    """
    (EN) Runs a backtest using a fixed set of parameters.
    (RU) Тестирование фиксированных параметров.
    """
    try:
        logging.info(f"\n{'=' * 40}\nRunning fixed params test for {symbol}\n{'=' * 40}")
        start_time = datetime.now()
        params = params.copy()
        params['symbol'] = symbol
        df = fetch_data(symbol, params['timeframe'], params['limit'])
        tscv = TimeSeriesSplit(n_splits=5) # Количество фолдов/Number of folds
        results = []
        for fold, (train_idx, test_idx) in enumerate(tscv.split(df)):
            total_size = len(train_idx) + len(test_idx)
            train_size = int(total_size * 0.5) # Длина Тест/Трейн//Train/Test length
            if len(train_idx) < train_size:
                train_size = len(train_idx)
            test_size = min(len(test_idx), total_size - train_size)
            train_idx = train_idx[-train_size:]
            test_idx = test_idx[:test_size]
            df_train = df.iloc[train_idx]
            df_test = df.iloc[test_idx]
            logging.info(f"CV Fold {fold}: Train={len(df_train)} rows ({len(df_train)/total_size:.1%}), Test={len(df_test)} rows ({len(df_test)/total_size:.1%})")
            df_train = add_indicators(df_train, params)
            df_train = generate_signals(df_train, params)
            train_result = backtest(df_train, params, trial_number=None, run_timestamp=run_timestamp, period=f"train_fold_{fold}")
            if not train_result:
                logging.warning(f"No valid result for {symbol} (train, fold {fold})")
                continue
            df_test = add_indicators(df_test, params)
            df_test = generate_signals(df_test, params)
            test_result = backtest(df_test, params, trial_number=None, run_timestamp=run_timestamp, period=f"test_fold_{fold}")
            if not test_result:
                logging.warning(f"No valid result for {symbol} (test, fold {fold})")
                continue
            results.append({
                'train': train_result,
                'test': test_result
            })
        if not results:
            logging.error(f"No valid results for {symbol}")
            return None

        train_trades = pd.concat([r['train']['trades'] for r in results], ignore_index=True)
        test_trades = pd.concat([r['test']['trades'] for r in results], ignore_index=True)
        train_exit_reasons = train_trades['exit_reason'].value_counts(normalize=True).to_dict()
        train_exit_reasons = {k: float(v * 100) for k, v in train_exit_reasons.items()}
        test_exit_reasons = test_trades['exit_reason'].value_counts(normalize=True).to_dict()
        test_exit_reasons = {k: float(v * 100) for k, v in test_exit_reasons.items()}

        result = {
            'train_sharpe': float(np.mean([r['train']['sharpe'] for r in results])),
            'train_win_rate': float(np.mean([r['train']['win_rate'] for r in results])),
            'train_profit_factor': float(np.mean([r['train']['profit_factor'] for r in results])),
            'train_cumulative_return': float(np.mean([r['train']['cumulative_return'] for r in results])),
            'train_annualized_return': float(np.mean([r['train']['annualized_return'] for r in results])),
            'train_num_trades': int(np.mean([r['train']['num_trades'] for r in results])),
            'train_max_drawdown': float(np.mean([r['train']['max_drawdown'] for r in results])),
            'train_final_capital': float(np.mean([r['train']['final_capital'] for r in results])),
            'train_trades': train_trades,
            'train_exit_reasons': train_exit_reasons,
            'test_sharpe': float(np.mean([r['test']['sharpe'] for r in results])),
            'test_win_rate': float(np.mean([r['test']['win_rate'] for r in results])),
            'test_profit_factor': float(np.mean([r['test']['profit_factor'] for r in results])),
            'test_cumulative_return': float(np.mean([r['test']['cumulative_return'] for r in results])),
            'test_annualized_return': float(np.mean([r['test']['annualized_return'] for r in results])),
            'test_num_trades': int(np.mean([r['test']['num_trades'] for r in results])),
            'test_max_drawdown': float(np.mean([r['test']['max_drawdown'] for r in results])),
            'test_final_capital': float(np.mean([r['test']['final_capital'] for r in results])),
            'test_trades': test_trades,
            'test_exit_reasons': test_exit_reasons,
            'params': params,
            'optimization_time': (datetime.now() - start_time).total_seconds(),
            'symbol': symbol
        }

        if ENABLE_VISUALIZER:
            visualize_strategy(result, symbol)
        return result
    except Exception as e:
        logging.error(f"Error in fixed params test for {symbol}: {str(e)}", exc_info=True)
        return None


def main():
    """Основная функция выполнения"""
    try:
        setup_logging()
        start_time = datetime.now()
        run_timestamp = start_time.strftime('%Y%m%d_%H%M%S')
        logging.info(f"Starting optimization process with run_timestamp={run_timestamp}")
        logging.info(f"Symbols to process: {', '.join(SYMBOLS)}")
        logging.info(f"Settings: Reporter={ENABLE_REPORTER}, Visualizer={ENABLE_VISUALIZER}, "
                     f"OptunaPlots={ENABLE_OPTUNA_PLOTS}, Logging={ENABLE_LOGGING}, "
                     f"FixedParams={ENABLE_FIXED_PARAMS}, Optuna={ENABLE_OPTUNA}, "
                     f"SummaryReport={ENABLE_SUMMARY_REPORT}, MinimalReport={ENABLE_MINIMAL_REPORT}, "
                     f"SuccessfulTrialsReport={ENABLE_SUCCESSFUL_TRIALS_REPORT}, Top5TrialsReport={ENABLE_TOP_5_TRIALS_REPORT}")
        fixed_results = {}
        optuna_results = {}
        successful_trials_data = {}  # Для хранения данных успешных попыток по символам/To store successful trial data by symbol

        if ENABLE_FIXED_PARAMS:
            for symbol in SYMBOLS:
                logging.info(f"Processing fixed params test for {symbol}")
                result = run_fixed_params_test(symbol, FIXED_PARAMS, run_timestamp)
                if result:
                    fixed_results[f"{symbol}_fixed"] = result
                    save_minimal_results(result, symbol, prefix="fixed_params")
        else:
            logging.info("Fixed params testing is disabled")

        if ENABLE_OPTUNA:
            logging.debug("Starting Optuna optimization for all symbols")
            for symbol in SYMBOLS:
                logging.info(f"Processing Optuna optimization for {symbol}")
                optuna_result = run_optimization(symbol, run_timestamp)
                if optuna_result:
                    result = optuna_result['result']
                    study = optuna_result['study']
                    optuna_results[symbol] = result
                    # Сохраняем минимальный отчет/Save the minimal report
                    if study.best_trial:
                        save_minimal_results(result, symbol, trial_number=study.best_trial.number, study=study)
                    # Собираем данные успешных попыток/Collect data from successful trials
                    trials_data = []
                    for trial in study.trials:
                        if trial.value != float('-inf'):
                            trial_data = {
                                'trial_number': trial.number,
                                'score': trial.value,
                                'params': trial.params,
                                'train_sharpe': trial.user_attrs.get('train_sharpe', 0.0),
                                'train_win_rate': trial.user_attrs.get('train_win_rate', 0.0),
                                'train_profit_factor': trial.user_attrs.get('train_profit_factor', 0.0),
                                'train_cumulative_return': trial.user_attrs.get('train_cumulative_return', 0.0),
                                'train_num_trades': trial.user_attrs.get('train_num_trades', 0),
                                'train_max_drawdown': trial.user_attrs.get('train_max_drawdown', 0.0),
                                'train_exit_reasons': trial.user_attrs.get('train_exit_reasons', {}),
                                'test_sharpe': trial.user_attrs.get('test_sharpe', 0.0),
                                'test_win_rate': trial.user_attrs.get('test_win_rate', 0.0),
                                'test_profit_factor': trial.user_attrs.get('test_profit_factor', 0.0),
                                'test_cumulative_return': trial.user_attrs.get('test_cumulative_return', 0.0),
                                'test_num_trades': trial.user_attrs.get('test_num_trades', 0),
                                'test_max_drawdown': trial.user_attrs.get('test_max_drawdown', 0.0),
                                'test_exit_reasons': trial.user_attrs.get('test_exit_reasons', {})
                            }
                            trials_data.append(trial_data)
                    successful_trials_data[symbol] = trials_data
                    # Сохраняем отчеты успешных и топ-5 попыток/Save reports for successful and top-5 trials
                    save_successful_trials(trials_data, symbol)
                    save_top_5_trials(trials_data, symbol)
        else:
            logging.info("Optuna optimization is disabled")

        valid_optuna_results = {k: v for k, v in optuna_results.items() if v is not None}
        valid_fixed_results = {k: v for k, v in fixed_results.items() if v is not None}
        if valid_optuna_results or valid_fixed_results:
            generate_summary_report(optuna_results, fixed_results)
        else:
            logging.warning("No valid results to generate summary report")

        duration = (datetime.now() - start_time).total_seconds() / 60
        logging.info(f"\n{'=' * 40}")
        logging.info(f"Grisha17 completed this hard work in {duration:.1f} minutes")
        logging.info(f"Success rate: {len(valid_optuna_results)}/{len(SYMBOLS)} (Optuna), "
                     f"{len(valid_fixed_results)}/{len(SYMBOLS)} (Fixed)")
        logging.info(f"Results saved in: {RESULTS_DIR}")
        return 0
    except KeyboardInterrupt:
        logging.info("\nOptimization stopped by user")
        return 1
    except Exception as e:
        logging.error(f"Fatal error in main: {str(e)}", exc_info=True)
        return 2


if __name__ == '__main__':
    sys.exit(main())
