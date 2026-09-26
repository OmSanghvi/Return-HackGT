// Build-time switch between the two modes described in web-app/hardcode.MD.
//
// - VITE_SKETCHSCAPE_API_URL unset (default): the site behaves exactly as it
//   always has -- one fake local user, photos as data URLs in localStorage,
//   timed animations standing in for the backend. Nothing in this file
//   changes that path; App.tsx branches on REAL_MODE before any of the mock
//   code runs.
// - VITE_SKETCHSCAPE_API_URL set: "real mode" -- an account picker between
//   the two hardcoded SKETCHSCAPE_DEMO_USERS accounts, and every screen talks
//   to the real FastAPI backend through src/api/client.ts.
//
// Only VITE_* (public, baked into the bundle) values live here -- never a
// secret. See collab-vr-accounts-and-gates for the full config matrix.

/** Empty string counts as unset, so `VITE_SKETCHSCAPE_API_URL=` in an env file cleanly falls back to mock mode. */
const rawApiUrl = (import.meta.env.VITE_SKETCHSCAPE_API_URL ?? '').trim();

/** True when the site should talk to a real backend instead of the local mock store. */
export const REAL_MODE = rawApiUrl.length > 0;

/**
 * Base URL every API call is joined against.
 *
 * - `http://localhost:8000` in local dev (talks straight to the FastAPI dev
 *   server; CORS must allow the Vite origin -- see hardcode.MD's "Local dev"
 *   section).
 * - `/api` in production: same-origin path that vercel.json rewrites to the
 *   EC2 backend server-side, which is what avoids the browser ever making an
 *   HTTPS-page-to-HTTP-backend ("mixed content") request.
 */
export const API_BASE_URL = rawApiUrl.replace(/\/+$/, '');

/**
 * The two hardcoded demo accounts, in order. Matches the backend's
 * `SKETCHSCAPE_DEMO_USERS` default (`demo-alice,demo-bob`). This is a
 * build-time list, not fetched from the backend (nothing today exposes that
 * env var over HTTP -- see the web-app-foundation skill) -- override it with
 * `VITE_SKETCHSCAPE_ACCOUNTS` if a deployment renames the accounts, so the
 * picker's labels never hard-code "demo-alice"/"demo-bob" as if those were
 * the only possible ids.
 */
export const DEMO_ACCOUNTS: string[] = (
  (import.meta.env.VITE_SKETCHSCAPE_ACCOUNTS ?? 'demo-alice,demo-bob') as string
)
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);
