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

アイコンのコードポイントは推測せず `~/.config/fastfetch/config.jsonc` から取る。

## ライセンス

SIL Open Font License 1.1（RFNなし）。全文は `OFL.txt`。
抜き出したものも同じライセンスで、再配布にはこの表記と `OFL.txt` が必要。
