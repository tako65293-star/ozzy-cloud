"""
memory_manager.py — 7カテゴリ(profile/preferences/goals/projects/experiences/
knowledge/rules)の長期記憶をmemory/memory.jsonに保存する。
PC版memory_manager.pyと同じ「JSON+都度分類方式」をクラウド版として移植したもの。

⚠️ Render無料Webサービスのディスクは、再デプロイ時にリセットされる可能性がある。
   個人利用でこまめな再デプロイをしないなら実用上は問題ないが、
   確実に記憶を残したい場合はSupabase等の外部DBへの保存先変更を検討すること
   (差し替えるのはこのファイルのload()/save()だけでよい構成にしてある)。
"""
import difflib
import json
import os

import llm_client

_MEMORY_PATH = os.path.join(os.path.dirname(__file__), "memory", "memory.json")

CATEGORIES = [
    "profile", "preferences", "goals", "projects",
    "experiences", "knowledge", "rules",
]

_DEFAULT_MEMORY = {"user_name": None, **{c: [] for c in CATEGORIES}}


def _load():
    if not os.path.exists(_MEMORY_PATH):
        return dict(_DEFAULT_MEMORY)
    with open(_MEMORY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    # 将来カテゴリが増えた場合でも欠けているキーを補う
    for c in CATEGORIES:
        data.setdefault(c, [])
    data.setdefault("user_name", None)
    return data


def _save(data):
    os.makedirs(os.path.dirname(_MEMORY_PATH), exist_ok=True)
    with open(_MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_memory = _load()


def get_all():
    return _memory


def save_memory():
    _save(_memory)


def classify_category(fact):
    """文言をどのカテゴリに入れるかだけをGroqに判定させる(文言自体は書き換えない)。"""
    prompt = (
        "次の発言を、以下のカテゴリのうち最もふさわしい1つに分類してください。"
        "カテゴリ名だけを出力し、説明文は書かないでください。\n\n"
        "profile: 名前・基本属性など変化の少ない情報\n"
        "preferences: 好きな物・趣味・好み\n"
        "goals: 目標・計画\n"
        "projects: 制作物・開発記録\n"
        "experiences: 日々の出来事\n"
        "knowledge: 勉強内容・知識\n"
        "rules: ユーザーがOZZYに指示した恒常的なルール\n\n"
        f"発言: 「{fact}」"
    )
    try:
        raw = llm_client.chat(
            [{"role": "user", "content": prompt}],
            model=llm_client.MODEL_FAST,
            timeout=20,
        )
    except Exception:
        return "knowledge"

    raw = raw.strip().lower()
    for c in CATEGORIES:
        if c in raw:
            return c
    return "knowledge"


def already_has(category, fact, threshold=0.8):
    """既存の同カテゴリ内エントリと文字列類似度が高いものがあれば重複とみなす。"""
    for existing in _memory.get(category, []):
        ratio = difflib.SequenceMatcher(None, existing, fact).ratio()
        if ratio >= threshold:
            return True
    return False


def add_entry(category, fact):
    if category not in CATEGORIES:
        category = "knowledge"
    if already_has(category, fact):
        return False
    _memory.setdefault(category, []).append(fact)
    save_memory()
    return True


def delete_entry(category, index):
    entries = _memory.get(category, [])
    if 0 <= index < len(entries):
        entries.pop(index)
        save_memory()
        return True
    return False


def remember(fact):
    """文言をそのまま(要約せず)分類して保存する。PC版のtry_remember()から呼ばれる想定。"""
    category = classify_category(fact)
    return add_entry(category, fact)


def set_user_name(name):
    _memory["user_name"] = name
    save_memory()


def build_memory_prompt():
    """rules→profile→preferences→goals→projects→knowledge→experiences(直近3件)の順で整形する。
    experiencesを5→3件に減らしているのは、毎回のシステムプロンプトに丸ごと乗るぶんの
    トークン消費を抑えるため(Groq無料枠の1日トークン上限対策)。"""
    order = ["rules", "profile", "preferences", "goals", "projects", "knowledge"]
    lines = []
    for c in order:
        for fact in _memory.get(c, []):
            lines.append(f"・{fact}")
    for fact in _memory.get("experiences", [])[-3:]:
        lines.append(f"・{fact}")
    if not lines:
        return "(まだ記憶はありません)"
    return "\n".join(lines)