# Return UI

The Return web-app UI, ported to Unity as a self-contained package for **Quest VR world-space panels** (UGUI + TextMeshPro, URP).
Everything lives in this folder, so it moves to another Unity project by copying it (or referencing it by git URL).

## Install in another project
1. **Tarball:** Package Manager > + > Add package from tarball > `com.return.ui-0.2.0.tgz`. **Folder:** copy `com.return.ui` into the project's `Packages/` folder (or add it from disk or a git URL).
2. Requires URP, `com.unity.ugui` and the Input System (all pulled in by `package.json`; set **Active Input Handling** to *Input System* or *Both*).
3. Open any scene, then either:
   - add the **ReturnApp** component to an empty GameObject, or
   - import the **Demo scenes** sample (Package Manager > Return UI > Samples) and open `ReturnDemo`.
4. First import brings in TextMeshPro Essentials automatically. If it does not, run **Return > Import TMP Essentials**.

`ReturnApp` needs a camera (it uses `Camera.main`). It builds the sky backdrop, the main panel, the router, a hand menu and the demo simulator. No XR SDK is required; for a headset add your rig's ray/poke input (for example a `TrackedDeviceGraphicRaycaster` on the panel canvas) and it drives the same `EventSystem` clicks.

## What is in it
| Area | Path | Notes |
|---|---|---|
| Tokens | `Runtime/Design/ReturnTokens.cs` | Generated from `tokens.json` in the web-app. Do not edit by hand. |
| Themes | `ThemeManager`, `ThemedGraphic` | Day/Dusk (Dusk 19:00 to 06:00, override with `SetOverride`, `SetForced` for the Ready screen). Every color is a token role. |
| Components | `Runtime/Components` | Button, Field, StatusTag, Avatar, PresenceStack, GlassNav, Stepper, Bar, Sheet, RoomCard, MemberList, DevelopProgress, PhotoDrop, InviteSearch, ShareSheet, HeroFrame, HandMenu, Nameplate, PortalWindow, RoomPortal (3D), SpatialPanel, SkyBackdrop |
| Screens | `Runtime/Screens` | Landing, SignIn, Dashboard, CreateRoom, RoomUpload, Room (waiting, building, ready) |
| Data | `Runtime/Data` | `IRoomStore` seam, `RoomStore` (JSON on disk), `RoomLogic` (rules and the demo simulator). Port of `store.ts`. |
| Nav | `Runtime/Nav/ScreenRouter.cs` | Route + auth guard + fade. Replaces react-router. |
| Shaders | `Runtime/Shaders/SkyParallax.shader` | Depth-map parallax and mist. Port of the web WebGL shader. |
| Assets | `Runtime/Resources/ReturnUI` | Fonts, skies, depth maps, icons, logos. Loaded through `UIAssets`. |

Units: 1 canvas unit = 1 dp = 1 mm (`SpatialPanel.MetersPerDp = 0.001`). Type sizes follow `ReturnType` (18 dp reading floor, 14 dp minimum). Hit targets are at least 48 dp.

## Use the components
Everything is built in code so it themes and moves with no prefab wiring:
```csharp
var panel = SpatialPanel.Create("Panel", 1024, 640);
var col = UI.V(panel.rect, "Col", 16, UI.Pad(32));
UI.Text(col, "Start a " + UI.Em("room"), TextStyle.DisplayM);
var name = RField.Create(col, "Name this room", "The lake house");
RButton.Create(col, "Next", BtnVariant.Primary, BtnSize.Lg, arrow: true, onClick: () => Debug.Log(name.Text));
```
`Return > Build Demo Scenes` regenerates the sample scenes. Open `ReturnGallery` to see every component in Day and Dusk.

## Replace the fake backend
The UI only talks to `IRoomStore`. Implement it against your API and pass it in place of `RoomStore` in `ReturnApp.Bootstrap`. The simulator (`FastForward`, the `.` key, the hand menu button) is demo-only; turn it off with `demoSimulator = false`.

