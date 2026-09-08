# JARVIS Secretary

手を2回叩くと、スタンドのスマホが起きる。話しかけると、**あなたのPC**がその場で文字起こしして、
Obsidian の Vault を読んで答える。Vault への書き込みは、スマホに出る承認を通ったものだけ。

このアプリはクラウドの AI API を呼ばない。手拍子の判定はスマホの中、音声認識は PC の中で終わり、
通信は同じ Wi-Fi の中に閉じている。考える仕事は、すでにあなたの PC へ入っている
**Codex CLI か Claude Code** に渡す（`.env` の1行で切り替わる）。

> **English** — A LAN-only voice secretary for a phone on a stand. Clap twice to wake it, speak, and
> your own PC transcribes locally (faster-whisper), reads your Obsidian vault, and answers on screen.
> Writes are approval-gated. The app calls no cloud AI API: the thinking is delegated to the Codex CLI
> or Claude Code already installed on your machine. **The setup guide ([SETUP.md](SETUP.md)) is written
> to be executed by that agent** — clone this repo, open Codex or Claude Code inside it, and say
> "set this up by following SETUP.md". Everything below is Japanese; the setup file is what matters.

## できること

| | |
|---|---|
| **手拍子2回で起きる** | 判定はブラウザの AudioWorklet の中。マイクの音はどこへも送らない |
| **話しかけて聞く** | 発話の終わりを VAD で切り、PC の faster-whisper で文字起こしする |
| **Vault を読んで答える** | 「今日のタスク」「先週決めたこと」を Markdown から拾い、画面のカードに出す |
| **書き込みは承認制** | 提案がスマホに出て、承認するまで1文字も書かない。120秒で自動却下 |
| **PCの画面で作業が見える**（任意） | 依頼が実際のターミナルで動き、その様子が PC のディスプレイに出る |
| **声で壁紙を変える**（任意） | Hyprland + caelestia。壁紙に合わせてスマホ側の配色も変わる |
| **声から note の下書き**（任意） | 常駐ブラウザで下書きまで作る。**公開はしない** |

## 動作条件

| | 要るもの | 無いとどうなるか |
|---|---|---|
| 必須 | **Linux**（Wayland で確認。Arch系 CachyOS で開発） | PC の実測パネルが `/proc` を読む。macOS / Windows では動かない |
| 必須 | Python 3.11 以降 / Node 20 以降 | — |
| 必須 | **Codex CLI か Claude Code**（ログイン済み） | 考える役がいない。`.env` の `AGENT_CMD` で差し替える |
| 必須 | Markdown の入ったフォルダ（Obsidian の Vault でなくてよい） | 読み書きの対象。`VAULT_PATH` で指す |
| 必須 | `openssl` | ブラウザのマイクは HTTPS でしか開かない。LAN 用の自己署名証明書を作る |
| 必須 | 同じ Wi-Fi のスマホ（iOS Safari / PWA で確認） | 画面。PC のブラウザだけでも見られる |
| 任意 | ImageMagick（`magick`） | 壁紙のサムネイルと note の見出し画像が出ない |
| 任意 | Hyprland + [caelestia](https://github.com/caelestia-dots/shell) | 壁紙の切り替えと配色の連動が丸ごと出ない。他は動く |
| 任意 | 端末エミュレータ（既定は `foot`） | 「作業が見える」表示だけ消える。`AGENT_VISIBLE=0` で明示的に切れる |
| 任意 | Google Chrome | note の下書き機能が使えない |

## はじめかた

### A. AI に入れてもらう（推奨）

このアプリは **Codex CLI か Claude Code をどのみち要求する**。だから設定もそれにやらせるのが速い。
難所（LAN の IP、証明書、デスクトップ環境ごとの分岐、任意機能の要否）は、
手順書を固定するとまず他人の環境で外れる。

```sh
git clone https://github.com/nanana-nnn/jarvis-secretary.git
cd jarvis-secretary
codex        # または claude
```

開いたエージェントにこう言う。

```
SETUP.md のとおりにセットアップして。分からないことは推測せず聞いて。
```

[SETUP.md](SETUP.md) は**エージェントが上から順に実行するために書いてある**。
先に人へ聞くべき4問、環境の検出、入っていないものの扱い、動いたことの確かめ方まで入っている。

### B. 自分で入れる

コマンドを自分で叩きたい人は [docs/manual-setup.md](docs/manual-setup.md)。
SETUP.md と同じことを、分岐を畳んだ形で並べてある。

## 動かす

端末を2枚使う。

```sh
.venv/bin/python -m server     # 1枚目：API と WebSocket（既定 8787）
npm run dev                    # 2枚目：画面（5173）
```

スマホで `https://<HOST>:5173` を開き、証明書を信頼して、**マイクを有効にする**を1回押す。
ホーム画面に追加すると全画面で常設できる。

見た目だけ確かめたいときは、状態を URL で直接出せる。

```
https://<HOST>:5173/?state=THINKING
```

`SLEEP` / `WAKING` / `LISTENING` / `TRANSCRIBING` / `THINKING` / `APPROVAL` / `SPEAKING` / `ERROR` / `OFFLINE`。
この口が開くのは `VITE_PREVIEW=1` で建てたときだけで、`npm run build` では無効。

## 安全のために決めてあること

- **インターネットへポートを開けない。** 同一 Wi-Fi 内だけ。外から使う仕組みは作らない（DESIGN.md §2）
- **クラウドの AI API を呼ばない。** 手拍子・音声認識・読み上げはすべて手元で終わる
- **Vault への書き込みは承認を通ったものだけ。** 削除・移動・改名は実装していない。`git commit` は自動化しない
- **note は下書きまで。** 公開の操作は実装していない。ログインは専用プロファイルで本人が手で1回だけ行う
- `.env` は gitignore。秘密の値を `.env.example` へ書かない

**ただし、接続してきた端末の認証は無い。** 効いているのは CORS と WebSocket の Origin チェックだけで、
同じ Wi-Fi にいる相手には壁にならない。信用できる人しかいない Wi-Fi で使うこと（[SETUP.md §11](SETUP.md#11-認証は無い設置前に読む)）。

## ドキュメント

| | |
|---|---|
| [SETUP.md](SETUP.md) | セットアップ（AI が実行する前提） |
| [docs/manual-setup.md](docs/manual-setup.md) | 同じ内容を手で叩く版 |
| [DESIGN.md](DESIGN.md) | 仕様の正本。状態機械・API・安全設計・実装段階 |
| [AGENTS.md](AGENTS.md) | このリポジトリを**改造する** AI 向けの作業ルール |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 手を入れるとき |
| [docs/ASSETS.md](docs/ASSETS.md) | 同梱画像の出どころとライセンス除外 |

## ライセンス

コードとドキュメントは MIT（[LICENSE](LICENSE)）。**画像は対象外**（[docs/ASSETS.md](docs/ASSETS.md)）。

## 現状

Phase 0–4 まで実装済み（接続 / 手拍子 / 音声往復 / Vault 読み取り / 承認つき書き込み）。
Phase 5「常設品質」（OLED 保護・自動再起動・停電復帰）は未着手。
Phase 4 は 2026-09-01 に実機で通した。実機と部屋が要る受け入れ項目は
[docs/phase-0-1-acceptance.md](docs/phase-0-1-acceptance.md) にある。
