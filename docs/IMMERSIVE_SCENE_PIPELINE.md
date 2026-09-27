# Immersive scene pipeline — contract (2026-09-26)

One uploaded photo becomes a room you stand inside on Quest:

1. **GPU (EC2 g6e, L40S)**: every object is cut out (SAM 3.1) and reconstructed
   in full 3D (Fast-SAM3D) *with its real pose, position and size in the photo*,
   and the **whole photo** becomes a metric 3D Gaussian-splat scene (Apple SHARP),
   with metric depth, camera intrinsics, gravity and the support plane
   (MoGe-2 + plane fit), plus a vision-model scene analysis (lighting, mood,
   materials, room type).
2. **Backend** stores these beside each job/upload. Uploads with no typed names
   auto-detect *all* objects by default.
3. **Sync** (`scripts/sync_s3_assets_to_unity.py --project-id`) pulls object
   splats, poses, the scene splat and scene metadata into HackGTUnity and the
   catalog, and cuts the separately reconstructed objects out of the scene splat.
4. **NemoClaw (Muse Spark)** composes the room with tools: photo scene +
   objects laid out exactly as in the photo at real (player-relative) scale,
   HDRI sky and matching light, web images, ambient sound, particles, staging,
   then the Meta XR rig/grab/teleport tools. `compose_room` emits a *room spec*
   (JSON); the Unity Editor script **RoomKit** builds it.

Everything below is the shared contract between the parts. Change it only
together with every consumer.

## 0. Frames and units

- **Camera frame** ("opencv"): x right, y down, z forward, **metres**, origin at
  the photo camera's optical centre. MoGe(-2) pointmaps and SHARP splats use it.
- **Unity world**: x right, y up, z forward (left-handed), metres, floor at y = 0.
- **Rotations in the room spec** are Unity quaternions `[x, y, z, w]`.
- **Gsplat import map** `G`: how HackGTUnity's Gsplat importer maps a PLY's
  `(x, y, z)` to the imported asset's local coordinates. Recorded once as
  `GSPLAT_IMPORT_MAP` in `backend/scene_layout.py` (verified in the live Editor
  by the RoomKit work); all splat transforms are computed in Python against it,
  so C# just applies transforms.

## 1. GPU outputs

### 1a. Per object job: `artifacts/<job_id>/pose.json` (version 2)

```json
{
  "version": 2,
  "frame": "opencv",
  "image_size": [W, H],                 // of the full-resolution source photo
  "intrinsics": {"fx": 0, "fy": 0, "cx": 0, "cy": 0},
  "gravity_up_cam": [0, -1, 0],         // unit "up" in camera frame
  "support_plane": {"normal_cam": [..3], "offset": 0.0, "camera_height": 1.2,
                     "kind": "floor|surface"},
  "object": {
    "mask_bbox": [x0, y0, x1, y1],      // pixels in the source photo
    "mask_area_frac": 0.05,
    "centroid_cam": [x, y, z],          // robust centre of the masked 3D points
    "base_cam": [x, y, z],              // contact point on its support (lowest along gravity)
    "extent_m": {"width": 0, "height": 0, "depth": 0},  // gravity-aligned, visible surface
    "yaw_deg": 0.0,                      // facing about gravity, 0 = toward camera; may be null
    "splat_to_cam": {                    // VERIFIED similarity: object PLY coords -> camera frame
      "rotation_wxyz": [1, 0, 0, 0], "translation": [0, 0, 0], "scale": 1.0
    },                                   // null when not verified for this job
    "reprojection_iou": 0.8              // mask IoU of the projected transformed splat; null if not run
  },
  "raw": { }                              // the untouched SAM 3D pose-decoder fields (v1 record)
}
```

All `*_cam` values are metric and **in the same frame as that photo's
`scene.json`** (same intrinsics, same scale). Older jobs may only have the
version-1 record; consumers treat it as "no placement".

