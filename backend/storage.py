"""Durable persistence for SketchScape authoring state.

This module owns the *only* place the API keeps projects, catalog assets,
experience-blueprint revisions, and immutable publication records. It replaces
the previous process-memory dictionaries so state survives an API restart.

The storage surface is defined once by ``AuthoringStore``. Two backends
implement it:

- ``LocalJsonStore`` (default): a single-process, JSON-file-backed store with
  atomic replace-on-write. It needs no external services and powers the local
  demo and the tests.
- ``DynamoDbStore``: an AWS-backed store for concurrency-safe cloud durability.
  It imports ``boto3`` lazily so the dependency stays optional; selecting this
  backend without ``boto3`` or table configuration fails with a clear message.

Route handlers depend only on ``AuthoringStore``; ``create_store()`` picks the
backend from ``SKETCHSCAPE_STORAGE_BACKEND`` (``local`` or ``dynamodb``).

Design constraints (aligned with docs/INFRASTRUCTURE_ROADMAP.md):

- The local backend adds no runtime dependency and writes atomically so a crash
  mid-write never corrupts existing state.
- Published revisions are the source of truth. Publishing appends an immutable
  ``PublicationRecord`` and never rewrites blueprint revisions.
- Both backends persist metadata only. Uploaded images and reconstruction
  artifacts continue to live under the data directory managed by ``main.py``.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a circular import.
    from main import (
        ConnectionInsight,
        Contribution,
        Contributor,
        ExperienceBlueprint,
        ProjectAsset,
        ProjectRecord,
        PublicationRecord,
        ReconstructionJob,
        RoomBuild,
        UploadRecord,
    )
    from letters import Letter, LetterOpenRecord

    from guided_tour import GuidedTour
    from guide import GuideSession, GuideTurn


STATE_VERSION = 3


class RevisionConflict(Exception):
    """Raised when an append would collide with an existing revision/sequence.

    Both backends raise this from ``append_blueprint``/``append_publication``
    when a conditional write loses a race with another writer (another API
    instance, another headset, NemoClaw). Callers retry with the next number.
    """


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


# -- room builds (docs/WEB_TO_QUEST_PIPELINE.md 1) ----------------------------
#
# A room build moves requested -> claimed -> syncing -> building -> packaging
# -> ready | failed. "Active" = not terminal; a project has at most one.
# "Leased" = held by a runner, which must keep reporting (each report bumps
# ``updated_at``) or the build goes back to ``requested``.
ROOM_BUILD_ACTIVE_STATUSES = ("requested", "claimed", "syncing", "building", "packaging")
ROOM_BUILD_LEASED_STATUSES = ("claimed", "syncing", "building", "packaging")
ROOM_BUILD_TERMINAL_STATUSES = ("ready", "failed")
ROOM_BUILD_REQUEUED_MESSAGE = "The Unity machine stopped reporting; waiting for a runner to pick it up again."


class RoomBuildConflict(Exception):
    """A project already has an active (non-terminal) room build."""

    def __init__(self, active) -> None:
        super().__init__(f"Project already has an active room build: {active.build_id} ({active.status}).")
        self.active = active


def iso_z(value: datetime) -> str:
    """UTC ISO 8601 with a ``Z`` suffix -- the same shape Pydantic gives datetimes."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _room_builds_newest_first(builds) -> list:
    return sorted(builds, key=lambda build: (build.created_at, build.build_id), reverse=True)


def _newest_active_room_build(builds):
    for build in _room_builds_newest_first(builds):
        if build.status in ROOM_BUILD_ACTIVE_STATUSES:
            return build
    return None


def _room_build_is_stale(build, now: datetime, lease_seconds: float) -> bool:
    if build.status not in ROOM_BUILD_LEASED_STATUSES:
        return False
    reported = _parse_iso(build.updated_at)
    return reported is None or reported <= now - timedelta(seconds=lease_seconds)


def _requeued_room_build(build, now: datetime):
    # ``runner_id`` is kept: if that runner was only slow (a long agent build)
    # and reports again before anyone else claims the build, it re-attaches.
    return build.model_copy(
        update={"status": "requested", "message": ROOM_BUILD_REQUEUED_MESSAGE, "updated_at": iso_z(now)}
    )


def _model_types() -> tuple[type, type, type, type]:
    """Return the authoring models, imported lazily to avoid a cycle.

    ``storage`` and ``main`` reference each other, so the models are imported
    at call time rather than at module import time.
    """
    from main import (
        ExperienceBlueprint,
        ProjectAsset,
        ProjectRecord,
        PublicationRecord,
    )

    return ProjectRecord, ProjectAsset, ExperienceBlueprint, PublicationRecord


def _social_model_types() -> tuple[type, type, type]:
    """Return the Shared Room social models, imported lazily to avoid a cycle.

    Kept separate from ``_model_types`` so existing call sites that destructure
    a fixed 4-tuple don't need to change.
    """
    from main import ConnectionInsight, Contribution, Contributor

    return Contributor, Contribution, ConnectionInsight


def _job_upload_types() -> tuple[type, type]:
    from main import ReconstructionJob, UploadRecord

    return ReconstructionJob, UploadRecord


def _tour_model_type() -> type:
    """Return ``GuidedTour``, imported lazily like the other model helpers above.

    ``guided_tour`` never imports ``storage`` or ``main``, so this is a
    one-directional import, not a cycle.
    """
    from guided_tour import GuidedTour

    return GuidedTour


def _guide_model_types() -> tuple[type, type]:
    """Return ``(GuideSession, GuideTurn)``, imported lazily.

    ``guide`` doesn't import ``storage`` at module scope (only for
    ``TYPE_CHECKING``), so this is one-directional, like ``_tour_model_type``.
    """
    from guide import GuideSession, GuideTurn

    return GuideSession, GuideTurn


def _job_status_type():
    from main import JobStatus

    return JobStatus


def _job_max_attempts() -> int:
    return max(1, int(os.environ.get("SKETCHSCAPE_JOB_MAX_ATTEMPTS", "2")))


def _letter_model_types() -> tuple[type, type]:
    from letters import Letter, LetterOpenRecord

    return Letter, LetterOpenRecord


def _room_build_type() -> type:
    from main import RoomBuild

    return RoomBuild


_ACTIVE_JOB_STATUSES = ("queued", "running", "mask_review")


