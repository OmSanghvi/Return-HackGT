#!/usr/bin/env python3
"""GPU-host dispatcher (Build Plan step 27).

Runs on the GPU host next to ``worker_server.py``. Loop:

    POST /v1/internal/jobs/claim (worker token)  ->  run  ->  renew the
    lease every 60 s  ->  post the result

Two job kinds, two different "run" strategies:

* ``segment`` -- claimed and driven entirely by this dispatcher. It fetches
  the pending selections' typed names, asks the warm SAM 3.1 server
  (``segment_sam31_local.py --serve``) to batch them into one predictor
  call, and reports each selection's outcome individually to the API
  (Hard Rule 7: one selection failing never blocks the others).
* ``reconstruct`` -- unchanged per job (skill item 2). The dispatcher hands
  it to the co-located, already-warm ``worker_server.py`` over its existing
  loopback ``/worker/jobs`` contract and only babysits the API-side lease
  while Fast-SAM3D runs; ``worker_server.py`` reports the PLY/mask/preview
  to the API itself, unchanged since Build Plan step 26.

Segment jobs are short, so they are claimed first every iteration (skill
item 4). ``SKETCHSCAPE_GPU_CONCURRENCY`` (default 1, the only value verified
safe on any instance type -- Hard Rule 5) bounds how many `reconstruct` jobs
this dispatcher will have in flight with `worker_server.py` at once; raising
it needs an approved VRAM benchmark on the actual instance type
(``worker/benchmark_concurrency.py``) recorded in ``docs/BUILD_PLAN.md``
step 27, never just a config change.

Everything in this file talks to two HTTP surfaces only: the SketchScape
API's ``/v1/internal/...`` routes (worker-token authenticated) and the two
loopback servers (``worker_server.py``, ``segment_sam31_local.py --serve``).
No CUDA, no torch, no ultralytics import here -- this process never touches
the GPU directly, so it (and everything below the thin ``ApiClient``/
``Sam31Client``/``WorkerServerClient`` HTTP methods) is fully unit-testable
on a CPU machine with fake clients standing in for the two servers and the
API. See ``worker/test_gpu_dispatcher.py``.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import shutil
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [dispatcher] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gpu_dispatcher")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


@dataclass
class DispatcherConfig:
    api_url: str
    worker_token: str
    worker_id: str
    sam31_server_url: str
    worker_server_url: str
    gpu_concurrency: int = 1
    lease_seconds: int = 900
    renew_interval: float = 60.0
    reconstruct_poll_interval: float = 2.0
    reconstruct_max_wait: float = 1800.0
    idle_backoff_min: float = 1.0
    idle_backoff_max: float = 10.0
    work_dir: Path = field(default_factory=lambda: Path("/tmp/sketchscape-dispatcher"))
    # A job whose hand-over failed goes back to the queue; this kind is not
    # claimed again for `handover_cooldown` s (doubling to the max), and one
    # job that fails its hand-over / is lost `max_handover_strikes` times is
    # failed instead of looping forever (e.g. a photo that crashes SAM 3.1).
    handover_cooldown: float = 15.0
    handover_cooldown_max: float = 120.0
    max_handover_strikes: int = 3
    # worker_server.py answering "unknown" for a job it accepted means it
    # restarted and the job is gone: release it after `lost_job_grace` s.
    # Not answering at all is ambiguous (a busy single-threaded server can
    # time out for a while), so that waits `unreachable_grace` s -- the
    # worker needs ~4 min to reload its models anyway.
    lost_job_grace: float = 30.0
    unreachable_grace: float = 180.0

    @classmethod
    def from_env(cls) -> "DispatcherConfig":
        default_worker_id = f"{socket.gethostname()}-{os.getpid()}"
        worker_server_port = os.environ.get("SKETCHSCAPE_WORKER_SERVER_PORT", "8001")
        return cls(
            api_url=_required("SKETCHSCAPE_API_URL").rstrip("/"),
            worker_token=_required("SKETCHSCAPE_WORKER_TOKEN"),
            worker_id=os.environ.get("SKETCHSCAPE_WORKER_ID", "").strip() or default_worker_id,
            sam31_server_url=os.environ.get("SAM31_SERVER_URL", "http://127.0.0.1:8002").rstrip("/"),
            worker_server_url=os.environ.get(
                "SKETCHSCAPE_WORKER_SERVER_URL", f"http://127.0.0.1:{worker_server_port}"
            ).rstrip("/"),
            gpu_concurrency=max(1, int(os.environ.get("SKETCHSCAPE_GPU_CONCURRENCY", "1"))),
            lease_seconds=max(30, int(os.environ.get("SKETCHSCAPE_JOB_LEASE_SECONDS", "900"))),
            work_dir=Path(os.environ.get("SKETCHSCAPE_DISPATCHER_WORK_DIR", "/tmp/sketchscape-dispatcher")),
            handover_cooldown=float(os.environ.get("SKETCHSCAPE_HANDOVER_COOLDOWN", "15")),
            max_handover_strikes=max(1, int(os.environ.get("SKETCHSCAPE_MAX_HANDOVER_STRIKES", "3"))),
            lost_job_grace=float(os.environ.get("SKETCHSCAPE_LOST_JOB_GRACE", "30")),
            unreachable_grace=float(os.environ.get("SKETCHSCAPE_UNREACHABLE_GRACE", "180")),
        )


# ---------------------------------------------------------------------------
# Thin HTTP clients (the adapter boundary). Real network calls only happen
# in these three classes; everything else takes them as parameters, so
# tests substitute fakes and never open a socket.
# ---------------------------------------------------------------------------


class ApiClient:
    """The SketchScape backend's worker-only `/v1/internal/...` routes."""

    def __init__(self, base_url: str, token: str, worker_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.worker_id = worker_id

    def _get_json(self, path: str, timeout: float = 30.0) -> dict[str, Any] | None:
        request = Request(
            f"{self.base_url}{path}",
            headers={"X-SketchScape-Worker-Token": self.token},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                if response.status == 204:
                    return None
                return json.loads(response.read())
        except HTTPError as error:
            if error.code == 204:
                return None
            raise

    def _get_bytes(self, path: str, timeout: float = 60.0) -> bytes:
        request = Request(
            f"{self.base_url}{path}",
            headers={"X-SketchScape-Worker-Token": self.token},
        )
        with urlopen(request, timeout=timeout) as response:
            return response.read()

    def _post_json(self, path: str, body: dict[str, Any], timeout: float = 30.0) -> dict[str, Any] | None:
        data = json.dumps(body).encode()
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-SketchScape-Worker-Token": self.token,
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                if response.status == 204:
                    return None
                return json.loads(response.read())
        except HTTPError as error:
            if error.code == 204:
                return None
            raise

    def _post_form(self, path: str, fields: dict[str, str], timeout: float = 30.0) -> dict[str, Any]:
        data = "&".join(f"{key}={_url_escape(value)}" for key, value in fields.items()).encode()
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())

    def _post_multipart(
        self,
        path: str,
        fields: dict[str, str],
        files: dict[str, bytes] | None,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        boundary = f"----SketchScapeDispatcher{uuid.uuid4().hex}"
        body = bytearray()

        def add_field(name: str, value: str) -> None:
            body.extend(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode()
            )

        for name, value in fields.items():
            add_field(name, value)
        for name, content in (files or {}).items():
            filename = f"{name}.png"
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            body.extend(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode()
            )
            body.extend(content)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        request = Request(
            f"{self.base_url}{path}",
            data=bytes(body),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())

    # -- public surface used by the job handlers below ---------------------

    def claim(self, kinds: list[str]) -> dict[str, Any] | None:
        return self._post_json("/v1/internal/jobs/claim", {"worker_id": self.worker_id, "kinds": kinds})

    def renew_lease(self, job_id: str) -> bool:
        response = self._post_form(
            f"/v1/internal/jobs/{job_id}/lease",
            {"worker_id": self.worker_id, "worker_token": self.token},
        )
        return bool(response.get("renewed"))

    def get_selections(self, job_id: str) -> dict[str, Any]:
        return self._get_json(f"/v1/internal/reconstructions/{job_id}/selections") or {}

    def get_input(self, job_id: str, kind: str) -> bytes:
        return self._get_bytes(f"/v1/internal/reconstructions/{job_id}/input/{kind}")

    def post_selection_result(
        self,
        job_id: str,
        selection_id: str,
        payload: dict[str, Any],
        mask_bytes: bytes | None,
        preview_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        files: dict[str, bytes] = {}
        if mask_bytes is not None:
            files["mask"] = mask_bytes
        if preview_bytes is not None:
            files["preview"] = preview_bytes
        return self._post_multipart(
            f"/v1/internal/reconstructions/{job_id}/selections/{selection_id}/result",
            {"worker_token": self.token, "worker_id": self.worker_id, "result": json.dumps(payload)},
            files,
        )

    def post_job_failed(self, job_id: str, error: str) -> dict[str, Any]:
        return self._post_multipart(
            f"/v1/internal/reconstructions/{job_id}/result",
            {
                "worker_token": self.token,
                "worker_id": self.worker_id,
                "result": json.dumps({"status": "failed", "error": error[:500]}),
            },
            None,
        )

    def release_job(self, job_id: str, reason: str) -> bool:
        """Give a claimed job back to the queue right now (status `queued`,
        no lease) instead of leaving it leased with nothing running it.

        Uses the API's ``POST /v1/internal/jobs/{job_id}/release`` when the
        backend has it; an older backend without that route (404/405) falls
        back to the same conditional DynamoDB write the API's own
        ``release_expired_leases`` makes (``DynamoJobReleaser``), which only
        succeeds while this worker still owns the lease. Never raises.
        """
        try:
            response = self._post_form(
                f"/v1/internal/jobs/{job_id}/release",
                {"worker_id": self.worker_id, "worker_token": self.token, "reason": reason[:300]},
            )
            released = bool(response.get("released"))
            log.info("[%s] Released via API (released=%s): %s", job_id[:8], released, reason)
            return released
        except HTTPError as error:
            if error.code not in (404, 405):
                log.error("[%s] API release failed (HTTP %s); job stays leased: %s", job_id[:8], error.code, reason)
                return False
        except Exception as exc:  # API down: the fallback below still works
            log.warning("[%s] API release unreachable (%s); trying the DynamoDB fallback", job_id[:8], exc)
        if self.fallback_releaser is None:
            log.error("[%s] No release route and no DynamoDB fallback; job stays leased: %s", job_id[:8], reason)
            return False
        try:
            released = self.fallback_releaser.release(job_id, self.worker_id)
        except Exception:
            log.exception("[%s] DynamoDB release failed; job stays leased", job_id[:8])
            return False
        log.info("[%s] Released via DynamoDB (released=%s): %s", job_id[:8], released, reason)
        return released

    # Set by `main()` (DynamoJobReleaser.from_env()); None in tests.
    fallback_releaser: "DynamoJobReleaser | None" = None


class DynamoJobReleaser:
    """Fallback for ``ApiClient.release_job`` when the backend has no release
    route: puts a job this worker holds back to ``queued`` with the same
    item layout and ``lease_owner`` condition as ``backend/storage.py``'s
    ``DynamoDBStore.release_expired_leases`` (the pattern
    ``worker/backfill_objects.py`` already uses for direct table writes).
    ``attempts`` is NOT incremented: the job never started running here.
    """

    def __init__(self, table: Any) -> None:
        self.table = table

    @classmethod
    def from_env(cls) -> "DynamoJobReleaser | None":
        if os.environ.get("SKETCHSCAPE_STORAGE_BACKEND", "").strip().lower() != "dynamodb":
            return None
        table_name = os.environ.get("SKETCHSCAPE_DYNAMODB_TABLE", "").strip()
        if not table_name:
            return None
        try:
            import boto3  # noqa: PLC0415 - the dispatcher runs in the backend venv
        except ImportError:
            log.warning("boto3 unavailable; claimed jobs can only be released through the API route")
            return None
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        return cls(boto3.resource("dynamodb", region_name=region).Table(table_name))

    def release(self, job_id: str, worker_id: str) -> bool:
        key = {"pk": f"JOB#{job_id}", "sk": "META"}
        item = self.table.get_item(Key=key, ConsistentRead=True).get("Item")
        if item is None:
            return False
        document = json.loads(item["document"])
        if document.get("lease_owner") != worker_id or str(item.get("status", "")) != "running":
            return False  # finished, or someone else's lease now: nothing to give back
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        document.update({"status": "queued", "lease_owner": None, "lease_expires_at": None, "updated_at": now_iso})
        new_item = dict(item)
        new_item["document"] = json.dumps(document)
        new_item["status"] = "queued"
        new_item["lease_owner"] = ""
        new_item["gsi2pk"] = str(item.get("gsi2pk", "JOBQ#running")).replace("running", "queued")
        try:
            self.table.put_item(
                Item=new_item,
                ConditionExpression="#lo = :owner",
                ExpressionAttributeNames={"#lo": "lease_owner"},
                ExpressionAttributeValues={":owner": worker_id},
            )
        except Exception as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if code == "ConditionalCheckFailedException":
                return False
            raise
        return True


def _url_escape(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value)


class Sam31Client:
    """The warm SAM 3.1 server (``segment_sam31_local.py --serve``)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def health(self, timeout: float = 5.0) -> bool:
        """True only once the warm server answers ``/health`` -- it binds its
        port after the model load + warm-up pass, so "connection refused"
        means "still loading" (or crashed)."""
        try:
            with urlopen(f"{self.base_url}/health", timeout=timeout) as response:
                if response.status != 200:
                    return False
                try:
                    body = json.loads(response.read() or b"{}")
                except ValueError:
                    return True
                return str(body.get("status", "ready")) == "ready"
        except Exception:
            return False

    ready = health

    def segment_many(
        self,
        image_path: Path,
        output_dir: Path,
        selections: list[dict[str, str]],
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        body = json.dumps(
            {"image": str(image_path), "output_dir": str(output_dir), "selections": selections}
        ).encode()
        request = Request(
            f"{self.base_url}/segment_many",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())


class WorkerServerClient:
    """The co-located, already-warm Fast-SAM3D server (``worker_server.py``)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def submit(self, job_id: str, subject_hint: str, timeout: float = 10.0) -> None:
        body = json.dumps({"job_id": job_id, "subject_hint": subject_hint}).encode()
        request = Request(
            f"{self.base_url}/worker/jobs",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                response.read()
        except HTTPError as error:
            if error.code == 409:
                # Already submitted (a retry after a dropped response) --
                # fine, `status()` polling below picks up the real outcome.
                return
            raise

    def status(self, job_id: str, timeout: float = 10.0) -> dict[str, Any]:
        with urlopen(f"{self.base_url}/worker/status/{job_id}", timeout=timeout) as response:
            return json.loads(response.read())

    def ready(self, timeout: float = 5.0) -> bool:
        """True only when ``/worker/health`` reports ``status == "ready"``
        (models loaded, no load error) and its accept queue has room -- the
        states in which ``POST /worker/jobs`` answers 202 rather than 503
        ("models not ready") or 429 ("worker busy")."""
        try:
            with urlopen(f"{self.base_url}/worker/health", timeout=timeout) as response:
                body = json.loads(response.read() or b"{}")
        except Exception:
            return False
        if body.get("status") != "ready":
            return False
        try:
            queue_size = int(body.get("queue_size") or 0)
            capacity = max(1, int(body.get("gpu_concurrency") or 1))
        except (TypeError, ValueError):
            return True
        return queue_size < capacity


# ---------------------------------------------------------------------------
# Job handlers (the testable core: everything above the HTTP method bodies
# takes clients as plain parameters, so a fake stands in for a real server).
# ---------------------------------------------------------------------------


_TERMINAL_WORKER_SERVER_STATUSES = {"complete", "failed", "mask_review"}
_LOST_WORKER_SERVER_STATUSES = {"unknown", "unreachable"}
_SERVICE_FOR_KIND = {"segment": "SAM 3.1 (:8002)", "reconstruct": "worker_server.py (:8001)"}


class HandoverGate:
    """Claim gating after failed hand-overs (docs/WEB_TO_QUEST_PIPELINE.md 7).

    * A per-kind cooldown: after a hand-over of kind K fails, no K job is
      claimed for ``cooldown`` s (doubling up to ``cooldown_max``, reset by
      the next successful hand-over), so a flapping service can't make the
      dispatcher spin claim -> fail -> release.
    * A per-job strike count: a job whose hand-over fails (or that the
      service loses mid-run) ``max_strikes`` times is failed with a reason
      instead of being released forever (a photo that crashes SAM 3.1 must
      not block every later upload).
    * Readiness logging on transitions only (no log line every poll).

    Thread-safe: `reconstruct` jobs are babysat on background threads.
    """

    def __init__(
        self,
        cooldown: float = 15.0,
        cooldown_max: float = 120.0,
        max_strikes: int = 3,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cooldown_base = max(0.0, cooldown)
        self._cooldown_max = max(self._cooldown_base, cooldown_max)
        self.max_strikes = max(1, max_strikes)
        self._now = now
        self._lock = threading.Lock()
        self._blocked_until: dict[str, float] = {}
        self._cooldown: dict[str, float] = {}
        self._strikes: dict[str, int] = {}
        self._waiting: dict[str, bool] = {}

    def can_claim(self, kind: str) -> bool:
        with self._lock:
            return self._now() >= self._blocked_until.get(kind, 0.0)

    def handover_failed(self, kind: str, job_id: str) -> int:
        """Record a failed hand-over; returns this job's strike count."""
        with self._lock:
            previous = self._cooldown.get(kind, 0.0)
            cooldown = self._cooldown_base if previous <= 0 else min(previous * 2, self._cooldown_max)
            self._cooldown[kind] = cooldown
            self._blocked_until[kind] = self._now() + cooldown
            self._strikes[job_id] = self._strikes.get(job_id, 0) + 1
            return self._strikes[job_id]

    def handover_ok(self, kind: str) -> None:
        with self._lock:
            self._cooldown.pop(kind, None)
            self._blocked_until.pop(kind, None)

    def job_done(self, job_id: str) -> None:
        with self._lock:
            self._strikes.pop(job_id, None)

    def note_ready(self, kind: str, ready: bool) -> None:
        with self._lock:
            was_waiting = self._waiting.get(kind, False)
            self._waiting[kind] = not ready
        service = _SERVICE_FOR_KIND.get(kind, kind)
        if not ready and not was_waiting:
            log.warning("%s is not ready; not claiming `%s` jobs until it is.", service, kind)
        elif ready and was_waiting:
            log.info("%s is ready again; claiming `%s` jobs.", service, kind)


def _describe(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    return f"{type(exc).__name__}: {exc}"[:300]


def _give_back(api: ApiClient, gate: HandoverGate, kind: str, job_id: str, reason: str) -> str:
    """A claimed job we could not run: release it to the queue at once, or
    -- on its ``max_strikes``-th failure -- fail it with the reason."""
    strikes = gate.handover_failed(kind, job_id)
    if strikes >= gate.max_strikes:
        log.error("[%s] %s -- giving up after %d attempts; failing the job.", job_id[:8], reason, strikes)
        try:
            api.post_job_failed(job_id, f"{reason} (gave up after {strikes} attempts)")
            gate.job_done(job_id)
            return "failed"
        except Exception:
            log.exception("[%s] Could not fail the job; releasing it instead", job_id[:8])
    else:
        log.warning("[%s] %s -- releasing the job to the queue (attempt %d/%d).",
                    job_id[:8], reason, strikes, gate.max_strikes)
    api.release_job(job_id, reason)
    return "released"


def handle_segment_job(
    api: ApiClient,
    sam31: Sam31Client,
    job: dict[str, Any],
    work_dir: Path,
    gate: HandoverGate | None = None,
) -> str:
    """One `segment` job, start to finish. Returns a short status string.

    A photo where the person typed several names batches into one SAM 3.1
    call (skill item 1); each selection is reported to the API
    independently, so one selection finding nothing never blocks the
    others (Hard Rule 7). Each selection's optional VLM ``box`` (stored
    photo pixels) is passed through to SAM 3.1, which uses it to pick *that*
    instance among several of the same kind.

    If SAM 3.1 can't be reached (down, restarting, timed out), the job is
    released back to the queue at once rather than failed or left leased;
    only a job that keeps failing is failed. The job's scratch dir is
    removed when it is done.
    """
    gate = gate or HandoverGate()
    job_id = job["job_id"]
    task = api.get_selections(job_id)
    selections: list[dict[str, Any]] = task.get("selections", [])
    if not selections:
        log.warning("[%s] Segment job has no pending selections; leaving it for lease expiry.", job_id[:8])
        return "no_selections"

    job_dir = work_dir / job_id
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        image_key = task.get("image_key") or job.get("image_key") or ""
        image_path = job_dir / ("image" + (Path(image_key).suffix or ".png"))
        image_path.write_bytes(api.get_input(job_id, "image"))

        output_dir = job_dir / "masks"
        try:
            response = sam31.segment_many(image_path, output_dir, selections)
        except Exception as exc:  # SAM 3.1 server unreachable, crashed, or timed out
            return _give_back(api, gate, "segment", job_id, f"SAM 3.1 segmentation unavailable: {_describe(exc)}")
        gate.handover_ok("segment")

        if response.get("error"):
            log.error("[%s] SAM 3.1 server error: %s", job_id[:8], response["error"])
        results: dict[str, Any] = response.get("results", {})
        for selection in selections:
            selection_id = selection["selection_id"]
            outcome = results.get(
                selection_id,
                {"status": "failed", "reason": "no SAM 3.1 result for this selection"},
            )
            mask_bytes: bytes | None = None
            mask_path = outcome.get("mask_path")
            if outcome.get("status") == "segmented" and mask_path:
                mask_bytes = Path(mask_path).read_bytes()
            api.post_selection_result(
                job_id,
                selection_id,
                {
                    "status": outcome.get("status", "failed"),
                    "score": outcome.get("score"),
                    "alternatives": outcome.get("alternatives", []),
                    "reason": outcome.get("reason"),
                },
                mask_bytes,
            )
        gate.job_done(job_id)
        return "done"
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


def handle_reconstruct_job(
    api: ApiClient,
    worker: WorkerServerClient,
    job: dict[str, Any],
    *,
    renew_interval: float = 60.0,
    poll_interval: float = 2.0,
    max_wait: float = 1800.0,
    lost_grace: float = 30.0,
    unreachable_grace: float = 180.0,
    gate: HandoverGate | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> str:
    """Hand a claimed `reconstruct` job to the co-located `worker_server.py`
    (Fast-SAM3D path unchanged since Build Plan step 26) and babysit the
    API-side lease while it runs. `worker_server.py` reports the PLY/mask
    itself, so this only renews the lease and reports the outcome for logs.

    Never leaves a job leased with nothing running it:

    * the hand-over fails (503 "models not ready", 429 busy, connection
      refused, timeout) -> the job is released to the queue at once
      ("released");
    * `worker_server.py` forgets the job (answers "unknown": it restarted
      mid-run) for ``lost_grace`` s, or stays unreachable for
      ``unreachable_grace`` s -> released;
    * nothing finishes within ``max_wait`` -> released ("timeout").

    Returns "lease_lost" if a renewal is rejected -- another worker now
    owns this job and this dispatcher must stop touching it.
    """
    gate = gate or HandoverGate()
    job_id = job["job_id"]
    try:
        worker.submit(job_id, job.get("subject_hint") or "")
    except Exception as exc:
        return _give_back(api, gate, "reconstruct", job_id, f"hand-over to worker_server.py failed: {_describe(exc)}")
    gate.handover_ok("reconstruct")

    deadline = now() + max_wait
    next_renew = now() + renew_interval
    lost_since: float | None = None
    while now() < deadline:
        try:
            status = str(worker.status(job_id).get("status", "unknown"))
        except Exception:
            status = "unreachable"
        if status in _TERMINAL_WORKER_SERVER_STATUSES:
            gate.job_done(job_id)
            return status
        if status in _LOST_WORKER_SERVER_STATUSES:
            if lost_since is None:
                lost_since = now()
            elif now() - lost_since >= (lost_grace if status == "unknown" else max(lost_grace, unreachable_grace)):
                return _give_back(
                    api, gate, "reconstruct", job_id,
                    f"worker_server.py lost the job ({status} for {now() - lost_since:.0f}s; restarted?)",
                )
        else:
            lost_since = None
        if now() >= next_renew:
            try:
                renewed = api.renew_lease(job_id)
            except Exception as exc:  # API blip: keep babysitting, retry soon
                log.warning("[%s] Lease renewal failed (%s); retrying.", job_id[:8], _describe(exc))
                next_renew = now() + min(renew_interval, 15.0)
            else:
                if not renewed:
                    log.error("[%s] Lease renewal rejected; another worker owns this job now.", job_id[:8])
                    gate.job_done(job_id)
                    return "lease_lost"
                next_renew = now() + renew_interval
        sleep(poll_interval)
    _give_back(api, gate, "reconstruct", job_id, f"timed out after {max_wait:.0f}s waiting for worker_server.py")
    return "timeout"


def next_backoff(current: float, minimum: float, maximum: float) -> float:
    """Idle backoff: 1 s growing to 10 s (skill item 3), doubling each
    empty poll and resetting to `minimum` the moment work is found."""
    return min(max(current, minimum) * 2, maximum)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


class _ReconstructSlots(Protocol):
    def acquire(self, blocking: bool = ...) -> bool: ...
    def release(self) -> None: ...


def run_once(
    api: ApiClient,
    sam31: Sam31Client,
    worker: WorkerServerClient,
    config: DispatcherConfig,
    reconstruct_slots: _ReconstructSlots,
    *,
    start_reconstruct: Callable[[dict[str, Any]], None] | None = None,
    gate: HandoverGate | None = None,
) -> bool:
    """One dispatcher iteration. Returns True if a job was claimed.

    Segment jobs are claimed and run to completion inline (skill item 4:
    they are short, so they take priority). A `reconstruct` job only gets
    claimed while a concurrency slot is free (`SKETCHSCAPE_GPU_CONCURRENCY`,
    default 1); `start_reconstruct` hands it off (a background thread in
    `main()`, called synchronously by tests) so a long reconstruction never
    blocks the next iteration's segment-job claim.

    Nothing is claimed while the service that would run it isn't ready
    (SAM 3.1 ``/health``; worker ``/worker/health`` status "ready" with
    queue room) or while that kind is cooling down after a failed hand-over
    -- a job left queued waits safely; a claimed one would sit leased.
    """
    gate = gate or HandoverGate(config.handover_cooldown, config.handover_cooldown_max, config.max_handover_strikes)
    did_work = False

    if gate.can_claim("segment"):
        sam31_ready = sam31.health()
        gate.note_ready("segment", sam31_ready)
        if sam31_ready:
            segment_job = api.claim(["segment"])
            if segment_job is not None:
                did_work = True
                try:
                    handle_segment_job(api, sam31, segment_job, config.work_dir, gate)
                except Exception as exc:
                    log.exception("[%s] Unhandled error running segment job", segment_job.get("job_id", "?")[:8])
                    _give_back(api, gate, "segment", segment_job["job_id"], f"dispatcher error: {_describe(exc)}")

    if gate.can_claim("reconstruct") and reconstruct_slots.acquire(blocking=False):
        handed_off = False
        try:
            worker_ready = worker.ready()
            gate.note_ready("reconstruct", worker_ready)
            if worker_ready:
                reconstruct_job = api.claim(["reconstruct"])
                if reconstruct_job is not None:
                    did_work = True
                    handed_off = True
                    (start_reconstruct or _default_start_reconstruct(api, worker, config, reconstruct_slots, gate))(
                        reconstruct_job
                    )
        finally:
            if not handed_off:
                reconstruct_slots.release()

    return did_work


def _default_start_reconstruct(
    api: ApiClient,
    worker: WorkerServerClient,
    config: DispatcherConfig,
    reconstruct_slots: _ReconstructSlots,
    gate: HandoverGate,
) -> Callable[[dict[str, Any]], None]:
    def start(job: dict[str, Any]) -> None:
        def run() -> None:
            try:
                status = handle_reconstruct_job(
                    api,
                    worker,
                    job,
                    renew_interval=config.renew_interval,
                    poll_interval=config.reconstruct_poll_interval,
                    max_wait=config.reconstruct_max_wait,
                    lost_grace=config.lost_job_grace,
                    unreachable_grace=config.unreachable_grace,
                    gate=gate,
                )
                log.info("[%s] reconstruct job finished: %s", job.get("job_id", "?")[:8], status)
            except Exception as exc:
                log.exception("[%s] Unhandled error running reconstruct job", job.get("job_id", "?")[:8])
                _give_back(api, gate, "reconstruct", job["job_id"], f"dispatcher error: {_describe(exc)}")
            finally:
                reconstruct_slots.release()

        threading.Thread(target=run, daemon=True, name=f"reconstruct-{job.get('job_id', '?')[:8]}").start()

    return start


def _sweep_work_dir(work_dir: Path) -> None:
    """Startup sweep of segment-job scratch dirs a crash left behind."""
    try:
        import disk_hygiene  # noqa: PLC0415 - sibling module on the GPU host
    except ImportError:
        return
    max_age = disk_hygiene.env_float("SKETCHSCAPE_JOB_DIR_MAX_AGE_HOURS", 3.0) * 3600
    result = disk_hygiene.sweep_old_dirs([work_dir], max_age)
    log.info("Startup sweep of %s: removed %d dir(s), %.1f MB", work_dir, result["removed"],
             result["freed_bytes"] / 2**20)


def main() -> None:
    config = DispatcherConfig.from_env()
    config.work_dir.mkdir(parents=True, exist_ok=True)
    _sweep_work_dir(config.work_dir)
    api = ApiClient(config.api_url, config.worker_token, config.worker_id)
    api.fallback_releaser = DynamoJobReleaser.from_env()
    sam31 = Sam31Client(config.sam31_server_url)
    worker = WorkerServerClient(config.worker_server_url)
    reconstruct_slots = threading.Semaphore(config.gpu_concurrency)
    gate = HandoverGate(config.handover_cooldown, config.handover_cooldown_max, config.max_handover_strikes)

    log.info(
        "Dispatcher starting: worker_id=%s api=%s gpu_concurrency=%s sam31=%s worker_server=%s "
        "release_fallback=%s readiness_gate=on",
        config.worker_id,
        config.api_url,
        config.gpu_concurrency,
        config.sam31_server_url,
        config.worker_server_url,
        "dynamodb" if api.fallback_releaser is not None else "none",
    )

    backoff = config.idle_backoff_min
    while True:
        try:
            did_work = run_once(api, sam31, worker, config, reconstruct_slots, gate=gate)
        except (URLError, ConnectionError, TimeoutError) as exc:  # API restarting: just wait
            log.warning("API unreachable (%s); retrying.", _describe(exc))
            did_work = False
        except Exception:
            log.exception("Unhandled error in dispatcher loop")
            did_work = False
        if did_work:
            backoff = config.idle_backoff_min
        else:
            time.sleep(backoff)
            backoff = next_backoff(backoff, config.idle_backoff_min, config.idle_backoff_max)


if __name__ == "__main__":
    main()