`splat_to_cam` (verified 2026-09-26 by reprojection): `p_cam = scale * R(rotation_wxyz) * p_ply + translation`,
with R the Hamilton quaternion (real part first) acting on column vectors, `p_ply` the x, y, z of the
stored `artifacts/<job_id>/reconstruction.ply` (Fast-SAM3D PLYs are **z-up**), and `p_cam` the scene.json
camera frame. The worker refines SAM 3D's coarse pose against the scene's metric pointmap inside the mask
(trimmed symmetric ICP, upright hypotheses about gravity) and writes `splat_to_cam` only when the mask IoU
is >= 0.6 **and** the depth residual is <= 15%, else `null` (consumers then place the object upright at
`base_cam`). The IoU is against the object's own mask, so an occluded support (a blanket under cats)
scores lower. Extra fields: top-level `metric` (bool) and `verification` {iou_sam3d_camera, iou_rebased,
sam3d_splat_to_cam, refine{chosen, iou, depth_residual, up_cos, ...}}.

### 1b. Per photo (upload): `artifacts/scenes/<upload_id>/`

- `scene.ply` — the whole photo as 3D Gaussians (SHARP), **camera frame, metric,
  aligned to scene.json**. Standard 3DGS binary little-endian PLY with only
  `x y z f_dc_0 f_dc_1 f_dc_2 opacity scale_0 scale_1 scale_2 rot_0 rot_1 rot_2 rot_3`
  (SH degree 0, no extra elements), pruned to <= 600k Gaussians, all values finite.
- `scene.json`:

```json
{
  "version": 1, "upload_id": "...", "photo": "uploads/<p>/<u>/source.jpg",
  "frame": "opencv", "image_size": [W, H],
  "intrinsics": {"fx": 0, "fy": 0, "cx": 0, "cy": 0},
  "gravity_up_cam": [..3], "support_plane": { ...as in 1a... },
  "depth_range_m": [near, far],
  "splat": {"file": "scene.ply", "count": 0, "source": "apple-sharp",
            "aligned_scale": 1.0},        // factor applied to SHARP to match the metric depth
  "depth_grid": {"w": 64, "h": 48, "points_cam": [x0, y0, z0, x1, ...]},  // row-major, NaN-free (invalid -> omitted via "valid" mask)
  "depth_grid_valid": "base64 bitmask or [] when all valid",
  "models": {"depth": "moge-2 ...", "splat": "sharp ...", "gravity": "..."}
}
```

**Metric scale (geometry v2):** the whole photo's metric scale follows SHARP. MoGe-2's pointmap is
rescaled to SHARP's scale (on close-ups MoGe-2 was 1.56x too large; known sizes side with SHARP), so
`splat.aligned_scale` is ~1.0 and every `*_cam` value, pointmap and pose of the photo shares that scale.
scene.json keeps `"version": 1`; v2 is marked by `splat.metric_scale.source == "sharp"`
(`splat.metric_scale` = {source, moge_over_sharp, moge_factor, align_log_mad, align_pixels}). Never mix a
v1 scene.json with v2 poses (the sync refuses: camera height within 3%, focal within 2%, gravity within
3 deg, and `metric: false` poses are rejected). Extra fields: `gravity`, `timings_s`, `vram_peak_gb`,
`splat.{prune, sh_degree, color_space}`.

- `analysis.json` (vision model on the GPU host; optional):

```json
{
  "room_type": "living room", "setting": "indoor|outdoor",
  "time_of_day": "evening", "mood": "cozy, quiet",
  "lighting": {"key_direction": "from window at left", "color_temperature_k": 3200,
               "sources": ["window left", "floor lamp right"], "brightness": "dim|medium|bright"},
  "materials": {"floor": "light oak wood", "walls": "white plaster", "other": ["pink fleece"]},
  "palette": ["#c2185b", "#f8bbd0"],
  "objects": [{"name": "cat", "box": [x0, y0, x1, y1], "salient": true}],
  "search_terms": {"hdri": ["cozy living room"], "sounds": ["room tone", "cat purring"],
                   "images": ["family photos"]},
  "caption": "Two tabby cats asleep on a pink blanket on a red sofa."
}
```

## 2. Backend

