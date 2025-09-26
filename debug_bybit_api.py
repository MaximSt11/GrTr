import requests
import json


def get_bybit_instrument_info(symbol):
    """
    Делает прямой запрос к API Bybit V5 для получения точной информации об инструменте.
    """
    url = "https://api.bybit.com/v5/market/instruments-info"
    params = {
        "category": "linear",
        "symbol": symbol
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        print("--- Полный ответ от API Bybit ---")
        print(json.dumps(data, indent=2))

        if data.get("result") and data["result"].get("list"):
            instrument_info = data["result"]["list"][0]
            lot_size_filter = instrument_info.get("lotSizeFilter")
            print("\n--- Истинный 'lotSizeFilter' для SOLUSDT ---")
            print(json.dumps(lot_size_filter, indent=2))

    except requests.exceptions.RequestException as e:
        print(f"Ошибка запроса: {e}")


get_bybit_instrument_info("SOLUSDT")