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
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.error import HTTPError
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


def _url_escape(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value)


class Sam31Client:
    """The warm SAM 3.1 server (``segment_sam31_local.py --serve``)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def health(self, timeout: float = 5.0) -> bool:
        try:
            with urlopen(f"{self.base_url}/health", timeout=timeout) as response:
                return response.status == 200
        except Exception:
            return False

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


# ---------------------------------------------------------------------------
# Job handlers (the testable core: everything above the HTTP method bodies
# takes clients as plain parameters, so a fake stands in for a real server).
# ---------------------------------------------------------------------------

_TERMINAL_WORKER_SERVER_STATUSES = {"complete", "failed", "mask_review"}


def handle_segment_job(api: ApiClient, sam31: Sam31Client, job: dict[str, Any], work_dir: Path) -> str:
    """One `segment` job, start to finish. Returns a short status string.

    A photo where the person typed several names batches into one SAM 3.1
    call (skill item 1); each selection is reported to the API
    independently, so one selection finding nothing never blocks the
    others (Hard Rule 7).
    """
    job_id = job["job_id"]
    task = api.get_selections(job_id)
    selections: list[dict[str, str]] = task.get("selections", [])
    if not selections:
        log.warning("[%s] Segment job has no pending selections; leaving it for lease expiry.", job_id[:8])
        return "no_selections"

    job_dir = work_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    image_key = task.get("image_key") or job.get("image_key") or ""
    image_path = job_dir / ("image" + (Path(image_key).suffix or ".png"))
    image_path.write_bytes(api.get_input(job_id, "image"))

    output_dir = job_dir / "masks"
    try:
        response = sam31.segment_many(image_path, output_dir, selections)
    except Exception as exc:  # SAM 3.1 server unreachable, crashed, or timed out
        log.exception("[%s] SAM 3.1 segmentation failed", job_id[:8])
        api.post_job_failed(job_id, f"SAM 3.1 segmentation unavailable: {exc}")
        return "failed"

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
    return "done"


def handle_reconstruct_job(
    api: ApiClient,
    worker: WorkerServerClient,
    job: dict[str, Any],
    *,
    renew_interval: float = 60.0,
    poll_interval: float = 2.0,
    max_wait: float = 1800.0,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> str:
    """Hand a claimed `reconstruct` job to the co-located `worker_server.py`
    (Fast-SAM3D path unchanged since Build Plan step 26) and babysit the
    API-side lease while it runs. `worker_server.py` reports the PLY/mask
    itself, so this only renews the lease and reports the outcome for logs.

    Returns "lease_lost" if a renewal is rejected -- another worker now
    owns this job and this dispatcher must stop touching it.
    """
    job_id = job["job_id"]
    worker.submit(job_id, job.get("subject_hint") or "")
    deadline = now() + max_wait
    next_renew = now() + renew_interval
    while now() < deadline:
        info = worker.status(job_id)
        status = info.get("status", "unknown")
        if status in _TERMINAL_WORKER_SERVER_STATUSES:
            return status
        if now() >= next_renew:
            if not api.renew_lease(job_id):
                log.error("[%s] Lease renewal rejected; another worker owns this job now.", job_id[:8])
                return "lease_lost"
            next_renew = now() + renew_interval
        sleep(poll_interval)
    log.error("[%s] Timed out waiting for worker_server.py.", job_id[:8])
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
) -> bool:
    """One dispatcher iteration. Returns True if a job was claimed.

    Segment jobs are claimed and run to completion inline (skill item 4:
    they are short, so they take priority). A `reconstruct` job only gets
    claimed while a concurrency slot is free (`SKETCHSCAPE_GPU_CONCURRENCY`,
    default 1); `start_reconstruct` hands it off (a background thread in
    `main()`, called synchronously by tests) so a long reconstruction never
    blocks the next iteration's segment-job claim.
    """
    did_work = False

    segment_job = api.claim(["segment"])
    if segment_job is not None:
        did_work = True
        try:
            handle_segment_job(api, sam31, segment_job, config.work_dir)
        except Exception:
            log.exception("[%s] Unhandled error running segment job", segment_job.get("job_id", "?")[:8])

    if reconstruct_slots.acquire(blocking=False):
        reconstruct_job = api.claim(["reconstruct"])
        if reconstruct_job is not None:
            did_work = True
            (start_reconstruct or _default_start_reconstruct(api, worker, config, reconstruct_slots))(
                reconstruct_job
            )
        else:
            reconstruct_slots.release()

    return did_work


def _default_start_reconstruct(
    api: ApiClient, worker: WorkerServerClient, config: DispatcherConfig, reconstruct_slots: _ReconstructSlots
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
                )
                log.info("[%s] reconstruct job finished: %s", job.get("job_id", "?")[:8], status)
            except Exception:
                log.exception("[%s] Unhandled error running reconstruct job", job.get("job_id", "?")[:8])
            finally:
                reconstruct_slots.release()

        threading.Thread(target=run, daemon=True, name=f"reconstruct-{job.get('job_id', '?')[:8]}").start()

    return start


def main() -> None:
    config = DispatcherConfig.from_env()
    config.work_dir.mkdir(parents=True, exist_ok=True)
    api = ApiClient(config.api_url, config.worker_token, config.worker_id)
    sam31 = Sam31Client(config.sam31_server_url)
    worker = WorkerServerClient(config.worker_server_url)
    reconstruct_slots = threading.Semaphore(config.gpu_concurrency)

    log.info(
        "Dispatcher starting: worker_id=%s api=%s gpu_concurrency=%s sam31=%s worker_server=%s",
        config.worker_id,
        config.api_url,
        config.gpu_concurrency,
        config.sam31_server_url,
        config.worker_server_url,
    )

    backoff = config.idle_backoff_min
    while True:
        try:
            did_work = run_once(api, sam31, worker, config, reconstruct_slots)
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
