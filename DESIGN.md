# JARVIS 秘書端末 実装設計書

iPhone 13 Pro を常設AI秘書端末にし、音声で Obsidian Vault と Codex を操作する。

- 設計日：2026-08-25（原本：Start Vault `02_projects/脳が育つAI秘書.md`）
- 設計書化：2026-08-26
- 実装担当：Codex
- この文書が実装の正本。原本ノートと食い違ったらこの文書を優先する

---

## 0. 読む順と前提

### 実装者が最初に読むもの

1. この文書（全体）
2. `AGENTS.md`（作業ルール）
3. Vault 側 `_kit/AI_RULES.md`（書き込み規約。Phase 3 以降で必要）

### 前提環境

| 項目 | 値 |
|---|---|
| PC | CachyOS（Arch系 Linux） |
| PCシェル | fish |
| 端末 | iPhone 13 Pro / iOS Safari・PWA |
| 設置 | 横向き・給電・スタンド常設 |
| ネットワーク | 同一Wi-Fi内のみ。ポート開放しない |
| Vault実パス | `/home/haru/ドキュメント/Start Vault`（`.env` で指定） |
| リポジトリ | `~/dev/jarvis-secretary/`（Vault の外） |

**Vault のファイルをこのリポジトリへコピーしない。** サーバーは実パスを参照する。

---

## 1. 完成時の体験

1. iPhone は横向き・給電でスタンドに常設
2. 待機中の秘書は目を閉じ、画面は暗い
3. 短時間に2回手を叩くと目を開き「はい、どうしました？」と応答
4. ユーザーが自然な日本語で指示する
5. iPhone が音声を PC へ送り、PC が文字起こし・用件判定・実行を担当
6. Vault への書き込みは iPhone に承認／却下を表示
7. 結果を音声と字幕で返し、無音が続くと目を閉じて待機へ戻る

---

## 2. 確定事項

未決だった5点は決定済み。**実装者が再検討しない。**

| # | 項目 | 決定 | 理由 |
|---|---|---|---|
| 1 | 実行役エージェント | **Codex CLI** | ログイン済み。アダプター層は差し替え可能に保つ |
| 2 | 音声認識 | **faster-whisper** | pip 完結。FastAPI と同一プロセスに載る |
| 3 | 回答音声 | **iPhone 標準 Web Speech API** | MVP は実装ゼロ・遅延最小。PC側TTSへ差し替えられる境界を切る |
| 4 | 保存時の運用 | **承認後にファイル更新まで。git commit は自動化しない** | ユーザーの未コミット作業と混ざる事故を避ける |
| 5 | 外出先利用 | **不要**（MVP は同一Wi-Fi内のみ） | 公開ポートを作らない |

### 基本方針

- iPhone は「顔・マイク・スピーカー・承認画面」、PC は「常駐する頭脳」
- **AI API を使わない。** 手拍子検出・音声認識・読み上げはすべてローカル処理
- 手拍子検出に LLM を使わない
- Obsidian を長期記憶の正本とし、JARVIS 独自の恒久メモリを増やさない
- 削除・移動・改名・任意シェル実行は実装しない

---

## 3. 非目標（MVP でやらないこと）

作らないこと。「ついでに」も禁止。

- App Store 向けネイティブアプリ
- iPhone をロックした状態での常時待機
- 1回の手拍子での起動を既定にすること
- 独自の長期記憶データベース
- AI API の導入
- 任意シェルコマンドの実行
- スマートホーム操作
- 自動の削除・移動・改名
- 口パク・Live2D
- インターネットへの直接公開
- git commit / push の自動化

---

## 4. システム構成

