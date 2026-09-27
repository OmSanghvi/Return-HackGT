#!/usr/bin/env python3
"""SketchScape room-build runner: web "Build room in VR" -> NemoClaw -> HackGTUnity.

Contract: docs/WEB_TO_QUEST_PIPELINE.md sections 0, 1, 1b, 2 and 4. Runs on the
Unity machine (the one with HackGTUnity open in the Editor and the NemoClaw
sandbox in WSL), standard library only:

    C:/msys64/ucrt64/bin/python.exe scripts/room_build_runner.py [--once]
        [--api http://100.63.32.83:8000] [--runner-id NAME] [--poll-seconds 5]
        [--no-agent] [--skip-deploy] [--unity-project ../HackGTUnity]

Loop: ``POST /v1/internal/room-builds/claim`` -> ``syncing`` (scripts/
sync_s3_assets_to_unity.py --project-id, then the shared snapshot: GET
/v1/rooms/{p}/shared as each demo account -> HackGTUnity
Assets/SketchScape/Resources/SharedSnapshots/<p>.json + readable letter pages as
<p>/<letter_id>.png) -> ``building`` (take the Unity Editor lock, redeploy the
sandbox skills, run ``nemoclaw sketchscape agent``, confirm the room scene was
saved, release the lock) -> ``ready`` with slug + scene_path (apk_path stays
"": no Android APK, user decision 2026-09-27) | ``failed`` with a short message.
The current status is re-posted every few minutes as a heartbeat.

The runner token (``Authorization: Bearer``, the API host's
SKETCHSCAPE_NEMOCLAW_TOKEN) comes from %USERPROFILE%/.config/sketchscape/
room-runner-token or the SKETCHSCAPE_ROOM_RUNNER_TOKEN environment variable. It
is never printed or logged (every log line is redacted) and never passed to
child processes. Log: %LOCALAPPDATA%/SketchScape/room-runner.log (rotated);
per-build step output: %LOCALAPPDATA%/SketchScape/room-builds/<build_id>/.

WSL/NemoClaw rule: a wsl.exe call that runs nemoclaw never gets a Windows-side
timeout (a killed wsl.exe leaves a stale NemoClaw lock); ``timeout <sec>`` runs
inside WSL instead, and Ctrl+C in the runner window does not reach it.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import json
import logging
import logging.handlers
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

REPO = Path(__file__).resolve().parent.parent
DEFAULT_API = "http://100.63.32.83:8000"
ACCOUNTS = ("demo-alice", "demo-bob")
CA_BUNDLE = Path("C:/Program Files/Git/mingw64/etc/ssl/certs/ca-bundle.crt")
TOKEN_ENV = "SKETCHSCAPE_ROOM_RUNNER_TOKEN"
AGENT_ROOMS_DIR = "Assets/SketchScape/AgentRooms"
SNAPSHOT_DIR = "Assets/SketchScape/Resources/SharedSnapshots"
LOCK_STALE_SECONDS = 60 * 60           # contract section 0
TIMED_OUT = -1                          # run_command's code for a Python-side timeout
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

log = logging.getLogger("room_runner")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def room_slug(name: str) -> str:
    """Mirror of backend/unity_room.room_slug (the scene file compose_room writes).

    Kept in sync by scripts/test_room_build_runner.py, which compares the two.
    """
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", (name or "").strip()).strip("_-")[:60]
    return slug or "SharedRoom"


def utc_iso(ts: Optional[float] = None) -> str:
    return dt.datetime.fromtimestamp(time.time() if ts is None else ts, dt.timezone.utc).strftime(_ISO_FMT)


def parse_iso(value: Any) -> Optional[float]:
    """ISO time -> epoch seconds (naive = local time); None if unparsable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return dt.datetime.fromisoformat(value.strip()).timestamp()
    except ValueError:
        return None


def to_wsl_path(path: Path | str) -> str:
    p = str(path).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):(.*)$", p)
    return f"/mnt/{m.group(1).lower()}{m.group(2)}" if m else p


def sh_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def fmt_seconds(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}m{seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def tail_text(path: Path, lines: int = 25, max_bytes: int = 8192) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            data = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(data.replace("\r\n", "\n").replace("\r", "\n").splitlines()[-lines:])


def _one_line(text: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def read_token(env: Optional[dict] = None, home: Optional[Path] = None) -> tuple[str, str]:
    """(token, source label). The label is safe to log; the token is not."""
    env = os.environ if env is None else env
    value = (env.get(TOKEN_ENV) or "").strip()
    if value:
        return value, f"env {TOKEN_ENV}"
    base = home if home is not None else Path(env.get("USERPROFILE") or Path.home())
    path = Path(base) / ".config" / "sketchscape" / "room-runner-token"
    try:
        value = path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return "", str(path)
    return value, str(path)


class Redactor(logging.Formatter):
    """Formats a record, then removes the token from the whole text (tracebacks included)."""

    def __init__(self, secrets: list[str], fmt: str) -> None:
        super().__init__(fmt)
        self._secrets = [s for s in secrets if s]

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), self._secrets)


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}", r"\1***", text)


