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
| 設置 | 縦向き・給電・スタンド常設 |
| ネットワーク | 同一Wi-Fi内のみ。ポート開放しない |
| Vault実パス | `/home/haru/ドキュメント/Start Vault`（`.env` で指定） |
| リポジトリ | `~/dev/jarvis-secretary/`（Vault の外） |

**Vault のファイルをこのリポジトリへコピーしない。** サーバーは実パスを参照する。

---

## 1. 完成時の体験

1. iPhone は縦向き・給電でスタンドに常設
2. 待機中のピクセルコアは小さく呼吸し、画面は暗い
3. 手を2回叩くとコアが衝撃波を返し、「なにする？」を Vault へ即座に問う
4. 続けて聞きたければ「続けて聞く」を押し、自然な日本語で指示する
5. iPhone が音声を PC へ送り、PC が文字起こし・用件判定・実行を担当
6. Vault への書き込みは iPhone に承認／却下を表示
7. 結果は1段目の文字回答カードへ表示する（読み上げは廃止、2026-09-02）。
   無音が続くとカードが閉じ、コアが縮んで待機へ戻る

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
- JARVIS の発話は起動声も回答もすべて親しいタメ口にする
- Obsidian を長期記憶の正本とし、JARVIS 独自の恒久メモリを増やさない
- 削除・移動・改名・任意シェル実行は実装しない

---

## 3. 非目標（MVP でやらないこと）

作らないこと。「ついでに」も禁止。

- App Store 向けネイティブアプリ
- iPhone をロックした状態での常時待機
- ダブルクラップを起動条件にすること
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
   ├ 待機中: RMS/高周波 → 手拍子2回の判定
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
| `BOOTING` | 小さく「接続中」と自己紹介カード | なし |
| `SLEEP` | コアが小さく呼吸し、輝度を落とす | 手拍子2回だけ監視 |
| `WAKING` | コアから衝撃波、1段目が文字回答カードへ切り替わる | 短い起動音 |
| `LISTENING` | コアが声量と高周波に追従 | なし |
| `TRANSCRIBING` | コアが収束し、聞き取った文をカードへ追加表示 | なし |
| `THINKING` | コア内部が回路状に変化 | 任意の小さな待機音 |
| `APPROVAL` | 左側に変更要約と承認／却下 | なし |
| `SPEAKING` | コアが中心から外へ波打ち、回答をカードへ追加表示（読み上げは廃止・2026-09-02） | なし |
| `ERROR` | コアがエラー色へ変化し、原因と再試行を表示 | 短いエラー音 |
| `OFFLINE` | コアが点へ縮退し「PCと未接続」 | 手拍子検出のみ継続 |

### 遷移

| From | 契機 | To |
|---|---|---|
| `BOOTING` | WS 接続成功 | `SLEEP` |
| `BOOTING` | 接続失敗 | `OFFLINE` |
| `SLEEP` | 手拍子2回を検出 | `WAKING` |
| `WAKING` | 衝撃波アニメ完了（250ms） | `LISTENING` |
| `WAKING` | 拍手の固定質問への応答が届く（`agent.started`） | `THINKING` |
| `LISTENING` | サーバーが `audio.final` を返す | `TRANSCRIBING` |
| `LISTENING` | 8秒無音（発話なし） | `SLEEP` |
| `TRANSCRIBING` | `agent.started` | `THINKING` |
| `THINKING` | `approval.required` | `APPROVAL` |
| `THINKING` | `agent.completed` | `SPEAKING` |
| `THINKING` | 「やめて」（`agent.cancelled`） | `SPEAKING`（中断した旨をカードへ表示） |
| `APPROVAL` | 承認／却下 → `agent.completed` | `SPEAKING` |
| `APPROVAL` | 120秒無操作 → 自動却下 | `SPEAKING` |
| `SPEAKING` | カード表示から20秒（「戻る」「続けて聞く」が無ければ） | `SLEEP` |
| `SPEAKING` | 「戻る」「ありがとう」「終わり」「寝て」 | `SLEEP` |
| `SPEAKING` | 「続けて聞く」 | `LISTENING`（WAKING を経由しない） |
| 任意 | `system.error` | `ERROR` |
| `ERROR` | 5秒経過 or 再試行タップ | `SLEEP` |
| 任意 | WS 切断 | `OFFLINE` |
| `OFFLINE` | 再接続成功 | `SLEEP` |

