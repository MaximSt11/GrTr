from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator
import logging


def add_indicators(df, params):
    """
    (EN) Adds only the REQUIRED technical indicators to the DataFrame based on the provided params.
    (RU) Добавление только НЕОБХОДИМЫХ технических индикаторов в DataFrame на основе переданных параметров.
    """
    try:
        df = df.copy()
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"Missing required columns: {set(required_cols) - set(df.columns)}")

        indicator_cols = []

        # --- Рассчитываем только те индикаторы, для которых есть параметры/Calculate only indicators for which parameters are provided ---

        # Рассчитываем быструю EMA, если задан ее период. Это нужно для нашей новой шорт-стратегии/Calculate fast EMA if its period is specified. This is needed for our new short strategy.
        if 'fast_ma' in params:
            df['ema_fast'] = EMAIndicator(df['close'], window=params['fast_ma'], fillna=True).ema_indicator()
            indicator_cols.append('ema_fast')

        # Рассчитываем MACD и медленную EMA, только если заданы ОБА периода/Calculate MACD and slow EMA only if BOTH periods are specified.
        if 'fast_ma' in params and 'slow_ma' in params:
            df['ema_slow'] = EMAIndicator(df['close'], window=params['slow_ma'], fillna=True).ema_indicator()
            indicator_cols.append('ema_slow')

            # Синхронизированный MACD/Synchronized MACD
            macd = MACD(df['close'], window_fast=params['fast_ma'], window_slow=params['slow_ma'], window_sign=9,
                        fillna=True)
            df['macd'] = macd.macd()
            df['macd_signal'] = macd.macd_signal()
            df['macd_hist'] = macd.macd_diff()
            indicator_cols.extend(['macd', 'macd_signal', 'macd_hist'])

        if 'rsi_period' in params:
            df['rsi'] = RSIIndicator(df['close'], window=params['rsi_period'], fillna=True).rsi()
            indicator_cols.append('rsi')

        # Расчет средней EMA для тренд-фильтра в скальпинге/Calculate medium EMA for the trend filter in scalping
        if 'medium_ema_period' in params:
            df['ema_medium'] = EMAIndicator(df['close'], window=params['medium_ema_period'],
                                            fillna=True).ema_indicator()
            indicator_cols.append('ema_medium')

        if 'bb_period' in params and 'bb_dev' in params:
            bb = BollingerBands(df['close'], window=params['bb_period'], window_dev=params['bb_dev'], fillna=True)
            df['bb_upper'] = bb.bollinger_hband()
            df['bb_middle'] = bb.bollinger_mavg()
            df['bb_lower'] = bb.bollinger_lband()
            indicator_cols.extend(['bb_upper', 'bb_middle', 'bb_lower'])

        if 'atr_period' in params:
            df['atr'] = AverageTrueRange(df['high'], df['low'], df['close'], window=params['atr_period'],
                                         fillna=True).average_true_range()
            indicator_cols.append('atr')

        if 'stoch_k_period' in params:
            stoch = StochasticOscillator(df['high'], df['low'], df['close'], window=params['stoch_k_period'],
                                         fillna=True)
            df['stoch_k'] = stoch.stoch()
            indicator_cols.append('stoch_k')

        if 'adx_period' in params:
            df['adx'] = ADXIndicator(df['high'], df['low'], df['close'], window=params['adx_period'], fillna=True).adx()
            indicator_cols.append('adx')

        if 'regime_filter_period' in params:
            df['ema_regime'] = EMAIndicator(df['close'], window=params['regime_filter_period'],
                                            fillna=True).ema_indicator()
            indicator_cols.append('ema_regime')

        if params.get('bull_filter_period', 0) > 0:
            df['ema_bull_filter'] = EMAIndicator(df['close'], window=params['bull_filter_period'],
                                                 fillna=True).ema_indicator()
            indicator_cols.append('ema_bull_filter')

        if 'obv_period' in params:
            df['obv'] = OnBalanceVolumeIndicator(df['close'], df['volume'], fillna=True).on_balance_volume()
            df['obv_ma'] = EMAIndicator(df['obv'], window=params['obv_period'], fillna=True).ema_indicator()
            indicator_cols.extend(['obv', 'obv_ma']) # Добавляем обе колонки/Add both columns

        if 'swing_period' in params:
            # Находим максимальный high за последние N свечей/Find the maximum high over the last N candles
            df['swing_high'] = df['high'].rolling(window=params['swing_period']).max()
            indicator_cols.append('swing_high')

        if 'macro_ema_period' in params:
            df['ema_macro'] = EMAIndicator(df['close'], window=params['macro_ema_period'], fillna=True).ema_indicator()
            indicator_cols.append('ema_macro')

        # Проверка данных/Data validation
        if not indicator_cols:
            logging.warning("No indicators were calculated based on the provided params.")
            return df  # Возвращаем df как есть, если не было рассчитано ни одного индикатора/Return df as is if no indicators were calculated


        rows_before = len(df)
        df = df.dropna(subset=indicator_cols)
        rows_after = len(df)
        if rows_before != rows_after:
            logging.debug(f"Dropped {rows_before - rows_after} rows due to NaN in indicators")

        if df.empty:
            raise ValueError("DataFrame is empty after dropping NaN")

        return df

    except Exception as e:
        logging.error(f"Error in add_indicators: {str(e)}", exc_info=True)
        raise