## Known limits
- **Photo picker is a stub.** There is no native file picker on Quest, so "Choose photos" returns sample images (`PhotoLibrary.Pick`). Swap it for an Android gallery picker.
- **Glass is a translucent panel, not a blur.** A backdrop blur is costly on Quest. The `Glass` tokens and edge highlight give the look.
- **Pipeline names are labels.** The building screen's four steps do not reflect a live model (see `hardcode.MD` in the web-app).
- **Fonts.** Role Model and Rusilla Serif are demo, personal-use fonts. Buy licenses before shipping commercially, or swap in Cormorant (SIL OFL).
- **Landing steps with buttons** instead of scrolling; the web version scrolls through the chapters.
- Variable fonts were cut into static weights (Cormorant Light Italic and Regular, Hanken Grotesk 400/500/600).

## Tests
`Tests/Editor` (EditMode, port of `store.test.ts` plus persistence) and `Tests/Runtime` (PlayMode: clicks through the whole flow). Add `"testables": ["com.return.ui"]` to the host `manifest.json` to run them from the Test Runner.

## VR hub (headset frontend)
`HubApp` is the Quest-facing app: a dusk painted sky and your worlds as arched portals on a ring. Worlds-only: the ring shows just the rooms the signed-in account is already in (joined or done) and that are ready to enter; inviting, accepting, uploading photos and building progress all happen on the web app, not here. Before sign-in, a glass account picker (two demo accounts) stands in for auth; picking one calls `RoomStore.SignIn(accountId)`. Each portal's label shows the room's title and the first names of everyone in it. The wrist menu is just Hub and Recenter. Pinching a portal fades out (white-out for day paintings, deep blue for dusk), loads the world through `IWorldLoader`, and fades in; the wrist menu's Hub button fades back to the ring.

- **Worlds:** implement `IWorldLoader` (scene, splat or download). `SceneWorldLoader` maps `roomId -> sceneName` (set `HubApp.worldMap`; scenes must be in Build Settings); unmapped rooms load `StubWorldLoader`, a placeholder panorama so the loop is demonstrable.
- **Rig:** `HubApp` only needs a `head` transform and optionally `leftHand`. The XR glue lives in the project (`Assets/ReturnVR`): it adds tracked-device UI raycasters to every `SpatialPanel` and an `XRSimpleInteractable` to every `RoomPortal` through the `SpatialPanel.Created` and `RoomPortal.Created` events.
- **Scene:** `Return > Build VR Hub Scene` (in `Assets/ReturnVR/Editor`) builds `Assets/Scenes/ReturnHub.unity` from the XR Interaction Toolkit hands and controllers rig plus the XR Device Simulator (editor only).
- **Hooks for later work** (greeting animation, step-through transitions, audio, haptics): `HubController.SignedIn` (display name), `HubController.PortalsLaidOut` (ring order), `HubController.EnteringRoom`, and the single `EnterRoom(Room, RoomPortal)` entry point that fires it.

## Headset quick start (any project)
1. Requirements: Unity 6, URP, uGUI, Input System. For VR also install **XR Interaction Toolkit 3+**, **XR Hands** and **OpenXR** (Package Manager).
2. `Return > Import XRI Samples` (imports Starter Assets, Hands Interaction Demo and the Device Simulator from the toolkit).
3. `Return > Build VR Hub Scene` builds `Assets/Scenes/ReturnHub.unity` and puts it first in Build Settings.
4. Press Play. The XR Device Simulator lets you look and click without a headset. For a Quest build you also need the Android Build Support module and OpenXR with the Meta Quest feature group enabled.
5. Worlds: fill `HubApp.worldMap` (room id to scene name, scenes in Build Settings) or implement `IWorldLoader`. Unmapped rooms open a stub world.
6. Swap the hub sky: replace `return-sky-dusk-hub.jpg` and `return-sky-dusk-hub.png` under `Runtime/Resources/ReturnUI` (see THIRD-PARTY.md).

Rooms come from `IRoomStore`; the shipped `RoomStore` is fake demo data. The hub shows rooms but does not create them (that is the web app's job).