### タイマー定数

| 名前 | 値 | 用途 |
|---|---|---|
| `WAKE_ANIM_MS` | 250 | 手拍子2回の衝撃波 |
| `LISTEN_IDLE_MS` | 20000 | 発話が来ないまま待機へ戻る（実装値。実機で8000は短すぎた） |
| `POST_ANSWER_IDLE_MS` | 20000 | 文字回答カードを見せたまま待機へ戻る（読み上げ廃止・2026-09-02） |
| `APPROVAL_TIMEOUT_MS` | 120000 | 無操作で自動却下 |
| `ERROR_AUTO_BACK_MS` | 5000 | ERROR から SLEEP へ |
| `UTTERANCE_MAX_MS` | 30000 | 1発話の上限 |
| `VAD_SILENCE_MS` | 1200 | 発話終端判定の無音長 |

---

## 7. 手拍子検出

**既定は手拍子2回。** 1回の指パッチンはタイピング音と実測指標が重なり誤起動したため、2026-09-02に取り下げた。

### 実装

- 初回起動時だけ「マイクを有効にする」ボタンをタップして許可を取る（iOS はユーザー操作なしにマイクを開始できない）
- `AudioWorkletProcessor` で 128 サンプルごとに処理
- 各フレームで **RMS** と **高周波成分**（4kHz 以上のエネルギー比）を計測
- 周囲騒音の **移動平均**（時定数 3 秒）を持ち、固定音量ではなく相対しきい値で判定
- 拍手候補の条件：`rms > noise_floor * CLAP_RATIO` かつ `hf_ratio > CLAP_HF_MIN` かつ 立ち上がりが 20ms 以内
- `CLAP_MODE=double` で、1回目から `CLAP_GAP_MIN`〜`CLAP_GAP_MAX` の間に2回目があれば起動する
- `single` はデバッグ用に残すが、常設端末の既定には使わない
- 検出後 `CLAP_COOLDOWN_MS` は無反応

### パラメータ（設定画面で変更可能・端末内に保存）

| 名前 | 既定値 | 範囲 |
|---|---|---|
| `CLAP_RATIO` | 6.0 | 3.0–15.0 |
| `CLAP_HF_MIN` | 0.20 | 0.15–0.7 |
| `CLAP_GAP_MIN` | 250ms | 100–300 |
| `CLAP_GAP_MAX` | 800ms | 500–1500 |
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

## 15. JARVIS ビジュアル

iPhone は縦置きを正とする。秘書画像ではなく、CachyOS の `sysmon` の `dots` パネル
（実体は **lavat**。§15.2）をそのまま移植したものをJARVISの顔にする。

- 中央に 69×34 のメタボールパネルを置く。丸い一般的なAIオーブにはしない
- **まず実物どおり「常に動いている」だけを再現する。状態や音への反応は後から決める**
- 上部は小さな JARVIS / PC LINK、下部は状態文と最低限の操作だけにする
- Caelestia のターミナル表示を組み替えたJARVIS自己紹介は接続・起動時だけ表示する
- Nerd Fontアイコンは小さな補助記号に限定し、iPhone Safariで字形を確認できないものは使わない
- 白髪秘書素材はUIへ表示しない。再利用する場合は目の位置と瞬きの整合を別途確認する
- `scheme.json` の `mode` と Material tokens を WebSocket で配信し、ライト／ダークへ即時追従する
- 使用する配色は `background` / `surfaceContainer` / `surfaceContainerHigh` / `onSurface` / `onSurfaceVariant` / `outlineVariant` / `primary` / `onPrimary` / `error`
- `scheme.json` が読めない場合はライトテーマの安全な既定値へ落とす
- 待機時は画面全体を240秒で数ピクセル移動させる
- OLED 保護のため、真っ白な静止画を長時間・最大輝度で表示しない

### 15.1 Claude Codeへの引き継ぎ（2026-08-30）

