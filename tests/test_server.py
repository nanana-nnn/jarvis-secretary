from pathlib import Path

from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings


SETTINGS = Settings("127.0.0.1", 8787, Path("cert"), Path("key"), ("https://phone.test",))


def test_health_reports_phase_one_connection_capabilities() -> None:
    with TestClient(create_app(SETTINGS)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "phase": 1, "connection": {"https": True, "websocket": True}}


def test_websocket_ready_and_ping() -> None:
    with TestClient(create_app(SETTINGS)) as client:
        with client.websocket_connect("/ws", headers={"origin": "https://phone.test"}) as socket:
            assert socket.receive_json()["type"] == "connection.ready"
            socket.send_json({"type": "connection.ping"})
            assert socket.receive_json()["type"] == "connection.pong"


def test_websocket_accepts_wake_candidate_log() -> None:
    with TestClient(create_app(SETTINGS)) as client:
        with client.websocket_connect("/ws", headers={"origin": "https://phone.test"}) as socket:
            assert socket.receive_json()["type"] == "connection.ready"
            socket.send_json({
                "type": "clap.candidate",
                "rms": 0.031,
                "hfRatio": 0.28,
                "riseMs": 8,
                "accepted": True,
                "reason": "wake",
            })
