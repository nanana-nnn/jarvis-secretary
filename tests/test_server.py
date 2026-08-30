from pathlib import Path

from fastapi.testclient import TestClient

from server.app import create_app, read_primary, read_scheme, read_telemetry
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