> **2026-08-31 訂正。この節の移植先は誤り。正しくは §15.2。**
> `sysmon-watch.sh` の `dots` 分岐は `command -v lavat` を先に見るため、
> lavat が入っているこの環境では **lavat が描いており `sysmon-dots.py` は動いていない**。
> 設定ファイルだけ読んで `ps` で動いているプロセスを確認しなかったのが原因。
> 以下は音声反応を前提にしているが、実物は音に反応しない。画面構成と配色の項だけ有効。

現在の `aecb6e9` の画面は完成形ではない。中央に丸いドットを置いただけで、参照元のLinux端末表示を再現できていない。次の実装では、見た目を推測で作り直さず、実際に動いている下記ファイルを正本として移植する。

#### 参照元

- ドットの描画本体：`~/.config/caelestia/sysmon-dots.py`
- 配色追従と再起動：`~/.config/caelestia/sysmon-watch.sh`
- 実際の5パネル配置：`~/.config/caelestia/hypr-user.lua` の `sysmon_layout`
- 起動コマンド：`~/.config/caelestia/cli.json` の `toggles.sysmon`

特に再現するのは、特殊ワークスペース `sysmon` で**時計の上に表示されている `dots` パネル**。この実物を先にスクリーンショットまたは画面で確認してから実装する。

#### ドットの動き

`sysmon-dots.py` のアルゴリズムをブラウザ側へ移植する。

1. Web Audio API のFFTから20本の周波数帯を作る（元コードの `BARS = 20` に合わせる）
2. 各セルを中心からの極座標へ変換する
3. `abs(dx)` を使って左右対称にする
4. 角度を20本のバー番号へ割り当てる
5. 半径は元コードと同じ `0.30 + level * 0.72` を基準にする
6. 上下も鏡像にし、音に合わせて輪郭が不規則に変わる「ブロックの塊」にする

単一の `rms` で円を拡大縮小するだけの実装は禁止。一般的なAIオーブ、均一な円、中央の `J` バッジにも戻さない。

#### 画面構成

- 上部に端末のFIGlet風ASCIIアートで **JARVIS** と表示する
- ユーザーが示したCaelestiaロゴと同じ斜体端末風の字形・密度を使う。ただし文字列は `JARVIS`
- 中央の主役は上記の動くドットパネル
- 表示文、ボタン、状態名は**すべて英語**
- 日本語の大見出し、説明文、カード型のシステム情報一覧は置かない
- 必要な情報は `STANDBY` / `LISTENING` / `THINKING` / `OFFLINE` のような短い状態名だけ
- Linux端末らしいモノスペース、余白、罫線で構成する。一般的なモバイルアプリ風の角丸カードUIにはしない
- Nerd Fontアイコンを使う場合は、iPhone Safariで実際に字形が出ることを確認する。確認できない字形はASCII記号へ置き換える

#### 配色

Caelestiaでテーマまたは壁紙を変更したら、iPhone側も再読み込みなしで追従する。

- サーバーは `~/.local/state/caelestia/scheme.json` の `mode` とMaterial tokensをWebSocketで配信する
- ブラウザは `scheme.changed` を受けてCSS変数を即時更新する
- ドット、ASCIIロゴ、罫線も `primary` に追従する
- 背景と文字色はlight/darkを含むscheme全体へ追従する
- `scheme.json` が読めない場合だけライトテーマの安全な既定値へ戻す

#### 合格条件

- 実際の `sysmon` の `dots` パネルと並べて見て、同じ種類の動きだと分かる
- マイク入力へ反応する輪郭が20帯域由来で、単純な円の拡大縮小ではない
- 390×844pxでASCIIの `JARVIS`、動くドット、英語の状態、操作が1画面に収まる
- 画面内に日本語がない
- Caelestiaのテーマを切り替えると、背景・文字・ドット・罫線がその場で変わる
- ライトテーマとダークテーマの両方をスクリーンショットで確認する
- iPhone Safari実機で動きと字形を確認する

### 15.2 dots パネルの正体は lavat（2026-08-31）

`sysmon` の `dots` パネルを描いているのは **lavat**（`lavat -g -c 615a7a -k 615a7a`）。
`sysmon-watch.sh` は lavat があればそれを使い、無いときだけ `sysmon-dots.py` へ落ちる。
実装は `apps/iphone-ui/src/components/LavaCore.tsx`。