def setup_logging(state_dir: Path, token: str, *, console: bool = True) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "room-runner.log"
    formatter = Redactor([token], "%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    log.propagate = False
    for handler in list(log.handlers):
        log.removeHandler(handler)
        handler.close()
    file_handler = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)
    if console:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        log.addHandler(stream)
    return path


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status


class ApiClient:
    """urllib JSON client. Service calls carry the bearer token; member calls the demo header."""

    def __init__(self, base: str, token: str, runner_id: str, *, timeout: float = 30.0) -> None:
        self.base = base.rstrip("/")
        self._token = token
        self._runner_id = runner_id
        self.timeout = timeout
        self._ctx: Optional[ssl.SSLContext] = None
        if self.base.lower().startswith("https"):
            cafile = str(CA_BUNDLE) if CA_BUNDLE.is_file() else None
            self._ctx = ssl.create_default_context(cafile=cafile)

    def _request(self, method: str, path: str, *, body: Any = None, user: str = "",
                 service: bool = False) -> tuple[int, bytes, str]:
        url = path if path.startswith(("http://", "https://")) else self.base + path
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", "sketchscape-room-runner/1")
        req.add_header("Accept", "application/json, image/png, */*")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if service:
            # Unredirected: never forwarded to another host on a redirect.
            req.add_unredirected_header("Authorization", f"Bearer {self._token}")
            req.add_header("X-SketchScape-NemoClaw-Id", re.sub(r"[^A-Za-z0-9_.-]", "-", f"room-runner-{self._runner_id}"))
        if user:
            req.add_header("X-SketchScape-Dev-User", user)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            try:
                payload = exc.read()
            except OSError:
                payload = b""
            return exc.code, payload, exc.headers.get("Content-Type", "") if exc.headers else ""
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ApiError(0, f"cannot reach {self.base}: {reason}") from None

    @staticmethod
    def _detail(payload: bytes) -> str:
        text = payload.decode("utf-8", "replace")
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and "detail" in obj:
                text = obj["detail"] if isinstance(obj["detail"], str) else json.dumps(obj["detail"])
        except ValueError:
            pass
        return _one_line(text, 200)

    def json_call(self, method: str, path: str, *, body: Any = None, user: str = "",
                  service: bool = False, ok: tuple[int, ...] = (200, 201)) -> tuple[int, Any]:
        status, payload, _ = self._request(method, path, body=body, user=user, service=service)
        if status == 204:
            return status, None
        if status not in ok:
            raise ApiError(status, self._detail(payload))
        try:
            return status, json.loads(payload.decode("utf-8"))
        except ValueError:
            raise ApiError(status, "response is not JSON") from None

    def get_bytes(self, path: str, *, user: str) -> bytes:
        status, payload, _ = self._request("GET", path, user=user)
        if status != 200:
            raise ApiError(status, self._detail(payload))
        return payload

    # Runner routes (section 1)
    def claim(self, runner_id: str) -> Optional[dict]:
        _, build = self.json_call("POST", "/v1/internal/room-builds/claim", body={"runner_id": runner_id},
                                  service=True, ok=(200,))
        return build if isinstance(build, dict) and build.get("build_id") else None

    def post_status(self, build_id: str, body: dict) -> dict:
        path = f"/v1/internal/room-builds/{urllib.parse.quote(build_id, safe='')}/status"
        _, result = self.json_call("POST", path, body=body, service=True, ok=(200,))
        return result if isinstance(result, dict) else {}

    # Member routes (sections 1, 1b)
    def get_build(self, project_id: str, build_id: str, user: str) -> dict:
        path = (f"/v1/projects/{urllib.parse.quote(project_id, safe='')}/room-builds/"
                f"{urllib.parse.quote(build_id, safe='')}")
        _, result = self.json_call("GET", path, user=user, ok=(200,))
        return result if isinstance(result, dict) else {}

    def shared_view(self, project_id: str, user: str) -> dict:
        _, result = self.json_call("GET", f"/v1/rooms/{urllib.parse.quote(project_id, safe='')}/shared",
                                   user=user, ok=(200,))
        if not isinstance(result, dict):
            raise ApiError(200, "shared view is not an object")
        return result

    def project(self, project_id: str, user: str) -> dict:
        _, result = self.json_call("GET", f"/v1/projects/{urllib.parse.quote(project_id, safe='')}",
                                   user=user, ok=(200,))
        return result if isinstance(result, dict) else {}


# ---------------------------------------------------------------------------
# Unity Editor lock (contract section 0)
# ---------------------------------------------------------------------------

class LockTimeout(Exception):
    pass


