import os
import time
import logging
import requests
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- Настройки ---
LOG_FILE_TO_WATCH = "trader.log"
MAX_SILENCE_MINUTES = 15
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Контекст для многострочных логов
entry_context_side = None  # Хранит 'LONG' или 'SHORT' в ожидании деталей входа
pnl_context_side = None  # Хранит 'LONG' или 'SHORT' в ожидании суммы PnL

# Раздельное хранение данных для Long и Short
saved_pnl_data = {}  # e.g., {'LONG': {'pnl': 10.5, 'emoji': '✅'}, 'SHORT': ...}
pnl_save_times = {}  # e.g., {'LONG': datetime_obj, 'SHORT': ...}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def send_telegram_alert(message):
    """Отправляет отформатированное сообщение в Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Токен или ID чата для Telegram не найдены в .env файле.")
        return

    full_message = f"{message}\n\n`--- GrishaLongAss ---`"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": full_message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logging.info("Оповещение в Telegram успешно отправлено.")
        else:
            logging.error(f"Ошибка отправки в Telegram: {response.status_code} - {response.text}")
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение в Telegram: {e}")


def parse_and_notify(line):
    """
    Анализирует строку лога и отправляет соответствующее уведомление.
    """
    global entry_context_side, pnl_context_side, saved_pnl_data, pnl_save_times

    # --- 1. Вход в позицию (Шаг 1: Определение стороны) ---
    match = re.search(r"===== (LONG|SHORT) ПОЗИЦИЯ УСПЕШНО ОТКРЫТА", line)
    if match:
        entry_context_side = match.group(1) # Запоминаем сторону и ждем следующую строку с деталями
        return

    # --- 2. Вход в позицию (Шаг 2: Получение деталей и отправка) ---
    if entry_context_side and "Размер:" in line and "Цена входа:" in line:
        try:
            side = entry_context_side
            size = re.search(r"Размер:\s*([\d.]+)", line).group(1)
            price = re.search(r"Цена входа:\s*([\d.]+)", line).group(1)
            sl_price = re.search(r"SL:\s*([\d.]+)", line).group(1)
            message = (f"📈 *Вход в {side} позицию*\n\n"
                       f"Цена входа: `{price}`\n"
                       f"Размер: `{size}`\n"
                       f"Стоп-лосс: `{sl_price}`")
            send_telegram_alert(message)
        except AttributeError:
            send_telegram_alert(f"⚠️ Ошибка парсинга деталей входа:\n`{line}`")
        finally:
            entry_context_side = None # Сбрасываем контекст
        return
    # Сбрасываем контекст входа, если следующая строка оказалась не той, что мы ждали
    elif entry_context_side and "СИГНАЛ НА ВХОД" not in line: # Более мягкая проверка
        entry_context_side = None


    # --- 3. Полное закрытие (Шаг 1: Определение стороны из строки расчета) ---
    match = re.search(r"\*ФИНАЛЬНЫЙ РАСЧЕТ PNL \((LONG|SHORT)\) ЗАВЕРШЕН\*", line)
    if match:
        pnl_context_side = match.group(1) # Запоминаем сторону и ждем строку с итоговым PnL
        return

    # --- 4. Полное закрытие (Шаг 2: Сохранение PnL) ---
    if pnl_context_side and "ИТОГОВЫЙ PNL по сделке" in line:
        try:
            pnl = re.search(r"ИТОГОВЫЙ PNL по сделке:\s*([\d.-]+) USDT", line).group(1)
            pnl_float = float(pnl)
            emoji = "✅" if pnl_float > 0 else "❌"

            side = pnl_context_side
            saved_pnl_data[side] = {"pnl": pnl_float, "emoji": emoji}
            pnl_save_times[side] = datetime.now()
            logging.info(f"Запомнил PnL для {side}: {pnl_float}. Ожидаю причину закрытия...")
        except (AttributeError, ValueError):
            send_telegram_alert(f"⚠️ Ошибка парсинга PNL сделки:\n`{line}`")
        finally:
            pnl_context_side = None # Сбрасываем контекст
        return

    # --- 5. Полное закрытие (Шаг 3: Поиск причины и отправка) ---
    match = re.search(r"Сброс (LONG|SHORT) состояния по причине: Закрытие по причине:\s*(.*)", line)
    if match:
        side, reason_text = match.groups()
        if side in saved_pnl_data:
            pnl_data = saved_pnl_data.pop(side) # Извлекаем и удаляем данные
            pnl_save_times.pop(side, None)      # Удаляем таймер

            message = (f"{pnl_data['emoji']} *{side} сделка закрыта: {pnl_data['pnl']:+.2f} USDT*\n\n"
                       f"Причина: `{reason_text.strip()}`")
            send_telegram_alert(message)
        else:
            logging.warning(f"Найдена причина закрытия для {side}, но PnL не был сохранен. Строка: {line}")
            message = (f"⚪️ *{side} сделка закрыта*\n\n"
                       f"Причина: `{reason_text.strip()}`\n\n"
                       f"_(PnL не был определен, возможно, сторож перезапускался)_")
            send_telegram_alert(message)
        return

    # --- 6. Частичное закрытие ---
    match = re.search(r"PnL частичной фиксации \((LONG|SHORT)\):\s*([\d.-]+) USDT.*Оставшийся размер:\s*([\d.]+)", line)
    if match:
        try:
            side, pnl, remaining_size = match.groups()
            message = (f"🎯 *Частичный тейк-профит ({side})*\n\n"
                       f"Прибыль части: `{float(pnl):.2f} USDT`\n"
                       f"Осталось в позиции: `{remaining_size}`")
            send_telegram_alert(message)
        except (AttributeError, ValueError):
            send_telegram_alert(f"⚠️ Ошибка парсинга частичного тейк-профита:\n`{line}`")
        return

    # --- 7. Критические ошибки и важные предупреждения ---
    lower_line = line.lower()
    if "критическая ошибка" in lower_line:
        message = f"🚨 *КРИТИЧЕСКАЯ ОШИБКА* 🚨\n\n`{line.strip()}`\n\nТребуется немедленное вмешательство!"
        send_telegram_alert(message)
        return

    if "рассинхрон" in lower_line:
        message = f"🟠 *ВНИМАНИЕ: РАССИНХРОН* 🟠\n\n`{line.strip()}`\n\nТорговец пытается автоматически исправить состояние."
        send_telegram_alert(message)
        return

    # --- 8. Успешное спасение позиции после рассинхрона ---
    match = re.search(r"!!! ПОЗИЦИЯ (LONG|SHORT) УСПЕШНО СПАСЕНА И ЗАЩИЩЕНА !!!", line)
    if match:
        side = match.group(1)
        message = (f"✅ *Позиция {side} успешно спасена!* ✅\n\n"
                   f"Состояние синхронизировано, Торговец установил для позиции защитный стоп-лосс.")
        send_telegram_alert(message)
        return


def watch():
    """Основной цикл сторожевого таймера."""
    global saved_pnl_data, pnl_save_times
    logging.info(f"Сторожевой таймер запущен. Слежу за файлом: {LOG_FILE_TO_WATCH}")
    send_telegram_alert("✅ *Сторож на посту...* (UTA)")

    last_position = 0
    current_inode = None
    silence_alert_sent = False

    while True:
        try:
            # --- Логика таймаута для PnL без причины (для обеих сторон) ---
            now = datetime.now()
            sides_to_clear = []
            for side, save_time in list(pnl_save_times.items()):
                if (now - save_time).total_seconds() > 30:  # Таймаут 30 секунд
                    logging.warning(f"PnL для {side} есть, но причина закрытия не найдена. Отправляю PnL.")
                    if side in saved_pnl_data:
                        pnl_data = saved_pnl_data.pop(side)
                        message = (f"{pnl_data['emoji']} *{side} сделка закрыта: {pnl_data['pnl']:+.2f} USDT*\n\n"
                                   f"_(Причина закрытия не была найдена в логах)_")
                        send_telegram_alert(message)
                    sides_to_clear.append(side)

            for side in sides_to_clear:
                pnl_save_times.pop(side, None)

            # --- Логика чтения файла ---
            if not os.path.exists(LOG_FILE_TO_WATCH):
                if current_inode is not None:
                    logging.warning(f"Файл {LOG_FILE_TO_WATCH} больше не существует. Ожидаю его повторного создания.")
                    current_inode = None
                time.sleep(10)
                continue

            try:
                new_inode = os.stat(LOG_FILE_TO_WATCH).st_ino
                if current_inode is None:
                    current_inode = new_inode
                    with open(LOG_FILE_TO_WATCH, 'r', encoding='utf-8') as f:
                        f.seek(0, 2)
                        last_position = f.tell()
                elif new_inode != current_inode:
                    logging.warning("Обнаружена ротация лог-файла. Начинаю чтение нового файла.")
                    current_inode = new_inode
                    last_position = 0
            except FileNotFoundError:
                continue

            last_modified_time = os.path.getmtime(LOG_FILE_TO_WATCH)
            time_since_modified = (datetime.now() - datetime.fromtimestamp(last_modified_time)).total_seconds() / 60

            if time_since_modified > MAX_SILENCE_MINUTES:
                if not silence_alert_sent:
                    alert_message = (
                        f"🚨 *ТРЕВОГА! Торговец не отвечает!* 🚨\n\n"
                        f"Файл `{LOG_FILE_TO_WATCH}` не обновлялся более *{MAX_SILENCE_MINUTES}* минут.\n"
                        f"Требуется ручная проверка!"
                    )
                    logging.error(alert_message)
                    send_telegram_alert(alert_message)
                    silence_alert_sent = True
            else:
                if silence_alert_sent:
                    logging.info("Торговец снова активен. Сбрасываю флаг тревоги.")
                    send_telegram_alert("✅ *Торговец снова в строю!*")
                    silence_alert_sent = False

            with open(LOG_FILE_TO_WATCH, 'r', encoding='utf-8') as f:
                f.seek(last_position)
                new_lines = f.readlines()
                if new_lines:
                    for line in new_lines:
                        # Игнорируем самые частые и "шумные" сообщения
                        if "Статус: IDLE" in line or "Управление " in line or "WS:" in line:
                            continue
                        parse_and_notify(line.strip())
                last_position = f.tell()

            time.sleep(5)

        except KeyboardInterrupt:
            logging.info("Сторожевой таймер остановлен.")
            send_telegram_alert("⚫️ *Сторожевой таймер остановлен вручную*")
            break
        except Exception as e:
            logging.error(f"Ошибка в цикле сторожевого таймера: {e}", exc_info=True)
            time.sleep(60)


if __name__ == '__main__':
    watch()