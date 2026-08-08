"""
weather.py — 天気ウィジェット用のヘルパー。

現在の気温・湿度は Open-Meteo(https://open-meteo.com/、APIキー不要)から取得する。
今日/明日の天気・最高/最低気温は、気象庁(JMA)が公式サイトで公開している
予報JSON(https://www.jma.go.jp/bosai/forecast/)から直接取得する。
どちらもAPIキー登録・クレジットカード登録が一切不要な無料のAPI。

JMAの予報JSONは正式に公開されたAPIではなく、気象庁サイトの表示用データを
そのまま利用しているだけなので、将来仕様が変わって取得できなくなる可能性はある。
その場合は_get_jma_forecast()の中身がNoneを返すだけなので、今日/明日の情報が
欠けるだけで、現在の気温取得(Open-Meteo側)には影響しない。

現在地点は函館市を既定値としている。別の場所にしたい場合は
下のLAT/LON/JMA_AREA_CODEを書き換えるだけでよい。
JMAの地域コードは https://www.jma.go.jp/bosai/common/const/area.json で調べられる。
"""
import time
from datetime import datetime, timedelta, timezone

import requests

LAT = 41.7687
LON = 140.7291

# 気象庁の地域コード(函館地方気象台)。他の地域にしたい場合はここを変更する。
JMA_AREA_CODE = "017000"
JMA_FORECAST_URL = f"https://www.jma.go.jp/bosai/forecast/data/forecast/{JMA_AREA_CODE}.json"

JST = timezone(timedelta(hours=9))

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


def _jma_code_icon(code):
    """
    JMAのweatherCode(3桁の文字列。100番台=晴、200番台=曇、300番台=雨、400番台=雪)から
    絵文字をざっくり決める。個々のコードの完全な意味までは追わない(HUD用途には過剰なため)。
    """
    if not code:
        return "🌡️"
    head = code[0]
    return {"1": "☀️", "2": "☁️", "3": "🌧️", "4": "❄️", "5": "🌨️"}.get(head, "🌡️")


def _find_date_index(time_defines, target_date):
    """
    ISO8601の日時文字列リスト(例: "2026-08-08T00:00:00+09:00")の中から、
    target_date(date型)と日付が一致する最初のインデックスを返す。無ければNone。
    """
    for i, t in enumerate(time_defines or []):
        try:
            d = datetime.fromisoformat(t).astimezone(JST).date()
        except Exception:
            continue
        if d == target_date:
            return i
    return None


_WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

_weekly_cache = {"data": None, "fetched_at": 0.0}


