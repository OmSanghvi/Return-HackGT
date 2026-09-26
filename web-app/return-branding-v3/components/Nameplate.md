# Nameplate

A floating name above another person's avatar inside a shared room, with speaking and muted state.

Props: `name`, `speaking`, `muted`, `status` (short line under the pill), `here` (default true).

Unity spec:
- Billboard toward the viewer, `nameplate-offset` (0.28m) above the head. Keep `vr-h2` apparent size (24dp) from 1m to 6m; hide beyond 8m.
- Glass pill with the `glow-aurora` ring; speaking animates three bars; muted shows the mic-off icon. First names only.
