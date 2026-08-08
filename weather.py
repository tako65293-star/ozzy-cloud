"""
weather.py — 天気ウィジェット用のヘルパー。

Open-Meteo(https://open-meteo.com/)を使用。APIキー登録・クレジットカード登録が
一切不要な無料の天気APIなので、GROQ_API_KEYのような環境変数設定も要らない。

現在地点は函館市の緯度経度を既定値としている。別の場所にしたい場合は
下のLAT/LONを書き換えるだけでよい。
"""
import time

import requests

LAT = 41.7687
LON = 140.7291

_CACHE_TTL = 10 * 60  # 10分
_cache = {"data": None, "fetched_at": 0.0}

# Open-MeteoのWMO weather codeを、日本語の一言説明と絵文字にざっくり変換する。
# 全コードを網羅する必要はなく、HUD的にひと目で分かればよいという方針。
_CODE_MAP = {
    0: ("快晴", "☀️"),
    1: ("晴れ", "🌤️"),
    2: ("晴れ時々曇り", "⛅"),
    3: ("曇り", "☁️"),
    45: ("霧", "🌫️"),
    48: ("霧", "🌫️"),
    51: ("小雨", "🌦️"),
    53: ("小雨", "🌦️"),
    55: ("小雨", "🌦️"),
    61: ("雨", "🌧️"),
    63: ("雨", "🌧️"),
    65: ("強い雨", "🌧️"),
    71: ("雪", "🌨️"),
    73: ("雪", "🌨️"),
    75: ("大雪", "❄️"),
    80: ("にわか雨", "🌦️"),
    81: ("にわか雨", "🌦️"),
    82: ("激しいにわか雨", "⛈️"),
    95: ("雷雨", "⛈️"),
    96: ("雷雨", "⛈️"),
    99: ("雷雨", "⛈️"),
}


def get_current_weather(force_refresh=False):
    """
    現在の気温・湿度・天気概況に加えて、今日の最高/最低気温と明日の天気予報も取得する。
    取得に失敗した場合はNoneを返す(呼び出し側のserver.pyが
    エラー時のJSON応答を組み立てる)。
    _CACHE_TTL秒以内の再取得はキャッシュを返す(チャット1往復ごとに
    毎回Open-Meteoへ取りに行かないようにするため)。

    戻り値の例:
        {
            "temp": 21, "humidity": 68, "condition": "晴れ", "icon": "🌤️",
            "today_max": 24, "today_min": 17,
            "tomorrow_condition": "曇り", "tomorrow_icon": "☁️",
            "tomorrow_max": 22, "tomorrow_min": 16,
        }
    """
    now = time.time()
    if not force_refresh and _cache["data"] and (now - _cache["fetched_at"]) < _CACHE_TTL:
        return _cache["data"]

    try:
        res = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT,
                "longitude": LON,
                "current": "temperature_2m,relative_humidity_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "forecast_days": 2,
                "timezone": "Asia/Tokyo",
            },
            timeout=8,
        )
        res.raise_for_status()
        payload = res.json()
        data = payload["current"]
        daily = payload.get("daily") or {}
    except Exception:
        # 取得失敗時、直近のキャッシュが残っていればそれを使い回す
        return _cache["data"]

    code = data.get("weather_code")
    label, icon = _CODE_MAP.get(code, ("不明", "🌡️"))

    result = {
        "temp": round(data.get("temperature_2m", 0)),
        "humidity": round(data.get("relative_humidity_2m", 0)),
        "condition": label,
        "icon": icon,
    }

    # daily配列の0番目=今日、1番目=明日(forecast_days=2で指定した並び順)
    daily_codes = daily.get("weather_code") or []
    daily_max = daily.get("temperature_2m_max") or []
    daily_min = daily.get("temperature_2m_min") or []

    if len(daily_max) > 0 and len(daily_min) > 0:
        result["today_max"] = round(daily_max[0])
        result["today_min"] = round(daily_min[0])

    if len(daily_codes) > 1 and len(daily_max) > 1 and len(daily_min) > 1:
        tomorrow_label, tomorrow_icon = _CODE_MAP.get(daily_codes[1], ("不明", "🌡️"))
        result["tomorrow_condition"] = tomorrow_label
        result["tomorrow_icon"] = tomorrow_icon
        result["tomorrow_max"] = round(daily_max[1])
        result["tomorrow_min"] = round(daily_min[1])

    _cache["data"] = result
    _cache["fetched_at"] = now
    return result