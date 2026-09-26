# PhotoDrop

The upload step: a dropzone for one moment's photos, with the chosen photos underneath.

Props: `photos` (`[{src, name, id}]`), `max` (default 12), `onFiles(files)` (image files only, clipped to the remaining slots), `onRemove(index)`, `title`, `hint`, `onImage` (frosted glass-strong version for use over imagery), `active` (force the drag-over look). Click, Enter or Space opens the file picker.

- Copy speaks about the moment: "Bring a *moment* back". The hint says what makes a better world (more angles of the same place).
- Drag-over lifts the zone and tints it `sky-soft`; the title changes to "Let *go*".
- The first photo is the cover; say so under the thumbnails.