**lavat はメタボールのラバライトで、音には一切反応せず常に動き続ける。**
まずこの「常に動いている」状態をそのまま再現する。反応をどう足すかはその後に決める。

移植した値はすべて lavat.c v3.0.0 の既定値。

| 項目 | 値 | 出どころ |
|---|---|---|
| ボール数 | 10 | `nballs = 10` |
| 半径係数 | `radiusIn = 110` | 既定値 |
| 半径 | `(110² + maxX*maxY) / 15000` | `init_params()` |
| 閾値 | `sumConst = 0.0225` | `init_params()` |
| 濃度 | `Σ radius² / dist²` がこれを超えたセルを塗る | `render` |
| 速度 | `((1/(maxX+maxY))*1e6 + 1e4) * (11-5)` µs | `init_params()` |
| 移動 | 等速で壁反射。`\|vx\| < 0.15` なら 0.15 へ戻す | `main()` |
| グリッド | **69 × 34** | 下記 |

縦解像度が2倍なのは、lavat が `▀` `▄` の半ブロックで1行を上下2ピクセルとして描くため
（`maxY = tb_height() * 2`）。実機のパネル 620×340px を実測すると1ピクセルが 9×10px なので、
グリッドは 69×34 になる。**ここを詰めないと「ピクセルが大きすぎる」見た目になる**
（33×33 で作って作り直した）。`-c` と `-k` に同じ色を渡しているのでグラデーションにならず単色。

#### 合格条件（実測で確認する。目視だけで済ませない）

- セル寸法が実機スクショと一致する（実測 9×10px → グリッド 69×34）
- 塗り面積比が実物と同じ範囲に入る（実物 0.746 / 移植 0.688〜0.885・中央値 0.783）
- 音を鳴らさなくても動き続ける（連続フレームがすべて相異なること）
- 実機スクショと並べて、同じ種類の形・同じ階段の粗さに見える

- PWA をホーム画面へ追加（`manifest.webmanifest` / `display: standalone` / `orientation: portrait`）
- 縦向きスタンド＋給電
- アクセスガイドで専用画面に固定
- 自動ロックを無効または長時間に設定
- 低電力モードは使わない
- **画面ロック・ブラウザのバックグラウンド化ではマイク監視を保証しない**
- PWA 再起動時はマイク開始のため 1 回タップが必要になる前提で UI を作る（`OFFLINE`／`BOOTING` に「マイクを有効にする」ボタンを置く）
- PC 切断時もJARVIS画面は表示し、`OFFLINE` から自動再接続する（指数バックオフ、上限 30 秒）

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

### Phase 1：手拍子2回で起きる

- [ ] 状態に反応するピクセルコアを配置する
- [ ] 状態機械（§6）を実装する
- [ ] 手拍子2回の検出（§7）を実装する
- [ ] 検出ログのデバッグ画面を作る
- [ ] アクセスガイドで一晩表示テストする

**合格条件：** 静かな部屋で 20 回中 18 回以上起動し、1 時間あたりの誤起動が 1 回以下。

### Phase 2：ローカル音声往復

- [x] iPhone 録音（16kHz PCM）を PC へ送信する（2026-08-31）
- [x] VAD と faster-whisper で文字起こしする（2026-08-31）
- [x] iPhone で字幕表示する（2026-08-31）
- [x] 回答は上段の固定高ターミナルカードへ文字表示する（読み上げは使わない）
      **2026-09-02 実装。** 下の「次の実装：文字回答カード」参照

**合格条件：** 日本語 10 文中 9 文以上で意図が分かる文字起こしになり、30 秒発話で停止しない。

### Phase 3：Vault 読み取り

- [ ] Vault 実パスを作業ディレクトリに固定する
- [ ] `AGENTS.md` / `CLAUDE.md` / `_kit/AI_RULES.md` への到達経路を確認する
- [ ] Codex アダプターを実装する
- [ ] `claude.py` はインターフェースだけ用意する（未実装で可）
- [ ] `ASK` と `DECIDE` を `read_only` で実装する

