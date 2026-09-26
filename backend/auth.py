"""Identity verification for SketchScape's authenticated API surface.

Build Plan step 16: real identities behind the API, so ``ExperienceBlueprint
.author`` (added by step 15) and future room-membership checks (step 17)
have something trustworthy to key off. Two kinds of caller show up here:

- The web app, signed in with Clerk, sending ``Authorization: Bearer <session
  token>`` (from ``@clerk/react``'s ``getToken()``).
- NemoClaw, calling back into the API as a Clerk M2M ("machine-to-machine")
  client, sending ``Authorization: Bearer <m2m token>``.

Selection follows this repo's existing pluggable pattern (``create_store`` in
storage.py, ``create_subject_labeler`` in subject_labeler.py): one selector
env var (``SKETCHSCAPE_AUTH_MODE``, ``mock`` | ``clerk`` | ``demo``), and the
third-party SDK (``clerk-backend-api``) is imported lazily, only inside the
``clerk`` branch, so the base install (``mock`` mode, the default) never
needs it installed.

``demo`` mode (added for the hackathon demo, ahead of step 13's real Clerk/
Meta account setup) is real per-project enforcement -- unlike ``mock``, which
no-ops membership and ownership checks -- but skips Clerk verification
entirely: the caller is one of exactly two hardcoded accounts, selected with
the same ``X-SketchScape-Dev-User`` header mock mode already uses. This is
what lets a two-person collaboration demo run today without a Clerk
dashboard. Clerk itself is left fully intact and dormant: switching back to
``SKETCHSCAPE_AUTH_MODE=clerk`` once step 13's account setup is done needs no
code changes here.

Meta room tokens for Quest headsets are a separate verifier added by step 18
(meta-quest-identity). ``require_identity`` is the extension point for it: a
room-token mode would add a fourth branch here and use the already-declared
``via="meta"`` value, not a rewrite.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request

IdentityKind = Literal["user", "service", "dev"]
IdentityVia = Literal["clerk", "meta", "mock", "demo"]


@dataclass(frozen=True)
class Identity:
    """Who is making this request, and how we know it."""

    user_id: str
    kind: IdentityKind
    via: IdentityVia


def _auth_mode() -> str:
    return os.environ.get("SKETCHSCAPE_AUTH_MODE", "mock").strip().lower()


def web_origins() -> list[str]:
    """Parse ``SKETCHSCAPE_WEB_ORIGINS`` (comma-separated) into a clean list.

    Used both as Clerk's ``authorized_parties`` allowlist and by the startup
    check that refuses to start in ``clerk`` mode with no configured origins.
    """
    raw = os.environ.get("SKETCHSCAPE_WEB_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _mock_identity(request: Request) -> Identity:
    dev_user = request.headers.get("X-SketchScape-Dev-User") or "dev-user"
    return Identity(user_id=dev_user, kind="dev", via="mock")


def demo_accounts() -> list[str]:
    """The exactly-two hardcoded demo accounts, in order.

    Overridable via ``SKETCHSCAPE_DEMO_USERS`` (comma-separated) so a demo
    can rename them without a code change; two hardcoded defaults keep a
    fresh checkout demo-ready with no configuration at all.
    """
    raw = os.environ.get("SKETCHSCAPE_DEMO_USERS", "demo-alice,demo-bob")
    accounts = [item.strip() for item in raw.split(",") if item.strip()]
    if len(accounts) != 2:
        raise RuntimeError(
            f"SKETCHSCAPE_DEMO_USERS must list exactly two accounts, got {accounts!r}."
        )
    return accounts


def _demo_identity(request: Request) -> Identity:
    """Exactly two hardcoded accounts, selected by the mock-mode dev-user header.

    Real per-project enforcement applies (unlike ``mock``): this is what lets
    the demo show one person unable to edit another's contributions.
    """
    dev_user = request.headers.get("X-SketchScape-Dev-User")
    accounts = demo_accounts()
    if dev_user not in accounts:
        raise HTTPException(
            401,
            f"X-SketchScape-Dev-User must be one of the demo accounts: {', '.join(accounts)}.",
        )
    return Identity(user_id=dev_user, kind="user", via="demo")


def _clerk_identity(request: Request) -> Identity:
    # Imported lazily so `clerk-backend-api` stays an optional, cloud-only
    # dependency (backend/requirements-cloud.txt) -- the mock-mode base
    # install never needs it, matching storage.py's lazy `boto3` import.
    from clerk_backend_api import AuthenticateRequestOptions, Clerk  # noqa: PLC0415

    secret_key = os.environ.get("CLERK_SECRET_KEY")
    if not secret_key:
        # run_startup_checks() refuses to start before this can be reached in
        # a real deployment; this is a defensive backstop only (e.g. a test
        # or script that calls require_identity directly).
        raise HTTPException(500, "CLERK_SECRET_KEY is not configured.")

    clerk = Clerk(bearer_auth=secret_key)
    request_state = clerk.authenticate_request(
        request,
        AuthenticateRequestOptions(
            accepts_token=["session_token", "m2m_token"],
            authorized_parties=web_origins(),
        ),
    )
    if not request_state.is_signed_in:
        raise HTTPException(401, detail=str(request_state.reason))

    payload = request_state.payload or {}
    # RequestState doesn't say which of the accepted token types matched, so
    # the payload shape tells us: a session token's JWT always carries a
    # `sub` claim; the m2m verification response carries `subject` instead
    # (see clerk_backend_api.security.types.M2MMachineAuthObject).
    if "sub" in payload:
        return Identity(user_id=str(payload["sub"]), kind="user", via="clerk")
    if "subject" in payload:
        return Identity(user_id=f"nemoclaw:{payload['subject']}", kind="service", via="clerk")
    raise HTTPException(401, detail="Unrecognized Clerk token payload.")


def require_identity(request: Request) -> Identity:
    """FastAPI dependency: who is calling, verified per ``SKETCHSCAPE_AUTH_MODE``.

    - ``mock`` (default): trusts an ``X-SketchScape-Dev-User`` header, for
      local development and the test suite. No network call, no secret.
    - ``demo``: the same header, restricted to exactly two hardcoded accounts,
      with real membership/ownership enforcement (see module docstring).
    - ``clerk``: verifies a real Clerk session or M2M bearer token.
    """
    mode = _auth_mode()
    if mode == "mock":
        return _mock_identity(request)
    if mode == "demo":
        return _demo_identity(request)
    if mode == "clerk":
        return _clerk_identity(request)
    raise RuntimeError(f"Unknown SKETCHSCAPE_AUTH_MODE '{mode}'. Use 'mock', 'demo', or 'clerk'.")


def require_user(identity: Identity = Depends(require_identity)) -> Identity:
    """Only a human caller (a Clerk session, or the mock dev user), never a service."""
    if identity.kind not in ("user", "dev"):
        raise HTTPException(403, "This endpoint requires a user identity.")
    return identity


def require_service(identity: Identity = Depends(require_identity)) -> Identity:
    """Only a Clerk M2M service caller (e.g. NemoClaw), never a human."""
    if identity.kind != "service":
        raise HTTPException(403, "This endpoint requires a service identity.")
    return identity


def author_from_identity(identity: Identity) -> str | None:
    """Resolve the ``author`` to record on a new blueprint revision/publication.

    Only a real, verified identity (``clerk`` or ``demo``) is recorded:
    mock-mode/manual authoring keeps ``author`` unset, matching today's
    mock-mode behavior (Hard Rule 2) and the step-15 comment on
    ``ExperienceBlueprint.author``. ``identity.user_id`` already carries the
    right shape per kind (a Clerk ``sub`` for a user, ``nemoclaw:<subject>``
    for a service caller, or a fixed demo account id), so no further
    branching is needed here.
    """
    return identity.user_id if identity.via in ("clerk", "demo") else None


def require_mock_mode() -> None:
    """FastAPI dependency guarding the legacy demo routes (``/scene``, etc.).

    Those routes predate the project/blueprint model, operate on unscoped
    process-global state, and carry no identity check of their own -- fine
    for the mock-mode local demo, not something to leave reachable once real
    per-project enforcement applies (``demo`` or ``clerk``). Step 17/21's
    room API is the intended replacement surface for headsets and the web
    app in both of those modes.
    """
    if _auth_mode() != "mock":
        raise HTTPException(404)


def run_startup_checks() -> None:
    """Refuse to start on an unsafe or self-contradictory configuration.

    Called from main.py's ``lifespan`` on every startup. Raises
    ``RuntimeError`` (never just logs/warns) so the process exits instead of
    serving traffic under a configuration that would silently do the wrong
    thing.
    """
    mode = _auth_mode()
    if mode == "clerk":
        if not os.environ.get("CLERK_SECRET_KEY"):
            raise RuntimeError(
                "SKETCHSCAPE_AUTH_MODE=clerk requires CLERK_SECRET_KEY to be set."
            )
        origins = web_origins()
        if not origins or "*" in origins:
            raise RuntimeError(
                "SKETCHSCAPE_AUTH_MODE=clerk requires SKETCHSCAPE_WEB_ORIGINS to list "
                "one or more explicit web origins (no '*', and not empty)."
            )
    elif mode == "demo":
        demo_accounts()  # raises if SKETCHSCAPE_DEMO_USERS isn't exactly two accounts
        origins = web_origins()
        if not origins or "*" in origins:
            raise RuntimeError(
                "SKETCHSCAPE_AUTH_MODE=demo requires SKETCHSCAPE_WEB_ORIGINS to list "
                "one or more explicit web origins (no '*', and not empty)."
            )
    elif mode == "mock":
        storage_backend = os.environ.get("SKETCHSCAPE_STORAGE_BACKEND", "local").strip().lower()
        if storage_backend in {"dynamodb", "aws", "dynamo"}:
            raise RuntimeError(
                "SKETCHSCAPE_AUTH_MODE=mock cannot be combined with "
                "SKETCHSCAPE_STORAGE_BACKEND=dynamodb; use SKETCHSCAPE_AUTH_MODE=clerk "
                "for a real deployment, or SKETCHSCAPE_STORAGE_BACKEND=local for mock."
            )
        pipeline_mode = os.environ.get("PIPELINE_MODE", "mock").strip().lower()
        if pipeline_mode != "mock":
            raise RuntimeError(
                f"SKETCHSCAPE_AUTH_MODE=mock cannot be combined with "
                f"PIPELINE_MODE={pipeline_mode!r}; use SKETCHSCAPE_AUTH_MODE=clerk for a "
                f"real deployment, or PIPELINE_MODE=mock for local/demo."
            )
    else:
        raise RuntimeError(f"Unknown SKETCHSCAPE_AUTH_MODE '{mode}'. Use 'mock', 'demo', or 'clerk'.")