class EditorLock:
    def __init__(self, path: Path, owner: str, *, stale_seconds: float = LOCK_STALE_SECONDS) -> None:
        self.path = path
        self.owner = owner
        self.stale_seconds = stale_seconds
        self.held = False

    def read(self) -> Optional[dict]:
        try:
            raw = self.path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return None
        except OSError:
            return {}
        try:
            info = json.loads(raw)
        except ValueError:
            return {}
        return info if isinstance(info, dict) else {}

    def age_seconds(self, info: Optional[dict]) -> float:
        since = parse_iso((info or {}).get("since"))
        now = time.time()
        if since is not None and since <= now + 60:
            return max(0.0, now - since)
        try:
            return max(0.0, now - self.path.stat().st_mtime)
        except OSError:
            return 0.0

    def try_acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"owner": self.owner, "since": utc_iso()}, fh)
        self.held = True
        return True

    def acquire(self, *, wait_seconds: float, poll_seconds: float,
                on_wait: Optional[Callable[[dict, float], None]] = None,
                own_prefix: str = "", own_stale_seconds: Optional[float] = None) -> None:
        deadline = time.monotonic() + wait_seconds
        while True:
            if self.try_acquire():
                return
            info = self.read()
            if info is None:
                continue  # released between our attempt and the read
            age = self.age_seconds(info)
            owner = str(info.get("owner") or "?")
            stale_after = self.stale_seconds
            if own_prefix and owner.startswith(own_prefix) and own_stale_seconds is not None:
                stale_after = min(stale_after, own_stale_seconds)  # our own leftover from a crash
            if age > stale_after:
                log.warning("removing stale Unity Editor lock (owner %r, %s old)", owner, fmt_seconds(age))
                with contextlib.suppress(FileNotFoundError):
                    self.path.unlink()
                continue
            if time.monotonic() >= deadline:
                raise LockTimeout(owner)
            if on_wait:
                on_wait(info, age)
            time.sleep(poll_seconds)

    def release(self) -> None:
        if not self.held:
            return
        self.held = False
        info = self.read()
        if info is not None and info.get("owner") != self.owner:
            log.warning("Unity Editor lock now belongs to %r; leaving it", info.get("owner"))
            return
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


# ---------------------------------------------------------------------------
# Child processes
# ---------------------------------------------------------------------------