- Worker result callback accepts the pose file (`pose`, <= 256 KB). New
  internal routes (worker-token auth):
  - `GET  /v1/internal/reconstructions/{job_id}/scene` ->
    `{"upload_id", "image_key", "exists": bool}`; `exists` = scene.json already stored.
  - `POST /v1/internal/reconstructions/{job_id}/scene` (multipart: `worker_token`,
    optional `worker_id`, files `scene_json` <= 2 MB, `scene_ply` <= 200 MB,
    optional `analysis_json` <= 256 KB) -> stores under `artifacts/scenes/<upload_id>/`,
    records `scene_key` on the upload and on the assets' views.
- Upload default: **no typed names -> detect all objects** (GPU vision labeler,
  `SKETCHSCAPE_SUBJECT_LABELER=gpu`, loopback `SKETCHSCAPE_VLM_URL`, default
  `http://127.0.0.1:8003`), one selection each, deduplicated, capped.

## 3. GPU vision server (`worker/vlm_server.py`, loopback :8003)

- `GET /health` -> `{"status": "ok", "model": "..."}`
- `POST /v1/detect` `{"image_b64": "...", "max_objects": 12}` ->
  `{"objects": [{"name": "tabby cat", "box": [x0,y0,x1,y1] | null, "salient": true}]}`
  Names are short, concrete, SAM-promptable nouns; background surfaces (wall,
  floor, ceiling) excluded; distinct instances of the same kind get distinct names
  only when the photo distinguishes them ("left cat", "right cat").
- `POST /v1/analyze` `{"image_b64": "..."}` -> the `analysis.json` document.
- Detect items also carry `"prompt"` (the bare noun, without the position word); responses carry
  `"model"` and `"cached": true` on a cache hit. Boxes are in the sent image's pixels. Send SAM 3.1 the
  box as well as the name: text alone confuses objects of the same kind.
- `lighting.key_direction` vocabulary (what compose_room parses): `left`, `right`, `above`,
  `behind camera[ left| right]` (light on the camera side), `ahead[ left| right], backlit` (light on the
  far side), plus `, window light` when the key is a window. Machine-readable twins:
  `key_direction_code` (left/right/above/camera[-left|-right]/backlight[-left|-right]) and
  `key_azimuth_deg` (0 = camera side, 90 = right, 180 = backlight, 270 = left). "front" is ambiguous; don't use it.
- Qwen3-VL-4B-Instruct, ~9 GB VRAM; detect ~7-10 s, analyze ~11-14 s uncached (5-7 s right after a
  detect of the same photo). Client timeouts: detect >= 45 s, analyze >= 60 s (one GPU queue).

## 4. Catalog (`config/nemoclaw/asset-catalog.json`, written by sync)

```json
{
  "assets": [{
    "label": "cat", "asset_id": "...", "project_id": "...", "upload_id": "...",
    "job_id": "...", "unity_path": "Assets/SketchScape/AssetLibrary/cat_eebc0a58.ply",
    "native_extent": [..3], "bounds_min": [..3], "bounds_max": [..3],
    "photo": "uploads/.../source.jpg", "pose": { ...pose.json v1 or v2... },
    "mask_area_frac": 0.05
  }],
  "scenes": [{
    "scene_id": "<upload_id>", "project_id": "...", "photo": "uploads/.../source.jpg",
    "unity_path": "Assets/SketchScape/Scenes/<upload_id8>/scene.ply",   // "" if no splat
    "scene": { ...scene.json with a COARSE depth_grid (<= 192 points)... },
    "analysis": { ...analysis.json or {}... },
    "asset_ids": ["..."],                  // objects reconstructed from this photo
    "cut_asset_ids": ["..."]               // objects removed from the scene splat (placed separately)
  }]
}
```

