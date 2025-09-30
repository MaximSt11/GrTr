# GrTr — Flexible Trading System / Гибкая торговая система

**EN | [RU version below](#-гибкая-торговая-система)**

---

## Overview
**GrTr** is a complete ecosystem for developing, backtesting, and deploying algorithmic trading strategies in Python. It provides a modular framework for data handling, performance-accelerated backtesting, advanced optimization (Optuna), and robust live trading on the Bybit exchange.

⚠️ **Important**: This project can execute live trades. Use **testnet first** and review all code before using with real funds.

---

## Features
- **High-Performance Backtesting:** The core backtesting engine is JIT-compiled with `numba` for a massive performance boost, enabling rapid and extensive optimization runs.
- **Advanced Optuna Optimization:** Features a sophisticated objective function with multi-stage hierarchical filtering to efficiently find robust strategies.
- **Independent Watchdog Monitor:** A separate `watchdog.py` process monitors the trader's health, parses logs for key events (entries, exits, errors), and sends detailed real-time alerts to Telegram.
- **Multi-Strategy Architecture:** The `config.py` file acts as a strategy library, allowing you to define and switch between entirely different trading models (e.g., trend-following, scalping) by changing a single key.
- **Detailed Trade Logging:** Automatically saves a full CSV log of all trades from the best-performing Optuna trial for in-depth analysis.
- **Two-Stage Validation:** Employs a robust pipeline where strategies are first discovered by Optuna and then validated for stability using Time Series Split cross-validation.
- **Live Trading Module:** A feature-rich live trader for Bybit designed for reliability and parity with the backtester.
  
---

## Core Concepts

**Design Philosophy: Backtest & Live Parity**

A core principle of this project is to ensure that the live trading module (`trader.py`) behaves identically to the backtesting engine (`backtester.py`). Both modules share the same core logic for signal generation, risk calculation, and trade management. This minimizes discrepancies and ensures that the live performance is a true reflection of the tested strategy.

**Default Strategy: Simple Entry, Sophisticated Management**

The baseline strategy uses a dual-EMA trend-following model for entries and RSI-based signals for exits. The true edge lies in its advanced trade management logic after a position is opened. This logic is fully customizable in the `generate_signals` function to fit your own trading philosophy.

- **State Reconciliation & Self-Healing (`reconcile_state_with_exchange`)**: The trader acts as an "immune system" by periodically checking its internal state against the actual position data from the exchange. If a discrepancy is found (e.g., a "zombie" position), it triggers a "rescue" protocol to take control of the orphaned position and apply the correct risk management. This prevents uncontrolled losses from desynchronization.

- **Real-Time Risk Management via WebSocket (`WebSocketManager`)**: The framework uses a persistent WebSocket connection to receive real-time price ticks. This allows the most critical function—checking the stop-loss—to happen almost instantly (in milliseconds) rather than waiting for the next API poll (seconds), significantly reducing slippage on exits.

- **Resilient API Communication (`api_retry_wrapper`)**: All critical calls to the exchange's API are wrapped in a retry mechanism. This makes the system resilient to transient network issues, request timeouts, or temporary exchange unavailability, preventing crashes due to common connection problems.

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

- Smart Cooldown: After a trade is closed (win or loss), the system activates an intelligent cooldown period for that specific trading pair. This prevents immediate re-entry into a volatile or uncertain market, helping to filter out market noise and avoid over-trading.

- Dynamic Risk Governor: Automatically reduces the risk per trade based on the current drawdown from the high-water mark, protecting capital during losing streaks.
  
- State Reconciliation & Position Rescue: A self-healing mechanism that periodically checks for discrepancies between the bot's state and the exchange. It can "rescue" and take control of orphaned positions to prevent uncontrolled losses.

- Profit Stagnation Exit: An advanced exit condition that closes a profitable trade if its profit decays significantly from its peak value within the trade. This actively protects unrealized gains from turning into smaller wins or losses.

- Opportunistic Cooldown Override: The system can intelligently ignore its own "Smart Cooldown" period if a powerful breakout signal occurs, allowing it to seize strong, immediate opportunities without delay.

- Atomic Entry & Stop-Loss Placement: To minimize risk from the very first moment a trade is live, the system places the entry order and its corresponding stop-loss in a single, atomic API request. This ensures every position is protected from the instant of execution.
  
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

### 1. Backtesting & Optimization
Edit `config.py` to define your strategy and parameter grid, then run:
```bash
python main.py
```
(Note: The number of Time Series Split folds can be adjusted directly in main.py, and the train/test ratio in optimizer.py.)

### 2. Live Trading
First, review and adjust your production configs (`prod_config_*.py`). Then run the trader:
```bash
python run_live.py
```
⚠️ Use testnet API keys in your `.env` file first.

### 3. Monitoring
Run the independent watchdog in a separate terminal to receive Telegram alerts:
```bash
python watchdog.py
```

### 4. Interactive Tuning
For manual parameter fine-tuning and rapid testing, use the interactive tool:
```bash
python interactive_tester.py
```

---

## Backtesting & Optimization Pipeline
1. **Optuna optimization** on parameter grid → selects top strategies.  
2. **Time Series Split validation** → confirms stability on unseen segments.  
3. Optionally: modify **objective function** in `optimizer.py` (Sharpe ratio, profit factor, custom scoring).  

---

## Example Backtest Results (1080 days depth/objective function - maximize Sharpe)

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

## License & Usage
- ✅ Educational and personal use permitted
- ✅ Commercial use requires written permission
- ⚠️ No warranty provided - use at your own risk
- 📧 Contact for commercial licensing

---

## Contact
- GitHub: [MaximSt11](https://github.com/MaximSt11/GrTr)  
- Telegram: @maximevg  

---

# 🇷🇺 Гибкая торговая система

## Обзор
**GrTr** — это полноценная экосистема для разработки, тестирования и развертывания алгоритмических стратегий на Python. Она предоставляет модульный фреймворк для обработки данных, высокопроизводительного бэктестинга, продвинутой оптимизации (Optuna) и надежной реальной торговли на бирже Bybit. 

⚠️ **Важно**: система может совершать реальные сделки. Всегда начинайте с **testnet** и внимательно проверяйте код.

---

## Возможности
- **Высокопроизводительный бэктест:** Ядро системы компилируется с помощью `numba` для огромного прироста скорости, что позволяет проводить быструю и масштабную оптимизацию.
- **Продвинутая оптимизация Optuna:** Используется сложная целевая функция с иерархической фильтрацией для эффективного поиска устойчивых и прибыльных стратегий.
- **Независимый "Сторож" (Watchdog):** Отдельный процесс `watchdog.py` отслеживает состояние бота, анализирует логи и отправляет подробные уведомления о всех ключевых событиях в Telegram.
- **Мульти-стратегическая архитектура:** Файл `config.py` работает как библиотека стратегий, позволяя легко переключаться между разными торговыми моделями (тренд, скальпинг).
- **Детальное логирование сделок:** Система автоматически сохраняет полный список сделок из лучшей попытки Optuna в CSV-файл для углубленного анализа.
- **Двухэтапная проверка стратегий:** Используется надежный конвейер, где стратегии сначала находятся с помощью Optuna, а затем проверяются на устойчивость через Time Series Split.
- **Боевой торговый модуль:** Полнофункциональный модуль для реальной торговли на Bybit, спроектированный для максимальной надежности и соответствия бэктесту.

---

## Дизайн Философия

Соответствие Бэктеста и Реальной Торговли: Ключевой принцип проекта — максимальная идентичность боевого модуля (`trader.py`) и движка бэктестера (`backtester.py`). Оба модуля используют одну и ту же основную логику для генерации сигналов, расчета рисков и управления сделками. Я старался сделать модули максимально одинаковыми, чтобы боевой модуль в точности повторял то, что было протестировано, и результаты бэктестов заслуживали доверия.

- **Сверка состояния и "самоисцеление" (`reconcile_state_with_exchange`)**: Трейдер работает как "иммунная система", периодически сверяя свое внутреннее состояние с реальными данными о позициях на бирже. При обнаружении расхождения (например, "зомби-позиция") запускается протокол "спасения", который берет потерянную позицию под контроль и применяет к ней корректный риск-менеджмент. Это предотвращает неконтролируемые убытки из-за рассинхронизации.

- **Риск-менеджмент в реальном времени через WebSocket (`WebSocketManager`)**: Фреймворк использует постоянное WebSocket-соединение для получения тиков цены в реальном времени. Это позволяет самой критически важной функции — проверке стоп-лосса — происходить практически мгновенно (в миллисекундах), а не ждать следующего запроса к API (секунды), что значительно снижает проскальзывание на выходах.

- **Устойчивость API-соединения (`api_retry_wrapper`)**: Все критические вызовы к API биржи обернуты в механизм повторных попыток. Это делает систему устойчивой к временным сетевым проблемам, таймаутам запросов или недоступности биржи, предотвращая сбои из-за стандартных проблем с соединением.

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

- Умный Кулдаун: После закрытия каждой сделки (неважно, прибыльной или убыточной) система активирует интеллектуальный период "остывания" для данной торговой пары. Это предотвращает мгновенный повторный вход в нестабильный рынок, позволяя отфильтровать шум и избежать избыточной торговли.

- Динамический "Губернатор Риска": Автоматически снижает риск на сделку в зависимости от текущей просадки от максимального капитала (High-Water Mark), защищая депозит в периоды неудач.
  
- Сверка состояния и "спасение" позиций: Механизм самодиагностики, который постоянно сверяет состояние бота с биржей. В случае рассинхрона система способна "подобрать" потерянную позицию и взять ее под управление.

- Выход по стагнации прибыли: Продвинутое условие выхода, которое закрывает прибыльную сделку, если ее нереализованная прибыль значительно снижается от своего пикового значения. Это позволяет активно защищать накопленный профит.

- Оппортунистическое прерывание кулдауна: Система способна интеллектуально проигнорировать свой собственный период "остывания" (Smart Cooldown), если возникает мощный пробойный сигнал, что позволяет не упускать сильные и быстрые рыночные движения.

- Атомарное размещение ордеров: Чтобы минимизировать риск с самого первого момента открытия сделки, система размещает ордер на вход и соответствующий ему стоп-лосс одним, атомарным запросом к API. Это гарантирует, что каждая позиция защищена с момента ее исполнения.

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

### 1. Бэктестинг и оптимизация
Отредактируйте `config.py`, чтобы задать стратегию и сетку параметров, затем запустите:
```bash
python main.py
```
(Примечание: количество фолдов для Time Series Split можно изменить прямо в `main.py`, а соотношение train/test — в `optimizer.py`.)

### 2. Реальная торговля
Сначала проверьте и настройте "боевые" конфиги (`prod_config_*.py`). Затем запустите торговца: 
```bash
python run_live.py
```
⚠️ Сначала используйте testnet API keys в вашем .env файле.

### 3. Мониторинг
Запустите независимого "сторожа" в отдельном терминале для получения оповещений в Telegram:
```bash
python watchdog.py
```

### 4. Интерактивная настройка
Для ручной "подгонки" параметров и быстрой проверки гипотез, используйте интерактивный инструмент:
```bash
python interactive_tester.py
```

---

## Pipeline оптимизации
1. **Optuna** на сетке параметров → поиск лучших стратегий  
2. **Time Series Split** → проверка устойчивости параметров на разных сегментах  
3. Опционально: изменить **целевую функцию** в `optimizer.py` (Sharpe, PF, winrate и т. д.)  

---

## Примеры результатов бэктестов (с глубиной данных в 1080 дней/Целевая функция - максимизация Шарпа)

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

## License & Usage
- ✅ Использование в образовательных целях и в личных целях
- ✅ Для коммерческого использования требуется письменное разрешение
- ⚠️ Гарантия не предоставляется - используйте на свой страх и риск
- 📧 Свяжитесь для получения коммерческого лицензирования

---

## Контакты
- GitHub: [MaximSt11](https://github.com/MaximSt11/GrTr)  
- Telegram: @maximevg  
