# note下書き1本の手動実行

題: ブラウザでnoteの下書きをつくる。まずは1本、保存まで

本文と画像はテスト用。画像UIのセレクタ候補は実機未確認です。
このコマンドは新規記事を作るため、失敗後に再実行しないでください。
結果の編集URLで同じ記事を確認してください。

リポジトリのルートから、本人のターミナルで実行します。

```sh
.venv/bin/python -m pytest -q tests/test_note_draft.py
env NOTE_TYPE_DELAY_MS=55 .venv/bin/python -m server.note_draft draft \
  --title 'ブラウザでnoteの下書きをつくる。まずは1本、保存まで' \
  --body-file examples/note-draft-20260905/body.md \
  --header-image examples/note-draft-20260905/header.png \
  --layout full --keep-open 300
```

専用プロファイルにログイン済みの状態で、1回だけ実行します。
Chromeは画面に表示されます。既存CLIの仕様で300秒後に閉じます。
「公開に進む」は押しません。noteのAPIを直接呼ぶ処理はありません。
保存の成功判定は既存実装どおりクリック後の待機なので、最後は画面でも
題・本文・見出し画像と下書き状態を確認してください。

画像: 内蔵imagegenで作成。プロンプトは、横長1.91:1、青と生成りの
ブラウザ操作の概念イラスト、見出し「ブラウザで下書きをつくる」、
副題「本文と見出し画像を、1本ずつ」、実機スクリーンショットではなく
公開ボタンやnoteロゴを含めない、という指定です。
