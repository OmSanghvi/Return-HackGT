# Field

Pill text inputs with label, hint and error wired to `aria-describedby`.

Props: `label`, `hint`, `error` (replaces the hint, sets `aria-invalid`), `multiline` (rounded textarea), `onImage` (glass input for heroes), `onSubmit(value)` (adds a round arrow button inside the pill and submits on Enter), `submitLabel`, plus native input attributes.

- Labels are questions or plain nouns. Placeholders show an example, never the instruction.
- Errors say what's wrong and how to fix it, in one sentence.
- On imagery use `onImage` with `onSubmit`: the waitlist or invite pill from the landing.
