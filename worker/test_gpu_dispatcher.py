"""Build Plan step 27: unit tests for `gpu_dispatcher.py`'s testable core.

Every test here runs against fake `ApiClient`/`Sam31Client`/
`WorkerServerClient` stand-ins -- no real HTTP, no GPU, no AWS. The three
real client classes only wrap `urllib.request` calls (the adapter
boundary); this file never exercises those, matching the same pattern as
`test_segment_sam31_local.py`.

Run with `python -m unittest test_gpu_dispatcher.py` from this directory.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError

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
        self.released: list[tuple[str, str]] = []
        self.claimed_kinds: list[list[str]] = []
        self.renew_calls = 0

    def claim(self, kinds: list[str]) -> dict | None:
        self.claimed_kinds.append(list(kinds))
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

    def release_job(self, job_id: str, reason: str) -> bool:
        self.released.append((job_id, reason))
        return True


class FakeSam31Client:
    def __init__(self, response=None, error: Exception | None = None, healthy: bool = True) -> None:
        self.response = response or {"results": {}}
        self.error = error
        self.healthy = healthy
        self.calls: list[tuple[Path, Path, list]] = []

    def health(self, timeout: float = 5.0) -> bool:
        return self.healthy

    def segment_many(self, image_path, output_dir, selections, timeout=180.0):
        self.calls.append((image_path, output_dir, selections))
        if self.error is not None:
            raise self.error
        return self.response


class FakeWorkerServerClient:
    def __init__(self, statuses: list, submit_error: Exception | None = None, is_ready: bool = True) -> None:
        # A status entry that is an Exception is raised (worker unreachable).
        self._statuses = list(statuses)
        self.submit_error = submit_error
        self.is_ready = is_ready
        self.submitted: list[tuple[str, str]] = []
        self.status_calls = 0
        self.ready_calls = 0

    def submit(self, job_id: str, subject_hint: str, timeout: float = 10.0) -> None:
        if self.submit_error is not None:
            raise self.submit_error
        self.submitted.append((job_id, subject_hint))

    def status(self, job_id: str, timeout: float = 10.0) -> dict:
        self.status_calls += 1
        entry = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
        if isinstance(entry, Exception):
            raise entry
        return entry

    def ready(self, timeout: float = 5.0) -> bool:
        self.ready_calls += 1
        return self.is_ready


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

    def test_sam31_unavailable_releases_the_job_instead_of_leaving_it_leased(self) -> None:
        api = FakeApiClient()
        api.selections_by_job["job-1"] = {
            "image_key": "image.png",
            "selections": [{"selection_id": "sel-a", "text": "vase"}],
        }
        api.inputs[("job-1", "image")] = b"bytes"
        sam31 = FakeSam31Client(error=ConnectionRefusedError("no server"))

        status = gd.handle_segment_job(api, sam31, {"job_id": "job-1"}, self.work_dir)

        self.assertEqual(status, "released")
        self.assertEqual([job for job, _ in api.released], ["job-1"])
        self.assertIn("SAM 3.1", api.released[0][1])
        self.assertEqual(api.failed_jobs, [])
        self.assertEqual(api.selection_results, [])

    def test_sam31_failing_the_same_job_repeatedly_fails_it_on_the_last_strike(self) -> None:
        api = FakeApiClient()
        api.selections_by_job["job-1"] = {
            "image_key": "image.png",
            "selections": [{"selection_id": "sel-a", "text": "vase"}],
        }
        api.inputs[("job-1", "image")] = b"bytes"
        sam31 = FakeSam31Client(error=TimeoutError("timed out"))
        gate = gd.HandoverGate(cooldown=0.0, max_strikes=3)

        statuses = [gd.handle_segment_job(api, sam31, {"job_id": "job-1"}, self.work_dir, gate) for _ in range(3)]

        self.assertEqual(statuses, ["released", "released", "failed"])
        self.assertEqual(len(api.released), 2)
        self.assertEqual([job for job, _ in api.failed_jobs], ["job-1"])
        self.assertIn("gave up after 3 attempts", api.failed_jobs[0][1])

    def test_passes_each_selections_vlm_box_through_to_sam31(self) -> None:
        api = FakeApiClient()
        selections = [
            {"selection_id": "sel-a", "text": "green armchair", "box": [422, 261, 618, 460]},
            {"selection_id": "sel-b", "text": "green armchair", "box": [582, 264, 739, 451]},
            {"selection_id": "sel-c", "text": "lamp", "box": None},
        ]
        api.selections_by_job["job-1"] = {"image_key": "room.jpg", "selections": selections}
        api.inputs[("job-1", "image")] = b"bytes"
        sam31 = FakeSam31Client(response={"results": {}})

        gd.handle_segment_job(api, sam31, {"job_id": "job-1"}, self.work_dir)

        self.assertEqual(sam31.calls[0][2], selections)
        self.assertTrue(str(sam31.calls[0][0]).endswith(".jpg"))

    def test_removes_its_scratch_dir_when_done(self) -> None:
        api = FakeApiClient()
        api.selections_by_job["job-1"] = {
            "image_key": "image.png",
            "selections": [{"selection_id": "sel-a", "text": "vase"}],
        }
        api.inputs[("job-1", "image")] = b"bytes"
        mask_path = self.work_dir / "job-1" / "masks" / "sel-a.png"

        class WritingSam31(FakeSam31Client):
            def segment_many(self, image_path, output_dir, selections, timeout=180.0):
                output_dir.mkdir(parents=True, exist_ok=True)
                mask_path.write_bytes(b"mask")
                return {"results": {"sel-a": {"status": "segmented", "score": 0.9, "mask_path": str(mask_path)}}}

        status = gd.handle_segment_job(api, WritingSam31(), {"job_id": "job-1"}, self.work_dir)

        self.assertEqual(status, "done")
        self.assertTrue(api.selection_results[0][3])  # the mask was read before cleanup
        self.assertFalse((self.work_dir / "job-1").exists())

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

    def test_times_out_if_worker_server_never_finishes_and_releases_the_job(self) -> None:
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
        self.assertEqual([job for job, _ in api.released], ["job-1"])

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


class HandOverFailureTests(unittest.TestCase):
    """docs/WEB_TO_QUEST_PIPELINE.md 7: a claimed job whose hand-over fails
    is released at once -- never left leased with nothing running it."""

    def _run(self, api, worker, gate=None, **kwargs):
        clock = ManualClock()
        defaults = dict(renew_interval=60.0, poll_interval=2.0, max_wait=1800.0, lost_grace=30.0)
        defaults.update(kwargs)
        return gd.handle_reconstruct_job(
            api, worker, {"job_id": "job-1", "subject_hint": "chair"},
            gate=gate or gd.HandoverGate(cooldown=0.0), sleep=clock.sleep, now=clock.now, **defaults
        ), clock

    def test_worker_503_models_not_ready_releases_the_job_at_once(self) -> None:
        api = FakeApiClient()
        error = HTTPError("http://worker/worker/jobs", 503, "Service Unavailable", {}, None)
        worker = FakeWorkerServerClient(statuses=[{"status": "unknown"}], submit_error=error)

        status, _clock = self._run(api, worker)

        self.assertEqual(status, "released")
        self.assertEqual(len(api.released), 1)
        self.assertIn("503", api.released[0][1])
        self.assertEqual(worker.status_calls, 0)  # nothing to babysit
        self.assertEqual(api.renew_calls, 0)

    def test_connection_refused_and_timeout_release_the_job(self) -> None:
        for error in (URLError(ConnectionRefusedError(111, "Connection refused")), TimeoutError("timed out")):
            api = FakeApiClient()
            worker = FakeWorkerServerClient(statuses=[{"status": "unknown"}], submit_error=error)
            status, _clock = self._run(api, worker)
            self.assertEqual(status, "released")
            self.assertEqual([job for job, _ in api.released], ["job-1"])

    def test_worker_restart_mid_job_releases_it_after_the_grace_period(self) -> None:
        api = FakeApiClient()
        # Accepted, ran, then the worker restarted and forgot the job.
        worker = FakeWorkerServerClient(statuses=[{"status": "running"}, {"status": "running"}, {"status": "unknown"}])

        status, clock = self._run(api, worker, lost_grace=10.0)

        self.assertEqual(status, "released")
        self.assertIn("lost the job", api.released[0][1])
        self.assertLess(clock.t, 30.0)  # seconds, not the 900 s lease

    def test_worker_unreachable_while_babysitting_releases_after_the_longer_grace(self) -> None:
        api = FakeApiClient()
        worker = FakeWorkerServerClient(statuses=[{"status": "running"}, ConnectionRefusedError("down")])

        status, clock = self._run(api, worker, lost_grace=10.0, unreachable_grace=60.0)

        self.assertEqual(status, "released")
        self.assertIn("unreachable", api.released[0][1])
        self.assertGreaterEqual(clock.t, 60.0)  # a busy/unresponsive worker gets the longer grace
        self.assertLess(clock.t, 70.0)

    def test_a_brief_blip_shorter_than_the_grace_is_tolerated(self) -> None:
        api = FakeApiClient()
        worker = FakeWorkerServerClient(
            statuses=[{"status": "running"}] + [TimeoutError("busy")] * 20 + [{"status": "running"}, {"status": "complete"}]
        )

        status, _clock = self._run(api, worker, lost_grace=10.0, unreachable_grace=60.0)  # ~40 s unresponsive

        self.assertEqual(status, "complete")
        self.assertEqual(api.released, [])

    def test_renewal_errors_are_retried_not_fatal(self) -> None:
        api = FakeApiClient()
        calls = {"n": 0}

        def flaky_renew(job_id: str) -> bool:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionResetError("api blip")
            return True

        api.renew_lease = flaky_renew  # type: ignore[method-assign]
        worker = FakeWorkerServerClient(statuses=[{"status": "running"}] * 40 + [{"status": "complete"}])

        status, _clock = self._run(api, worker, renew_interval=10.0, poll_interval=5.0)

        self.assertEqual(status, "complete")
        self.assertGreaterEqual(calls["n"], 2)

    def test_repeated_hand_over_failures_fail_the_job_on_the_last_strike(self) -> None:
        api = FakeApiClient()
        worker = FakeWorkerServerClient(statuses=[{"status": "unknown"}], submit_error=TimeoutError("timed out"))
        gate = gd.HandoverGate(cooldown=0.0, max_strikes=2)

        first, _ = self._run(api, worker, gate=gate)
        second, _ = self._run(api, worker, gate=gate)

        self.assertEqual((first, second), ("released", "failed"))
        self.assertEqual([job for job, _ in api.failed_jobs], ["job-1"])

    def test_a_409_already_submitted_is_not_a_hand_over_failure(self) -> None:
        class Worker409(FakeWorkerServerClient):
            def submit(self, job_id, subject_hint, timeout=10.0):
                self.submitted.append((job_id, subject_hint))  # real client swallows 409

        api = FakeApiClient()
        status, _ = self._run(api, Worker409(statuses=[{"status": "complete"}]))
        self.assertEqual(status, "complete")
        self.assertEqual(api.released, [])


class HandoverGateTests(unittest.TestCase):
    def test_cooldown_blocks_the_kind_then_doubles_and_resets_on_success(self) -> None:
        clock = ManualClock()
        gate = gd.HandoverGate(cooldown=10.0, cooldown_max=25.0, max_strikes=5, now=clock.now)
        self.assertTrue(gate.can_claim("reconstruct"))
        gate.handover_failed("reconstruct", "a")
        self.assertFalse(gate.can_claim("reconstruct"))
        self.assertTrue(gate.can_claim("segment"))  # per kind
        clock.t = 10.0
        self.assertTrue(gate.can_claim("reconstruct"))
        gate.handover_failed("reconstruct", "a")  # 20 s now
        clock.t = 29.0
        self.assertFalse(gate.can_claim("reconstruct"))
        clock.t = 30.0
        self.assertTrue(gate.can_claim("reconstruct"))
        gate.handover_failed("reconstruct", "b")  # capped at 25 s
        clock.t = 55.0
        self.assertTrue(gate.can_claim("reconstruct"))
        gate.handover_ok("reconstruct")
        gate.handover_failed("reconstruct", "c")  # back to 10 s
        clock.t = 65.0
        self.assertTrue(gate.can_claim("reconstruct"))


class DynamoJobReleaserTests(unittest.TestCase):
    class FakeTable:
        def __init__(self, item):
            self.item = item
            self.puts: list[dict] = []
            self.fail_condition = False

        def get_item(self, Key, ConsistentRead=False):
            return {"Item": dict(self.item)} if self.item is not None else {}

        def put_item(self, Item, ConditionExpression, ExpressionAttributeNames, ExpressionAttributeValues):
            if self.fail_condition or self.item.get("lease_owner") != ExpressionAttributeValues[":owner"]:
                error = Exception("conditional")
                error.response = {"Error": {"Code": "ConditionalCheckFailedException"}}
                raise error
            self.puts.append(Item)
            self.item = Item

    def _item(self, owner="gpu-host-1", status="running"):
        doc = {"job_id": "j1", "status": status, "lease_owner": owner, "lease_expires_at": "2026-09-27T05:00:00Z",
               "attempts": 0, "kind": "reconstruct", "created_at": "2026-09-27T04:00:00Z"}
        return {"pk": "JOB#j1", "sk": "META", "document": json.dumps(doc), "status": status,
                "lease_owner": owner or "", "gsi1pk": "PROJECTJOBS#p", "gsi1sk": "2026#j1",
                "gsi2pk": f"JOBQ#{status}", "gsi2sk": "2026#j1"}

    def test_releases_our_running_job_back_to_the_queue(self) -> None:
        table = self.FakeTable(self._item())
        self.assertTrue(gd.DynamoJobReleaser(table).release("j1", "gpu-host-1"))
        put = table.puts[0]
        self.assertEqual((put["status"], put["lease_owner"], put["gsi2pk"]), ("queued", "", "JOBQ#queued"))
        self.assertEqual((put["gsi1pk"], put["gsi2sk"]), ("PROJECTJOBS#p", "2026#j1"))  # order kept
        doc = json.loads(put["document"])
        self.assertEqual((doc["status"], doc["lease_owner"], doc["lease_expires_at"]), ("queued", None, None))
        self.assertEqual(doc["attempts"], 0)  # never ran: no retry consumed

    def test_never_touches_a_job_someone_else_holds_or_that_finished(self) -> None:
        for item in (self._item(owner="other-worker"), self._item(owner=None, status="ready")):
            table = self.FakeTable(item)
            self.assertFalse(gd.DynamoJobReleaser(table).release("j1", "gpu-host-1"))
            self.assertEqual(table.puts, [])

    def test_a_lost_race_is_a_clean_false(self) -> None:
        table = self.FakeTable(self._item())
        table.fail_condition = True
        self.assertFalse(gd.DynamoJobReleaser(table).release("j1", "gpu-host-1"))


class ApiReleaseJobTests(unittest.TestCase):
    def test_uses_the_api_route_when_the_backend_has_one(self) -> None:
        api = gd.ApiClient("http://api.invalid", "t", "gpu-host-1")
        api._post_form = lambda path, fields, timeout=30.0: {"released": True}  # type: ignore[method-assign]
        self.assertTrue(api.release_job("j1", "worker 503"))

    def test_falls_back_to_dynamodb_when_the_route_is_missing(self) -> None:
        api = gd.ApiClient("http://api.invalid", "t", "gpu-host-1")

        def missing(path, fields, timeout=30.0):
            raise HTTPError(path, 404, "Not Found", {}, None)

        released: list[tuple[str, str]] = []

        class Fallback:
            def release(self, job_id, worker_id):
                released.append((job_id, worker_id))
                return True

        api._post_form = missing  # type: ignore[method-assign]
        api.fallback_releaser = Fallback()
        self.assertTrue(api.release_job("j1", "worker 503"))
        self.assertEqual(released, [("j1", "gpu-host-1")])

    def test_without_route_or_fallback_it_reports_false_and_never_raises(self) -> None:
        api = gd.ApiClient("http://api.invalid", "t", "gpu-host-1")

        def missing(path, fields, timeout=30.0):
            raise HTTPError(path, 404, "Not Found", {}, None)

        api._post_form = missing  # type: ignore[method-assign]
        self.assertFalse(api.release_job("j1", "worker 503"))


class _HealthServer:
    """A real loopback HTTP server answering GET /worker/health and /health."""

    def __init__(self, body: dict | None, code: int = 200):
        payload = json.dumps(body or {}).encode()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class ReadinessProbeTests(unittest.TestCase):
    def _worker_ready(self, body: dict) -> bool:
        server = _HealthServer(body)
        try:
            return gd.WorkerServerClient(server.url).ready()
        finally:
            server.close()

    def test_worker_ready_only_when_status_ready_with_queue_room(self) -> None:
        self.assertTrue(self._worker_ready({"status": "ready", "queue_size": 0, "gpu_concurrency": 1}))
        self.assertFalse(self._worker_ready({"status": "loading", "models_loaded": False, "queue_size": 0}))
        self.assertFalse(self._worker_ready({"status": "error", "error": "boom"}))
        self.assertFalse(self._worker_ready({"status": "ready", "queue_size": 1, "gpu_concurrency": 1}))

    def test_nothing_listening_means_not_ready(self) -> None:
        server = _HealthServer({"status": "ready"})
        url = server.url
        server.close()
        self.assertFalse(gd.WorkerServerClient(url).ready(timeout=1.0))
        self.assertFalse(gd.Sam31Client(url).health(timeout=1.0))

    def test_sam31_health(self) -> None:
        server = _HealthServer({"status": "ready"})
        try:
            self.assertTrue(gd.Sam31Client(server.url).health())
        finally:
            server.close()


class RunOnceReadinessGateTests(unittest.TestCase):
    def _config(self) -> gd.DispatcherConfig:
        return gd.DispatcherConfig(
            api_url="http://api.invalid", worker_token="token", worker_id="gpu-1",
            sam31_server_url="http://sam31.invalid", worker_server_url="http://worker.invalid",
            work_dir=Path(tempfile.mkdtemp()),
        )

    def test_never_claims_a_segment_job_while_sam31_is_not_ready(self) -> None:
        api = FakeApiClient()
        api.claim_queue = [{"job_id": "seg-1", "kind": "segment"}]
        worker = FakeWorkerServerClient(statuses=[{"status": "complete"}], is_ready=False)

        did_work = gd.run_once(api, FakeSam31Client(healthy=False), worker, self._config(), threading.Semaphore(1))

        self.assertFalse(did_work)
        self.assertEqual(api.claimed_kinds, [])  # nothing claimed at all
        self.assertEqual(api.claim_queue, [{"job_id": "seg-1", "kind": "segment"}])

    def test_never_claims_a_reconstruct_job_while_the_worker_is_loading(self) -> None:
        api = FakeApiClient()
        api.claim_queue = [None, {"job_id": "rec-1", "kind": "reconstruct"}]
        worker = FakeWorkerServerClient(statuses=[{"status": "complete"}], is_ready=False)
        slots = threading.Semaphore(1)
        started: list[dict] = []

        did_work = gd.run_once(api, FakeSam31Client(), worker, self._config(), slots, start_reconstruct=started.append)

        self.assertFalse(did_work)
        self.assertEqual(api.claimed_kinds, [["segment"]])  # reconstruct never claimed
        self.assertEqual(started, [])
        self.assertTrue(slots.acquire(blocking=False))  # the slot was given back

    def test_waits_while_loading_then_claims_and_runs_once_ready(self) -> None:
        api = FakeApiClient()
        api.claim_queue = [{"job_id": "rec-1", "kind": "reconstruct"}]
        api.claim = lambda kinds: (api.claimed_kinds.append(list(kinds)) or  # type: ignore[method-assign]
                                   (api.claim_queue.pop(0) if kinds == ["reconstruct"] and api.claim_queue else None))
        worker = FakeWorkerServerClient(statuses=[{"status": "complete"}], is_ready=False)
        slots = threading.Semaphore(1)
        started: list[dict] = []
        gate = gd.HandoverGate()

        for _ in range(3):  # model load in progress
            self.assertFalse(gd.run_once(api, FakeSam31Client(), worker, self._config(), slots,
                                         start_reconstruct=started.append, gate=gate))
        worker.is_ready = True
        self.assertTrue(gd.run_once(api, FakeSam31Client(), worker, self._config(), slots,
                                    start_reconstruct=started.append, gate=gate))
        self.assertEqual(started, [{"job_id": "rec-1", "kind": "reconstruct"}])

    def test_no_claims_of_a_kind_during_its_hand_over_cooldown(self) -> None:
        clock = ManualClock()
        gate = gd.HandoverGate(cooldown=15.0, now=clock.now)
        gate.handover_failed("reconstruct", "rec-0")
        api = FakeApiClient()
        # Positional fake: each iteration's segment claim pops one entry first.
        api.claim_queue = [None, None, {"job_id": "rec-1", "kind": "reconstruct"}]
        worker = FakeWorkerServerClient(statuses=[{"status": "complete"}])
        started: list[dict] = []

        gd.run_once(api, FakeSam31Client(), worker, self._config(), threading.Semaphore(1),
                    start_reconstruct=started.append, gate=gate)
        self.assertEqual(started, [])
        self.assertEqual(worker.ready_calls, 0)
        clock.t = 16.0
        gd.run_once(api, FakeSam31Client(), worker, self._config(), threading.Semaphore(1),
                    start_reconstruct=started.append, gate=gate)
        self.assertEqual(started, [{"job_id": "rec-1", "kind": "reconstruct"}])


if __name__ == "__main__":
    unittest.main()