**合格条件：** 「今日何をする？」「この企画の状態は？」に、Vault を根拠として答えられる。

### Phase 4：承認つき書き込み

- [x] `CAPTURE` を実装する
- [x] diff と変更対象を iPhone へ表示する
- [x] 承認／却下を実装する
- [x] 競合・未コミット変更の保護を実装する
- [x] 操作ログを実装する

**合格条件：** 却下時はファイルが変化せず、承認時だけ指定先へ追記される。既存変更を壊さない。

**2026-09-01 実機で合格。** 3経路すべて確認した。

| 経路 | 結果 |
|---|---|
| 却下 | Vault 141ファイルのハッシュ無変化。提案コピーも破棄 |
| 承認 | 141ファイル中1つだけ変化。`01_daily` の取り込み欄に1行追記のみ |
| 120秒無操作 | 自動却下。`operations.jsonl` に `reason: "timeout"` |

§11-3 の警告も発火した（対象が dirty だったため「承認すると上書きされます」を表示）。

実機で分かった前提の誤り2件（どちらも修正済み）:

- 重い処理を WebSocket の受信ループの中で待っていた。エージェントは20〜40秒かかるので、
  その間サーバーが受信せず、送られ続ける音声フレームが溜まって接続が切れ、端末が
  再接続して STANDBY へ戻っていた。書き起こしとエージェントは別タスクへ出す
- 音声を常時送信していた。§4 のとおり送るのは「会話中」だけで、待機中は端末側の
  指パッチ判定だけを回す

### Phase 5：常設品質

- [x] OLED 保護（輝度低下・微小移動）2026-09-02 実装・実機確認済み
- [ ] PC 起動時のサーバー自動起動（systemd user unit）
- [ ] 障害復帰
- [ ] 外出先接続の要否を判断する
- ~~口パク~~ **中止**（2026-09-02）。アバターを使わない方針に決めたため。
  音声読み上げも iPhone Web Speech の実機動作が不安定なため廃止する。

### 文字回答カード（2026-09-02 合意・実装）

`apps/iphone-ui/src/components/AnswerCard.tsx`。質問が始まると1段目（旧 fastfetch
カード）をここへ差し替える。実装は `server/agent.py` の状態機械拡張（`SPEAKING`
の `IDLE`/`CONTINUE`、`THINKING` の `IDLE`）と組みで動く。

- [x] 回答の音声読み上げは廃止する
- [x] 質問後はUI上段を、Starship風の丸いバッジを持つターミナルカードへ切り替える
- [x] 質問は `› 質問文`、処理中は点滅カーソル、回答は段落または行単位で追加表示する
- [x] カードの高さは固定する（`clamp(210px, 30dvh, 300px)`）。出力中は最下部へ自動追従し、
      古い文字は上側へ見切れる
- [x] 利用者が途中で上へスクロールしたら自動追従を止める（24px 以上離れたら判定）
- [x] 全文表示後はカード内を自由にスクロールできる
- [x] 完了後に「戻る」「続けて聞く」の2ボタンを表示する。拍手を戻る操作には兼用しない
- [x] 聞き取り開始から回答表示完了までは、カードの縁・背景・外側のぼかしを
      壁紙テーマ色で約2.5秒周期に明暗させ、呼吸するように見せる。回転する縁は使わない
- [x] 完了時は呼吸を止め、弱い常時発光へ落ち着かせる

**実機での見た目確認はまだ。** ヘッドレスビルド・tsc・vitest（machine の新規遷移
2件を含む）は通過している。

---

## 18.1 ブラウザ操作（2026-09-05）

「ブラウザ操作の許可」の最初の1本。**note の下書きまで。公開しない。**

- ブラウザは `server/browser.py` の常駐1枚。**専用プロファイル**
  （`~/.local/state/jarvis-secretary/browser-profile`）で、普段の Chrome を触らない。
  **ヘッドレスにしない**（本人の指定：PC の画面で動いているのが見えることが要件。
  常駐ターミナルと同じ扱い）
- note 固有の手順は `server/note_draft.py`。掴みどころは候補を順に試す
  （note の DOM は変わる。1つに賭けると改装のたびに黙って壊れる）
