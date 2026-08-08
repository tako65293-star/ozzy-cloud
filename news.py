"""
news.py — ニュース見出し取得用のヘルパー。

weather.pyと同じ方針で、APIキー登録・クレジットカード登録が一切不要な
Yahoo!ニュースのRSSフィード(トピックス主要)を使用する。
取得結果は _CACHE_TTL 秒だけキャッシュし、チャット1往復ごとに
毎回外部サイトへ取りに行かないようにしている(応答速度対策)。
"""
import time
import xml.etree.ElementTree as ET

import requests

NEWS_RSS_URL = "https://news.yahoo.co.jp/rss/topics/top-picks.xml"

_CACHE_TTL = 15 * 60  # 15分
_cache = {"headlines": [], "fetched_at": 0.0}


def _fetch_headlines(limit=5):
    res = requests.get(NEWS_RSS_URL, timeout=8)
    res.raise_for_status()
    root = ET.fromstring(res.content)

    headlines = []
    for item in root.findall(".//item")[:limit]:
        title_el = item.find("title")
        if title_el is not None and title_el.text:
            headlines.append(title_el.text.strip())
    return headlines


def get_top_news(limit=5, force_refresh=False):
    """
    最新ニュース見出しをlimit件返す。取得に失敗した場合は空リストを返す
    (呼び出し側のserver.pyが「取得できませんでした」等の表示を組み立てる)。
    """
    now = time.time()
    if not force_refresh and _cache["headlines"] and (now - _cache["fetched_at"]) < _CACHE_TTL:
        return _cache["headlines"][:limit]

    try:
        headlines = _fetch_headlines(limit=max(limit, 5))
    except Exception:
        # 取得失敗時、直近のキャッシュが残っていればそれを使い回す
        return _cache["headlines"][:limit]

    _cache["headlines"] = headlines
    _cache["fetched_at"] = now
    return headlines[:limit]