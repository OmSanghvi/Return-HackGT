"""NemoClaw's `author_guided_tour` tool (Build Plan step 31).

Runs after `place_objects_in_scene` and `stage_immersive_reveal` (both in
`scene_tools.py`) have built the room, in the same NemoClaw session, so the
tour follows the staging's reveal order when one exists. It reads only
public/authoring HTTP routes -- never Unity MCP -- writes the `GuidedTour`
JSON with one model call through NemoClaw's configured provider, and posts
it as a **draft** using NemoClaw's service identity
(`SKETCHSCAPE_NEMOCLAW_TOKEN`, Build Plan R14). It never activates: a person
approves the draft on the website (`POST .../tours/{version}/activate`,
people-only per `backend/tour_routes.py`).

Uses only `urllib.request` (stdlib), matching `main.py`'s existing worker
dispatch -- no new HTTP dependency.

The live model call (structured output through NemoClaw's configured
provider, e.g. Muse Spark) needs the NemoClaw agent runtime (Build Plan step
3), which hasn't been stood up in this repo yet (see docs/BUILD_PLAN.md's
status table). `author_guided_tour` takes a `model_call` callable instead of
hard-coding that dependency, so the HTTP read/write/retry logic here is real
and independently testable with a stub, the same "keep pure logic separate
from a live LLM" split `scene_tools.py` uses (design rule 10 in the
`top-tier-nemoclaw-tool-design` skill).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

MAX_RETRIES = 2
_DEFAULT_TIMEOUT_S = 30


class TourAuthorError(RuntimeError):
    """Raised when `author_guided_tour` is misconfigured or fails after retries."""


def _backend_base_url() -> str:
    return os.environ.get("SKETCHSCAPE_API_BASE_URL", "http://localhost:8000").rstrip("/")


def _nemoclaw_headers() -> dict[str, str]:
    token = os.environ.get("SKETCHSCAPE_NEMOCLAW_TOKEN")
    if not token:
        raise TourAuthorError(
            "SKETCHSCAPE_NEMOCLAW_TOKEN is not configured; author_guided_tour needs "
            "NemoClaw's service identity (Build Plan R14) to read and draft."
        )
    headers = {"Authorization": f"Bearer {token}"}
    nemoclaw_id = os.environ.get("SKETCHSCAPE_NEMOCLAW_ID")
    if nemoclaw_id:
        headers["X-SketchScape-NemoClaw-Id"] = nemoclaw_id
    return headers


def _request(method: str, path: str, *, body: dict | None = None) -> tuple[int, Any]:
    url = f"{_backend_base_url()}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = _nemoclaw_headers()
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=_DEFAULT_TIMEOUT_S) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = {"detail": raw.decode("utf-8", "replace")}
        return error.code, parsed


def gather_tour_inputs(project_id: str) -> dict:
    """Read everything `author_guided_tour` needs, over HTTP only."""
    status, compiled_scene = _request("GET", f"/v1/projects/{project_id}/compiled-scene")
    if status != 200:
        raise TourAuthorError(f"GET compiled-scene failed ({status}): {compiled_scene}")
    status, insights = _request("GET", f"/v1/projects/{project_id}/connection/insights")
    if status != 200:
        raise TourAuthorError(f"GET connection/insights failed ({status}): {insights}")
    if not insights:
        raise TourAuthorError(f"Project {project_id} has no ConnectionInsight yet.")
    status, contributions = _request("GET", f"/v1/projects/{project_id}/contributions")
    if status != 200:
        raise TourAuthorError(f"GET contributions failed ({status}): {contributions}")
    status, contributors = _request("GET", f"/v1/projects/{project_id}/contributors")
    if status != 200:
        raise TourAuthorError(f"GET contributors failed ({status}): {contributors}")
    return {
        "compiled_scene": compiled_scene,
        "latest_insight": insights[-1],
        "contributions": contributions,
        "contributors": contributors,
    }


def _default_model_call(inputs: dict, rule_feedback: str | None) -> dict:  # noqa: ARG001
    """The live NemoClaw model call -- not wired up until Build Plan step 3.

    Pass a real callable (e.g. a live NemoClaw agent-loop function once step
    3 exists, or a test stub) as `author_guided_tour`'s `model_call` instead
    of relying on this default.
    """
    raise TourAuthorError(
        "author_guided_tour's live model call needs the NemoClaw agent runtime (Build Plan "
        "step 3), which hasn't been stood up in this repo yet. Pass a `model_call` callable "
        "instead of relying on the default."
    )


def author_guided_tour(
    project_id: str,
    *,
    model_call: Callable[[dict, str | None], dict] = _default_model_call,
) -> dict:
    """`author_guided_tour(project_id) -> {tour_version, status: "draft"}`.

    `model_call(inputs, rule_feedback)` must return a `GuidedTourInput`-shaped
    dict, following the instructions in the `nemoclaw-tour-authoring` skill
    (staging/blueprint order, `memory_text` sentences verbatim, connective
    prose as `authored` facts with `derived_from` set, never a letter's
    `note_text`). On a `POST /tours` 422, that response's rule message is fed
    back as `rule_feedback` and the model gets up to `MAX_RETRIES` more
    attempts; after that this raises `TourAuthorError` with the last message.
    Never calls the activate route -- a person does that on the website.
    """
    inputs = gather_tour_inputs(project_id)
    rule_feedback: str | None = None
    last_detail = ""
    for _attempt in range(MAX_RETRIES + 1):
        tour_input = model_call(inputs, rule_feedback)
        status, body = _request("POST", f"/v1/projects/{project_id}/tours", body=tour_input)
        if status == 201:
            return {"tour_version": body["tour_version"], "status": body["status"]}
        if status == 422:
            last_detail = (body or {}).get("detail", "") if isinstance(body, dict) else str(body)
            rule_feedback = last_detail
            continue
        raise TourAuthorError(f"POST /tours failed ({status}): {body}")
    raise TourAuthorError(
        f"author_guided_tour gave up after {MAX_RETRIES} retries; last validator error: {last_detail}"
    )
