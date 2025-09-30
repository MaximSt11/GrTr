# GrTr — Flexible Trading System / Гибкая торговая система

**EN | [RU version below](#-гибкая-торговая-система)**

---

## Overview
**GrTr** is a modular algorithmic trading framework written in Python.  
It provides tools for **data fetching, indicators, backtesting, parameter optimization (Optuna), Time Series Split validation, and live trading (Bybit)**.  

⚠️ **Important**: This project can execute live trades. Use **testnet first** and review all code before using with real funds.

---

## Features
- Backtesting via `main.py`
- Live trading via `run_live.py` (Bybit)
- Two-stage validation:  
  1. **Optuna optimization** on parameter grid  
  2. **Time Series Split (TSS)** for stability check of best parameters  
- Adjustable number of folds and train/test split lengths in TSS
- Target function in `optimizer.py` can be customized
- Multi-strategy setup with flexible configs
- Logging, reporting, watchdog, visualization modules
- Production configs for long/short strategies

---

## Strategy Logic & Trade Management

**Signal Generation Philosophy**

The default strategy is built on a dual-EMA trend-following model with RSI-based exits.

- Long Signal: A long position is initiated when the closing price is above both a short-term (tactical) and a long-term (macro) Exponential Moving Average (EMA), indicating alignment in the trend. The position is exited if the Relative Strength Index (RSI) moves into an overbought condition (e.g., above 75), suggesting the move is exhausted.

- Short Signal: A short position is initiated when the price is below both tactical and macro EMAs. An optional ADX filter can be enabled to ensure entries only occur during strong trends. The position is exited if the RSI moves into an oversold condition (e.g., below 25).

**This is the baseline logic, but the framework is designed for flexibility**. If you have a different trading philosophy, you can easily modify the conditions within the `generate_signals` function to implement your own unique entry and exit criteria.

**Advanced Trade Management Features**

The true strength of this framework lies not just in its entry signals, but in its sophisticated suite of trade and risk management tools, allowing for precise control over every position:

- Position Scaling (Pyramiding): Automatically adds to winning positions to maximize profit during strong trends, with a configurable maximum position size.

- Dynamic Trailing Stops: The stop-loss automatically moves to lock in profits as the price moves in your favor, based on ATR or a fixed percentage.

- Partial Take-Profits: Allows you to secure gains by closing a portion of your position when it hits a predefined profit target.

- Profit Lock (Breakeven Stop): Once a trade is sufficiently in profit, the stop-loss can be moved to the entry price, effectively eliminating the risk of that trade turning into a loss.

- ATR-Based Sizing: Position sizes can be calculated automatically based on market volatility (ATR) to maintain consistent risk across different assets and market conditions.

- Time-Based Exits: Positions can be automatically closed if they remain open for longer than a specified duration (e.g., `max_hold_hours`).

---

## Installation
```bash
git clone https://github.com/MaximSt11/GrTr.git
cd GrTr

python -m venv .venv
source .venv/bin/activate       # macOS / Linux
.venv\Scripts\activate        # Windows

pip install -r requirements.txt
```

---

## Configuration (`config.py`)
Key parameters for running strategies:
- `DATA_DAYS_DEPTH` — depth of historical data for tests  
- `SYMBOLS` — tickers to test  
- `ACTIVE_STRATEGY_KEY` — strategy key for backtest  
- `FIXED_PARAMS_LONG/SHORT` — fixed params for TSS validation  
- `PARAM_GRID_LONG/SHORT` — parameter grids for Optuna (usually 4–6 meaningful parameters)  
- `n_trials` — number of Optuna trials  
- `CAPITAL` — initial capital for backtest  

---

## Usage

### 1. Run Backtest
Edit `config.py` and run:
```bash
python main.py
```
You can adjust:
- number of TSS folds  (in main.py)
- ratio of train/test period length (in optimizer.py)  

### 2. Run Live Trading (Bybit)
Review and adjust configs:  
- `prod_config_long.py`  
- `prod_config_short.py`  

Then run:
```bash
python run_live.py
```
⚠️ Use **testnet API keys** first. Never commit real keys to the repo.

---

## Backtesting & Optimization Pipeline
1. **Optuna optimization** on parameter grid → selects top strategies.  
2. **Time Series Split validation** → confirms stability on unseen segments.  
3. Optionally: modify **objective function** in `optimizer.py` (Sharpe ratio, profit factor, custom scoring).  

---

## Example Backtest Results (1080 days depth)

### Long Strategy (SOL/USDT)
```
train_sharpe: 1.52 | test_sharpe: 3.09
train_win_rate: 74% | test_win_rate: 76%
train_return: 1488% | test_return: 21%
train_trades: 982 | test_trades: 265
train_max_dd: -31% | test_max_dd: -2.8%
```
*Annualized return: 280% (train), 55% (test)*

### Short Strategy (SOL/USDT)
```
train_sharpe: 0.68 | test_sharpe: 2.50
train_win_rate: 79% | test_win_rate: 86%
train_return: 94% | test_return: 41%
train_trades: 84 | test_trades: 30
train_max_dd: -20% | test_max_dd: -11%
```
*Annualized return: 38% (train), 120% (test)*

---

## Project Structure (short)
- `main.py` — backtest entrypoint  (with customizable number of TSS folds)
- `run_live.py` — live trading entrypoint  
- `backtester.py` — backtesting core  
- `optimizer.py` — optimization (with customizable target function and ratio of train/test period length)  
- `indicators.py` — trading TA indicators  
- `trader.py`, `trader_utils.py` — live trading logic  
- `prod_config_*.py` — production configs  
- `requirements.txt` — dependencies  

---

## Safety
- Test in sandbox/testnet first  
- Double-check position sizing and risk controls  
- Do not share or commit API keys  

---

## Contact
- GitHub: [MaximSt11](https://github.com/MaximSt11/GrTr)  
- Telegram: @maximevg  

---

# 🇷🇺 Гибкая торговая система

## Обзор
**GrTr** — модульный фреймворк для алгоритмической торговли на Python.  
Содержит инструменты для **загрузки данных, индикаторов, бэктестинга, оптимизации параметров (Optuna), проверки через Time Series Split и реальной торговли (Bybit)**.  

⚠️ **Важно**: система может совершать реальные сделки. Всегда начинайте с **testnet** и внимательно проверяйте код.

---

## Возможности
- Бэктест через `main.py`  
- Реальная торговля через `run_live.py` (Bybit)  
- Двухступенчатая проверка:  
  1. **Оптимизация параметров через Optuna**  
  2. **Закрепление результата через Time Series Split**  
- Возможность менять количество фолдов и длину train/test периода  
- Целевая функция в `optimizer.py` может быть изменена  
- Поддержка нескольких стратегий  
- Логирование, отчётность, watchdog, визуализация  
- Продакшн-конфиги для long/short стратегий  

---

## Логика Стратегии и Управление Сделками

**Философия Генерации Сигналов**

Стандартная стратегия построена на трендовой модели с использованием двух EMA и выходами по RSI.

- Сигнал на покупку (Long): Длинная позиция открывается, когда цена закрытия находится выше как краткосрочной (тактической), так и долгосрочной (макро) экспоненциальной скользящей средней (EMA). Это указывает на совпадение трендов. Выход из позиции происходит, если индикатор RSI входит в зону перекупленности (например, выше 75), что говорит о возможном истощении движения.

- Сигнал на продажу (Short): Короткая позиция открывается, когда цена находится ниже обеих EMA. Дополнительно можно включить фильтр по ADX, чтобы входить в рынок только при наличии сильного тренда. Выход из позиции осуществляется, когда RSI входит в зону перепроданности (например, ниже 25).

**Это базовая логика, но система создана гибкой**. Если вы придерживаетесь другой торговой философии, вы можете легко поменять условия в функции `generate_signals`, чтобы реализовать ваши собственные критерии входа и выхода.

**Продвинутые Функции Управления Сделками**

Истинная сила фреймворка заключается не только в сигналах, но и в продвинутом наборе инструментов для управления торговлей и рисками, что дает полный контроль над каждой позицией:

- Масштабирование позиции (Пирамидинг): Автоматическое добавление к прибыльным позициям для максимизации дохода во время сильных трендов с настраиваемым максимальным размером.

- Динамический Трейлинг-Стоп: Стоп-лосс автоматически перемещается для фиксации прибыли по мере движения цены в вашу пользу, основываясь на ATR или фиксированном проценте.

- Частичная Фиксация Прибыли: Позволяет зафиксировать часть прибыли, закрыв долю позиции при достижении заранее определенной цели.

- Замок на прибыль (Перевод в безубыток): Как только сделка достигает достаточной прибыли, стоп-лосс может быть перемещен на точку входа, что полностью исключает риск превращения этой сделки в убыточную.

- Расчет размера по ATR: Размер позиции может рассчитываться автоматически на основе волатильности рынка (ATR) для поддержания постоянного уровня риска для разных активов и условий.

- Выход по времени: Позиции могут быть автоматически закрыты, если они остаются открытыми дольше заданного периода (например, `max_hold_hours`).

---


## Установка
```bash
git clone https://github.com/MaximSt11/GrTr.git
cd GrTr

python -m venv .venv
source .venv/bin/activate       # Linux / macOS
.venv\Scripts\activate        # Windows

pip install -r requirements.txt
```

---

## Конфигурация (`config.py`)
Ключевые параметры:
- `DATA_DAYS_DEPTH` — глубина истории для тестов  
- `SYMBOLS` — список тикеров  
- `ACTIVE_STRATEGY_KEY` — ключ стратегии для теста  
- `FIXED_PARAMS_LONG/SHORT` — фиксированные параметры для проверки через TSS  
- `PARAM_GRID_LONG/SHORT` — сетка параметров для Optuna  
- `n_trials` — количество итераций Optuna  
- `CAPITAL` — стартовый капитал для теста  

---

## Использование

### 1. Запуск бэктеста
Редактируем `config.py` и запускаем:
```bash
python main.py
```
Можно регулировать:
- число фолдов TSS (в main.py)
- баланс длины train/test периода (в optimizer.py)

### 2. Запуск боевого модуля (Bybit)
Проверить и настроить:  
- `prod_config_long.py`  
- `prod_config_short.py`  

Затем:
```bash
python run_live.py
```
⚠️ Сначала используйте **testnet API keys**. Никогда не храните реальные ключи в коде.  

---

## Pipeline оптимизации
1. **Optuna** на сетке параметров → поиск лучших стратегий  
2. **Time Series Split** → проверка устойчивости параметров на разных сегментах  
3. Опционально: изменить **целевую функцию** в `optimizer.py` (Sharpe, PF, winrate и т. д.)  

---

## Примеры результатов бэктестов (с глубиной данных в 1080 дней)

### Лонг (SOL/USDT)
```
train_sharpe: 1.52 | test_sharpe: 3.09
train_win_rate: 74% | test_win_rate: 76%
train_return: 1488% | test_return: 21%
train_trades: 982 | test_trades: 265
train_max_dd: -31% | test_max_dd: -2.8%
```
*Годовая доходность: 280% (train), 55% (test)*

### Шорт (SOL/USDT)
```
train_sharpe: 0.68 | test_sharpe: 2.50
train_win_rate: 79% | test_win_rate: 86%
train_return: 94% | test_return: 41%
train_trades: 84 | test_trades: 30
train_max_dd: -20% | test_max_dd: -11%
```
*Годовая доходность: 38% (train), 120% (test)*

---

## Структура проекта (коротко)
- `main.py` — точка входа бэктеста (настраиваемое число фолдов TSS)
- `run_live.py` — точка входа реальной торговли  
- `backtester.py` — ядро бэктеста  
- `optimizer.py` — оптимизация (целевая функция и баланс длины train/test периода настраиваются)  
- `indicators.py` — индикаторы ТА
- `trader.py`, `trader_utils.py` — логика торговли  
- `prod_config_*.py` — конфиги  
- `requirements.txt` — зависимости  

---

## Безопасность
- Начинайте только с тестовой среды (testnet)  
- Проверяйте риск-менеджмент и параметры позиций  
- Никогда не храните API-ключи в коде  

---

## Контакты
- GitHub: [MaximSt11](https://github.com/MaximSt11/GrTr)  
- Telegram: @maximevg  
