# HandMenu

The wrist menu that opens when someone turns their palm up: the only persistent UI inside a room.

Props: `items` (`[{icon, label, onSelect, toggle, active, hover}]`).

Unity spec:
- Anchor to the non-dominant wrist, 8cm above the palm, facing the head. Palm-up opens it; palm-down or a selection closes it.
- Glass column (`glass`, `radius-frame`); each item a 48dp glass circle with a `vr-body` label, 12mm apart. Hover: `halo`. Toggles on: `action` fill.
- Order: Hub, Who's here, Mic, Photos, Leave room last. Five items at most.
- Leaving fades through white (day) or deep blue (dusk) over `duration-enter`.
