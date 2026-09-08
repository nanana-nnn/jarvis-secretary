# SETUP.md — セットアップ（AI が実行する前提で書いてある）

**エージェント（Codex CLI / Claude Code）へ:** これは上から順に実行するための手順書。
分岐が多いのは、この構成が「あなたの環境に何が入っているか」で変わるため。
**推測で埋めない。** 分からない値は §0 のとおり人に聞く。

人が手で叩きたい場合は [docs/manual-setup.md](docs/manual-setup.md)（同じことを分岐なしで並べた版）。

コマンド例は POSIX シェル（bash / zsh）で書いてある。fish のときは §7 の読み替えを見る。

---

## 0. 先に人へ聞く（4問）

答えが揃うまで先へ進まない。

1. **考える役はどちらにするか** — Codex CLI / Claude Code。
   両方入っていれば選んでもらう。どちらも**ログイン済みであること**が前提（このアプリは API キーを持たない）
2. **Vault にするフォルダの絶対パス** — Obsidian の Vault でなくてよい。Markdown が入ったフォルダなら動く。
   **書き込みが起きる場所**なので、テスト用に別フォルダを使いたいか併せて聞く
3. **任意機能をどれだけ入れるか** — (a) 壁紙の切り替えと配色連動 / (b) 作業が見えるターミナル / (c) note の下書き。
   全部いらないなら §5 を丸ごと飛ばす
4. **どの端末から使うか** — 同じ Wi-Fi のスマホ / PC のブラウザだけ。
   後者なら証明書は `127.0.0.1` で作る（§4）

---

## 1. 前提を数える

```sh
uname -sr
python3 --version
node --version && npm --version
openssl version
command -v codex claude magick foot hyprctl caelestia google-chrome-stable
```

判定：

| 見たもの | どうするか |
|---|---|
| `uname` が Linux でない | **ここで止める。** `server/facts.py` `browser.py` `terminal.py` が `/proc` を読むので動かない。人にそう伝える |
| Python < 3.11 | 止めて、入れ方を人に確認する（`pyproject.toml` が 3.11 以上を要求） |
| Node < 20 | 同上 |
| `openssl` が無い | 止める。証明書が作れず、ブラウザのマイクが開かない |
| `codex` も `claude` も無い | 止める。§0-1 の答えの側を入れてもらう |
| `magick` / `foot` / `hyprctl` / `caelestia` / Chrome が無い | 止めない。§5 で該当機能を切る |

---

## 2. 取ってきて入れる

```sh
git clone https://github.com/nanana-nnn/jarvis-secretary.git
cd jarvis-secretary
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm install
```

- `npm install` はルートで1回でよい（workspaces で `apps/iphone-ui` まで入る）
- Playwright の Chromium は**落とさない**。`server/browser.py` は `channel="chrome"` で
  OS に入っている Google Chrome を使う。`playwright install` は実行しないこと
- faster-whisper のモデルは**初回の音声認識のときに自動で落ちてくる**（`small` で数百MB、
  常駐時のメモリは実測 785MB）。ここでは何もしない

---

## 3. `.env` を書く

```sh
cp .env.example .env
```

`.env.example` の中身は作者の環境向けの確定形なので、**そのままにしない。**
最低限この4つを書き換える。

### HOST / ALLOWED_ORIGINS

PC の LAN IP を調べて入れる。`0.0.0.0` にはしない（LAN の外へ出さないため）。

```sh
ip -4 -brief addr | grep -v ' lo '
```

- 複数出たら、**スマホと同じ Wi-Fi につながっている側**を人に確認する
- §0-4 が「PC のブラウザだけ」なら `HOST=127.0.0.1`
- `ALLOWED_ORIGINS` は `https://<HOST>:5173` にする。ここが食い違うと
  WebSocket が `1008 origin not allowed` で閉じ、画面は OFFLINE のまま黙る

### VAULT_PATH

§0-2 で聞いた絶対パス。`~` は展開されないので**フルパスで書く**。