| 層 | 動作場所 | 技術 | 役割 |
|---|---|---|---|
| 秘書UI | iPhone | Vite + React + TypeScript の PWA | 表情、字幕、状態表示、承認 |
| 手拍子検出 | iPhone | Web Audio API / AudioWorklet | 待機中の低負荷な起動検出 |
| 通信 | iPhone ↔ PC | HTTP + WebSocket（同一LAN） | 音声、状態、回答、承認 |
| 常駐サーバー | PC | Python 3.11+ / FastAPI / uvicorn | セッション管理、VAD、ルーティング |
| 音声認識 | PC | faster-whisper | 日本語音声をテキスト化 |
| ルーター | PC | ルールベース（正規表現＋キーワード） | 用件を5種類に分類 |
| 実行アダプター | PC | Codex CLI をサブプロセス起動 | Vault 検索、判断、ファイル編集 |
| 音声回答 | iPhone | Web Speech API (`SpeechSynthesis`) | 回答テキストの読み上げ |
| 記憶 | PC の Vault | Obsidian + Git | 正本、変更履歴、復旧 |

### データの流れ

```
[iPhone]                          [PC]
 AudioWorklet
   ├ 待機中: RMS/高周波 → ダブルクラップ判定
   └ 会話中: 16kHz mono Int16 PCM
        └─ WS binary ─────────────→ リングバッファ
                                     └ webrtcvad で発話終端判定
                                        └ faster-whisper で文字起こし
                                           └ ルーターで5分類
                                              └ Codex アダプター実行
                                                 ├ 書き込みあり → 承認要求
   承認/却下 ── POST ───────────────────────────→ 適用 or 破棄
   字幕表示 ←─ WS json ───────────────────────── 結果イベント
   Web Speech で読み上げ
```

---

## 5. リポジトリ構成

```text
jarvis-secretary/
├── apps/
│   └── iphone-ui/                  # PWA
│       ├── src/
│       │   ├── states/             # 有限状態機械
│       │   │   ├── machine.ts
│       │   │   └── types.ts
│       │   ├── audio/
│       │   │   ├── clap-worklet.ts     # AudioWorkletProcessor
│       │   │   ├── clap-detector.ts    # 判定・クールダウン
│       │   │   └── recorder.ts         # 16kHz PCM 化と送信
│       │   ├── components/
│       │   │   ├── Secretary.tsx       # 顔（右側）
│       │   │   ├── Caption.tsx         # 字幕
│       │   │   ├── Waveform.tsx        # 波形
│       │   │   ├── Approval.tsx        # 承認／却下
│       │   │   └── StatusBar.tsx
│       │   ├── api/
│       │   │   ├── socket.ts           # WS client・自動再接続
│       │   │   └── http.ts
│       │   ├── speech/tts.ts           # Web Speech API
│       │   └── settings/               # しきい値等の端末内設定
│       ├── public/
│       │   ├── manifest.webmanifest
│       │   └── assets/
│       │       ├── secretary-sleep.webp
│       │       └── secretary-awake.webp
│       └── vite.config.ts
├── server/
│   ├── app.py                      # FastAPI エントリ
│   ├── config.py                   # .env 読み込みと検証
│   ├── session.py                  # セッション・ジョブキュー
│   ├── audio/
│   │   ├── vad.py                  # webrtcvad による発話終端判定
│   │   └── stt.py                  # faster-whisper ラッパー
│   ├── router/
│   │   ├── classify.py             # 5分類
│   │   └── rules.py                # キーワード表
│   ├── agents/
│   │   ├── base.py                 # AgentRunner 抽象
│   │   ├── codex.py                # Codex CLI アダプター
│   │   └── claude.py               # 予約（未実装で可）
│   ├── vault/
│   │   ├── paths.py                # 実パス固定・パス検証
│   │   ├── git.py                  # status / diff（commit しない）
│   │   └── write.py                # 承認済み書き込み適用
│   └── security/
│       ├── pairing.py              # QR・ペアリングトークン
│       └── tokens.py               # 端末トークン検証
├── tests/
├── scripts/
│   ├── gen-cert.sh                 # LAN 用自己署名証明書
│   └── show-qr.py                  # ペアリングQR表示
├── .env.example
├── AGENTS.md
├── CLAUDE.md
└── README.md
```

