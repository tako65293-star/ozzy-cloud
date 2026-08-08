"""
news.py — ニュース取得用のヘルパー。

weather.pyと同じ方針で、APIキー登録・クレジットカード登録が一切不要な
Yahoo!ニュースのRSSフィード(トピックス主要)を使用する。
※Yahoo!ニュースのRSSは個人利用の範囲での利用を想定したもの。このOZZY Cloudは
  私用の1ユーザー向けチャットであり、公開・再配布は行わない前提で使用する。

先頭の記事だけ「注目ニュース」として扱い、記事ページのOGPメタタグ
(og:image / og:description)からサムネイル画像と概要を追加取得する。
残りはヘッドラインのみのリストとして返す。

取得結果は _CACHE_TTL 秒だけキャッシュし、チャット1往復ごとに
毎回外部サイトへ取りに行かないようにしている(応答速度対策)。
"""
import time
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

NEWS_RSS_URL = "https://news.yahoo.co.jp/rss/topics/top-picks.xml"

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OzzyCloud/1.0)"}

_CACHE_TTL = 15 * 60  # 15分
_cache = {"data": None, "fetched_at": 0.0}


def _fetch_rss_items(limit=6):
    res = requests.get(NEWS_RSS_URL, timeout=8, headers=_HEADERS)
    res.raise_for_status()
    root = ET.fromstring(res.content)

    items = []
    for item in root.findall(".//item")[:limit]:
        title_el = item.find("title")
        link_el = item.find("link")
        if title_el is not None and title_el.text:
            items.append({
                "title": title_el.text.strip(),
                "link": link_el.text.strip() if link_el is not None and link_el.text else None,
            })
    return items


def _fetch_article_meta(url):
    """記事ページのOGPメタタグからサムネイル画像と概要を取得する(失敗時は両方None)。"""
    if not url:
        return None, None
    try:
        res = requests.get(url, timeout=8, headers=_HEADERS)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        image = None
        og_image = soup.find("meta", attrs={"property": "og:image"})
        if og_image and og_image.get("content"):
            image = og_image["content"]

        description = None
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        if og_desc and og_desc.get("content"):
            description = og_desc["content"].strip()
        else:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                description = meta_desc["content"].strip()

        return image, description
    except Exception:
        return None, None


def get_news(limit=6, force_refresh=False):
    """
    {"featured": {"title", "link", "image", "description"} | None,
     "others": ["見出し", ...]}
    を返す。取得に全失敗した場合はfeatured=None, others=[]になる。
    """
    now = time.time()
    if not force_refresh and _cache["data"] and (now - _cache["fetched_at"]) < _CACHE_TTL:
        return _cache["data"]

    try:
        items = _fetch_rss_items(limit=max(limit, 5))
    except Exception:
        # 取得失敗時、直近のキャッシュが残っていればそれを使い回す
        if _cache["data"]:
            return _cache["data"]
        return {"featured": None, "others": []}

    if not items:
        result = {"featured": None, "others": []}
    else:
        top = items[0]
        image, description = _fetch_article_meta(top.get("link"))
        result = {
            "featured": {
                "title": top["title"],
                "link": top.get("link"),
                "image": image,
                "description": description,
            },
            "others": [it["title"] for it in items[1:limit]],
        }

    _cache["data"] = result
    _cache["fetched_at"] = now
    return result


def get_top_news(limit=5):
    """後方互換用: 見出しだけのフラットなリストが欲しい場合に使う。"""
    data = get_news(limit=limit + 1)
    headlines = []
    if data["featured"]:
        headlines.append(data["featured"]["title"])
    headlines += data["others"]
    return headlines[:limit]