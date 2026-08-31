# fonts

`jbmono-nerd-{regular,bold}.woff2` は JetBrainsMono Nerd Font Mono から、
この画面で実際に使う字だけを抜き出したもの（116字 / 各5.7KB）。

- ASCII、枠線6字（`╭ ╮ ╰ ╯ ─ │`）、fastfetch の項目アイコン8字
- 全グリフの送り幅が 0.6em で揃っているので、枠と本文の桁がずれない

フォント全体は約4MBあり、そのまま置くとWi-Fi経由の初回表示が固まる
（2026-08-29 に PNG 6.3MB で同じ事故を起こしている）。必ず抜き出して使う。

## 作り直すとき

```fish
set UNI "U+0020-007E,U+00A0,U+2500,U+2502,U+256D,U+256E,U+256F,U+2570,U+2022,U+25CF,U+2026,U+2588,U+2580,U+2584"
set ICONS "U+F473,U+E385,U+F489,U+EFC5,U+F487,U+F007,U+F108,U+F0EC0"
pyftsubset /usr/share/fonts/TTF/JetBrainsMonoNerdFontMono-Regular.ttf \
  --unicodes="$UNI,$ICONS" --layout-features= --no-hinting --desubroutinize \
  --flavor=woff2 --output-file=jbmono-nerd-regular.woff2
```

アイコンのコードポイントは推測せず、出どころから取る。
- fetch(1段目)の8字 … `~/.config/fastfetch/config.jsonc` の key に埋まっている
- live(3段目)の7字 … **必ず一度描いて字を目で確かめてから入れる**

2026-08-31、記憶で書いたら md-brain のつもりが再生ボタン、sparkle のつもりが
車になった。候補を並べて描いた画像で確認してから決めること。

## ライセンス

SIL Open Font License 1.1（RFNなし）。全文は `OFL.txt`。
抜き出したものも同じライセンスで、再配布にはこの表記と `OFL.txt` が必要。
