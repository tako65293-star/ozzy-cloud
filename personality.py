"""
personality.py — config/personality.json を読み込み、システムプロンプトの
「人格」部分を組み立てる。PC版personality.pyと同じインターフェース
(personality辞書 / build_personality_prompt() / get_num_predict(mode))を維持する。

※ PC版config/personality.jsonの中身と完全に一致させたい場合は、
   config/personality.json をPC版からコピーしてここに上書きしてください。
"""
import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "personality.json")

with open(_CONFIG_PATH, encoding="utf-8") as f:
    personality = json.load(f)


def build_personality_prompt():
    """名前・性格・話し方・関係性・response_styleの方針を1つの文章にまとめる。"""
    return (
        f"あなたの名前は「{personality['name']}」です。"
        f"性格: {personality['personality']}。"
        f"話し方: {personality['speech_style']}。"
        f"ユーザーとの関係性: {personality['relationship']}。"
    )


# response_style(casual/confirmation)に応じてGroqの生成トークン数上限を切り替える。
# 「簡潔に」という指示だけでなく物理的にも長さを制限する(PC版と同じ狙い)。
_NUM_PREDICT = {
    "casual": 400,
    "confirmation": 120,
}


def get_num_predict(mode="casual"):
    return _NUM_PREDICT.get(mode, _NUM_PREDICT["casual"])
