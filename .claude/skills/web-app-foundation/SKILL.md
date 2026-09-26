---
name: web-app-foundation
description: Use for Build Plan step 19 — creating the SketchScape web app in app/ (React + Vite + TypeScript + Tailwind + Zustand + lucide-react) with Clerk sign-in via @clerk/react, an authenticated API client for the FastAPI backend, the environment/config setup, and an offline mock mode. Replaces the earlier Electron desktop-app plan.
---

# Web app foundation (step 19)

## Gate

`python3 scripts/check_collab_gates.py 19` (needs 13 and 16). BLOCKED means stop.

## Decision

The user's control surface is a **web app** at `app/`, not Electron
(decided 2026-09-25). Clerk officially supports React web apps, and its
Electron support is unofficial. A web app also runs in the Quest browser.
Keep the visual direction from AGENT.md (clean, dark, minimal,
lucide-react). No Next.js: the backend stays FastAPI.

## Stack (verified package names)

- Vite + React + TypeScript, Tailwind, Zustand, lucide-react.
- `@clerk/react`. The old name `@clerk/clerk-react` is replaced, so don't
  install it. Key: `VITE_CLERK_PUBLISHABLE_KEY`.
- Pin exact versions in `package.json` and commit the lockfile.

## Config (`app/.env.development`, `app/.env.production`; see the matrix in `collab-vr-accounts-and-gates`)

```
VITE_SKETCHSCAPE_API_URL=http://localhost:8000
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...   # public; omit for offline mock mode
```
- **Only public values.** Vite bakes every `VITE_*` variable into the
  public JavaScript. Never add a secret; the gate script fails on any
  `VITE_*SECRET*` name and on Clerk `sk_` keys.
- Commit `app/.env.example` with placeholders. Keep real `.env*` files
  git-ignored.

## Build

1. `main.tsx`: when `VITE_CLERK_PUBLISHABLE_KEY` is set, wrap the app in
   `<ClerkProvider publishableKey=…>`. When it isn't set, run **mock
   mode**: no Clerk, and the API client sends `X-SketchScape-Dev-User`.
   This only works against a backend in `SKETCHSCAPE_AUTH_MODE=mock`, which
   keeps the offline demo working (Hard Rule 2).
2. Routes: Sign in / Sign up (Clerk components), Projects, Project detail,
   Upload (step 20), Link Quest (step 20), Room (live revision + approve
   NemoClaw proposals, step 24).
3. **API client** (`src/api/client.ts`), used for every call:
   - Before each request, `const token = await getToken()` from
     `useAuth()`, then `Authorization: Bearer ${token}`. Don't store tokens
     in state, `localStorage`, or logs; `getToken()` handles caching and
     refresh.
   - Base URL from `VITE_SKETCHSCAPE_API_URL`.
   - Map errors to readable messages: 401 → sign in again; 403 → "you're
     not a member of this project"; 409 → show the server's message; 413 →
     file too large (backend limit 16 MB); 415 → unsupported file type.
   - Upload progress: use `XMLHttpRequest` (fetch has no upload progress)
     for multipart uploads.
   - Poll jobs without blocking the UI (AGENT.md rule).
4. **Rendering user text:** always as text, never `dangerouslySetInnerHTML`
   (memory text, labels, and NemoClaw explanations are untrusted).
5. Hosting is a separate decision. Build output is static (`vite build`),
   and whoever hosts it adds that origin to `SKETCHSCAPE_WEB_ORIGINS` and
   the Clerk instance. Don't provision hosting without approval.

## Tests

Vitest for the API client (token header added, error mapping, mock-mode
header). Add `cd app && npm ci && npm test && npm run build` to
`verify_local.sh` only when `app/node_modules` exists, following the
existing `.venv`-optional pattern, so verification still works offline
without Node installed.

## Definition of done

`python3 scripts/check_collab_gates.py --done 19` and
`bash scripts/verify_local.sh` pass. Signed in with Clerk against a dev
backend in `clerk` mode, the app lists and creates projects. With no
publishable key against a mock backend, the same screens work offline.
