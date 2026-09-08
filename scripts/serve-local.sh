#!/usr/bin/env bash
# 外出先など、自宅LANの外でPCのブラウザだけで画面を見るための起動。
#
# .env の HOST は自分の LAN IP で固定してある。別のネットワークに
# いるとそのアドレスは自分に割り当たっていないので、サーバーは
# 「[Errno 99] cannot assign requested address」で即死する。
#
# ここでは .env を書き換えずに 127.0.0.1 で建てる。python-dotenv も Vite の
# loadEnv も既存の環境変数を上書きしないので、先に export した値が勝つ。
#   → 自宅へ戻ったら .env のまま `python -m server` / `npm run phone` に戻せばよい。
#
# 証明書は LAN IP 向けなので 127.0.0.1 では名前が一致しない。ブラウザの警告は
# 「詳細 → アクセスする」で通す。LAN内の実機確認には使わないこと。
#
# 使い方: ./scripts/serve-local.sh   （Ctrl-C で両方止まる）
set -euo pipefail

host=127.0.0.1
port=5173

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

export HOST="$host"
export ALLOWED_ORIGINS="https://$host:$port"

server_pid=
preview_pid=

# npm は node を子として起こすので、親を kill しても孫が残る。子ごと落とす。
# exec で preview を起こしてはいけない（シェルが置き換わって trap が消え、
# サーバーが取り残される。2026-08-31 に実際そうなった）。
cleanup() {
    trap - EXIT INT TERM
    for pid in "$preview_pid" "$server_pid"; do
        [ -n "$pid" ] || continue
        pkill -TERM -P "$pid" 2>/dev/null || true
        kill -TERM "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# VITE_PREVIEW=1 は ?state= で状態ごとの見た目を出すための口（README「実機確認」）
(cd apps/iphone-ui && VITE_PREVIEW=1 npx vite build)

.venv/bin/python -m server &
server_pid=$!

(cd apps/iphone-ui && npx vite preview --port "$port" --strictPort) &
preview_pid=$!

echo
echo "  ブラウザで https://$host:$port/ を開く（証明書の警告は通す）"
echo "  状態を指定するなら https://$host:$port/?state=LISTENING"
echo "  止めるときは Ctrl-C（サーバーとプレビューの両方が止まる）"
echo

# どちらかが落ちたら、もう片方も片付けて終わる（片肺で動いたままにしない）
wait -n

