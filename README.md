# OZZY Cloud(会話+記憶+人格のみの軽量版)

PC版OZZYからPC操作ツール・wake_word(呼びかけ語)・VOICEVOXを取り除き、
「Groq API + Memory System + Personality System」だけを残した、
**スマホのブラウザからいつでも雑談・相談できる版**です。

PCの電源を切っていても使えます(そのぶん、アプリ起動・音量調整などの
PC操作系ツールはこのクラウド版にはありません。それらが必要なときはPC版OZZYを使ってください)。

## できること / できないこと

| 機能 | クラウド版 |
|---|---|
| 雑談・相談(Groq API) | ○ |
| 記憶(名前・好み・目標など7カテゴリ) | ○ |
| 人格(personality.json) | ○ |
| PC操作(音量・アプリ起動など) | × PC版を使ってください |
| 音声入出力(wake word・VOICEVOX) | × ブラウザのテキストチャットのみ |

## 1. 事前準備

1. [console.groq.com](https://console.groq.com/keys) でGroqのAPIキーを発行(無料・クレジットカード不要)
2. `config/personality.json` を、PC版の実際の設定に合わせて書き換える(そのままでも動きます)

## 2. ローカルで動作確認

```bash
pip install -r requirements.txt --break-system-packages
export GROQ_API_KEY=gsk_xxxxxxxx   # Windowsは set GROQ_API_KEY=gsk_xxxxxxxx
python server.py
```

ブラウザで `http://127.0.0.1:5151` を開いて会話できれば成功です。

## 3. Renderへのデプロイ(無料・クレジットカード不要)

1. このフォルダをGitHubリポジトリにpushする
2. [render.com](https://render.com) にサインアップ(GitHub連携でOK。クレジットカード登録は不要)
3. 「New +」→「Web Service」→ 該当リポジトリを選択
4. 以下を設定
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn server:app`
5. 「Environment」タブで `GROQ_API_KEY` を追加
6. Deploy

デプロイ後に発行されるURL(`https://xxxxx.onrender.com`)にスマホのブラウザからアクセスすれば、
外出先からOZZYと話せます。ホーム画面に追加しておくとアプリのように使えます。

## 4. 注意点(無料枠の制約)

- **15分アクセスがないとスリープ**します。次にアクセスしたとき、起動に30〜60秒かかります(個人の雑談用途なら問題ないはずです)。
- **記憶ファイル(`memory/memory.json`)は再デプロイ時にリセットされる可能性があります**。コードを更新してpushするたびに記憶が消える可能性がある、という点は理解した上で使ってください。
  - 確実に記憶を残したい場合は、`memory_manager.py` の `_load()` / `_save()` を、Supabase等の外部DB(無料・クレジットカード不要)への読み書きに差し替えるのが次のステップです。必要であれば実装します。

## 5. PC版との違い(移植で削ったもの)

- `tools.py` / `automation.py` / `device_tool.py` / `calendar_tool.py` / `security.py` は含めていません(すべてPC操作前提のため)
- `wake_word.py` / `speech_to_text.py` / `voicevox_tts.py` は含めていません(マイク・スピーカーが前提のため)
- `try_remember()` はPC版main.pyの簡易版です。正規表現のパターンは必要に応じて調整してください。
