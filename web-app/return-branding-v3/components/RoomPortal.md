# RoomPortal

A room in the VR hub: an arched window onto its world, floating in the sky. Pinch it to step inside.

Props: `src`, `title`, `people` (count of past visitors), `state` (`idle` | `hover` | `entering`), `onEnter`.

Unity spec:
- `portal-size` 0.9×1.2m arched window showing a live render (or the cover) of the room. Portals sit on an arc `portal-ring-radius` (2.4m) from the viewer at eye height, bobbing 2cm over 6s. Only rooms with status ready appear.
- Hover (gaze or ray): scale 1.04, `halo`, hint reads "Pinch to step inside".
- Entering: the window scales toward the viewer and blooms white, then the view fades through white into the room over `duration-enter`. Reverse when leaving.
- Title `vr-display`, roman.
