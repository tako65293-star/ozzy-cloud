"""
server.py — OZZYクラウド版(会話+記憶+人格のみ)。
PC版main.pyからPC操作ツール・wake_word・VOICEVOXを取り除き、
「AI Engine(Groq)+ Memory System + Personality System」だけを残した軽量版。

ローカルでの動作確認:
    pip install -r requirements.txt --break-system-packages
    set GROQ_API_KEY=gsk_...   (Windows) / export GROQ_API_KEY=gsk_... (Mac/Linux)
    python server.py
    → http://127.0.0.1:5151 をブラウザで開く

Renderへのデプロイ:
    1. このフォルダをGitHubリポジトリにpush
    2. Render → New → Web Service → そのリポジトリを選択
    3. Build Command: pip install -r requirements.txt
       Start Command: gunicorn server:app
    4. Environment Variables に GROQ_API_KEY を追加
    5. Deploy(クレジットカード登録は不要)

UI(_CHAT_PAGE_TEMPLATE)について:
    テンプレートエンジン(Jinja2のrender_template)は使わず、1つのPython文字列に
    HTML/CSS/JSをまとめている。既存のtemplates/static構成が無いプロジェクトなので、
    Render無料枠にファイルを増やさずデプロイの単純さを保つための選択(static/だけは
    ミタマの立ち絵を置くために新設した)。
    人格名(OZZYなど)だけは personality.json の値をモジュール読み込み時に
    文字列置換(__OZZY_NAME__)で埋め込んでいる。

レイアウト:
    左カラム(companion) = ミタマの立ち絵 + 天気/時計オーバーレイ + ニュース枠
    右カラム(chatPane)  = OZZYとのチャット
    横画面(スマホを横向きで使う想定・PC)ではこの2カラムを維持し、
    縦画面のときだけcompanionを上部の細いバーに畳む(CSSのorientationクエリで切替)。

    ミタマの表情切り替え:
    OZZYの返答をGroq(MODEL_FAST)にもう一度渡し、感情を1語だけ分類させて、
    static/mitama/配下の該当画像にクライアント側で差し替える(classify_emotion)。
    数秒(REVERT_MS)経つと自動でbase.pngに戻る。
    立ち絵はさらにCSSのidle-floatアニメーションで常時わずかに揺れる。

    ニュース枠は今回は見た目のみのプレースホルダー(実データ連携は次回)。
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request

import llm_client
import memory_manager
import news
import weather
from personality import build_personality_prompt, get_num_predict, personality

app = Flask(__name__)

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

# Renderのサーバー環境はデフォルトのタイムゾーンがUTCになっていることが多く、
# datetime.now()をそのまま使うとチャットの「現在日時」が実際とズレる。
# 常に日本時間で計算するようにこれを明示的に指定する。
JST = ZoneInfo("Asia/Tokyo")

memory = memory_manager.get_all()

# 会話履歴(個人利用の1ユーザー想定。PC版と同じくモジュールレベルで共有)
chat_history = []

# 「覚えて」「〇〇って覚えて」を検出する(PC版main.pyのtry_remember相当)
_REMEMBER_RE = re.compile(r"(.+?)って覚えて|覚えて[、。]?(.+)?$")
_NAME_RE = re.compile(r"私の名前は(.+?)です")

# ミタマの表情ファイル(static/mitama/配下)。感情分類の出力キーと対応させる。
EMOTION_FILES = {
    "smile": "smile.png",
    "heart_eyes": "heart_eyes.png",
    "crying": "crying.png",
    "wailing": "wailing.png",
    "gentle_smile": "gentle_smile.png",
    "surprised": "surprised.png",
    "stunned": "stunned.png",
    "angry": "angry.png",
    "impressed": "impressed.png",
    "eyes_closed": "eyes_closed.png",
    "neutral": "base.png",
}


def try_remember(user_input):
    """「覚えて」系の発言・名前の発言を検出し、記憶する。記憶したらTrueを返す。"""
    name_match = _NAME_RE.search(user_input)
    if name_match:
        memory_manager.set_user_name(name_match.group(1).strip())
        return True

    if "覚えて" in user_input:
        fact = user_input.replace("覚えて", "").strip("、。！？!? ")
        if fact:
            return memory_manager.remember(fact)
    return False


def build_system_prompt():
    now = datetime.now(JST)
    weekday = WEEKDAY_JP[now.weekday()]
    lines = [
        build_personality_prompt(),
        f"現在日時: {now.strftime('%Y年%m月%d日')}({weekday}) {now.strftime('%H:%M')}(日本時間)",
    ]

    # 天気・ニュースはUIのHUD/ニュース枠と同じデータソースをそのままLLMにも
    # 渡すことで、チャットで聞かれたときにその場で正しく答えられるようにする。
    current_weather = weather.get_current_weather()
    if current_weather:
        weather_line = (
            "現在の天気(函館市): "
            f"{current_weather['condition']}({current_weather['icon']}) "
            f"気温{current_weather['temp']}°C 湿度{current_weather['humidity']}%"
        )
        if "today_condition" in current_weather:
            weather_line += f" / 今日の予報: {current_weather['today_condition']}"
        if "today_max" in current_weather and "today_min" in current_weather:
            weather_line += (
                f" / 今日の最高{current_weather['today_max']}°C"
                f"・最低{current_weather['today_min']}°C"
            )
        lines.append(weather_line)

        if "tomorrow_condition" in current_weather:
            lines.append(
                "明日の天気(函館市): "
                f"{current_weather['tomorrow_condition']}"
                f"({current_weather.get('tomorrow_icon', '')}) "
                f"最高{current_weather.get('tomorrow_max', '?')}°C"
                f"・最低{current_weather.get('tomorrow_min', '?')}°C"
            )
    else:
        lines.append("現在の天気情報は取得できませんでした(取得エラー)。")

    news_data = news.get_news()
    featured = news_data.get("featured")
    others = news_data.get("others") or []
    if featured:
        detail = f"注目ニュース: 「{featured['title']}」"
        if featured.get("description"):
            detail += f" — {featured['description']}"
        lines.append(detail)
    if others:
        lines.append("その他の見出し:\n" + "\n".join(f"・{h}" for h in others))
    if not featured and not others:
        lines.append("最新ニュースは取得できませんでした(取得エラー)。")

    if memory.get("user_name"):
        lines.append(f"ユーザーの名前: {memory['user_name']}")
    lines.append("これまでに覚えていること:\n" + memory_manager.build_memory_prompt())
    lines.append(
        "注意: 分からないことを自信ありげに作り話しないでください。"
        "分からない場合は正直に「分かりません」と答えてください。"
        "上記の天気・ニュース情報は、ユーザーから聞かれたときや話題に関係する"
        "ときだけ使ってください。毎回の返答で自分から天気やニュースの話を"
        "始める必要はありません。"
        "「今日のニュース」などと聞かれた場合は、上記の注目ニュースについて、"
        "分かっている情報(タイトル・概要)をもとに3〜4文程度でそこそこ詳しく、"
        "分かりやすく説明してください。概要の情報が少ない場合は、"
        "分かる範囲で説明したうえで詳細は元記事を確認してほしい旨を伝えてください。"
        "存在しない詳細を作り話しないでください。"
        "このクラウド版にはPC操作系のツール(アプリ起動・音量調整など)はありません。"
        "PC操作を頼まれた場合は、PC版OZZYで対応してほしい旨を伝えてください。"
        "ユーザーを「お客様」のような接客業めいた敬称で呼ばないでください。"
        "名前が分かっている場合はその名前で呼び、分かっていない場合は"
        "二人称をできるだけ省略するか、砕けた言い方(「あなた」程度)にとどめてください。"
        "返答は基本的に日本語だけで書いてください。"
        "ユーザーが英語など他の言語で話しかけてきた場合を除き、"
        "1つの返答の中に英語や他の言語の単語・文を混ぜないでください。"
    )
    return "\n".join(lines)


def ask_ozzy(user_input, history, mode="casual"):
    messages = [{"role": "system", "content": build_system_prompt()}]
    messages += history
    messages.append({"role": "user", "content": user_input})

    try:
        return llm_client.chat(
            messages,
            model=llm_client.MODEL_CHAT,
            max_tokens=get_num_predict(mode),
            timeout=60,
        )
    except Exception as e:
        print(f"(Groqへの接続に失敗しました: {e})")
        return "すみません、少し考えるのに時間がかかりすぎたようです。もう一度話しかけてもらえますか?"


def classify_emotion(reply_text):
    """
    OZZYの返答テキストから、ミタマに表示させる表情を1つだけ判定する。
    軽量モデル(MODEL_FAST)で十分な単純タスクなので、雑談生成本体とは別に
    もう一度Groqを呼ぶ(判定に失敗・接続エラーの場合は"neutral"にフォールバックする)。
    """
    prompt = (
        "次のセリフを話しているキャラクターの表情として、"
        "以下の単語のうち最もふさわしいものを1つだけ出力してください。"
        "説明文は書かず、単語だけを出力してください。\n\n"
        f"選択肢: {', '.join(EMOTION_FILES.keys())}\n\n"
        f"セリフ: 「{reply_text}」"
    )
    try:
        raw = llm_client.chat(
            [{"role": "user", "content": prompt}],
            model=llm_client.MODEL_FAST,
            timeout=15,
        )
    except Exception:
        return "neutral"

    raw = raw.strip().lower()
    for key in EMOTION_FILES:
        if key in raw:
            return key
    return "neutral"


@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()
    if not user_input:
        return jsonify({"error": "message is required"}), 400

    remembered = try_remember(user_input)
    reply = ask_ozzy(user_input, chat_history)
    emotion = classify_emotion(reply)

    chat_history.append({"role": "user", "content": user_input})
    chat_history.append({"role": "assistant", "content": reply})
    del chat_history[:-20]

    return jsonify({
        "reply": reply,
        "remembered": remembered,
        "name": personality["name"],
        "image": EMOTION_FILES[emotion],
    })


@app.route("/api/weather")
def api_weather():
    data = weather.get_current_weather()
    if not data:
        return jsonify({"error": "weather unavailable"}), 503
    return jsonify(data)


@app.route("/api/news")
def api_news():
    data = news.get_news()
    if not data.get("featured") and not data.get("others"):
        return jsonify({"error": "news unavailable", "featured": None, "others": []}), 503
    return jsonify(data)


@app.route("/")
def index():
    return _CHAT_PAGE


@app.route("/healthz")
def healthz():
    return "ok"


_CHAT_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0A0E13">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="__OZZY_NAME__">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='42' fill='%230A0E13'/%3E%3Ccircle cx='50' cy='50' r='42' fill='none' stroke='%2345D8E8' stroke-width='4'/%3E%3Ccircle cx='50' cy='50' r='14' fill='%2345D8E8'/%3E%3C/svg%3E">
<title>__OZZY_NAME__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    color-scheme: dark;
    --bg: #0A0E13;
    --panel: rgba(20, 27, 35, 0.72);
    --panel-solid: #131a22;
    --border: rgba(148, 196, 208, 0.16);
    --border-strong: rgba(69, 216, 232, 0.4);
    --accent: #45D8E8;
    --accent-2: #8C7CF0;
    --text: #E7EEF3;
    --text-dim: #7E8FA0;
    --text-faint: #4A5A6A;
    --good: #45E0A8;
    --pending: #F0B94A;
    --danger: #F0785A;
    --safe-top: env(safe-area-inset-top, 0px);
    --safe-bottom: env(safe-area-inset-bottom, 0px);
    --safe-left: env(safe-area-inset-left, 0px);
  }

  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }

  html, body { height: 100%; margin: 0; background: var(--bg); }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Noto Sans JP", sans-serif;
    color: var(--text);
    background:
      radial-gradient(ellipse 900px 500px at 15% -10%, rgba(140, 124, 240, 0.16), transparent 60%),
      radial-gradient(ellipse 700px 500px at 100% 0%, rgba(69, 216, 232, 0.12), transparent 55%),
      repeating-linear-gradient(0deg, transparent, transparent 27px, rgba(148,196,208,0.035) 28px),
      repeating-linear-gradient(90deg, transparent, transparent 27px, rgba(148,196,208,0.035) 28px),
      var(--bg);
    overscroll-behavior-y: contain;
  }

  /* ===== 全体の2カラム構成 ===== */
  #stage {
    height: 100vh;
    height: 100dvh;
    display: flex;
    flex-direction: row;
    padding-left: var(--safe-left);
  }

  /* ===== 左カラム: ミタマ + 天気/時計 + ニュース ===== */
  #companion {
    flex: 0 0 34%;
    max-width: 380px;
    min-width: 220px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: calc(10px + var(--safe-top)) 10px 10px 10px;
  }

  .portrait-card {
    position: relative;
    flex: 1 1 auto;
    min-height: 220px;
    border-radius: 18px;
    overflow: hidden;
    border: 1px solid var(--border);
    background: var(--panel-solid);
  }
  .portrait-card img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: top center;
    display: block;
    animation: idle-float 4s ease-in-out infinite;
    transition: opacity .15s ease;
  }
  @keyframes idle-float {
    0%, 100% { transform: translateY(0) scale(1); }
    50% { transform: translateY(-6px) scale(1.02); }
  }

  .hud-bar {
    position: absolute;
    top: 0; left: 0; right: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 10px 12px;
    background: linear-gradient(180deg, rgba(10,14,19,0.85), transparent);
    backdrop-filter: blur(6px);
  }
  .weather-chip {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 10px;
    border-radius: 100px;
    background: rgba(10,14,19,0.55);
    border: 1px solid var(--border);
    font-family: "JetBrains Mono", monospace;
    font-size: 12px;
    letter-spacing: 0.02em;
  }
  .weather-chip .icon { font-size: 14px; }
  .weather-chip .temp { color: var(--text); font-weight: 500; }
  .weather-chip .range { color: var(--text-dim); font-size: 10.5px; }
  .weather-chip .humidity { color: var(--text-dim); }
  .weather-chip-tomorrow { opacity: 0.8; }
  .weather-chip-tomorrow .tomorrow-label { color: var(--text-dim); font-size: 10.5px; }

  .clock-chip {
    font-family: "Space Grotesk", sans-serif;
    font-weight: 600;
    font-size: 17px;
    letter-spacing: 0.02em;
    padding: 4px 10px;
    border-radius: 100px;
    background: rgba(10,14,19,0.55);
    border: 1px solid var(--border);
  }

  .news-card {
    flex: 0 0 auto;
    max-height: 128px;
    border-radius: 16px;
    border: 1px solid var(--border);
    background: var(--panel);
    backdrop-filter: blur(8px);
    padding: 10px 12px;
    overflow-y: auto;
  }
  .news-label {
    font-family: "JetBrains Mono", monospace;
    font-size: 9.5px;
    letter-spacing: 0.16em;
    color: var(--accent);
    margin-bottom: 5px;
  }
  .news-thumb {
    display: none;
    width: 100%;
    height: 40px;
    object-fit: cover;
    border-radius: 8px;
    margin-bottom: 5px;
    border: 1px solid var(--border);
  }
  .news-featured-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--text);
    line-height: 1.35;
    margin-bottom: 2px;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    overflow: hidden;
  }
  .news-featured-desc {
    display: none;
    font-size: 11px;
    color: var(--text-dim);
    line-height: 1.4;
    margin-bottom: 6px;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    overflow: hidden;
  }
  .news-divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 0 0 5px;
  }
  .news-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .news-list li {
    position: relative;
    padding-left: 12px;
    font-size: 11px;
    line-height: 1.35;
    color: var(--text-dim);
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 1;
    overflow: hidden;
  }
  .news-list li::before {
    content: "・";
    position: absolute;
    left: 0;
    color: var(--accent);
  }

  /* ===== 右カラム: チャット ===== */
  #chatPane {
    flex: 1 1 auto;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  #app {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: calc(14px + var(--safe-top)) 16px 12px;
    background: linear-gradient(180deg, rgba(10,14,19,0.92), rgba(10,14,19,0.55));
    backdrop-filter: blur(10px);
    position: relative;
    z-index: 5;
  }

  .brand { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .brand-glyph { display: flex; align-items: flex-end; gap: 3px; height: 20px; flex-shrink: 0; }
  .brand-glyph .bar {
    width: 3px; border-radius: 2px;
    background: linear-gradient(180deg, var(--accent), var(--accent-2));
    transform-origin: bottom;
    animation: barIdle 2.4s ease-in-out infinite;
  }
  .brand-glyph .bar:nth-child(1) { height: 8px; animation-delay: 0s; }
  .brand-glyph .bar:nth-child(2) { height: 18px; animation-delay: .2s; }
  .brand-glyph .bar:nth-child(3) { height: 12px; animation-delay: .4s; }
  .brand-glyph .bar:nth-child(4) { height: 16px; animation-delay: .1s; }
  #app.thinking .brand-glyph .bar { animation: barActive .6s ease-in-out infinite; }
  @keyframes barIdle { 0%,100% { transform: scaleY(.45); opacity:.75; } 50% { transform: scaleY(1); opacity:1; } }
  @keyframes barActive { 0%,100% { transform: scaleY(.35); } 50% { transform: scaleY(1.25); } }

  .brand-text { display: flex; flex-direction: column; line-height: 1.15; min-width: 0; }
  .brand-name { font-family: "Space Grotesk", sans-serif; font-weight: 600; font-size: 17px; letter-spacing: 0.01em; white-space: nowrap; }
  .brand-sub { font-family: "JetBrains Mono", monospace; font-size: 9.5px; letter-spacing: 0.16em; color: var(--text-dim); }

  .status { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
  .status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--pending); box-shadow: 0 0 0 3px rgba(240, 185, 74, 0.18); animation: dotPulse 1.6s ease-in-out infinite; }
  .status-dot.online { background: var(--good); box-shadow: 0 0 0 3px rgba(69, 224, 168, 0.18); animation: none; }
  .status-dot.error { background: var(--danger); box-shadow: 0 0 0 3px rgba(240, 120, 90, 0.18); }
  @keyframes dotPulse { 0%,100% { opacity: 1; } 50% { opacity: .4; } }
  .status-label { font-family: "JetBrains Mono", monospace; font-size: 10.5px; letter-spacing: 0.1em; color: var(--text-dim); }

  #scanline {
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--accent), var(--accent-2), transparent);
    background-size: 200% 100%;
    opacity: 0.55;
    animation: sweep 5s linear infinite;
  }
  @keyframes sweep { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

  #log {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding: 18px 16px 10px;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    gap: 2px;
  }

  #empty-state { margin: auto; text-align: center; padding: 20px; color: var(--text-dim); }
  #empty-state .brand-glyph { justify-content: center; margin: 0 auto 14px; height: 26px; }
  #empty-state .bar { width: 4px; }
  #empty-state .bar:nth-child(1) { height: 10px; }
  #empty-state .bar:nth-child(2) { height: 24px; }
  #empty-state .bar:nth-child(3) { height: 16px; }
  #empty-state .bar:nth-child(4) { height: 20px; }
  #empty-state h2 { font-family: "Space Grotesk", sans-serif; font-size: 15px; font-weight: 600; color: var(--text); margin: 0 0 4px; }
  #empty-state p { font-size: 13.5px; margin: 0; }

  .row { display: flex; flex-direction: column; margin: 7px 0; max-width: 78%; }
  .row.user { align-self: flex-end; align-items: flex-end; }
  .row.ozzy { align-self: flex-start; align-items: flex-start; }

  .msg { padding: 10px 14px; border-radius: 16px; font-size: 15.5px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; }
  .row.user .msg { background: linear-gradient(135deg, var(--accent-2), var(--accent)); color: #0A0E13; font-weight: 500; border-bottom-right-radius: 5px; }
  .row.ozzy .msg { background: var(--panel); backdrop-filter: blur(8px); border: 1px solid var(--border); border-bottom-left-radius: 5px; }
  .row.ozzy .msg.error { border-color: rgba(240, 120, 90, 0.4); color: var(--danger); }

  .meta { font-family: "JetBrains Mono", monospace; font-size: 10px; color: var(--text-faint); margin: 4px 4px 0; letter-spacing: 0.02em; }

  .retry-btn {
    margin-top: 6px;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    letter-spacing: 0.04em;
    color: var(--danger);
    background: rgba(240, 120, 90, 0.08);
    border: 1px solid rgba(240, 120, 90, 0.35);
    border-radius: 8px;
    padding: 5px 10px;
    cursor: pointer;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 5px;
    padding: 3px 9px;
    border-radius: 100px;
    background: rgba(69, 216, 232, 0.1);
    border: 1px solid rgba(69, 216, 232, 0.3);
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    letter-spacing: 0.04em;
    color: var(--accent);
  }

  .dots { display: flex; gap: 4px; padding: 4px 2px; }
  .dots span { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: dotBounce 1.1s ease-in-out infinite; }
  .dots span:nth-child(2) { animation-delay: .15s; }
  .dots span:nth-child(3) { animation-delay: .3s; }
  @keyframes dotBounce { 0%,80%,100% { transform: translateY(0); opacity: .5; } 40% { transform: translateY(-4px); opacity: 1; } }

  #form {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    padding: 10px 14px calc(10px + var(--safe-bottom));
    background: linear-gradient(0deg, rgba(10,14,19,0.95), rgba(10,14,19,0.7));
    backdrop-filter: blur(10px);
    border-top: 1px solid var(--border);
  }

  #input {
    flex: 1;
    resize: none;
    max-height: 140px;
    padding: 11px 15px;
    border-radius: 18px;
    border: 1px solid var(--border);
    background: var(--panel-solid);
    color: var(--text);
    font-size: 16px;
    line-height: 1.4;
    font-family: inherit;
    outline: none;
    transition: border-color .15s ease, box-shadow .15s ease;
  }
  #input:focus { border-color: var(--border-strong); box-shadow: 0 0 0 3px rgba(69, 216, 232, 0.12); }
  #input::placeholder { color: var(--text-faint); }

  #send {
    flex-shrink: 0;
    width: 44px;
    height: 44px;
    border-radius: 50%;
    border: none;
    background: linear-gradient(135deg, var(--accent-2), var(--accent));
    color: #0A0E13;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: opacity .15s ease, transform .1s ease;
  }
  #send:active { transform: scale(0.92); }
  #send:disabled { opacity: .45; cursor: default; }
  #send svg { width: 19px; height: 19px; }

  /* ===== 縦画面: companionを上部の細いバーに畳む ===== */
  @media (orientation: portrait) {
    #stage { flex-direction: column; }
    #companion {
      flex: 0 0 auto;
      max-width: none;
      min-width: 0;
      flex-direction: row;
      align-items: stretch;
      padding: calc(8px + var(--safe-top)) 10px 8px;
      gap: 8px;
    }
    .portrait-card { flex: 0 0 84px; height: 84px; border-radius: 14px; }
    .hud-bar { flex-direction: column; align-items: flex-start; gap: 4px; padding: 6px 8px; }
    .weather-chip, .clock-chip { font-size: 10.5px; padding: 3px 7px; }
    .news-card { flex: 1 1 auto; padding: 8px 12px; max-height: 84px; }
    .news-label { margin-bottom: 4px; }
    .news-thumb { display: none !important; }
    .news-featured-title { font-size: 11.5px; margin-bottom: 2px; -webkit-line-clamp: 2; display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden; }
    .news-featured-desc { display: none !important; }
    .news-divider { display: none; }
    .news-list { display: none; }
  }

  @media (prefers-reduced-motion: reduce) {
    * { animation-duration: .001s !important; animation-iteration-count: 1 !important; }
  }
</style>
</head>
<body>
<div id="stage">
  <aside id="companion">
    <div class="portrait-card">
      <img src="/static/mitama/base.png" alt="ミタマ" id="portraitImg">
      <div class="hud-bar">
        <div class="weather-chip" id="weatherChip">
          <span class="icon">🌡️</span>
          <span class="temp">--°C</span>
          <span class="range">↑--° ↓--°</span>
          <span class="humidity">--%</span>
        </div>
        <div class="weather-chip weather-chip-tomorrow" id="weatherTomorrowChip">
          <span class="tomorrow-label">明日</span>
          <span class="icon">🌡️</span>
          <span class="range">↑--° ↓--°</span>
        </div>
        <div class="clock-chip" id="clock">--:--</div>
      </div>
    </div>
    <div class="news-card">
      <div class="news-label">NEWS</div>
      <img class="news-thumb" id="newsThumb" alt="">
      <div class="news-featured-title" id="newsFeaturedTitle">読み込み中...</div>
      <div class="news-featured-desc" id="newsFeaturedDesc"></div>
      <hr class="news-divider">
      <ul class="news-list" id="newsList"></ul>
    </div>
  </aside>

  <section id="chatPane">
    <div id="app">
      <header>
        <div class="brand">
          <span class="brand-glyph" aria-hidden="true">
            <span class="bar"></span><span class="bar"></span><span class="bar"></span><span class="bar"></span>
          </span>
          <div class="brand-text">
            <span class="brand-name">__OZZY_NAME__</span>
            <span class="brand-sub">CLOUD LINK</span>
          </div>
        </div>
        <div class="status">
          <span class="status-dot" id="statusDot"></span>
          <span class="status-label" id="statusLabel">起動中</span>
        </div>
      </header>
      <div id="scanline"></div>

      <main id="log" aria-live="polite">
        <div id="empty-state">
          <span class="brand-glyph" aria-hidden="true">
            <span class="bar"></span><span class="bar"></span><span class="bar"></span><span class="bar"></span>
          </span>
          <h2>スタンバイ中です</h2>
          <p>何でも話しかけてください。</p>
        </div>
      </main>

      <form id="form">
        <textarea id="input" rows="1" autocomplete="off" placeholder="__OZZY_NAME__に話しかける..."></textarea>
        <button id="send" type="submit" aria-label="送信">
          <svg viewBox="0 0 24 24" fill="none"><path d="M4 12L20 4L13 20L11 13L4 12Z" fill="currentColor"/></svg>
        </button>
      </form>
    </div>
  </section>
</div>

<script>
const app = document.getElementById('app');
const log = document.getElementById('log');
const emptyState = document.getElementById('empty-state');
const form = document.getElementById('form');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');
const statusDot = document.getElementById('statusDot');
const statusLabel = document.getElementById('statusLabel');
const weatherChip = document.getElementById('weatherChip');
const weatherTomorrowChip = document.getElementById('weatherTomorrowChip');
const portraitImg = document.getElementById('portraitImg');

let lastUserMessage = null;
let revertTimer = null;

// 表情画像に切り替え、しばらくしたら自動でbase.pngに戻す
function setExpression(imageFile) {
  portraitImg.src = '/static/mitama/' + imageFile;
  clearTimeout(revertTimer);
  revertTimer = setTimeout(() => {
    portraitImg.src = '/static/mitama/base.png';
  }, 6000);
}

function formatTime(d) {
  return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function scrollToBottom() { log.scrollTop = log.scrollHeight; }
function hideEmptyState() { if (emptyState.parentNode) emptyState.remove(); }

function addMessage(text, who) {
  hideEmptyState();
  const row = document.createElement('div');
  row.className = 'row ' + who;
  const bubble = document.createElement('div');
  bubble.className = 'msg';
  bubble.textContent = text;
  row.appendChild(bubble);
  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = formatTime(new Date());
  row.appendChild(meta);
  log.appendChild(row);
  scrollToBottom();
  return { row, bubble, meta };
}

function addTyping() {
  hideEmptyState();
  const row = document.createElement('div');
  row.className = 'row ozzy';
  const bubble = document.createElement('div');
  bubble.className = 'msg';
  bubble.innerHTML = '<div class="dots"><span></span><span></span><span></span></div>';
  row.appendChild(bubble);
  log.appendChild(row);
  scrollToBottom();
  return { row, bubble };
}

function addRememberedChip(row) {
  const chip = document.createElement('div');
  chip.className = 'chip';
  chip.textContent = '記憶しました';
  row.appendChild(chip);
  scrollToBottom();
}

function setStatus(state, label) {
  statusDot.className = 'status-dot ' + state;
  statusLabel.textContent = label;
}

function autoResize() {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 140) + 'px';
}
input.addEventListener('input', autoResize);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

async function sendMessage(text) {
  lastUserMessage = text;
  addMessage(text, 'user');
  input.value = '';
  autoResize();
  sendBtn.disabled = true;
  app.classList.add('thinking');

  const typing = addTyping();

  try {
    const res = await fetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text })
    });
    if (!res.ok) throw new Error('bad status');
    const data = await res.json();

    typing.bubble.textContent = data.reply;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = formatTime(new Date());
    typing.row.appendChild(meta);

    setStatus('online', 'ONLINE');
    if (data.remembered) addRememberedChip(typing.row);
    if (data.image) setExpression(data.image);
  } catch (err) {
    typing.bubble.classList.add('error');
    typing.bubble.textContent = '接続に失敗しました。もう一度お試しください。';
    const retry = document.createElement('button');
    retry.className = 'retry-btn';
    retry.type = 'button';
    retry.textContent = '再送信';
    retry.addEventListener('click', () => {
      typing.row.remove();
      sendMessage(lastUserMessage);
    });
    typing.row.appendChild(retry);
    setStatus('error', 'オフライン');
  } finally {
    sendBtn.disabled = false;
    app.classList.remove('thinking');
    scrollToBottom();
  }
}

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  sendMessage(text);
});

// Render無料枠はしばらくアクセスが無いとスリープするため、
// 初回接続時は「起動中」の状態を明示してユーザーを待たせている理由を伝える。
async function checkHealth() {
  setStatus('', '起動中');
  try {
    const res = await fetch('/healthz');
    setStatus(res.ok ? 'online' : 'error', res.ok ? 'ONLINE' : 'オフライン');
  } catch (e) {
    setStatus('error', 'オフライン');
  }
}
checkHealth();
input.focus();

// ===== 時計(1秒ごとにクライアント側で更新) =====
function tickClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');
}
tickClock();
setInterval(tickClock, 1000);

// ===== 天気(読み込み時+10分ごとに更新) =====
async function loadWeather() {
  try {
    const res = await fetch('/api/weather');
    if (!res.ok) throw new Error('bad status');
    const data = await res.json();
    weatherChip.querySelector('.icon').textContent = data.icon;
    weatherChip.querySelector('.temp').textContent = data.temp + '°C';
    weatherChip.querySelector('.humidity').textContent = data.humidity + '%';

    const rangeEl = weatherChip.querySelector('.range');
    if (data.today_max !== undefined && data.today_min !== undefined) {
      rangeEl.textContent = `↑${data.today_max}° ↓${data.today_min}°`;
    } else {
      rangeEl.textContent = '';
    }

    if (data.tomorrow_condition !== undefined) {
      weatherTomorrowChip.style.display = '';
      weatherTomorrowChip.querySelector('.icon').textContent = data.tomorrow_icon;
      weatherTomorrowChip.querySelector('.range').textContent =
        `↑${data.tomorrow_max}° ↓${data.tomorrow_min}°`;
    } else {
      weatherTomorrowChip.style.display = 'none';
    }
  } catch (e) {
    weatherChip.querySelector('.temp').textContent = '--°C';
    weatherChip.querySelector('.humidity').textContent = '--%';
  }
}
loadWeather();
setInterval(loadWeather, 10 * 60 * 1000);

// ===== ニュース(読み込み時+15分ごとに更新) =====
const newsThumb = document.getElementById('newsThumb');
const newsFeaturedTitle = document.getElementById('newsFeaturedTitle');
const newsFeaturedDesc = document.getElementById('newsFeaturedDesc');
const newsList = document.getElementById('newsList');

async function loadNews() {
  try {
    const res = await fetch('/api/news');
    if (!res.ok) throw new Error('bad status');
    const data = await res.json();
    const featured = data.featured;
    const others = data.others || [];

    if (featured) {
      newsFeaturedTitle.textContent = featured.title;

      if (featured.image) {
        newsThumb.src = featured.image;
        newsThumb.style.display = 'block';
      } else {
        newsThumb.style.display = 'none';
      }

      if (featured.description) {
        newsFeaturedDesc.textContent = featured.description;
        newsFeaturedDesc.style.display = 'block';
      } else {
        newsFeaturedDesc.style.display = 'none';
      }
    } else {
      newsFeaturedTitle.textContent = 'ニュースを取得できませんでした。';
      newsThumb.style.display = 'none';
      newsFeaturedDesc.style.display = 'none';
    }

    newsList.innerHTML = '';
    others.slice(0, 2).forEach((headline) => {
      const li = document.createElement('li');
      li.textContent = headline;
      newsList.appendChild(li);
    });
  } catch (e) {
    newsFeaturedTitle.textContent = 'ニュースを取得できませんでした。';
    newsThumb.style.display = 'none';
    newsFeaturedDesc.style.display = 'none';
    newsList.innerHTML = '';
  }
}
loadNews();
setInterval(loadNews, 15 * 60 * 1000);
</script>
</body>
</html>
"""

_CHAT_PAGE = _CHAT_PAGE_TEMPLATE.replace("__OZZY_NAME__", personality["name"])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5151, debug=True)