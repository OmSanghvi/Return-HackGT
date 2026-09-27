"""Tests for scripts/room_build_runner.py (docs/WEB_TO_QUEST_PIPELINE.md section 2).

A fake backend (http.server in a thread) plays the room-build + shared-view
routes; child processes (sync, skill deploy, NemoClaw agent) are faked, and the
Unity project, state dir and repo are temp folders. No AWS, WSL or Unity.

Run with: python -m unittest scripts/test_room_build_runner.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import room_build_runner as rbr  # noqa: E402

TOKEN = "tok_" + "S3cr3tRunnerToken" * 3
PROJECT = "p1cabin"
SCENE = "3ae525c11c0b4163b2829c9951fbb1fd"
PNG_ALICE = b"\x89PNG\r\n\x1a\nalice-letter"
PNG_BOB = b"\x89PNG\r\n\x1a\nbob-letter"


def _view(viewer: str) -> dict:
    alice = viewer == "demo-alice"
    return {
        "project_id": PROJECT, "title": "Cabin living room", "viewer": viewer,
        "viewer_label": "Account 1" if alice else "Account 2",
        "accounts": [{"id": "demo-alice", "label": "Account 1", "display_name": "Alice", "color": "#e8a33d"},
                     {"id": "demo-bob", "label": "Account 2", "display_name": "Bob", "color": "#4aa3df"}],
        "notes": [{"note_id": "n1", "author": "demo-alice", "text": "Our winter trip", "upload_id": SCENE,
                   "asset_ids": ["a1"], "created_at": "2026-09-27T01:00:00Z"}],
        "letters": [
            # L1: alice -> bob, sealed; only its author may read it.
            {"letter_id": "L1", "author": "demo-alice", "recipients": ["demo-bob"], "title": "For Bob",
             "sealed": True, "can_open": not alice, "opened": False,
             "body": "Dear Bob" if alice else "", "texture_url": f"/v1/projects/{PROJECT}/letters/L1/texture" if alice else ""},
            # L2: bob -> alice, sealed; only bob may read it.
            {"letter_id": "L2", "author": "demo-bob", "recipients": ["demo-alice"], "title": "For Alice",
             "sealed": True, "can_open": alice, "opened": False,
             "body": "" if alice else "Dear Alice", "texture_url": "" if alice else f"/v1/projects/{PROJECT}/letters/L2/texture"},
        ],
        "objects": [{"asset_id": "a1", "label": "green sofa", "contributor": "demo-alice", "editable_by_me": alice}],
        "latest_build": {"build_id": "", "status": "", "slug": "", "scene_path": "", "apk_path": ""},
    }


class FakeBackend:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.queue: list[dict] = []
        self.builds: dict[str, dict] = {}
        self.posts: list[dict] = []          # status bodies, in order
        self.requests: list[tuple[str, str, dict]] = []
        self.views = {u: _view(u) for u in ("demo-alice", "demo-bob")}
        self.view_errors: dict[str, int] = {}
        self.conflict_on: set[str] = set()   # statuses answered with 409
        self.reject_same_status = False      # 409 on a repeated status (still ours)
        self.refuse: set[str] = set()        # 409 for these statuses, build still ours
        self.claim_error: tuple[int, str] | None = None
        self.status_error: tuple[int, str] | None = None

    def add_build(self, **fields) -> dict:
        build = {"build_id": "b1", "project_id": PROJECT, "requested_by": "demo-alice",
                 "prompt": "Make it feel like our winter trip, cozy by the fire.", "scene_id": SCENE,
                 "status": "requested", "message": "", "slug": "", "scene_path": "", "apk_path": "",
                 "runner_id": "", "created_at": "", "updated_at": ""}
        build.update(fields)
        self.queue.append(build)
        self.builds[build["build_id"]] = build
        return build

    def statuses(self) -> list[str]:
        """Status transitions (consecutive repeats = heartbeats collapsed)."""
        out: list[str] = []
        for body in self.posts:
            if not out or out[-1] != body["status"]:
                out.append(body["status"])
        return out


def make_handler(backend: FakeBackend):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # quiet
            pass

        def _send(self, code: int, obj=None, raw: bytes | None = None, ctype="application/json") -> None:
            data = raw if raw is not None else (b"" if obj is None else json.dumps(obj).encode())
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _service_ok(self) -> bool:
            return self.headers.get("Authorization") == f"Bearer {TOKEN}"

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            with backend.lock:
                backend.requests.append(("POST", self.path, {k.lower(): v for k, v in self.headers.items()}))
            if not self._service_ok():
                return self._send(401, {"detail": "Missing or invalid credentials."})
            if self.path == "/v1/internal/room-builds/claim":
                if backend.claim_error:
                    code, detail = backend.claim_error
                    return self._send(code, {"detail": detail})
                with backend.lock:
                    if not backend.queue:
                        return self._send(204)
                    build = backend.queue.pop(0)
                    build.update(status="claimed", runner_id=body["runner_id"])
                return self._send(200, build)
            m = re.match(r"^/v1/internal/room-builds/([^/]+)/status$", self.path)
            if m:
                with backend.lock:
                    build = backend.builds.get(m.group(1))
                    if build is None:
                        return self._send(404, {"detail": "no build"})
                    if backend.status_error:
                        code, detail = backend.status_error
                        backend.posts.append(body)
                        return self._send(code, {"detail": detail})
                    if body["status"] in backend.conflict_on:
                        build["runner_id"] = "another-runner"   # the backend re-queued + re-claimed it
                        return self._send(409, {"detail": "held by another runner"})
                    if build["status"] in ("ready", "failed"):
                        return self._send(409, {"detail": "terminal"})
                    if body["status"] in backend.refuse:
                        return self._send(409, {"detail": "transition not allowed"})
                    if backend.reject_same_status and body["status"] == build["status"]:
                        backend.posts.append(body)
                        return self._send(409, {"detail": "same status"})
                    backend.posts.append(body)
                    build.update({k: v for k, v in body.items() if k != "runner_id"})
                    build["runner_id"] = body["runner_id"]
                    return self._send(200, build)
            self._send(404, {"detail": "Not Found"})

        def do_GET(self) -> None:
            with backend.lock:
                backend.requests.append(("GET", self.path, {k.lower(): v for k, v in self.headers.items()}))
            user = self.headers.get("X-SketchScape-Dev-User", "")
            if user not in backend.views:
                return self._send(401, {"detail": "who are you"})
            if self.path == f"/v1/rooms/{PROJECT}/shared":
                if user in backend.view_errors:
                    return self._send(backend.view_errors[user], {"detail": "boom"})
                return self._send(200, backend.views[user])
            m = re.match(rf"^/v1/projects/{PROJECT}/letters/([^/]+)/texture$", self.path)
            if m:
                readable = {l["letter_id"] for l in backend.views[user]["letters"] if l["texture_url"]}
                if m.group(1) not in readable:
                    return self._send(403, {"detail": "This letter is sealed."})
                return self._send(200, raw=PNG_ALICE if m.group(1) == "L1" else PNG_BOB, ctype="image/png")
            m = re.match(rf"^/v1/projects/{PROJECT}/room-builds/([^/]+)$", self.path)
            if m and m.group(1) in backend.builds:
                return self._send(200, backend.builds[m.group(1)])
            if self.path == f"/v1/projects/{PROJECT}":
                return self._send(200, {"project_id": PROJECT, "name": "Cabin living room"})
            self._send(404, {"detail": "Not Found"})

    return Handler


class FakeCommands:
    """Stands in for run_command: records calls; the agent 'saves' a scene like RoomKit."""

    def __init__(self, test: "RunnerTestCase") -> None:
        self.t = test
        self.calls: list[dict] = []
        self.codes: dict[str, int] = {}
        self.sleep: dict[str, float] = {}
        self.save_as: str | None = "Cabin_living_room"
        self.output: dict[str, str] = {"sync": "layout preview: 6 objects\n", "deploy": "== installing ok\n",
                                       "agent": "Built and finalized the room Cabin living room.\n"}

    def __call__(self, argv, log_path, *, cwd=None, env=None, timeout=None, wsl=False) -> int:
        kind = Path(log_path).stem
        lock = self.t.cfg.lock_path
        call = {"kind": kind, "argv": list(argv), "env": dict(env or {}), "timeout": timeout, "wsl": wsl,
                "lock": json.loads(lock.read_text()) if lock.exists() else None, "at": time.time()}
        if kind in ("deploy", "agent"):
            call["script"] = (Path(log_path).parent / f"{kind}.sh").read_text(encoding="utf-8")
        if kind == "agent":
            call["prompt"] = (Path(log_path).parent / "prompt.txt").read_text(encoding="utf-8")
        self.calls.append(call)
        time.sleep(self.sleep.get(kind, 0))
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(self.output.get(kind, ""))
        if kind == "agent" and self.save_as and self.codes.get("agent", 0) in (0, 124):
            rooms = self.t.unity / rbr.AGENT_ROOMS_DIR
            rooms.mkdir(parents=True, exist_ok=True)
            (rooms / f"{self.save_as}.unity").write_text("%YAML 1.1\n", encoding="utf-8")
        return self.codes.get(kind, 0)

    def kinds(self) -> list[str]:
        return [c["kind"] for c in self.calls]


class RunnerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.unity = root / "HackGTUnity"
        (self.unity / "Assets").mkdir(parents=True)
        self.repo = root / "repo"
        (self.repo / "config" / "nemoclaw").mkdir(parents=True)
        (self.repo / "config" / "nemoclaw" / "asset-catalog.json").write_text(json.dumps({
            "assets": [
                {"asset_id": "x1", "label": "wooden table", "upload_id": SCENE},
                {"asset_id": "x2", "label": "green sofa", "upload_id": SCENE},
                {"asset_id": "x3", "label": "stone fireplace", "upload_id": SCENE},
                {"asset_id": "x4", "label": "cat", "upload_id": "otherupload"},
            ],
            "scenes": [{"scene_id": SCENE, "project_id": PROJECT, "cut_asset_ids": ["x2", "x3"],
                        "analysis": {"room_type": "cabin living room"}}],
        }), encoding="utf-8")
        self.state = root / "state"
        self.backend = FakeBackend()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.backend))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.api_base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.cfg = rbr.Config(api=self.api_base, runner_id="unity-box", token=TOKEN, repo=self.repo,
                              unity_project=self.unity, state_dir=self.state, python="python",
                              poll_seconds=0.05, heartbeat_seconds=60, lock_wait_seconds=5,
                              lock_poll_seconds=0.05, retry_seconds=0.01)
        self.log_path = rbr.setup_logging(self.state, TOKEN, console=False)
        self.commands = FakeCommands(self)

    def tearDown(self) -> None:
        for handler in list(rbr.log.handlers):
            rbr.log.removeHandler(handler)
            handler.close()
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def runner(self) -> rbr.Runner:
        return rbr.Runner(self.cfg, run=self.commands)

    def log_text(self) -> str:
        for handler in rbr.log.handlers:
            handler.flush()
        return self.log_path.read_text(encoding="utf-8")

    def ready_body(self) -> dict:
        return [b for b in self.backend.posts if b["status"] == "ready"][-1]

    def failed_body(self) -> dict:
        return [b for b in self.backend.posts if b["status"] == "failed"][-1]


class HappyPathTests(RunnerTestCase):
    def test_full_build_reaches_ready_with_scene(self) -> None:
        self.backend.add_build()
        os.environ[rbr.TOKEN_ENV] = TOKEN
        try:
            code = self.runner().run_once()
        finally:
            del os.environ[rbr.TOKEN_ENV]
        self.assertEqual(code, 0)
        self.assertEqual(self.backend.statuses(), ["syncing", "building", "ready"])
        ready = self.ready_body()
        self.assertEqual(ready["slug"], "Cabin_living_room")
        self.assertEqual(ready["scene_path"], "Assets/SketchScape/AgentRooms/Cabin_living_room.unity")
        self.assertEqual(ready["apk_path"], "")
        self.assertEqual(ready["runner_id"], "unity-box")
        self.assertIn("Cabin living room", ready["message"])
        self.assertNotIn("incomplete", ready["message"])
        self.assertEqual(self.commands.kinds(), ["sync", "deploy", "agent"])

        sync, deploy, agent = self.commands.calls
        self.assertEqual(sync["argv"][2:], ["--project-id", PROJECT, "--unity-project", str(self.unity)])
        self.assertTrue(sync["argv"][1].endswith("sync_s3_assets_to_unity.py"))
        self.assertEqual(sync["env"].get("PYTHONUTF8"), "1")
        self.assertNotIn(rbr.TOKEN_ENV, sync["env"])      # the token never reaches a child
        self.assertIsNotNone(sync["timeout"])
        self.assertFalse(sync["wsl"])
        self.assertIsNone(sync["lock"])                    # sync runs without the Editor lock
        for call in (deploy, agent):
            self.assertTrue(call["wsl"])
            self.assertEqual(call["argv"][:6], ["wsl.exe", "-d", "Ubuntu", "--exec", "bash", "-l"])
            self.assertTrue(call["argv"][6].endswith(f"{call['kind']}.sh"))
            self.assertEqual(call["lock"]["owner"], "room-runner unity-box build b1")
            self.assertIsNotNone(rbr.parse_iso(call["lock"]["since"]))
        self.assertIn("timeout 900 bash scripts/nemoclaw-deploy-skills.sh 'sketchscape'", deploy["script"])
        self.assertIn("timeout 2400 nemoclaw 'sketchscape' agent --agent main --session-id 'room-build-b1' -m \"$PROMPT\"",
                      agent["script"])
        prompt = agent["prompt"]
        self.assertIn("scene 3ae525c1", prompt)
        self.assertIn("the one with the green sofa, the stone fireplace and the wooden table", prompt)  # verified first
        self.assertIn("cabin living room photo", prompt)
        self.assertIn("Call it Cabin living room.", prompt)
        self.assertIn("Make it feel like our winter trip, cozy by the fire.", prompt)
        self.assertIn("Make it a Quest room where both accounts can find their notes and letters.", prompt)
        self.assertFalse(self.cfg.lock_path.exists())      # released
        self.assertFalse(self.cfg.state_path.exists())     # nothing to resume

    def test_snapshot_holds_each_accounts_exact_view_and_readable_pages(self) -> None:
        self.backend.add_build()
        self.assertEqual(self.runner().run_once(), 0)
        snap_dir = self.unity / rbr.SNAPSHOT_DIR
        snap = json.loads((snap_dir / f"{PROJECT}.json").read_text(encoding="utf-8"))
        self.assertEqual(snap["version"], 1)
        self.assertEqual(snap["project_id"], PROJECT)
        self.assertIsNotNone(rbr.parse_iso(snap["fetched_at"]))
        self.assertEqual([v["account"] for v in snap["views"]], ["demo-alice", "demo-bob"])
        self.assertEqual(snap["views"][0]["shared"], self.backend.views["demo-alice"])
        self.assertEqual(snap["views"][1]["shared"], self.backend.views["demo-bob"])
        self.assertEqual((snap_dir / PROJECT / "L1.png").read_bytes(), PNG_ALICE)
        self.assertEqual((snap_dir / PROJECT / "L2.png").read_bytes(), PNG_BOB)
        # Each page was fetched as an account allowed to read it (the fake answers 403 otherwise).
        textures = [(p, h.get("x-sketchscape-dev-user")) for m, p, h in self.backend.requests if p.endswith("/texture")]
        self.assertEqual(sorted(textures), [(f"/v1/projects/{PROJECT}/letters/L1/texture", "demo-alice"),
                                            (f"/v1/projects/{PROJECT}/letters/L2/texture", "demo-bob")])

    def test_auth_headers_service_vs_member(self) -> None:
        self.backend.add_build()
        self.runner().run_once()
        for method, path, headers in self.backend.requests:
            if path.startswith("/v1/internal/"):
                self.assertEqual(headers.get("authorization"), f"Bearer {TOKEN}")
                self.assertNotIn("x-sketchscape-dev-user", headers)
            else:  # member routes: demo header only, never the service token
                self.assertNotIn("authorization", headers)
                self.assertIn(headers.get("x-sketchscape-dev-user"), rbr.ACCOUNTS)

    def test_agent_that_named_the_room_differently(self) -> None:
        self.backend.add_build(prompt="Call it Cozy Cabin")
        self.commands.save_as = "Cozy_Cabin"
        self.assertEqual(self.runner().run_once(), 0)
        self.assertEqual(self.ready_body()["slug"], "Cozy_Cabin")
        self.assertEqual(self.ready_body()["scene_path"], "Assets/SketchScape/AgentRooms/Cozy_Cabin.unity")

    def test_dry_run_skips_only_the_agent(self) -> None:
        self.backend.add_build()
        self.cfg.agent = False
        self.assertEqual(self.runner().run_once(), 0)
        self.assertEqual(self.commands.kinds(), ["sync", "deploy"])
        self.assertEqual(self.backend.statuses(), ["syncing", "building", "ready"])
        ready = self.ready_body()
        self.assertEqual(ready["scene_path"], "")
        self.assertIn("Dry run", ready["message"])
        self.assertTrue((self.unity / rbr.SNAPSHOT_DIR / f"{PROJECT}.json").exists())

    def test_dry_run_without_deploy_needs_no_editor_lock(self) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        held = json.dumps({"owner": "vr-layer agent testing", "since": rbr.utc_iso()})
        self.cfg.lock_path.write_text(held, encoding="utf-8")
        self.backend.add_build()
        self.cfg.agent = False
        self.cfg.deploy = False
        self.cfg.lock_wait_seconds = 0.2
        self.assertEqual(self.runner().run_once(), 0)
        self.assertEqual(self.commands.kinds(), ["sync"])
        self.assertEqual(self.cfg.lock_path.read_text(encoding="utf-8"), held)  # untouched

    def test_skip_deploy(self) -> None:
        self.backend.add_build()
        self.cfg.deploy = False
        self.assertEqual(self.runner().run_once(), 0)
        self.assertEqual(self.commands.kinds(), ["sync", "agent"])

    def test_nothing_to_claim(self) -> None:
        self.assertEqual(self.runner().run_once(), 2)
        self.assertEqual(self.commands.calls, [])

    def test_title_falls_back_to_shared_room(self) -> None:
        for view in self.backend.views.values():
            view["title"] = ""
        self.backend.add_build(prompt="")
        self.commands.save_as = "Cabin_living_room"  # project name fallback
        self.assertEqual(self.runner().run_once(), 0)
        self.assertIn("Call it Cabin living room.", self.commands.calls[-1]["prompt"])
        self.assertNotIn("asked for it", self.commands.calls[-1]["prompt"])


class FailureTests(RunnerTestCase):
    def test_sync_failure_fails_the_build_without_touching_unity(self) -> None:
        self.backend.add_build()
        self.commands.codes["sync"] = 1
        self.commands.output["sync"] = "aws: error: credentials expired\n"
        self.assertEqual(self.runner().run_once(), 1)
        self.assertEqual(self.backend.statuses(), ["syncing", "failed"])
        self.assertEqual(self.failed_body()["message"], "Syncing the scans from AWS failed (exit 1).")
        self.assertEqual(self.commands.kinds(), ["sync"])
        self.assertFalse(self.cfg.lock_path.exists())
        self.assertIn("credentials expired", self.log_text())  # the step's tail lands in the runner log

    def test_sync_timeout_message(self) -> None:
        self.backend.add_build()
        self.commands.codes["sync"] = rbr.TIMED_OUT
        self.assertEqual(self.runner().run_once(), 1)
        self.assertEqual(self.failed_body()["message"], "Syncing the scans from AWS failed (timed out).")

    def test_deploy_failure_releases_the_lock(self) -> None:
        self.backend.add_build()
        self.commands.codes["deploy"] = 2
        self.assertEqual(self.runner().run_once(), 1)
        self.assertEqual(self.backend.statuses(), ["syncing", "building", "failed"])
        self.assertIn("Deploying the NemoClaw skills failed", self.failed_body()["message"])
        self.assertNotIn("agent", self.commands.kinds())
        self.assertFalse(self.cfg.lock_path.exists())

    def test_agent_without_a_saved_scene_fails(self) -> None:
        self.backend.add_build()
        self.commands.save_as = None
        self.commands.codes["agent"] = 124
        self.assertEqual(self.runner().run_once(), 1)
        self.assertEqual(self.failed_body()["message"], "Muse Spark finished (timed out) without saving a room scene.")
        self.assertFalse(self.cfg.lock_path.exists())

    def test_an_old_scene_file_does_not_count(self) -> None:
        rooms = self.unity / rbr.AGENT_ROOMS_DIR
        rooms.mkdir(parents=True)
        old = rooms / "Cabin_living_room.unity"
        old.write_text("old", encoding="utf-8")
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        self.backend.add_build()
        self.commands.save_as = None
        self.assertEqual(self.runner().run_once(), 1)
        self.assertIn("without saving a room scene", self.failed_body()["message"])

    def test_saved_scene_with_nonzero_agent_exit_is_ready_with_a_warning(self) -> None:
        self.backend.add_build()
        self.commands.codes["agent"] = 124
        self.assertEqual(self.runner().run_once(), 0)
        self.assertIn("stopped early (exit 124)", self.ready_body()["message"])

    def test_unexpected_runner_error_still_ends_the_build(self) -> None:
        self.backend.add_build()

        def boom(*args, **kwargs):
            raise RuntimeError("bug")

        runner = rbr.Runner(self.cfg, run=boom)
        self.assertEqual(runner.run_once(), 1)
        self.assertEqual(self.failed_body()["message"], "The room runner hit an error (RuntimeError).")
        self.assertIn("RuntimeError: bug", self.log_text())

    def test_conflict_abandons_without_posting_failed(self) -> None:
        self.backend.add_build()
        self.backend.conflict_on = {"building"}
        self.assertEqual(self.runner().run_once(), 1)
        self.assertEqual(self.backend.statuses(), ["syncing"])
        self.assertNotIn("agent", self.commands.kinds())
        self.assertFalse(self.cfg.lock_path.exists())
        self.assertIn("abandoned", self.log_text())

    def test_missing_shared_views_keep_the_previous_snapshot(self) -> None:
        snap_dir = self.unity / rbr.SNAPSHOT_DIR
        snap_dir.mkdir(parents=True)
        (snap_dir / f"{PROJECT}.json").write_text('{"version": 1, "old": true}', encoding="utf-8")
        self.backend.view_errors = {"demo-alice": 500, "demo-bob": 500}
        self.backend.add_build()
        self.assertEqual(self.runner().run_once(), 0)
        self.assertEqual(json.loads((snap_dir / f"{PROJECT}.json").read_text())["old"], True)
        self.assertIn("incomplete", self.ready_body()["message"])

    def test_one_missing_view_is_left_out_not_guessed(self) -> None:
        self.backend.view_errors = {"demo-bob": 403}
        self.backend.add_build()
        self.assertEqual(self.runner().run_once(), 0)
        snap = json.loads((self.unity / rbr.SNAPSHOT_DIR / f"{PROJECT}.json").read_text())
        self.assertEqual([v["account"] for v in snap["views"]], ["demo-alice"])
        self.assertFalse((self.unity / rbr.SNAPSHOT_DIR / PROJECT / "L2.png").exists())

    def test_pages_no_longer_readable_are_removed(self) -> None:
        pages = self.unity / rbr.SNAPSHOT_DIR / PROJECT
        pages.mkdir(parents=True)
        (pages / "GONE.png").write_bytes(b"\x89PNGold")
        (pages / "GONE.png.meta").write_text("meta", encoding="utf-8")
        self.backend.add_build()
        self.runner().run_once()
        self.assertFalse((pages / "GONE.png").exists())
        self.assertFalse((pages / "GONE.png.meta").exists())
        self.assertTrue((pages / "L1.png").exists())


class HeartbeatTests(RunnerTestCase):
    def test_long_steps_repost_the_current_status(self) -> None:
        self.backend.add_build()
        self.cfg.heartbeat_seconds = 0.1
        self.commands.sleep = {"sync": 0.65, "agent": 0.65}
        self.assertEqual(self.runner().run_once(), 0)
        syncing = [b for b in self.backend.posts if b["status"] == "syncing"]
        building = [b for b in self.backend.posts if b["status"] == "building"]
        self.assertGreaterEqual(len(syncing), 4, syncing)
        self.assertGreaterEqual(len(building), 4, building)
        self.assertTrue(any("Muse Spark is building" in b["message"] for b in building))
        self.assertEqual(self.backend.statuses(), ["syncing", "building", "ready"])

    def test_backend_rejecting_same_status_reposts_is_tolerated(self) -> None:
        self.backend.add_build()
        self.backend.reject_same_status = True
        self.cfg.heartbeat_seconds = 0.1
        self.commands.sleep = {"sync": 0.4}
        self.assertEqual(self.runner().run_once(), 0)
        self.assertEqual(self.backend.statuses(), ["syncing", "building", "ready"])

    def test_heartbeat_conflict_stops_the_build_after_the_step(self) -> None:
        build = self.backend.add_build()
        self.backend.reject_same_status = True
        self.cfg.heartbeat_seconds = 0.1

        def taken_over(*args, **kwargs):
            with self.backend.lock:
                build["runner_id"] = "someone-else"
            time.sleep(0.4)
            return 0

        runner = rbr.Runner(self.cfg, run=taken_over)
        self.assertEqual(runner.run_once(), 1)
        self.assertEqual(self.backend.statuses(), ["syncing"])  # no building, no failed


class LockTests(RunnerTestCase):
    def _hold(self, owner: str, age_seconds: float) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        self.cfg.lock_path.write_text(json.dumps({"owner": owner, "since": rbr.utc_iso(time.time() - age_seconds)}),
                                      encoding="utf-8")

    def test_waits_for_a_held_lock_then_builds(self) -> None:
        self._hold("vr-layer agent testing", 10)
        released = {}

        def release_later() -> None:
            time.sleep(0.5)
            released["at"] = time.time()
            self.cfg.lock_path.unlink()

        threading.Thread(target=release_later, daemon=True).start()
        self.backend.add_build()
        self.cfg.heartbeat_seconds = 0.1
        self.assertEqual(self.runner().run_once(), 0)
        deploy = self.commands.calls[1]
        self.assertGreaterEqual(deploy["at"], released["at"])
        self.assertEqual(deploy["lock"]["owner"], "room-runner unity-box build b1")
        self.assertTrue(any("in use: vr-layer agent testing" in b["message"] for b in self.backend.posts))
        self.assertFalse(self.cfg.lock_path.exists())

    def test_stale_lock_is_removed(self) -> None:
        self._hold("crashed tester", 2 * 3600)
        self.backend.add_build()
        self.assertEqual(self.runner().run_once(), 0)
        self.assertIn("removing stale Unity Editor lock", self.log_text())

    def test_lock_timeout_fails_and_leaves_the_foreign_lock(self) -> None:
        self._hold("vr-layer agent testing", 10)
        self.cfg.lock_wait_seconds = 0.3
        self.backend.add_build()
        self.assertEqual(self.runner().run_once(), 1)
        self.assertIn("Unity Editor stayed busy", self.failed_body()["message"])
        self.assertEqual(json.loads(self.cfg.lock_path.read_text())["owner"], "vr-layer agent testing")
        self.assertNotIn("deploy", self.commands.kinds())

    def test_own_leftover_lock_expires_after_the_agent_timeout(self) -> None:
        self._hold("room-runner unity-box build old", self.cfg.agent_timeout + 300)  # < 60 min, > agent timeout
        self.backend.add_build()
        self.assertEqual(self.runner().run_once(), 0)

    def test_foreign_lock_of_same_age_is_respected(self) -> None:
        self._hold("vr-layer agent testing", self.cfg.agent_timeout + 300)
        self.cfg.lock_wait_seconds = 0.2
        self.backend.add_build()
        self.assertEqual(self.runner().run_once(), 1)

    def test_lock_with_local_time_and_garbage(self) -> None:
        lock = rbr.EditorLock(self.state / "x.lock", "me")
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "x.lock").write_text('{"owner": "ps", "since": "2026-09-27T00:12:00.1234567-04:00"}')
        self.assertGreater(lock.age_seconds(lock.read()), 0)
        (self.state / "x.lock").write_text("not json")
        self.assertEqual(lock.read(), {})
        self.assertLess(lock.age_seconds(lock.read()), 60)  # falls back to the file time

    def test_release_leaves_someone_elses_lock(self) -> None:
        lock = rbr.EditorLock(self.state / "y.lock", "me")
        self.assertTrue(lock.try_acquire())
        (self.state / "y.lock").write_text(json.dumps({"owner": "other", "since": rbr.utc_iso()}))
        lock.release()
        self.assertTrue((self.state / "y.lock").exists())


class SecretTests(RunnerTestCase):
    def test_token_never_reaches_the_logs(self) -> None:
        self.backend.claim_error = (500, f"database said no to {TOKEN}")
        runner = self.runner()
        self.assertEqual(runner.run_once(), 2)
        self.backend.claim_error = None
        self.backend.add_build()
        self.backend.status_error = (500, f"echo Bearer {TOKEN}")
        rbr.log.info("direct attempt: %s / Bearer %s", TOKEN, TOKEN)
        runner.run_once()
        text = self.log_text()
        self.assertIn("database said no to ***", text)
        self.assertIn("***", text)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("S3cr3tRunnerToken", text)
        for path in self.state.rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN, path.read_text(encoding="utf-8", errors="replace"), path)
        for call in self.commands.calls:
            self.assertNotIn(TOKEN, json.dumps(call))

    def test_redact_bearer_pattern(self) -> None:
        self.assertEqual(rbr.redact("Authorization: Bearer abcdefghijkl123", []), "Authorization: Bearer ***")

    def test_read_token_prefers_env_then_file(self) -> None:
        home = Path(self.tmp.name) / "home"
        (home / ".config" / "sketchscape").mkdir(parents=True)
        (home / ".config" / "sketchscape" / "room-runner-token").write_text("\ufefffile-token\n", encoding="utf-8")
        self.assertEqual(rbr.read_token({}, home)[0], "file-token")
        self.assertEqual(rbr.read_token({rbr.TOKEN_ENV: " env-token "}, home), ("env-token", f"env {rbr.TOKEN_ENV}"))
        self.assertEqual(rbr.read_token({}, Path(self.tmp.name) / "nobody")[0], "")


class RestartTests(RunnerTestCase):
    def test_resumes_the_build_it_was_driving(self) -> None:
        build = self.backend.add_build(status="building", runner_id="unity-box")
        self.backend.queue.clear()   # already claimed before the crash
        self.state.mkdir(parents=True, exist_ok=True)
        self.cfg.state_path.write_text(json.dumps({"build": build, "attempt": 1}), encoding="utf-8")
        self.assertEqual(self.runner().run_once(), 0)
        self.assertFalse(any(p.endswith("/claim") for _, p, _ in self.backend.requests))
        self.assertEqual(self.backend.statuses(), ["syncing", "building", "ready"])
        self.assertIn("--session-id 'room-build-b1-r2'", self.commands.calls[-1]["script"])
        self.assertFalse(self.cfg.state_path.exists())

    def test_resume_survives_a_backend_refusing_to_go_back_to_syncing(self) -> None:
        build = self.backend.add_build(status="building", runner_id="unity-box")
        self.backend.queue.clear()
        self.backend.refuse = {"syncing"}
        self.state.mkdir(parents=True, exist_ok=True)
        self.cfg.state_path.write_text(json.dumps({"build": build, "attempt": 1}), encoding="utf-8")
        self.assertEqual(self.runner().run_once(), 0)
        self.assertEqual(self.backend.statuses(), ["building", "ready"])
        self.assertIn("still ours", self.log_text())

    def test_gives_up_after_max_attempts(self) -> None:
        build = self.backend.add_build(status="building", runner_id="unity-box")
        self.backend.queue.clear()
        self.state.mkdir(parents=True, exist_ok=True)
        self.cfg.state_path.write_text(json.dumps({"build": build, "attempt": 2}), encoding="utf-8")
        self.assertEqual(self.runner().run_once(), 1)
        self.assertEqual(self.backend.statuses(), ["failed"])
        self.assertIn("restarted", self.failed_body()["message"])
        self.assertEqual(self.commands.calls, [])

    def test_resumed_build_owned_by_someone_else_is_dropped(self) -> None:
        build = self.backend.add_build(status="ready", runner_id="other")
        self.backend.queue.clear()
        self.state.mkdir(parents=True, exist_ok=True)
        self.cfg.state_path.write_text(json.dumps({"build": build, "attempt": 1}), encoding="utf-8")
        self.assertEqual(self.runner().run_once(), 1)
        self.assertEqual(self.backend.posts, [])
        self.assertFalse(self.cfg.state_path.exists())


class HelperTests(unittest.TestCase):
    def test_room_slug_matches_backend(self) -> None:
        names = ["Cabin living room", "Cabin by the Fire", "  Café—by the Fire!! ", "", "___", "a" * 80,
                 "Lazy Sunday", "x/y\\z:*?"]
        sys.path.insert(0, str(rbr.REPO / "backend"))
        try:
            import unity_room  # noqa: PLC0415
        except Exception as exc:  # pragma: no cover - backend deps missing
            self.skipTest(f"backend/unity_room.py not importable here: {exc}")
        finally:
            sys.path.pop(0)
        for name in names:
            self.assertEqual(rbr.room_slug(name), unity_room.room_slug(name), name)

    def test_paths_and_quoting(self) -> None:
        self.assertEqual(rbr.to_wsl_path(r"C:\Users\kriva\AppData\Local\SketchScape\x.sh"),
                         "/mnt/c/Users/kriva/AppData/Local/SketchScape/x.sh")
        self.assertEqual(rbr.sh_quote("it's"), "'it'\"'\"'s'")

    def test_real_run_command_exit_code_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "step.log"
            code = rbr.run_command([sys.executable, "-c", "print('hello from child'); raise SystemExit(3)"], log_path)
            self.assertEqual(code, 3)
            self.assertIn("hello from child", rbr.tail_text(log_path))
            code = rbr.run_command([sys.executable, "-c", "import time; time.sleep(5)"], log_path, timeout=0.5)
            self.assertEqual(code, rbr.TIMED_OUT)
            self.assertIn("timed out", rbr.tail_text(log_path))


if __name__ == "__main__":
    logging.disable(logging.NOTSET)
    unittest.main()
