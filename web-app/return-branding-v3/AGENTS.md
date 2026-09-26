# Design rules for agents

This folder is return's design system: ethereal, imagery-led, glass over painted skies. Follow it for all UI, web and Unity.

The product: someone starts a **room** for a place, invites the people who were there by email, everyone adds photos and a note, and once everyone is in, return builds the room and it appears in each person's Quest (same Clerk account, no pairing code). The seven screens are specified in `components/Screen*.md`, rendered live in `previews/Screen*.html`, and shown as images in `screens/`.

## Before building UI

1. Read `BRAND.md` once per session.
2. Before using or building a component, read `components/<Name>.md` and its props in `components/index.d.ts`.
3. Open `previews/<Name>.html` to see how it should look and move.
4. Building a page? Start from its screen: `components/Screen<Name>.md` (route, content, states, transitions) and `previews/Screen<Name>.html`.

## Hard rules

- **Tokens only.** CSS variables from `tokens.css`; `ReturnColors` / `ReturnSpatial` / `ReturnMotion` / `ReturnType` in Unity. No raw hex, spacing or durations that have a token.
- **Two themes.** `data-theme="day"` (default) and `"dusk"`. Every screen must work in both; test both.
- **Imagery is the brand.** Heroes and section backgrounds use `imagery/web/*.webp` inside `HeroFrame` (rounded `radius-frame` window on `canvas`). Never stock photos, 3D renders or gradients as a substitute. New imagery follows the recipe in `BRAND.md`.
- **Readable on any sky.** Text directly on imagery is `on-image` over `image-scrim` (24px and up) or `image-scrim-strong` (smaller). Everything else on imagery goes on glass (`glass`, `glass-edge`, `glass-blur`, text `on-glass`) or `glass-strong` panels (text `ink`). Never put white text on day glass.
- **Color jobs are fixed.** `action`: one primary per view on plain surfaces; `light` button: the primary on imagery. `aurora`: people only. `blossom`: new/anniversary. `sun`: developing. `sky`: links and selection.
- **Status is never color alone**: StatusTag, or icon + word.
- **Type.** Role Model (`--font-display`) for headlines and room names; the one feeling word per headline goes in `<em>`, which renders in Cormorant Light Italic (never a faked italic). Rusilla Serif (`--font-caps`, class `kicker`) only for short all-caps kickers, 18px and up. Hanken Grotesk for all UI. Role Model's demo has no punctuation, so keep headlines to words. In VR: `vr-*` sizes, 14dp minimum, no italics, no Rusilla.
- **Shape.** Everything interactive is a pill. Cards `radius-lg`, frames and VR panels `radius-frame`.
- **Focus.** 2px `focus` ring offset 2px on plain surfaces; `on-image` ring with a dark halo on imagery (already in `bundle.css`).
- **Copy.** Lowercase "return", sentence case, no exclamation marks, no emoji. The shared thing is always a "room" (never memory, space or project). Moments and places, not files and models.
- **Auth is Clerk.** Use Clerk's SignIn/SignUp with `clerk/appearance.ts`; don't build custom auth screens.

## Making it interactive (the feel to aim for)

The references are slow, luminous, dreamlike. Motion should feel like weather, not UI.

- **Drift:** hero imagery breathes on `duration-drift` (60s) with `ease-in-out` (`rt-drift` keyframes). Layered parallax is welcome: split an image into sky and foreground layers and move them at different rates on scroll, max ~40px.
- **Pointer parallax:** `HeroFrame` sets `--rt-px` / `--rt-py` (-0.5 to 0.5) from the pointer; image moves at most 14px. Reuse the same variables for cursor-reactive light (a soft radial highlight that follows the pointer).
- **Mist clearing:** text and media enter with `rt-reveal` (blur 14px → 0, fade, 12px rise, `duration-reveal`, `ease-out`), staggered 180ms. Trigger on scroll with an IntersectionObserver at 20% visibility, once.
- **Coming into focus:** anything generated resolves from white fog: `DevelopProgress` drives blur/saturation from `progress`. Use the same effect when a room image first loads.
- **Stepping in (web):** opening a ready RoomCard blooms white from the card (`scale` + white radial, `duration-base`), then fades the page through white (day) or deep blue (dusk) over `duration-enter` into the room view. Use the View Transitions API where available, a full-screen overlay otherwise. Never a hard cut.
- **Day to dusk:** switch `data-theme` to dusk for the VR hub, night hours (after local sunset is fine to approximate as 7pm to 6am), and whenever someone else is in the room with you. Crossfade the hero image and tokens over `duration-reveal`.
- **Hover:** `halo` glow and 1 to 4px lift. Nothing bounces, spins (except loaders) or shakes.
- **Performance:** animate only `transform`, `opacity` and `filter`; use `will-change` sparingly; lazy-load imagery below the fold; serve WebP with the JPEG fallback.
- **Reduced motion:** `prefers-reduced-motion` disables drift, parallax, reveals and bloom (already handled in `bundle.css`); keep short linear fades.

## Room flow logic

- Status drives routing: invited → join → add photos (screen 5) → waiting (6) → building (6, DevelopProgress) → ready (7).
- Building starts automatically when every member's status is done; the owner can start early from screen 6 (confirm first).
- Keep MemberList live (poll every few seconds or subscribe) on screens 5 and 6.
- Email invitees on invite; email everyone when the room is ready.

## Porting components

`components/bundle.js` is a plain script (React from `window`). When porting to ES modules keep the markup, `rt-` class names, ARIA attributes and prop names from `index.d.ts`, and import `bundle.css` as is. Don't restyle in place: change `bundle.css` and the component's `.md` together.

## Adding to the system

A new component gets `components/<Name>.md` (first sentence = its purpose, then props, then do and don't) and a preview in `previews/`. A new color gets a token for both themes in `tokens.json` with a usage note naming where it's used and which surfaces it reads on; check contrast in both themes before adding it.
