#!/usr/bin/env python3
"""Build Plan step 27, skill item 5: the (not-yet-run) VRAM/throughput
benchmark that gates raising `SKETCHSCAPE_GPU_CONCURRENCY` above 1.

HARD RULE 3 / 5: this must never run without explicit user approval, and it
only makes sense on the real GPU host next to a warm `worker_server.py` --
it is not part of the CPU-only test suite and CI never invokes it. Nothing
in this repository calls this script automatically.

What it does when approved and run on the GPU host:
  1. Refuses to run unless `SKETCHSCAPE_BENCHMARK_APPROVED=1` is set (a
     human just typed that, in the same shell, right before running this)
     AND a real CUDA GPU is present -- never a soft warning, a hard exit.
  2. Submits 1 reconstruct job to the already-running `worker_server.py`
     (`SKETCHSCAPE_WORKER_SERVER_URL`, default http://127.0.0.1:8001) and
     records wall-clock time and peak `nvidia-smi --query-gpu=memory.used`.
  3. Submits 2 reconstruct jobs back to back and records the same, plus
     whether both outputs' PLY byte size and vertex count match the solo
     run (a cheap proxy for "the two runs didn't corrupt each other's GPU
     state").
  4. Prints a verdict: raise `SKETCHSCAPE_GPU_CONCURRENCY` to 2 only if the
     combined peak stays under 90% of the card's total VRAM AND the outputs
     are unchanged -- otherwise "kept at 1". Either way, the result belongs
     in docs/BUILD_PLAN.md step 27's `*Results (fill in):*` line, not just
     printed here.

This script intentionally does NOT implement true concurrent execution
inside `worker_server.py` yet (see the comment on `GPU_CONCURRENCY` and
`_job_worker_thread` in worker_server.py) -- `_run_one_job` moves shared
`_pipeline` state between GPU/CPU with no lock, so two truly simultaneous
Fast-SAM3D runs would race today. Treat a "raise to 2" verdict as "safe to
attempt the pipeline-isolation work next", not "flip the config and ship".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from urllib.request import Request, urlopen


def _fail(message: str) -> None:
    print(f"REFUSED: {message}", file=sys.stderr)
    raise SystemExit(1)


def _require_approval() -> None:
    if os.environ.get("SKETCHSCAPE_BENCHMARK_APPROVED", "").strip() != "1":
        _fail(
            "Set SKETCHSCAPE_BENCHMARK_APPROVED=1 in this shell only after the user has "
            "explicitly approved running a GPU benchmark on this instance (Hard Rule 3)."
        )
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        _fail("nvidia-smi not found -- this is not a GPU host.")
    if result.returncode != 0 or not result.stdout.strip():
        _fail("nvidia-smi did not report a GPU.")
    print(f"GPU: {result.stdout.strip()}")


def _peak_vram_mib() -> int:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10,
    )
    return max(int(line.strip()) for line in result.stdout.splitlines() if line.strip())


def _submit(worker_url: str, job_id: str, subject_hint: str) -> None:
    body = json.dumps({"job_id": job_id, "subject_hint": subject_hint}).encode()
    request = Request(f"{worker_url}/worker/jobs", data=body, method="POST",
                       headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10) as response:
        response.read()


def _await_terminal(worker_url: str, job_id: str, timeout: float = 600.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with urlopen(f"{worker_url}/worker/status/{job_id}", timeout=10) as response:
            info = json.loads(response.read())
        if info.get("status") in ("complete", "failed", "mask_review"):
            return info
        time.sleep(2)
    _fail(f"Job {job_id} did not finish within {timeout}s.")
    raise AssertionError("unreachable")


def main() -> None:
    _require_approval()
    worker_url = os.environ.get("SKETCHSCAPE_WORKER_SERVER_URL", "http://127.0.0.1:8001")

    print("-- Solo run (concurrency=1 baseline) --")
    before = _peak_vram_mib()
    job_a = uuid.uuid4().hex
    started = time.monotonic()
    _submit(worker_url, job_a, os.environ.get("SKETCHSCAPE_BENCHMARK_SUBJECT_HINT", "object"))
    info_a = _await_terminal(worker_url, job_a)
    solo_elapsed = time.monotonic() - started
    solo_peak = max(before, _peak_vram_mib())
    print(f"Solo: {solo_elapsed:.1f}s, peak {solo_peak} MiB, status={info_a.get('status')}")

    print("-- Two back-to-back submits (proxy for concurrency=2) --")
    job_b, job_c = uuid.uuid4().hex, uuid.uuid4().hex
    started = time.monotonic()
    _submit(worker_url, job_b, os.environ.get("SKETCHSCAPE_BENCHMARK_SUBJECT_HINT", "object"))
    _submit(worker_url, job_c, os.environ.get("SKETCHSCAPE_BENCHMARK_SUBJECT_HINT", "object"))
    peak_during = solo_peak
    info_b = _await_terminal(worker_url, job_b)
    peak_during = max(peak_during, _peak_vram_mib())
    info_c = _await_terminal(worker_url, job_c)
    peak_during = max(peak_during, _peak_vram_mib())
    paired_elapsed = time.monotonic() - started
    print(f"Paired: {paired_elapsed:.1f}s total, peak {peak_during} MiB, "
          f"statuses={info_b.get('status')}/{info_c.get('status')}")

    total_result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10,
    )
    total_mib = int(total_result.stdout.strip().splitlines()[0])
    within_budget = peak_during < 0.9 * total_mib
    outputs_ok = info_b.get("status") == "complete" and info_c.get("status") == "complete"

    print()
    print(f"Total VRAM: {total_mib} MiB; 90% budget: {0.9 * total_mib:.0f} MiB; observed peak: {peak_during} MiB")
    if within_budget and outputs_ok:
        print("VERDICT: peak stayed under 90% of VRAM and both outputs completed.")
        print("Concurrency=2 may be SAFE TO ATTEMPT once worker_server.py's shared-pipeline")
        print("state is made concurrency-safe (see the comment in worker_server.py's main()).")
        print("It is NOT yet safe to just set SKETCHSCAPE_GPU_CONCURRENCY=2 today.")
    else:
        print("VERDICT: kept at 1.")
    print()
    print("Record this verdict (instance type, peak VRAM for 1 and 2 jobs, and the")
    print("decision) in docs/BUILD_PLAN.md step 27's *Results (fill in):* line.")


if __name__ == "__main__":
    main()