class AuthoringStore(ABC):
    """The persistence surface every backend must implement.

    Callers mutate the returned model instances and then call the matching
    ``save_*``/``append_*`` method to persist the change; this mirrors how the
    in-memory dictionaries were used originally, so route handlers stay simple.
    """

    @abstractmethod
    def load(self) -> None:
        """Rehydrate any cached state from the backing store."""

    @abstractmethod
    def get_project(self, project_id: str) -> ProjectRecord | None: ...

    @abstractmethod
    def save_project(self, project: ProjectRecord) -> None: ...

    @abstractmethod
    def get_asset(self, asset_id: str) -> ProjectAsset | None: ...

    @abstractmethod
    def save_asset(self, asset: ProjectAsset) -> None: ...

    @abstractmethod
    def list_blueprints(self, project_id: str) -> list[ExperienceBlueprint]: ...

    @abstractmethod
    def append_blueprint(self, blueprint: ExperienceBlueprint) -> None: ...

    @abstractmethod
    def list_publications(self, project_id: str) -> list[PublicationRecord]: ...

    @abstractmethod
    def append_publication(self, record: PublicationRecord) -> None: ...

    @abstractmethod
    def get_live_revision(self, project_id: str) -> int | None:
        """Return the revision currently live for a project, or None if unset.

        This is the authoritative "what's published" pointer — readers
        (compiled-scene, the room API) should use this, not the cached
        ``ProjectRecord.published_revision``.
        """

    @abstractmethod
    def set_live_revision(self, project_id: str, expected: int | None, new: int) -> bool:
        """Compare-and-set the live revision pointer.

        Succeeds only if the current live revision equals ``expected``
        (``None`` means "nothing published yet"). Returns whether the update
        applied; never raises on a losing race.
        """

    @abstractmethod
    def list_contributors(self, project_id: str) -> list[Contributor]: ...

    @abstractmethod
    def append_contributor(self, contributor: Contributor) -> None: ...

    @abstractmethod
    def list_contributions(self, project_id: str) -> list[Contribution]: ...

    @abstractmethod
    def append_contribution(self, contribution: Contribution) -> None: ...

    @abstractmethod
    def list_connection_insights(self, project_id: str) -> list[ConnectionInsight]: ...

    @abstractmethod
    def append_connection_insight(self, insight: ConnectionInsight) -> None: ...

    # -- durable jobs + uploads (Build Plan step 26) ------------------------

    @abstractmethod
    def save_job(self, job: ReconstructionJob) -> None: ...

    @abstractmethod
    def get_job(self, job_id: str) -> ReconstructionJob | None: ...

    @abstractmethod
    def list_project_jobs(self, project_id: str, active_only: bool = False) -> list[ReconstructionJob]: ...

    @abstractmethod
    def claim_next_job(
        self, worker_id: str, kinds: list[str], lease_seconds: int
    ) -> ReconstructionJob | None: ...

    @abstractmethod
    def renew_lease(self, job_id: str, lease_owner: str, lease_seconds: int) -> bool: ...

    @abstractmethod
    def complete_job(self, job_id: str, lease_owner: str, updates: dict) -> bool: ...

    @abstractmethod
    def release_expired_leases(self) -> int: ...

    @abstractmethod
    def release_job(self, job_id: str, lease_owner: str) -> bool:
        """Put a running job its owner couldn't hand over back in the queue
        (lease cleared, ``attempts`` unchanged). False unless ``lease_owner``
        holds the lease of a running job."""

    @abstractmethod
    def link_asset(self, project_id: str, asset_id: str) -> None: ...

    @abstractmethod
    def list_linked_asset_ids(self, project_id: str) -> list[str]: ...

    @abstractmethod
    def save_upload_record(self, upload: UploadRecord) -> None: ...

    @abstractmethod
    def get_upload_record(self, project_id: str, upload_id: str) -> UploadRecord | None: ...

    @abstractmethod
    def list_upload_records(self, project_id: str) -> list[UploadRecord]: ...

    # -- letters (Build Plan step 28) ----------------------------------------

    @abstractmethod
    def save_letter(self, letter: Letter) -> None: ...

    @abstractmethod
    def get_letter(self, project_id: str, letter_id: str) -> Letter | None: ...

    @abstractmethod
    def list_letters(self, project_id: str) -> list[Letter]: ...

    @abstractmethod
    def record_letter_open(
        self, project_id: str, letter_id: str, contributor_id: str, opened_at: datetime
    ) -> bool:
        """Conditional put of one recipient's open. Returns True if this call
        created the record, False if it already existed (idempotent -- a
        repeat open never writes a duplicate item)."""

    @abstractmethod
    def list_letter_opens(self, project_id: str, letter_id: str) -> list[LetterOpenRecord]: ...

    @abstractmethod
    def letters_version(self, project_id: str) -> int:
        """A cheap, monotonically non-decreasing count of every open
        recorded for this project, used to fold letter state into the
        room-state ETag (room-api-and-ownership polling contract)."""

    def persist_all(self) -> None:  # pragma: no cover - default no-op
        """Force a full flush. Backends that write eagerly need not override."""

    # -- room builds (docs/WEB_TO_QUEST_PIPELINE.md 1) -----------------------

    @abstractmethod
    def create_room_build(self, build: "RoomBuild") -> None:
        """Store a new build; raises ``RoomBuildConflict`` (carrying the active
        build) when the project already has a non-terminal one."""

    @abstractmethod
    def get_room_build(self, build_id: str, project_id: str | None = None) -> "RoomBuild | None": ...

    @abstractmethod
    def list_room_builds(self, project_id: str) -> list["RoomBuild"]:
        """Every build of the project, newest first."""

    @abstractmethod
    def claim_next_room_build(self, runner_id: str, now: datetime) -> "RoomBuild | None":
        """The oldest ``requested`` build (any project), now ``claimed`` by ``runner_id``."""

    @abstractmethod
    def update_room_build(
        self,
        build: "RoomBuild",
        *,
        expected_status: str,
        expected_runner_id: str,
        expected_updated_at: str,
    ) -> bool:
        """Compare-and-set write of the whole build. False (never raises) when
        the stored build no longer matches the expected status/runner/time."""

    @abstractmethod
    def release_stale_room_builds(
        self, lease_seconds: float, now: datetime, project_id: str | None = None
    ) -> int:
        """Put leased builds whose runner stopped reporting back to ``requested``."""

    # -- guided tours (Build Plan step 30) -----------------------------------

    @abstractmethod
    def append_tour(self, tour: "GuidedTour") -> None:
        """Conditional put on TOUR#<version padded>; raises RevisionConflict on collision."""

    @abstractmethod
    def get_tour(self, project_id: str, tour_version: int) -> "GuidedTour | None": ...

    @abstractmethod
    def list_tours(self, project_id: str) -> list["GuidedTour"]: ...

    @abstractmethod
    def get_active_tour_version(self, project_id: str) -> int | None:
        """The TOURLIVE pointer: which tour_version the in-room guide performs, if any."""

    @abstractmethod
    def activate_tour(self, project_id: str, expected: int | None, new_version: int) -> "GuidedTour | None":
        """Compare-and-set TOURLIVE to ``new_version``, same pattern as ``set_live_revision``.

        On success, flips the previously active tour's ``status`` to
        ``retired`` and the new one's to ``active``, and returns the updated
        (now-active) ``GuidedTour``. Returns ``None`` (never raises) on a
        losing race against ``expected``, so callers can turn it into a 409.
        """

    # -- guide sessions (Build Plan step 32) ---------------------------------

    @abstractmethod
    def create_guide_session(self, session: "GuideSession") -> None:
        """First write for a new session. Also retires any prior active
        session for the same ``(project_id, account)`` -- one active session
        per account, per the guide-runtime contract."""

    @abstractmethod
    def get_guide_session(self, project_id: str, session_id: str) -> "GuideSession | None": ...

    @abstractmethod
    def get_active_guide_session_id(self, project_id: str, account: str) -> str | None: ...

    @abstractmethod
    def update_guide_session(
        self, project_id: str, session_id: str, expected_turn_count: int, updates: dict
    ) -> "GuideSession | None":
        """Compare-and-set on ``turn_count``. ``updates`` is the full new
        session document (``GuideSession.model_dump(mode="json")``), matching
        the caller's ``expected_turn_count`` -> ``expected_turn_count + 1``
        transition. Returns the updated session, or ``None`` (never raises)
        on a losing race so the caller can 409 with the stored turn."""

    @abstractmethod
    def append_guide_turn(self, project_id: str, turn: "GuideTurn") -> None:
        """Append-only ``GUIDETURN#<session_id>#<turn_seq padded>`` audit row."""

    @abstractmethod
    def get_guide_turn_by_client_id(
        self, project_id: str, session_id: str, client_turn_id: str
    ) -> "GuideTurn | None":
        """Idempotency lookup: the stored turn for a repeated ``client_turn_id``."""

    @abstractmethod
    def get_guide_turn_by_seq(self, project_id: str, session_id: str, turn_seq: int) -> "GuideTurn | None": ...

    @abstractmethod
    def increment_guide_daily_usage(self, project_id: str, date_key: str) -> int:
        """Atomic ADD counter for ``GUIDEUSAGE#<yyyy-mm-dd>`` (``date_key``);
        returns the new total. Used against
        ``SKETCHSCAPE_GUIDE_DAILY_MODEL_TURNS`` to fall back to the mock
        provider once a project's daily model-turn budget is spent."""


