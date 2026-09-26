# ShareSheet

The manage-people dialog for an existing room (from the room card's ⋮ menu): who's in it and what they can do. For inviting during room creation use InviteSearch.

Props: `title`, `link`, `people` (`[{name, role: 'owner' | 'visit' | 'add', here, note}]`), `onInvite(value)`, `onRoleChange(person, role)`, `onCopy`, `onClose`, `onImage` (frosted glass-strong version over the room's own image). Render it inside your modal with `image-scrim` behind.

- Two roles: **Can visit** and **Can add photos**. Adding photos rebuilds the room with more angles; that's the connective loop.
- Title: "Who can *return* here". Show who is here now in `aurora`.
