# SpatialPanel

The VR panel: frosted glass floating in the sky with a Role Model title, body and pill actions. In the preview 1px = 1dp at panel scale.

Props: `eyebrow`, `title`, `children`, `actions`, `width` (dp, default 640).

Unity spec:
- `panel-size` 1024×640dp default, 384×500dp minimum. At `panel-distance-ray` (1.2m; 0.8m to 3m) for ray or pinch; `panel-distance-touch` (0.44m) for poke.
- Fill `glass-strong` over a pre-blurred skybox layer, `radius-frame` corners, 1px `glass-edge`. Padding `space-5`/`space-6`.
- Title `vr-display` (Role Model, with Cormorant as the TMP fallback for punctuation), body `vr-body`, eyebrow `vr-caption`.
- Buttons are 48dp pills, 12mm apart; hover adds `halo`; poke travel 7mm with a soft click.
