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
"""
import re
from datetime import datetime

from flask import Flask, jsonify, request

import llm_client
import memory_manager
from personality import build_personality_prompt, get_num_predict, personality

app = Flask(__name__)

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

memory = memory_manager.get_all()

# 会話履歴(個人利用の1ユーザー想定。PC版と同じくモジュールレベルで共有)
chat_history = []

# 「覚えて」「〇〇って覚えて」を検出する(PC版main.pyのtry_remember相当)
_REMEMBER_RE = re.compile(r"(.+?)って覚えて|覚えて[、。]?(.+)?$")
_NAME_RE = re.compile(r"私の名前は(.+?)です")


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
    now = datetime.now()
    weekday = WEEKDAY_JP[now.weekday()]
    lines = [
        build_personality_prompt(),
        f"現在日時: {now.strftime('%Y年%m月%d日')}({weekday}) {now.strftime('%H:%M')}",
    ]
    if memory.get("user_name"):
        lines.append(f"ユーザーの名前: {memory['user_name']}")
    lines.append("これまでに覚えていること:\n" + memory_manager.build_memory_prompt())
    lines.append(
        "注意: 分からないことを自信ありげに作り話しないでください。"
        "分からない場合は正直に「分かりません」と答えてください。"
        "このクラウド版にはPC操作系のツール(アプリ起動・音量調整など)はありません。"
        "PC操作を頼まれた場合は、PC版OZZYで対応してほしい旨を伝えてください。"
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


@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()
    if not user_input:
        return jsonify({"error": "message is required"}), 400

    remembered = try_remember(user_input)
    reply = ask_ozzy(user_input, chat_history)

    chat_history.append({"role": "user", "content": user_input})
    chat_history.append({"role": "assistant", "content": reply})
    del chat_history[:-20]

    return jsonify({"reply": reply, "remembered": remembered, "name": personality["name"]})


@app.route("/")
def index():
    return _CHAT_PAGE


@app.route("/healthz")
def healthz():
    return "ok"


_CHAT_PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OZZY</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", sans-serif;
         margin: 0; display: flex; flex-direction: column; height: 100vh; }
  #log { flex: 1; overflow-y: auto; padding: 12px; }
  .msg { margin: 8px 0; padding: 10px 14px; border-radius: 14px; max-width: 80%;
         line-height: 1.5; white-space: pre-wrap; }
  .user { background: #2563eb; color: white; margin-left: auto; }
  .ozzy { background: #e5e7eb; color: #111; margin-right: auto; }
  #form { display: flex; padding: 10px; gap: 8px; border-top: 1px solid #ddd; }
  #input { flex: 1; padding: 10px; border-radius: 10px; border: 1px solid #ccc; font-size: 16px; }
  #send { padding: 10px 18px; border-radius: 10px; border: none; background: #2563eb; color: white; }
</style>
</head>
<body>
<div id="log"></div>
<form id="form">
  <input id="input" autocomplete="off" placeholder="OZZYに話しかける...">
  <button id="send" type="submit">送信</button>
</form>
<script>
const log = document.getElementById('log');
const form = document.getElementById('form');
const input = document.getElementById('input');

function addMsg(text, who) {
  const div = document.createElement('div');
  div.className = 'msg ' + who;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  addMsg(text, 'user');
  input.value = '';
  addMsg('...', 'ozzy');
  const thinking = log.lastChild;
  try {
    const res = await fetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text })
    });
    const data = await res.json();
    thinking.textContent = data.reply;
  } catch (err) {
    thinking.textContent = '(通信エラーが発生しました)';
  }
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5151, debug=True)