### AGENT_CMD ほか（考える役）

`.env.example` には Codex CLI の行が有効で、Claude Code の行がコメントで入っている。
§0-1 の答えが Claude Code なら、Codex の3行をコメントアウトして次を有効にする。

```dotenv
AGENT_CMD=cd {cwd} && claude -p --output-format text {sandbox} > {out_file}
AGENT_SANDBOX_READ=--allowedTools "Read,Glob,Grep"
AGENT_SANDBOX_WRITE=--permission-mode acceptEdits
```

**`AGENT_RESUME_CMD` も一緒に直すこと。** 既定は `codex exec resume --last` のままで、
Claude Code には効かない。効かせない場合は行ごとコメントアウトする（会話の続きだけが無効になる）。

置換される変数は `{sandbox} {cwd} {prompt_file} {schema_file} {out_file}`。
契約は「プロンプトは標準入力／答えの JSON を `{out_file}` へ書く／終了コード 0 が成功」。
この契約さえ満たせば、別のコマンドへ差し替えてよい（DESIGN.md §10）。

---

## 4. 証明書を作る

ブラウザのマイクは HTTPS でないと開かない。LAN IP 向けの自己署名証明書を作る。

```sh
./scripts/gen-cert.sh 192.168.1.74     # ← §3 で決めた HOST と同じ値
```

`certs/` は gitignore。**引数に `x` が入っているとスクリプトが弾く**（`192.168.0.x` のまま
渡す事故を止めるため）。HOST を変えたら作り直す。

---

## 5. 任意機能を決める（§0-3 の答えで分岐）

| 機能 | 要るもの | 入れないときにすること |
|---|---|---|
| 壁紙の切り替え・配色連動 | Hyprland + `caelestia` + `magick` | 何もしなくてよい。`~/.local/state/caelestia/scheme.json` が無ければ配色は既定のまま、壁紙一覧は空で出る |
| 作業が見えるターミナル | 端末エミュレータ（既定 `foot`）+ `hyprctl` | `.env` に `AGENT_VISIBLE=0` を書く。**書かないと既定でオン**（既定値は1） |
| 別の端末を使いたい | — | `AGENT_TERMINAL_CMD` を書き換える。`{title} {colours} {worker}` が置換される。例：`AGENT_TERMINAL_CMD=alacritty --title {title} -e bash {worker}` |
| note の下書き | Google Chrome | 何もしなくてよい。使わなければ起動しない |
| 壁紙を置く場所 | — | `~/画像/Wallpapers` か `~/Pictures/Wallpapers` を見る（`server/wallpapers.py`） |

note の下書きを使うなら、**ログインは人が手で1回だけ行う**（§8）。

---

## 6. 動かして確かめる

順に通す。**3つとも緑になってから**画面を見に行く。

```sh
.venv/bin/pytest        # server 側
npm test                # 画面側（vitest）
npm run build           # 型（tsc -b）とビルド
```

サーバーを起こして、生きているか確かめる。

```sh
.venv/bin/python -m server
curl -k https://<HOST>:8787/health
```

`{"ok":true,...}` 系が返れば通っている。`[Errno 99] cannot assign requested address` で
即死したときは、`HOST` がこの PC に割り当たっていない（Wi-Fi が別、あるいは IP が変わった）。

別の端末で画面を建てる。

```sh
npm run dev
```

ブラウザで `https://<HOST>:5173/?state=LISTENING` を開く。証明書の警告は「詳細 → アクセスする」で通す。
状態が指定どおりに描ければ、画面側は動いている。

---

## 7. fish のときの読み替え

作者の環境は fish。`&&` と `>` は同じだが、変数展開が違う。

```fish
# .env の HOST を読んで証明書を作る
./scripts/gen-cert.sh (string split = (grep '^HOST=' .env))[2]
```

`export VAR=値` は `set -x VAR 値`。venv は `source .venv/bin/activate.fish`
（このリポジトリの手順は `.venv/bin/python` を直接呼ぶので、activate は要らない）。

