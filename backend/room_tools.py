"""NemoClaw room tools (Build Plan step 24): get_room_state, propose_room_edit.

Unlike scene_tools.py (pure, offline reasoning), these two tools are thin
HTTP clients against this project's own backend API -- NemoClaw never writes
the store directly and never publishes (AGENT.md Hard Rule 4 / Hard Rule 6;
top-tier-nemoclaw-tool-design skill). A proposed edit lands as a new,
unpublished blueprint revision (a draft); a person approves the publish on
the website's Room page. That publish step (registry id blueprint.publish,
``POST /v1/projects/{id}/blueprints/{revision}/publish``) already exists and
is untouched here.

Authentication: NemoClaw's shared service token, ``SKETCHSCAPE_NEMOCLAW_TOKEN``
(backend/auth.py R14, ``Identity(kind="service")``), sent as
``Authorization: Bearer <token>``. The credential lives in NemoClaw's runtime
credential provider, never in this repo -- these functions only read it from
the environment (or an explicit ``token=`` override for tests).

Stale-revision handling: ``propose_room_edit`` builds its draft from a
specific ``base_revision``. If the room's live revision moved on since (a
409 from ``POST /v1/projects/{id}/blueprints``), it re-reads the room with
``get_room_state`` and raises ``StaleRevisionError`` carrying the fresh state
-- the caller re-drafts against the new live revision; this module never
retries the same write blindly (room-api-and-ownership skill: "On 409,
re-read with get_room_state and re-draft. Never overwrite.").

No new backend route was needed for either tool: ``get_room_state`` uses the
existing ``GET /v1/rooms/{project_id}/state`` (step 21; service identities
may always read), and ``propose_room_edit`` uses the existing
``POST /v1/projects/{project_id}/blueprints?base_revision=<live>`` (step 15;
``require_project_draft`` already allows a service identity to draft).
"""

from __future__ import annotations

import copy
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import jsonschema

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "shared" / "experience-blueprint.schema.json"
_SCHEMA_CACHE: dict | None = None

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 15.0
_TRANSFORM_AXES = ("position", "rotation", "scale")


class RoomToolError(RuntimeError):
    """Raised for any get_room_state/propose_room_edit failure.

    Messages are actionable (top-tier-nemoclaw-tool-design design rule 6):
    they say what to do next, not just what went wrong.
    """


class StaleRevisionError(RoomToolError):
    """Raised by propose_room_edit on a 409: base_revision is no longer live.

    Carries the freshly re-read room state (best-effort) so the caller
    doesn't need a second round trip before re-drafting.
    """

    def __init__(self, message: str, *, live_revision: int, room_state: dict):
        super().__init__(message)
        self.live_revision = live_revision
        self.room_state = room_state


# ---------------------------------------------------------------------------
# Schema validation (same schema and wrapper approach as scene_tools.py)
# ---------------------------------------------------------------------------


def _load_schema() -> dict:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = json.loads(_SCHEMA_PATH.read_text())
    return _SCHEMA_CACHE


def _validate_blueprint_input(blueprint_input: dict, *, project_id: str, revision: int) -> None:
    envelope = {
        "project_id": project_id,
        "revision": revision,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **blueprint_input,
    }
    try:
        jsonschema.validate(envelope, _load_schema())
    except jsonschema.ValidationError as exc:
        raise RoomToolError(
            f"propose_room_edit would produce a schema-invalid blueprint: {exc.message}"
        ) from exc


# ---------------------------------------------------------------------------
# HTTP plumbing (stdlib only -- no new dependency for a handful of calls)
# ---------------------------------------------------------------------------


CONFIG_DIR = Path(os.environ.get("SKETCHSCAPE_CONFIG_DIR", "~/.config/sketchscape")).expanduser()


