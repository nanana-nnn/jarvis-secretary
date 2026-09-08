"""端末の登録（DESIGN.md §13）。

**同じ Wi-Fi にいるだけでは繋げない**ようにするための層。
CORS と Origin チェックは詐称できるので、認証にならない（公開整備のとき §13 へ書いた）。

流れは3つだけ。

1. PC で `scripts/show-qr.py` を走らせると、5分だけ有効な合図（コード）が
   `state/pairing.json` に書かれ、画面にコードと URL が出る
2. スマホが `POST /pair` にそのコードを送ると、端末トークンと引き換えになる。
   コードは1回で消える
3. 以後の WebSocket・承認・画像はそのトークンを要求する

**トークンの実値はサーバーに残さない。** 保存するのは SHA-256 だけで、
照合は `hmac.compare_digest`（比較の時間差から当てられないようにする）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import hmac
import json
import logging
import secrets
import time

logger = logging.getLogger("uvicorn.error")

# §13「有効期限 5 分」
PAIRING_TTL_S = 300
# 読み上げ・打ち込みを間違えにくい字だけ（0/O・1/I/l を入れない）
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH = 8


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _write(path: Path, payload: dict) -> None:
    """秘密を含むので、置く前に 0600 で作る。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.touch(mode=0o600, exist_ok=True)
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    tmp.replace(path)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


@dataclass
class PairingStore:
    """1回きりの合図。**ファイル越しに渡す。**

    合図を作るのは別プロセス（`scripts/show-qr.py`）なので、
    メモリに置くと server 側から見えない。
    """
    path: Path

    def issue(self, now: float | None = None) -> str:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        _write(self.path, {"code": code, "expires": (now or time.time()) + PAIRING_TTL_S})
        return code

    def consume(self, code: str, now: float | None = None) -> bool:
        """合っていれば True。**合っても外れても、その合図は使えなくなる。**"""
        saved = _read(self.path)
        self.path.unlink(missing_ok=True)
        if not saved.get("code"):
            return False
        if (now or time.time()) > float(saved.get("expires", 0)):
            logger.info("[PAIR] 期限切れの合図")
            return False
        return hmac.compare_digest(str(saved["code"]), code.strip().upper())


@dataclass
class DeviceStore:
    """登録済み端末。実値は持たず、ハッシュだけ持つ。"""
    path: Path

    def register(self, name: str = "") -> str:
        token = secrets.token_urlsafe(32)
        saved = _read(self.path)
        devices = list(saved.get("devices", []))
        devices.append({"hash": _hash(token), "name": name, "created": int(time.time())})
        _write(self.path, {"devices": devices})
        logger.info("[PAIR] 端末を登録した（登録数 %d）", len(devices))
        return token

    def verify(self, token: str | None) -> bool:
        if not token:
            return False
        digest = _hash(token)
        return any(hmac.compare_digest(str(device.get("hash", "")), digest)
                   for device in _read(self.path).get("devices", []))

    def count(self) -> int:
        return len(_read(self.path).get("devices", []))