Sync behaviour (scripts/sync_s3_assets_to_unity.py `--project-id <p>` and/or `--scene-id <id>`):
- Standalone scenes (no project) get `project_id` "" and `unity_path` `Assets/SketchScape/Scenes/<id[:8]>/scene.ply`.
- Scene Gaussians clearly below the support plane (3x the plane noise) are pruned as SHARP depth-edge floaters.
- Cut semantics: objects with a **verified** `splat_to_cam` and `mask_area_frac` < 0.3 are cut out and placed
  separately (grabbable); only the part of the mask the placed scan covers is cut (+~2 px, in front of the
  object's far side). Unverified objects stay inside the photo splat (`CUT_UNVERIFIED = False`): from the spawn
  point the photo shows them exactly, whereas an upright guess at `base_cam` floats when the photo crops the
  object (a table cut off by the frame has its lowest *visible* point at seat height). The support under each
  cut object is patched so lifting it shows the surface, not a hole.
- The sync may refine a verified pose against the photo: `pose.object.splat_to_cam` holds the refined value
  (a scale about the camera, so the outline is unchanged), the GPU's original is `splat_to_cam_gpu`, and the
  check is in `pose.sync_refine` {coverage, depth_factor, gap_m_before/after, colour_gain}. Library PLYs of
  cut objects may get a per-channel colour gain (clamped 0.7-1.6) to match the photo (`--no-colour-gain` off).
- `scenes[].cut` records `below_support_pruned`, `filled` and `photo_check`.
- Every splat it writes also gets a Quest-sized copy next to it, `<name>_quest.ply` (not a catalog asset; see 5b).

## 5. Room spec (compose_room -> `SketchScape.RoomKit.Build(string json)`)

JsonUtility-compatible: no nested arrays, no dictionaries, no nulls (use
`enabled`/empty string/empty array). All positions Unity world metres.

```json
{
  "version": 1,
  "slug": "Lazy_Sunday",
  "scene_path": "Assets/SketchScape/AgentRooms/Lazy_Sunday.unity",
  "root": "SharedRoom_Lazy_Sunday",
  "player": {"eye_height": 1.6, "spawn": [0, 0, 0], "yaw": 0},
  "photo_scene": {"enabled": true, "splat_path": "Assets/SketchScape/Scenes/ab12cd34/scene.ply",
                   "position": [..3], "rotation": [..4], "scale": [..3]},
  "objects": [{
    "id": "cat", "label": "cat", "asset_id": "...", "splat_path": "Assets/...ply",  // "" -> placeholder cube
    "mode": "transform|upright",
    "position": [..3], "rotation": [..4], "scale": [..3],   // transform: applied to the splat itself
    "size_m": 0.5,                        // upright: largest side in metres; position = floor contact point, rotation = yaw only
    "tint": [r, g, b], "grabbable": true,
    "light": {"enabled": false, "type": "point", "color": [..3], "intensity": 1.5, "range": 4, "offset": [0, 0.5, 0]}
  }],
  "environment": {
    "hdri_url": "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/<id>_2k.hdr", "hdri_rotation": 0, "hdri_exposure": 1.0,
    "sky_tint": [..3], "ambient_mode": "skybox|flat", "ambient_color": [..3], "ambient_intensity": 1.0,
    "fog": {"enabled": true, "color": [..3], "density": 0.02},
    "floor": {"enabled": true, "size": [12, 12], "height": 0, "texture_url": "", "color": [..3], "tiling": 4},
    "shell": {"enabled": false, "center": [..3], "size": [6, 3, 6], "wall_texture_url": "", "wall_color": [..3], "ceiling": true}
  },
  "lights": [{"type": "directional|point|spot", "color": [..3], "intensity": 1, "position": [..3],
               "rotation": [..4], "range": 5, "spot_angle": 60, "shadows": "soft|hard|none", "name": "Key Light"}],
  "images": [{"url": "...", "title": "...", "attribution": "...", "position": [..3], "rotation": [..4],
              "width": 0.8, "frame": true, "frame_color": [..3], "lit": true}],
  "audio": [{"url": "...", "title": "...", "attribution": "...", "position": [..3], "spatial": true,
             "volume": 0.6, "loop": true, "min_distance": 1, "max_distance": 12}],
  "particles": [{"kind": "dust|fireflies|snow|rain|embers", "position": [..3], "size": [..3],
                 "color": [..3], "rate": 20}],
  "staging": {"enabled": true, "mood_color": [..3], "glow_position": [..3], "motif_xz": [x0, z0, x1, z1],
              "reveal_order": ["cat"], "reveal_seconds": 1.2, "narration": "...", "narration_audio_url": ""},
  "teleport": {"floor_collider": true, "hotspots": [x0, y0, z0, x1, y1, z1]},
  "credits": ["'Title' by Author, CC BY 4.0, via Openverse"],
  "performance": {"target": "quest", "prefer_quest_lod": true, "pickups": true,
                  "quest_performance": true, "meta_setup": true}   // optional; absent = these defaults (5b)
}
```

`RoomKit.Build` refuses to run when an open scene other than the room's own has
unsaved changes (1.0.16; before, unsaved AgentRooms scenes were discarded),
creates the scene at `scene_path`, downloads every URL once into
`Assets/SketchScape/WebCache/` (failures are reported, never fatal), builds
everything, adds a `SketchScape.RoomDirector` (runtime reveal/ambience) and a
`SketchScape.RoomBuildInfo` (the performance flags + grabbable ids, for Finalize) to the
root, saves, and returns a short plain-text report (< 2 KB) of what exists and
what failed. `RoomKit.Finalize(string slug, float spawnX, float spawnZ, float yaw)`
does the Meta XR setup, moves the camera rig to the spawn point, saves, and reports (5b).

Conventions (RoomKit 1.0.16, type `"SketchScape.RoomKit, Assembly-CSharp-Editor"`, `Version()`):
- Build report lines: `OK built <path> root=<root>`, `objects N: id(splat,transform|splat,upright|cube)...`,
  `photo_scene=ok|missing|off sky=... lights= images=a/b audio=a/b particles= hotspots= staging=on(reveal N) lighting=baked`,
  `credits: ...`, optional `notes: ...`, `failures: none|...`, `next: ...`. Errors start with `ERROR`.
- Gsplat imports PLY (x, y, z) as local (x, y, -z) (`GSPLAT_IMPORT_MAP`); that flip is the one reflection
  right-handed data needs, so photo and object splats get proper rotations. Upright mode: Euler(90,0,0), positive scale.
- `objects[].id` is the GameObject name under the root (Finalize targets `/<root>/<id>`); `images[].rotation` has +Z pointing away
  from the viewer; the floor plane is centred at the world origin; `floor.height` is -0.02 under a floor-kind photo scene.
- Floor-kind photo scenes tint the room floor to the photo's own floor colour; surface-kind scenes (no floor in the
  photo) get a collider-less plinth 0.12 m under the surface. After Build/Finalize the Scene View sits at spawn + eye height.

