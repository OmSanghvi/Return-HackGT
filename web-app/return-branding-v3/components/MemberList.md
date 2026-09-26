# MemberList

Everyone in a room and whether they've added their photos. The heart of the waiting screen.

Props: `members` (`[{name, email, status: 'done' | 'uploading' | 'joined' | 'invited', count, hasNote, progress, sentAgo, isYou, isOwner, here}]`), `onResend(member)`.

- Each row: initials, name ("(you)" for the viewer), and a status line with an icon: done "Added 4 photos and a note" (success), uploading "Uploading 2 of 6" (sun, spinner), joined "Joined, hasn't added photos yet", invited "Invite sent 2 hours ago" with a Resend button.
- Update it live (poll or subscribe) so people see others finish while they wait.