def run_command(argv: list[str], log_path: Path, *, cwd: Optional[Path] = None, env: Optional[dict] = None,
                timeout: Optional[float] = None, wsl: bool = False) -> int:
    """Run argv with stdout+stderr appended to log_path; return the exit code.

    ``wsl=True``: no Python-side timeout, never killed from Windows, and in its
    own process group so Ctrl+C in the runner window doesn't reach it.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    flags = 0
    if wsl:
        timeout = None
        if os.name == "nt":
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    with open(log_path, "ab") as out:
        out.write(f"\n[{utc_iso()}] $ {subprocess.list2cmdline(argv)}\n".encode("utf-8"))
        out.flush()
        proc = subprocess.Popen(argv, cwd=str(cwd) if cwd else None, env=env, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT, creationflags=flags)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            out.write(f"\n[runner] timed out after {timeout:.0f}s\n".encode("utf-8"))
            return TIMED_OUT
        except KeyboardInterrupt:
            if not wsl:
                proc.kill()
            raise
        out.write(f"\n[{utc_iso()}] exit {code}\n".encode("utf-8"))
        return code


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

class StepFailed(Exception):
    def __init__(self, message: str, log_path: Optional[Path] = None) -> None:
        super().__init__(message)
        self.message = message
        self.log_path = log_path


class BuildLost(Exception):
    """The backend says another runner holds the build, or it is already terminal."""


@dataclasses.dataclass
class Config:
    api: str = DEFAULT_API
    runner_id: str = dataclasses.field(default_factory=socket.gethostname)
    token: str = ""
    repo: Path = REPO
    unity_project: Path = REPO.parent / "HackGTUnity"
    state_dir: Path = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SketchScape"
    python: str = sys.executable
    distro: str = "Ubuntu"
    sandbox: str = "sketchscape"
    poll_seconds: float = 5.0
    heartbeat_seconds: float = 240.0      # contract: at least every 5 min
    lock_wait_seconds: float = 90 * 60.0
    lock_poll_seconds: float = 15.0
    agent: bool = True
    deploy: bool = True
    sync_timeout: float = 30 * 60.0       # Python-side (no WSL involved)
    deploy_timeout: int = 900             # inside WSL
    agent_timeout: int = 2400             # inside WSL
    max_attempts: int = 2                 # resumes after a runner crash/restart
    retry_seconds: float = 2.0            # status-post retry back-off step
    keep_build_logs: int = 20

    @property
    def lock_path(self) -> Path:
        return self.state_dir / "unity-editor.lock"

    @property
    def state_path(self) -> Path:
        return self.state_dir / "room-runner-state.json"


CommandRunner = Callable[..., int]


class Runner:
    def __init__(self, cfg: Config, *, api: Optional[ApiClient] = None,
                 run: CommandRunner = run_command) -> None:
        self.cfg = cfg
        self.api = api or ApiClient(cfg.api, cfg.token, cfg.runner_id)
        self.run = run
        self._state_lock = threading.Lock()
        self._post_lock = threading.Lock()
        self._status = ""
        self._message = ""
        self._step_started = 0.0
        self._lost = threading.Event()
        self._build: dict = {}
        self._last_claim_error = ("", 0.0)

    # -- status reporting -----------------------------------------------------

    def _member_for(self, build: dict) -> str:
        requested_by = str(build.get("requested_by") or "")
        return requested_by if requested_by in ACCOUNTS else ACCOUNTS[0]

    def _post(self, status: str, message: str, *, extra: Optional[dict] = None, attempts: int = 3,
              cancelled: Optional[threading.Event] = None) -> None:
        """POST the status. Serialized, so a heartbeat in flight can never land after the next
        phase's status; ``cancelled`` (the heartbeat's stop event) drops a post that lost the race."""
        build = self._build
        body = {"runner_id": self.cfg.runner_id, "status": status, "message": message}
        body.update(extra or {})
        with self._post_lock:
            for attempt in range(1, attempts + 1):
                if cancelled is not None and cancelled.is_set():
                    return
                try:
                    self.api.post_status(build["build_id"], body)
                    return
                except ApiError as exc:
                    if exc.status == 409:
                        # 409 = another runner holds it / it is terminal. A backend with stricter
                        # transition rules (a same-status heartbeat, a resumed build going back to
                        # syncing) also answers 409 while the build is still ours: keep going then.
                        if status not in ("ready", "failed") and self._still_ours(build):
                            log.warning("backend refused status %s (%s) but the build is still ours", status, exc)
                            return
                        self._lost.set()
                        raise BuildLost(str(exc)) from None
                    if exc.status in (401, 403):
                        log.error("status %s for build %s rejected (%s): check the runner token", status,
                                  build["build_id"], exc)
                        return
                    log.warning("posting status %s (try %d/%d) failed: %s", status, attempt, attempts, exc)
                    if attempt < attempts:
                        time.sleep(min(30.0, self.cfg.retry_seconds * attempt))
            log.error("could not post status %s for build %s; continuing", status, build["build_id"])

    def _still_ours(self, build: dict) -> bool:
        try:
            current = self.api.get_build(build["project_id"], build["build_id"], self._member_for(build))
        except ApiError as exc:
            log.warning("could not re-read build %s after a 409 (%s); assuming it is still ours",
                        build["build_id"], exc)
            return True
        ours = (current.get("runner_id") in ("", self.cfg.runner_id)
                and current.get("status") not in ("ready", "failed", "requested"))
        if not ours:
            log.warning("build %s is now %s / runner %r", build["build_id"], current.get("status"),
                        current.get("runner_id"))
        return ours

    def set_status(self, status: str, message: str, *, extra: Optional[dict] = None, attempts: int = 3) -> None:
        with self._state_lock:
            self._status, self._message = status, message
            self._step_started = time.monotonic()
        log.info("build %s -> %s: %s", self._build.get("build_id"), status, message)
        self._post(status, message, extra=extra, attempts=attempts)

    def set_message(self, message: str, *, post: bool = False) -> None:
        """Change the message shown for the current status; ``post`` sends it now (else the
        next heartbeat carries it)."""
        with self._state_lock:
            self._message = message
            status = self._status
            if post:  # a new phase: its "N min so far" counts from here
                self._step_started = time.monotonic()
        if post:
            log.info("build %s (%s): %s", self._build.get("build_id"), status, message)
            self._post(status, message, attempts=2)

    def _check_lost(self) -> None:
        if self._lost.is_set():
            raise BuildLost("the backend gave this build to another runner (or ended it)")

    @contextlib.contextmanager
    def heartbeat(self) -> Iterator[None]:
        stop = threading.Event()

        def beat() -> None:
            while not stop.wait(self.cfg.heartbeat_seconds):
                with self._state_lock:
                    status, message, started = self._status, self._message, self._step_started
                minutes = int((time.monotonic() - started) // 60)
                text = f"{message} ({minutes} min so far)" if minutes >= 1 else message
                try:
                    self._post(status, text, attempts=1, cancelled=stop)
                except BuildLost as exc:
                    log.error("heartbeat: %s; this build will stop after the current step", exc)
                    return
                except Exception as exc:  # never let the heartbeat thread die noisily
                    log.warning("heartbeat failed: %s", exc)

        thread = threading.Thread(target=beat, name="room-runner-heartbeat", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=5)

    # -- crash/restart state --------------------------------------------------

    def _save_state(self, build: dict, attempt: int) -> None:
        tmp = self.cfg.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"build": build, "attempt": attempt, "since": utc_iso()}), encoding="utf-8")
        os.replace(tmp, self.cfg.state_path)

    def _load_state(self) -> Optional[dict]:
        try:
            state = json.loads(self.cfg.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return state if isinstance(state, dict) and isinstance(state.get("build"), dict) else None

    def _clear_state(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.cfg.state_path.unlink()

    # -- steps ----------------------------------------------------------------

    def _child_env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if k != TOKEN_ENV}
        env["PYTHONUTF8"] = "1"
        return env

    def _fail_step(self, code: int, what: str, log_path: Path) -> StepFailed:
        reason = "timed out" if code == TIMED_OUT else f"exit {code}"
        return StepFailed(f"{what} failed ({reason}).", log_path)

    def step_sync(self, build: dict, build_dir: Path) -> None:
        log_path = build_dir / "sync.log"
        argv = [self.cfg.python, str(self.cfg.repo / "scripts" / "sync_s3_assets_to_unity.py"),
                "--project-id", build["project_id"], "--unity-project", str(self.cfg.unity_project)]
        code = self.run(argv, log_path, cwd=self.cfg.repo, env=self._child_env(), timeout=self.cfg.sync_timeout)
        if code != 0:
            raise self._fail_step(code, "Syncing the scans from AWS", log_path)

    def write_snapshot(self, build: dict) -> tuple[list[dict], list[str]]:
        """Section 4. Returns (views, warnings); a failed account is left out, never guessed."""
        project_id = build["project_id"]
        views: list[dict] = []
        warnings: list[str] = []
        readable: dict[str, tuple[str, str]] = {}  # letter_id -> (account, texture_url)
        for account in ACCOUNTS:
            try:
                shared = self.api.shared_view(project_id, account)
            except ApiError as exc:
                warnings.append(f"shared view as {account}: {exc}")
                continue
            views.append({"account": account, "shared": shared})
            for letter in shared.get("letters") or []:
                if not isinstance(letter, dict):
                    continue
                letter_id, url = str(letter.get("letter_id") or ""), str(letter.get("texture_url") or "")
                if url and _ID_RE.match(letter_id):
                    readable.setdefault(letter_id, (account, url))
        root = self.cfg.unity_project / SNAPSHOT_DIR
        if not views:
            warnings.append("no shared view could be read; the previous snapshot (if any) was kept")
            return views, warnings
        root.mkdir(parents=True, exist_ok=True)
        snapshot = {"version": 1, "project_id": project_id, "fetched_at": utc_iso(), "views": views}
        target = root / f"{project_id}.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, target)
        pages = root / project_id
        pages.mkdir(parents=True, exist_ok=True)
        written: set[str] = set()
        for letter_id, (account, url) in sorted(readable.items()):
            try:
                data = self.api.get_bytes(url, user=account)
            except ApiError as exc:
                warnings.append(f"letter page {letter_id}: {exc}")
                continue
            if not data.startswith(b"\x89PNG"):
                warnings.append(f"letter page {letter_id}: not a PNG")
                continue
            (pages / f"{letter_id}.png").write_bytes(data)
            written.add(f"{letter_id}.png")
        for old in pages.glob("*.png"):  # pages no account may read any more
            if old.name not in written and old.stem not in readable:
                old.unlink()
                with contextlib.suppress(FileNotFoundError):
                    Path(str(old) + ".meta").unlink()
        log.info("snapshot: %s (%d view(s), %d letter page(s))", target, len(views), len(written))
        return views, warnings

    def scene_hint(self, scene_id: str) -> tuple[str, list[str]]:
        """(room type, a few object labels) for the scene, from the synced asset catalog."""
        try:
            catalog = json.loads((self.cfg.repo / "config" / "nemoclaw" / "asset-catalog.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "", []
        room_type = ""
        cut: list[str] = []
        for scene in catalog.get("scenes") or []:
            if isinstance(scene, dict) and scene.get("scene_id") == scene_id:
                analysis = scene.get("analysis") if isinstance(scene.get("analysis"), dict) else {}
                room_type = str(analysis.get("room_type") or "")
                cut = [str(a) for a in scene.get("cut_asset_ids") or []]
        labels_by_id = {str(a.get("asset_id")): str(a.get("label") or "") for a in catalog.get("assets") or []
                        if isinstance(a, dict) and a.get("upload_id") == scene_id}
        ordered = [labels_by_id[a] for a in cut if a in labels_by_id] + list(labels_by_id.values())
        labels: list[str] = []
        for label in ordered:
            if label and label != "object" and label not in labels:
                labels.append(label)
        return room_type, labels[:3]

    def build_prompt(self, build: dict, room_name: str, title: str) -> str:
        scene_id = str(build.get("scene_id") or "")
        room_type, labels = self.scene_hint(scene_id) if scene_id else ("", [])
        photo = f"the {_one_line(room_type, 60)} photo" if room_type else "the photo"
        where = f'{photo} of the project "{_one_line(title, 80)}"' if title else photo
        if scene_id:
            clause = f"scene {scene_id[:8]}"
            if labels:
                named = [f"the {label}" for label in labels]
                joined = named[0] if len(named) == 1 else ", ".join(named[:-1]) + " and " + named[-1]
                clause += f", the one with {joined}"
            where += f" ({clause})"
        parts = [f"Build an immersive Shared Room in Unity from {where}.", f"Call it {room_name}."]
        wish = _one_line(str(build.get("prompt") or ""), 1000).replace('"', "'")
        if wish:
            parts.append(f'The person who asked for it said: "{wish}"')
        parts.append("Make it a Quest room where both accounts can find their notes and letters.")
        # A 2026-09-27 build overflowed Muse Spark's context and rebuilt a finished room twice (14.5 min):
        # start from RoomKit's status, and let finalize do the Meta rig / grab / teleport setup.
        parts.append("Follow the sketchscape-unity-room skill (/sandbox/.openclaw/workspace/skills/sketchscape-unity-room/"
                     f"SKILL.md): first run status_code {room_slug(room_name)} and resume "
                     "from what is already done (never rebuild a finished room); finalize_code adds the rig, grab, "
                     "teleports, pickups and foveation, so make no meta_add_* calls.")
        return " ".join(parts)

    def _wsl(self, name: str, script: str, build_dir: Path) -> tuple[int, Path]:
        script_path = build_dir / f"{name}.sh"
        with open(script_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(script)
        log_path = build_dir / f"{name}.log"
        argv = ["wsl.exe", "-d", self.cfg.distro, "--exec", "bash", "-l", to_wsl_path(script_path)]
        return self.run(argv, log_path, cwd=self.cfg.repo, env=self._child_env(), wsl=True), log_path

    def step_deploy(self, build_dir: Path) -> None:
        script = (f"cd {sh_quote(to_wsl_path(self.cfg.repo))} && "
                  f"timeout {int(self.cfg.deploy_timeout)} bash scripts/nemoclaw-deploy-skills.sh {sh_quote(self.cfg.sandbox)}\n")
        code, log_path = self._wsl("deploy", script, build_dir)
        if code != 0:
            raise self._fail_step(code, "Deploying the NemoClaw skills", log_path)

    def step_agent(self, build: dict, prompt: str, build_dir: Path, attempt: int) -> tuple[int, Path]:
        prompt_path = build_dir / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        session = f"room-build-{build['build_id']}" + (f"-r{attempt}" if attempt > 1 else "")
        script = (f"PROMPT=\"$(cat {sh_quote(to_wsl_path(prompt_path))})\"\n"
                  f"timeout {int(self.cfg.agent_timeout)} nemoclaw {sh_quote(self.cfg.sandbox)} agent --agent main "
                  f"--session-id {sh_quote(session)} -m \"$PROMPT\"\n")
        return self._wsl("agent", script, build_dir)

    def find_scene(self, slug: str, since: float) -> Optional[str]:
        """The saved room: <slug>.unity modified after `since` (the agent's start, which is after
        the build's start), else the newest room scene saved since then (the agent chose another
        name). The Editor lock makes the agent the only Editor driver in that window."""
        rooms = self.cfg.unity_project / AGENT_ROOMS_DIR
        expected = rooms / f"{slug}.unity"
        try:
            if expected.is_file() and expected.stat().st_mtime >= since - 2:
                return slug
        except OSError:
            pass
        fresh = []
        for path in rooms.glob("*.unity") if rooms.is_dir() else []:
            with contextlib.suppress(OSError):
                if path.stat().st_mtime >= since - 2:
                    fresh.append((path.stat().st_mtime, path.stem))
        if fresh:
            other = max(fresh)[1]
            log.warning("no fresh %s.unity; the agent saved %s.unity instead, using that", slug, other)
            return other
        return None

    # -- one build ------------------------------------------------------------

    def _build_dir(self, build_id: str) -> Path:
        root = self.cfg.state_dir / "room-builds"
        root.mkdir(parents=True, exist_ok=True)
        dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
        for old in dirs[: max(0, len(dirs) - self.cfg.keep_build_logs)]:
            if old.name != build_id:
                shutil.rmtree(old, ignore_errors=True)
        path = root / build_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def process_build(self, build: dict, attempt: int = 1) -> bool:
        """Drive one claimed build to ready/failed. Returns True when it ended ready."""
        build_id, project_id = str(build.get("build_id") or ""), str(build.get("project_id") or "")
        self._build = build
        self._lost.clear()
        if not _ID_RE.match(build_id) or not _ID_RE.match(project_id):
            log.error("refusing build with unsafe ids %r / %r", build_id, project_id)
            if _ID_RE.match(build_id):
                with contextlib.suppress(BuildLost):
                    self._post("failed", "The build has an invalid project id.")
            return False
        started = time.time()
        timings: dict[str, float] = {}
        self._save_state(build, attempt)
        build_dir = self._build_dir(build_id)
        lock = EditorLock(self.cfg.lock_path, f"room-runner {self.cfg.runner_id} build {build_id}")
        log.info("=== build %s (project %s, scene %s, requested by %s, attempt %d)", build_id, project_id,
                 build.get("scene_id") or "?", build.get("requested_by") or "?", attempt)
        ok = False
        try:
            # 1. syncing: scans + scenes, then the offline snapshot
            self.set_status("syncing", "Pulling the 3D scans and photo scenes onto the Unity machine\u2026")
            with self.heartbeat():
                t = time.monotonic()
                self.step_sync(build, build_dir)
                timings["sync"] = time.monotonic() - t
                self._check_lost()
                t = time.monotonic()
                views, warnings = self.write_snapshot(build)
                timings["snapshot"] = time.monotonic() - t
            for warning in warnings:
                log.warning("snapshot: %s", warning)
            self._check_lost()
            title = ""
            for view in views:
                title = title or str(view["shared"].get("title") or "")
            if not title:
                with contextlib.suppress(ApiError):
                    title = str(self.api.project(project_id, self._member_for(build)).get("name") or "")
            room_name = _one_line(title, 60) or "Shared Room"
            slug = room_slug(room_name)
            prompt = self.build_prompt(build, room_name, title)

            # 2. building: Editor lock -> skills -> agent -> saved scene
            self.set_status("building", "Waiting for the Unity Editor\u2026")
            scene_slug: Optional[str] = None
            agent_code = 0
            with self.heartbeat():
                t = time.monotonic()

                def waiting(info: dict, age: float) -> None:
                    self.set_message(f"Waiting for the Unity Editor (in use: {_one_line(str(info.get('owner') or '?'), 60)})\u2026")

                try:
                    if self.cfg.deploy or self.cfg.agent:  # a dry run with --skip-deploy touches neither
                        lock.acquire(wait_seconds=self.cfg.lock_wait_seconds, poll_seconds=self.cfg.lock_poll_seconds,
                                     on_wait=waiting, own_prefix=f"room-runner {self.cfg.runner_id} ",
                                     own_stale_seconds=self.cfg.agent_timeout + 120)
                except LockTimeout as exc:
                    raise StepFailed(f"The Unity Editor stayed busy ({_one_line(str(exc), 60)}); try again later.") from None
                timings["lock_wait"] = time.monotonic() - t
                try:
                    if self.cfg.deploy:
                        self.set_message("Getting NemoClaw ready with the new scans\u2026", post=True)
                        t = time.monotonic()
                        self.step_deploy(build_dir)
                        timings["deploy"] = time.monotonic() - t
                        self._check_lost()
                    if self.cfg.agent:
                        self.set_message(f"Muse Spark is building \u201c{room_name}\u201d in Unity\u2026", post=True)
                        log.info("agent prompt: %s", prompt)
                        agent_started = time.time()
                        t = time.monotonic()
                        try:
                            agent_code, agent_log = self.step_agent(build, prompt, build_dir, attempt)
                        except KeyboardInterrupt:
                            # The agent keeps driving the Editor inside WSL (bounded by its own
                            # timeout), so the Editor lock stays; a restarted runner treats its
                            # own leftover lock as stale after agent_timeout + 2 min.
                            lock.held = False
                            log.warning("the NemoClaw agent keeps running in WSL (<= %ss); the Unity Editor "
                                        "lock stays until then", self.cfg.agent_timeout)
                            raise
                        timings["agent"] = time.monotonic() - t
                        summary = tail_text(agent_log, 15)
                        log.info("agent exit %s; last lines:\n%s", agent_code, summary)
                        scene_slug = self.find_scene(slug, agent_started)
                        if scene_slug is None:
                            reason = "timed out" if agent_code == 124 else f"exit {agent_code}"
                            raise StepFailed(f"Muse Spark finished ({reason}) without saving a room scene.", agent_log)
                finally:
                    lock.release()
            self._check_lost()

            # 3. ready (no APK: contract section 6)
            if self.cfg.agent and scene_slug:
                scene_path = f"{AGENT_ROOMS_DIR}/{scene_slug}.unity"
                message = f"Your room \u201c{room_name}\u201d is ready in Unity ({scene_path})."
                if agent_code != 0:
                    message += f" Muse Spark stopped early (exit {agent_code}); check the room."
                extra = {"slug": scene_slug, "scene_path": scene_path, "apk_path": ""}
            else:
                message = "Dry run: scans synced and notes snapshot written; the agent was skipped (--no-agent)."
                extra = {"slug": slug, "scene_path": "", "apk_path": ""}
            if warnings:
                message += " (The offline notes snapshot is incomplete.)"
            self.set_status("ready", message, extra=extra, attempts=8)
            ok = True
        except StepFailed as exc:
            if exc.log_path:
                log.error("step output (%s), last lines:\n%s", exc.log_path, tail_text(exc.log_path))
            with contextlib.suppress(BuildLost):
                self.set_status("failed", exc.message, attempts=8)
        except BuildLost as exc:
            log.error("build %s abandoned: %s", build_id, exc)
        except KeyboardInterrupt:
            log.warning("stopped by the operator during build %s", build_id)
            with contextlib.suppress(BuildLost, Exception):
                self.set_status("failed", "The room runner was stopped; press Build room again.", attempts=1)
            self._clear_state()
            raise
        except Exception as exc:  # a runner bug must still end the build
            log.error("runner error in build %s:\n%s", build_id, traceback.format_exc())
            with contextlib.suppress(BuildLost):
                self.set_status("failed", f"The room runner hit an error ({type(exc).__name__}).", attempts=8)
        finally:
            lock.release()
        self._clear_state()
        total = time.time() - started
        steps = ", ".join(f"{k} {fmt_seconds(v)}" for k, v in timings.items())
        log.info("=== build %s %s in %s (%s)", build_id, "ready" if ok else "not ready", fmt_seconds(total), steps)
        return ok

    # -- claiming ---------------------------------------------------------------

    def resume_if_needed(self) -> Optional[bool]:
        """A build this runner was driving when it died: resume it (bounded) or end it."""
        state = self._load_state()
        if not state:
            return None
        build, attempt = state["build"], int(state.get("attempt") or 1) + 1
        if not _ID_RE.match(str(build.get("build_id") or "")):
            self._clear_state()
            return None
        if attempt > self.cfg.max_attempts:
            log.error("build %s already restarted %d time(s); ending it", build["build_id"], attempt - 1)
            self._build = build
            with contextlib.suppress(BuildLost):
                self._post("failed", "The room runner restarted during this build; press Build room again.")
            self._clear_state()
            return False
        log.warning("resuming build %s after a runner restart (attempt %d)", build["build_id"], attempt)
        return self.process_build(build, attempt)

    def claim(self) -> Optional[dict]:
        try:
            return self.api.claim(self.cfg.runner_id)
        except ApiError as exc:
            key = f"{exc.status}"
            last_key, last_time = self._last_claim_error
            if key != last_key or time.monotonic() - last_time > 600:
                hint = ""
                if exc.status in (401, 403):
                    hint = (" (the runner token was rejected: it must equal SKETCHSCAPE_NEMOCLAW_TOKEN on the API host)")
                elif exc.status == 404:
                    hint = " (the room-build routes are not deployed on this API yet)"
                log.warning("claim failed: %s%s", exc, hint)
                self._last_claim_error = (key, time.monotonic())
            return None

    def run_once(self) -> int:
        resumed = self.resume_if_needed()
        if resumed is not None:
            return 0 if resumed else 1
        build = self.claim()
        if not build:
            log.info("no room build is waiting")
            return 2
        return 0 if self.process_build(build) else 1

    def run_forever(self) -> None:
        self.resume_if_needed()
        log.info("waiting for room builds (every %.0fs)", self.cfg.poll_seconds)
        while True:
            build = self.claim()
            if build:
                self.process_build(build)
                continue
            time.sleep(self.cfg.poll_seconds)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def single_instance(state_dir: Path) -> Iterator[bool]:
    """Hold an OS lock on room-runner.instance for the process lifetime (freed if it dies)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    fh = open(state_dir / "room-runner.instance", "a+b")
    try:
        try:
            if os.name == "nt":
                import msvcrt  # noqa: PLC0415
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl  # noqa: PLC0415
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        fh.close()


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default=os.environ.get("SKETCHSCAPE_API_BASE", DEFAULT_API),
                        help=f"API base (default {DEFAULT_API}; the https Vercel proxy works too)")
    parser.add_argument("--runner-id", default=socket.gethostname())
    parser.add_argument("--once", action="store_true", help="claim at most one build, run it, exit "
                        "(exit 0 ready, 1 failed, 2 nothing to do)")
    parser.add_argument("--no-agent", action="store_true", help="dry run: everything except the NemoClaw agent call")
    parser.add_argument("--skip-deploy", action="store_true", help="don't redeploy the sandbox skills + catalog")
    parser.add_argument("--no-apk", action="store_true", help="no-op (kept for compatibility: no APK is built)")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=240.0)
    parser.add_argument("--lock-wait-minutes", type=float, default=90.0)
    parser.add_argument("--agent-timeout", type=int, default=2400, help="seconds, enforced inside WSL")
    parser.add_argument("--unity-project", default=str(REPO.parent / "HackGTUnity"))
    parser.add_argument("--distro", default="Ubuntu")
    parser.add_argument("--sandbox", default="sketchscape")
    parser.add_argument("--python", default=sys.executable, help="Python for the sync script")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")
    token, token_source = read_token()
    state_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SketchScape"
    log_path = setup_logging(state_dir, token)
    if not token:
        log.error("no runner token: create %s (one line) or set %s", token_source, TOKEN_ENV)
        return 2
    cfg = Config(api=args.api, runner_id=args.runner_id, token=token, unity_project=Path(args.unity_project),
                 state_dir=state_dir, python=args.python, distro=args.distro, sandbox=args.sandbox,
                 poll_seconds=max(1.0, args.poll_seconds), heartbeat_seconds=max(5.0, args.heartbeat_seconds),
                 lock_wait_seconds=max(0.0, args.lock_wait_minutes * 60), agent=not args.no_agent,
                 deploy=not args.skip_deploy, agent_timeout=max(60, args.agent_timeout))
    if not (cfg.unity_project / "Assets").is_dir():
        log.error("no Unity project at %s (pass --unity-project)", cfg.unity_project)
        return 2
    with single_instance(state_dir) as alone:
        if not alone:
            log.error("another room runner is already running on this machine (%s)",
                      state_dir / "room-runner.instance")
            return 2
        log.info("room runner %s: api %s, unity %s, token from %s, log %s%s%s", cfg.runner_id, cfg.api,
                 cfg.unity_project, token_source, log_path, "" if cfg.agent else ", DRY RUN (--no-agent)",
                 "" if cfg.deploy else ", --skip-deploy")
        runner = Runner(cfg)
        try:
            if args.once:
                return runner.run_once()
            runner.run_forever()
        except KeyboardInterrupt:
            log.info("room runner stopped")
            return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
