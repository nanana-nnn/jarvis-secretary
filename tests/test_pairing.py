"""端末認証の検証（DESIGN.md §13）。

**ここだけ `auth_required=True` で建てる。** 他のテストは conftest で切ってある。
"""
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.app import create_app
from server.config import Settings
from server.pairing import PAIRING_TTL_S, DeviceStore, PairingStore


SETTINGS = Settings("127.0.0.1", 8787, Path("cert"), Path("key"), ("https://phone.test",))
NO_SCHEME = Path("/path/that/does/not/exist/scheme.json")
ORIGIN = {"origin": "https://phone.test"}


def build(tmp_path: Path) -> tuple[TestClient, PairingStore]:
    app = create_app(SETTINGS, NO_SCHEME, warmup=False, auth_required=True, state_dir=tmp_path)
    return TestClient(app), PairingStore(tmp_path / "pairing.json")


def test_pairing_code_exchanges_for_a_device_token(tmp_path: Path) -> None:
    client, pairings = build(tmp_path)
    code = pairings.issue()
    with client:
        response = client.post("/pair", json={"code": code, "name": "iPhone"})
    assert response.status_code == 200
    assert response.json()["token"], "トークンが返っていない"
    assert DeviceStore(tmp_path / "devices.json").count() == 1


def test_pairing_code_is_single_use(tmp_path: Path) -> None:
    """**外れても消える。** 総当たりで当てられないようにする。"""
    client, pairings = build(tmp_path)
    code = pairings.issue()
    with client:
        assert client.post("/pair", json={"code": code}).status_code == 200
        assert client.post("/pair", json={"code": code}).status_code == 403
        pairings.issue()
        assert client.post("/pair", json={"code": "WRONGONE"}).status_code == 403
        assert client.post("/pair", json={"code": code}).status_code == 403


def test_expired_pairing_code_is_refused(tmp_path: Path) -> None:
    """§13「有効期限 5 分」。"""
    client, pairings = build(tmp_path)
    code = pairings.issue(now=time.time() - PAIRING_TTL_S - 1)
    with client:
        assert client.post("/pair", json={"code": code}).status_code == 403


def test_websocket_needs_a_token(tmp_path: Path) -> None:
    """同じ Wi-Fi にいるだけでは繋げない。"""
    client, _ = build(tmp_path)
    with client:
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws", headers=ORIGIN):
                pass
        assert closed.value.code == 4001


def test_paired_device_can_connect(tmp_path: Path) -> None:
    client, pairings = build(tmp_path)
    code = pairings.issue()
    with client:
        token = client.post("/pair", json={"code": code}).json()["token"]
        with client.websocket_connect(f"/ws?token={token}", headers=ORIGIN) as socket:
            assert socket.receive_json()["type"] == "connection.ready"


def test_approval_needs_a_token(tmp_path: Path) -> None:
    """**承認だけは特に効かせる。** 通ると Vault が書き換わる経路。"""
    client, pairings = build(tmp_path)
    code = pairings.issue()
    with client:
        assert client.post("/jobs/none/approve").status_code == 401
        token = client.post("/pair", json={"code": code}).json()["token"]
        allowed = client.post("/jobs/none/approve", headers={"X-Device-Token": token})
        # 認証は通り、その先の「そんなジョブは無い」（approval.py の 404）まで届く。
        # **401 と 404 の別が、弾かれたのか中身が無いのかの別になる**
        assert allowed.status_code == 404, "登録済みの端末が弾かれている"


def test_images_need_a_token_in_the_query(tmp_path: Path) -> None:
    """`<img src>` はヘッダを付けられないので、合図はクエリで渡す。"""
    client, _ = build(tmp_path)
    with client:
        assert client.get("/wallpaper.webp").status_code == 401
        assert client.get("/wallpapers/whatever/thumb.webp").status_code == 401
        code = PairingStore(tmp_path / "pairing.json").issue()
        token = client.post("/pair", json={"code": code}).json()["token"]
        # 返る中身は環境しだい（壁紙がある機械なら 200、無ければ 404）。
        # ここで見たいのは**弾かれていないこと**だけ
        assert client.get(f"/wallpaper.webp?token={token}").status_code != 401


def test_health_stays_open_and_reports_pairing_state(tmp_path: Path) -> None:
    """設置の確認に使うので開けておく。**中身は固定値と件数だけ。**"""
    client, pairings = build(tmp_path)
    with client:
        assert client.get("/health").json()["auth"] == {"required": True, "devices": 0}
        client.post("/pair", json={"code": pairings.issue()})
        assert client.get("/health").json()["auth"] == {"required": True, "devices": 1}
