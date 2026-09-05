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

実物（2026-09-05 時点）。**構成を変えたらこの表も直す。**
2026-09-05 まで、ここは 2026-08-26 の計画のまま実物と一致していなかった
（`server/audio/` `server/security/` など、作られなかったものが載っていた）。

```text
jarvis-secretary/
├── apps/
│   └── iphone-ui/                      # PWA（Vite + React）
│       └── src/
│           ├── App.tsx                 # 画面の組み立てと待機/復帰のタイマー
│           ├── theme.ts                # 届いた配色・壁紙をDOMへ反映（§15）
│           ├── copy.ts                 # 状態ごとの表示文
│           ├── model.ts                # 画面が持つ値の型
│           ├── clap-settings.ts        # しきい値の端末内保存
│           ├── hooks/
│           │   ├── useSecretarySocket.ts   # WS接続とイベントの振り分け（§12）
│           │   ├── useMicrophone.ts        # マイク・手拍子検出・画面ロック
│           │   ├── useQaCard.ts            # 文字回答カードの状態
│           │   └── useViewportReset.ts     # iOS standalone のズレ対策
│           ├── clap-settings.ts        # しきい値の端末内保存
│           ├── states/                 # 有限状態機械（§6）
│           ├── audio/                  # AudioWorklet・手拍子判定・録音
│           ├── api/socket.ts           # WSクライアント・自動再接続（socket.test.ts で接続交代を検証）
│           └── components/             # Fetch / LavaCore / Live / AnswerCard 他
├── server/
│   ├── app.py                          # FastAPI の組み立て。配線だけ置く
│   ├── session.py                      # 端末1台との会話（受信ループ・応答）
│   ├── hub.py                          # 接続中の端末と、配り続けるイベント
│   ├── approval.py                     # 承認待ちの提案・監査ログ・自動却下（§11）
│   ├── agent.py                        # Codex CLI アダプター（§10）
│   ├── router.py                       # 用件の5分類（§9）
│   ├── transcribe.py                   # faster-whisper ラッパー（§8）
│   ├── audio.py                        # VAD による発話終端判定（§8）
│   ├── vault.py                        # Vault の読み取りと直答（§9）
│   ├── write.py                        # 承認済み提案の適用（§11）
│   ├── gitstate.py                     # Vault の git 状態（読むだけ）
│   ├── facts.py                        # PC の実測値（テレメトリ・プロセス）
│   ├── scheme.py                       # caelestia の配色（§15）
│   ├── wallpapers.py                   # 壁紙の一覧・切り替え・変換
│   ├── terminal.py                     # 作業を見せるターミナル
│   ├── browser.py                      # 常駐ブラウザの操作（§18.1）
│   ├── note_draft.py                   # noteのエディタ操作（§18.1）
│   ├── note_writer.py                  # 声→下書きの取り回し。常駐ブラウザ1枚（§18.2）
│   ├── thumbnail.py                    # 見出し画像を題から作る（§18.2）
│   ├── clock.py                        # イベントに載せる時刻
│   └── config.py                       # .env 読み込みと検証
├── tests/                              # pytest（server 側。test_lifecycle_regressions.py は切断・承認・競合の回帰検証）
├── docs/
│   ├── phase-0-1-acceptance.md
│   └── archive/                        # 実装の根拠にしない過去の検討
├── examples/                           # 実際に通した入出力の控え
├── scripts/
│   ├── gen-cert.sh                     # LAN 用自己署名証明書
│   └── serve-local.sh                  # 外出先で 127.0.0.1 に建てる
├── .env.example
├── AGENTS.md
├── DESIGN.md
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
| `SLEEP` | 指パッチン1回を検出、または画面の操作部以外をタップ | `WAKING` |
| `WAKING` | 衝撃波アニメ完了（250ms） | `LISTENING` |
| `WAKING` | 拍手の固定質問への応答が届く（`agent.started`） | `THINKING` |
| `LISTENING` | サーバーが `audio.final` を返す | `TRANSCRIBING` |
| `LISTENING` | 10秒無音（発話なし） | `SLEEP` |
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
| `LISTEN_IDLE_MS` | 10000 | 発話が来ないまま待機へ戻る。9/2 に 8000→20000 としたが、実際はタイマーが張られていなかった（`continueQa` で `speaking` を降ろしていなかった）。2026-09-05 に修正したうえで 10000 |
| `POST_ANSWER_IDLE_MS` | 20000 | 文字回答カードを見せたまま待機へ戻る（読み上げ廃止・2026-09-02） |
| `APPROVAL_TIMEOUT_MS` | 120000 | 無操作で自動却下 |
| `ERROR_AUTO_BACK_MS` | 5000 | ERROR から SLEEP へ |
| `UTTERANCE_MAX_MS` | 30000 | 1発話の上限 |
| `VAD_SILENCE_MS` | 1200 | 発話終端判定の無音長 |

---

## 7. 手拍子検出

**既定は指パッチン1回**（`single`、2026-09-05に本人の指定で戻した）。

経緯：2026-08-26 は指パッチン1回 → 2026-09-02 にタイピング音の誤起動で手拍子2回へ →
2026-09-05 に指パッチン1回へ戻した。**誤起動が出たら mode を変えず、`CLAP_RATIO` と
`CLAP_HF_MIN` を上げて対処する**（起動方式は本人の指定が優先）。
真値は `apps/iphone-ui/src/audio/types.ts` の `DEFAULT_CLAP_SETTINGS.mode`。

### 実装

- 初回起動時だけ「マイクを有効にする」ボタンをタップして許可を取る（iOS はユーザー操作なしにマイクを開始できない）
- `AudioWorkletProcessor` で 128 サンプルごとに処理
- 各フレームで **RMS** と **高周波成分**（4kHz 以上のエネルギー比）を計測
- 周囲騒音の **移動平均**（時定数 3 秒）を持ち、固定音量ではなく相対しきい値で判定
- 拍手候補の条件：`rms > noise_floor * CLAP_RATIO` かつ `hf_ratio > CLAP_HF_MIN` かつ 立ち上がりが 20ms 以内
- `single` は候補が1つ出た時点で起動する（現在の既定）
- `double` は1回目から `CLAP_GAP_MIN`〜`CLAP_GAP_MAX` の間に2回目があれば起動する。誤起動が増えたときの逃げ道として残す
- 検出後 `CLAP_COOLDOWN_MS` は無反応

### パラメータ（設定画面で変更可能・端末内に保存）

| 名前 | 既定値 | 範囲 |
|---|---|---|
| `CLAP_RATIO` | 6.0 | 3.0–15.0 |
| `CLAP_HF_MIN` | 0.20 | 0.15–0.7 |
| `CLAP_GAP_MIN` | 250ms | 100–300 |
| `CLAP_GAP_MAX` | 800ms | 500–1500 |
| `CLAP_COOLDOWN_MS` | 2000 | 固定 |
| `CLAP_MODE` | `single` | `single` / `double` |

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

LLM を使わないルールベース。キーワードは `server/router.py` に表として持つ。

| 分類 | 意味 | 判定の手がかり | 実行モード |
|---|---|---|---|
| `SYSTEM` | 端末操作 | 「音量」「再接続」「寝て」「終わり」「ありがとう」「やめて」 | サーバー内処理 |
| `NOTE` | note の下書きを作る | 「note」「note記事」 | `note` |
| `WALLPAPER` | PC の壁紙を選ぶ | 「壁紙」「背景」「かべがみ」 | サーバー内処理 |
| `ASK` | Vault を読んで答える | 「何」「どこ」「教えて」「状態」「どうなってる」 | `read_only` |
| `CAPTURE` | デイリーへ記録する | 「記録して」「残して」「メモして」「書いて」 | `propose_write` |
| `DECIDE` | 判断・優先順位 | 「どっち」「優先」「決めて」「軍配」 | `read_only` |
| `EXECUTE` | Codex で作業する | 「作って」「直して」「実装して」 | `propose_write` |

### 規則

- `SYSTEM` を最優先で判定する（エージェントを起動しない）
- **`NOTE` と `WALLPAPER` は表より先に見る。** どちらも下の行の手がかりに
  食われる（「note書いて」→ `CAPTURE` の「書いて」／「壁紙変えて」→ `EXECUTE` の
  「変えて」）。先に捕まえないと、頼んでいない Vault の書き換え提案が出る
- **ひらがな・カタカナの「ノート」を `NOTE` に入れない。** Obsidian のノートと
  区別が付かず、「今日のデイリーノートに書いて」まで note の下書きになる
- 聞き間違いは実機ログに出たものだけを手がかりへ足す。推測で足さない
  （2026-09-05：「壁紙」が `壁が見` `風が見` と書き起こされ、5回中3回外していた）
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

**ビジュアルの正本はこの §15 だけ。** 過去の検討（移植先を取り違えた引き継ぎ・秘書画像の改訂案）は `docs/archive/` にある。実装の根拠にしない。

iPhone は縦置きを正とする。秘書画像ではなく、CachyOS の `sysmon` の `dots` パネル
（実体は **lavat**。§15.1）をそのまま移植したものをJARVISの顔にする。

- 中央に 69×34 のメタボールパネルを置く。丸い一般的なAIオーブにはしない
- **まず実物どおり「常に動いている」だけを再現する。状態や音への反応は後から決める**
- 上部は小さな JARVIS / PC LINK、下部は状態文と最低限の操作だけにする
- **表示文・ボタン・状態名はすべて英語**にし、短い状態名だけにする（実装は `apps/iphone-ui/src/copy.ts`）
- Caelestia のターミナル表示を組み替えたJARVIS自己紹介は接続・起動時だけ表示する
- Nerd Fontアイコンは小さな補助記号に限定し、iPhone Safariで字形を確認できないものは使わない
- 白髪秘書素材はUIへ表示しない。再利用する場合は目の位置と瞬きの整合を別途確認する
- `scheme.json` の `mode` と Material tokens を WebSocket で配信し、ライト／ダークへ即時追従する
- 使用する配色は `background` / `surfaceContainer` / `surfaceContainerHigh` / `onSurface` / `onSurfaceVariant` / `outlineVariant` / `primary` / `onPrimary` / `error`
- `scheme.json` が読めない場合はライトテーマの安全な既定値へ落とす
- 待機時は画面全体を240秒で数ピクセル移動させる
- OLED 保護のため、真っ白な静止画を長時間・最大輝度で表示しない

### 15.1 dots パネルの正体は lavat（2026-08-31 確認）

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

---

### 15.2 画面に足したもの（2026-09-05）

**1段目 `wake` 行** — 待機中に聞こえた音を1行で見せる（`Fetch.tsx` の `wakeRow`）。
右端が最新。`_` 静か / `▄` しきい値は越えたが起動条件に合わなかった音 / `█` 起こした1回。
高さの基準は `ABSOLUTE_MIN_RMS`（検出器と同じ関門）。生の RMS で描くと静かな部屋で
棒が動かない。

> **字は実測で選ぶこと。** `▁▂▃▅▆▇` `░▒▓` `▏▎▍▌` 点字はすべて同梱サブセットに無く、
> 基準9px に対して 15.2px の別フォントへ落ちて**箱の右の罫線が壊れた**（実測）。
> 入っているのは `▄` `█` と ASCII と罫線6字だけ。

> **行を増やしたら高さを測り直すこと。** 13行になって 9px はみ出し、箱の下の罫線が
> 切れた。行送りを 1.24 → 1.14、gap を 4 → 2 にして収めてある（390×844 実測）。

**3段目 操作ボタン** — 起きているあいだだけ出す（`Live.tsx` の `LiveAction`）。
待機へ戻ると消える。文字は添えず絵だけ（`aria-label` に名前を残す）。
背景 / チャット / タスク / 待機の4つ。**押してやることは全部いまある経路に乗せる** ──
背景とタスクは発話と同じ `text.input` を通すので、判定はサーバーのルーター1か所のまま。
画面側に2つ目の判定を作らない。

**チャット（打ち込み）** — 「チャット」を押すと1段目が文字回答カードになり、
下に打ち込み欄が出る（`AnswerCard` の `onSend`）。声で頼めない場面用。
打った文は `text.input` → ルーター → Codex と、声とまったく同じ道を通る。
状態も `CONTINUE` → `AUDIO_FINAL` で声と同じ入口へ入れる（飛ばすと THINKING の
見た目にならず経過も出ない）。入力欄は 16px（iOS は 16px 未満で自動拡大し桁が崩れる）。

> **浮かせた窓は作らない。** 質問と回答が積み上がる文字回答カードが既にチャット。
> 窓を浮かせると「どの段も同じ枠」という前提から外れ、iOS standalone の位置ズレ
> （2026-09-02、101px）を踏み直す。

> **見た目と状態を混ぜない。** ボタンの表示は `view`（`?state=` で差し替わる見た目）で
> 決める。「待機で畳む」判定を `state`（本物）で書いたため、プレビューで押した直後に
> 打ち消された（2026-09-05）。どちらか一方に揃えること。

**アイコンを足すとき** — `public/fonts/README.md` の `$ICONS` を先に直して
フォントを作り直す。**入っていない字は豆腐にならず、幅9pxの透明な空白として出る**ので
画面を見ても気づけない（2026-09-05、候補14字すべてが描画量0だった）。
コードポイントは記憶で書かず、元フォントで一覧に描いて選ぶ。

---

## 16. 常設運用

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

## 18.2 声から note の下書きまで（2026-09-05）

「noteの記事を書いて」で本文を作り、ブラウザで下書き保存まで行う。
「サムネも作って」が含まれる場合だけ、見出し画像を生成して記事へアップロードする。

「JARVISのnote書いて」と言うと、**Codex が本文を書き、そのまま下書きまで入る。**
Vault は変えない。公開には触れない。

```
発話 → router: NOTE (mode="note", long)
     → agent.run(mode="note")            読み取り専用。NOTE_SCHEMA で題と本文を受け取る
     → thumbnail.make(題)                見出し画像を文字と面だけで作る（1280×670）
     → note_writer.write(題, 本文, 画像)  常駐ブラウザで下書き保存
     → agent.completed（題と編集URLを画面へ）
```

決めてあること。

- **本文は Codex が Vault を根拠に書く。** 出典が言えないことは書かせない（`NOTE_PROMPT`）
- **題と本文が両方揃わなければ失敗にする。** 片方だけで進めると中途半端な記事が
  note に残り、作り直さない規則があるので取り返せない
- 見出し画像は**写真も生成AIも使わない**。文字と面だけで作る（出所を説明できる）。
  作れなかったら画像なしで下書きへ進む。あとから `note_draft header` で足せる
- **同時に2本走らせない。** 走っている間に頼まれたら `NOTE_BUSY` を返して待たせる
- ブラウザは1枚を常駐で持つ（専用プロファイルは1プロセスしか掴めない）
- 承認カードは出さない。§11 の承認は Vault への書き込みのための仕組みで、
  note の下書きは Vault の外。**代わりに画面に出したまま操作するのが確認手段**（§18.1）

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