def _config_value(name: str) -> Optional[str]:
    """A per-user setting file (mode 600, written by scripts/start_local_backend.sh
    into the NemoClaw sandbox). Used when the matching env var isn't set:
    OpenShell has no generic way to inject env into a skill's shell today."""
    path = CONFIG_DIR / name
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _resolve(
    base_url: str | None, token: str | None, nemoclaw_id: str | None, timeout_seconds: float | None
) -> tuple[str, str, Optional[str], float]:
    base_url = (
        base_url or os.environ.get("SKETCHSCAPE_API_URL") or _config_value("api-url") or DEFAULT_BASE_URL
    ).rstrip("/")
    token = token or os.environ.get("SKETCHSCAPE_NEMOCLAW_TOKEN") or _config_value("nemoclaw-token")
    if not token:
        raise RoomToolError(
            "No NemoClaw service token. Room tools authenticate as NemoClaw's service identity "
            "(backend/auth.py R14): set SKETCHSCAPE_NEMOCLAW_TOKEN, or run "
            "scripts/start_local_backend.sh, which provisions it into the sandbox. Never put it in this repo."
        )
    nemoclaw_id = nemoclaw_id or os.environ.get("SKETCHSCAPE_NEMOCLAW_ID")
    timeout = timeout_seconds or float(
        os.environ.get("SKETCHSCAPE_ROOM_TOOLS_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)
    )
    return base_url, token, nemoclaw_id, timeout


def _request(
    method: str,
    url: str,
    *,
    token: str,
    nemoclaw_id: str | None,
    timeout: float,
    body: Optional[dict] = None,
) -> tuple[int, Any]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if nemoclaw_id:
        headers["X-SketchScape-NemoClaw-Id"] = nemoclaw_id
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except urllib.error.URLError as exc:
        raise RoomToolError(f"Could not reach the SketchScape backend at {url}: {exc.reason}") from exc
    text = raw.decode("utf-8") if raw else ""
    if not text:
        return status, None
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, text


# ---------------------------------------------------------------------------
# get_room_state (registry id room.state.fetch)
# ---------------------------------------------------------------------------


def get_room_state(
    project_id: str,
    *,
    base_url: str | None = None,
    token: str | None = None,
    nemoclaw_id: str | None = None,
    timeout_seconds: float | None = None,
    response_format: str = "concise",
) -> dict:
    """``GET /v1/rooms/{project_id}/state``. Read-only; no approval needed.

    Returns a short, human-readable summary by default (design rule 5 --
    large room payloads shouldn't fill the agent's context);
    ``response_format="detailed"`` returns the full RoomStateResponse JSON.
    """
    if response_format not in ("concise", "detailed"):
        raise RoomToolError("response_format must be 'concise' or 'detailed'.")
    base_url, token, nemoclaw_id, timeout = _resolve(base_url, token, nemoclaw_id, timeout_seconds)
    url = f"{base_url}/v1/rooms/{project_id}/state"
    status, payload = _request("GET", url, token=token, nemoclaw_id=nemoclaw_id, timeout=timeout)

    if status == 404:
        raise RoomToolError(f"Project {project_id!r} has no published room yet (404). Nothing to read.")
    if status == 429:
        raise RoomToolError("Rate-limited on room-state polling; slow down and retry shortly.")
    if status != 200:
        raise RoomToolError(f"get_room_state failed ({status}): {payload}")

    if response_format == "detailed":
        return payload

    objects = payload.get("objects", [])
    lines = [
        f"{obj['id']} ({obj['asset_id']}) owned by "
        f"{obj.get('owner_contributor_id') or 'unowned/environment'}, "
        f"{'editable by me' if obj.get('editable_by_me') else 'read-only to me'}, "
        f"pos={obj['position']}"
        for obj in objects
    ]
    summary = (
        f"project {project_id} live revision {payload['live_revision']}: {len(objects)} object(s). "
        + ("; ".join(lines) if lines else "no objects.")
    )
    return {
        "project_id": project_id,
        "live_revision": payload["live_revision"],
        "objects": objects,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# propose_room_edit (registry id room.edit.draft)
# ---------------------------------------------------------------------------


def propose_room_edit(
    project_id: str,
    base_revision: int,
    edits: list[dict],
    *,
    base_url: str | None = None,
    token: str | None = None,
    nemoclaw_id: str | None = None,
    timeout_seconds: float | None = None,
) -> dict:
    """Draft a new blueprint revision from ``base_revision`` with ``edits``
    applied. Never publishes -- publishing is a separate, approval-gated
    step a person takes on the website's Room page.

    ``edits`` is a list of ``{"object_id": str, "position"/"rotation"/"scale": [x, y, z]}``
    (any non-empty subset of the three transforms per edit), matching the
    room API's own edit shape. May target environment objects and, when the
    person asked for a layout change, contributed objects too -- the
    returned summary always names which contributor(s) own the objects
    moved, so the approver knows.

    Raises ``StaleRevisionError`` on a 409 (``base_revision`` is no longer
    live), with the freshly re-read room state attached. Never retries the
    write itself -- call ``get_room_state`` (already done for you, see the
    exception's ``room_state``) and re-propose against the new revision.
    """
    if not edits:
        raise RoomToolError("propose_room_edit needs at least one edit.")
    base_url, token, nemoclaw_id, timeout = _resolve(base_url, token, nemoclaw_id, timeout_seconds)

    # 1. Fetch the full blueprint at base_revision -- room state's view is
    # deliberately reduced (no portals, no contribution_id), so the POST
    # body for a new draft needs the real blueprint record, not that view.
    blueprint_url = f"{base_url}/v1/projects/{project_id}/blueprints/{base_revision}"
    status, blueprint = _request("GET", blueprint_url, token=token, nemoclaw_id=nemoclaw_id, timeout=timeout)
    if status == 404:
        raise RoomToolError(
            f"Revision {base_revision} of project {project_id!r} was not found. "
            "Call get_room_state to find the current live_revision and retry with that."
        )
    if status != 200:
        raise RoomToolError(f"Could not read base_revision {base_revision} ({status}): {blueprint}")

    # 2. Apply edits to a deep copy of the live objects.
    objects_by_id = {obj["id"]: copy.deepcopy(obj) for obj in blueprint["objects"]}
    unknown = sorted({edit["object_id"] for edit in edits} - set(objects_by_id))
    if unknown:
        raise RoomToolError(
            f"Unknown object id(s) in revision {base_revision}: {', '.join(unknown)}. "
            "Call get_room_state to see current object ids."
        )

    changes: list[str] = []
    for edit in edits:
        object_id = edit["object_id"]
        target = objects_by_id[object_id]
        touched = False
        for axis in _TRANSFORM_AXES:
            value = edit.get(axis)
            if value is None:
                continue
            if not (isinstance(value, list) and len(value) == 3 and all(isinstance(v, (int, float)) for v in value)):
                raise RoomToolError(f"{object_id}.{axis} must be a 3-number list.")
            before = target[axis]
            target[axis] = [float(v) for v in value]
            changes.append(f"{object_id}.{axis} {before} -> {target[axis]}")
            touched = True
        if not touched:
            raise RoomToolError(f"{object_id}: set at least one of position/rotation/scale.")

    new_input = {
        "experience": blueprint["experience"],
        "environment": blueprint["environment"],
        "objects": list(objects_by_id.values()),
        "portals": blueprint.get("portals", []),
        "navigation": blueprint["navigation"],
    }
    if blueprint.get("staging"):
        # An edit moves objects; it must not silently drop the room's staging.
        new_input["staging"] = blueprint["staging"]
    _validate_blueprint_input(new_input, project_id=project_id, revision=base_revision + 1)

    # 3. Best-effort ownership lookup for the approver's benefit. A failure
    # here shouldn't block the draft itself.
    owners = "unknown (room-state read failed)"
    try:
        state = get_room_state(
            project_id,
            base_url=base_url,
            token=token,
            nemoclaw_id=nemoclaw_id,
            timeout_seconds=timeout,
            response_format="detailed",
        )
        owner_by_id = {
            obj["id"]: (obj.get("owner_contributor_id") or "unowned/environment") for obj in state["objects"]
        }
        touched_ids = {edit["object_id"] for edit in edits}
        owners = ", ".join(sorted({owner_by_id.get(obj_id, "unknown") for obj_id in touched_ids}))
    except RoomToolError:
        pass

    # 4. POST the draft, based on base_revision.
    draft_url = f"{base_url}/v1/projects/{project_id}/blueprints?base_revision={base_revision}"
    status, result = _request(
        "POST", draft_url, token=token, nemoclaw_id=nemoclaw_id, timeout=timeout, body=new_input
    )

    if status == 409:
        live_revision = (result or {}).get("published_revision")
        try:
            refreshed = get_room_state(
                project_id,
                base_url=base_url,
                token=token,
                nemoclaw_id=nemoclaw_id,
                timeout_seconds=timeout,
                response_format="concise",
            )
        except RoomToolError as exc:
            refreshed = {"summary": f"(could not re-read room state: {exc})"}
        if live_revision is None:
            live_revision = refreshed.get("live_revision", base_revision)
        raise StaleRevisionError(
            f"base_revision {base_revision} is stale; live revision is now {live_revision}. "
            f"Re-read via get_room_state and redo the proposal: {refreshed.get('summary', '')}",
            live_revision=live_revision,
            room_state=refreshed,
        )
    if status != 201:
        raise RoomToolError(f"propose_room_edit failed ({status}): {result}")

    revision = result["revision"]
    summary = (
        f"revision {revision} drafted from live {base_revision}; {'; '.join(changes)}; "
        f"objects owned by: {owners}; not published (a person approves the publish on the website)."
    )
    return {
        "project_id": project_id,
        "revision": revision,
        "based_on_revision": base_revision,
        "changes": changes,
        "owners": owners,
        "published": False,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# draft_room (registry id room.draft_from_project)
# ---------------------------------------------------------------------------

_ROOM_ASSET_KINDS = ("reconstruction", "sketch_card")


def draft_room(
    project_id: str,
    *,
    connection_insight: Optional[dict] = None,
    theme: Optional[str] = None,
    player_eye_height: Optional[float] = None,
    base_url: str | None = None,
    token: str | None = None,
    nemoclaw_id: str | None = None,
    timeout_seconds: float | None = None,
) -> dict:
    """Lay out a project's ready assets as a whole room and draft it as a new
    blueprint revision on the backend. Never publishes.

    Uses ``place_objects_in_scene`` for layout and, when a
    ``connection_insight`` is given, ``stage_immersive_reveal`` for the
    blueprint's ``staging`` (lighting, motif, narration, haptics). Real
    Fast-SAM3D scans are normalized to about 1 m, so each gets a *uniform*
    scale equal to its label's real-world size (largest side, metres) and
    sits at floor level (y = 0); Unity's offline builder stands the Z-up scan
    upright and rests it on the floor. Every object is grabbable and linked
    to its contribution, so the room keeps each person's attribution.

    The draft is based on the live revision (0 if nothing is published) and
    replaces the live layout. On a 409 it raises ``StaleRevisionError``.
    """
    import scene_layout
    import scene_tools as st  # local: keeps get_room_state/propose_room_edit import-light

    base_url, token, nemoclaw_id, timeout = _resolve(base_url, token, nemoclaw_id, timeout_seconds)
    kwargs = {"token": token, "nemoclaw_id": nemoclaw_id, "timeout": timeout}

    status, assets = _request("GET", f"{base_url}/v1/projects/{project_id}/assets", **kwargs)
    if status == 404:
        raise RoomToolError(f"Project {project_id!r} does not exist.")
    if status != 200:
        raise RoomToolError(f"Could not list project assets ({status}): {assets}")
    ready = [a for a in assets or [] if a.get("status") == "ready" and a.get("kind", "reconstruction") in _ROOM_ASSET_KINDS]
    if not ready:
        raise RoomToolError(
            f"Project {project_id!r} has no ready 3D assets yet; wait for its uploads to finish reconstructing."
        )

    status, contributions = _request("GET", f"{base_url}/v1/projects/{project_id}/contributions", **kwargs)
    contribution_by_asset = (
        {c["asset_id"]: c["contribution_id"] for c in contributions if c.get("asset_id")} if status == 200 else {}
    )

    status, state = _request("GET", f"{base_url}/v1/rooms/{project_id}/state", **kwargs)
    if status == 200:
        live_revision = int(state["live_revision"])
    elif status == 404:
        live_revision = 0
    else:
        raise RoomToolError(f"Could not read the room's live revision ({status}): {state}")

    room_theme = (theme or (connection_insight or {}).get("theme") or "Shared Room")[:200]
    by_id = {a["asset_id"]: a for a in ready}
    try:
        blueprint = st.place_objects_in_scene(
            [{"asset_id": a["asset_id"], "label": a.get("label") or "object"} for a in ready],
            project_id=project_id,
            theme=room_theme,
        )
    except st.SceneToolError as exc:
        raise RoomToolError(f"Layout failed: {exc}") from exc

    for obj in blueprint["objects"]:
        asset = by_id[obj["asset_id"]]
        obj["interactions"] = ["highlight", "inspect", "grab"]
        obj["contribution_id"] = contribution_by_asset.get(obj["asset_id"])
        if asset.get("kind", "reconstruction") == "reconstruction" and asset.get("artifact_url"):
            size = max(st._footprint_for_label(asset.get("label") or ""))
            obj["scale"] = [round(size, 3)] * 3
            obj["position"][1] = 0.0

    # Where the scans carry their pose from the photo, reproduce the photo:
    # positions, orientations and player-relative sizes (scene_layout.py).
    photo_layout = scene_layout.apply_photo_layout(
        blueprint["objects"],
        {
            obj["id"]: {
                "pose": by_id[obj["asset_id"]].get("pose"),
                "photo": ((by_id[obj["asset_id"]].get("views") or [{}])[0]).get("image_key"),
                "label_size": max(st._footprint_for_label(by_id[obj["asset_id"]].get("label") or "")),
            }
            for obj in blueprint["objects"]
        },
        player_eye_height=player_eye_height,
    )

    staging = None
    if connection_insight:
        staging = st.stage_immersive_reveal(connection_insight, blueprint["objects"])
        blueprint["staging"] = staging
        blueprint["environment"]["lighting_preset"] = staging["lighting_preset"]
    blueprint["navigation"] = {"vr": "teleport", "ar": "surface-placement"}
    _validate_blueprint_input(blueprint, project_id=project_id, revision=live_revision + 1)

    status, result = _request(
        "POST",
        f"{base_url}/v1/projects/{project_id}/blueprints?base_revision={live_revision}",
        body=blueprint,
        **kwargs,
    )
    if status == 409:
        latest = (result or {}).get("published_revision", live_revision)
        raise StaleRevisionError(
            f"The room changed while drafting (live revision is now {latest}); call draft_room again.",
            live_revision=latest,
            room_state={},
        )
    if status != 201:
        raise RoomToolError(f"draft_room failed ({status}): {result}")

    objects = [
        {
            "id": obj["id"],
            "label": by_id[obj["asset_id"]].get("label"),
            "size_m": obj["scale"][0],
            "attributed": obj["contribution_id"] is not None,
            "placed_from_photo": obj.get("placement") == "pose",
        }
        for obj in blueprint["objects"]
    ]
    summary = (
        f"revision {result['revision']} drafted for project {project_id} from live {live_revision}: "
        f"{len(objects)} object(s) ({', '.join(str(o['label']) for o in objects)}), all grabbable"
        + (f", lighting {staging['lighting_preset']}, reveal {' -> '.join(staging['reveal_order'])}" if staging else "")
        + (
            f"; {len(photo_layout['objects'])} object(s) placed as in their photo, scaled to a "
            f"{photo_layout['player_eye_height']} m eye height ({photo_layout['scale_source']})"
            if photo_layout
            else "; no photo poses, so objects are arranged in an arc"
        )
        + ". Not published: a project member publishes it (website or scripts/publish_room.py), then "
        "scripts/export_unity_experience.py + Unity's offline builder turn it into the VR scene."
    )
    return {
        "project_id": project_id,
        "revision": result["revision"],
        "based_on_revision": live_revision,
        "objects": objects,
        "staging": None if not staging else {
            "lighting_preset": staging["lighting_preset"],
            "reveal_order": staging["reveal_order"],
            "narration": staging["narration"]["text"],
        },
        "photo_layout": photo_layout,
        "published": False,
        "summary": summary,
    }
