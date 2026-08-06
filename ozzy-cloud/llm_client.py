"""
llm_client.py — 「思考」をGroq API(クラウド)経由で行うための共通ヘルパー。
main.py版と同じインターフェースにしてあるので、そのまま使い回せる。

事前準備(Renderの場合):
  Renderダッシュボード → 対象サービス → Environment → Environment Variables で
  GROQ_API_KEY を登録する(Windows環境変数のsetxは不要)。
"""
import os

from groq import Groq

# ツール判定用(速さ重視・軽量)
MODEL_FAST = "llama-3.1-8b-instant"
# 雑談・応答生成用(精度重視)
MODEL_CHAT = "llama-3.3-70b-versatile"

_api_key = os.environ.get("GROQ_API_KEY")
if not _api_key:
    raise RuntimeError(
        "環境変数 GROQ_API_KEY が設定されていません。"
        "Renderのダッシュボード → Environment で設定してください。"
    )

_client = Groq(api_key=_api_key)


def chat(messages, model=MODEL_CHAT, max_tokens=None, json_mode=False, timeout=40):
    kwargs = {
        "model": model,
        "messages": messages,
        "timeout": timeout,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = _client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


def chat_stream(messages, model=MODEL_CHAT, max_tokens=None, timeout=60):
    kwargs = {
        "model": model,
        "messages": messages,
        "stream": True,
        "timeout": timeout,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    stream = _client.chat.completions.create(**kwargs)
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
