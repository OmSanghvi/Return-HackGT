---
name: collab-vr-accounts-and-gates
description: Use before ANY work on the Collaborative VR + web accounts track (Build Plan steps 13-29). Explains the identity model (two hardcoded accounts, decision 2026-09-26 — no Clerk, no Meta account linking, no room tokens), the in-app account switcher used on both the website and the Quest headset, the prerequisite gate system (scripts/check_collab_gates.py + config/collab-vr/gates.json), and the config and secrets matrix for local/dev/prod. Load this first, then the skill for your step.
---

# Collaborative VR + web accounts: identity, gates, config (step 13)

## Identity model (revised 2026-09-26 — supersedes the 2026-09-25 Clerk/Meta plan)

**There is no Clerk sign-in and no Meta account linking in this plan.**
Every person is one of exactly two hardcoded accounts, named in
`SKETCHSCAPE_DEMO_USERS` (default `demo-alice,demo-bob`), verified
server-side by `SKETCHSCAPE_AUTH_MODE=demo` (`backend/auth.py`,
`backend-auth-clerk`) with **real per-project membership/ownership
enforcement** — this is not a lightweight stand-in for something else;
it's the actual identity system for this track.

| Who | Signs in with | Backend sees | Verified by |
| --- | --- | --- | --- |
| Person on the **website** (`app/`) | An account picker (no sign-in screen) | `X-SketchScape-Dev-User` header | `require_identity` in `demo` mode, restricted to the two hardcoded accounts |
| Person on a **Quest** | The same account picker, as an in-headset "Account 1 / Account 2" switcher | The same header, sent directly by the headset | Same as above |
| **NemoClaw** | A shared bearer token (`SKETCHSCAPE_NEMOCLAW_TOKEN`, matching the existing `SKETCHSCAPE_WORKER_TOKEN` pattern) | `kind="service"` | Not yet built — small `auth.py` follow-up needed before step 24 (`docs/KNOWN_ISSUES.md` R14); NemoClaw/step 3 hasn't started |
| Unity Cloud (Multiplayer Services) | Anonymous Unity sign-in (`SignInAnonymouslyAsync`) | UGS player, tagged with a player property holding the chosen account id | Unity Authentication's built-in anonymous provider — no Meta account needed |

- **Two hardcoded accounts are the account system.** Nobody signs up.
  `SKETCHSCAPE_DEMO_USERS` lists the accounts; the website and the Quest
  each offer a picker/switcher between them, not a login form.
- **One headset, one shared Meta account for the hardware — but that's
  irrelevant to app identity.** The Quest's own Meta/Horizon login (for
  the OS and the Store) is separate from who the *app* thinks you are.
  The app-level identity is always the chosen hardcoded account.
- **Unity Multiplayer Services session identity is anonymous, and that's
  fine.** Distributed Authority and NGO 2.x don't care which auth
  provider signed a player in; they need *a* signed-in UGS player, and
  `SignInAnonymouslyAsync` provides one. The account id goes on as a
  player property, not through the sign-in call itself.
- **Superseded (kept for reference only, see below):** Clerk as the
  account system, Meta Platform SDK `GetUserProof()` +
  `SignInWithOculusAsync` + a backend room token, linked once via a
  website code. None of it is built, and nothing in this plan depends on
  it. `SKETCHSCAPE_AUTH_MODE=clerk` and its code in `backend/auth.py`
  still exist and are still tested — a possible future upgrade path if
  this ever becomes a real multi-user product — but don't build new work
  against it, and don't wire the account switcher through it.

### Why this replaced the Clerk/Meta plan (decided 2026-09-26)

The project is using two hardcoded accounts for the live demo, not a
temporary stand-in ahead of a Clerk/Meta rollout. Keeping Clerk/Meta in
the *plan* (even as "the eventual real path") meant steps 19, 20, 21, 22,
28, 29 all carried dependencies on steps 13/14/18 (Clerk app + Meta app +
Quest linking), which needed dashboard work and on-device testing nobody
had scheduled. Retiring 13's old scope and steps 14/18 entirely removes
those dependencies: steps 19, 20, 21, 28 now depend only on already-done
steps (15, 16, 17, 26), and step 22 needs only a linked Unity Cloud
project. See `docs/KNOWN_ISSUES.md` R13 for the full list of files this
touched, and R14/R15 for what's still open.