---

## 6. 状態機械

画面側の独自判断で状態を飛ばさない。遷移はすべてこの表に従う。

### 状態

| 状態 | 秘書の表情・画面 | 音 |
|---|---|---|
| `BOOTING` | 目を閉じたまま、小さく「接続中」 | なし |
| `SLEEP` | 目を閉じる。輝度を落とす | 手拍子だけ監視 |
| `WAKING` | 目を開くアニメーション | 短い起動音 |
| `LISTENING` | 目を開き、左側に音声波形 | 「はい、どうしました？」 |
| `TRANSCRIBING` | 目を開いたまま、字幕を順次表示 | なし |
| `THINKING` | 瞳または眼鏡に弱い紫の光 | 任意の小さな待機音 |
| `APPROVAL` | 左側に変更要約と承認／却下 | 「確認してください」 |
| `SPEAKING` | 目を開き、回答字幕を表示 | 回答読み上げ |
| `ERROR` | 目を閉じかけ、原因と再試行を表示 | 短いエラー音 |
| `OFFLINE` | 目を閉じ「PCと未接続」 | 手拍子検出のみ継続 |

### 遷移

| From | 契機 | To |
|---|---|---|
| `BOOTING` | WS 接続成功 | `SLEEP` |
| `BOOTING` | 接続失敗 | `OFFLINE` |
| `SLEEP` | ダブルクラップ検出 | `WAKING` |
| `WAKING` | 開眼アニメ完了（250ms）＋起動発話 | `LISTENING` |
| `LISTENING` | サーバーが `audio.final` を返す | `TRANSCRIBING` |
| `LISTENING` | 8秒無音（発話なし） | `SLEEP` |
| `TRANSCRIBING` | `agent.started` | `THINKING` |
| `THINKING` | `approval.required` | `APPROVAL` |
| `THINKING` | `agent.completed` | `SPEAKING` |
| `APPROVAL` | 承認／却下 → `agent.completed` | `SPEAKING` |
| `APPROVAL` | 120秒無操作 → 自動却下 | `SPEAKING` |
| `SPEAKING` | 読み上げ完了後 8秒無音 | `SLEEP` |
| `SPEAKING` | 「ありがとう」「終わり」「寝て」 | `SLEEP` |
| 任意 | `system.error` | `ERROR` |
| `ERROR` | 5秒経過 or 再試行タップ | `SLEEP` |
| 任意 | WS 切断 | `OFFLINE` |
| `OFFLINE` | 再接続成功 | `SLEEP` |

### タイマー定数

| 名前 | 値 | 用途 |
|---|---|---|
| `WAKE_ANIM_MS` | 250 | 開眼クロスフェード |
| `LISTEN_IDLE_MS` | 8000 | 発話が来ないまま待機へ戻る |
| `POST_SPEAK_IDLE_MS` | 8000 | 読み上げ後に待機へ戻る |
| `APPROVAL_TIMEOUT_MS` | 120000 | 無操作で自動却下 |
| `ERROR_AUTO_BACK_MS` | 5000 | ERROR から SLEEP へ |
| `UTTERANCE_MAX_MS` | 30000 | 1発話の上限 |
| `VAD_SILENCE_MS` | 1200 | 発話終端判定の無音長 |

---

## 7. 手拍子検出

**既定はダブルクラップ。** 単発の大きな音では誤作動する。

### 実装

- 初回起動時だけ「マイクを有効にする」ボタンをタップして許可を取る（iOS はユーザー操作なしにマイクを開始できない）
- `AudioWorkletProcessor` で 128 サンプルごとに処理
- 各フレームで **RMS** と **高周波成分**（4kHz 以上のエネルギー比）を計測
- 周囲騒音の **移動平均**（時定数 3 秒）を持ち、固定音量ではなく相対しきい値で判定
- 拍手候補の条件：`rms > noise_floor * CLAP_RATIO` かつ `hf_ratio > CLAP_HF_MIN` かつ 立ち上がりが 20ms 以内
- 1回目から `CLAP_GAP_MIN`〜`CLAP_GAP_MAX` の間に2回目があれば起動
- 検出後 `CLAP_COOLDOWN_MS` は無反応

