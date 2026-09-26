# Button

Pill buttons. The label is a verb in sentence case ("Start your return", "Return in VR", "Copy link").

Props: `variant`, `size` (`sm` | `md` | `lg`), `icon`, `iconAfter`, `arrow` (true for a right arrow, or an Icon name such as `arrowUpRight`: adds the round dot at the end), `loading`, `fullWidth`, `href` (renders a link), plus native button attributes.

Variants on plain surfaces and glass-strong:
- **primary**: `action` fill, `on-action` label. Once per view, for the step toward returning.
- **secondary**: outlined with `line-strong`. Share, Invite, Add photos.
- **ghost**: dismissals. **danger**: destructive and irreversible only, never filled.

Variants on imagery:
- **light**: solid white pill with dark label. The primary on imagery.
- **glass**: frosted pill (`glass`, `on-glass`). Secondary actions on imagery.
- **text**: bare white label with an icon. Only over a scrim.

Don't put two primaries (or two lights) side by side, and don't use icon-only buttons without an `aria-label`.
