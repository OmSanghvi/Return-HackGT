# Third-party material and provenance

## Fonts (`Runtime/Resources/ReturnUI/Fonts`)
- **Role Model** and **Rusilla Serif**: demo, personal-use fonts. Buy commercial licenses (or swap them out) before shipping a commercial product. Licenses are next to the fonts.
- **Bemirs** (`Bemirs-Regular.otf`, `LICENSE-Bemirs.txt`): demo, personal-use font by Nirmana Visual, copied verbatim from the web-app's `design-system/fonts` (same source as Role Model). Caps-only, no digits, so `FontFace.Display` falls back to Role Model for numerals, then Cormorant for punctuation (see `UIAssets.EnsureFonts`). Buy a commercial license from nirmanavisual.com or swap the face before any commercial launch. Run **Return > Build Font Assets** once to generate `Bemirs-Regular SDF.asset`.
- **Cormorant** and **Hanken Grotesk**: SIL Open Font License. Converted from woff2 to TTF and cut to static weights.

## Art
- **Painted skies** (`Skies`, `Depth`, except the hub sky): from the Return brand kit in the web-app. Depth maps generated with Depth Anything V2 Small.
- **Hub sky** (`return-sky-dusk-hub.jpg`): AI-generated on 2026-09-26 with Higgsfield (model `z_image`). The prompt asked for a hand-painted anime landscape "in the manner of Studio Ghibli background art", and the result resembles that studio's backgrounds closely. **Treat it as placeholder art for demos.** Replace it with licensed or commissioned art before any commercial release. To swap it, overwrite `return-sky-dusk-hub.jpg` and `return-sky-dusk-hub.png` (depth map, linear, any size) keeping the names. Also confirm the generator's commercial terms for your plan.
- **Icons and logos**: rasterized from the web-app's SVGs.

## Audio (`Runtime/Resources/ReturnUI/Audio`)
All clips are CC0 1.0 (public domain) or generated in-house; no attribution is legally required, credited here anyway.

- **ui_hover.ogg** (0.24s): from `rollover1.wav`, Kenney "UI Audio" pack (kenney.nl/assets/ui-audio). Author: Kenney (kenney.nl). License: CC0 1.0. Source mirror: https://github.com/Calinou/kenney-ui-audio
- **ui_select.ogg** (0.29s): from `confirmation_001.wav`, Kenney "Interface Sounds" pack (kenney.nl/assets/interface-sounds). Author: Kenney (kenney.nl). License: CC0 1.0. Source mirror: https://github.com/Calinou/kenney-interface-sounds
- **chime.ogg** (0.13s): from `bong_001.wav`, Kenney "Interface Sounds" pack. Author: Kenney (kenney.nl). License: CC0 1.0. Source mirror: https://github.com/Calinou/kenney-interface-sounds
- **ripple.ogg** (0.13s): from `drop_001.wav`, Kenney "Interface Sounds" pack. Author: Kenney (kenney.nl). License: CC0 1.0. Source mirror: https://github.com/Calinou/kenney-interface-sounds
- **lantern_bump.ogg** (0.07s): from `back_001.wav`, Kenney "Interface Sounds" pack. Author: Kenney (kenney.nl). License: CC0 1.0. Source mirror: https://github.com/Calinou/kenney-interface-sounds
- **ambience_hub.ogg** (42.8s): looped/crossfaded from "Crickets Ambient Noise - loopable" (`crickets_1.mp3`, original 11.45s). Author: Wolfgang_ (additional attribution noted: Ted Kerr). License: CC0. Source: https://opengameart.org/content/crickets-ambient-noise-loopable
- **portal_hum.ogg** (4.0s), **greeting_swell.ogg** (3.0s), **whoosh_in.ogg** (1.4s), **whoosh_out.ogg** (1.4s): generated in-house with ffmpeg lavfi sine/noise synthesis (no external source), 2026-09-26. Treat as placeholder-quality; swap for sourced/composed audio before any commercial release.

All clips converted/mixed to Ogg Vorbis at 44.1kHz with ffmpeg. Total folder size ~1.24MB.

## Unity packages (not bundled)
This package depends on `com.unity.ugui`, `com.unity.inputsystem` and URP. The XR files activate only if `com.unity.xr.interaction.toolkit` is installed. The XR Interaction Toolkit sample rig used by `Return > Build VR Hub Scene` is imported from Unity's package samples, not shipped here.

## Code
The package code has no license file yet. Add one before distributing it outside your team.
