"""Build Plan step 27: unit tests for `gpu_dispatcher.py`'s testable core.

Every test here runs against fake `ApiClient`/`Sam31Client`/
`WorkerServerClient` stand-ins -- no real HTTP, no GPU, no AWS. The three
real client classes only wrap `urllib.request` calls (the adapter
boundary); this file never exercises those, matching the same pattern as
`test_segment_sam31_local.py`.

Run with `python -m unittest test_gpu_dispatcher.py` from this directory.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu_dispatcher as gd  # noqa: E402


class FakeApiClient:
    """Records every call so tests can assert on the claim/renew/complete
    sequence the skill calls out: "claim -> run (fake) -> renew ->
    complete"."""

    def __init__(self) -> None:
        self.claim_queue: list[dict | None] = []
        self.selections_by_job: dict[str, dict] = {}
        self.inputs: dict[tuple[str, str], bytes] = {}
        self.renew_results: list[bool] = []
        self.selection_results: list[tuple[str, str, dict, bool, bool]] = []
        self.failed_jobs: list[tuple[str, str]] = []
        self.renew_calls = 0

    def claim(self, kinds: list[str]) -> dict | None:
        if not self.claim_queue:
            return None
        return self.claim_queue.pop(0)

    def renew_lease(self, job_id: str) -> bool:
        self.renew_calls += 1
        if not self.renew_results:
            return True
        return self.renew_results.pop(0)

    def get_selections(self, job_id: str) -> dict:
        return self.selections_by_job.get(job_id, {"selections": []})

    def get_input(self, job_id: str, kind: str) -> bytes:
        return self.inputs[(job_id, kind)]

    def post_selection_result(self, job_id, selection_id, payload, mask_bytes, preview_bytes=None):
        self.selection_results.append((job_id, selection_id, payload, mask_bytes is not None, preview_bytes is not None))
        return {"selection_id": selection_id, **payload}

    def post_job_failed(self, job_id: str, error: str) -> dict:
        self.failed_jobs.append((job_id, error))
        return {"status": "failed", "error": error}


class FakeSam31Client:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response or {"results": {}}
        self.error = error
        self.calls: list[tuple[Path, Path, list]] = []

    def segment_many(self, image_path, output_dir, selections, timeout=180.0):
        self.calls.append((image_path, output_dir, selections))
        if self.error is not None:
            raise self.error
        return self.response


class FakeWorkerServerClient:
    def __init__(self, statuses: list[dict]) -> None:
        self._statuses = list(statuses)
        self.submitted: list[tuple[str, str]] = []
        self.status_calls = 0

    def submit(self, job_id: str, subject_hint: str, timeout: float = 10.0) -> None:
        self.submitted.append((job_id, subject_hint))

    def status(self, job_id: str, timeout: float = 10.0) -> dict:
        self.status_calls += 1
        if len(self._statuses) > 1:
            return self._statuses.pop(0)
        return self._statuses[0]


