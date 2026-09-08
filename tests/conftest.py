"""テスト全体の前提。

**書き起こしモデルを読みに行かせない。** `create_app` は起動時にモデルの
先読みを投げる（2026-09-08）。テストで走らせるとモデルの取得と読み込みで
数百MB・数十秒を使うので、既定で切っておく。先読み自体の検証は
`tests/test_server.py` がスタブを差して行う。
"""
import os

os.environ.setdefault("STT_WARMUP", "0")
# 端末認証は既定で必須（§13）。ペアリングを通していない既存のテストが
# 全部 401 になるので、ここで切る。**認証そのものの検証は
# `tests/test_pairing.py` が auth_required=True を明示して行う。**
os.environ.setdefault("AUTH_REQUIRED", "0")
