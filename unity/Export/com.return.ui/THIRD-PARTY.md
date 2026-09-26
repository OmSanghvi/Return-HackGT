# Third-party material and provenance

## Fonts (`Runtime/Resources/ReturnUI/Fonts`)
- **Role Model** and **Rusilla Serif**: demo, personal-use fonts. Buy commercial licenses (or swap them out) before shipping a commercial product. Licenses are next to the fonts.
- **Cormorant** and **Hanken Grotesk**: SIL Open Font License. Converted from woff2 to TTF and cut to static weights.

## Art
- **Painted skies** (`Skies`, `Depth`, except the hub sky): from the Return brand kit in the web-app. Depth maps generated with Depth Anything V2 Small.
- **Hub sky** (`return-sky-dusk-hub.jpg`): AI-generated on 2026-09-26 with Higgsfield (model `z_image`). The prompt asked for a hand-painted anime landscape "in the manner of Studio Ghibli background art", and the result resembles that studio's backgrounds closely. **Treat it as placeholder art for demos.** Replace it with licensed or commissioned art before any commercial release. To swap it, overwrite `return-sky-dusk-hub.jpg` and `return-sky-dusk-hub.png` (depth map, linear, any size) keeping the names. Also confirm the generator's commercial terms for your plan.
- **Icons and logos**: rasterized from the web-app's SVGs.

## Unity packages (not bundled)
This package depends on `com.unity.ugui`, `com.unity.inputsystem` and URP. The XR files activate only if `com.unity.xr.interaction.toolkit` is installed. The XR Interaction Toolkit sample rig used by `Return > Build VR Hub Scene` is imported from Unity's package samples, not shipped here.

## Code
The package code has no license file yet. Add one before distributing it outside your team.
