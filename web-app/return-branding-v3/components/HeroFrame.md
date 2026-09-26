# HeroFrame

The signature surface: painted imagery in a rounded window with a floating nav, an eyebrow, a kicker, a Role Model headline, subcopy and pill actions. It drifts slowly and shifts with the pointer.

Props: `image` (an Imagery URL), `nav`, `eyebrow` (use `Eyebrow`: `badge` + children), `kicker` (a short all-caps line above the title, in Rusilla Serif), `title` (wrap the one emotional word in `em`), `subtitle`, `actions`, `footer`, `align` (`center` | `bottom-left`), `height` (min-height, default 520), `bleed` (no frame radius), `drift` (default true), `parallax` (default true), `label`, plus `children` after the actions.

- Center alignment for the landing hero; bottom-left for section heroes and room pages, like the Rainmaker and Polaris references.
- Scrims are built in: a soft center scrim (or bottom gradient) keeps on-image text readable. Pick imagery whose headline area is sky or haze, not busy detail.
- On the page, inset the frame from the viewport with `space-5` (mobile) to `space-6` and sit it on `canvas`.
- The title resolves out of blur on load (`rt-reveal`); stagger follows eyebrow → title → subtitle → actions. Motion respects `prefers-reduced-motion`.
- Wrap it in `data-theme="dusk"` for dusk heroes; use the cloud-sea or night-lake imagery there.