class LocalJsonStore(AuthoringStore):
    """A JSON-file-backed, single-process authoring store.

    All public methods keep the in-memory maps and the on-disk snapshot in
    sync. This is a durable local store, not a concurrency-safe multi-writer
    store; the roadmap keeps DynamoDB for that.
    """

    def __init__(self, state_path: Path) -> None:
        self._state_path = Path(state_path)
        self._lock = threading.RLock()
        self.projects: dict[str, ProjectRecord] = {}
        self.assets: dict[str, ProjectAsset] = {}
        self.blueprints: dict[str, list[ExperienceBlueprint]] = {}
        self.publications: dict[str, list[PublicationRecord]] = {}
        self.contributors: dict[str, list[Contributor]] = {}
        self.contributions: dict[str, list[Contribution]] = {}
        self.connection_insights: dict[str, list[ConnectionInsight]] = {}
        self.live_revisions: dict[str, int] = {}
        self.jobs: dict[str, ReconstructionJob] = {}
        self.uploads: dict[str, dict[str, UploadRecord]] = {}
        self.asset_links: dict[str, list[str]] = {}
        # Step 28: project_id -> letter_id -> Letter; project_id -> letter_id
        # -> contributor_id -> LetterOpenRecord.
        self.letters: dict[str, dict[str, Letter]] = {}
        self.letter_opens: dict[str, dict[str, dict[str, LetterOpenRecord]]] = {}
        # project_id -> build_id -> RoomBuild (docs/WEB_TO_QUEST_PIPELINE.md 1).
        self.room_builds: dict[str, dict[str, "RoomBuild"]] = {}

        self.tours: dict[str, list["GuidedTour"]] = {}
        self.tour_live: dict[str, int] = {}

        # Step 32: project_id -> session_id -> GuideSession; project_id ->
        # account -> active session_id; project_id -> session_id -> turn_seq
        # -> GuideTurn; project_id -> date_key -> count.
        self.guide_sessions: dict[str, dict[str, "GuideSession"]] = {}
        self.guide_active_sessions: dict[str, dict[str, str]] = {}
        self.guide_turns: dict[str, dict[str, dict[int, "GuideTurn"]]] = {}
        self.guide_daily_usage: dict[str, dict[str, int]] = {}

    # -- lifecycle ---------------------------------------------------------

    def load(self) -> None:
        """Rehydrate state from disk. A missing or empty file starts empty."""
        ProjectRecord, ProjectAsset, ExperienceBlueprint, PublicationRecord = _model_types()
        Contributor, Contribution, ConnectionInsight = _social_model_types()

        with self._lock:
            self.projects = {}
            self.assets = {}
            self.blueprints = {}
            self.publications = {}
            self.contributors = {}
            self.contributions = {}
            self.connection_insights = {}
            self.live_revisions = {}
            self.jobs = {}
            self.uploads = {}
            self.asset_links = {}
            self.letters = {}
            self.letter_opens = {}
            self.room_builds = {}

            self.tours = {}
            self.tour_live = {}
            self.guide_sessions = {}
            self.guide_active_sessions = {}
            self.guide_turns = {}
            self.guide_daily_usage = {}
            if not self._state_path.is_file():
                return
            try:
                raw = json.loads(self._state_path.read_text("utf-8") or "{}")
            except (json.JSONDecodeError, OSError):
                # A corrupt snapshot must not crash startup. Preserve the bad
                # file for inspection and begin from an empty, valid state.
                self._quarantine_corrupt_state()
                return
            ReconstructionJob, UploadRecord = _job_upload_types()
            for record in raw.get("projects", []):
                project = ProjectRecord.model_validate(record)
                self.projects[project.project_id] = project
            for record in raw.get("assets", []):
                asset = ProjectAsset.model_validate(record)
                self.assets[asset.asset_id] = asset
            for project_id, revisions in raw.get("blueprints", {}).items():
                self.blueprints[project_id] = [
                    ExperienceBlueprint.model_validate(item) for item in revisions
                ]
            for project_id, records in raw.get("publications", {}).items():
                self.publications[project_id] = [
                    PublicationRecord.model_validate(item) for item in records
                ]
            for project_id, records in raw.get("contributors", {}).items():
                self.contributors[project_id] = [
                    Contributor.model_validate(item) for item in records
                ]
            for project_id, records in raw.get("contributions", {}).items():
                self.contributions[project_id] = [
                    Contribution.model_validate(item) for item in records
                ]
            for project_id, records in raw.get("connection_insights", {}).items():
                self.connection_insights[project_id] = [
                    ConnectionInsight.model_validate(item) for item in records
                ]
            # Absent in files written before this field existed — default to
            # unset per project rather than failing to load an older snapshot.
            for project_id, revision in raw.get("live_revisions", {}).items():
                self.live_revisions[project_id] = int(revision)
            for record in raw.get("jobs", []):
                job = ReconstructionJob.model_validate(record)
                self.jobs[job.job_id] = job
            for project_id, records in raw.get("uploads", {}).items():
                self.uploads[project_id] = {
                    item["upload_id"]: UploadRecord.model_validate(item) for item in records
                }
            for project_id, asset_ids in raw.get("asset_links", {}).items():
                self.asset_links[project_id] = list(asset_ids)
            Letter, LetterOpenRecord = _letter_model_types()
            for project_id, records in raw.get("letters", {}).items():
                self.letters[project_id] = {
                    item["letter_id"]: Letter.model_validate(item) for item in records
                }
            for project_id, by_letter in raw.get("letter_opens", {}).items():
                self.letter_opens[project_id] = {
                    letter_id: {
                        item["contributor_id"]: LetterOpenRecord.model_validate(item) for item in records
                    }
                    for letter_id, records in by_letter.items()
                }

            if raw.get("room_builds"):
                RoomBuild = _room_build_type()
                for project_id, records in raw.get("room_builds", {}).items():
                    self.room_builds[project_id] = {
                        item["build_id"]: RoomBuild.model_validate(item) for item in records
                    }

            GuidedTour = _tour_model_type()
            for project_id, versions in raw.get("tours", {}).items():
                self.tours[project_id] = [GuidedTour.model_validate(item) for item in versions]
            for project_id, version in raw.get("tour_live", {}).items():
                self.tour_live[project_id] = int(version)

            GuideSession, GuideTurn = _guide_model_types()
            for project_id, records in raw.get("guide_sessions", {}).items():
                self.guide_sessions[project_id] = {
                    item["session_id"]: GuideSession.model_validate(item) for item in records
                }
            for project_id, by_account in raw.get("guide_active_sessions", {}).items():
                self.guide_active_sessions[project_id] = dict(by_account)
            for project_id, by_session in raw.get("guide_turns", {}).items():
                self.guide_turns[project_id] = {
                    session_id: {item["turn_seq"]: GuideTurn.model_validate(item) for item in records}
                    for session_id, records in by_session.items()
                }
            for project_id, by_date in raw.get("guide_daily_usage", {}).items():
                self.guide_daily_usage[project_id] = {date_key: int(count) for date_key, count in by_date.items()}

    def _quarantine_corrupt_state(self) -> None:
        backup = self._state_path.with_suffix(
            self._state_path.suffix + f".corrupt-{int(datetime.now(UTC).timestamp())}"
        )
        try:
            self._state_path.replace(backup)
        except OSError:
            pass

    # -- persistence -------------------------------------------------------

    def _snapshot(self) -> dict[str, object]:
        return {
            "version": STATE_VERSION,
            "saved_at": _utc_now_iso(),
            "projects": [project.model_dump(mode="json") for project in self.projects.values()],
            "assets": [asset.model_dump(mode="json") for asset in self.assets.values()],
            "blueprints": {
                project_id: [item.model_dump(mode="json") for item in revisions]
                for project_id, revisions in self.blueprints.items()
            },
            "publications": {
                project_id: [record.model_dump(mode="json") for record in records]
                for project_id, records in self.publications.items()
            },
            "contributors": {
                project_id: [item.model_dump(mode="json") for item in records]
                for project_id, records in self.contributors.items()
            },
            "contributions": {
                project_id: [item.model_dump(mode="json") for item in records]
                for project_id, records in self.contributions.items()
            },
            "connection_insights": {
                project_id: [item.model_dump(mode="json") for item in records]
                for project_id, records in self.connection_insights.items()
            },
            "live_revisions": dict(self.live_revisions),
            "jobs": [job.model_dump(mode="json") for job in self.jobs.values()],
            "uploads": {
                project_id: [item.model_dump(mode="json") for item in records.values()]
                for project_id, records in self.uploads.items()
            },
            "asset_links": {project_id: list(ids) for project_id, ids in self.asset_links.items()},
            "letters": {
                project_id: [letter.model_dump(mode="json") for letter in letters.values()]
                for project_id, letters in self.letters.items()
            },
            "letter_opens": {
                project_id: {
                    letter_id: [record.model_dump(mode="json") for record in records.values()]
                    for letter_id, records in by_letter.items()
                }
                for project_id, by_letter in self.letter_opens.items()
            },
            "room_builds": {
                project_id: [build.model_dump(mode="json") for build in builds.values()]
                for project_id, builds in self.room_builds.items()
            },

            "tours": {
                project_id: [item.model_dump(mode="json") for item in versions]
                for project_id, versions in self.tours.items()
            },
            "tour_live": dict(self.tour_live),

            "guide_sessions": {
                project_id: [item.model_dump(mode="json") for item in sessions.values()]
                for project_id, sessions in self.guide_sessions.items()
            },
            "guide_active_sessions": {
                project_id: dict(by_account) for project_id, by_account in self.guide_active_sessions.items()
            },
            "guide_turns": {
                project_id: {
                    session_id: [item.model_dump(mode="json") for item in turns.values()]
                    for session_id, turns in by_session.items()
                }
                for project_id, by_session in self.guide_turns.items()
            },
            "guide_daily_usage": {
                project_id: dict(by_date) for project_id, by_date in self.guide_daily_usage.items()
            },
        }

    def _flush(self) -> None:
        """Atomically write the full snapshot to disk."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._snapshot(), indent=2, sort_keys=False)
        # Write to a temp file in the same directory, then atomically replace so
        # a reader never observes a half-written file.
        fd, tmp_name = tempfile.mkstemp(
            prefix=self._state_path.name + ".", suffix=".tmp", dir=self._state_path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self._state_path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    # -- projects ----------------------------------------------------------

    def get_project(self, project_id: str) -> ProjectRecord | None:
        return self.projects.get(project_id)

    def save_project(self, project: ProjectRecord) -> None:
        with self._lock:
            self.projects[project.project_id] = project
            self.blueprints.setdefault(project.project_id, [])
            self.publications.setdefault(project.project_id, [])
            self.contributors.setdefault(project.project_id, [])
            self.contributions.setdefault(project.project_id, [])
            self.connection_insights.setdefault(project.project_id, [])
            self._flush()

    # -- assets ------------------------------------------------------------

    def get_asset(self, asset_id: str) -> ProjectAsset | None:
        return self.assets.get(asset_id)

    def save_asset(self, asset: ProjectAsset) -> None:
        with self._lock:
            self.assets[asset.asset_id] = asset
            self._flush()

    # -- blueprints --------------------------------------------------------

    def list_blueprints(self, project_id: str) -> list[ExperienceBlueprint]:
        return self.blueprints.setdefault(project_id, [])

    def append_blueprint(self, blueprint: ExperienceBlueprint) -> None:
        with self._lock:
            existing = self.blueprints.setdefault(blueprint.project_id, [])
            if blueprint.revision != len(existing) + 1:
                raise RevisionConflict(
                    f"Blueprint revision {blueprint.revision} for project "
                    f"{blueprint.project_id} is out of sequence (expected "
                    f"{len(existing) + 1})."
                )
            existing.append(blueprint)
            self._flush()

    # -- publications ------------------------------------------------------

    def list_publications(self, project_id: str) -> list[PublicationRecord]:
        return self.publications.setdefault(project_id, [])

    def append_publication(self, record: PublicationRecord) -> None:
        """Append an immutable publication record.

        Publication history is append-only. A newly published revision records
        a new entry; earlier records are never rewritten, so the log always
        reflects exactly which revision was live at each publish time.
        """
        with self._lock:
            self.publications.setdefault(record.project_id, []).append(record)
            self._flush()

    # -- live revision pointer ----------------------------------------------

    def get_live_revision(self, project_id: str) -> int | None:
        return self.live_revisions.get(project_id)

    def set_live_revision(self, project_id: str, expected: int | None, new: int) -> bool:
        with self._lock:
            current = self.live_revisions.get(project_id)
            if current != expected:
                return False
            self.live_revisions[project_id] = new
            self._flush()
            return True

    # -- contributors --------------------------------------------------------

    def list_contributors(self, project_id: str) -> list[Contributor]:
        return self.contributors.setdefault(project_id, [])

    def append_contributor(self, contributor: Contributor) -> None:
        with self._lock:
            self.contributors.setdefault(contributor.project_id, []).append(contributor)
            self._flush()

    # -- contributions -------------------------------------------------------

    def list_contributions(self, project_id: str) -> list[Contribution]:
        return self.contributions.setdefault(project_id, [])

    def append_contribution(self, contribution: Contribution) -> None:
        with self._lock:
            self.contributions.setdefault(contribution.project_id, []).append(contribution)
            self._flush()

    # -- connection insights ---------------------------------------------------

    def list_connection_insights(self, project_id: str) -> list[ConnectionInsight]:
        return self.connection_insights.setdefault(project_id, [])

    def append_connection_insight(self, insight: ConnectionInsight) -> None:
        with self._lock:
            self.connection_insights.setdefault(insight.project_id, []).append(insight)
            self._flush()

    def persist_all(self) -> None:
        """Force a full flush; useful after a batch of in-place mutations."""
        with self._lock:
            self._flush()

    # -- durable jobs (Build Plan step 26) ----------------------------------

    def save_job(self, job: ReconstructionJob) -> None:
        with self._lock:
            self.jobs[job.job_id] = job
            self._flush()

    def get_job(self, job_id: str) -> ReconstructionJob | None:
        return self.jobs.get(job_id)

    def list_project_jobs(self, project_id: str, active_only: bool = False) -> list[ReconstructionJob]:
        jobs = [job for job in self.jobs.values() if job.project_id == project_id]
        if active_only:
            jobs = [job for job in jobs if job.status in _ACTIVE_JOB_STATUSES]
        jobs.sort(key=lambda job: job.created_at, reverse=True)
        return jobs

    def claim_next_job(
        self, worker_id: str, kinds: list[str], lease_seconds: int
    ) -> ReconstructionJob | None:
        JobStatus = _job_status_type()
        with self._lock:
            candidates = sorted(
                (job for job in self.jobs.values() if job.status == "queued" and job.kind in kinds),
                key=lambda job: job.created_at,
            )
            if not candidates:
                return None
            job = candidates[0]
            now = datetime.now(UTC)
            job.status = JobStatus.RUNNING
            job.lease_owner = worker_id
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.updated_at = now
            self._flush()
            return job

    def renew_lease(self, job_id: str, lease_owner: str, lease_seconds: int) -> bool:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None or job.lease_owner != lease_owner:
                return False
            job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
            self._flush()
            return True

    def complete_job(self, job_id: str, lease_owner: str, updates: dict) -> bool:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None or job.lease_owner != lease_owner:
                return False
            for key, value in updates.items():
                setattr(job, key, value)
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = datetime.now(UTC)
            self._flush()
            return True

    def release_expired_leases(self) -> int:
        JobStatus = _job_status_type()
        max_attempts = _job_max_attempts()
        now = datetime.now(UTC)
        released = 0
        with self._lock:
            for job in self.jobs.values():
                if job.status != "running" or job.lease_expires_at is None or job.lease_expires_at > now:
                    continue
                job.attempts += 1
                job.lease_owner = None
                job.lease_expires_at = None
                job.updated_at = now
                if job.attempts >= max_attempts:
                    job.status = JobStatus.FAILED
                    job.error = job.error or "Exceeded maximum retry attempts after lease expiry."
                else:
                    job.status = JobStatus.QUEUED
                released += 1
            if released:
                self._flush()
        return released

    def release_job(self, job_id: str, lease_owner: str) -> bool:
        JobStatus = _job_status_type()
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None or job.status != "running" or job.lease_owner != lease_owner:
                return False
            job.status = JobStatus.QUEUED
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = datetime.now(UTC)
            self._flush()
            return True

    # -- project -> asset links (Build Plan step 26) ------------------------

    def link_asset(self, project_id: str, asset_id: str) -> None:
        with self._lock:
            links = self.asset_links.setdefault(project_id, [])
            if asset_id not in links:
                links.append(asset_id)
                self._flush()

    def list_linked_asset_ids(self, project_id: str) -> list[str]:
        return list(self.asset_links.get(project_id, []))

    # -- uploads (Build Plan step 26) ---------------------------------------

    def save_upload_record(self, upload: UploadRecord) -> None:
        with self._lock:
            self.uploads.setdefault(upload.project_id, {})[upload.upload_id] = upload
            self._flush()

    def get_upload_record(self, project_id: str, upload_id: str) -> UploadRecord | None:
        return self.uploads.get(project_id, {}).get(upload_id)

    def list_upload_records(self, project_id: str) -> list[UploadRecord]:
        return list(self.uploads.get(project_id, {}).values())

    # -- letters (Build Plan step 28) ----------------------------------------

    def save_letter(self, letter: Letter) -> None:
        with self._lock:
            self.letters.setdefault(letter.project_id, {})[letter.letter_id] = letter
            self._flush()

    def get_letter(self, project_id: str, letter_id: str) -> Letter | None:
        return self.letters.get(project_id, {}).get(letter_id)

    def list_letters(self, project_id: str) -> list[Letter]:
        return list(self.letters.get(project_id, {}).values())

    def record_letter_open(
        self, project_id: str, letter_id: str, contributor_id: str, opened_at: datetime
    ) -> bool:
        _, LetterOpenRecord = _letter_model_types()
        with self._lock:
            opens = self.letter_opens.setdefault(project_id, {}).setdefault(letter_id, {})
            if contributor_id in opens:
                return False
            opens[contributor_id] = LetterOpenRecord(
                project_id=project_id, letter_id=letter_id, contributor_id=contributor_id, opened_at=opened_at
            )
            self._flush()
            return True

    def list_letter_opens(self, project_id: str, letter_id: str) -> list[LetterOpenRecord]:
        return list(self.letter_opens.get(project_id, {}).get(letter_id, {}).values())

    def letters_version(self, project_id: str) -> int:
        return sum(len(opens) for opens in self.letter_opens.get(project_id, {}).values())

    # -- room builds (docs/WEB_TO_QUEST_PIPELINE.md 1) -----------------------
    # Copies go in and out, so a caller mutating a returned build can never
    # change stored state behind update_room_build's compare-and-set.

    def create_room_build(self, build: "RoomBuild") -> None:
        with self._lock:
            builds = self.room_builds.setdefault(build.project_id, {})
            active = _newest_active_room_build(builds.values())
            if active is not None:
                raise RoomBuildConflict(active.model_copy())
            builds[build.build_id] = build.model_copy()
            self._flush()

    def get_room_build(self, build_id: str, project_id: str | None = None) -> "RoomBuild | None":
        with self._lock:
            pools = [self.room_builds.get(project_id, {})] if project_id is not None else self.room_builds.values()
            for builds in pools:
                if build_id in builds:
                    return builds[build_id].model_copy()
            return None

    def list_room_builds(self, project_id: str) -> list["RoomBuild"]:
        with self._lock:
            builds = self.room_builds.get(project_id, {}).values()
            return [build.model_copy() for build in _room_builds_newest_first(builds)]

    def claim_next_room_build(self, runner_id: str, now: datetime) -> "RoomBuild | None":
        with self._lock:
            requested = [
                build
                for builds in self.room_builds.values()
                for build in builds.values()
                if build.status == "requested"
            ]
            if not requested:
                return None
            oldest = min(requested, key=lambda build: (build.created_at, build.build_id))
            claimed = oldest.model_copy(
                update={"status": "claimed", "runner_id": runner_id, "message": "", "updated_at": iso_z(now)}
            )
            self.room_builds[claimed.project_id][claimed.build_id] = claimed
            self._flush()
            return claimed.model_copy()

    def update_room_build(
        self,
        build: "RoomBuild",
        *,
        expected_status: str,
        expected_runner_id: str,
        expected_updated_at: str,
    ) -> bool:
        with self._lock:
            current = self.room_builds.get(build.project_id, {}).get(build.build_id)
            if (
                current is None
                or current.status != expected_status
                or current.runner_id != expected_runner_id
                or current.updated_at != expected_updated_at
            ):
                return False
            self.room_builds[build.project_id][build.build_id] = build.model_copy()
            self._flush()
            return True

    def release_stale_room_builds(
        self, lease_seconds: float, now: datetime, project_id: str | None = None
    ) -> int:
        with self._lock:
            if project_id is not None:
                pools = [self.room_builds.get(project_id, {})]
            else:
                pools = list(self.room_builds.values())
            released = 0
            for builds in pools:
                for build_id, build in list(builds.items()):
                    if _room_build_is_stale(build, now, lease_seconds):
                        builds[build_id] = _requeued_room_build(build, now)
                        released += 1
            if released:
                self._flush()
            return released

    # -- guided tours (Build Plan step 30) -----------------------------------

    def list_tours(self, project_id: str) -> list["GuidedTour"]:
        return self.tours.setdefault(project_id, [])

    def append_tour(self, tour: "GuidedTour") -> None:
        with self._lock:
            existing = self.tours.setdefault(tour.project_id, [])
            if tour.tour_version != len(existing) + 1:
                raise RevisionConflict(
                    f"Tour version {tour.tour_version} for project {tour.project_id} is out of "
                    f"sequence (expected {len(existing) + 1})."
                )
            existing.append(tour)
            self._flush()

    def get_tour(self, project_id: str, tour_version: int) -> "GuidedTour | None":
        existing = self.tours.get(project_id, [])
        if tour_version < 1 or tour_version > len(existing):
            return None
        return existing[tour_version - 1]

    def get_active_tour_version(self, project_id: str) -> int | None:
        return self.tour_live.get(project_id)

    def activate_tour(self, project_id: str, expected: int | None, new_version: int) -> "GuidedTour | None":
        with self._lock:
            current = self.tour_live.get(project_id)
            if current != expected:
                return None
            existing = self.tours.get(project_id, [])
            if new_version < 1 or new_version > len(existing):
                return None
            if current is not None and 1 <= current <= len(existing):
                existing[current - 1] = existing[current - 1].model_copy(update={"status": "retired"})
            existing[new_version - 1] = existing[new_version - 1].model_copy(update={"status": "active"})
            self.tour_live[project_id] = new_version
            self._flush()
            return existing[new_version - 1]

    # -- guide sessions (Build Plan step 32) ---------------------------------

    def create_guide_session(self, session: "GuideSession") -> None:
        with self._lock:
            by_account = self.guide_active_sessions.setdefault(session.project_id, {})
            previous_id = by_account.get(session.account)
            project_sessions = self.guide_sessions.setdefault(session.project_id, {})
            if previous_id is not None and previous_id in project_sessions:
                project_sessions[previous_id] = project_sessions[previous_id].model_copy(update={"active": False})
            project_sessions[session.session_id] = session
            by_account[session.account] = session.session_id
            self._flush()

    def get_guide_session(self, project_id: str, session_id: str) -> "GuideSession | None":
        return self.guide_sessions.get(project_id, {}).get(session_id)

    def get_active_guide_session_id(self, project_id: str, account: str) -> str | None:
        return self.guide_active_sessions.get(project_id, {}).get(account)

    def update_guide_session(
        self, project_id: str, session_id: str, expected_turn_count: int, updates: dict
    ) -> "GuideSession | None":
        GuideSession, _ = _guide_model_types()
        with self._lock:
            current = self.guide_sessions.get(project_id, {}).get(session_id)
            if current is None or current.turn_count != expected_turn_count:
                return None
            updated = GuideSession.model_validate(updates)
            self.guide_sessions[project_id][session_id] = updated
            self._flush()
            return updated

    def append_guide_turn(self, project_id: str, turn: "GuideTurn") -> None:
        with self._lock:
            session_turns = self.guide_turns.setdefault(project_id, {}).setdefault(turn.session_id, {})
            session_turns[turn.turn_seq] = turn
            self._flush()

    def get_guide_turn_by_client_id(
        self, project_id: str, session_id: str, client_turn_id: str
    ) -> "GuideTurn | None":
        for turn in self.guide_turns.get(project_id, {}).get(session_id, {}).values():
            if turn.client_turn_id == client_turn_id:
                return turn
        return None

    def get_guide_turn_by_seq(self, project_id: str, session_id: str, turn_seq: int) -> "GuideTurn | None":
        return self.guide_turns.get(project_id, {}).get(session_id, {}).get(turn_seq)

    def increment_guide_daily_usage(self, project_id: str, date_key: str) -> int:
        with self._lock:
            per_project = self.guide_daily_usage.setdefault(project_id, {})
            per_project[date_key] = per_project.get(date_key, 0) + 1
            self._flush()
            return per_project[date_key]


class DynamoDbStore(AuthoringStore):
    """A DynamoDB-backed authoring store for concurrency-safe cloud durability.

    Each entity type maps to one item family in a single table using a
    partition/sort key layout so a project's assets, blueprints, and
    publications are queryable together:

        PK = "PROJECT#<project_id>"
        SK = "META"                     -> project record
        SK = "BLUEPRINT#<0-padded rev>" -> one blueprint revision
        SK = "PUBLICATION#<0-padded seq>" -> one append-only publication record
        PK = "ASSET#<asset_id>"
        SK = "META"                     -> catalog asset

    Blueprint and publication ordering is handled with zero-padded sort keys so
    a ``Query`` returns them in creation order. ``boto3`` is imported lazily so
    it remains an optional dependency; nothing here runs unless this backend is
    explicitly selected.
    """

    _SORT_WIDTH = 12  # zero-padded width for ordered sort keys

    def __init__(self, table_name: str, *, region_name: str | None = None) -> None:
        if not table_name:
            raise RuntimeError(
                "DynamoDbStore requires a table name. Set SKETCHSCAPE_DYNAMODB_TABLE."
            )
        self._table_name = table_name
        self._region_name = region_name
        self._lock = threading.RLock()
        self._table = None  # resolved lazily in load()

    # -- lifecycle ---------------------------------------------------------

    def _resource(self):
        try:
            import boto3  # noqa: PLC0415 - optional dependency, imported lazily
        except ImportError as error:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "The DynamoDB storage backend requires boto3. Install it with "
                "`pip install boto3`, or use SKETCHSCAPE_STORAGE_BACKEND=local."
            ) from error
        return boto3.resource("dynamodb", region_name=self._region_name)

    def load(self) -> None:
        """Bind the table handle and verify the step-26 GSIs are provisioned.

        Reads (beyond this check) happen per request, not cached here.
        """
        with self._lock:
            if self._table is None:
                self._table = self._resource().Table(self._table_name)
                self._check_required_indexes()

    def _check_required_indexes(self) -> None:
        """Fail fast if GSI1/GSI2 (step 26 jobs + membership queries) are missing.

        The table starts with no GSIs (docs/DATA_ARCHITECTURE.md). Adding them
        is a Terraform change (infra/aws/main.tf) that needs explicit approval
        before ``terraform apply`` -- this only checks whether it has already
        been applied, it never applies it itself.
        """
        try:
            description = self._table.meta.client.describe_table(TableName=self._table_name)
        except Exception as error:  # noqa: BLE001 - surfaced as a clear RuntimeError below
            raise RuntimeError(
                f"Could not describe DynamoDB table {self._table_name!r}: {error}"
            ) from error
        present = {
            gsi["IndexName"] for gsi in description["Table"].get("GlobalSecondaryIndexes", [])
        }
        missing = {"gsi1", "gsi2"} - present
        if missing:
            raise RuntimeError(
                f"DynamoDB table {self._table_name!r} is missing required index(es) "
                f"{sorted(missing)}. Apply the GSI1 (gsi1pk/gsi1sk)/GSI2 (gsi2pk/gsi2sk) "
                "Terraform change in infra/aws/main.tf (see docs/DATA_ARCHITECTURE.md) "
                "before selecting SKETCHSCAPE_STORAGE_BACKEND=dynamodb."
            )

    def _require_table(self):
        if self._table is None:
            self.load()
        return self._table

    @staticmethod
    def _seq_key(prefix: str, value: int) -> str:
        return f"{prefix}#{value:0{DynamoDbStore._SORT_WIDTH}d}"

    @staticmethod
    def _is_conditional_check_failure(error: Exception) -> bool:
        """Identify a DynamoDB conditional-write rejection, without importing
        botocore at module scope (boto3/botocore stay optional dependencies).
        """
        try:
            from botocore.exceptions import ClientError  # noqa: PLC0415
        except ImportError:  # pragma: no cover - botocore ships with boto3
            return False
        if not isinstance(error, ClientError):
            return False
        return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"

    # -- projects ----------------------------------------------------------

    def get_project(self, project_id: str) -> ProjectRecord | None:
        ProjectRecord, *_ = _model_types()
        response = self._require_table().get_item(
            Key={"pk": f"PROJECT#{project_id}", "sk": "META"}
        )
        item = response.get("Item")
        if item is None:
            return None
        return ProjectRecord.model_validate_json(item["document"])

    def save_project(self, project: ProjectRecord) -> None:
        with self._lock:
            self._require_table().put_item(
                Item={
                    "pk": f"PROJECT#{project.project_id}",
                    "sk": "META",
                    "document": project.model_dump_json(),
                }
            )

    # -- assets ------------------------------------------------------------

    def get_asset(self, asset_id: str) -> ProjectAsset | None:
        _, ProjectAsset, *_ = _model_types()
        response = self._require_table().get_item(
            Key={"pk": f"ASSET#{asset_id}", "sk": "META"}
        )
        item = response.get("Item")
        if item is None:
            return None
        return ProjectAsset.model_validate_json(item["document"])

    def save_asset(self, asset: ProjectAsset) -> None:
        with self._lock:
            self._require_table().put_item(
                Item={
                    "pk": f"ASSET#{asset.asset_id}",
                    "sk": "META",
                    "document": asset.model_dump_json(),
                }
            )

    # -- blueprints --------------------------------------------------------

    def _query_children(self, project_id: str, sk_prefix: str, *, consistent: bool = False) -> list[dict]:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        table = self._require_table()
        items: list[dict] = []
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(f"PROJECT#{project_id}")
            & Key("sk").begins_with(f"{sk_prefix}#"),
            "ScanIndexForward": True,
        }
        if consistent:
            kwargs["ConsistentRead"] = True
        while True:
            response = table.query(**kwargs)
            items.extend(response.get("Items", []))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
            kwargs["ExclusiveStartKey"] = start_key
        return items

    def list_blueprints(self, project_id: str) -> list[ExperienceBlueprint]:
        _, _, ExperienceBlueprint, _ = _model_types()
        return [
            ExperienceBlueprint.model_validate_json(item["document"])
            for item in self._query_children(project_id, "BLUEPRINT")
        ]

    def append_blueprint(self, blueprint: ExperienceBlueprint) -> None:
        """Append a blueprint revision, rejecting a collision with a sibling.

        ``self._lock`` only serializes this process; the ``ConditionExpression``
        is what actually protects against a second API instance writing the
        same revision number at the same time. On a collision this raises
        ``RevisionConflict`` so the caller (``create_blueprint``) can retry
        with the next revision number instead of silently overwriting.
        """
        with self._lock:
            try:
                self._require_table().put_item(
                    Item={
                        "pk": f"PROJECT#{blueprint.project_id}",
                        "sk": self._seq_key("BLUEPRINT", blueprint.revision),
                        "document": blueprint.model_dump_json(),
                    },
                    ConditionExpression="attribute_not_exists(sk)",
                )
            except Exception as error:  # noqa: BLE001 - narrowed below
                if self._is_conditional_check_failure(error):
                    raise RevisionConflict(
                        f"Blueprint revision {blueprint.revision} for project "
                        f"{blueprint.project_id} already exists."
                    ) from error
                raise

    # -- publications ------------------------------------------------------

    def list_publications(self, project_id: str) -> list[PublicationRecord]:
        _, _, _, PublicationRecord = _model_types()
        return [
            PublicationRecord.model_validate_json(item["document"])
            for item in self._query_children(project_id, "PUBLICATION")
        ]

    def append_publication(self, record: PublicationRecord) -> None:
        """Append an immutable publication record using an ordered sort key.

        The sort key is the next sequence number, so republishing an earlier
        revision appends a new item rather than overwriting history. The
        write is conditional on that sequence slot being free; publications
        are append-only, so on a collision (another instance grabbed the same
        slot) it's always correct to retry with the next number — no data can
        be lost by retrying, unlike a blueprint revision.
        """
        with self._lock:
            last_error: Exception | None = None
            for _ in range(5):
                next_seq = len(self._query_children(record.project_id, "PUBLICATION")) + 1
                try:
                    self._require_table().put_item(
                        Item={
                            "pk": f"PROJECT#{record.project_id}",
                            "sk": self._seq_key("PUBLICATION", next_seq),
                            "document": record.model_dump_json(),
                        },
                        ConditionExpression="attribute_not_exists(sk)",
                    )
                    return
                except Exception as error:  # noqa: BLE001 - narrowed below
                    if self._is_conditional_check_failure(error):
                        last_error = error
                        continue
                    raise
            raise RevisionConflict(
                f"Could not append a publication record for project "
                f"{record.project_id} after retries."
            ) from last_error

    # -- live revision pointer ----------------------------------------------

    def get_live_revision(self, project_id: str) -> int | None:
        response = self._require_table().get_item(
            Key={"pk": f"PROJECT#{project_id}", "sk": "LIVE"}
        )
        item = response.get("Item")
        if item is None:
            return None
        return int(item["revision"])

    def set_live_revision(self, project_id: str, expected: int | None, new: int) -> bool:
        """Compare-and-set the LIVE pointer item for a project.

        ``expected is None`` means "nothing published yet", so the condition
        requires the item not to exist at all; otherwise it requires the
        stored ``revision`` attribute to still equal ``expected``. A losing
        race returns False rather than raising, so callers can turn it into a
        409 without a try/except.
        """
        item = {"pk": f"PROJECT#{project_id}", "sk": "LIVE", "revision": new}
        if expected is None:
            kwargs: dict = {"Item": item, "ConditionExpression": "attribute_not_exists(pk)"}
        else:
            kwargs = {
                "Item": item,
                "ConditionExpression": "attribute_not_exists(pk) OR #r = :expected",
                "ExpressionAttributeNames": {"#r": "revision"},
                "ExpressionAttributeValues": {":expected": expected},
            }
        with self._lock:
            try:
                self._require_table().put_item(**kwargs)
                return True
            except Exception as error:  # noqa: BLE001 - narrowed below
                if self._is_conditional_check_failure(error):
                    return False
                raise

    # -- contributors --------------------------------------------------------

    def list_contributors(self, project_id: str) -> list[Contributor]:
        Contributor, _, _ = _social_model_types()
        return [
            Contributor.model_validate_json(item["document"])
            for item in self._query_children(project_id, "CONTRIBUTOR")
        ]

    def append_contributor(self, contributor: Contributor) -> None:
        with self._lock:
            self._require_table().put_item(
                Item={
                    "pk": f"PROJECT#{contributor.project_id}",
                    "sk": f"CONTRIBUTOR#{contributor.contributor_id}",
                    "document": contributor.model_dump_json(),
                }
            )

    # -- contributions -------------------------------------------------------

    def list_contributions(self, project_id: str) -> list[Contribution]:
        _, Contribution, _ = _social_model_types()
        return [
            Contribution.model_validate_json(item["document"])
            for item in self._query_children(project_id, "CONTRIBUTION")
        ]

    def append_contribution(self, contribution: Contribution) -> None:
        with self._lock:
            self._require_table().put_item(
                Item={
                    "pk": f"PROJECT#{contribution.project_id}",
                    "sk": f"CONTRIBUTION#{contribution.contribution_id}",
                    "document": contribution.model_dump_json(),
                }
            )

    # -- connection insights ---------------------------------------------------

    def list_connection_insights(self, project_id: str) -> list[ConnectionInsight]:
        _, _, ConnectionInsight = _social_model_types()
        return [
            ConnectionInsight.model_validate_json(item["document"])
            for item in self._query_children(project_id, "INSIGHT")
        ]

    def append_connection_insight(self, insight: ConnectionInsight) -> None:
        """Append an insight revision, exactly like `append_blueprint`.

        Insights are revisioned like blueprints, so republishing a new
        composition pass appends a new item rather than overwriting history.
        """
        with self._lock:
            self._require_table().put_item(
                Item={
                    "pk": f"PROJECT#{insight.project_id}",
                    "sk": self._seq_key("INSIGHT", insight.revision),
                    "document": insight.model_dump_json(),
                }
            )

    # -- durable jobs (Build Plan step 26) -----------------------------------
    #
    # Job = PK "JOB#<job_id>" / SK "META", with gsi1pk="PROJECTJOBS#<project_id>"
    # (batch polling for one project) and gsi2pk="JOBQ#<status>" (the GPU
    # dispatcher's claim query), both ordered by gsi*sk="<created_at>#<job_id>".
    # A job's whole document is rewritten on every save/claim/complete, exactly
    # like `save_asset` above; the conditional writes below guard against two
    # writers claiming or completing the same job at once.

    def _job_item(self, job: ReconstructionJob) -> dict:
        order_key = f"{job.created_at.isoformat()}#{job.job_id}"
        return {
            "pk": f"JOB#{job.job_id}",
            "sk": "META",
            "document": job.model_dump_json(),
            "status": str(job.status),
            "lease_owner": job.lease_owner or "",
            "gsi1pk": f"PROJECTJOBS#{job.project_id or '_none_'}",
            "gsi1sk": order_key,
            "gsi2pk": f"JOBQ#{job.status}",
            "gsi2sk": order_key,
        }

    def save_job(self, job: ReconstructionJob) -> None:
        with self._lock:
            self._require_table().put_item(Item=self._job_item(job))

    def get_job(self, job_id: str) -> ReconstructionJob | None:
        ReconstructionJob, _ = _job_upload_types()
        response = self._require_table().get_item(Key={"pk": f"JOB#{job_id}", "sk": "META"})
        item = response.get("Item")
        if item is None:
            return None
        return ReconstructionJob.model_validate_json(item["document"])

    def _query_index(
        self, index_name: str, key_condition, *, scan_index_forward: bool = True
    ) -> list[dict]:
        """Paginated ``Query`` against a GSI, mirroring ``_query_children``'s loop.

        The job-queue queries (``list_project_jobs``, ``claim_next_job``,
        ``release_expired_leases``) must see every matching item, not just the
        first page. A single unpaginated ``Query`` silently truncates at ~1 MB
        or the table's per-page item count -- for ``claim_next_job`` that can
        mean a job is never claimed because it happens to be filtered out of
        (or simply never queried into) the truncated first page, and for
        ``list_project_jobs``/``release_expired_leases`` it silently drops
        jobs from a busy project or a large backlog.
        """
        table = self._require_table()
        items: list[dict] = []
        kwargs = {
            "IndexName": index_name,
            "KeyConditionExpression": key_condition,
            "ScanIndexForward": scan_index_forward,
        }
        while True:
            response = table.query(**kwargs)
            items.extend(response.get("Items", []))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
            kwargs["ExclusiveStartKey"] = start_key
        return items

    def list_project_jobs(self, project_id: str, active_only: bool = False) -> list[ReconstructionJob]:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        ReconstructionJob, _ = _job_upload_types()
        items = self._query_index(
            "gsi1", Key("gsi1pk").eq(f"PROJECTJOBS#{project_id}"), scan_index_forward=False
        )
        jobs = [ReconstructionJob.model_validate_json(item["document"]) for item in items]
        if active_only:
            jobs = [job for job in jobs if job.status in _ACTIVE_JOB_STATUSES]
        return jobs

    def claim_next_job(
        self, worker_id: str, kinds: list[str], lease_seconds: int
    ) -> ReconstructionJob | None:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        JobStatus = _job_status_type()
        ReconstructionJob, _ = _job_upload_types()
        table = self._require_table()
        with self._lock:
            items = self._query_index("gsi2", Key("gsi2pk").eq("JOBQ#queued"), scan_index_forward=True)
            for item in items:
                job = ReconstructionJob.model_validate_json(item["document"])
                if job.kind not in kinds:
                    continue
                job.status = JobStatus.RUNNING
                job.lease_owner = worker_id
                job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
                job.updated_at = datetime.now(UTC)
                try:
                    table.put_item(
                        Item=self._job_item(job),
                        ConditionExpression="#s = :expected",
                        ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={":expected": "queued"},
                    )
                except Exception as error:  # noqa: BLE001 - narrowed below
                    if self._is_conditional_check_failure(error):
                        continue
                    raise
                return job
        return None

    def renew_lease(self, job_id: str, lease_owner: str, lease_seconds: int) -> bool:
        ReconstructionJob, _ = _job_upload_types()
        table = self._require_table()
        with self._lock:
            response = table.get_item(Key={"pk": f"JOB#{job_id}", "sk": "META"})
            item = response.get("Item")
            if item is None:
                return False
            job = ReconstructionJob.model_validate_json(item["document"])
            if job.lease_owner != lease_owner:
                return False
            job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
            job.updated_at = datetime.now(UTC)
            try:
                table.put_item(
                    Item=self._job_item(job),
                    ConditionExpression="#lo = :owner",
                    ExpressionAttributeNames={"#lo": "lease_owner"},
                    ExpressionAttributeValues={":owner": lease_owner},
                )
            except Exception as error:  # noqa: BLE001 - narrowed below
                if self._is_conditional_check_failure(error):
                    return False
                raise
            return True

    def complete_job(self, job_id: str, lease_owner: str, updates: dict) -> bool:
        ReconstructionJob, _ = _job_upload_types()
        table = self._require_table()
        with self._lock:
            response = table.get_item(Key={"pk": f"JOB#{job_id}", "sk": "META"})
            item = response.get("Item")
            if item is None:
                return False
            job = ReconstructionJob.model_validate_json(item["document"])
            if job.lease_owner != lease_owner:
                return False
            for key, value in updates.items():
                setattr(job, key, value)
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = datetime.now(UTC)
            try:
                table.put_item(
                    Item=self._job_item(job),
                    ConditionExpression="#lo = :owner",
                    ExpressionAttributeNames={"#lo": "lease_owner"},
                    ExpressionAttributeValues={":owner": lease_owner},
                )
            except Exception as error:  # noqa: BLE001 - narrowed below
                if self._is_conditional_check_failure(error):
                    return False
                raise
            return True

    def release_expired_leases(self) -> int:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        JobStatus = _job_status_type()
        ReconstructionJob, _ = _job_upload_types()
        max_attempts = _job_max_attempts()
        now = datetime.now(UTC)
        released = 0
        table = self._require_table()
        with self._lock:
            items = self._query_index("gsi2", Key("gsi2pk").eq("JOBQ#running"))
            for item in items:
                job = ReconstructionJob.model_validate_json(item["document"])
                if job.lease_expires_at is None or job.lease_expires_at > now:
                    continue
                previous_owner = job.lease_owner or ""
                job.attempts += 1
                job.lease_owner = None
                job.lease_expires_at = None
                job.updated_at = now
                if job.attempts >= max_attempts:
                    job.status = JobStatus.FAILED
                    job.error = job.error or "Exceeded maximum retry attempts after lease expiry."
                else:
                    job.status = JobStatus.QUEUED
                try:
                    table.put_item(
                        Item=self._job_item(job),
                        ConditionExpression="#lo = :owner",
                        ExpressionAttributeNames={"#lo": "lease_owner"},
                        ExpressionAttributeValues={":owner": previous_owner},
                    )
                    released += 1
                except Exception as error:  # noqa: BLE001 - narrowed below
                    if self._is_conditional_check_failure(error):
                        continue
                    raise
        return released

    def release_job(self, job_id: str, lease_owner: str) -> bool:
        JobStatus = _job_status_type()
        ReconstructionJob, _ = _job_upload_types()
        table = self._require_table()
        with self._lock:
            response = table.get_item(Key={"pk": f"JOB#{job_id}", "sk": "META"}, ConsistentRead=True)
            item = response.get("Item")
            if item is None:
                return False
            job = ReconstructionJob.model_validate_json(item["document"])
            if job.status != "running" or job.lease_owner != lease_owner:
                return False
            job.status = JobStatus.QUEUED
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = datetime.now(UTC)
            try:
                table.put_item(
                    Item=self._job_item(job),
                    ConditionExpression="#lo = :owner AND #s = :running",
                    ExpressionAttributeNames={"#lo": "lease_owner", "#s": "status"},
                    ExpressionAttributeValues={":owner": lease_owner, ":running": "running"},
                )
            except Exception as error:  # noqa: BLE001 - narrowed below
                if self._is_conditional_check_failure(error):
                    return False
                raise
            return True

    # -- project -> asset links (Build Plan step 26) -------------------------
    #
    # Replaces `ProjectRecord.asset_ids` (a list-in-a-blob) as the write path
    # for new assets: each link is its own child item, so two uploads racing
    # never lose one to a last-write-wins project save. Old snapshots'
    # `asset_ids` lists are still read for backward compatibility.

    def link_asset(self, project_id: str, asset_id: str) -> None:
        with self._lock:
            try:
                self._require_table().put_item(
                    Item={
                        "pk": f"PROJECT#{project_id}",
                        "sk": f"ASSET#{asset_id}",
                        "created_at": _utc_now_iso(),
                    },
                    ConditionExpression="attribute_not_exists(sk)",
                )
            except Exception as error:  # noqa: BLE001 - narrowed below
                if self._is_conditional_check_failure(error):
                    return
                raise

    def list_linked_asset_ids(self, project_id: str) -> list[str]:
        return [
            item["sk"].removeprefix("ASSET#") for item in self._query_children(project_id, "ASSET")
        ]

    # -- uploads (Build Plan step 26) ----------------------------------------

    def save_upload_record(self, upload: UploadRecord) -> None:
        with self._lock:
            self._require_table().put_item(
                Item={
                    "pk": f"PROJECT#{upload.project_id}",
                    "sk": f"UPLOAD#{upload.upload_id}",
                    "document": upload.model_dump_json(),
                }
            )

    def get_upload_record(self, project_id: str, upload_id: str) -> UploadRecord | None:
        _, UploadRecord = _job_upload_types()
        response = self._require_table().get_item(
            Key={"pk": f"PROJECT#{project_id}", "sk": f"UPLOAD#{upload_id}"}
        )
        item = response.get("Item")
        if item is None:
            return None
        return UploadRecord.model_validate_json(item["document"])

    def list_upload_records(self, project_id: str) -> list[UploadRecord]:
        _, UploadRecord = _job_upload_types()
        return [
            UploadRecord.model_validate_json(item["document"])
            for item in self._query_children(project_id, "UPLOAD")
        ]

    # -- letters (Build Plan step 28) -----------------------------------------
    #
    # Letter = PK "PROJECT#<project_id>" / SK "LETTER#<letter_id>".
    # LetterOpen = PK "PROJECT#<project_id>" / SK "LETTEROPEN#<letter_id>#<contributor_id>",
    # written with a conditional put so a repeat open by the same recipient
    # is a no-op rather than a second item. ("LETTEROPEN#" never collides
    # with the "LETTER#" prefix query below -- the 7th character differs.)

    def save_letter(self, letter: Letter) -> None:
        with self._lock:
            self._require_table().put_item(
                Item={
                    "pk": f"PROJECT#{letter.project_id}",
                    "sk": f"LETTER#{letter.letter_id}",
                    "document": letter.model_dump_json(),
                }
            )

    def get_letter(self, project_id: str, letter_id: str) -> Letter | None:
        Letter, _ = _letter_model_types()
        response = self._require_table().get_item(
            Key={"pk": f"PROJECT#{project_id}", "sk": f"LETTER#{letter_id}"}
        )
        item = response.get("Item")
        if item is None:
            return None
        return Letter.model_validate_json(item["document"])

    def list_letters(self, project_id: str) -> list[Letter]:
        Letter, _ = _letter_model_types()
        return [
            Letter.model_validate_json(item["document"])
            for item in self._query_children(project_id, "LETTER")
        ]

    def record_letter_open(
        self, project_id: str, letter_id: str, contributor_id: str, opened_at: datetime
    ) -> bool:
        _, LetterOpenRecord = _letter_model_types()
        record = LetterOpenRecord(
            project_id=project_id, letter_id=letter_id, contributor_id=contributor_id, opened_at=opened_at
        )
        with self._lock:
            try:
                self._require_table().put_item(
                    Item={
                        "pk": f"PROJECT#{project_id}",
                        "sk": f"LETTEROPEN#{letter_id}#{contributor_id}",
                        "document": record.model_dump_json(),
                    },
                    ConditionExpression="attribute_not_exists(sk)",
                )
                return True
            except Exception as error:  # noqa: BLE001 - narrowed below
                if self._is_conditional_check_failure(error):
                    return False
                raise

    def list_letter_opens(self, project_id: str, letter_id: str) -> list[LetterOpenRecord]:
        _, LetterOpenRecord = _letter_model_types()
        return [
            LetterOpenRecord.model_validate_json(item["document"])
            for item in self._query_children(project_id, f"LETTEROPEN#{letter_id}")
        ]

    def letters_version(self, project_id: str) -> int:
        return len(self._query_children(project_id, "LETTEROPEN"))

    # -- room builds (docs/WEB_TO_QUEST_PIPELINE.md 1) ------------------------
    #
    # RoomBuild = PK "PROJECT#<project_id>" / SK "ROOMBUILD#<build_id>", with
    # gsi2pk="ROOMBUILDQ#<status>" / gsi2sk="<created_at>#<build_id>" so the
    # runner's claim is a Query (never a Scan). A tiny pointer item
    # PK "ROOMBUILD#<build_id>" / SK "META" holds the project id, because the
    # runner's status route only knows the build id. Per-project reads are
    # strongly consistent (base table), so a double-clicked "Build room in
    # VR" sees the first build and gets its 409.

    def _room_build_item(self, build: "RoomBuild") -> dict:
        return {
            "pk": f"PROJECT#{build.project_id}",
            "sk": f"ROOMBUILD#{build.build_id}",
            "document": build.model_dump_json(),
            "status": build.status,
            "runner_id": build.runner_id,
            "updated_at": build.updated_at,
            "gsi2pk": f"ROOMBUILDQ#{build.status}",
            "gsi2sk": f"{build.created_at}#{build.build_id}",
        }

    def _project_room_builds(self, project_id: str) -> list["RoomBuild"]:
        RoomBuild = _room_build_type()
        return [
            RoomBuild.model_validate_json(item["document"])
            for item in self._query_children(project_id, "ROOMBUILD", consistent=True)
        ]

    def create_room_build(self, build: "RoomBuild") -> None:
        table = self._require_table()
        with self._lock:
            active = _newest_active_room_build(self._project_room_builds(build.project_id))
            if active is not None:
                raise RoomBuildConflict(active)
            table.put_item(
                Item={"pk": f"ROOMBUILD#{build.build_id}", "sk": "META", "project_id": build.project_id}
            )
            table.put_item(Item=self._room_build_item(build), ConditionExpression="attribute_not_exists(sk)")

    def get_room_build(self, build_id: str, project_id: str | None = None) -> "RoomBuild | None":
        RoomBuild = _room_build_type()
        table = self._require_table()
        if project_id is None:
            pointer = table.get_item(
                Key={"pk": f"ROOMBUILD#{build_id}", "sk": "META"}, ConsistentRead=True
            ).get("Item")
            if pointer is None:
                return None
            project_id = pointer["project_id"]
        item = table.get_item(
            Key={"pk": f"PROJECT#{project_id}", "sk": f"ROOMBUILD#{build_id}"}, ConsistentRead=True
        ).get("Item")
        return RoomBuild.model_validate_json(item["document"]) if item else None

    def list_room_builds(self, project_id: str) -> list["RoomBuild"]:
        return _room_builds_newest_first(self._project_room_builds(project_id))

    def claim_next_room_build(self, runner_id: str, now: datetime) -> "RoomBuild | None":
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        RoomBuild = _room_build_type()
        with self._lock:
            items = self._query_index("gsi2", Key("gsi2pk").eq("ROOMBUILDQ#requested"), scan_index_forward=True)
            for item in items:
                indexed = RoomBuild.model_validate_json(item["document"])
                # The GSI is eventually consistent: re-read the base item.
                current = self.get_room_build(indexed.build_id, indexed.project_id)
                if current is None or current.status != "requested":
                    continue
                claimed = current.model_copy(
                    update={"status": "claimed", "runner_id": runner_id, "message": "", "updated_at": iso_z(now)}
                )
                if self.update_room_build(
                    claimed,
                    expected_status=current.status,
                    expected_runner_id=current.runner_id,
                    expected_updated_at=current.updated_at,
                ):
                    return claimed
        return None

    def update_room_build(
        self,
        build: "RoomBuild",
        *,
        expected_status: str,
        expected_runner_id: str,
        expected_updated_at: str,
    ) -> bool:
        with self._lock:
            try:
                self._require_table().put_item(
                    Item=self._room_build_item(build),
                    ConditionExpression="#s = :s AND #r = :r AND #u = :u",
                    ExpressionAttributeNames={"#s": "status", "#r": "runner_id", "#u": "updated_at"},
                    ExpressionAttributeValues={
                        ":s": expected_status,
                        ":r": expected_runner_id,
                        ":u": expected_updated_at,
                    },
                )
            except Exception as error:  # noqa: BLE001 - narrowed below
                if self._is_conditional_check_failure(error):
                    return False
                raise
            return True

    def release_stale_room_builds(
        self, lease_seconds: float, now: datetime, project_id: str | None = None
    ) -> int:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        RoomBuild = _room_build_type()
        if project_id is not None:
            candidates = self._project_room_builds(project_id)
        else:
            candidates = [
                RoomBuild.model_validate_json(item["document"])
                for status in ROOM_BUILD_LEASED_STATUSES
                for item in self._query_index("gsi2", Key("gsi2pk").eq(f"ROOMBUILDQ#{status}"))
            ]
        released = 0
        for build in candidates:
            if not _room_build_is_stale(build, now, lease_seconds):
                continue
            if self.update_room_build(
                _requeued_room_build(build, now),
                expected_status=build.status,
                expected_runner_id=build.runner_id,
                expected_updated_at=build.updated_at,
            ):
                released += 1
        return released

    # -- guided tours (Build Plan step 30) -----------------------------------
    #
    # TOUR#<0-padded version> mirrors BLUEPRINT#<rev>; TOURLIVE mirrors LIVE.
    # `activate_tour` CASes the TOURLIVE pointer first (that's the actual
    # linearization point, same as `set_live_revision`), then best-effort
    # rewrites the two tour documents' `status` field so `GET /tours` shows
    # draft/active/retired without a second read against the pointer.
    #
    # ponytail: the guided-tour-contract skill suggests TransactWriteItems
    # for the pointer + two status rewrites; that's skipped here in favor of
    # two plain conditional/unconditional puts after the CAS succeeds. The
    # pointer write above is what actually decides which tour is live, so a
    # crash between these three puts only leaves a stale `status` label, not
    # a wrong live tour. Upgrade to TransactWriteItems if a reader ever needs
    # the stored `status` field to be authoritative independent of a second
    # `get_active_tour_version` read.

    def _tour_key(self, project_id: str, tour_version: int) -> dict:
        return {"pk": f"PROJECT#{project_id}", "sk": self._seq_key("TOUR", tour_version)}

    def _put_tour(self, tour: "GuidedTour") -> None:
        self._require_table().put_item(
            Item={**self._tour_key(tour.project_id, tour.tour_version), "document": tour.model_dump_json()}
        )

    def list_tours(self, project_id: str) -> list["GuidedTour"]:
        GuidedTour = _tour_model_type()
        return [
            GuidedTour.model_validate_json(item["document"])
            for item in self._query_children(project_id, "TOUR")
        ]

    def append_tour(self, tour: "GuidedTour") -> None:
        with self._lock:
            try:
                self._require_table().put_item(
                    Item={**self._tour_key(tour.project_id, tour.tour_version), "document": tour.model_dump_json()},
                    ConditionExpression="attribute_not_exists(sk)",
                )
            except Exception as error:  # noqa: BLE001 - narrowed below
                if self._is_conditional_check_failure(error):
                    raise RevisionConflict(
                        f"Tour version {tour.tour_version} for project {tour.project_id} already exists."
                    ) from error
                raise

    def get_tour(self, project_id: str, tour_version: int) -> "GuidedTour | None":
        GuidedTour = _tour_model_type()
        response = self._require_table().get_item(Key=self._tour_key(project_id, tour_version))
        item = response.get("Item")
        if item is None:
            return None
        return GuidedTour.model_validate_json(item["document"])

    def get_active_tour_version(self, project_id: str) -> int | None:
        response = self._require_table().get_item(Key={"pk": f"PROJECT#{project_id}", "sk": "TOURLIVE"})
        item = response.get("Item")
        if item is None:
            return None
        return int(item["tour_version"])

    def activate_tour(self, project_id: str, expected: int | None, new_version: int) -> "GuidedTour | None":
        pointer_item = {"pk": f"PROJECT#{project_id}", "sk": "TOURLIVE", "tour_version": new_version}
        if expected is None:
            kwargs: dict = {"Item": pointer_item, "ConditionExpression": "attribute_not_exists(pk)"}
        else:
            kwargs = {
                "Item": pointer_item,
                "ConditionExpression": "attribute_not_exists(pk) OR tour_version = :expected",
                "ExpressionAttributeValues": {":expected": expected},
            }
        with self._lock:
            try:
                self._require_table().put_item(**kwargs)
            except Exception as error:  # noqa: BLE001 - narrowed below
                if self._is_conditional_check_failure(error):
                    return None
                raise
            if expected is not None:
                previous = self.get_tour(project_id, expected)
                if previous is not None:
                    self._put_tour(previous.model_copy(update={"status": "retired"}))
            new_tour = self.get_tour(project_id, new_version)
            if new_tour is None:
                return None
            new_tour = new_tour.model_copy(update={"status": "active"})
            self._put_tour(new_tour)
            return new_tour

    # -- guide sessions (Build Plan step 32) ---------------------------------
    #
    # GuideSession = PK "PROJECT#<project_id>" / SK "GUIDESESSION#<session_id>".
    # The active-session pointer = SK "GUIDEACTIVESESSION#<account>", holding
    # just the session_id -- one active session per (project_id, account),
    # mirroring TOURLIVE's pointer-row shape. GuideTurn = SK
    # "GUIDETURN#<session_id>#<turn_seq padded>", append-only. Daily model-turn
    # usage = SK "GUIDEUSAGE#<yyyy-mm-dd>", an atomic ADD counter.

    def _guide_session_key(self, project_id: str, session_id: str) -> dict:
        return {"pk": f"PROJECT#{project_id}", "sk": f"GUIDESESSION#{session_id}"}

    def _guide_active_key(self, project_id: str, account: str) -> dict:
        return {"pk": f"PROJECT#{project_id}", "sk": f"GUIDEACTIVESESSION#{account}"}

    def _guide_turn_key(self, project_id: str, session_id: str, turn_seq: int) -> dict:
        padded = f"{turn_seq:0{self._SORT_WIDTH}d}"
        return {"pk": f"PROJECT#{project_id}", "sk": f"GUIDETURN#{session_id}#{padded}"}

    def create_guide_session(self, session: "GuideSession") -> None:
        GuideSession, _ = _guide_model_types()
        with self._lock:
            table = self._require_table()
            previous_id = self.get_active_guide_session_id(session.project_id, session.account)
            if previous_id is not None:
                previous = self.get_guide_session(session.project_id, previous_id)
                if previous is not None:
                    table.put_item(
                        Item={
                            **self._guide_session_key(session.project_id, previous_id),
                            "document": previous.model_copy(update={"active": False}).model_dump_json(),
                        }
                    )
            table.put_item(
                Item={
                    **self._guide_session_key(session.project_id, session.session_id),
                    "document": session.model_dump_json(),
                    "turn_count": session.turn_count,
                }
            )
            table.put_item(
                Item={
                    **self._guide_active_key(session.project_id, session.account),
                    "session_id": session.session_id,
                }
            )

    def get_guide_session(self, project_id: str, session_id: str) -> "GuideSession | None":
        GuideSession, _ = _guide_model_types()
        response = self._require_table().get_item(Key=self._guide_session_key(project_id, session_id))
        item = response.get("Item")
        if item is None:
            return None
        return GuideSession.model_validate_json(item["document"])

    def get_active_guide_session_id(self, project_id: str, account: str) -> str | None:
        response = self._require_table().get_item(Key=self._guide_active_key(project_id, account))
        item = response.get("Item")
        return item["session_id"] if item else None

    def update_guide_session(
        self, project_id: str, session_id: str, expected_turn_count: int, updates: dict
    ) -> "GuideSession | None":
        GuideSession, _ = _guide_model_types()
        updated = GuideSession.model_validate(updates)
        with self._lock:
            try:
                self._require_table().put_item(
                    Item={
                        **self._guide_session_key(project_id, session_id),
                        "document": updated.model_dump_json(),
                        "turn_count": updated.turn_count,
                    },
                    ConditionExpression="attribute_exists(pk) AND turn_count = :expected",
                    ExpressionAttributeValues={":expected": expected_turn_count},
                )
            except Exception as error:  # noqa: BLE001 - narrowed below
                if self._is_conditional_check_failure(error):
                    return None
                raise
            return updated

    def append_guide_turn(self, project_id: str, turn: "GuideTurn") -> None:
        self._require_table().put_item(
            Item={
                **self._guide_turn_key(project_id, turn.session_id, turn.turn_seq),
                "document": turn.model_dump_json(),
            }
        )

    def get_guide_turn_by_client_id(
        self, project_id: str, session_id: str, client_turn_id: str
    ) -> "GuideTurn | None":
        _, GuideTurn = _guide_model_types()
        for item in self._query_children(project_id, f"GUIDETURN#{session_id}"):
            turn = GuideTurn.model_validate_json(item["document"])
            if turn.client_turn_id == client_turn_id:
                return turn
        return None

    def get_guide_turn_by_seq(self, project_id: str, session_id: str, turn_seq: int) -> "GuideTurn | None":
        _, GuideTurn = _guide_model_types()
        response = self._require_table().get_item(Key=self._guide_turn_key(project_id, session_id, turn_seq))
        item = response.get("Item")
        if item is None:
            return None
        return GuideTurn.model_validate_json(item["document"])

    def increment_guide_daily_usage(self, project_id: str, date_key: str) -> int:
        response = self._require_table().update_item(
            Key={"pk": f"PROJECT#{project_id}", "sk": f"GUIDEUSAGE#{date_key}"},
            UpdateExpression="ADD guide_turns_count :one",
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(response["Attributes"]["guide_turns_count"])


def create_store(
    *,
    local_state_path: Path,
    backend: str | None = None,
) -> AuthoringStore:
    """Build the configured authoring store.

    Selection order:
    - ``backend`` argument when given (used by tests),
    - else ``SKETCHSCAPE_STORAGE_BACKEND`` (``local`` default, or ``dynamodb``).

    The DynamoDB backend reads ``SKETCHSCAPE_DYNAMODB_TABLE`` and optional
    ``AWS_REGION``. It never runs unless explicitly selected.
    """
    selected = (backend or os.environ.get("SKETCHSCAPE_STORAGE_BACKEND", "local")).strip().lower()
    if selected in {"", "local", "json", "file"}:
        store = LocalJsonStore(local_state_path)
        store.load()
        return store
    if selected in {"dynamodb", "aws", "dynamo"}:
        store = DynamoDbStore(
            os.environ.get("SKETCHSCAPE_DYNAMODB_TABLE", ""),
            region_name=os.environ.get("AWS_REGION") or None,
        )
        store.load()
        return store
    raise RuntimeError(
        f"Unknown SKETCHSCAPE_STORAGE_BACKEND '{selected}'. Use 'local' or 'dynamodb'."
    )


# Backward-compatible alias: earlier code and tests refer to ``Store``.
Store = LocalJsonStore
