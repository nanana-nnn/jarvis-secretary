# 手を入れるとき

## 人へ

- **まず動かしてから。** セットアップは [SETUP.md](SETUP.md)。壊れた報告より「自分の環境ではこう外れた」が助かる
- 仕様の正本は [DESIGN.md](DESIGN.md)。振る舞いを変える変更は、DESIGN.md の該当節も同じコミットで直す
- 検証は3つ揃えて出す。`.venv/bin/pytest` / `npm test` / `npm run build`
- 手拍子・音声認識・読み上げに**クラウドAPIを足さない。** LAN の外へ出ないことがこのアプリの前提（DESIGN.md §2）
- 環境依存の機能（caelestia の壁紙・foot のターミナル・Chrome の note 操作）を足すときは、
  **無い環境で静かに無効化されること**を確認する。落ちてはいけない
- コミットメッセージ・コード内コメントは日本語で構わない

## AI（Codex / Claude Code）へ

このリポジトリで作業するときのルールは [AGENTS.md](AGENTS.md) にある。着手前に読む。
セットアップを頼まれただけなら [SETUP.md](SETUP.md) だけでよい。

## 報告

Issue には最低限これを書いてほしい。

```
OS / デスクトップ環境:
Python / Node:
使ったエージェント: codex | claude
起きたこと:
そのときの `.venv/bin/python -m server` の出力:
```
