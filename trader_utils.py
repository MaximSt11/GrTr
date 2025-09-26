import ccxt
import time
import logging
import os
import json
from datetime import datetime
import websocket
import threading
from dotenv import load_dotenv


STATE_FILE = "trader_state.json"

# --- Вспомогательные функции API и состояния ---

load_dotenv()


def api_retry_wrapper(api_call, *args, **kwargs):
    """Обертка для вызовов API с механизмом повторных попыток."""
    max_retries = 3
    retry_delay_seconds = 5
    for attempt in range(max_retries):
        try:
            return api_call(*args, **kwargs)
        except (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable) as e:
            if attempt < max_retries - 1:
                logging.warning(f"Временная ошибка API: {e}. Попытка {attempt + 1}/{max_retries}...")
                time.sleep(retry_delay_seconds)
            else:
                logging.error(f"Не удалось выполнить вызов API после {max_retries} попыток.")
                raise
        except ccxt.ExchangeError as e:
            logging.error(f"Постоянная ошибка API: {e}")
            raise


def save_state(state):
    """Сохраняет состояние бота в JSON файл."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4, default=str)
    logging.info(f"Состояние сохранено в {STATE_FILE}")


def load_state():
    """Загружает состояние бота из JSON файла."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            try:
                state = json.load(f)
                if state.get('entry_time'):
                    state['entry_time'] = datetime.fromisoformat(state['entry_time'])

                if state.get('last_tsl_exit_timestamp'):
                    # Проверяем, это число (старый формат) или строка-дата (новый)
                    if isinstance(state['last_tsl_exit_timestamp'], str):
                         state['last_tsl_exit_timestamp'] = datetime.fromisoformat(state['last_tsl_exit_timestamp'])
                    # Обратная совместимость со старым форматом float/int
                    elif isinstance(state['last_tsl_exit_timestamp'], (float, int)):
                         state['last_tsl_exit_timestamp'] = datetime.fromtimestamp(state['last_tsl_exit_timestamp'])

                logging.info(f"Состояние успешно загружено из {STATE_FILE}")
                return state
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logging.warning(f"Файл состояния {STATE_FILE} поврежден или имеет неверный формат ({e}). Начинаем с чистого листа.")
                return {}
    return {}


def connect_to_bybit():
    """Подключается к Bybit API, используя ключи из .env файла."""
    try:
        api_key = os.getenv("BYBIT_API_KEY")
        api_secret = os.getenv("BYBIT_API_SECRET")
        if not api_key or not api_secret:
            logging.error("API ключ или секрет не найдены в .env файле.")
            return None

        exchange = ccxt.bybit({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',
            },
        })

        exchange.load_markets()
        logging.info("Успешное подключение к Bybit API (режим SWAP).")
        return exchange
    except Exception as e:
        logging.error(f"Ошибка подключения к Bybit: {e}", exc_info=True)
        return None


def log_initial_balance(exchange):
    """Запрашивает и выводит в лог стартовый баланс."""
    try:
        logging.info("Запрос стартового баланса...")
        balance_data = api_retry_wrapper(exchange.fetch_balance)
        usdt_balance = balance_data.get('total', {}).get('USDT', 0.0)
        logging.info(f"Стартовый баланс ЕТА: {usdt_balance:.2f} USDT")
    except Exception as e:
        logging.error(f"Не удалось получить стартовый баланс: {e}")


# --- WebSocket менеджер ---
class WebSocketManager:
    """
    Класс для управления WebSocket-соединением в отдельном потоке.
    Получает тики (изменения цены) в реальном времени.
    """
    def __init__(self, symbol):
        self._ws = None
        self.latest_price = None
        self._symbol = symbol.replace('/', '').split(':')[0]
        self._url = f"wss://stream.bybit.com/v5/public/linear"
        self._thread = threading.Thread(target=self._run)
        self._running = False
        self._lock = threading.Lock()

    def _on_message(self, ws, message):
        data = json.loads(message)
        # Bybit v5 tickers stream отправляет данные как словарь (dict), а не список (list)
        # и использует ключ 'lastPrice'
        if 'topic' in data and data['topic'].startswith('tickers.') and 'data' in data:
            if isinstance(data['data'], dict) and 'lastPrice' in data['data']:
                with self._lock:
                    self.latest_price = float(data['data']['lastPrice'])

    def _on_error(self, ws, error):
        logging.error(f"WebSocket ошибка: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        logging.warning("WebSocket соединение закрыто.")

    def _on_open(self, ws):
        logging.info("WebSocket соединение открыто.")
        ws.send(json.dumps({
            "op": "subscribe",
            "args": [f"tickers.{self._symbol}"]
        }))

    def _run(self):
        self._ws = websocket.WebSocketApp(self._url,
                                          on_open=self._on_open,
                                          on_message=self._on_message,
                                          on_error=self._on_error,
                                          on_close=self._on_close)
        while self._running:
            self._ws.run_forever(ping_interval=20, ping_timeout=10)
            if self._running: # Проверяем, не была ли дана команда на остановку
                logging.info("Переподключение WebSocket через 10 секунд...")
                time.sleep(10)

    def start(self):
        self._running = True
        self._thread.start()
        logging.info("WebSocket менеджер запущен в фоновом потоке.")

    def stop(self):
        self._running = False
        if self._ws:
            self._ws.close()
        self._thread.join()
        logging.info("WebSocket менеджер остановлен.")

    def get_latest_price(self):
        with self._lock:
            return self.latest_price
