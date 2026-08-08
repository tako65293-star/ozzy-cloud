"""
weather.py — 天気ウィジェット用のヘルパー。

Open-Meteo(https://open-meteo.com/)を使用。APIキー登録・クレジットカード登録が
一切不要な無料の天気APIなので、GROQ_API_KEYのような環境変数設定も要らない。

現在地点は函館市の緯度経度を既定値としている。別の場所にしたい場合は
下のLAT/LONを書き換えるだけでよい。
"""
import requests

LAT = 41.7687
LON = 140.7291

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


def get_current_weather():
    """
    現在の気温・湿度・天気概況を取得する。
    取得に失敗した場合はNoneを返す(呼び出し側のserver.pyが
    エラー時のJSON応答を組み立てる)。
    """
    try:
        res = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT,
                "longitude": LON,
                "current": "temperature_2m,relative_humidity_2m,weather_code",
                "timezone": "Asia/Tokyo",
            },
            timeout=8,
        )
        res.raise_for_status()
        data = res.json()["current"]
    except Exception:
        return None

    code = data.get("weather_code")
    label, icon = _CODE_MAP.get(code, ("不明", "🌡️"))

    return {
        "temp": round(data.get("temperature_2m", 0)),
        "humidity": round(data.get("relative_humidity_2m", 0)),
        "condition": label,
        "icon": icon,
    }