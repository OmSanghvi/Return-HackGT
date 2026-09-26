# return: brand book

return turns photos of a shared moment into a world you can stand inside again, in VR, with the people who were there. Someone starts a **room** for a place, invites the others by email, everyone adds their photos and a note, and once everyone's in, return builds the room and it appears in each person's headset. The brand is ethereal: painted skies, soft light, glass floating over imagery, a tall serif voice. It should feel like the edge of a dream you're trying to hold on to. Calm, luminous, a little nostalgic. Never sci-fi, never neon, never cute.

## Name

- Always lowercase: **return**, including at the start of a sentence in UI. In prose where that reads as a typo, rephrase.
- The name is also the verb. Use it on purpose, once per screen: "Who can return here", "Ready to return".
- The shared thing is a **room**, everywhere: "Start a room", "Your rooms", "Invite people to this room", "Leave room". Never "memory", "space" or "project" in UI copy.

## Voice

- Talk about moments, places and people, not files, models or scenes. "Walk back into the moments you miss", not "Generate 3D environments from images". The product noun is "room"; the feeling is still moments and places.
- Short, quiet sentences. Sentence case. No exclamation marks, no emoji, no hype words.
- One italic word per headline carries the feeling: "Walk back into the *moments* you miss", "Some places only exist *in you*". Never italicize a whole line.
- Be honest about the AI: say what it's doing in plain words ("Estimating depth", "Building the world") and what makes it better ("More angles build a fuller world"). Never claim the world is exactly how it was.
- Rooms can hold tender moments. Empty states invite, errors explain and offer the fix ("We need at least one photo with clear ground in it"), nothing jokes about what's in a room.

## Imagery: the brand is the sky

- Every hero, landing section and VR hub is full-bleed painted imagery from `imagery/`: soft cumulus skies, meadows, still water, a lone small figure seen from behind. Day scenes for the default theme; the cloud sea and night lake for dusk.
- Frame it: on web, imagery sits in a `radius-frame` window inset `space-5` (mobile) to `space-6` from the viewport edge on `canvas`, like the reference sites. Full bleed (`HeroFrame bleed`) only for the in-app viewer.
- The imagery moves, slowly: a 60s drift loop (`duration-drift`), a few pixels of pointer parallax on heroes, and text that resolves out of blur on first view (`rt-reveal`). Nothing snaps, bounces or spins except loading spinners.
- New imagery follows the same recipe: *hand-painted matte painting, soft brushwork, towering cumulus, pastel or golden light, open sky in the upper center, no text, people only as a tiny figure from behind.* Keep one style; never mix in photography or 3D renders.
- Users' rooms are the exception: their own generated worlds show as they are, inside RoomCard, DevelopProgress and RoomPortal.

## Color

Two themes. **Day** (default): warm cloud-white canvas, frosted light glass, ink text. **Dusk**: deep night blue, smoked glass, white text. Switch with `data-theme` on any element; use dusk for the VR hub, night viewing, and moments where people are together in a room.

- Grounds: `canvas` around framed imagery; `surface-100` for plain pages; `surface-200` for cards and sheets; `surface-300` for hover and selection.
- Text on plain surfaces: `ink`, `ink-muted` for metadata, `ink-faint` only for placeholders. All pass 4.5:1 on every surface in both themes.
- **On imagery:** text directly on an image is `on-image` (white) and must sit on `image-scrim` (text 24px and up) or `image-scrim-strong` (smaller text). Everything else on imagery goes on **glass**: `glass` + `glass-edge` + `glass-blur`, text in `on-glass`. Day glass is light frosted with ink text; dusk glass is smoked with white text, so glass stays readable on any sky. Frosted panels holding real content use `glass-strong` with ink text.
- Primary action: `action` fill with `on-action` label on plain surfaces; on imagery the primary is the white **light** pill (`Button variant="light"`). One primary per view.
- Accents are rare and each has one job: `sky` for links and selection, `aurora` for other people and presence only, `blossom` for invitations and "new", `sun` for a room that's building. Each has a `-soft` ground for chips.
- Status: `success` ready, `danger` failed or destructive, always with an icon and a word.
- Focus: 2px solid `focus`, offset 2px, on plain surfaces; on imagery a 2px `on-image` ring with a dark halo. Both are in `bundle.css`.
- Never: neon, saturated gradients as decoration, purple-to-blue "AI" glows, pure black.

## Type

- **Role Model** is the voice: soft, airy, high-contrast with rounded terminals, like handwriting set in type. `hero` (104px, clamp down to 52px), `display-l`, `display-m`, `title`, and `room-title` for the names people give their rooms.
- **Cormorant Light Italic** (`accent-italic`) is the one feeling word in a headline, wrapped in `<em>`: "Walk back into the *moments* you miss". Role Model has no italic; never let the browser fake one (`font-synthesis: none` is set on display text).
- **Rusilla Serif** (`kicker`) is an all-caps titling face for short kickers above headlines ("Welcome back, Dylan", "Lake Norman, summer 2019"). Its word-initial capitals are larger by design. 18px minimum, over a scrim on imagery, never for sentences, buttons or VR.
- **Hanken Grotesk** for everything functional: `body-l`, `body`, `label` (buttons, nav), `caption`, `overline` (tiny uppercase badges only).
- Headlines are short and balanced (`text-wrap: balance`). Role Model's demo has letters and numbers only: periods, commas, apostrophes and question marks fall back to Cormorant automatically, so write headlines as words ("Walk back into the moments you miss"). Never all caps in Role Model.
- In VR: Hanken Grotesk `vr-h1`, `vr-h2`, `vr-body`, `vr-caption` in dp at panel scale, 18dp reading floor, 14dp minimum. Role Model only as `vr-display` for room names and panel titles 32dp and up, with Cormorant as the TextMesh Pro fallback for punctuation. No italics and no Rusilla in-headset.
- Web demo hero titles use Bemirs (caps only, personal-use demo license, digits fall back to Role Model); everything else follows the scale above.
- **Licensing:** Role Model and Rusilla Serif are personal-use demo fonts (Role Model: free for personal and non-profit use; Rusilla: personal use only). Fine for the hackathon demo; buy commercial licenses (Role Model from its designer, Rusilla from Dealita Studio) before return makes money, or swap them for Cormorant, which is SIL OFL. Cormorant and Hanken Grotesk are free for any use.

