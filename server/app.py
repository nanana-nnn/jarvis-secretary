import asyncio
from contextlib import asynccontextmanager, suppress
from functools import lru_cache
import json
import logging
import os
from pathlib import Path
import platform
import pwd
import re
import socket as system_socket
import subprocess
import shutil
import uuid
from time import monotonic_ns

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .agent import CodexAgent, LONG_TIMEOUT
from .audio import SpeechSplitter
from .config import Settings
from .router import route
from .transcribe import Transcriber
from . import vault as vault_reader
from .write import WriteRejected, apply_proposal


logger = logging.getLogger("uvicorn.error")

# §11 承認フロー「120秒無操作 → 自動却下」
APPROVAL_TIMEOUT_S = 120
# 長い仕事の経過を送る間隔。黙って待たせないための最低条件（2026-09-02）
PROGRESS_EVERY_S = 10
DEFAULT_SCHEME_PATH = Path.home() / ".local/state/caelestia/scheme.json"
# caelestia が今出している壁紙。配色と同じタイミングで書き換わる
DEFAULT_WALLPAPER_PATH = Path.home() / ".local/state/caelestia/wallpaper/path.txt"
# 変換済みの置き場。元は数MBのこともあるので、そのままは配らない
WALLPAPER_CACHE = Path.home() / ".cache/jarvis-secretary"
WALLPAPER_MAX = 1400          # 長辺。iPhone で見るには十分で、転送量を抑えられる
WALLPAPER_QUALITY = 72
# 判断・記録の正本（AI_RULES.md の Vault）。VAULT_PATH で差し替えられる
DEFAULT_VAULT_PATH = Path(os.getenv("VAULT_PATH") or Path.home() / "ドキュメント/Start Vault")
HEX_COLOUR = re.compile(r"^[0-9a-fA-F]{6}$")
SCHEME_KEYS = (
    "background",
    "surfaceContainer",
    "surfaceContainerHigh",
    "onSurface",
    "onSurfaceVariant",
    "outlineVariant",
    "primary",
    "onPrimary",
    "error",
)


def timestamp_ms() -> int:
    return monotonic_ns() // 1_000_000


