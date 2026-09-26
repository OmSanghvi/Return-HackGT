# Changelog

## 0.2.0
- **VR hub** (`HubApp`): dusk painted sky and star dome, your rooms as arched portals on a ring, portal states (ready, building, waiting, add photos, invited), glass panels for sign-in and room screens, wrist menu, fade in and out of worlds.
- **World loading seam**: `IWorldLoader`, `SceneWorldLoader` (roomId to scene map, additive), `StubWorldLoader`, `WorldSession`, `ScreenFade`.
- **XR glue inside the package** (`Runtime/XR`, `Editor/XR`): compiles only when `com.unity.xr.interaction.toolkit` 3.0+ is installed. Adds tracked-device raycasters to every panel and interactables to every portal. Menus: `Return > Import XRI Samples`, `Return > Build VR Hub Scene`.
- New hub sky (`SceneKey.Hub`), AI-generated (see THIRD-PARTY.md).
- The hub does not create rooms or start new ones: that happens in the web app.
- Fixes: a destroyed hub no longer clears a newer hub's forced theme.

## 0.1.0
- Design tokens, Day/Dusk themes, components, six flat screens, fake `RoomStore`, EditMode and PlayMode tests.
