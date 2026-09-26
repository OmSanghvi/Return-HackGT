# Changelog

## 0.4.0
- **Daylight hub**: the hub now opens on a light, dreamy daylight scene (meadow and lake) instead of painted dusk. Real skyboxes (graded CC0 Poly Haven skies, `Design/Skyboxes.cs`, `Return/SkyboxEquirect`) replace the static dome and panorama; fog, ambient light and glass blur take their color from the sky's horizon. Blossom petals and daytime birds in daylight; fireflies, lanterns and crickets stay for dusk.
- **Liquid glass UI**: `Return/LiquidGlass` (rounded SDF, rim, sheen, fake frosted blur from the sky) on every glass surface via `UI.Img`. Display type is Bemirs, matching the web app.
- **Portals**: head-driven parallax (lean in to see depth), a quiet spatial hum per portal that ducks while you are in a world, edges that blend into the sky horizon, and a soft glow that brightens on hover. Portal windows keep their paintings.
- **Hands and comfort**: soft light-beam pointer, fireflies gather at a still hand and scatter on a fast swing, smooth turn (75 deg/s) with the tunneling vignette, floor tracking, 72 Hz and fixed foveation on device.
- **Worlds**: arrival card ("Lake House, with Maya"), a small Hub portal behind you and hold B/Y (H in the editor) to go home, props under 0.5 m are grabbable with haptics and everything else is solid, plus runtime presence: ambient bed and reverb, contact shadows, dust, sway and flicker, and fog with a ground fade instead of a hard edge.
- **Perf**: Android defaults to the Medium quality tier, shorter shadows, late latching, ASTC textures, and a `Return > Bake World Lighting` menu for world scenes.
- **Fixes**: fireflies and motes no longer render as black squares on device (`Return/ParticleGlow` bakes the blend state instead of relying on stripped URP keywords).
- Meta XR Audio SDK was tried and removed: v85 does not compile on Unity 6000.6. Sounds use Unity's built-in 3D panning.

## 0.3.0
- **VR hub, worlds-only ring**: the ring now shows only rooms the signed-in account is joined to (or done with) and that are ready to enter. Inviting, accepting, adding photos and building progress moved to the web app; the hub no longer routes to those flat screens.
- **Account picker**: replaces sign-in in the headset. Two demo accounts (Dylan, Maya) with overlapping ready rooms; picking one calls `RoomStore.SignIn(accountId)`.
- **Portal labels**: title plus the first names of everyone in the room.
- **Wrist menu**: just Hub and Recenter now; Theme and Advance (the demo simulator) were flat-app-only concerns and are gone from the hub.
- **Hook points for later work**: `HubController.SignedIn`, `HubController.PortalsLaidOut`, `HubController.EnteringRoom` events, and a single `EnterRoom(Room, RoomPortal)` entry point for world entry.
- Removed `PortalKind`/`PortalPresentation` (every ring portal is ready by construction) and the hub's demo simulator (`HubApp.demoSimulator`, the "." fast-forward).
- Demo seed: 4 ready rooms with distinct skies for Dylan, 3 overlapping ready rooms for Maya; save file bumped to `return-demo-v2.json`.

## 0.2.0
- **VR hub** (`HubApp`): dusk painted sky and star dome, your rooms as arched portals on a ring, portal states (ready, building, waiting, add photos, invited), glass panels for sign-in and room screens, wrist menu, fade in and out of worlds.
- **World loading seam**: `IWorldLoader`, `SceneWorldLoader` (roomId to scene map, additive), `StubWorldLoader`, `WorldSession`, `ScreenFade`.
- **XR glue inside the package** (`Runtime/XR`, `Editor/XR`): compiles only when `com.unity.xr.interaction.toolkit` 3.0+ is installed. Adds tracked-device raycasters to every panel and interactables to every portal. Menus: `Return > Import XRI Samples`, `Return > Build VR Hub Scene`.
- New hub sky (`SceneKey.Hub`), AI-generated (see THIRD-PARTY.md).
- The hub does not create rooms or start new ones: that happens in the web app.
- Fixes: a destroyed hub no longer clears a newer hub's forced theme.

## 0.1.0
- Design tokens, Day/Dusk themes, components, six flat screens, fake `RoomStore`, EditMode and PlayMode tests.
