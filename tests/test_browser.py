"""常駐ブラウザのウィンドウ配置（2026-09-05、実機で「画面が半分切れる」）。

**ここで確かめるのは配管。** 実際に窓が動くかはコンポジタの仕事なので、
`hyprctl` を呼ばずに、送っている命令の形だけを固定する。
実機で効く形が分かるまでに2回外している（起動引数は Wayland で無視される／
`hyprctl dispatch setfloating address:` は 0.56 では構文エラー）ので、
分かった形を戻せないようにしておく。
"""
import json

from server import browser


def _fake_hyprctl(monkeypatch, clients, sent):
    def run(command, **kwargs):
        class Result:
            stdout = json.dumps(clients) if "clients" in command else ""
        if command[:2] == ["hyprctl", "dispatch"]:
            sent.append(command[2])
        return Result()
    monkeypatch.setattr(browser.subprocess, "run", run)


def test_タイル中の窓は浮かせてから画面いっぱいにする(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(browser, "screen_size", lambda: (1600, 1000))
    monkeypatch.setattr(browser, "_chrome_pids", lambda profile: {42})
    _fake_hyprctl(monkeypatch, [{"pid": 42, "address": "0x1", "floating": False}], sent)

    assert browser.fit_window(browser.PROFILE_DIR) is True
    assert len(sent) == 3, sent
    assert "float" in sent[0]
    assert "x=1552, y=952, exact=true" in sent[1], sent[1]
    assert "x=24, y=24, exact=true" in sent[2], sent[2]


def test_すでに浮いている窓にfloatを送らない(monkeypatch) -> None:
    """float は切り替え。2回送ると元へ戻り、効いていないように見える
    （2026-09-05、実機でこれにはまった）。"""
    sent: list[str] = []
    monkeypatch.setattr(browser, "screen_size", lambda: (1600, 1000))
    monkeypatch.setattr(browser, "_chrome_pids", lambda profile: {42})
    _fake_hyprctl(monkeypatch, [{"pid": 42, "address": "0x1", "floating": True}], sent)

    browser.fit_window(browser.PROFILE_DIR)
    assert not any("float" in expression for expression in sent), sent


def test_他人の窓には触らない(monkeypatch) -> None:
    """普段の Chrome も同時に開いている。プロファイルの PID のものだけを動かす。"""
    sent: list[str] = []
    monkeypatch.setattr(browser, "screen_size", lambda: (1600, 1000))
    monkeypatch.setattr(browser, "_chrome_pids", lambda profile: {42})
    _fake_hyprctl(monkeypatch, [{"pid": 99, "address": "0xother", "floating": False}], sent)

    assert browser.fit_window(browser.PROFILE_DIR) is False
    assert sent == []


def test_Hyprland以外では何もしない(monkeypatch) -> None:
    monkeypatch.setattr(browser, "screen_size", lambda: None)
    monkeypatch.setattr(browser, "_chrome_pids", lambda profile: {42})
    assert browser.fit_window(browser.PROFILE_DIR) is False


def test_レイアウトは画面の割合から座標を出す() -> None:
    """4分割の右下は、画面の右下1/4に余白ぶん内側で入る。"""
    assert browser.geometry("full", (1600, 1000)) == (24, 24, 1552, 952)
    assert browser.geometry("left", (1600, 1000)) == (24, 24, 752, 952)
    assert browser.geometry("bottom-right", (1600, 1000)) == (824, 524, 752, 452)
    # 知らない名前で落とさない（音声から来るので、綴りが揺れても動くこと）
    assert browser.geometry("しらない", (1600, 1000)) == browser.geometry("full", (1600, 1000))


def test_通常は縮めない_極端に狭いときだけ縮める() -> None:
    """ビューポートを窓に合わせたので、4分割でも等倍で収まる（2026-09-05）。
    縮尺は「note のエディタの最低幅を割るほど狭いとき」の保険として残す。"""
    assert browser.page_zoom(1552) == 1.0          # 分割なし
    assert browser.page_zoom(752) == 1.0           # 4分割・縦2分割でも等倍
    assert browser.page_zoom(420) == 0.6           # それより狭ければ縮める
    assert browser.page_zoom(200) == browser.MIN_ZOOM   # 縮めすぎない下限