def read_primary(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["colours"]["primary"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return f"#{value.lower()}" if isinstance(value, str) and HEX_COLOUR.fullmatch(value) else None


def read_scheme(path: Path) -> dict[str, str] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        colours = payload["colours"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None

    mode = payload.get("mode")
    if mode not in {"light", "dark"}:
        return None

    scheme = {"mode": mode}
    for key in SCHEME_KEYS:
        value = colours.get(key)
        if not isinstance(value, str) or not HEX_COLOUR.fullmatch(value):
            return None
        scheme[key] = f"#{value.lower()}"
    return scheme


def scheme_event(path: Path) -> dict[str, object]:
    return {"type": "scheme.changed", "scheme": read_scheme(path), "ts": timestamp_ms()}


def format_uptime(seconds: float) -> str:
    """fastfetch と同じ「9 hours, 55 minutes」表記。0 の単位は出さない。"""
    total = int(seconds)
    parts = []
    for count, unit in ((total // 86400, "day"), (total % 86400 // 3600, "hour"), (total % 3600 // 60, "minute")):
        if count:
            parts.append(f"{count} {unit}{'s' if count != 1 else ''}")
    return ", ".join(parts) or "less than a minute"


@lru_cache(maxsize=1)
def static_facts() -> dict[str, str]:
    """再起動するまで変わらない項目。毎回読み直さない。"""
    facts = {"kernel": platform.release(), "hname": system_socket.gethostname(), "shell": "?", "user": "?", "distro": "?"}
    try:
        entry = pwd.getpwuid(os.getuid())
        facts["user"] = entry.pw_name
        # $SHELL は起動元（Claude Code なら zsh）を指すので passwd のログインシェルを見る
        facts["shell"] = Path(entry.pw_shell).name
    except (KeyError, OSError):
        pass
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                facts["distro"] = line.split("=", 1)[1].strip().strip('"')
                break
    except OSError:
        pass
    return facts


def read_packages() -> int:
    """fastfetch の packages {all} と同じ数。

    pacman だけだと合わない。fastfetch は ~/Applications の AppImage も数えるので、
    実機では pacman 1490 + appimage 2 = 1492 になる（`fastfetch --structure packages`
    で確認）。pacman の数は `pacman -Q | wc -l` と一致する。
    """
    total = 0
    try:
        total += sum(1 for entry in Path("/var/lib/pacman/local").iterdir() if entry.is_dir())
    except OSError:
        pass
    try:
        total += sum(1 for entry in (Path.home() / "Applications").iterdir()
                     if entry.is_file() and entry.suffix.lower() == ".appimage")
    except OSError:
        pass
    return total


# 3段目に出す「生きているもの」。名前は /proc/<pid>/comm と cmdline の両方で見る
# （electron 系は comm が "obsidian" にならないことがあるため）。
# ここに嘘を混ぜない。検出できないものは足さないこと。
WATCHED = (
    ("obsidian", ("obsidian",)),
    ("codex", ("codex",)),
    ("claude", ("claude",)),
    ("chrome", ("chrome", "chromium")),
    ("term", ("foot", "kitty", "alacritty")),
)


def read_processes(seen: dict[str, tuple[int, float]]) -> dict[str, dict[str, object]]:
    """監視対象ごとに、動いているか（alive）と処理中か（busy）を返す。

    busy は CPU 時間の増え方で見る。前回の観測との差分が要るので、
    最初の1回は必ず False になる（起動直後に「処理中」と嘘をつかないため）。

    `seen` は呼び出し側が持つ。モジュール変数にすると別インスタンスへ状態が
    漏れて「初回は False」が保証できなくなる（テストで実際に破れた）。
    """
    ticks = os.sysconf("SC_CLK_TCK")
    now = monotonic_ns() / 1e9
    totals = {name: 0 for name, _ in WATCHED}
    found = {name: False for name, _ in WATCHED}

    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip().lower()
            cmdline = (entry / "cmdline").read_bytes().decode("utf-8", "ignore").replace("\0", " ").lower()
            stat = (entry / "stat").read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        haystack = f"{comm} {cmdline}"
        for name, needles in WATCHED:
            if not any(n in haystack for n in needles):
                continue
            found[name] = True
            # stat は comm に空白を含みうるので、必ず最後の ')' より後ろを読む
            fields = stat[stat.rfind(")") + 2:].split()
            with suppress(IndexError, ValueError):
                totals[name] += int(fields[11]) + int(fields[12])  # utime + stime

    result: dict[str, dict[str, object]] = {}
    for name, _ in WATCHED:
        busy = False
        previous = seen.get(name)
        if previous is not None:
            elapsed = now - previous[1]
            if elapsed > 0:
                # 1コアの5%以上を使っていたら「処理中」とみなす
                busy = (totals[name] - previous[0]) / ticks / elapsed > 0.05
        seen[name] = (totals[name], now)
        result[name] = {"alive": found[name], "busy": busy and found[name]}
    return result


def read_vault(vault: Path) -> dict[str, object]:
    """Vault が git 管理下にあるか、未コミットが何件あるか。数えられなければ触れない。"""
    head = vault / ".git"
    if not head.exists():
        return {"tracked": False, "dirty": 0}
    dirty = 0
    try:
        # git を呼ばずに済ませたいが、状態の正確さは git にしか出せない
        out = subprocess.run(["git", "-C", str(vault), "status", "--porcelain"],
                             capture_output=True, text=True, timeout=5)
        dirty = len([line for line in out.stdout.splitlines() if line.strip()])
    except (OSError, subprocess.SubprocessError):
        return {"tracked": True, "dirty": -1}  # 数えられなかった。0 と偽らない
    return {"tracked": True, "dirty": dirty}


def dirty_paths(vault: Path) -> set[str] | None:
    """§11-1 実行前の `git status --porcelain`。ユーザーの既存変更を識別するために使う。

    数えられなかったときは空集合ではなく None を返す。「dirty が無い」と
    「調べられなかった」を同じ値にすると、警告を出すべき場面で黙ってしまう。
    -z なので core.quotepath による引用が入らず、日本語パスもそのまま取れる。
    """
    if not (vault / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "-C", str(vault), "status", "--porcelain=v1", "-z"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    entries = out.stdout.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.add(entry[3:])
        # R/C は「移動元」が次のエントリに続く。両方ユーザーの変更として数える
        if entry[0] in ("R", "C"):
            if index < len(entries) and entries[index]:
                paths.add(entries[index])
            index += 1
    return paths


def wallpaper_source() -> Path | None:
    """caelestia が今出している壁紙の実体パス。読めなければ None。"""
    try:
        raw = DEFAULT_WALLPAPER_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    source = Path(raw)
    return source if source.is_file() else None


def wallpaper_version(source: Path | None) -> str:
    """壁紙が変わったことを一意に表す札。パスと更新時刻から作る。"""
    if source is None:
        return ""
    try:
        stamp = source.stat().st_mtime_ns
    except OSError:
        return ""
    import hashlib
    return hashlib.sha256(f"{source}:{stamp}".encode()).hexdigest()[:16]


def wallpaper_webp(source: Path | None, version: str) -> Path | None:
    """壁紙を iPhone 向けの WebP に落として返す。同じ版があれば作り直さない。

    元は数MBになることがある。PNG のまま置いて初回表示が固まった事故があるので
    （2026-08-29、2枚で 6.3MB）、必ず縮めてから配る。
    """
    if source is None or not version:
        return None
    WALLPAPER_CACHE.mkdir(parents=True, exist_ok=True)
    out = WALLPAPER_CACHE / f"wallpaper-{version}.webp"
    if out.is_file():
        return out
    try:
        subprocess.run(
            ["magick", str(source), "-auto-orient",
             "-resize", f"{WALLPAPER_MAX}x{WALLPAPER_MAX}>",
             "-quality", str(WALLPAPER_QUALITY), str(out)],
            check=True, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # 古い版を片付ける（壁紙を変えるたびに溜まるため）
    for stale in WALLPAPER_CACHE.glob("wallpaper-*.webp"):
        if stale != out:
            with suppress(OSError):
                stale.unlink()
    return out if out.is_file() else None


def read_telemetry() -> dict[str, object]:
    used_ratio, used_gib, total_gib, uptime_seconds = 0.0, 0.0, 0.0, 0.0
    try:
        memory = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0])
        # fastfetch と同じ「total - available」を使用量とする（used+buff/cache ではない）
        total_kib, available_kib = memory["MemTotal"], memory["MemAvailable"]
        used_ratio = 100 * (1 - available_kib / total_kib)
        used_gib, total_gib = (total_kib - available_kib) / 1048576, total_kib / 1048576
        uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        pass
    return {
        "type": "system.telemetry",
        "load": round(os.getloadavg()[0], 2),
        "memory": round(used_ratio, 1),
        "uptime": format_uptime(uptime_seconds),
        "mem": f"{used_gib:.2f} GiB / {total_gib:.2f} GiB",
        "pkgs": read_packages(),
        **static_facts(),
        "host": system_socket.gethostname(),
        "ts": timestamp_ms(),
    }


def create_app(settings: Settings | None = None, scheme_path: Path = DEFAULT_SCHEME_PATH,
               vault_path: Path = DEFAULT_VAULT_PATH) -> FastAPI:
    config = settings or Settings.from_env()
    clients: set[WebSocket] = set()
    # busy 判定に使う直前の CPU 時間。アプリ単位で持つ（モジュール変数にしない）
    cpu_seen: dict[str, tuple[int, float]] = {}
    # 書き起こしはモデルを常駐させるのでアプリに1つだけ持つ（§8）
    transcriber = Transcriber()
    # エージェントは同時1ジョブ（§10）。アプリで1つ持って直列化する
    agent = CodexAgent(vault_path)
    # どのバックエンドで動いているかは起動ログでしか分からない（.env は
    # 実行時に load_dotenv で読むので /proc/<pid>/environ には出ない）
    logger.info("[AGENT] %s", agent.command)
    logger.info("[AGENT] sandbox read=%s write=%s", agent.sandbox_read, agent.sandbox_write)
    pending: dict[str, dict[str, object]] = {}

    def operation_log(entry: dict[str, object]) -> None:
        """Append-only audit log outside the Vault (DESIGN.md §11)."""
        path = Path(config.log_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": timestamp_ms(), **entry}, ensure_ascii=False) + "\n")

    def discard(job: dict[str, object]) -> None:
        """Drop the proposal copy. The real Vault was never touched, so there is nothing to undo."""
        timer = job.get("timer")
        if isinstance(timer, asyncio.Task):
            timer.cancel()
        proposal = job["proposal"]
        if isinstance(proposal, Path):
            shutil.rmtree(proposal.parent, ignore_errors=True)

    async def resolve_pending(job_id: str, approve: bool) -> dict[str, object]:
        job = pending.pop(job_id, None)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown or expired job")
        proposal = job["proposal"]
        assert isinstance(proposal, Path)
        timer = job.get("timer")
        if isinstance(timer, asyncio.Task):
            timer.cancel()
        try:
            if not approve:
                operation_log({"intent": job["intent"], "text": job["text"], "changed_files": job["changed_files"],
                               "approved": False, "reason": "rejected"})
                return {"job_id": job_id, "applied": False, "summary": "変更を破棄しました。", "spoken_reply": "変更を破棄しました。"}
            originals = job["original_contents"]
            assert isinstance(originals, dict)
            for relative, original in originals.items():
                target = vault_path / str(relative)
                current = target.read_bytes() if target.is_file() else None
                if current != original:
                    operation_log({"intent": job["intent"], "text": job["text"], "changed_files": job["changed_files"],
                                   "approved": False, "reason": "conflict", "conflict": str(relative)})
                    raise HTTPException(status_code=409, detail="VAULT_DIRTY: target changed after proposal")
            changed = job["changed_files"]
            assert isinstance(changed, list)
            apply_proposal(vault_path, proposal, [str(path) for path in changed])
            operation_log({"intent": job["intent"], "text": job["text"], "changed_files": changed,
                           "approved": True, "warnings": job.get("warnings", [])})
            return {"job_id": job_id, "applied": True, "summary": job["summary"], "spoken_reply": job["spoken_reply"]}
        except WriteRejected as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            shutil.rmtree(proposal.parent, ignore_errors=True)

    async def auto_reject(job_id: str, socket: WebSocket) -> None:
        """§11「120秒無操作 → 自動却下」。提案は破棄し、端末にも結果を返す。

        タイマーを置かないと、提案の Vault コピーが temp に残り続ける。
        承認画面を開いたまま端末が寝る／離れるのは常設端末では普通に起きる。
        """
        try:
            await asyncio.sleep(APPROVAL_TIMEOUT_S)
        except asyncio.CancelledError:
            return
        job = pending.pop(job_id, None)
        if job is None:
            return
        operation_log({"intent": job["intent"], "text": job["text"], "changed_files": job["changed_files"],
                       "approved": False, "reason": "timeout"})
        discard(job)
        with suppress(Exception):
            await socket.send_json({
                "type": "agent.completed", "intent": job["intent"], "job_id": job_id, "applied": False,
                "summary": "確認がなかったので変更を破棄しました。",
                "spoken_reply": "確認がなかったので変更を破棄しました。",
                "sources": [], "took": 0, "ts": timestamp_ms(),
            })

    async def watch_scheme() -> None:
        previous = read_scheme(scheme_path)
        previous_paper = wallpaper_version(wallpaper_source())
        while True:
            scheme = read_scheme(scheme_path)
            if scheme != previous:
                previous = scheme
                event = scheme_event(scheme_path)
                for client in tuple(clients):
                    with suppress(RuntimeError, WebSocketDisconnect):
                        await client.send_json(event)

            # 壁紙は配色と同じタイミングで変わる。版が変われば作り直して知らせる
            paper = wallpaper_version(wallpaper_source())
            if paper != previous_paper:
                previous_paper = paper
                event = wallpaper_event()
                for client in tuple(clients):
                    with suppress(RuntimeError, WebSocketDisconnect):
                        await client.send_json(event)
            await asyncio.sleep(1)

    def wallpaper_event() -> dict[str, object]:
        source = wallpaper_source()
        version = wallpaper_version(source)
        # 変換に失敗したら version を空で返す。壁紙なしとして扱わせる
        ready = wallpaper_webp(source, version) is not None
        return {"type": "wallpaper.changed", "version": version if ready else "", "ts": timestamp_ms()}

    def live_event() -> dict[str, object]:
        """3段目に出す「今どうなっているか」。すべて実測。数えられないものは出さない。

        重い処理（/proc の全走査と git status）が入るので、5秒間隔の
        テレメトリと同じ便に乗せて回数を増やさない。
        """
        return {
            "type": "system.live",
            "apps": read_processes(cpu_seen),
            "vault": read_vault(vault_path),
            "phones": len(clients),   # 実際に繋がっている台数。サーバーが持っている
            "ts": timestamp_ms(),
        }

    async def push_telemetry() -> None:
        while True:
            events = (read_telemetry(), live_event())
            for client in tuple(clients):
                for event in events:
                    with suppress(RuntimeError, WebSocketDisconnect):
                        await client.send_json(event)
            await asyncio.sleep(5)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = config
        # 承認待ちの一覧。承認は WS ではなく HTTP で来るので、外から見える所に置く
        app.state.pending = pending
        watcher = asyncio.create_task(watch_scheme())
        telemetry = asyncio.create_task(push_telemetry())
        try:
            yield
        finally:
            watcher.cancel()
            telemetry.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            with suppress(asyncio.CancelledError):
                await telemetry

    app = FastAPI(title="JARVIS Secretary", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.post("/jobs/{job_id}/approve")
    async def approve(job_id: str) -> dict[str, object]:
        return await resolve_pending(job_id, approve=True)

    @app.post("/jobs/{job_id}/reject")
    async def reject(job_id: str) -> dict[str, object]:
        return await resolve_pending(job_id, approve=False)

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "phase": 1, "connection": {"https": True, "websocket": True}}

    @app.get("/wallpaper.webp")
    async def wallpaper() -> Response:
        source = wallpaper_source()
        out = wallpaper_webp(source, wallpaper_version(source))
        if out is None:
            return Response(status_code=404)
        # 版ごとに別URLで取りに来るので、長く持たせてよい
        return FileResponse(out, media_type="image/webp",
                            headers={"Cache-Control": "public, max-age=604800, immutable"})

    @app.websocket("/ws")
    async def websocket_endpoint(socket: WebSocket) -> None:
        origin = socket.headers.get("origin")
        if config.allowed_origins and origin not in config.allowed_origins:
            await socket.close(code=1008, reason="origin not allowed")
            return
        await socket.accept()
        clients.add(socket)

        async def emit(payload: dict) -> bool:
            """切れたソケットへの送信で例外を上げない。

            エージェントは20〜40秒かかるので、返ってきた時点で端末が
            再接続済み＝この socket が閉じていることがある。そこで
            RuntimeError が出るとハンドラごと落ち、提案が捨てられる
            （2026-09-01 実機）。送れたかどうかだけ返す。
            """
            try:
                await socket.send_json(payload)
                return True
            except (RuntimeError, WebSocketDisconnect):
                return False

        await emit({"type": "connection.ready", "ts": timestamp_ms()})
        await emit(scheme_event(scheme_path))
        await emit(wallpaper_event())
        await emit(read_telemetry())
        await emit(live_event())
        # §12「binary フレーム = 16kHz mono Int16 PCM」「text フレーム = JSON」
        splitter = SpeechSplitter()
        was_speaking = False
        # 書き起こしとエージェントは受信ループの中で待たない。20〜40秒のあいだ
        # socket.receive() が呼ばれないと、送られ続ける音声フレームが溜まって
        # 接続が切れ、端末が再接続して STANDBY へ戻る（2026-09-01 実機）
        job: asyncio.Task | None = None
        # 走っているエージェント。「やめて」で止めるためにここへ出しておく
        agent_task: asyncio.Task | None = None

        async def finish(utterance) -> None:
            """確定した発話を書き起こして返す。失敗は黙って捨てず理由を送る。"""
            logger.info("[STT] utterance %dms (%s)", utterance.ms, utterance.reason)
            result = await transcriber.transcribe(utterance.pcm)
            if result is None:
                await emit({
                    "type": "system.error", "code": "STT_UNAVAILABLE",
                    "message": transcriber.error or "model not loaded",
                    "retryable": False, "ts": timestamp_ms(),
                })
                return
            logger.info("[STT] %dms → %r", result.ms, result.text[:60])
            if not result.text:
                # §17「聞き取れませんでした」と返して LISTENING へ戻す
                await emit({
                    "type": "system.error", "code": "STT_FAILED",
                    "message": "聞き取れませんでした", "retryable": True, "ts": timestamp_ms(),
                })
                return
            await emit({
                "type": "audio.final", "text": result.text,
                "ms": utterance.ms, "took": result.ms, "ts": timestamp_ms(),
            })
            await respond(result.text)

        async def respond(text: str) -> None:
            """用件を判定して答える（§9）。決まった問いは即答、それ以外は Codex。"""
            decision = route(text)
            logger.info("[ROUTE] %s/%s matched=%r direct=%s",
                        decision.intent, decision.mode, decision.matched, decision.direct)

            # §9「SYSTEM を最優先で判定する（エージェントを起動しない）」
            if decision.intent == "SYSTEM":
                await emit({"type": "session.sleep", "reason": "system", "ts": timestamp_ms()})
                return

            # 決まった問いはファイルを読むだけで返す。Codex は実測 42.6 秒かかる
            if decision.direct:
                found = vault_reader.answer(vault_path, decision.direct)
                if found is not None:
                    await emit({
                        "type": "agent.completed", "intent": decision.intent,
                        "summary": found.summary, "spoken_reply": found.spoken_reply,
                        "sources": found.sources, "took": 0, "ts": timestamp_ms(),
                    })
                    return

            # ここから先は時間がかかる。待たせると分かるよう先に知らせる（§12）
            await emit({
                "type": "agent.started", "intent": decision.intent,
                "matched": decision.matched, "long": decision.long, "ts": timestamp_ms(),
            })
            started = timestamp_ms()
            # §11-1 実行前の状態を保存する。実行後に取ると、ユーザーが作業中に
            # 触ったぶんと区別できなくなる
            before_dirty = dirty_paths(vault_path) if decision.mode == "propose_write" else None
            # 時間のかかる用件は持ち時間を延ばす。**ただし黙って待たせない。**
            # 経過を送り続け、「やめて」で止められる状態を保つのが延長の条件
            # （2026-09-02。長い仕事ほど、途中で違うと気づいたとき止めたくなる）
            nonlocal agent_task
            agent_task = asyncio.create_task(
                agent.run(text, decision.mode, timeout=LONG_TIMEOUT if decision.long else None))
            try:
                while True:
                    done, _ = await asyncio.wait({agent_task}, timeout=PROGRESS_EVERY_S)
                    if done:
                        break
                    await emit({
                        "type": "agent.progress", "intent": decision.intent,
                        "elapsed": (timestamp_ms() - started) // 1000, "ts": timestamp_ms(),
                    })
                outcome = agent_task.result()
            except asyncio.CancelledError:
                # 「やめて」で割り込まれた。提案は作られていないので捨てるものは無い
                logger.info("[AGENT] cancelled by user (%dms)", timestamp_ms() - started)
                await emit({"type": "agent.cancelled", "intent": decision.intent, "ts": timestamp_ms()})
                return
            finally:
                agent_task = None
            took = timestamp_ms() - started
            if outcome.error:
                logger.warning("[AGENT] %s (%dms)", outcome.error, took)
                await emit({
                    "type": "system.error", "code": outcome.error.split(":")[0],
                    "message": outcome.error, "retryable": True, "ts": timestamp_ms(),
                })
                return
            if outcome.proposed_root is not None:
                # The agent changed only its temporary Vault copy.  Keep that
                # copy as the exact approval artifact; the real Vault remains
                # untouched until the HTTP approval endpoint verifies and applies it.
                job_id = uuid.uuid4().hex
                # §11-3 既にユーザーの未コミット変更があるファイルは、承認画面で警告を出す。
                # 止めはしない（判断はユーザー）が、黙って上書きさせない
                if before_dirty is None:
                    warnings = ["未コミット変更を確認できませんでした。上書き前に手元で確認してください。"]
                else:
                    warnings = [f"{name} には未コミットの変更があります。承認すると上書きされます。"
                                for name in outcome.changed_files if name in before_dirty]
                pending[job_id] = {
                    "proposal": outcome.proposed_root,
                    "original_contents": outcome.original_contents,
                    "changed_files": outcome.changed_files,
                    "intent": decision.intent,
                    "text": text,
                    "summary": outcome.summary,
                    "spoken_reply": outcome.spoken_reply,
                    "warnings": warnings,
                }
                pending[job_id]["timer"] = asyncio.create_task(auto_reject(job_id, socket))
                sent = await emit({
                    "type": "approval.required", "job_id": job_id,
                    "summary": outcome.summary, "changed_files": outcome.changed_files,
                    "diff": outcome.diff, "warnings": warnings, "ts": timestamp_ms(),
                })
                if not sent:
                    # 承認画面を出せなかった提案は残さない。押す手段が無いまま
                    # Vault 1個ぶんのコピーが temp に積まれる
                    logger.warning("[AGENT] approval could not be delivered; proposal dropped")
                    stale = pending.pop(job_id, None)
                    if stale is not None:
                        operation_log({"intent": stale["intent"], "text": stale["text"],
                                       "changed_files": stale["changed_files"],
                                       "approved": False, "reason": "undeliverable"})
                        discard(stale)
                return
            logger.info("[AGENT] %dms → %r", took, outcome.spoken_reply[:60])
            await emit({
                "type": "agent.completed", "intent": decision.intent,
                "summary": outcome.summary, "spoken_reply": outcome.spoken_reply,
                "sources": outcome.sources, "took": took, "ts": timestamp_ms(),
            })

        try:
            while True:
                packet = await socket.receive()
                if packet.get("type") == "websocket.disconnect":
                    break

                # 音声チャンク（20ms ごと）。VAD が発話の切れ目を決める
                chunk = packet.get("bytes")
                if chunk:
                    for utterance in splitter.feed(chunk):
                        if job is not None and not job.done():
                            # §10「同時実行は1ジョブ」。考えている最中のマイクは
                            # ほぼ環境音なので、待たせずに捨てる。
                            # **ただし「やめて」だけは通す。** 長い仕事ほど途中で
                            # 止めたくなるので、割り込みの口をここに開ける
                            # （2026-09-02。持ち時間を延ばした条件のひとつ）
                            if agent_task is not None and not agent_task.done():
                                heard = await transcriber.transcribe(utterance.pcm)
                                if heard is not None and heard.text and route(heard.text).intent == "SYSTEM":
                                    logger.info("[AGENT] stop requested: %r", heard.text[:40])
                                    agent_task.cancel()
                                    continue
                            logger.info("[STT] busy, dropped utterance %dms", utterance.ms)
                            continue
                        job = asyncio.create_task(finish(utterance))
                    # 話し始めたことを伝える。iPhone 側はこれで待機へ戻る
                    # タイマーを止める（話している最中に寝てしまっていた）
                    if splitter.speaking != was_speaking:
                        was_speaking = splitter.speaking
                        if was_speaking:
                            await emit({"type": "audio.speaking", "ts": timestamp_ms()})
                    continue

                text = packet.get("text")
                if not text:
                    continue
                with suppress(json.JSONDecodeError):
                    message = json.loads(text)
                    if message.get("type") == "connection.ping":
                        await emit({"type": "connection.pong", "ts": timestamp_ms()})
                    elif message.get("type") == "clap.candidate":
                        logger.info(
                            "[WAKE] rms=%.3f hf=%.2f rise=%dms accepted=%s reason=%s",
                            float(message.get("rms", 0)),
                            float(message.get("hfRatio", 0)),
                            int(message.get("riseMs", 0)),
                            bool(message.get("accepted", False)),
                            str(message.get("reason", "unknown")),
                        )
                    elif message.get("type") == "mic.health":
                        # 実機のマイクが止まったときだけ届く。原因の切り分けに使う
                        logger.warning(
                            "[MIC] stalled context=%s track=%s muted=%s revived=%s",
                            message.get("context"), message.get("track"),
                            message.get("muted"), message.get("revived"),
                        )
                    elif message.get("type") == "session.sleep":
                        # 待機へ戻ったら、言いかけを持ち越さない
                        splitter.reset()
        except WebSocketDisconnect:
            pass
        finally:
            # 切断時に話しかけていた分は書き起こさない（返す先がもう無い）
            splitter.flush()
            if job is not None and not job.done():
                job.cancel()
            clients.discard(socket)

    return app


app = create_app()
