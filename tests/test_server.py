from pathlib import Path
import re

from fastapi.testclient import TestClient

from server.app import create_app, format_uptime, read_primary, read_processes, read_scheme, read_telemetry
from server.config import Settings


SETTINGS = Settings("127.0.0.1", 8787, Path("cert"), Path("key"), ("https://phone.test",))
NO_SCHEME = Path("/path/that/does/not/exist/scheme.json")


def receive_until(socket, wanted: str, limit: int = 8) -> dict:
    """指定の type が来るまで読み飛ばす。

    接続直後に送る種類が増えても壊れないように、順序と件数に依存させない。
    """
    for _ in range(limit):
        event = socket.receive_json()
        if event["type"] == wanted:
            return event
    raise AssertionError(f"{wanted} が {limit} 件以内に来なかった")


def test_health_reports_phase_one_connection_capabilities() -> None:
    with TestClient(create_app(SETTINGS, NO_SCHEME)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "phase": 1, "connection": {"https": True, "websocket": True}}


def test_websocket_ready_and_ping() -> None:
    with TestClient(create_app(SETTINGS, NO_SCHEME)) as client:
        with client.websocket_connect("/ws", headers={"origin": "https://phone.test"}) as socket:
            assert socket.receive_json()["type"] == "connection.ready"
            assert receive_until(socket, "scheme.changed")["scheme"] is None
            receive_until(socket, "system.telemetry")
            receive_until(socket, "system.live")
            socket.send_json({"type": "connection.ping"})
            assert receive_until(socket, "connection.pong")


def test_scheme_primary_is_sent_on_connect(tmp_path: Path) -> None:
    scheme = tmp_path / "scheme.json"
    scheme.write_text('''{"mode":"light","colours":{
      "background":"f6fafa","surfaceContainer":"e7eff0","surfaceContainerHigh":"e1eaeb",
      "onSurface":"2a3435","onSurfaceVariant":"566162","outlineVariant":"a9b4b5",
      "primary":"1b696f","onPrimary":"e8fdff","error":"a83836"
    }}''', encoding="utf-8")
    with TestClient(create_app(SETTINGS, scheme)) as client:
        with client.websocket_connect("/ws", headers={"origin": "https://phone.test"}) as socket:
            assert socket.receive_json()["type"] == "connection.ready"
            event = receive_until(socket, "scheme.changed")
            assert event["scheme"]["mode"] == "light"
            assert event["scheme"]["primary"] == "#1b696f"
            receive_until(socket, "system.telemetry")


def test_invalid_or_missing_scheme_falls_back_to_none(tmp_path: Path) -> None:
    scheme = tmp_path / "scheme.json"
    assert read_primary(scheme) is None
    scheme.write_text('{"colours":{"primary":"not-a-colour"}}', encoding="utf-8")
    assert read_primary(scheme) is None
    assert read_scheme(scheme) is None


def test_telemetry_reports_linux_host_metrics() -> None:
    telemetry = read_telemetry()
    assert telemetry["type"] == "system.telemetry"
    assert isinstance(telemetry["load"], float)
    assert 0 <= telemetry["memory"] <= 100


def test_telemetry_carries_every_field_the_fetch_panel_shows() -> None:
    """画面の fastfetch 表示は9行を実測で埋める。欠けると「…」のまま残る。"""
    telemetry = read_telemetry()
    for key in ("kernel", "uptime", "shell", "mem", "user", "hname", "distro"):
        assert isinstance(telemetry[key], str) and telemetry[key], f"{key} が空"
    assert isinstance(telemetry["pkgs"], int) and telemetry["pkgs"] > 0
    # mem は「2.32 GiB / 6.59 GiB」の形。桁数を変えると枠の桁揃えが崩れる
    assert re.fullmatch(r"\d+\.\d{2} GiB / \d+\.\d{2} GiB", str(telemetry["mem"]))