### パラメータ（設定画面で変更可能・端末内に保存）

| 名前 | 既定値 | 範囲 |
|---|---|---|
| `CLAP_RATIO` | 6.0 | 3.0–15.0 |
| `CLAP_HF_MIN` | 0.35 | 0.15–0.7 |
| `CLAP_GAP_MIN` | 150ms | 100–300 |
| `CLAP_GAP_MAX` | 1100ms | 500–1500 |
| `CLAP_COOLDOWN_MS` | 2000 | 固定 |
| `CLAP_MODE` | `double` | `double` / `single` |

### 調整

テレビ音・食器音・咳による誤起動は実機ログで調整する。デバッグ画面に直近30件の
検出候補（時刻・RMS・HF比・採否）を残し、しきい値決定の根拠にする。

---

## 8. 音声パイプライン

### iPhone 側

- `MediaRecorder` を使わない。**Safari の対応形式が不安定なため、AudioWorklet で生 PCM を取る**
- マイク入力を 16,000 Hz mono へダウンサンプル、Int16 LE に変換
- 20ms（320 サンプル = 640 バイト）ごとに WebSocket の **binary フレーム**で送信
- 同じストリームを手拍子検出と共用する（マイクを二重に開かない）

### PC 側

1. セッションごとにリングバッファへ蓄積
2. `webrtcvad`（モード 2、30ms フレーム）で発話区間を判定
3. 発話開始後、**1,200ms 無音**で発話終了とみなす
4. 1発話が **30秒**を超えたら強制的に終了させる
5. 確定した区間を faster-whisper へ渡す

### faster-whisper 設定

| 項目 | 値 |
|---|---|
| モデル | `large-v3`（起動が重い／精度不足なら `medium` へ落とす） |
| device | `cpu`（GPU があれば `cuda`） |
| compute_type | `int8`（cuda 時は `float16`） |
| language | `"ja"` 固定 |
| vad_filter | `True` |
| beam_size | 5 |

- モデルはサーバー起動時に一度だけロードし、常駐させる
- 途中経過は `audio.partial`、確定は `audio.final` で送る

---

## 9. ルーター（用件判定）

LLM を使わないルールベース。キーワードは `server/router/rules.py` に表として持つ。

| 分類 | 意味 | 判定の手がかり | 実行モード |
|---|---|---|---|
| `ASK` | Vault を読んで答える | 「何」「どこ」「教えて」「状態」「どうなってる」 | `read_only` |
| `CAPTURE` | デイリーへ記録する | 「記録して」「残して」「メモして」 | `propose_write` |
| `DECIDE` | 判断・優先順位 | 「どっち」「優先」「決めて」「軍配」 | `read_only` |
| `EXECUTE` | Codex で作業する | 「作って」「直して」「実装して」 | `propose_write` |
| `SYSTEM` | 端末操作 | 「音量」「再接続」「寝て」「終わり」「ありがとう」 | サーバー内処理 |

### 規則

- `SYSTEM` を最優先で判定する（エージェントを起動しない）
- どれにも当たらなければ **`ASK` を既定**とする
- 分類結果を `agent.started` イベントに含め、字幕へ小さく表示する（誤分類に気づけるようにする）
- 誤分類時のため「違う、記録して」のような言い直しで再分類できるようにする

---

## 10. エージェントアダプター

Codex と Claude Code を同じインターフェースで扱う。**MVP で実装するのは Codex のみ。**

### インターフェース

