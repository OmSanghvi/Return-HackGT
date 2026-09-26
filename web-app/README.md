# return web app

Immersive frontend demo of the room flow: landing, sign in, rooms, create and invite, add photos, waiting, building, ready.
Pure frontend for now: rooms live in localStorage and a simulator plays the other people.

```bash
npm install
npm run dev        # http://localhost:5173
npm test           # store logic
npm run build
```

- **Demo controls:** `/?reset` restores the seeded rooms. Rooms only move when you act: on any `/rooms/:id` page press `.` to bring the next person in. When everyone is in (or you press Start without X) the build plays on its own over about 7 seconds while the page is open.
- **Theme:** always dusk. The sky paintings carry the light; stars and fireflies appear over the dusk scenes (night lake, cloud sea).
- **Auth:** local only. Sign-in always logs in as `ME` from `src/data/store.ts`.
- **The sky:** `src/world/` is one WebGL canvas behind every page. `Stage` marks where the painted window goes; the shader parallaxes each painting using the depth maps in `src/assets/depth/` (regenerate with `npm i --no-save @huggingface/transformers && npm run depth`). No WebGL or reduced motion falls back to plain drifting images.
- **Design system:** `src/design-system/` is copied from `return-branding-v3/`; `src/ui/` is a TSX port of its components.
