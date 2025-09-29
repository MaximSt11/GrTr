# GrTr — Flexible Trading System / Гибкая торговая система

**EN | [RU version below](#-гибкая-торговая-система-russian)**

---

## Overview
**GrTr** is a modular algorithmic trading framework written in Python.  
It provides tools for **data fetching, indicators, backtesting, parameter optimization (Optuna), and live trading (Bybit)**.  

⚠️ **Important**: This project can execute live trades. Use **testnet first** and review all code before using with real funds.

---

## Features
- Backtesting via `main.py`
- Live trading via `run_live.py` (Bybit)
- Optuna-based parameter optimization
- Multi-strategy setup with flexible configs
- Logging, reporting, watchdog, visualization modules
- Production configs for long/short strategies

---

## Installation
```bash
git clone https://github.com/MaximSt11/GrTr.git
cd GrTr

python -m venv .venv
source .venv/bin/activate       # macOS / Linux
.venv\Scripts\activate          # Windows

pip install -r requirements.txt
```

---

## Usage

### 1. Run Backtest
Edit `config.py` (symbols, strategy, parameters, data depth) and run:
```bash
python main.py
```

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

## Project Structure (short)
- `main.py` — backtest entrypoint  
- `run_live.py` — live trading entrypoint  
- `backtester.py` — backtesting core  
- `optimizer.py` — parameter optimization (part of system, not standalone entrypoint)  
- `indicators.py` — trading indicators  
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
- Telegram: @maximevg  

---

# 🇷🇺 Гибкая торговая система (Russian)

## Обзор
**GrTr** — модульный фреймворк для алгоритмической торговли на Python.  
Содержит инструменты для **загрузки данных, индикаторов, бэктестинга, оптимизации параметров (Optuna) и реальной торговли (Bybit)**.  

⚠️ **Важно**: система может совершать реальные сделки. Всегда начинайте с **testnet** и внимательно проверяйте код.

---

## Возможности
- Бэктест через `main.py`  
- Реальная торговля через `run_live.py` (Bybit)  
- Встроенная оптимизация параметров (модуль `optimizer.py`)  
- Поддержка нескольких стратегий  
- Логирование, отчётность, watchdog, визуализация  
- Продакшн-конфиги для long/short стратегий  

---

## Установка
```bash
git clone https://github.com/MaximSt11/GrTr.git
cd GrTr

python -m venv .venv
source .venv/bin/activate       # Linux / macOS
.venv\Scripts\activate          # Windows

pip install -r requirements.txt
```

---

## Использование

### 1. Запуск бэктеста
В `config.py` указать параметры (тикеры, стратегия, глубина данных) и запустить:
```bash
python main.py
```

### 2. Запуск реального модуля (Bybit)
Проверить и настроить:
- `prod_config_long.py`  
- `prod_config_short.py`  

Затем:
```bash
python run_live.py
```
⚠️ Сначала используйте **testnet API keys**. Никогда не храните реальные ключи в коде.  

---

## Структура проекта (коротко)
- `main.py` — точка входа бэктеста  
- `run_live.py` — точка входа реальной торговли  
- `backtester.py` — ядро бэктеста  
- `optimizer.py` — оптимизация параметров
- `indicators.py` — индикаторы  
- `trader.py`, `trader_utils.py` — логика торговли  
- `prod_config_*.py` — конфиги для работы  
- `requirements.txt` — зависимости  

---

## Безопасность
- Начинайте только с тестовой среды (testnet)  
- Проверяйте риск-менеджмент и параметры позиций  
- Не храните и не публикуйте API-ключи  


---

## Контакты
- Telegram: @maximevg  