```python
class AgentRunner(Protocol):
    async def run(
        self,
        prompt: str,
        working_directory: str,
        mode: Literal["read_only", "propose_write", "approved_write"],
        timeout_seconds: int,
    ) -> AgentResult: ...

@dataclass
class AgentResult:
    summary: str            # 画面用の要約
    spoken_reply: str       # 読み上げ用。80文字程度まで
    changed_files: list[str]
    diff: str               # unified diff
    requires_approval: bool
    error: str | None
```

### 実行設定

| 項目 | 値 |
|---|---|
| 既定エージェント | Codex CLI |
| 作業ディレクトリ | Vault 実パス（`.env` の `VAULT_PATH`）に固定 |
| 読み取り | 許可 |
| 新規作成・追記 | Vault ルールに従う（承認必須） |
| 既存文の書き換え | 承認必須 |
| 削除・移動・改名 | **禁止**（アダプター層で拒否する） |
| タイムアウト | 通常 120 秒 |
| 同時実行 | **1ジョブ。**新しい依頼はキューへ積む |

### Codex CLI の呼び出し

- サブプロセスとして非対話実行する。**コマンド文字列は `.env` の `CODEX_CMD` にテンプレートとして持ち、ハードコードしない**
- 実装前に `codex --help` で実際の非対話サブコマンドとフラグを確認し、`.env.example` に確定形を書く
- stdout を構造化して受け取れない場合は、プロンプト側で「最後に `---SUMMARY---` 以降へ要約と変更ファイル一覧を出力せよ」と指示し、サーバーが末尾を解析する
- 標準入力・環境変数にユーザーの音声文字列をそのまま渡さない（引数展開を避け、一時ファイル経由で渡す）

### プロンプト組み立て

エージェントへ渡すプロンプトには必ず次を含める。

1. Vault の `AGENTS.md` / `CLAUDE.md` / `_kit/AI_RULES.md` を読むこと
2. 現在のモード（`read_only` なら「ファイルを変更するな」）
3. 削除・移動・改名の禁止
4. ユーザーの発話（文字起こし結果）
5. 出力形式（要約・読み上げ用短文・変更ファイル一覧）

---

## 11. Obsidian 書き込みの安全設計

**この節の違反はバグではなく事故として扱う。**

1. 実行前に `git status --porcelain` を保存し、ユーザーの既存変更を識別する
2. **JARVIS が変更したファイルだけを** diff 表示する
3. 既存の未コミット変更を上書きしない。対象ファイルが既に dirty なら承認画面に警告を出す
4. Vault の AI_RULES にある「デイリーの取り込み欄へ1行」「削除・移動・改名禁止」を優先する
5. 書き込み後は対象ファイル・要約・差分を iPhone へ返す
6. **git commit は自動化しない**（決定事項 #4）。安定後に「承認済み変更だけ」を追加するか再検討する
7. 任意のシェルコマンドを音声から直接実行しない
8. サーバー側で Vault 実パスを固定し、**音声からパスを指定できないようにする**
9. 書き込み先が `VAULT_PATH` 配下であることを `os.path.realpath` で検証する（シンボリックリンク・`..` を弾く）
10. 全操作を `logs/operations.jsonl` に追記する（時刻・分類・発話・変更ファイル・承認結果）

### 承認フロー

```
THINKING → requires_approval=true → APPROVAL 表示
  ├ 承認 → 変更を適用 → agent.completed（適用済み）
  ├ 却下 → 変更を破棄 → agent.completed（ファイル無変化）
  └ 120秒無操作 → 自動却下
```

**却下時にファイルが1バイトも変わらないこと**を Phase 4 の合格条件とする。
そのため、エージェントには一時作業領域で変更させ、承認後に Vault へ適用する。

---

## 12. 通信 API

### HTTP

| メソッド | パス | 役割 |
|---|---|---|
| GET | `/health` | PC・Whisper・Vault・エージェントの状態 |
| POST | `/session` | 会話セッション開始（`{session_id}` を返す） |
| POST | `/pair` | ペアリングトークンを端末トークンへ交換 |
| POST | `/jobs/{id}/approve` | 書き込み承認 |
| POST | `/jobs/{id}/reject` | 却下 |
| POST | `/sleep` | 待機へ戻す |

