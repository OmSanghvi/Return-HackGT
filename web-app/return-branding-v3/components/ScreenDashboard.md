# ScreenDashboard

Route `/rooms`. Your rooms: invitations to accept, rooms you're in, and creating a new one.

- Top: plain GlassNav (Rooms, Settings, Create a room, avatar). A short bottom-left HeroFrame header "Your *rooms*" with a one-line summary of what needs attention.
- Invitations row (only when there are any): RoomCard with status `invited` and Join room / Decline actions.
- Your rooms grid: RoomCard per room with its status (waiting / building / ready) and a ⋮ manage menu (Rename, Manage people → ShareSheet, Leave room, Delete room). Last tile: dashed Create a room.
- Opening a room routes by its state: you haven't added photos → screen 5; waiting on others → screen 6; building → screen 6 in its building state; ready → screen 7.
- Empty state: HeroFrame with "Start your first *room*" and one primary.
