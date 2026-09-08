# 自分で入れる

[SETUP.md](../SETUP.md) と同じことを、分岐を畳んで並べた版。
判断が要るところ（考える役の選択、任意機能の要否、認証が無いことの意味）は SETUP.md 側にしか
書いていないので、迷ったらそちらを読む。

コマンド例は fish。bash / zsh のときは §変数展開だけ読み替える。

## 入れる

```fish
git clone https://github.com/nanana-nnn/jarvis-secretary.git
cd jarvis-secretary
cp .env.example .env
# .env の 192.168.0.x を、この PC の LAN IP に置き換える。VAULT_PATH も自分のフォルダにする
./scripts/gen-cert.sh (string split = (grep '^HOST=' .env))[2]
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm install
```

bash / zsh なら証明書はこう。

```sh
./scripts/gen-cert.sh 192.168.1.74
```

`npm install` はルートで1回でよい（workspaces で `apps/iphone-ui` まで入る）。
Playwright の Chromium は落とさないこと（`server/browser.py` は OS の Google Chrome を使う）。
faster-whisper のモデルは初回の音声認識で自動的に落ちてくる。

## 動かす

端末を2枚。

```fish
.venv/bin/python -m server
npm run dev
```

スマホで `https://<HOST>:5173` を開き、証明書を信頼して、**マイクを有効にする**を1回押す。
ホーム画面に追加すると全画面の常設になる。

**スマホから使うポートは 5173 / 8787 に固定する。** ufw で LAN（`192.168.1.0/24`）から
許可しているのがこの2つだけなら、別ポートでは TLS の前に遮断される。

## 確かめる

```fish
.venv/bin/pytest
npm test
npm run build
```

実機と部屋が要る項目（再起動・Wi-Fi 復帰・手拍子の精度・一晩の放置）は
[phase-0-1-acceptance.md](phase-0-1-acceptance.md) を使う。
Phase 4（承認つき書き込み：却下 / 承認 / 120秒の自動却下）は 2026-09-01 に実機で通した。

## 見た目だけ確かめる（実機）

見た目の確認には静的ビルドを配る `npm run phone` を使う。リクエストが JS・CSS・画像あわせて
数本になる。

```fish
cd apps/iphone-ui
npm run phone      # VITE_PREVIEW=1 vite build && vite preview --port 5173 --strictPort
```

`?state=` で状態ごとの見た目を直接出せる。

```
https://<HOST>:5173/?state=THINKING
```

`SLEEP` / `WAKING` / `LISTENING` / `TRANSCRIBING` / `THINKING` / `APPROVAL` / `SPEAKING` /
`ERROR` / `OFFLINE`。この口は `VITE_PREVIEW=1` を付けて建てたときだけ開く。
`npm run build`（通常の本番ビルド）では無効。

## LAN の外にいるとき、PC のブラウザだけで見る

`.env` の `HOST` は自宅の LAN IP で固定してある。**別のネットワークにいるとそのアドレスは
自分に割り当たっていないので、サーバーは `[Errno 99] cannot assign requested address` で即死する。**

`.env` も証明書も書き換えずに、`127.0.0.1` で建てるスクリプトを使う。

```fish
./scripts/serve-local.sh      # Ctrl-C でサーバーとプレビューの両方が止まる
```

`https://127.0.0.1:5173/` を開く。証明書は LAN IP 向けなので名前が一致せず警告が出る。
「詳細 → アクセスする」で通す。`?state=LISTENING` も使える。

これは見た目の確認用で、**外から本番として使う道ではない**（LAN の外へ出す仕組みは作らない）。

## 画像を足すとき

`apps/iphone-ui/public/assets/` に置く画像は WebP にする。

```fish
magick source.png -resize '1672x940!' -quality 78 -define webp:method=6 out.webp
```

PNG のまま置くと数MBになり、Wi-Fi 経由の初回表示が「止まったように見える」
（2026-08-29 に2枚 6.3MB で実際に固まった）。**合計 400KB 未満**を目安にする。
同梱画像の扱いは [ASSETS.md](ASSETS.md)。
