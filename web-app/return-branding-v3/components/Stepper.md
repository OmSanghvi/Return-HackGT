# Stepper

Where someone is in creating a room: Name and invite → Add your photos → Wait for everyone.

Props: `steps` (labels), `current` (0-based), `onImage`.

- Done steps get a check in `success-soft`; the current step is filled with `action`.
- Use the same three labels on screens 4, 5 and 6 so people always know where they are. Invited people who join an existing room start at step 2.
