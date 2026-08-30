# JARVIS Secretary — Phase 0/1

HTTPS/WSS connection, installable iPhone PWA, finite-state UI, and local double-clap detection. Audio upload, speech recognition, Vault access, and agents are intentionally not implemented.

## Setup

```fish
cp .env.example .env
# Replace 192.168.0.x with this PC's LAN address in .env
./scripts/gen-cert.sh (string split = (grep '^HOST=' .env))[2]
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm install
```

## Run

In two terminals:

```fish
.venv/bin/python -m server
npm run dev
```

Open `https://<HOST>:5173` on the iPhone, trust the generated certificate, then tap **マイクを有効にする** once. Add the page to the Home Screen for standalone landscape use.

## 外出先で、PCのブラウザだけで見る

`.env` の `HOST` は自宅の LAN IP（`192.168.1.74`）で固定してある。**別のネットワークに
いるとそのアドレスは自分に割り当たっていないので、サーバーは
`[Errno 99] cannot assign requested address` で即死する。**

`.env` も証明書も書き換えずに、`127.0.0.1` で建てるスクリプトを使う。

```fish
./scripts/serve-local.sh      # Ctrl-C でサーバーとプレビューの両方が止まる
```

`https://127.0.0.1:5173/` を開く。証明書は自宅IP向けなので名前が一致せず警告が出る。
「詳細 → アクセスする」で通す。`?state=LISTENING` も使える。

自宅へ戻ったら、この節は使わず下の「実機（iPhone）で見た目を確認する」に戻る。

## 実機（iPhone）で見た目を確認する

**iPhone から使うポートは 5173 / 8787 に固定する。** ufw で LAN
（`192.168.1.0/24`）から許可しているのがこの2ポートだけなので、別ポートでは
TLS の前に遮断される。見た目確認には静的ビルドを配る `npm run phone` を使う。

代わりに静的ビルドを配る。リクエストは JS・CSS・画像あわせて数本になる。

```fish
cd apps/iphone-ui
npm run phone      # VITE_PREVIEW=1 vite build && vite preview --port 5173 --strictPort
```

`?state=` で状態ごとの見た目を直接出せる（`SLEEP` / `WAKING` / `LISTENING` /
`TRANSCRIBING` / `THINKING` / `APPROVAL` / `SPEAKING` / `ERROR` / `OFFLINE`）。

```
https://<HOST>:5173/?state=THINKING
```

この口は `VITE_PREVIEW=1` を付けて建てたときだけ開く。`npm run build`（通常の本番ビルド）では無効。

### 画像は必ず WebP にする

`public/assets/secretary-*.webp` は PNG 原本から変換し、sleep / awake を同じ 1672×940 に揃える。
原本は `apps/iphone-ui/.asset-backup/source/` にある。

```fish
magick secretary-sleep.png -resize '1672x940!' -quality 78 -define webp:method=6 secretary-sleep.webp
```

PNG のまま置くと2枚で 6MB を超え、Wi-Fi 経由の初回表示が「止まったように見える」。
WebP は2枚合計 400KB 未満を目安にする。

## Verify

```fish
.venv/bin/pytest
npm test
npm run build
```

The Phase 0 restart/Wi-Fi recovery test and Phase 1 clap accuracy/overnight test require the target iPhone and room, so use `docs/phase-0-1-acceptance.md`.
