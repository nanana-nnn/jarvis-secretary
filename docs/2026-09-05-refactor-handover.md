# 引き継ぎ：2026-09-05 の作業

Claude Code が1日で入れた変更のまとめ。**続きを引き取る人がこれを最初に読む。**
commit して実機で1周確認できたら `docs/archive/` へ移してよい。

## 今どうなっているか

| | 状態 |
|---|---|
| 機械検証 | **全通過**（pytest 125 / vitest 21 / `tsc -b` / `npm run build`） |
| 実機（iPhone）確認 | **一部だけ**。下の表を見ること |
| note の下書き | 3本できている。**すべて未公開**（未ログインで404を確認済み） |

### 実機で確かめた／確かめていない

| 何を | 実機 |
|---|---|
| 手拍子で起きる → 話す → 壁紙が実際に変わる | **通った** |
| 3段目のテレメトリ・生死表示 | **通った** |
| 声 → note の下書き（§18.2） | **未確認。まだ一度も声から通していない** |
| 1段目の `wake` 行 | ヘッドレスで桁と高さは実測。**実機の見た目は未確認** |
| 3段目の操作ボタン・チャット打ち込み | ヘッドレスで寸法は実測。**実機のタップとキーボードは未確認** |
| 指パッチン1回での誤起動の量 | **未確認**（下の「気をつけること」1番） |

## 何を変えたか

### 1. 構成の作り直し（挙動は変えていない）

`server/app.py` 865行 → **155行**。`create_app` の中に全部入っていたものを出した。

| 旧（`app.py` の中） | 新 |
|---|---|
| WS ハンドラ・`finish` / `respond` | `session.py` の `Session` |
| `clients` / `watch_scheme` / `push_telemetry` / 各 event | `hub.py` の `Hub` |
| `pending` / 承認 / 監査ログ / 自動却下 | `approval.py` の `ApprovalStore` |
| テレメトリ・プロセス走査 | `facts.py` |
| caelestia の配色 | `scheme.py` |
| Vault の git 状態 | `gitstate.py` |
| `timestamp_ms` | `clock.py` |
| 今出ている壁紙 | `wallpapers.py` の `current_*` |

`App.tsx` 696行 → **327行**。`hooks/useSecretarySocket` `useMicrophone` `useQaCard`
`useViewportReset` と `theme.ts` `copy.ts` `model.ts` `clap-settings.ts` へ分けた。

呼び名だけ変わったもの：`openQaSession`→`qa.open` / `appendQaExchange`→`qa.append` /
`updateLastQa`→`qa.update` / `appendQaLines`→`qa.addLines` / `setQa([])`→`qa.clear`。

削除：`server/briefing.py` と `tests/test_briefing.py`（配線が外れて誰も呼んでいなかった）。
**戻すときは commit `f883f54` から2ファイルとも取る。**

### 2. 起動方式を指パッチン1回へ戻した（本人の指定）

真値は `apps/iphone-ui/src/audio/types.ts` の `DEFAULT_CLAP_SETTINGS.mode`。
経緯は 8/26 single → 9/2 double（タイピング音の誤起動）→ **9/5 single**。

### 3. ルーターに NOTE を足した／聞き間違いを拾えるようにした

- `NOTE`（「note」「note記事」）→ Codex が本文を書いて下書きまで（§18.2）
- 「壁紙」の聞き間違い `壁が見` `風が見` を実機ログから `WALLPAPER_WORDS` へ追加。
  5回中3回外していた

### 4. 画面（§15.2）

1段目に `wake` 行、3段目に操作ボタン4つ、チャットの打ち込み欄。

### 5. 直したバグ

| 何 | どこ |
|---|---|
| 「続けて聞く」のあと LISTENING から待機へ戻らない（`speaking` を降ろすのが WAKING の中だけだった） | `App.tsx` `continueQa` |
| 見出し画像が入っているのに失敗と報告する／確定ダイアログを開いたまま進んで下書き保存を押せない | `note_draft.py` `_confirm_header` |
| 編集画面からプレビューへ流されると保存できない | `note_draft.py` `_back_to_editor` |
| 切断時に走っている Codex が止まらない | `session.py` `_agent_with_progress` |

## 気をつけること

1. **指パッチン1回は誤起動が増える見込み。** 9/5 のログ（候補468件）で、single 相当だと
   起動は 14回 → 52回になる。**mode を勝手に戻さないこと**（本人の指定が優先）。
   誤起動が出たら `CLAP_RATIO` / `CLAP_HF_MIN` を上げて対処する（§7）
2. **`useSecretarySocket` と `useMicrophone` の依存配列が空なのは意図。**
   普通の依存配列に「直す」と、再接続のたびに端末が STANDBY へ戻り、音が途切れる
3. **`app.py` 末尾の再輸出を消さない。** `tests/test_server.py` と `test_approval.py` が
   `server.app.<name>` で参照している
4. **note は失敗しても作り直さない。** 同じ編集URLで確認する。公開ボタンには触れない
5. **フォントに無い字は透明な空白として出る。** 豆腐にならないので画面では気づけない。
   字を足すときは `public/fonts/README.md` の `$ICONS` を直して作り直す
6. **1段目の行を増やしたら高さを測り直す。** 13行で 9px はみ出して罫線が切れた

## 実機で見るところ

1. 配色と壁紙が PC に追従する
2. 3段目のテレメトリが5秒ごとに動く
3. **指パッチン1回**で起きる → 光が縁を1周 → LISTENING
4. 何か聞く → 回答カードに行が出る
5. 「壁紙かえたい」→ スライダー → 選ぶ → 変わってカードへ戻る
6. **続けて聞く → 黙る → 10秒で待機へ戻る**（今日直したところ）
7. **3段目のボタン4つ**（背景／チャット／タスク／待機）。待機で消えること
8. **チャットで打ち込んで Codex へ通る**こと。キーボードで画面が崩れないこと
9. **「JARVISのnote書いて」と声で頼んで下書きまで**（まだ一度も通していない）
10. 書き込みを頼む → 承認カード → 承認と却下の両方
11. 黙って120秒 → 自動却下が届く

## 検証コマンド

```fish
.venv/bin/python -m pytest -q          # 125 passed
npx vitest run                         # 21 passed
npx tsc -b apps/iphone-ui
npm run build
```

## 別セッションが入れた変更

`apps/iphone-ui/src/api/socket.ts` と `socket.test.ts`、`tests/test_lifecycle_regressions.py`、
`_kit/AI_RULES.md` の省トークン運用の節は Codex 側が入れたもの。**そのまま残してある。**
socket.ts は「サーバーが古い端末を閉じたとき（コード4000）に再接続しにいかない」修正で、
放っておくと2つのタブが互いを蹴り合う。正しい上乗せ。
