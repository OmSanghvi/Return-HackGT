---
name: unity-guide-bot
description: Use for Build Plan steps 33 and 34 — the guide bot inside the Quest room (HackGTUnity). Step 33 is single-headset: the JsonUtility DTOs, SketchScapeGuideClient calling /v1/rooms/{project_id}/guide/*, the element-id → GameObject map, the light-orb bot state machine (move, reveal, highlight, spatial audio), XRI input (next/repeat/ask-about/more/linger), and the editor simulator. Step 34 makes one shared bot per room over Netcode for GameObjects with Distributed Authority, driven by the session owner.
---

# Unity guide bot (steps 33, 34)

## Gate

- Step 33: run `python3 scripts/check_collab_gates.py 33`. It needs step
  32. Step 32's mock provider is enough; no live model is needed.
- Step 34: run the same command with `34`. It needs steps 22 and 33.
- If either says BLOCKED, stop. The Unity project is `../HackGTUnity` (or
  `SKETCHSCAPE_UNITY_PROJECT`).

## Rules

- Unity talks only to `/v1/rooms/{project_id}/guide/*` (Hard Rule 4). No
  model SDKs and no model keys. The gate's secret scan covers `Assets/`.
- **No text on screen.** No speech bubbles, no captions, no panels.
  Everything is voice, light, and motion (AGENT.md: felt, not read).
- If there's no tour, or the backend is unreachable, the room loads and
  works exactly as before, with no bot. Test this.
- Use existing patterns:
  - the `apiBaseUrl` serialized field, the same as
    `SketchScapeExperienceCompiler`
  - `UnityWebRequest`
  - `JsonUtility`
  - `NamedSceneInteractive` ids for objects

## Step 33 files (`Assets/Scripts/Guide/`)

1. `SketchScapeGuideModels.cs`: `[Serializable]` classes:
   - `GuideTourResponse`, `GuideStep`, `GuideStop`, `GuideElement`
   - `GuideSessionResponse`
   - `GuideTurnRequest`, `GuideEvent`
   - `GuideTurnResponse`, `GuideLine`, `GuideValidation`

   Field names use snake_case exactly as in the JSON. `offset_m` is
   `float[]`. JsonUtility can't do nulls, so the backend sends `""` and
   `[]` (step 32 guarantees it). Treat `""` as absent.
2. `SketchScapeGuideClient.cs`:
   - `IEnumerator GetTour(Action<GuideTourResponse>)`
   - `StartSession(...)`
   - `SendTurn(GuideEvent, Action<GuideTurnResponse>)`
   - Header `X-SketchScape-Dev-User` comes from `AccountSwitcher.Current`
     if the type exists (step 22), else from a serialized
     `defaultAccount`.
   - Keeps `turnSeq`. Generates `client_turn_id =
     Guid.NewGuid().ToString("N")`, and reuses it on a retry of the same
     event.
   - On 409, applies the returned turn and sets `turnSeq` to the server's
     value. `timeout = 15`.
3. `SketchScapeGuideObjectMap.cs`: builds `Dictionary<string, GameObject>`
   from every `NamedSceneInteractive` in the scene, keyed by its id.
   `RegisterMotif(string stagingCueId, GameObject go)` is for step 6's
   components. `TryGet(elementId, out GameObject)` resolves through the
   tour's `element.object_id` or `staging_cue_id`.
4. `SketchScapeGuideHighlighter.cs`:
   - `Highlight(IEnumerable<GameObject>)`, `ClearAll()`.
   - Mesh objects get an emissive rim (MaterialPropertyBlock, no material
     leaks).
   - Gaussian splats (no mesh renderer) get a narrow spotlight cone from
     the bot plus a soft ring decal on the floor under the object's
     bounds.
   - At most 4 at once.
5. `SketchScapeGuideBot.cs` (the prefab `Assets/Prefabs/GuideBot.prefab`
   is a 12 cm emissive sphere with a particle halo, an `AudioSource` with
   `spatialBlend = 1` and min/max distance 0.5/8 m, and a point light):
   - States: `Idle`, `Thinking`, `Moving`, `Speaking`.
   - `Execute(GuideTurnResponse t)` is a coroutine that runs these in
     order:
     1. `ClearAll()`.
     2. If `t.move_to.anchor_element_id != ""`, move to `anchor.position
        + anchor.rotation * offset` with `Vector3.SmoothDamp`. Use the
        step 6 tween library instead if it's installed. Max 1.2 m/s, keep
        the height ≥ 1.2 m, and face the anchor.
     3. Reveal each id: `SetActive(true)`, a 0.6 s scale from 0 to the
        original size, and a chime.
     4. Highlight the ids.
     5. For each line: if `audio_url != ""`, load it with
        `UnityWebRequestMultimedia.GetAudioClip(url, AudioType.WAV)`,
        play it, and wait `clip.length + 0.25 s`. If `audio_url` is empty
        and `pending_audio` is true, retry once after 1 s, then skip. If
        there's no audio at all, play the chime and wait 1 s.
     6. If `t.end`, fade out and despawn.
   - While `Thinking` (the request is in flight), the light pulses at
     0.8 Hz, with a soft hum loop at −18 dB. Stop it the moment the
     response arrives.
   - At load: `GetTour`. If `tour_available` is false, disable the bot and
     return. Hide every element with `initially_visible == false` (after
     the builder spawned it), and keep a set of revealed ids.
     `StartSession` → `Execute(first turn)`.
6. `SketchScapeGuideInput.cs` uses XRI 3.0.11 input action references,
   not hard-coded buttons:
   - `primaryButton` (A) = `next`
   - `secondaryButton` (B) = `repeat`
   - `activate` (trigger) while the right `XRRayInteractor` hovers a
     mapped element = `ask_about`
   - `select` (grip) on the bot's collider = `more`
   - Gaze: a raycast from the camera every 0.2 s. Dwell ≥ 6 s on a mapped
     element that has no linger sent yet, and that isn't the current
     step's focus, sends `linger`. At most one per element per session.
   - Everything is ignored while `bot.Busy`.
7. **Builder:** in `SketchScapeOfflineExperienceBuilder`, after the
   authored objects, instantiate `GuideBot.prefab` under the experience
   root and add `SketchScapeGuideInput` to the rig. Pass `project_id`
   from `BuiltExperienceController`.
8. **Editor:** in `Assets/Editor/SketchScapeGuideSimulator.cs`, the menu
   `Tools/SketchScape/Guide/Simulate Tour` enters Play mode with keyboard
   bindings: N = next, R = repeat, M = more, left-click an object =
   ask_about.

## Step 33 verification

- Desktop simulator against `uvicorn` in mock mode with 3 contributors and
  a tour composed and activated through step 30:
  - the full tour plays
  - the hidden element is revealed at `s_together`
  - `ask_about` works on each contributed object
  - an unreachable backend → no bot, room fine
- On Quest: 72 Hz with the bot moving and audio playing (use the OVR
  Metrics Tool). Audio is clearly spatial. The user confirms
  `guide_bot_verified` in `config/collab-vr/gates.json`. Never set it
  yourself.

## Step 34: shared guide (`SketchScapeGuideNetwork.cs`)

- The bot prefab gets a `NetworkObject` and a `NetworkTransform`, and it's
  spawned by the session owner. In Distributed Authority, set ownership to
  the session owner, and handle `OnSessionOwnerChanged` by taking
  ownership.
- Store the backend `session_id` in a session property (`guide_session`),
  and replicate `turnSeq` as a `NetworkVariable<int>`.
- A new owner reuses both and sends nothing until the next visitor event.
  If its `turn_seq` is behind, the backend's 409 returns the latest turn,
  and the owner adopts it (step 32's compare-and-set).
- `NetworkVariable<FixedString64Bytes> currentStepId`, `speakingLineId`.
  `NetworkVariable<FixedString4096Bytes> revealedCsv`, `highlightedCsv`,
  `speakingAudioUrl`. `NetworkVariable<double> speakingStartTime`
  (`NetworkManager.ServerTime.Time + 0.3`).
- Every client plays `speakingAudioUrl` when `ServerTime ≥
  speakingStartTime`. Each client downloads its own copy. Clients that
  join late apply `revealedCsv` and `highlightedCsv`, and don't replay a
  line that already started more than 1 s ago.
- `[Rpc(SendTo.Owner)] void SubmitGuideEventRpc(FixedString32Bytes type,
  FixedString64Bytes elementId)`. The owner queues events FIFO with a
  maximum of 4 and drops extras, sending one to the backend at a time.
- Backend: `POST /guide/sessions?scope=room` (added in this step) returns
  the project's single room session.

## Step 34 verification

On two Quests: A asks about B's object, and both hear the answer in sync
(within 150 ms). The owner leaves mid-tour, and the other headset continues
from the same step. A late joiner sees the already-revealed elements. The
user confirms `shared_guide_verified`, and the results are recorded in the
step 25 results.
