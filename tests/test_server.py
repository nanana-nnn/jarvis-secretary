from pathlib import Path
import re

from fastapi.testclient import TestClient

from server.app import create_app, format_uptime, read_primary, read_scheme, read_telemetry
from server.config import Settings


SETTINGS = Settings("127.0.0.1", 8787, Path("cert"), Path("key"), ("https://phone.test",))
NO_SCHEME = Path("/path/that/does/not/exist/scheme.json")


def test_health_reports_phase_one_connection_capabilities() -> None:
    with TestClient(create_app(SETTINGS, NO_SCHEME)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "phase": 1, "connection": {"https": True, "websocket": True}}


def test_websocket_ready_and_ping() -> None:
    with TestClient(create_app(SETTINGS, NO_SCHEME)) as client:
        with client.websocket_connect("/ws", headers={"origin": "https://phone.test"}) as socket:
            assert socket.receive_json()["type"] == "connection.ready"
            event = socket.receive_json()
            assert event["type"] == "scheme.changed"
            assert event["scheme"] is None
            assert socket.receive_json()["type"] == "system.telemetry"
            socket.send_json({"type": "connection.ping"})
            assert socket.receive_json()["type"] == "connection.pong"


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
            event = socket.receive_json()
            assert event["type"] == "scheme.changed"
            assert event["scheme"]["mode"] == "light"
            assert event["scheme"]["primary"] == "#1b696f"
            assert socket.receive_json()["type"] == "system.telemetry"


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
            assert socket.receive_json()["scheme"]["mode"] == "light"

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


def test_websocket_accepts_wake_candidate_log() -> None:
    with TestClient(create_app(SETTINGS, NO_SCHEME)) as client:
        with client.websocket_connect("/ws", headers={"origin": "https://phone.test"}) as socket:
            assert socket.receive_json()["type"] == "connection.ready"
            event = socket.receive_json()
            assert event["type"] == "scheme.changed"
            assert event["scheme"] is None
            assert socket.receive_json()["type"] == "system.telemetry"
            socket.send_json({
                "type": "clap.candidate",
                "rms": 0.031,
                "hfRatio": 0.28,
                "riseMs": 8,
                "accepted": True,
                "reason": "wake",
            })
