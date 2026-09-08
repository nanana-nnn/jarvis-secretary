#!/usr/bin/env python
"""スマホを登録する合図を出す（DESIGN.md §13）。

    .venv/bin/python scripts/show-qr.py

5分だけ有効な合図を `state/pairing.json` へ書き、画面に URL とコードを出す。
スマホでその URL を開くと、画面が合図をトークンへ引き換えて保存する。
**登録は1回だけ。** 以後は普通に開けばつながる。

QR は `qrcode` が入っていれば出す（`.venv/bin/pip install qrcode`）。
入っていなくても、URL とコードだけで登録できる。
"""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv                                   # noqa: E402
from server.pairing import PAIRING_TTL_S, DeviceStore, PairingStore   # noqa: E402

UI_PORT = 5173


def main() -> int:
    load_dotenv()
    host = os.getenv("HOST")
    if not host or "x" in host:
        print("HOST が .env に無い（あるいは 192.168.0.x のまま）。先に .env を直す", file=sys.stderr)
        return 2

    state = Path(os.getenv("STATE_DIR") or "./state")
    code = PairingStore(state / "pairing.json").issue()
    url = f"https://{host}:{UI_PORT}/?pair={code}"

    try:
        import qrcode                                            # noqa: PLC0415
    except ImportError:
        pass
    else:
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)

    print()
    print(f"  {url}")
    print(f"  コード: {code}    （有効 {PAIRING_TTL_S // 60} 分・1回だけ）")
    print(f"  登録済みの端末: {DeviceStore(state / 'devices.json').count()} 台")
    print()
    print("  スマホでこのURLを開く。QRが出ていればカメラで読むだけでよい。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
