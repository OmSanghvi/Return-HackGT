---
name: collab-vr-accounts-and-gates
description: Use before ANY work on the Collaborative VR + web accounts track (Build Plan steps 13-29). Explains the identity model (Clerk on the website, Meta account on the Quest, linked once), the prerequisite gate system (scripts/check_collab_gates.py + config/collab-vr/gates.json), the config and secrets matrix for local/dev/prod, and step 13 account setup. Load this first, then the skill for your step.
---

# Collaborative VR + web accounts: identity, gates, config (step 13)

## Identity model (decided 2026-09-25)

| Who | Signs in with | Backend sees | Verified by |
| --- | --- | --- | --- |
| Person on the **website** (`app/`) | Clerk (`@clerk/react`) | Clerk session token | `clerk-backend-api` `authenticate_request`, `accepts_token=["session_token"]`, `authorized_parties` = web origins |
| Person on a **Quest** | Their Meta account (already signed in on the headset) | Backend **room token** (short JWT) | Backend checked a Meta `GetUserProof` nonce at `graph.oculus.com/user_nonce_validate`, then looked up the linked Clerk user |
| **NemoClaw** | Clerk M2M token | `kind="service"` | `accepts_token=["m2m_token"]` |
| Unity Cloud (Multiplayer Services) | Meta account | UGS player | Unity's built-in Meta Quest provider: `SignInWithOculusAsync(nonce, userId)` |

- **Clerk is the account system.** Every person is a Clerk user, created
  on the website. A Quest's Meta ID is **linked** to that Clerk user once:
  the headset shows a code, and the person enters it on the website's Link
  Quest page. Unlinked headsets can't join rooms.
- Clerk has **no Meta Quest login provider** (its Facebook login isn't the
  Meta Horizon account), so the headset never holds a Clerk token.
- The earlier plan (Clerk OAuth + PKCE browser login on the headset,
  federated into Unity via OIDC) is **dropped**. The browser redirect back
  into an immersive app was the riskiest step, and it's no longer needed.

## Gate rule (every step 13-29)

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
5. Every run scans for leaked secrets: Clerk `sk_live_`/`sk_test_` keys,
   Meta `OC|app_id|app_secret` tokens, and any `VITE_*SECRET*` variable in
   `app/` (Vite bundles `VITE_*` values into the public site). A hit fails
   `verify_local.sh`.

## Step order

| Step | What | Needs |
| --- | --- | --- |
| 13 | Accounts: Clerk app, Meta app + test users, Unity Meta provider | — |
| 14 | Quest Meta identity spike on a real headset | 13 |
| 15 | Backend revision safety | — |
| 16 | Backend auth core (Clerk web + M2M) | 15 |
| 17 | Membership, invites, Clerk binding, ownership | 2, 16 |
| 18 | Meta identity exchange + Quest linking (backend) | 14, 16 |
| 19 | Web app foundation (`app/`) | 13, 16 |
| 20 | Web uploads (multi-object), Notability sketches, optional text, Link Quest page | 7, 17, 18, 19, 26 |
| 21 | Public room API `/v1/rooms/*` | 15, 17, 18 |
| 22 | Unity networking (Meta sign-in, Distributed Authority) | 13, 14 |
| 23 | Unity backprop client | 21, 22 |
| 24 | NemoClaw room tools | 3, 15, 16, 21 |
| 25 | Two or more headsets + web, end to end | 20, 23, 29 |
| 26 | Durable jobs, shared uploads, multi-object upload API, batch polling | 15 |
| 27 | GPU worker: SAM 3.1 masks from person-chosen selections, dispatcher, benchmarked concurrency | 26 |
| 28 | Letters: backend, recipient-only open, web form | 17, 19, 21, 26 |
| 29 | Letters in VR: envelope + 3D paper page | 22, 28 |

Every known issue and where it's fixed: `docs/KNOWN_ISSUES.md`. Check it
before starting a step, so you don't rediscover a solved problem.

Can start today: 13 (you, in dashboards) and 15 (backend). 26 follows
15. Data model, S3 layout, and polling rules for every step are in
`docs/DATA_ARCHITECTURE.md`. Everything takes lists of people; never
hard-code two.

## Step 13: account setup (the user does dashboard work)

Account actions need explicit approval (Hard Rule 3). Let the user do the
dashboards unless they ask otherwise.

