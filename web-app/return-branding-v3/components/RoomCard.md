# RoomCard

A room on the dashboard: its world as a tall rounded image, the name in Role Model, a status, the people in it, and a manage menu.

Props: `src` (cover or generated view; falls back to a sky gradient), `title`, `place`, `date`, `photoCount`, `meta` (overrides the meta line, e.g. "2 of 3 added photos"), `status` (`invited`, `waiting`, `developing`, `ready`, `shared`, `private`, `failed`), `waitingFor` (name, reads "Waiting for Sam"), `people` (`[{name, here}]`), `onOpen`, `onManage` (shows the ⋮ menu button; you render the menu: Rename, Invite people, Leave room, Delete room), `action` (buttons pinned to the bottom, used for invitations: Join room / Decline), `width`.

- The card is a div with a full-size open button behind the content, so the manage button and actions stay separate buttons (no nesting).
- `developing` rooms show the image blurred and washed out until the world is built.
- Status per flow step: invited → (joined) → waiting (someone hasn't added photos) → developing (building) → ready.
- Grid of four on desktop with `space-5` gaps; the last tile is the dashed "Create a room" tile (see the dashboard screen).