`/health` の応答例：

```json
{
  "ok": true,
  "whisper": {"loaded": true, "model": "large-v3"},
  "vault": {"path": "...", "git_dirty": 2},
  "agent": {"name": "codex", "available": true},
  "queue": {"running": 0, "pending": 0}
}
```

### WebSocket

`WS /ws/session/{id}`

- **binary フレーム** = 16kHz mono Int16 PCM の音声チャンク（iPhone → PC）
- **text フレーム** = JSON イベント（双方向）

### イベント

| 名前 | 向き | payload |
|---|---|---|
| `session.wake` | → PC | `{trigger: "clap"}` |
| `audio.partial` | → iPhone | `{text}` |
| `audio.final` | → iPhone | `{text}` |
| `agent.started` | → iPhone | `{job_id, intent}` |
| `agent.progress` | → iPhone | `{job_id, note}` |
| `approval.required` | → iPhone | `{job_id, summary, changed_files, diff, warnings}` |
| `agent.completed` | → iPhone | `{job_id, summary, spoken_reply, applied}` |
| `speech.started` | → PC | `{job_id}` |
| `session.sleep` | 双方向 | `{reason}` |
| `system.error` | → iPhone | `{code, message, retryable}` |

すべてのイベントに `type` と `ts`（サーバー単調時刻・ミリ秒）を含める。

---

## 13. 接続と認証

MVP は**同一 Wi-Fi 内限定**。

- PC は LAN アドレスで待ち受ける（`0.0.0.0` ではなく LAN IP を明示）
- iOS のマイク許可は **secure context 必須**。LAN IP では `http://` が secure context にならないため、`scripts/gen-cert.sh` で自己署名証明書を作り **HTTPS/WSS** で待ち受け、iPhone に証明書を信頼させる
- 初回に PC 画面へ QR コードを表示してペアリングする（`scripts/show-qr.py`）
- QR には**有効期限 5 分**のペアリングトークンを含める
- `/pair` で端末固有トークンへ交換し、iPhone の `localStorage` に保存する
- 以後の HTTP / WS は端末トークン必須
- CORS は登録済みの iPhone UI オリジンだけ許可
- **インターネットへポート開放しない。** UPnP・ポートフォワードを設定しない
- 外出先対応は MVP 後。必要なら Tailscale を検討し、公開 URL 方式にはしない

---

## 14. 設定（`.env.example`）

```dotenv
# --- ネットワーク ---
HOST=192.168.0.x            # PC の LAN IP
PORT=8787
TLS_CERT=./certs/lan.crt
TLS_KEY=./certs/lan.key
ALLOWED_ORIGINS=https://192.168.0.x:5173

# --- Vault ---
VAULT_PATH=/home/haru/ドキュメント/Start Vault

# --- 音声認識 ---
WHISPER_MODEL=large-v3
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8

# --- エージェント ---
AGENT=codex
# 非対話実行のコマンドテンプレート。{prompt_file} と {cwd} を置換する。
# 実装前に `codex --help` で確定形を確認してここへ書くこと。
CODEX_CMD=codex exec --cd {cwd} --file {prompt_file}
AGENT_TIMEOUT_SECONDS=120

# --- 動作 ---
APPROVAL_TIMEOUT_SECONDS=120
LOG_PATH=./logs/operations.jsonl
```

---

## 15. 秘書ビジュアル

白髪・白い眼鏡の秘書画像を基準にする。iPhone は横置き。

### レイアウト（横向き）

```
┌──────────────────────────┬───────────────┐
│ 左：字幕 / 波形 / 状態    │ 右：顔（固定） │
│    承認・却下ボタン       │               │
└──────────────────────────┴───────────────┘
```

