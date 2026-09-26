---
name: backend-auth-clerk
description: Use for Build Plan step 16 — backend/auth.py with SKETCHSCAPE_AUTH_MODE=mock|demo|clerk. `demo` mode (two hardcoded accounts, SKETCHSCAPE_DEMO_USERS) is the track's real, permanent identity model (decision 2026-09-26, see collab-vr-accounts-and-gates) — not a stand-in for anything. It verifies the X-SketchScape-Dev-User header against exactly two accounts, records authors, locks down CORS, and refuses to start when misconfigured. `clerk` mode (Clerk session/M2M tokens) still exists and is tested but is retired from the active plan (R15) — don't build new work against it. NemoClaw's service identity needs a small follow-up (SKETCHSCAPE_NEMOCLAW_TOKEN, not yet built — R14) before step 24.
---

# Backend auth core (step 16)

**`demo` mode is the real identity model for this track (decided
2026-09-26), not a temporary stand-in for Clerk/Meta.** See
`collab-vr-accounts-and-gates` for the full picture and
`docs/KNOWN_ISSUES.md` R13. The `clerk` mode described below is real,
tested code — kept in place as a possible future upgrade — but nothing in
the current plan depends on it or should be built against it (R15).

## Gate

`python3 scripts/check_collab_gates.py 16` (needs 15). BLOCKED means stop.

## Verified facts

- `clerk-backend-api` (Python): `Clerk(bearer_auth=CLERK_SECRET_KEY).authenticate_request(request, AuthenticateRequestOptions(...))`
  accepts FastAPI `Request` objects. `accepts_token` values:
  `session_token`, `oauth_token`, `m2m_token`, `api_key`. The result has
  `is_signed_in`, `payload`, `reason`. `authorized_parties` restricts which
  web origins a session token may come from (the `azp` claim).
- The web app sends `Authorization: Bearer <await getToken()>` from
  `@clerk/react`.

## Build `backend/auth.py`

Follow the repo's pluggable pattern (`create_store`, `subject_labeler`):
one selector env var, and the SDK is imported lazily only in `clerk` mode.

- `Identity(user_id: str, kind: Literal["user", "service", "dev"], via: Literal["clerk", "meta", "mock", "demo"])`
- `require_identity(request) -> Identity` (FastAPI dependency).
  - **mock:** header `X-SketchScape-Dev-User` (default `dev-user`),
    `kind="dev"`. Membership/ownership checks no-op in this mode.
  - **demo** (added 2026-09-26): same header, restricted to exactly two
    accounts (`SKETCHSCAPE_DEMO_USERS`, default `demo-alice,demo-bob`),
    `kind="user"`, `via="demo"`. Real membership/ownership enforcement
    applies, same as `clerk`. Exists so a two-person demo runs without a
    Clerk dashboard; the `clerk` branch below is untouched and dormant.
  - **clerk:** `accepts_token=["session_token", "m2m_token"]`,
    `authorized_parties=SKETCHSCAPE_WEB_ORIGINS`.
    - `session_token` → `kind="user"`, `user_id=payload["sub"]`.
    - `m2m_token` → `kind="service"`, `user_id="nemoclaw:" + subject`.
    - Failure → 401 with `reason`.
- `require_user` / `require_service` helpers for routes that accept only
  one kind.

## NemoClaw service identity — not yet built (R14)

Removing Clerk from the active plan leaves a real gap: today `kind="service"`
is only ever produced by a Clerk M2M token, and Clerk is off this plan. Before
step 24 (NemoClaw room tools) can use `require_service`, add a fourth
`require_identity` branch:

- A new env var `SKETCHSCAPE_NEMOCLAW_TOKEN`, matching the existing
  `SKETCHSCAPE_WORKER_TOKEN` pattern (`worker_is_authorized` in
  `backend/main.py`): a shared secret, compared with
  `secrets.compare_digest`, sent as a bearer token or header by NemoClaw.
- On a match: `Identity(kind="service", user_id="nemoclaw", via="demo")`
  (or a new `via` value if that reads clearer — `via` is a `Literal`, so
  either extend it or reuse `"demo"`; use your judgment when you build
  this).
- Not urgent: NemoClaw itself (step 3) hasn't started, so nothing calls
  this yet. Do it as part of step 24's own work, not speculatively now.

## Startup checks (fail fast in `main.py` lifespan, never just warn)

| Condition | Result |
| --- | --- |
| `clerk` and no `CLERK_SECRET_KEY` | refuse to start |
| `clerk` and `SKETCHSCAPE_WEB_ORIGINS` empty or containing `*` | refuse to start |
| `demo` and `SKETCHSCAPE_WEB_ORIGINS` empty or containing `*` | refuse to start |
| `demo` and `SKETCHSCAPE_DEMO_USERS` isn't exactly two accounts | refuse to start |
| `mock` and `SKETCHSCAPE_STORAGE_BACKEND=dynamodb` | refuse to start |
| `mock` and `PIPELINE_MODE` ≠ `mock` | refuse to start |

CORS: in `clerk` and `demo` mode use `SKETCHSCAPE_WEB_ORIGINS`, not
`SKETCHSCAPE_ALLOWED_ORIGINS=*`. Allow the `Authorization` header (and
`X-SketchScape-Dev-User` for `demo`). Keep `allow_credentials=False`,
because bearer/header auth doesn't need cookies.

## Where auth applies

- Outside `mock` mode (`clerk` or `demo`), every `/v1/projects/**`,
  `/v1/reconstructions`, and `/v1/artifacts/**` route requires an identity.
  Membership (is this person in this project?) is step 17.
- `/v1/internal/**` keeps the existing worker token and never accepts user
  tokens or a demo header.
- Legacy demo routes (`/v1/scene`, `/scene`, `/sketch`, `/modify-scene`)
  stay open **only in mock mode**. In `clerk` or `demo` mode they return 404.
- Set `author` on new blueprint revisions and publication records (the
  field comes from step 15).
- Mock mode behavior and all existing tests are unchanged (Hard Rule 2).

## Dependencies

`clerk-backend-api` goes in `backend/requirements-cloud.txt`, pinned to
the version you test with. Tests stub the SDK and never call Clerk.

## Tests (`backend/test_auth.py`; add to `verify_local.sh` compile and unittest lists)

- Mock header → dev identity.
- Demo header → user identity for either hardcoded account; unknown/missing
  header → 401; misconfigured `SKETCHSCAPE_DEMO_USERS` → refuses to start.
- Stubbed Clerk: session → user; m2m → service; rejected → 401 with
  reason; wrong origin → 401.
- Each startup rule in the table refuses to start.
- In clerk mode, `/v1/internal/**` rejects a Clerk token.

## Definition of done

`python3 scripts/check_collab_gates.py --done 16` and
`bash scripts/verify_local.sh` pass.