class ManualClock:
    """A fake clock + sleep so `handle_reconstruct_job`'s poll/renew loop
    is deterministic and instant in tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class NextBackoffTests(unittest.TestCase):
    def test_grows_from_minimum_and_caps_at_maximum(self) -> None:
        self.assertEqual(gd.next_backoff(1.0, 1.0, 10.0), 2.0)
        self.assertEqual(gd.next_backoff(2.0, 1.0, 10.0), 4.0)
        self.assertEqual(gd.next_backoff(8.0, 1.0, 10.0), 10.0)
        self.assertEqual(gd.next_backoff(10.0, 1.0, 10.0), 10.0)

    def test_never_grows_below_minimum_even_from_a_smaller_seed(self) -> None:
        self.assertEqual(gd.next_backoff(0.1, 1.0, 10.0), 2.0)


class HandleSegmentJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.work_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_fetches_selections_image_and_posts_one_result_per_selection(self) -> None:
        api = FakeApiClient()
        api.selections_by_job["job-1"] = {
            "image_key": "uploads/p/u/image.png",
            "selections": [
                {"selection_id": "sel-a", "text": "vase"},
                {"selection_id": "sel-b", "text": "lamp"},
            ],
        }
        api.inputs[("job-1", "image")] = b"fake-png-bytes"

        mask_path = self.work_dir / "sel-a-mask.png"
        mask_path.write_bytes(b"mask-bytes")
        sam31 = FakeSam31Client(
            response={
                "results": {
                    "sel-a": {"status": "segmented", "score": 0.9, "alternatives": [], "mask_path": str(mask_path)},
                    "sel-b": {"status": "failed", "score": None, "alternatives": [], "reason": "nothing found"},
                }
            }
        )

        status = gd.handle_segment_job(api, sam31, {"job_id": "job-1"}, self.work_dir)

        self.assertEqual(status, "done")
        self.assertEqual(len(sam31.calls), 1)
        _image_path, _output_dir, selections = sam31.calls[0]
        self.assertEqual(selections, api.selections_by_job["job-1"]["selections"])

        by_selection = {entry[1]: entry for entry in api.selection_results}
        self.assertEqual(by_selection["sel-a"][2]["status"], "segmented")
        self.assertTrue(by_selection["sel-a"][3])  # mask bytes were attached
        self.assertEqual(by_selection["sel-b"][2]["status"], "failed")
        self.assertFalse(by_selection["sel-b"][3])  # no mask for a failed selection

    def test_no_pending_selections_does_nothing(self) -> None:
        api = FakeApiClient()
        api.selections_by_job["job-1"] = {"selections": []}
        sam31 = FakeSam31Client()
        status = gd.handle_segment_job(api, sam31, {"job_id": "job-1"}, self.work_dir)
        self.assertEqual(status, "no_selections")
        self.assertEqual(sam31.calls, [])
        self.assertEqual(api.selection_results, [])

    def test_sam31_unavailable_fails_the_whole_job_without_blocking_other_jobs(self) -> None:
        api = FakeApiClient()
        api.selections_by_job["job-1"] = {
            "image_key": "image.png",
            "selections": [{"selection_id": "sel-a", "text": "vase"}],
        }
        api.inputs[("job-1", "image")] = b"bytes"
        sam31 = FakeSam31Client(error=ConnectionRefusedError("no server"))

        status = gd.handle_segment_job(api, sam31, {"job_id": "job-1"}, self.work_dir)

        self.assertEqual(status, "failed")
        self.assertEqual(len(api.failed_jobs), 1)
        self.assertEqual(api.failed_jobs[0][0], "job-1")
        self.assertEqual(api.selection_results, [])

    def test_missing_result_for_a_selection_is_reported_as_failed(self) -> None:
        api = FakeApiClient()
        api.selections_by_job["job-1"] = {
            "image_key": "image.png",
            "selections": [{"selection_id": "sel-a", "text": "vase"}],
        }
        api.inputs[("job-1", "image")] = b"bytes"
        sam31 = FakeSam31Client(response={"results": {}})

        gd.handle_segment_job(api, sam31, {"job_id": "job-1"}, self.work_dir)

        self.assertEqual(len(api.selection_results), 1)
        self.assertEqual(api.selection_results[0][2]["status"], "failed")


class HandleReconstructJobTests(unittest.TestCase):
    def test_claim_run_renew_complete_sequence(self) -> None:
        api = FakeApiClient()
        worker = FakeWorkerServerClient(statuses=[{"status": "running"}, {"status": "running"}, {"status": "complete"}])
        clock = ManualClock()

        status = gd.handle_reconstruct_job(
            api,
            worker,
            {"job_id": "job-1", "subject_hint": "vase"},
            renew_interval=20.0,
            poll_interval=30.0,
            max_wait=1000.0,
            sleep=clock.sleep,
            now=clock.now,
        )

        self.assertEqual(status, "complete")
        self.assertEqual(worker.submitted, [("job-1", "vase")])
        # Two "running" polls 30s apart cross the 20s renew mark before the
        # third poll reports "complete".
        self.assertGreaterEqual(api.renew_calls, 1)

    def test_lease_lost_mid_run_stops_the_dispatcher_from_continuing(self) -> None:
        api = FakeApiClient()
        api.renew_results = [False]
        worker = FakeWorkerServerClient(statuses=[{"status": "running"}])
        clock = ManualClock()

        status = gd.handle_reconstruct_job(
            api,
            worker,
            {"job_id": "job-1"},
            renew_interval=10.0,
            poll_interval=15.0,
            max_wait=1000.0,
            sleep=clock.sleep,
            now=clock.now,
        )

        self.assertEqual(status, "lease_lost")

    def test_times_out_if_worker_server_never_finishes(self) -> None:
        api = FakeApiClient()
        worker = FakeWorkerServerClient(statuses=[{"status": "running"}])
        clock = ManualClock()

        status = gd.handle_reconstruct_job(
            api,
            worker,
            {"job_id": "job-1"},
            renew_interval=1000.0,
            poll_interval=10.0,
            max_wait=25.0,
            sleep=clock.sleep,
            now=clock.now,
        )

        self.assertEqual(status, "timeout")

    def test_failed_status_from_worker_server_is_returned(self) -> None:
        api = FakeApiClient()
        worker = FakeWorkerServerClient(statuses=[{"status": "failed"}])
        clock = ManualClock()
        status = gd.handle_reconstruct_job(
            api, worker, {"job_id": "job-1"}, sleep=clock.sleep, now=clock.now
        )
        self.assertEqual(status, "failed")


class RunOnceTests(unittest.TestCase):
    """Exercises the per-iteration dispatch logic: segment-first priority,
    a 204/None claim leading to no work (backoff in `main()`'s caller), and
    the reconstruct concurrency slot."""

    def _config(self, gpu_concurrency: int = 1) -> gd.DispatcherConfig:
        return gd.DispatcherConfig(
            api_url="http://api.invalid",
            worker_token="token",
            worker_id="gpu-1",
            sam31_server_url="http://sam31.invalid",
            worker_server_url="http://worker.invalid",
            gpu_concurrency=gpu_concurrency,
            work_dir=Path(tempfile.mkdtemp()),
        )

    def test_idle_returns_false_and_claims_nothing(self) -> None:
        api = FakeApiClient()  # claim_queue empty -> None every time
        sam31 = FakeSam31Client()
        worker = FakeWorkerServerClient(statuses=[{"status": "complete"}])
        slots = threading.Semaphore(1)

        did_work = gd.run_once(api, sam31, worker, self._config(), slots)

        self.assertFalse(did_work)

    def test_segment_job_is_claimed_and_run_inline(self) -> None:
        api = FakeApiClient()
        api.claim_queue = [{"job_id": "seg-1", "kind": "segment"}, None]
        api.selections_by_job["seg-1"] = {"selections": []}
        sam31 = FakeSam31Client()
        worker = FakeWorkerServerClient(statuses=[{"status": "complete"}])
        slots = threading.Semaphore(1)

        did_work = gd.run_once(api, sam31, worker, self._config(), slots)

        self.assertTrue(did_work)

    def test_reconstruct_job_only_claimed_when_a_concurrency_slot_is_free(self) -> None:
        api = FakeApiClient()
        # No segment job; a reconstruct job is available.
        api.claim_queue = [None, {"job_id": "rec-1", "kind": "reconstruct"}]
        sam31 = FakeSam31Client()
        worker = FakeWorkerServerClient(statuses=[{"status": "complete"}])
        slots = threading.Semaphore(1)
        # Occupy the only slot -- as if a reconstruct job were already running.
        slots.acquire()

        started: list[dict] = []
        did_work = gd.run_once(
            api, sam31, worker, self._config(), slots, start_reconstruct=started.append
        )

        self.assertFalse(did_work)
        self.assertEqual(started, [])

    def test_reconstruct_job_is_handed_to_start_reconstruct_when_a_slot_is_free(self) -> None:
        api = FakeApiClient()
        api.claim_queue = [None, {"job_id": "rec-1", "kind": "reconstruct"}]
        sam31 = FakeSam31Client()
        worker = FakeWorkerServerClient(statuses=[{"status": "complete"}])
        slots = threading.Semaphore(1)

        started: list[dict] = []
        did_work = gd.run_once(
            api, sam31, worker, self._config(), slots, start_reconstruct=started.append
        )

        self.assertTrue(did_work)
        self.assertEqual(started, [{"job_id": "rec-1", "kind": "reconstruct"}])


if __name__ == "__main__":
    unittest.main()