- **押していいのは「下書き保存」だけ。** 公開ボタンには触れない（テストで固定）
- 本文の生成（Codex）とは分けてある。失敗したときに原因が本文側かブラウザ側かを
  切り分けられるようにするため

### ログイン（最初の1回だけ、本人が手で行う）

```
.venv/bin/python -m server.note_draft login --by-hand
```

資格情報はこのプロジェクトが持たない（Vault にも `.env` にも置かない）。
2つの実測が効いている。

1. **Google のログインは自動操作されたブラウザを弾く**
   （「このブラウザまたはアプリは安全でない可能性があります」）。
   なので Playwright を噛ませず、素の Chrome として同じプロファイルを開く
2. **その素の Chrome にも `--use-mock-keychain` を渡す。**
   何も指定しないと Chrome は OS のキーリングでクッキーを暗号化するが、
   Playwright が起動する Chrome は固定鍵で動くため復号できない。
   クッキーは名前だけ残り、画面は未ログインのまま、という食い違いになる

待ち受け中に**こちらからページを動かさない**こと。定期的にトップへ遷移して
ログイン済みかを確かめる作りにしたら、本人が入力している最中に画面が飛んだ。

### ウィンドウの置き場所

**Chrome の起動引数では決まらない。** Wayland では `--window-position` も
`--window-size` も無視され、コンポジタが置き場所を決める。既定ではタイルの半分に
収まり、note のエディタが右で切れる（2026-09-05、実機のスクショで確認）。

開いたあとに Hyprland へ名指しで指示する（`server/browser.py` の `fit_window`）。
このプロファイルで動いている PID のウィンドウだけを動かし、普段の Chrome には触らない。

- Hyprland 0.56 は **Lua のディスパッチャ**。`hyprctl dispatch setfloating address:...`
  は構文エラーになる。`hl.dsp.window.float({window="address:0x..."})` の形で送る
- **float は切り替え。** すでに浮いている窓に送ると戻ってしまう
- 大きさと位置は `hl.dsp.window.resize` / `move` に `exact=true` を付けて指定する
- サンドボックスは切らない（`chromium_sandbox=True`）。切ると
  「サポートされていないコマンドラインフラグ --no-sandbox」の黄色い帯が画面に映る

### 窓の大きさに中身を追従させる

**真因は Playwright の既定ビューポート。** `viewport=None` では外れず、窓を小さくしても
中身は 1280px 幅のまま描かれ、はみ出した右側がコンポジタに切られていた
（実測：窓 752px に対して `window.innerWidth` が 1280 のまま）。
`no_viewport=True` で窓の実寸に従う。これで4分割でも note が自分でレスポンシブに畳み、
「下書き保存」まで見える。**縮尺（CSS zoom）で埋める必要はない**
（`page_zoom` は、note のエディタの最低幅を割るほど狭いときの保険として残してある）。

置き場所は `--layout` で選ぶ。`full` / `left` `right`（縦2分割）/ `top` `bottom`（横2分割）/
`top-left` 等（4分割）。既定は `full`、環境変数 `BROWSER_LAYOUT` でも変えられる。

狭い窓では、本文を打った直後の**書式ツールバーが「下書き保存」に重なってクリックを
横取りする**。押す前に Escape で選択を外す（4分割で実際に落ちた）。

### 打鍵の速さ

1文字 55ms（`NOTE_TYPE_DELAY_MS`）。段落のあいだに 400ms 置く。
規約に自動操作を禁じる条項は無いが、note は「機械的に大量の記事を投稿する行為」への
対応強化を明文化している（2026-02-27）。機械的な速さを出さず、1件ずつにとどめて
そこから離れる。調査は Vault の
`04_resources/2026-09-05 noteのAI利用と自動操作の規約確認`。

### 実測（2026-09-05）

固定文で1本通し、`https://editor.note.com/notes/<key>/edit/` まで到達。
記事一覧に「下書き」ステータスで題・本文とも残ることを確認した。

---

## 19. 受け入れ条件

全項目を満たしたら完成とする。

- [ ] iPhone 13 Pro を縦置きし、JARVIS画面を 8 時間連続表示できる
- [ ] 手拍子2回でコアが反応し、音声入力へ移る
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
