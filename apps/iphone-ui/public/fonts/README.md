# fonts

`jbmono-nerd-{regular,bold}.woff2` は JetBrainsMono Nerd Font Mono から、
この画面で実際に使う字だけを抜き出したもの（125字 / 各6.9KB）。

- ASCII、枠線6字、fastfetch の項目アイコン5字、live(3段目)のアイコン7字、
  文字回答カードの2字
- 全グリフの送り幅が 0.6em で揃っているので、枠と本文の桁がずれない

フォント全体は約4MBあり、そのまま置くとWi-Fi経由の初回表示が固まる
（2026-08-29 に PNG 6.3MB で同じ事故を起こしている）。必ず抜き出して使う。

## 作り直すとき

**この `$ICONS` が全字を含む。** ここが正本。コンポーネント側で新しい字を
使ったら、まずここへ足してから作り直す（2026-09-02、live(3段目)の7字を
この行に足し忘れたまま作り直し、実機でアイコンが消える事故を起こした）。

```fish
set UNI "U+0020-007E,U+00A0,U+2500,U+2502,U+256D,U+256E,U+256F,U+2570,U+2022,U+25CF,U+2026,U+2588,U+2580,U+2584,U+25B6"
set ICONS "U+F473,U+E385,U+F489,U+EFC5,U+F487,U+F007,U+F108,U+F0EC0,U+F0AA2,U+E6BB,U+EC81,U+EC82,U+F268,U+EA85,U+F011C,U+E702"
pyftsubset /usr/share/fonts/TTF/JetBrainsMonoNerdFontMono-Regular.ttf \
  --unicodes="$UNI,$ICONS" --layout-features= --no-hinting --desubroutinize \
  --flavor=woff2 --output-file=jbmono-nerd-regular.woff2
# bold も同じ --unicodes で JetBrainsMonoNerdFontMono-Bold.ttf から作る
```

アイコンのコードポイントは推測せず、出どころから取る。
- fetch(1段目)の5字（`U+F473 U+E385 U+F489 U+EFC5 U+F487`）
  … `Fetch.tsx` の `ROWS`（kernel/uptime/shell/mem/pkgs）。
  出どころは `~/.config/fastfetch/config.jsonc` の key
- live(3段目)の7字（`U+E6BB U+EC81 U+EC82 U+F268 U+EA85 U+F011C U+E702`）
  … `Live.tsx` の `APPS` 5字 + `PHONE` + `GIT`。
  **必ず一度描いて字を目で確かめてから入れる**
- `U+F0AA2` … 文字回答カード(`AnswerCard.tsx`)のプロンプト行。
  `~/.config/starship.toml` の `[cmd_duration]` と同じ字（2026-09-02追加）
- `U+25B6`（▶）… 同じくプロンプト行の矢印。フォールバックフォントでも表示は
  できていたが、字送りを他の字と揃えるため本体へ入れた
- `U+F007,U+F108,U+F0EC0` … 出どころ未確認の3字。将来消えたら描いて確認する

2026-08-31、記憶で書いたら md-brain のつもりが再生ボタン、sparkle のつもりが
車になった。候補を並べて描いた画像で確認してから決めること。

## ライセンス

SIL Open Font License 1.1（RFNなし）。全文は `OFL.txt`。
抜き出したものも同じライセンスで、再配布にはこの表記と `OFL.txt` が必要。