- 右側：顔を固定する。位置・画角を動かさない
- 左側：字幕、波形、処理状態、承認ボタン
- `secretary-awake.webp`：全面プリズムの開眼素材（虹彩は青から黄への多色バースト）
- `secretary-sleep.webp`：同一画角の閉眼素材

  > **2026-08-30 更新（2回目）。** 素材を水彩の全身像へ差し替えた。
  > Caelestia のログイン画面の中央アバターを基準に描き起こし、髪を白銀にしたもの。
  > 1254×1254 の正方形・背景は黒で、顔は画像のほぼ中央。
  > 位置合わせはグレースケール RMSE の最小がオフセット (0, 0)＝2枚は揃っている。
  >
  > 正方形を横長のペインへ `cover` で置くので**切れるのは上下だけ**。
  > `object-position` の X は効かない。`50% 30%` で頭頂が切れずに収まる。
  > `iris-pulse` のマスクも同じ座標系なので、素材を替えたら両方直すこと
  > （片方だけ直すと THINKING の光が瞳から外れる）。
  >
  > 差し替え前のプリズム調2枚（16:9・目のクローズアップ）は
  > `apps/iphone-ui/.asset-backup/unused/secretary-prism-{sleep,awake}.webp` にある。
  > 素材差し替え時は毎回、位置合わせと画角の検証をやり直すこと。
- 切り替えは 150〜250ms のクロスフェード
- UI は色相を持たせず、白の不透明度違いだけで組む。警告色は例外
- 文字は絵の実効輝度が残らない左側へ置き、左フェザーで確実に分離する
- caelestia の `scheme.json` にある `primary` はビーコンと tick 先頭22%だけに使う
- `THINKING` は色相を追加せず、虹彩の彩度を 1.0〜1.45、1.6秒周期で脈打たせる
- **MVP では口パクしない。** 音声波形と字幕で会話感を出す
- 待機時は `brightness(.17) saturate(.2)` とし、数ピクセル単位のゆっくりした位置移動を入れる
  （`drift`。240秒で 6px×4px。焼き付くのは動く光り物ではなく、見出し・トンボ・
  カード枠のように位置が固定された要素なので、画面ごと動かす）
- OLED 保護のため、真っ白な静止画を長時間・最大輝度で表示しない

**画像編集は別工程。** 元の顔・比率を変えず、ユーザー承認後に作る。
素材が未着の間は、同一画角のプレースホルダー2枚で実装を進めてよい。

---

## 16. iPhone での常設条件

- PWA をホーム画面へ追加（`manifest.webmanifest` / `display: standalone` / `orientation: landscape`）
- 横向きスタンド＋給電
- アクセスガイドで専用画面に固定
- 自動ロックを無効または長時間に設定
- 低電力モードは使わない
- **画面ロック・ブラウザのバックグラウンド化ではマイク監視を保証しない**
- PWA 再起動時はマイク開始のため 1 回タップが必要になる前提で UI を作る（`OFFLINE`／`BOOTING` に「マイクを有効にする」ボタンを置く）
- PC 切断時も秘書画面は表示し、`OFFLINE` から自動再接続する（指数バックオフ、上限 30 秒）

---

## 17. エラー処理

| コード | 状況 | 挙動 |
|---|---|---|
| `WS_DISCONNECTED` | PC 切断 | `OFFLINE` へ。自動再接続を続ける |
| `MIC_DENIED` | マイク許可なし | 再許可ボタンを表示 |
| `STT_FAILED` | 文字起こし失敗 | 「聞き取れませんでした」と返して `LISTENING` へ戻す（1回だけ） |
| `AGENT_TIMEOUT` | 120 秒超過 | ジョブを中止し、変更を破棄して報告 |
| `AGENT_FAILED` | 非ゼロ終了 | stderr 末尾を要約して報告。変更は破棄 |
| `VAULT_DIRTY` | 対象ファイルが未コミット変更中 | 承認画面に警告を出す。自動では進めない |
| `PATH_REJECTED` | Vault 外への書き込み | 即座に中止。ログへ記録 |

