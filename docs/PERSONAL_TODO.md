# What you personally need to do right now

Last updated: 2026-09-26 (after the decision to use two hardcoded accounts
instead of Clerk/Meta account setup — see `docs/KNOWN_ISSUES.md` R13).

**The "Step 13 account dashboards" and "Step 14 Quest Meta identity spike"
work below is retired.** The project uses two hardcoded accounts
(`SKETCHSCAPE_DEMO_USERS`) as the real identity model, not Clerk/Meta
accounts, so none of the Clerk app, Meta Horizon app, Unity Meta provider,
or on-device `GetUserProof` work is needed. It's kept below for reference
only, in case a real multi-user product is built later. The gates it
referred to (`clerk_app_ready`, `meta_app_ready`,
`unity_meta_provider_configured`, `quest_meta_identity_spike_passed`) no
longer exist in `config/collab-vr/gates.json`.

This is **only** the human/dashboard/hardware work. Coding steps agents can
run without you are listed at the bottom so you can ignore them.

---

## Do next (blocks the Collaborative VR track)

Nothing blocks coding today. Steps 19, 20, 21, 22, 24, 26, 27, 28, 29 can
all start without any dashboard work from you (see "Agents can do without
you" below). The one thing left for you:

| Task | Why | Notes |
| --- | --- | --- |
| Approve GPU / AWS spend when asked | Hard Rule 3 — agents must not start EC2 or paid runs alone | Step 27 and any re-smoke of the GPU path |
| Confirm `two_headset_verified` / `account_switcher_verified` after trying it on real hardware | Manual gates only you can set | Steps 22, 25 |

---

## Retired (kept for reference only) — Step 13 account dashboards

Unity Cloud is already linked — that part still matters for step 22
(Multiplayer Services needs a linked Unity Cloud project), and is checked
automatically. The rest below assumed Clerk/Meta accounts, which this
track no longer uses.

| # | Task | When done, tell an agent so they can flip |
| --- | --- | --- |
| 1a | **Clerk (dev):** create the app; note the **publishable** key (`pk_…`); put the **secret** key only in backend env (never the repo or chat); make sure `http://localhost:5173` works as a allowed origin; confirm you can create an M2M machine for NemoClaw | ~~gate `clerk_app_ready`~~ (retired) |
| 1b | **Meta Horizon:** create the developer app for the Quest build; note **App ID**; put **App Secret** only in backend env + Unity Dashboard; **add every tester as a test user** (required until Data Use Checkup is approved) | ~~gate `meta_app_ready`~~ (retired) |
| 1c | **Unity Dashboard → Authentication → ID Providers → Meta Quest (Oculus):** enter that Meta App ID + App Secret | ~~gate `unity_meta_provider_configured`~~ (retired) |

## Retired (kept for reference only) — Step 14 Quest Meta identity spike (real headset)

On a **real Quest** signed in as a **test user**, this would have proved:

1. Entitlement check passes
2. `GetLoggedInUser` returns an ID
3. Two `GetUserProof` nonces obtained
4. `SignInWithOculusAsync` succeeds with one nonce
5. The other nonce validates with `is_valid: true` at
   `graph.oculus.com/user_nonce_validate` (run from a shell with the App
   Secret in an env var — never paste the secret into chat)

Not needed — step 22's Unity networking now uses anonymous Unity sign-in
(`SignInAnonymouslyAsync`) tagged with the chosen hardcoded account id,
via an in-headset account switcher, instead of Meta account sign-in.

---

## Soon, but not blocking coding today

| Task | Why | Notes |
| --- | --- | --- |
| Approve GPU / AWS spend when asked | Hard Rule 3 — agents must not start EC2 or paid runs alone | Step 27 and any re-smoke of the GPU path |
| Set cloud env vars on the EC2 API process | Live DynamoDB/S3 path on the instance | Optional for mock judging; ~5 min; `infra/aws/SMOKE_TEST_GUIDE.md` Step 5 |
| Record demo video + write-up | Judging | Prefer local mock + precomputed assets (`docs/PROJECT_STATUS.md`) |
| Keep secrets out of the repo | Gate script fails `verify_local.sh` on leaks | Clerk `sk_…` (the `clerk` code path still exists, unused), any `VITE_*SECRET*` |

Secrets that live **only** in backend secret storage (not files, not
chat):

- `SKETCHSCAPE_NEMOCLAW_TOKEN` (≥32 random bytes, when the step-16
  follow-up for NemoClaw's service identity lands — `docs/KNOWN_ISSUES.md`
  R14, needed before step 24)
- Model API keys for NemoClaw (`META_MODEL_API_KEY` / `XAI_API_KEY` / …)

Not needed for this track (kept only if `clerk` mode is ever revived):
`CLERK_SECRET_KEY`, `SKETCHSCAPE_META_APP_SECRET`,
`SKETCHSCAPE_ROOM_TOKEN_SECRET`.

---

## Already done (you can ignore)

- Step 13 — scope approval for the Collaborative VR track
- Step 15 — backend revision safety
- Step 16 — backend auth core (two hardcoded accounts, mock mode)
- Step 17 — membership, invites, ownership, `room_prompt`
- Steps 1–2 — contributor data model + API
- Step 26 — durable jobs, shared uploads, multi-object upload API
- Unity Cloud project linked

---

## Agents can do without you (for now)

None of steps 19, 20, 21, 22, 26, 27, 28 need your dashboard work — the
account switcher is just an in-app picker between the hardcoded accounts,
built entirely by agents.

| Step | What | Needs |
| --- | --- | --- |
| 19 | Web app foundation, account picker | 16 (ready) |
| 20 | Web uploads, Notability sketches, optional text | 7, 17, 19, 26 |
| 21 | Public room API, account-switcher backend | 15, 17 (ready) |
| 22 | Unity networking, anonymous sign-in + account switcher | Unity Cloud linked (ready) |
| 24 | NemoClaw room tools | 3 (not started), 15, 16, 21 — also needs the R14 service-token follow-up |
| 26 | Durable jobs, shared uploads, multi-object upload API | 15 (ready) |
| 27 | GPU worker: multi-object masks, dispatcher | 26 (ready; every GPU run still needs your approval) |
| 28 | Letters: backend, recipient-only open, web form | 17, 19, 21, 26 |
| 7 | Notability flat card + memory plaque | — |

Blocked on real hardware, not on you personally:

| Step | Waiting on |
| --- | --- |
| 25 | Real two-headset + web verification |

Full gate status: `python3 scripts/check_collab_gates.py --status`
