import pandas as pd
from main import run_fixed_params_test
from config import CAPITAL

# --- КОНСТАНТЫ ЦВЕТА ---
GREEN = '\033[92m'
RED = '\033[91m'
CYAN = '\033[96m'
YELLOW = '\033[93m'
RESET = '\033[0m'


def is_realistic(results):
    """Проверяет, являются ли результаты бэктеста реалистичными."""
    MAX_REALISTIC_SHARPE = 999999999999999999999999999
    MAX_REALISTIC_PROFIT_FACTOR = 999999999999999999999999999

    if results['test_sharpe'] > MAX_REALISTIC_SHARPE:
        print(f"{YELLOW}ПРЕДУПРЕЖДЕНИЕ: Результат с Test Sharpe > {MAX_REALISTIC_SHARPE} считается аномальным.{RESET}")
        return False

    if results['test_profit_factor'] > MAX_REALISTIC_PROFIT_FACTOR:
        print(
            f"{YELLOW}ПРЕДУПРЕЖДЕНИЕ: Результат с Test Profit Factor > {MAX_REALISTIC_PROFIT_FACTOR} считается аномальным.{RESET}")
        return False

    return True


def print_summary(current_results, best_results):
    if not current_results:
        print("Тест не вернул результатов.")
        return

    print(f"\n{CYAN}--- Сводка по TimeSeriesSplit ---{RESET}")

    def print_metric_line(metric_name, train_curr, test_curr, train_best, test_best):
        train_delta_str = ""
        if train_best is not None:
            delta = train_curr - train_best
            color = GREEN if delta >= 0 else RED
            if "рейт" in metric_name or "просадка" in metric_name:
                train_delta_str = f" {color}({delta:+.1%}){RESET}"
            else:
                train_delta_str = f" {color}({delta:+.2f}){RESET}"

        test_delta_str = ""
        if test_best is not None:
            delta = test_curr - test_best
            color = GREEN if delta >= 0 else RED
            if "рейт" in metric_name or "просадка" in metric_name:
                test_delta_str = f" {color}({delta:+.1%}){RESET}"
            else:
                test_delta_str = f" {color}({delta:+.2f}){RESET}"

        # Основной вывод
        if "рейт" in metric_name or "просадка" in metric_name:
            print(
                f"{metric_name:<25} | Train: {train_curr:.1%}{train_delta_str} | Test: {test_curr:.1%}{test_delta_str}")
        else:
            print(
                f"{metric_name:<25} | Train: {train_curr:.2f}{train_delta_str} | Test: {test_curr:.2f}{test_delta_str}")

    br = best_results

    print_metric_line("Шарп", current_results['train_sharpe'], current_results['test_sharpe'],
                      br['train_sharpe'] if br else None, br['test_sharpe'] if br else None)
    print_metric_line("Профит-фактор", current_results['train_profit_factor'], current_results['test_profit_factor'],
                      br['train_profit_factor'] if br else None, br['test_profit_factor'] if br else None)
    print_metric_line("Винрейт", current_results['train_win_rate'], current_results['test_win_rate'],
                      br['train_win_rate'] if br else None, br['test_win_rate'] if br else None)
    print_metric_line("Макс. просадка", current_results['train_max_drawdown'], current_results['test_max_drawdown'],
                      br['train_max_drawdown'] if br else None, br['test_max_drawdown'] if br else None)

    print(
        f"{'Количество сделок':<25} | Train: {current_results['train_num_trades']} | Test: {current_results['test_num_trades']}")
    print(f"{CYAN}-----------------------------------{RESET}\n")


if __name__ == '__main__':
    base_params = {
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

        'mode': 'short_only',
        "symbol": "SOL/USDT"
    }

    current_params = base_params.copy()
    best_results_so_far = None
    best_params_so_far = None

    print("--- Интерактивный тюнер стратегий ---")
    print("Доступные команды: 'run', 'exit', 'reset', 'best'")

    while True:
        param_to_change = input("Введите имя параметра для изменения или команду: ")

        if param_to_change.lower() == 'exit':
            break

        if param_to_change.lower() == 'run':
            print("Запускаю тест с текущими параметрами...")
            results = run_fixed_params_test("SOL/USDT", current_params, "interactive_run")

            if results:
                print_summary(results, best_results_so_far)
                if not is_realistic(results):
                    print("Аномальный результат отфильтрован и не будет считаться лучшим.")
                elif best_results_so_far is None or results['test_sharpe'] > best_results_so_far['test_sharpe']:
                    print(f"{GREEN}*** Найден новый лучший результат по Test Sharpe! ***{RESET}")
                    best_results_so_far = results.copy()
                    best_params_so_far = current_params.copy()
            continue

        if param_to_change.lower() == 'best':
            if best_params_so_far:
                print("--- Лучшие параметры сессии ---")
                for key, val in best_params_so_far.items():
                    print(f"  {key}: {val}")
                print("-----------------------------")
            else:
                print("Лучший результат еще не найден.")
            continue

        if param_to_change.lower() == 'reset':
            if best_params_so_far:
                current_params = best_params_so_far.copy()
                print("Параметры сброшены к лучшим найденным в сессии.")
            else:
                current_params = base_params.copy()
                print("Параметры сброшены к базовым.")
            continue

        if param_to_change not in current_params:
            print("Ошибка: такого параметра нет.")
            continue

        new_value_str = input(
            f"Текущее значение '{param_to_change}' = {current_params[param_to_change]}. Введите новое: ")

        try:
            original_value = current_params[param_to_change]
            if isinstance(original_value, bool):
                current_params[param_to_change] = new_value_str.lower() in ['true', '1', 't', 'y']
            else:
                current_params[param_to_change] = type(original_value)(new_value_str)
            print(f"Параметр '{param_to_change}' изменен на {current_params[param_to_change]}")
        except (ValueError, TypeError):
            print("Ошибка: неверный тип значения.")