## 5b. Quest budgets + RoomKit 1.0.16 finalize

A room built on 2026-09-27 ran at 5 FPS on a Quest 2: 3.37M Gaussian splats (one 976k-splat teddy bear),
the Ultra quality level (4x MSAA), no foveation. Every room is now Quest-ready by default:

- **Quest copies (sync).** `scripts/sync_s3_assets_to_unity.py` writes `<name>_quest.ply` next to every splat
  it syncs (`decimate_splats.decimate`: the most important splats by opacity x area, kept splats scaled up
  <= 1.3x to keep coverage). Budgets: 25,000 per object (`--quest-object-splats`), 120,000 per photo scene
  (`--quest-scene-splats`), so a photo scene + 6 objects is ~270k; a smaller source is copied as is;
  `--no-quest-lod` turns it off. The copy's `.meta` is the source's (same Gsplat importer settings) with a new
  GUID, moved into `Assets` before the PLY (both are staged in `%LOCALAPPDATA%\SketchScape\questlod-stage`).
  A copy newer than its source with the right count is skipped; a remade copy keeps its GUID.
  `--quest-lod-only [PATH ...]` makes / refreshes copies for splats already in the project (no AWS, catalog
  untouched), e.g. for scans synced before 2026-09-27.
- **Build** renders `<path>_quest.ply` instead of `<path>.ply` when it exists and `prefer_quest_lod` is on
  (objects and the photo scene); placement and colliders still come from the full-resolution splat, so the
  layout is identical either way. Report line: `splats: <n> Quest copies + <m> full-res, <total> in all
  (target quest)`, naming splats that have no copy and warning above 400,000 splats. `next:` says
  `finalize_code <slug>`.
