# 同梱している画像の出どころ

コードとドキュメントは MIT（`LICENSE`）。**このページに挙げた画像は MIT の対象外。**
リポジトリを読むために置いてあるだけで、再配布・改変・自分の作品への流用は許可していない。
フォークして使う人は、下の「無いとどうなるか」を見て自分の画像へ差し替えること。

| ファイル | 何 | 出どころ | 無いとどうなるか |
|---|---|---|---|
| `server/assets/note-header-base-image2.png` | note 見出し画像の背景（1732×908） | 画像生成モデルの出力（`server/thumbnail.py` 冒頭の「Image 2で生成した背景」） | `thumbnail.py` が無地の背景（`#F4EFE6` + 紺の帯）へ自動で切り替わる。機能は止まらない |
| `examples/note-draft-20260905/header.png` | 上の背景の控え（手動実行の入力に使った） | 同上 | 例を再現するとき `server/assets/note-header-base-image2.png` を指せばよい |
| `examples/note-jarvis-*/header.png` | `thumbnail.py` が実際に作った出力（1280×670） | 上の背景＋ImageMagick の文字乗せ | 例の見た目が分からなくなるだけ |

フォントは同梱していない。`thumbnail.py` は OS に入っている `Noto-Sans-CJK-JP` を名前で呼ぶ。

## 落としたもの

秘書のポートレート（`secretary-sleep` / `secretary-awake` の webp・png・svg）と、それを描いていた
`components/Secretary.tsx` は、**公開前に履歴ごと削除した**（2026-09-08）。出どころを記録できておらず、
かつ画面に出ていなかったため。ビジュアルの正本は DESIGN.md §15 の `lavat` 由来のコア表示で、
ポートレートは使っていない。元画像は作者の手元（`.asset-backup/`、gitignore）にだけ残っている。

## 埋めるところ（作者向け）

- [ ] `note-header-base-image2.png` を作ったツール名と日付
