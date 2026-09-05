"""壁紙スライダーの検証（2026-09-05、本人の指定）。

ここで確かめるのは**選択肢の作り方と安全性**であって、見た目ではない。
実際の切り替え（caelestia の起動）は環境に依存するので呼ばない。
"""
from pathlib import Path

import pytest

from server import wallpapers
from server.router import route


def _image(directory: Path, name: str, size: int = 64) -> Path:
    """中身は問わない。一覧は拡張子とサイズで見ているので、それだけ揃える。"""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"\x00" * size)
    return path


@pytest.fixture
def library(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "Wallpapers"
    monkeypatch.setattr(wallpapers, "SEARCH_DIRS", (root,))
    return root


def test_only_images_are_offered(library: Path) -> None:
    """壁紙以外を選択肢に混ぜない。"""
    _image(library, "a.jpg")
    _image(library, "b.png")
    _image(library, "c.webp")
    _image(library, "notes.txt")
    _image(library, "video.mp4")
    names = sorted(path.name for _, path in wallpapers.find_all())
    assert names == ["a.jpg", "b.png", "c.webp"]


def test_the_same_picture_is_not_offered_twice(library: Path) -> None:
    """同じ画像が複数フォルダにあることがある（過去に重複を整理した経緯あり）。
    スライダーに同じ絵が2回出ると、選んでも変わっていないように見える。"""
    _image(library, "same.jpg", size=100)
    _image(library / "sub", "same.jpg", size=100)
    _image(library / "sub", "other.jpg", size=100)
    names = sorted(path.name for _, path in wallpapers.find_all())
    assert names == ["other.jpg", "same.jpg"]


def test_a_stable_order_so_the_slider_does_not_jump(library: Path) -> None:
    """並びが毎回変わると、さっき見た絵をもう一度探せない。"""
    for name in ("c.jpg", "a.jpg", "b.jpg"):
        _image(library, name)
    first = [path.name for _, path in wallpapers.find_all()]
    assert first == sorted(first)
    assert first == [path.name for _, path in wallpapers.find_all()]


def test_only_listed_pictures_can_be_resolved(library: Path) -> None:
    """**一覧の外は選べない。** 札はパスではないので、任意のパスを送りつけても
    取り出せない（サムネイル配信とファイル切り替えの両方がここを通る）。"""
    wanted = _image(library, "ok.jpg")
    identifier = wallpapers.find_all()[0][0]
    assert wallpapers.resolve(identifier) == wanted

    assert wallpapers.resolve("deadbeefdeadbeef") is None
    assert wallpapers.resolve("../../../etc/passwd") is None
    assert wallpapers.resolve("/etc/passwd") is None
    assert wallpapers.resolve("") is None


def test_a_missing_library_is_not_an_error(tmp_path: Path, monkeypatch) -> None:
    """フォルダが無い環境でも落ちない。選択肢が空になるだけ。"""
    monkeypatch.setattr(wallpapers, "SEARCH_DIRS", (tmp_path / "nope",))
    assert wallpapers.find_all() == []


def test_the_list_is_capped(library: Path, monkeypatch) -> None:
    """指で探せる数を超えたら切る。全部配ると転送量も無駄になる。"""
    monkeypatch.setattr(wallpapers, "MAX_ITEMS", 5)
    for number in range(12):
        _image(library, f"{number:02d}.jpg", size=64 + number)
    assert len(wallpapers.find_all()) == 5


def test_wallpaper_requests_never_reach_codex_or_the_vault() -> None:
    """「壁紙変えて」は EXECUTE の「変えて」に当たると、Codex に Vault を
    書き換えさせる話になってしまう。判定の手前で捕まえること（2026-09-05）。"""
    for text in ("壁紙かえたい", "壁紙を変えて", "背景変えて", "かべがみ変えたい",
                 "背景替えたい", "はいけい変えたい",
                 # faster-whisper が実際に返した聞き間違い（2026-09-05 実機ログ）
                 "壁が見替えたい", "風が見かえたい"):
        decision = route(text)
        assert decision.intent == "WALLPAPER", text
        assert decision.mode == "read_only", f"{text} が書き込みへ回っている"
        assert decision.direct is None
