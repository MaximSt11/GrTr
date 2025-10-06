import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import hashlib
import os
import pyarrow.feather as feather
from config import DATA_DAYS_DEPTH, CACHE_DIR, CACHE_EXPIRE_MINUTES
import logging
from pandas import DataFrame
from typing import Optional

ccxt_logger = logging.getLogger('ccxt')
ccxt_logger.setLevel(logging.INFO)


def _get_cache_key(symbol, timeframe, limit):
    """
    (EN) Generates a cache key for the given parameters.
    (RU) Генерирует ключ кеша для заданных параметров.
    """
    key = f"{symbol}_{timeframe}_{limit}_{DATA_DAYS_DEPTH}"
    return hashlib.md5(key.encode()).hexdigest() + ".feather"


def _save_to_cache(df, cache_key):
    """
    (EN) Saves the DataFrame to a Feather format cache file.
    (RU) Сохраняет DataFrame в файл кэша в формате Feather.
    """
    cache_path = os.path.join(CACHE_DIR, cache_key)
    df.reset_index(inplace=True)
    df['_cache_timestamp'] = datetime.now()
    feather.write_feather(df, cache_path)


def _load_from_cache(cache_key: str) -> Optional[DataFrame]:
    """
        (EN) Loads data from the cache.
        Args:
            cache_key: Hash for the cache file.
        Returns:
            DataFrame with data or None if the cache is missing or expired.
            
        (RU) Векторная загрузка данных из кэша.
        Args:
            cache_key: Хэш для файла кэша.
        Returns:
            DataFrame с данными или None, если кэш отсутствует или устарел.
    """
    cache_path = os.path.join(CACHE_DIR, cache_key)

    if not os.path.exists(cache_path):
        return None

    try:
        df = feather.read_feather(cache_path)
        cache_time = df['_cache_timestamp'].iloc[0]
        df.drop('_cache_timestamp', axis=1, inplace=True)

        if (datetime.now() - cache_time) > timedelta(minutes=CACHE_EXPIRE_MINUTES):
            return None

        df.set_index('timestamp', inplace=True)
        return df
    except Exception:
        os.remove(cache_path)
        return None


def clean_old_cache():
    """
    (EN) Deletes cache files older than 7 days.
    (Added just in case this function was missing)

    (RU) Удаляет файлы кэша старше 7 дней.
    (Добавлено на случай, если этой функции не было)
    """
    if not os.path.exists(CACHE_DIR):
        return
    for file in os.listdir(CACHE_DIR):
        file_path = os.path.join(CACHE_DIR, file)
        try:
            if os.path.isfile(file_path):
                file_age_days = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(file_path))).days
                if file_age_days > 7:
                    os.remove(file_path)
                    logging.debug(f"Removed old cache file: {file}")
        except Exception as e:
            logging.warning(f"Could not process or remove old cache file {file_path}: {e}")


def fetch_data(symbol: str, timeframe: str, limit: int) -> DataFrame:
    """
        (EN) Fetches OHLCV data with caching and outlier filtering.
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT').
            timeframe: Timeframe (e.g., '1h').
            limit: Number of candles.
        Returns:
            DataFrame with columns ['open', 'high', 'low', 'close', 'volume'].
            
        (RU) Получение OHLCV-данных с кэшированием и фильтрацией выбросов.
        Args:
            symbol: Торговая пара (например, 'BTC/USDT').
            timeframe: Таймфрейм (например, '1h').
            limit: Количество свечей.
        Returns:
            DataFrame с колонками ['open', 'high', 'low', 'close', 'volume'].
    """
    cache_key = _get_cache_key(symbol, timeframe, limit)

    clean_old_cache()

    # Проверка кеша/Check cache
    cached_data = _load_from_cache(cache_key)
    if cached_data is not None:
        logging.info(f"Loaded {symbol} {timeframe} from cache: {cache_key}")
        return cached_data

    logging.info(f"Fetching {symbol} {timeframe} from Bybit, limit={limit}")

    # Векторный запрос к API/API Request
    exchange = ccxt.bybit({'enableRateLimit': True})
    since = exchange.parse8601((datetime.now() - timedelta(days=DATA_DAYS_DEPTH)).strftime('%Y-%m-%d %H:%M:%S'))

    markets = exchange.load_markets()
    if symbol not in markets:
        raise ValueError(f"Symbol {symbol} not supported")
    if timeframe not in exchange.timeframes:
        raise ValueError(f"Timeframe {timeframe} not supported")

    # Итеративный запрос данных/Iterative data fetching
    ohlcv = []
    max_candles_per_request = 999  # Ограничение Bybit/Bybit's limit
    candles_to_fetch = limit
    current_since = since

    while candles_to_fetch > 0:
        fetch_limit = min(max_candles_per_request, candles_to_fetch)
        try:
            logging.debug(f"Requesting {fetch_limit} candles from {datetime.fromtimestamp(current_since/1000)}")
            data = exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=fetch_limit)
            if not data:
                logging.info(f"No more data available for {symbol} {timeframe}")
                break
            ohlcv.extend(data)
            candles_to_fetch -= len(data)
            logging.debug(f"Received {len(data)} candles, {candles_to_fetch} remaining")
            if len(data) == 0:
                logging.info(f"No more data available for {symbol} {timeframe}")
                break
            current_since = int(data[-1][0]) + 1  # Следующая свеча после последней/Next candle after the last one
        except ccxt.BaseError as e:
            logging.error(f"Failed to fetch {symbol} {timeframe}: {str(e)}")
            raise

    if not ohlcv:
        raise ValueError(f"No data fetched for {symbol} {timeframe}")

    # Векторное преобразование/DataFrame conversion
    data = np.array(ohlcv)
    df = pd.DataFrame({
        'timestamp': pd.to_datetime(data[:, 0], unit='ms'),
        'open': data[:, 1],
        'high': data[:, 2],
        'low': data[:, 3],
        'close': data[:, 4],
        'volume': data[:, 5]
    }).set_index('timestamp')

    # Удаляем дубликаты/Remove duplicates
    df = df[~df.index.duplicated(keep='first')]

    # Фильтрация выбросов/Outlier filtering
    initial_rows = len(df)
    df = df[df['close'].pct_change().abs() < 0.1]  # Удалить свечи с изменением >10%/Remove candles with >10% change
    filtered_rows = len(df)
    if initial_rows != filtered_rows:
        logging.warning(f"Filtered {initial_rows - filtered_rows} outlier candles for {symbol} {timeframe} (>10% price change)")

    _save_to_cache(df.copy(), cache_key)
    logging.info(f"Saved {symbol} {timeframe} to cache: {cache_key}, rows: {len(df)}")

    if df.empty or len(df) < 10:
        logging.warning(f"Insufficient data for {symbol} {timeframe}: {len(df)} rows")
        raise ValueError("Not enough data")

    return df
