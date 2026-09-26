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
from datetime import UTC, datetime
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
    )


STATE_VERSION = 2


class RevisionConflict(Exception):
    """Raised when an append would collide with an existing revision/sequence.

    Both backends raise this from ``append_blueprint``/``append_publication``
    when a conditional write loses a race with another writer (another API
    instance, another headset, NemoClaw). Callers retry with the next number.
    """


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


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

    def persist_all(self) -> None:  # pragma: no cover - default no-op
        """Force a full flush. Backends that write eagerly need not override."""


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
            if not self._state_path.is_file():
                return
            try:
                raw = json.loads(self._state_path.read_text("utf-8") or "{}")
            except (json.JSONDecodeError, OSError):
                # A corrupt snapshot must not crash startup. Preserve the bad
                # file for inspection and begin from an empty, valid state.
                self._quarantine_corrupt_state()
                return
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
        """Bind the table handle. Reads happen per request, not cached here."""
        with self._lock:
            if self._table is None:
                self._table = self._resource().Table(self._table_name)

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

    def _query_children(self, project_id: str, sk_prefix: str) -> list[dict]:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        table = self._require_table()
        items: list[dict] = []
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(f"PROJECT#{project_id}")
            & Key("sk").begins_with(f"{sk_prefix}#"),
            "ScanIndexForward": True,
        }
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