- **Finalize** (one Run Command instead of ~20 `meta_add_*` calls) follows the flags Build recorded
  (`RoomBuildInfo`; a room built before 1.0.16 gets the defaults, every object grabbable) and only adds what is
  missing, in order: Meta camera rig -> interaction rig -> near grab and distance grab (PullToHand) on every
  grabbable object -> a Meta teleport hotspot (SnapPosition) at every `TeleportHotspots/TeleportHotspot_N`
  marker, moved under its marker (`meta_setup`; it calls the `meta_add_*` tools' own handlers from
  `com.meta.xr.unity-mcp.extension`, and says so if the package is missing) -> `SketchScapePickup` on every
  grabbable object (`pickups`) -> `QuestPerformance` (foveated rendering) on the `OVRCameraRig` and, if
  Android's default quality level has MSAA, Android switched to the highest level without it
  (`quest_performance`) -> rig to the spawn (floor-level tracking) -> `RoomBuildInfo.finalizedWith` stamped
  -> save. One report line per step, `added`, `present`, `skipped` or `FAILED`, e.g. `grab 3/3 added`,
  `teleport hotspots 4/4 present`. When the room's scene isn't the active one, Finalize opens it first,
  never over unsaved changes. Running it twice is safe.
- **Status** `RoomKit.Status(string slug)` (read-only; `status_code <slug>`) returns one JSON line with the keys
  `slug, scene, scene_exists, open, built, objects, grabbable, distance_grabbable, pickups, teleports,
  camera_rig, interaction_rig, quest_performance, quest_lod_renderers, full_res_renderers, splats_total,
  finalized, android_msaa`. It never opens a scene: when the room isn't the active scene, `open` is false,
  `scene_exists` says whether `AgentRooms/<slug>.unity` exists and the other scene values are null.

## 6. Agent tools (sandbox skill `sketchscape-unity-room`)

`unity_room_cli.py` verbs: `list_scenes all`, `list_assets all`,
`search_images '<json>'`, `search_environment '<json>'`, `search_sounds '<json>'`,
`compose_room '<json>'`, `build_code <slug>`, `finalize_code <slug>`.
Generated `Unity_RunCommand` code is a few lines that call RoomKit through
reflection with the spec as a string literal, so the agent copies little.

`compose_room` request (all optional except scene_id and/or objects): `scene_id` (id or unique prefix >= 6
chars; `"none"` disables the automatic scene), `objects` [{label, asset_id?}], `room_name`, `theme`,
`connection_insight` {theme, explanation}, `player_eye_height` (0.8-2.2), `environment` {hdri | hdri_url,
floor_texture, wall_texture (enables the shell), fog: false | number | {enabled, density, color}, shell},
`images` [{url, title, attribution, width?, height?, placement: left|right|behind|{position}}] (max 6),
`sounds` [{url, title, attribution, kind: ambient|object, attach_to}] (max 5), `lights` [...],
`particles` (auto|none|kind|[kinds]), `credits`. Plan output: summary, room {slug, scene_path, root, spawn,
yaw}, photo_scene, objects, in_photo_scene, environment, lights, audio, images, particles, staging, credits,
unity_steps, notes.

Anchoring to the photo: compose_room locates each `analysis.objects[].box` in the room (median depth of the
coarse depth-grid points inside the box, unprojected with the scene intrinsics and mapped with the photo
splat's camera -> world transform). A fireplace in the photo gets the fire crackle, the embers and a warm
"Hearth glow" light; lamps named as light sources get their practical light at the lamp; outdoor ambience
(birdsong, street) and rain come in through the photo's window (or curtains). The analysis' own
`search_terms.sounds` choose the curated sounds; indoors the non-spatial bed is always an indoor ambience.