def get_weekly_forecast(force_refresh=False):
    """
    気象庁公式の週間予報から、今日を含む7日分の[{date, weekday, condition, icon, max, min}, ...]を返す。
    取得・解析に失敗した場合は空リストを返す。
    """
    now = time.time()
    if not force_refresh and _weekly_cache["data"] is not None and (now - _weekly_cache["fetched_at"]) < _CACHE_TTL:
        return _weekly_cache["data"]

    try:
        res = requests.get(JMA_FORECAST_URL, timeout=8)
        res.raise_for_status()
        payload = res.json()

        short_term = payload[0]
        weekly = payload[1]

        # 天気文言・コードは、3日間予報(今日・明日・明後日を含む、より詳しい文言)と
        # 週間予報(7日分、文言は簡素)の両方を日付でマージして使う。
        weather_lookup = {}  # date -> (condition_text, icon)

        short_weather_series = short_term["timeSeries"][0]
        for area in short_weather_series.get("areas", [])[:1]:
            for t, w, c in zip(
                short_weather_series["timeDefines"],
                area.get("weathers") or [],
                area.get("weatherCodes") or [],
            ):
                try:
                    d = datetime.fromisoformat(t).astimezone(JST).date()
                except Exception:
                    continue
                weather_lookup[d] = (w.replace("　", " ").strip(), _jma_code_icon(c))

        weekly_weather_series = weekly["timeSeries"][0]
        for area in weekly_weather_series.get("areas", [])[:1]:
            for t, c in zip(
                weekly_weather_series["timeDefines"],
                area.get("weatherCodes") or [],
            ):
                try:
                    d = datetime.fromisoformat(t).astimezone(JST).date()
                except Exception:
                    continue
                if d not in weather_lookup:
                    label, icon = _CODE_MAP.get(int(c) // 100 * 100, (None, None)) if c else (None, None)
                    weather_lookup[d] = (label or "", icon or _jma_code_icon(c))

        # 気温は3日間予報+週間予報を日付でマージ(今日は3日間予報側にしかないことが多いため)
        temp_lookup = {}  # date -> (max, min)

        def _to_int(v):
            try:
                return round(float(v))
            except (TypeError, ValueError):
                return None

        for series in (short_term["timeSeries"][-1], weekly["timeSeries"][1]):
            areas = series.get("areas") or []
            if not areas:
                continue
            area = areas[0]
            tmax_list = area.get("tempsMax") or area.get("temps") or []
            tmin_list = area.get("tempsMin") or []
            for i, t in enumerate(series["timeDefines"]):
                try:
                    d = datetime.fromisoformat(t).astimezone(JST).date()
                except Exception:
                    continue
                tmax = _to_int(tmax_list[i]) if i < len(tmax_list) else None
                tmin = _to_int(tmin_list[i]) if i < len(tmin_list) else None
                if d not in temp_lookup:
                    temp_lookup[d] = [None, None]
                if tmax is not None:
                    temp_lookup[d][0] = tmax
                if tmin is not None:
                    temp_lookup[d][1] = tmin

        today = datetime.now(JST).date()
        days = []
        for i in range(7):
            d = today + timedelta(days=i)
            condition, icon = weather_lookup.get(d, ("", "🌡️"))
            tmax, tmin = temp_lookup.get(d, (None, None))
            if tmax is None and tmin is None and not condition:
                continue  # データが無い日は飛ばす(週の終盤など)
            days.append({
                "date": d.strftime("%m/%d"),
                "weekday": _WEEKDAY_JP[d.weekday()],
                "condition": condition,
                "icon": icon,
                "max": tmax,
                "min": tmin,
            })

        _weekly_cache["data"] = days
        _weekly_cache["fetched_at"] = now
        return days
    except Exception:
        return _weekly_cache["data"] or []


def _get_jma_forecast():
    """
    気象庁公式サイトの予報JSONから、今日/明日の天気概況文と最高/最低気温を取得する。
    取得・解析に失敗した場合は空のdictを返す(呼び出し側はOpen-Meteoの値をそのまま使う)。
    """
    try:
        res = requests.get(JMA_FORECAST_URL, timeout=8)
        res.raise_for_status()
        payload = res.json()

        short_term = payload[0]  # 3日間予報(今日・明日・明後日の天気文言)
        weekly = payload[1]  # 週間予報(7日分の最高/最低気温)

        today = datetime.now(JST).date()
        tomorrow = today + timedelta(days=1)

        result = {}

        # ----- 天気概況文(今日・明日) -----
        weather_series = short_term["timeSeries"][0]
        area = weather_series["areas"][0]  # 函館地方気象台の代表エリア
        time_defines = weather_series["timeDefines"]
        weathers = area.get("weathers") or []
        codes = area.get("weatherCodes") or []

        idx_today = _find_date_index(time_defines, today)
        idx_tomorrow = _find_date_index(time_defines, tomorrow)

        if idx_today is not None and idx_today < len(weathers):
            result["today_condition"] = weathers[idx_today].replace("　", " ").strip()
            if idx_today < len(codes):
                result["today_icon"] = _jma_code_icon(codes[idx_today])

        if idx_tomorrow is not None and idx_tomorrow < len(weathers):
            result["tomorrow_condition"] = weathers[idx_tomorrow].replace("　", " ").strip()
            if idx_tomorrow < len(codes):
                result["tomorrow_icon"] = _jma_code_icon(codes[idx_tomorrow])

        # ----- 最高/最低気温 -----
        # 「今日」は3日間予報側(timeSeries[2])に入っていることが多く、
        # 「週間予報」側(weekly)は"明日から7日分"で今日を含まないことがある。
        # そのため、今日は3日間予報→(無ければ)週間予報の順で、
        # 明日は週間予報→(無ければ)3日間予報の順で探す。
        def _to_int(v):
            try:
                return round(float(v))
            except (TypeError, ValueError):
                return None

        def _lookup_temps(series_areas_source, target_date):
            """(timeDefines, areas)の組から、target_dateに一致する日のtempsMax/tempsMinを探す"""
            for time_defines, areas in series_areas_source:
                if not areas:
                    continue
                idx = _find_date_index(time_defines, target_date)
                if idx is None:
                    continue
                a = areas[0]
                tmax_list = a.get("tempsMax") or a.get("temps") or []
                tmin_list = a.get("tempsMin") or []
                tmax = _to_int(tmax_list[idx]) if idx < len(tmax_list) else None
                tmin = _to_int(tmin_list[idx]) if idx < len(tmin_list) else None
                if tmax is not None or tmin is not None:
                    return tmax, tmin
            return None, None

        short_temp_series = short_term["timeSeries"][-1]  # 3日間予報側の気温シリーズ(通常は最後)
        weekly_temp_series = weekly["timeSeries"][1]  # 週間予報側の気温シリーズ

        sources_for_today = [
            (short_temp_series["timeDefines"], short_temp_series["areas"]),
            (weekly_temp_series["timeDefines"], weekly_temp_series["areas"]),
        ]
        sources_for_tomorrow = [
            (weekly_temp_series["timeDefines"], weekly_temp_series["areas"]),
            (short_temp_series["timeDefines"], short_temp_series["areas"]),
        ]

        tmax, tmin = _lookup_temps(sources_for_today, today)
        if tmax is not None:
            result["today_max"] = tmax
        if tmin is not None:
            result["today_min"] = tmin

        tmax, tmin = _lookup_temps(sources_for_tomorrow, tomorrow)
        if tmax is not None:
            result["tomorrow_max"] = tmax
        if tmin is not None:
            result["tomorrow_min"] = tmin

        return result
    except Exception:
        # JMA側の取得・解析に失敗しても、現在の気温(Open-Meteo側)には影響させない
        return {}


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
                # 既定(best_match)は海外モデルとのブレンドで日本国内の精度が
                # 落ちることがあるため、気象庁(JMA)のモデルを明示指定する
                "models": "jma_seamless",
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

    # 気象庁公式の予報値が取れた場合は、そちら(今日/明日の最高最低・天気文言)で上書きする。
    # (Open-Meteoはモデル予測値なのに対し、こちらは気象庁が実際に発表している値そのもの)
    jma = _get_jma_forecast()
    result.update(jma)

    _cache["data"] = result
    _cache["fetched_at"] = now
    return result