### The account switcher (website and Quest)

One UI idea, used in both places: a picker/switcher between the accounts
in `SKETCHSCAPE_DEMO_USERS`. Picking an account sets which identity every
subsequent API call presents (the `X-SketchScape-Dev-User` header),
including the account list the switcher itself offers (never hard-code
"Account 1"/"Account 2" as `demo-alice`/`demo-bob` — read the list from
config, since a demo can rename the accounts).

- **One shared room, not two worlds:** both accounts view the **same**
  project — the one published blueprint (step 15's LIVE pointer) is the
  single source of truth, and both accounts read and write it through the
  same room API (step 21). Switching accounts changes each account's
  *view* of that one shared room — which objects are `editable_by_me`
  (step 17 ownership, derived from `Contribution`, so images/objects are
  already attributed to whichever account uploaded them — no schema
  change needed) and which letters they can open (step 28) — while the
  underlying scene state stays shared and in sync, since switching
  accounts never forks any data.
- **Letters cross-visibility:** this is what makes "account 2 sees the
  letter account 1 wrote them, or vice versa" work — the step 28 design
  (a sealed letter's page is visible to its author **and** its addressed
  recipients, not the whole room). Switch to account 2 and, if account 1
  addressed them a letter, they can see and open it; switch back to
  account 1 and they see their own sent letter. This is the existing
  sealed/opened + author-or-recipient access rule, not a new data model.
- On the **website** (step 19), the switcher is a simple picker in place
  of a sign-in screen.
- On the **Quest** (step 21's backend half + step 22's Unity half), it's
  an in-headset panel. A native Quest client sends no `Origin` header, so
  the `demo`-mode CORS lock (`SKETCHSCAPE_WEB_ORIGINS`) doesn't affect it.

## Gate rule (every step 13-29, and the guided tour bot steps 30-34)

Steps 30–34 (the in-VR guide bot, decision 2026-09-26) use the same gate
script, the same identity header, and the same secret scan. Their skills
are `guided-tour-contract`, `nemoclaw-tour-authoring`, `muse-guide-runtime`,
and `unity-guide-bot`.


1. Before writing code or config for a step, run
   `python3 scripts/check_collab_gates.py <step>`.
2. **BLOCKED means stop.** Don't implement, stub, fake, or work around a
   missing prerequisite. Tell the user what's missing and offer to do that
   step instead (it has its own gate).
3. Done means `python3 scripts/check_collab_gates.py --done <step>` **and**
   `bash scripts/verify_local.sh` both pass. Adding strings to satisfy the
   gate without a working, tested implementation breaks Hard Rule 9.
4. Manual gates in `config/collab-vr/gates.json` may be set only after the
   user explicitly confirms them in the conversation.
5. Every run scans for leaked secrets: Clerk `sk_live_`/`sk_test_` keys
   (the `clerk` code path still exists, so this still matters) and any
   `VITE_*SECRET*` variable in `app/` (Vite bundles `VITE_*` values into
   the public site). A hit fails `verify_local.sh`.

## Step order

| Step | What | Needs |
| --- | --- | --- |
| 13 | Scope approval for this track (done) | — |
| 15 | Backend revision safety | — |
| 16 | Backend auth core (hardcoded demo accounts) | 15 |
| 17 | Membership, invites, account binding, ownership | 2, 16 |
| 19 | Web app foundation (`app/`), account picker | 16 |
| 20 | Web uploads (multi-object), Notability sketches, optional text | 7, 17, 19, 26 |
| 21 | Public room API `/v1/rooms/*`, account-switcher backend | 15, 17 |
| 22 | Unity networking (anonymous sign-in + account switcher, Distributed Authority) | — (needs a linked Unity Cloud project) |
| 23 | Unity backprop client | 21, 22 |
| 24 | NemoClaw room tools | 3, 15, 16, 21 |
| 25 | Two or more headsets + web, end to end | 20, 23, 29 |
| 26 | Durable jobs, shared uploads, multi-object upload API, batch polling | 15 |
| 27 | GPU worker: SAM 3.1 masks from person-chosen selections, dispatcher, benchmarked concurrency | 26 |
| 28 | Letters: backend, recipient-only open, web form | 17, 19, 21, 26 |
| 29 | Letters in VR: envelope + 3D paper page | 22, 28 |

Steps 14 and 18 (the Quest Meta-identity spike, and the backend Meta
identity exchange + Quest↔Clerk linking) are **retired** — see "Why this
replaced the Clerk/Meta plan" above. Their research stays in
`meta-quest-identity` for reference only.

Every known issue and where it's fixed: `docs/KNOWN_ISSUES.md`. Check it
before starting a step, so you don't rediscover a solved problem.

Can start today: 15, 16, 17, 19, 20, 21, 26 (15/16/17/26 already are;
19/20/21 need no manual gate at all now). Data model, S3 layout, and
polling rules for every step are in `docs/DATA_ARCHITECTURE.md`.
Everything takes lists of people; never hard-code two.

## Config and secrets matrix (single source for every step)

| Setting | Local mock | Dev | Prod | Lives in |
| --- | --- | --- | --- | --- |
| `PIPELINE_MODE` | `mock` | per env | per env | backend env |
| `SKETCHSCAPE_STORAGE_BACKEND` | `local` | `dynamodb` | `dynamodb` | backend env |
| `SKETCHSCAPE_AUTH_MODE` | `mock` | `demo` | `demo` | backend env |
| `SKETCHSCAPE_DEMO_USERS` | `demo-alice,demo-bob` (default) | same, or renamed for a real demo | same | backend env — the account switcher reads this list, never hard-coded |
| `SKETCHSCAPE_WEB_ORIGINS` | `http://localhost:5173` | dev site URL | prod site URL | backend env (CORS; never `*` in `demo` mode) |
| `SKETCHSCAPE_NEMOCLAW_TOKEN` | unset | ≥32 random bytes | ≥32 random bytes | backend secret storage **only** — not built yet, see R14 |
| `VITE_SKETCHSCAPE_API_URL` | `http://localhost:8000` | dev API | prod API | `app/.env.*` |
| Backend base URL in Unity | local | dev API | prod API | Unity public config ScriptableObject |
| `SKETCHSCAPE_ARTIFACTS_BACKEND` / `_BUCKET` | `local` | `s3` + bucket | `s3` + bucket | backend env (uploads, masks, PLYs, letters) |
| `SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD` | 8 | 8 | 8 | backend env (safety cap per photo, not a quota) |
| `SKETCHSCAPE_GPU_CONCURRENCY` | n/a | 1 until benchmarked | benchmarked value | GPU host env |
| `NEMOCLAW_MODEL_PROVIDER` / `NEMOCLAW_MODEL` | mock | `meta` | `meta` | NemoClaw runtime |
| `META_MODEL_API_KEY` / `XAI_API_KEY` / `NEBIUS_API_KEY` | unset | runtime secret | runtime secret | NemoClaw credential provider **only** |

Not part of this plan any more (superseded, R13): `CLERK_SECRET_KEY`,
`SKETCHSCAPE_META_ENABLED`/`_META_APP_ID`/`_META_APP_SECRET`,
`SKETCHSCAPE_ROOM_TOKEN_SECRET`, `VITE_CLERK_PUBLISHABLE_KEY`. Leave them
unset; don't configure them for this track.

Rules:
- The backend **refuses to start** when misconfigured (built in step 16):
  - `demo` mode without `SKETCHSCAPE_WEB_ORIGINS`.
  - `demo` mode without exactly two `SKETCHSCAPE_DEMO_USERS`.
  - `mock` mode with DynamoDB storage or a non-mock pipeline.
- Mock mode stays the default and fully offline (Hard Rule 2). The web app
  runs against a mock backend (dev-user header) with no account picker
  needed, and the Unity Editor uses a mock identity.
- Cost decision (user, 2026-09-25): **no per-user upload limits** on
  reconstruction. Every upload starts a GPU job when the cloud pipeline is
  on. That's uncapped spend, so watch the AWS bill, and keep the GPU
  instance start itself manual (Hard Rule 3 still applies to agents).

## Definition of done (step 13)

`python3 scripts/check_collab_gates.py --done 13` passes (scope approval
only — the account setup this step used to cover is retired).