**どのエラーでも Vault が中途半端な状態で残らないこと。**

---

## 18. 実装段階

Phase は順番に進める。**前の Phase の合格条件を満たすまで次へ進まない。**

### Phase 0：接続だけ

- [ ] PC で FastAPI サーバーを起動する
- [ ] 自己署名証明書を作り HTTPS/WSS で待ち受ける
- [ ] iPhone から `/health` を確認する
- [ ] PWA をホーム画面へ追加する
- [ ] WebSocket 自動再接続を実装する

**合格条件：** PC 再起動・Wi-Fi 切断後に、iPhone が操作なしで再接続状態へ戻る。

### Phase 1：目を閉じる／開く

- [ ] 目を開いた素材と閉じた素材を配置する
- [ ] 状態機械（§6）を実装する
- [ ] ダブルクラップ検出（§7）を実装する
- [ ] 検出ログのデバッグ画面を作る
- [ ] アクセスガイドで一晩表示テストする

**合格条件：** 静かな部屋で 20 回中 18 回以上起動し、1 時間あたりの誤起動が 1 回以下。

### Phase 2：ローカル音声往復

- [ ] iPhone 録音（16kHz PCM）を PC へ送信する
- [ ] VAD と faster-whisper で文字起こしする
- [ ] iPhone で字幕表示する
- [ ] iPhone 標準音声（Web Speech API）で回答を読み上げる

**合格条件：** 日本語 10 文中 9 文以上で意図が分かる文字起こしになり、30 秒発話で停止しない。

### Phase 3：Vault 読み取り

- [ ] Vault 実パスを作業ディレクトリに固定する
- [ ] `AGENTS.md` / `CLAUDE.md` / `_kit/AI_RULES.md` への到達経路を確認する
- [ ] Codex アダプターを実装する
- [ ] `claude.py` はインターフェースだけ用意する（未実装で可）
- [ ] `ASK` と `DECIDE` を `read_only` で実装する

**合格条件：** 「今日何をする？」「この企画の状態は？」に、Vault を根拠として答えられる。

### Phase 4：承認つき書き込み

- [ ] `CAPTURE` を実装する
- [ ] diff と変更対象を iPhone へ表示する
- [ ] 承認／却下を実装する
- [ ] 競合・未コミット変更の保護を実装する
- [ ] 操作ログを実装する

**合格条件：** 却下時はファイルが変化せず、承認時だけ指定先へ追記される。既存変更を壊さない。

### Phase 5：常設品質

- [ ] OLED 保護（輝度低下・微小移動）
- [ ] PC 起動時のサーバー自動起動（systemd user unit）
- [ ] 障害復帰
- [ ] 外出先接続の要否を判断する
- [ ] 口パク・高品質音声は必要性を確認してから追加する

---

## 19. 受け入れ条件

全項目を満たしたら完成とする。

- [ ] iPhone 13 Pro を横置きし、秘書画面を 8 時間連続表示できる
- [ ] ダブルクラップで目が開き、音声入力へ移る
- [ ] 発話終了を自動判定し、PC で日本語文字起こしできる
- [ ] Codex が Vault を読んで回答できる
- [ ] Obsidian 書き込み前に変更内容を確認できる
- [ ] 却下すればファイルが変わらない
- [ ] PC・Wi-Fi 切断後に自動復帰できる
- [ ] API 料金なしで基本会話が成立する
- [ ] Vault 以外の任意ファイルやシェルへ到達できない

---

## 20. 技術制約の根拠

- Apple「アクセスガイド」：https://support.apple.com/ja-jp/111795
- Apple「自動ロック」：https://support.apple.com/ja-jp/guide/iphone/iph7117338a8/ios
- Apple「アプリ停止時の音声セッション中断」：https://developer.apple.com/documentation/avfaudio/avaudiosession/interruptionreason/appwassuspended