def test_uptime_matches_fastfetch_wording() -> None:
    assert format_uptime(35700) == "9 hours, 55 minutes"
    assert format_uptime(3600) == "1 hour"
    assert format_uptime(90000) == "1 day, 1 hour"
    assert format_uptime(30) == "less than a minute"


def test_scheme_change_is_pushed_without_reconnecting(tmp_path: Path) -> None:
    """壁紙・テーマを替えたとき、iPhone側が再読み込みなしで追従できること。"""
    scheme = tmp_path / "scheme.json"

    def write(mode: str, primary: str) -> None:
        scheme.write_text(f'''{{"mode":"{mode}","colours":{{
          "background":"f6fafa","surfaceContainer":"e7eff0","surfaceContainerHigh":"e1eaeb",
          "onSurface":"2a3435","onSurfaceVariant":"566162","outlineVariant":"a9b4b5",
          "primary":"{primary}","onPrimary":"e8fdff","error":"a83836"
        }}}}''', encoding="utf-8")

    write("light", "1b696f")
    with TestClient(create_app(SETTINGS, scheme)) as client:
        with client.websocket_connect("/ws", headers={"origin": "https://phone.test"}) as socket:
            assert socket.receive_json()["type"] == "connection.ready"
            assert receive_until(socket, "scheme.changed")["scheme"]["mode"] == "light"

            write("dark", "9ccfdb")  # caelestia がテーマを切り替えたのと同じこと

            # watch_scheme は1秒間隔。接続を張り直さずに次の scheme.changed が来る
            for _ in range(40):
                event = socket.receive_json()
                if event["type"] == "scheme.changed":
                    assert event["scheme"]["mode"] == "dark"
                    assert event["scheme"]["primary"] == "#9ccfdb"
                    break
            else:
                raise AssertionError("scheme.changed が再送されなかった")


def test_live_reports_only_measured_state(tmp_path: Path) -> None:
    """3段目は実測だけを出す。分からないものを 0 や False と偽らないこと。"""
    with TestClient(create_app(SETTINGS, NO_SCHEME, tmp_path)) as client:
        with client.websocket_connect("/ws", headers={"origin": "https://phone.test"}) as socket:
            live = receive_until(socket, "system.live")

    # 監視対象は必ず alive/busy の両方を持つ。欠けると画面が黙って消灯する
    for name, state in live["apps"].items():
        assert set(state) == {"alive", "busy"}, name
        assert isinstance(state["alive"], bool) and isinstance(state["busy"], bool)

    # git 管理下でない場所を渡したので、dirty を 0 と偽らず tracked=False を返す
    assert live["vault"] == {"tracked": False, "dirty": 0}

    # 接続しているのは自分だけ
    assert live["phones"] == 1


def test_busy_needs_a_previous_observation() -> None:
    """busy は CPU 時間の差分。観測が1回しかない時点で「処理中」と言わないこと。

    接続時の live には背景タスクが先に1回観測している分の差分が乗りうるので、
    保証したいのはこの関数の性質そのもの。ここで直接確かめる。
    """
    seen: dict[str, tuple[int, float]] = {}
    first = read_processes(seen)
    assert all(not state["busy"] for state in first.values())
    assert seen, "次回の差分に使う観測が残っていない"

    # 2回目以降は差分が取れるので busy が立ちうる（真偽は実機の負荷しだい）
    second = read_processes(seen)
    assert set(second) == set(first)


def test_websocket_accepts_wake_candidate_log() -> None:
    with TestClient(create_app(SETTINGS, NO_SCHEME)) as client:
        with client.websocket_connect("/ws", headers={"origin": "https://phone.test"}) as socket:
            assert socket.receive_json()["type"] == "connection.ready"
            assert receive_until(socket, "scheme.changed")["scheme"] is None
            receive_until(socket, "system.telemetry")
            socket.send_json({
                "type": "clap.candidate",
                "rms": 0.031,
                "hfRatio": 0.28,
                "riseMs": 8,
                "accepted": True,
                "reason": "wake",
            })
