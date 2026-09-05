"""note の下書きをブラウザ操作で1本作る（2026-09-05）。

「ブラウザ操作の許可」の最初の1本。**公開まで行かない。下書き止まり。**
本文の生成（Codex）とは分けてあり、ここがやるのは「与えられた題と本文を
note のエディタへ入れて、下書きとして保存する」だけ。失敗したときに
原因が本文側かブラウザ側かを切り分けられるようにするため（2026-09-05、本人の選択）。

ブラウザは server/browser.py の常駐1枚（専用プロファイル・開いたまま）。
ログインはこのプロファイルの中に一度だけ本人が手で行う。

  ログイン: .venv/bin/python -m server.note_draft login
  下書き:   .venv/bin/python -m server.note_draft draft --title 題 --body-file 本文.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys

from .browser import LAYOUTS, PROFILE_DIR, VisibleBrowser

# 素の Chrome を開くときの実体。VisibleBrowser は channel="chrome" で同じものを使う
CHROME_BINARY = os.getenv("BROWSER_BINARY", "google-chrome-stable")

# 素の Chrome で開くときも、**クッキーの鍵を Playwright 側と揃える。**
# 何も指定しないと Chrome は OS のキーリングでクッキーを暗号化する。
# Playwright が起動する Chrome は `--use-mock-keychain`（固定鍵）で動くので、
# 鍵が合わず値を復号できない。ログイン済みのクッキーが名前だけ残り、
# 画面は未ログインのまま、という食い違いになる（2026-09-05、実機で1時間はまった）
MANUAL_ARGS = ("--use-mock-keychain", "--password-store=basic")

logger = logging.getLogger("uvicorn.error")

TOP = "https://note.com/"
LOGIN = "https://note.com/login"
# 新規テキスト投稿。note はここから編集URL（/notes/<key>/edit）へ飛ばす
NEW_TEXT = "https://note.com/notes/new"

# ログインしていないと必ず出る導線。これが消えたらログイン済みと見る
LOGGED_OUT_MARK = 'a[href^="/login"]'

LOGIN_POLL_S = 2.0
LOGIN_WAIT_S = 300          # 手で入れる時間。5分待って諦める


async def logged_in(page, navigate: bool = True) -> bool:
    """ログイン済みか。**トップの「ログイン」リンクの有無で見る。**

    `navigate=False` のときは今開いている画面をそのまま読む。
    **待ち受け中はこちらを使う。** 2秒おきにトップへ遷移して確かめていたら、
    本人がログイン情報を入れている最中に画面を飛ばしてしまった
    （2026-09-05、実機で「ログインしようとするとリロードがかかる」）。
    """
    if navigate and not page.url.startswith(TOP):
        await page.goto(TOP, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
    if not page.url.startswith("https://note.com/"):
        return False                      # note の外（外部ログインの途中など）
    return await page.locator(LOGGED_OUT_MARK).count() == 0


async def wait_for_login(browser: VisibleBrowser, timeout_s: int = LOGIN_WAIT_S) -> bool:
    """ログイン画面を出して、本人が入れ終わるのを待つ。**代わりに入力しない。**

    資格情報はこのプロジェクトの持ち物ではない（Vault にも .env にも置かない）。
    開いたブラウザで本人が入れる。入り終わったらプロファイルに残るので、
    以降の下書きは無人で通る。

    待っているあいだ、**こちらからは一切ページを動かさない。**
    見るのは今表示されている画面だけ（上の navigate=False）。
    """
    page = await browser.page()
    if await logged_in(page):
        return True
    await page.goto(LOGIN, wait_until="domcontentloaded")
    print("ブラウザで note にログインしてください（待っています）", flush=True)
    waited = 0.0
    while waited < timeout_s:
        await page.wait_for_timeout(int(LOGIN_POLL_S * 1000))
        waited += LOGIN_POLL_S
        try:
            # ログインが済むと note の中の別の画面（トップ等）へ移る。
            # /login に居るあいだ・note の外に居るあいだは何もしない
            if "/login" in page.url:
                continue
            if await logged_in(page, navigate=False):
                print("ログインを確認しました", flush=True)
                return True
        except Exception:
            return False                  # ブラウザを閉じられた
    return False


# エディタの掴みどころ。**候補を順に試す。** note の DOM は変わるので、
# 1つに賭けると次の改装で黙って壊れる。当たったものをログに出して、
# 壊れたときにどこで外れたか分かるようにする
TITLE_SELECTORS = (
    'textarea[placeholder*="タイトル"]',
    'input[placeholder*="タイトル"]',
    '[data-testid="note-title"]',
    'h1[contenteditable="true"]',
)
BODY_SELECTORS = (
    'div.ProseMirror[contenteditable="true"]',
    '[data-testid="note-body"] [contenteditable="true"]',
    'div[contenteditable="true"]:not([placeholder*="タイトル"])',
)
# **「公開」は押さない。** 押していいのは下書き保存だけ（2026-09-05、本人の指定）
DRAFT_BUTTON_SELECTORS = (
    'button:has-text("下書き保存")',
    'button:has-text("保存")',
    '[data-testid="save-draft"]',
)
EDITOR_WAIT_MS = 20000

# 打鍵の速さ（1文字あたりms）。**人が書く速度に寄せる**（2026-09-05）。
# note の規約に自動操作を禁じる条項は無いが、2026-02-27 のお知らせで
# 「機械的に大量の記事を投稿する行為」への対応強化が明文化されている。
# 機械的な速さを出さないことと、1件ずつにとどめることでそこから離れる
# （調査は Vault の `04_resources/2026-09-05 noteのAI利用と自動操作の規約確認`）。
# 画面に映すのが目的でもあるので、速すぎると「書いている様子」にも見えない
TYPE_DELAY_MS = int(os.getenv("NOTE_TYPE_DELAY_MS", "55"))
# 段落のあいだの間。人が改行して次を書きはじめるまでの呼吸
PARAGRAPH_PAUSE_MS = 400


async def _first_visible(page, selectors: tuple[str, ...], timeout_ms: int):
    """候補のうち最初に現れたものを返す。どれも来なければ None。"""
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            continue
        logger.info("[NOTE] matched %s", selector)
        return locator, selector
    return None


async def create_draft(browser: VisibleBrowser, title: str, body: str) -> dict:
    """題と本文を入れて下書き保存する。返すのは結果の要約。

    **公開しない。** 押すのは下書き保存だけで、公開ボタンには触れない。
    """
    page = await browser.page()
    if not await logged_in(page):
        return {"ok": False, "error": "not_logged_in",
                "message": "note にログインしていません（`python -m server.note_draft login`）"}

    await page.goto(NEW_TEXT, wait_until="domcontentloaded")
    # 窓が狭いとエディタが右で切れる。遷移のたびに中身の縮尺を掛け直す
    await browser.fit_page(page)
    found = await _first_visible(page, TITLE_SELECTORS, EDITOR_WAIT_MS)
    if found is None:
        return {"ok": False, "error": "no_title_field", "url": page.url,
                "message": "エディタの題名欄が見つかりません（note の画面が変わった可能性）"}
    title_field, _ = found
    await title_field.click()
    await page.keyboard.type(title, delay=TYPE_DELAY_MS)

    found = await _first_visible(page, BODY_SELECTORS, 5000)
    if found is None:
        return {"ok": False, "error": "no_body_field", "url": page.url,
                "message": "エディタの本文欄が見つかりません"}
    body_field, _ = found
    await body_field.click()
    # 段落ごとに入れる。まとめて type すると改行が段落にならないことがある
    for index, line in enumerate(body.split("\n")):
        if index:
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(PARAGRAPH_PAUSE_MS)
        if line:
            await page.keyboard.type(line, delay=TYPE_DELAY_MS)

    # **浮遊ツールバーをどける。** 本文を打った直後は note の書式ツールバーが
    # 出ていて、狭い窓では「下書き保存」に重なりクリックを横取りする
    # （2026-09-05、4分割で実際に落ちた）。選択を外してから押す
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)
    found = await _first_visible(page, DRAFT_BUTTON_SELECTORS, 5000)
    if found is None:
        return {"ok": False, "error": "no_draft_button", "url": page.url,
                "message": "下書き保存のボタンが見つかりません"}
    button, _ = found
    await button.click()
    # 保存されると編集URL（/notes/<key>/edit）に落ち着く。少し待って現況を返す
    await page.wait_for_timeout(4000)
    return {"ok": True, "url": page.url, "title": title}


async def login_by_hand(profile_dir: Path | None = None) -> bool:
    """**Playwright を噛ませずに**素の Chrome で開き、本人にログインしてもらう。

    Google のログインは自動操作されたブラウザ（CDP が繋がった状態）を弾く
    ―「このブラウザまたはアプリは安全でない可能性があります」（2026-09-05、実機）。
    素の Chrome として同じプロファイルを開けば普通にログインでき、
    クッキーはプロファイルに残るので、以後は自動操作側がそれを使える。

    プロファイルは1プロセスしか掴めないので、**ここでは Playwright を開かない。**
    ウィンドウを閉じてもらってから確かめる。
    """
    profile = profile_dir or PROFILE_DIR
    profile.mkdir(parents=True, exist_ok=True)
    print("素のChromeで開きます。noteにログインしたら、そのウィンドウを閉じてください", flush=True)
    process = await asyncio.create_subprocess_exec(
        CHROME_BINARY, f"--user-data-dir={profile}", *MANUAL_ARGS, LOGIN,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await process.wait()
    # 閉じたあとで、自動操作側から見てログイン済みかを確かめる（ここが本番の見え方）
    browser = VisibleBrowser(profile_dir=profile)
    try:
        page = await browser.page()
        ok = await logged_in(page)
    finally:
        await browser.close()
    print("ログインを確認しました" if ok else "まだログインできていません", flush=True)
    return ok


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="note_draft")
    sub = parser.add_subparsers(dest="command", required=True)
    login = sub.add_parser("login")
    login.add_argument("--wait", type=int, default=LOGIN_WAIT_S,
                       help="手で入れ終わるのを待つ秒数")
    # Google のログインは自動操作を弾くので、素の Chrome で開く道を用意する
    login.add_argument("--by-hand", action="store_true",
                       help="Playwrightを噛ませず素のChromeで開く（Googleログイン用）")
    draft = sub.add_parser("draft")
    draft.add_argument("--title", required=True)
    draft.add_argument("--body-file", required=True)
    # 見えることが要件なので、CLI から試すときは保存後もしばらく開けておく
    draft.add_argument("--keep-open", type=int, default=60, help="保存後に開けておく秒数")
    # 置き場所（2026-09-05、本人の希望：分割なし／2分割／4分割を臨機応変に）
    draft.add_argument("--layout", default=None, choices=sorted(LAYOUTS),
                       help="窓の置き場所。既定は full")
    args = parser.parse_args(argv)

    browser = VisibleBrowser(layout=getattr(args, "layout", None))
    try:
        if args.command == "login":
            if args.by_hand:
                return 0 if await login_by_hand() else 1
            return 0 if await wait_for_login(browser, args.wait) else 1
        if args.layout:
            await browser.set_layout(args.layout)
        body = Path(args.body_file).read_text(encoding="utf-8")
        result = await create_draft(browser, args.title, body)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        await asyncio.sleep(args.keep_open)
        return 0 if result.get("ok") else 1
    finally:
        # **閉じない。** 開いたままにするのが要件（本人の指定）。
        # ただし CLI から呼ばれた場合はプロセスが終わると道連れになるので、
        # ここでは明示的に閉じて「開きっぱなしの幽霊」を残さない
        await browser.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