---

## 8. スマホでの初回（§0-4 が「スマホ」のとき）

1. ファイアウォールを開ける。**開けるのは LAN からの 5173 と 8787 だけ。**
   インターネットへ向けて開けない（`ufw` の例）
   ```sh
   sudo ufw allow from 192.168.1.0/24 to any port 5173 proto tcp
   sudo ufw allow from 192.168.1.0/24 to any port 8787 proto tcp
   ```
2. **端末を登録する（§13）。** 登録していない端末は繋がらない
   ```sh
   .venv/bin/python scripts/show-qr.py
   ```
   5分だけ有効な合図と URL が出る。スマホでその URL を開けば登録は終わり（1回だけ）。
   QR を出したいときは `.venv/bin/pip install qrcode` を先に入れる
3. スマホで `https://<HOST>:5173` を開き、証明書を信頼する
4. **マイクを有効にする**を1回押す（iOS はユーザー操作なしにマイクを開けない）
5. ホーム画面に追加すると全画面で常設できる
6. 指を1回鳴らす。コアが反応すれば通し（既定は指パッチン1回。DESIGN.md §7）

note の下書きを使うなら、ここで人に頼む。

```sh
.venv/bin/python -m server.note_draft login
```

専用プロファイルの Chrome が開くので、**本人が手で note にログインする**。
このリポジトリはパスワードも Cookie も持たない。

---

## 9. つまずくところ（既知）

| 症状 | 原因 |
|---|---|
| 画面が OFFLINE のまま | `ALLOWED_ORIGINS` と実際のオリジンの不一致。WS が 1008 で閉じている |
| サーバーが起動直後に落ちる | `HOST` がこの PC に無いアドレス。Wi-Fi が変わったか、DHCP で IP が動いた |
| スマホで開けない | ufw が 5173 / 8787 を通していない。**TLS の前に遮断される**ので警告すら出ない |
| マイクの許可が出ない | `http://` で開いている。secure context でないとブラウザがマイクを出さない |
| 壁紙は変わるのにスライダーが空 | `magick` が無い（サムネイルを作れない） |
| 文字起こしが遅い | 初回はモデルの取得。2回目以降も遅ければ `WHISPER_MODEL=small` を確認する |

---

## 10. やってはいけないこと（エージェントへ）

1. **`.env` の実値をコミットしない。** 追跡対象は `.env.example` だけ
2. **インターネットへポートを開けない。** ポートフォワード・UPnP・トンネルを設定しない
3. **Vault のファイルをこのリポジトリへコピーしない。** サーバーは `VAULT_PATH` の実パスを読む
4. **Vault へ勝手に書かない。** 書き込みは承認フローを通る。セットアップ中に試し書きをしない
5. **このアプリにクラウド AI API を足さない。** 手拍子・音声認識・読み上げは手元で完結させる（DESIGN.md §2）
6. セットアップの範囲を超えて実装へ手を伸ばさない。改造を頼まれたら [AGENTS.md](AGENTS.md) を先に読む

---

## 11. 認証の範囲（設置前に読む）

**登録した端末だけが繋がる**（2026-09-08 実装、DESIGN.md §13）。
WebSocket・承認・画像は端末トークンを要求し、持っていない接続は 4001 / 401 で切る。
サーバーはトークンの実値を持たず、SHA-256 だけを持つ。

それでも次は成り立たないので、置き場所は選ぶこと。

- **トークンを持ち出されたら終わり。** 端末の `localStorage` にあるので、
  端末そのものを渡すのと同じ意味になる
- **通信は自己署名証明書。** 同じ Wi-Fi にいる相手が証明書を差し替えても、警告を無視されたら通る
- `/health` は開いている（設置の確認に使う。返すのは固定値と登録台数だけ）
- `AUTH_REQUIRED=0` にすると誰でも繋がる。画面のない検証以外で使わない
- インターネットへ出さない（§10-2）
