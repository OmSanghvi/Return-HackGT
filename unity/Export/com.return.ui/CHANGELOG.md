# Changelog

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
