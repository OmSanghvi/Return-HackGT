# DevelopProgress

Generation shown as a world coming out of the mist: the cover starts blurred and washed in white fog and resolves to sharp as the steps finish.

Props: `src`, `title`, `steps` (default: Reading your photos, Estimating depth, Building the world, Setting the light), `step` (current index), `progress` (0 to 1), `error` (a sentence; switches to the failed state), `actions`.

- Rename the steps to match what your pipeline does.
- Say how long it takes and that people can leave the page.
- At `progress` 1 the title reads "Ready to *return*" and the bar turns success. Viewing is VR only: tell people it's waiting in their headset under the same account.
- In the room flow this is the "building" state that follows the waiting screen once everyone has added photos.
- On failure, name the cause and the fix, never a raw error.