1. **Unity Cloud project**: already linked. The gate checks it.
2. **Clerk (dev instance):** create the application; note the
   **publishable key** (public). Keep the **secret key** only in the backend
   environment. `http://localhost:5173` must work as the dev web origin.
   → gate `clerk_app_ready`.
3. **Meta Horizon developer app** for the Quest build: note the **App ID**
   (public). The **App Secret** goes only in the backend environment and
   the Unity dashboard. **Add every tester as a test user.** User
   verification (`GetUserProof`) requires Meta's **Data Use Checkup**, and
   until Meta approves it only test users work. Submit the DUC early if
   anyone outside the team will use it. → gate `meta_app_ready`.
4. **Unity Dashboard → Authentication → ID Providers → Meta Quest
   (Oculus):** enter the Meta App ID and App Secret. →
   gate `unity_meta_provider_configured`.

## Config and secrets matrix (single source for every step)

| Setting | Local mock | Dev | Prod | Lives in |
| --- | --- | --- | --- | --- |
| `PIPELINE_MODE` | `mock` | per env | per env | backend env |
| `SKETCHSCAPE_STORAGE_BACKEND` | `local` | `dynamodb` | `dynamodb` | backend env |
| `SKETCHSCAPE_AUTH_MODE` | `mock` | `clerk` | `clerk` | backend env |
| `CLERK_SECRET_KEY` | unset | dev key | prod key | backend secret storage **only** |
| `SKETCHSCAPE_WEB_ORIGINS` | `http://localhost:5173` | dev site URL | prod site URL | backend env (CORS + Clerk `authorized_parties`; never `*` in clerk mode) |
| `SKETCHSCAPE_META_ENABLED` | `false` | `true` | `true` | backend env |
| `SKETCHSCAPE_META_APP_ID` | unset | app id | app id | backend env (public value) |
| `SKETCHSCAPE_META_APP_SECRET` | unset | secret | secret | backend secret storage **only** (+ Unity dashboard) |
| `SKETCHSCAPE_ROOM_TOKEN_SECRET` | unset | ≥32 random bytes | ≥32 random bytes | backend secret storage **only** |
| `VITE_CLERK_PUBLISHABLE_KEY` | optional | dev `pk_` | prod `pk_` | `app/.env.*` (public; never a secret) |
| `VITE_SKETCHSCAPE_API_URL` | `http://localhost:8000` | dev API | prod API | `app/.env.*` |
| Meta App ID in Unity | dev app | dev app | prod app | Unity Meta Platform settings (public) |
| Backend base URL in Unity | local | dev API | prod API | Unity public config ScriptableObject |
| `SKETCHSCAPE_ARTIFACTS_BACKEND` / `_BUCKET` | `local` | `s3` + bucket | `s3` + bucket | backend env (uploads, masks, PLYs, letters) |
| `SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD` | 8 | 8 | 8 | backend env (safety cap per photo, not a quota) |
| `SKETCHSCAPE_GPU_CONCURRENCY` | n/a | 1 until benchmarked | benchmarked value | GPU host env |
| `NEMOCLAW_MODEL_PROVIDER` / `NEMOCLAW_MODEL` | mock | `meta` | `meta` | NemoClaw runtime |
| `META_MODEL_API_KEY` / `XAI_API_KEY` / `NEBIUS_API_KEY` | unset | runtime secret | runtime secret | NemoClaw credential provider **only** |

Rules:
- The backend **refuses to start** when misconfigured (built in steps 16
  and 18):
  - `clerk` mode without `CLERK_SECRET_KEY`.
  - `clerk` mode with `*` in origins.
  - `mock` mode with DynamoDB storage or a non-mock pipeline.
  - Meta routes enabled without an app id, app secret, and room-token
    secret.
- Mock mode stays the default and fully offline (Hard Rule 2). The web app
  runs without Clerk against a mock backend (dev-user header), and the
  Unity Editor uses a mock Meta identity.
- Cost decision (user, 2026-09-25): **no per-user upload limits** on
  reconstruction. Every signed-in upload starts a GPU job when the cloud
  pipeline is on. That's uncapped spend, so watch the AWS bill, and keep
  the GPU instance start itself manual (Hard Rule 3 still applies to
  agents).

## Definition of done (step 13)

`python3 scripts/check_collab_gates.py --done 13` passes.
