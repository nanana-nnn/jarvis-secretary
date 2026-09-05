"""noteの下書きをブラウザ操作で作る経路の検証（2026-09-05）。

**本物の note へはつながない。** ここで確かめるのは約束事のほうで、
DOM が今日どう書かれているかではない（それは実機で1本通して確かめる）。

守らせたいのは3つ。
  - 公開ボタンを押さない（下書き止まり。本人の指定）
  - 未ログインのときは何も作らずに戻る
  - note の画面が変わってもすぐには壊れない（掴みどころは候補から探す）
"""
import asyncio
from functools import wraps

from server import note_draft


def _sync(test):
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run


class FakeLocator:
    def __init__(self, page, selector: str, exists: bool) -> None:
        self.page, self.selector, self.exists = page, selector, exists

    @property
    def first(self):
        return self

    async def count(self) -> int:
        return 1 if self.exists else 0

    async def wait_for(self, state: str = "visible", timeout: float = 0) -> None:
        if not self.exists:
            raise TimeoutError(self.selector)

    async def click(self) -> None:
        self.page.clicked.append(self.selector)


class FakeKeyboard:
    def __init__(self, page) -> None:
        self.page = page

    async def type(self, text: str, delay: int = 0) -> None:
        self.page.typed.append(text)

    async def press(self, key: str) -> None:
        self.page.typed.append(f"<{key}>")


class FakePage:
    """存在するセレクタだけを持つ画面。"""

    def __init__(self, present: set[str], url: str = note_draft.TOP) -> None:
        self.present, self.url = present, url
        self.clicked: list[str] = []
        self.typed: list[str] = []
        self.visited: list[str] = []
        self.keyboard = FakeKeyboard(self)

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector, selector in self.present)

    async def goto(self, url: str, wait_until: str = "load") -> None:
        self.visited.append(url)
        self.url = url

    async def wait_for_timeout(self, ms: int) -> None:
        return None


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    async def page(self) -> FakePage:
        return self._page


LOGGED_IN_EDITOR = {
    note_draft.TITLE_SELECTORS[0],
    note_draft.BODY_SELECTORS[0],
    note_draft.DRAFT_BUTTON_SELECTORS[0],
}


@_sync
async def test_未ログインなら下書きを作らずに戻る() -> None:
    """ログイン導線が出ている＝未ログイン。ここで編集画面へ進むと
    中途半端な下書きが残る。**進まないこと**を確かめる。"""
    page = FakePage({note_draft.LOGGED_OUT_MARK})
    result = await note_draft.create_draft(FakeBrowser(page), "題", "本文")

    assert result["ok"] is False and result["error"] == "not_logged_in"
    assert note_draft.NEW_TEXT not in page.visited, "未ログインなのに編集画面へ進んでいる"


@_sync
async def test_公開ボタンは押さない() -> None:
    """下書き止まりが要件（2026-09-05、本人の指定）。押した先に「公開」が
    混ざっていないことを、クリック履歴で確かめる。"""
    page = FakePage(LOGGED_IN_EDITOR)
    result = await note_draft.create_draft(FakeBrowser(page), "題", "本文")

    assert result["ok"] is True
    assert page.clicked, "何も押していない"
    assert not any("公開" in selector for selector in page.clicked), page.clicked
    assert any("下書き保存" in selector for selector in page.clicked), page.clicked


@_sync
async def test_掴みどころは候補の2つ目でも通る() -> None:
    """note の DOM は変わる。1つ目が外れても次の候補で通ることを確かめる
    （1つに賭けると、改装のたびに黙って壊れる）。"""
    page = FakePage({
        note_draft.TITLE_SELECTORS[1],
        note_draft.BODY_SELECTORS[0],
        note_draft.DRAFT_BUTTON_SELECTORS[0],
    })
    result = await note_draft.create_draft(FakeBrowser(page), "題", "本文")
    assert result["ok"] is True


@_sync
async def test_本文の改行はEnterで段落にする() -> None:
    """まとめて打ち込むと改行が段落にならない。行ごとに Enter を入れる。"""
    page = FakePage(LOGGED_IN_EDITOR)
    await note_draft.create_draft(FakeBrowser(page), "題", "一行目\n二行目")

    assert page.typed == ["題", "一行目", "<Enter>", "二行目"], page.typed


@_sync
async def test_エディタが見つからなければ理由を返す() -> None:
    """黙って成功にしない。どこで外れたかを返す（§17 の失敗の見せ方に倣う）。"""
    page = FakePage(set())
    result = await note_draft.create_draft(FakeBrowser(page), "題", "本文")
    assert result["ok"] is False and result["error"] == "no_title_field"


@_sync
async def test_ログイン待ちのあいだ画面を動かさない() -> None:
    """2秒おきにトップへ遷移して確かめていたため、本人がログイン情報を
    入れている最中に画面が飛んだ（2026-09-05、実機で「リロードがかかる」）。
    待ち受け中は goto を1回も足さないことを、遷移履歴で固定する。"""
    page = FakePage({note_draft.LOGGED_OUT_MARK})

    async def advance(ms: int, _page=page) -> None:
        # 3回目の見張りで、本人がログインを終えてトップへ移った状況にする
        _page.ticks = getattr(_page, "ticks", 0) + 1
        if _page.ticks >= 3:
            _page.url = note_draft.TOP
            _page.present = set()

    page.wait_for_timeout = advance
    ok = await note_draft.wait_for_login(FakeBrowser(page), timeout_s=30)

    assert ok is True
    assert page.visited == [note_draft.LOGIN], page.visited
