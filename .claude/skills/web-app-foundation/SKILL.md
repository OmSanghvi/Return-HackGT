---
name: web-app-foundation
description: Use for Build Plan step 19 — creating the SketchScape web app in app/ (React + Vite + TypeScript + Tailwind + Zustand + lucide-react) with an account picker between the two hardcoded SKETCHSCAPE_DEMO_USERS accounts (no Clerk sign-in — decision 2026-09-26), an authenticated API client for the FastAPI backend, the environment/config setup, and an offline mock mode. Replaces the earlier Electron desktop-app plan.
---

# Web app foundation (step 19)

## Gate

`python3 scripts/check_collab_gates.py 19` (needs 16). BLOCKED means stop.

## Decision

The user's control surface is a **web app** at `app/`, not Electron
(decided 2026-09-25). A web app also runs in the Quest browser. Keep the
visual direction from AGENT.md (clean, dark, minimal, lucide-react). No
Next.js: the backend stays FastAPI.

**No Clerk (decided 2026-09-26, see `collab-vr-accounts-and-gates` R13).**
There is no sign-in screen. Identity is one of the two hardcoded accounts
in `SKETCHSCAPE_DEMO_USERS` (default `demo-alice,demo-bob`), chosen from
an **account picker**, the same idea the Quest headset's switcher uses.

## Stack (verified package names)

- Vite + React + TypeScript, Tailwind, Zustand, lucide-react.
- No `@clerk/react` and no Clerk key — don't add either.
- Pin exact versions in `package.json` and commit the lockfile.

## Config (`app/.env.development`, `app/.env.production`; see the matrix in `collab-vr-accounts-and-gates`)

```
VITE_SKETCHSCAPE_API_URL=http://localhost:8000
```
- **Only public values.** Vite bakes every `VITE_*` variable into the
  public JavaScript. Never add a secret; the gate script fails on any
  `VITE_*SECRET*` name.
- Commit `app/.env.example` with placeholders. Keep real `.env*` files
  git-ignored.

## Build

1. **Account picker**, shown before anything else: a small screen or
   header control offering the accounts (call
   `GET /v1/projects` or a similarly cheap existing route isn't the right
   source — instead read the list from a public, non-secret source: the
   simplest correct option is a build-time list matching
   `SKETCHSCAPE_DEMO_USERS`'s default, shown as plain buttons/a dropdown;
   don't fetch the backend's env var directly, since nothing today
   exposes it over HTTP). Store the chosen account (Zustand store +
   `localStorage`, so a reload keeps the choice) and let the person switch
   at any time from a persistent header control, mirroring the Quest
   switcher in `collab-vr-accounts-and-gates`.
   - **Mock mode** (no backend account enforcement): when the app talks to
     a `SKETCHSCAPE_AUTH_MODE=mock` backend, the picker can default to a
     single "dev-user" identity and skip the picker UI entirely — mock
     mode keeps working offline either way (Hard Rule 2).
2. Routes: Projects, Project detail, Upload (step 20), Room (live
   revision + approve NemoClaw proposals, step 24). No Sign in / Sign up
   route, and no Link Quest route (retired — there's no per-headset
   account to link; the headset picks the same two accounts).
3. **API client** (`src/api/client.ts`), used for every call:
   - Every request sends `X-SketchScape-Dev-User: <chosen account>` from
     the picker's stored value. No bearer token, no `getToken()` call.
   - Base URL from `VITE_SKETCHSCAPE_API_URL`.
   - Map errors to readable messages: 401 → "choose an account" (bad or
     missing header); 403 → "you're not a member of this project"; 409 →
     show the server's message; 413 → file too large (backend limit
     16 MB); 415 → unsupported file type.
   - Upload progress: use `XMLHttpRequest` (fetch has no upload progress)
     for multipart uploads.
   - Poll jobs without blocking the UI (AGENT.md rule).
4. **Rendering user text:** always as text, never `dangerouslySetInnerHTML`
   (memory text, labels, and NemoClaw explanations are untrusted).
5. Hosting is a separate decision. Build output is static (`vite build`),
   and whoever hosts it adds that origin to `SKETCHSCAPE_WEB_ORIGINS`.
   Don't provision hosting without approval.

## Tests

Vitest for the API client (account header added from the picker's stored
value, error mapping, mock-mode default). Add
`cd app && npm ci && npm test && npm run build` to `verify_local.sh` only
when `app/node_modules` exists, following the existing `.venv`-optional
pattern, so verification still works offline without Node installed.

## Definition of done

`python3 scripts/check_collab_gates.py --done 19` and
`bash scripts/verify_local.sh` pass. Against a `demo`-mode backend,
picking either account in the picker lists and creates projects under
that account, and switching accounts changes what's shown as
editable/owned. With no picker interaction against a mock backend, the
same screens work offline.
