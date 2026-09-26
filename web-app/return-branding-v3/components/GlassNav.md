# GlassNav

The floating pill navigation that sits on top of hero imagery.

Props: `items` (`[{label, href, active, onClick}]`), `brand` (a logo node), `brandCenter` (splits items around the logo, Polaris-style), `cta` (usually a `light` or `primary` Button, size `sm`), `plain` (solid version for pages without imagery), `onMenu` (the menu button shown under 720px), `label`.

- Put it in `HeroFrame`'s `nav` slot so it floats `space-5` from the top of the frame.
- Brand: `return-lockup-ink.svg` on day glass, `return-lockup-white.svg` on dusk.
- Four items at most. The current page uses `active`, which sets `aria-current`.
- Under 720px the items collapse to the brand and a menu button; you provide the menu (a glass-strong sheet).
