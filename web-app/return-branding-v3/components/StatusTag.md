# StatusTag

The state of a room as a pill with an icon and a word, so it never depends on color alone.

Props: `status`: `new` (blossom), `developing` (sun, spinner, reads "Building"), `waiting` (sky, "Waiting" or "Waiting for Sam"), `invited` (blossom, "Invitation"), `ready` (success), `shared` (aurora), `private` (muted), `failed` (danger, reads "Couldn't build"); `onImage` (glass version for cards); children override the word.

- One status per room, plus `new` if it applies. On cards they sit top-left and top-right on glass.
- Don't invent new colors for new states: map them to these or change the word.
