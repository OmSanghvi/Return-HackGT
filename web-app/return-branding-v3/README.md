# return: branding and design system (v3)

Everything needed to build return's web app and VR UI as one product: the room flow's seven screens, painted-sky imagery, glass UI, a tall serif voice, day and dusk themes. Drop this folder into the repo as `design-system/`.

Open `previews/index.html` to see the screens and every component live, straight from disk.

## What's here

| Path | What it is | Who uses it |
| --- | --- | --- |
| `BRAND.md` | Brand book: name, voice, imagery, color, type, shape, motion, the screen flow, VR, logo | Everyone. Read first. |
| `AGENTS.md` | Rules, room-flow logic and interaction recipes for coding agents | Claude Code, Cursor, Codex |
| `components/Screen*.md` | The seven screens: route, content, states, what each button does | Whoever builds pages |
| `screens/*.jpg` | Full-size images of the seven screens, numbered in flow order | Reference, Devpost |
| `clerk/appearance.ts` | Clerk `appearance` (variables + element hooks) for day and dusk | Sign-in / sign-up |
| `tokens.json` | Source of truth: every token for both themes, with a usage note on each | Tools |
| `tokens.css` | CSS variables for `day` (default) and `dusk`, `@font-face`, a class per type style | Web |
| `unity/ReturnTokens.cs` | Colors for both themes, motion, spatial measurements, VR type sizes | Unity |
| `components/bundle.js` + `bundle.css` | 18 React 18 components (`window.Return`) and their styles, built only on tokens | Reference implementation |
| `components/index.d.ts`, `components/<Name>.md` | Props and guidelines per component, Unity specs for the VR ones | Everyone |
| `imagery/web/`, `imagery/original/` | The 8 painted environments: 2048×1152 WebP + JPEG, and full-quality PNGs | Web, Unity |
| `fonts/` | Role Model (display), Rusilla Serif (kicker), Cormorant (italic accent + fallback), Hanken Grotesk (UI), with license notes; OTF sources for Unity | Web; Unity via TextMesh Pro |
| `logos/` | Lockup, mark, wordmark in ink and white (SVG), plus app icons, favicons, brand covers | Web, Quest store, Devpost |
| `previews/` | A live page per screen and component, and a gallery | Everyone |

## The flow

1. Landing `/` → 2. Sign in `/sign-in` (Clerk) → 3. Dashboard `/rooms` → 4. Create a room + invite by email `/rooms/new` → 5. Add photos and a note `/rooms/:id/add` → 6. Waiting for everyone `/rooms/:id` (building starts when everyone is in) → 7. Ready `/rooms/:id` (VR only) → back to 3. Invited people join from the dashboard straight into 5.

## Web setup

```html
<html data-theme="day">
<link rel="stylesheet" href="/design-system/tokens.css">
<link rel="stylesheet" href="/design-system/components/bundle.css">
```

`tokens.css` loads fonts from `./fonts/`, so keep them together. Wrap any subtree in `data-theme="dusk"` to switch it. For Clerk: `import { returnAppearance } from './design-system/clerk/appearance'` and pass `appearance={returnAppearance('day')}` to `ClerkProvider`.

In a Vite or Next app, port the components you need to ES modules and keep the `rt-` class names and `bundle.css` so everything stays identical. `bundle.js` is the reference.

## Unity setup

1. Copy `unity/ReturnTokens.cs` into `Assets/Scripts/Design/`. Use `ReturnColors.Get(theme)`, `ReturnMotion`, `ReturnSpatial`, `ReturnType`.
2. Make TextMesh Pro font assets from Hanken Grotesk (all VR text) and `fonts/source/RoleModel-Regular.otf` (room names and panel titles 32dp and up), with Cormorant as Role Model's fallback for punctuation. No italics or Rusilla in-headset.
3. The headset signs in with the same Clerk account and lists ready rooms as RoomPortals in a dusk hub (`imagery/original/return-sky-dusk-night-lake.png` sets the mood).

## Font licensing

Role Model and Rusilla Serif are personal-use demo fonts: fine for the hackathon, not for a paid product. See `fonts/README.md` for where to license them, or swap both for Cormorant (SIL OFL) by changing `--font-display` and `--font-caps` in `tokens.json`.

## Changing a token

Edit `tokens.json`, then update `tokens.css` and `unity/ReturnTokens.cs` to match. Keep text at 4.5:1 (3:1 for 24px and up) on the surfaces its note names, in both themes.