## Shape, space and depth

- Everything interactive is a pill (`radius-pill`): buttons, inputs, nav, chips, avatars. Pill buttons can carry a round arrow "dot" at the end for forward motion (`arrow`).
- Containers are soft: cards and sheets `radius-lg`, hero frames and VR panels `radius-frame`, thumbnails `radius-sm`. RoomPortals are arched windows.
- Spacing steps `space-1` 4 through `space-8` 80. Hero content insets `space-7`; sections breathe with `space-8`.
- Depth is light, not lines: `shadow-float` for floating sheets, `shadow-soft` at rest, `halo` (a soft white glow) for hover and gaze. `glow-aurora` marks a person who is here now.

## Motion

- Everything arrives slowly with `ease-out` (a long, floaty settle). `duration-fast` for hover and press, `duration-base` for sheets and chips.
- **Mist clearing** is the signature: text and images resolve from blur to sharp (`rt-reveal`, `duration-reveal`), and a room being built clears from white fog into focus (`DevelopProgress`, `duration-develop`).
- **Drift**: hero imagery breathes on a 60s loop and shifts a few pixels with the pointer. Keep parallax under 14px.
- **Stepping in** (web and VR): the portal blooms with white light and the view fades through white (day) or deep blue (dusk) over `duration-enter`. Never a hard cut.
- `prefers-reduced-motion` turns off drift, parallax and reveals; fades stay short and linear.

## VR

- The hub is a dusk sky: portals (arched windows onto each ready room) float on an arc `portal-ring-radius` from the viewer at eye height. Inside a room there is no UI except the HandMenu and nameplates.
- Panels at `panel-distance-ray` (1.2m; 0.8m to 3m) for pinch or ray; `panel-distance-touch` (0.44m) only for poke UI. Default `panel-size` 1024×640dp.
- Targets at least `target-min` (48dp), `target-gap` (12mm) apart, poke travel `press-depth` (7mm). Hover and gaze show `halo`.
- Glass in VR: approximate backdrop blur with a pre-blurred copy of the skybox behind panels; keep panel fill at the `glass-strong` values.
- These numbers follow Meta's Horizon OS guidance for Quest; test on the headset.

## Iconography

- Use the Icon component: line icons on a 24px grid, 1.5 stroke, round caps, `currentColor`. 14px in chips, 16 to 18px in buttons, 24px in VR.
- A missing glyph is drawn on the same grid and stroke; Lucide at 1.5 stroke is the closest stand-in. No emoji, no filled icons (except play).

## Logo

- The mark is a sun on the horizon with its reflection on still water: a moment coming back. The wordmark is "return" in Instrument Serif italic, outlined. It stays in that open-licensed face on purpose: the display fonts are personal-use demos, and a logo needs a font you can use commercially.
- Use `return-lockup-ink.svg` on canvas, plain surfaces and day glass; `return-lockup-white.svg` on dusk glass and directly on scrimmed imagery. The marks alone for favicons, the Quest app tile and small spaces.
- Minimum size: 20px tall for the mark, 24px for the lockup. Clear space: the sun's radius on every side. Don't recolor, add effects or set the name in another face.

## Screens and flow

Seven screens, in the order people move through them (each has a live page in `previews/` and a spec in `components/Screen*.md`):

1. **Landing** `/`: framed hero, Start a room.
2. **Sign in** `/sign-in`: Clerk's SignIn/SignUp, themed with return's appearance settings over the cloud imagery.
3. **Dashboard** `/rooms`: invitations to join, your rooms with their status, manage menu, Create a room.
4. **Create a room** `/rooms/new`: name it and invite people by email (step 1 of 3).
5. **Add photos and a note** `/rooms/:id/add`: PhotoDrop, a note, who's in the room (step 2).
6. **Waiting for everyone** `/rooms/:id`: live list of who has added photos; building starts automatically when everyone is in; the owner can start without someone (step 3).
7. **Ready** `/rooms/:id`: the room is built and waiting in everyone's headset (VR only), then back to the dashboard.

A room's status drives where it opens: invited → your photos needed (5) → waiting (6) → building (6, DevelopProgress) → ready (7).

## Components

Web: Button, Field, GlassNav, HeroFrame (with Eyebrow), StatusTag, RoomCard, Stepper, InviteSearch, PhotoDrop, MemberList, DevelopProgress, PresenceStack, ShareSheet, Icon. VR references: SpatialPanel, HandMenu, Nameplate, RoomPortal. All ship in `components/bundle.js` as `window.Return` (React 18) with styles in `components/bundle.css`, built only on the token variables. Authentication UI is Clerk's, themed to match; there is no pairing code: the headset signs in with the same account.
