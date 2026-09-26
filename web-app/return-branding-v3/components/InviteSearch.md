# InviteSearch

Invite people to a room by searching your contacts or typing an email.

Props: `results` (`[{name, email}]` matching the current query; you run the search), `invited` (`[{name, email}]`), `onQuery(query)`, `onInvite(person)`, `onRemove(person)`, `searching`, `label`, `placeholder`, `defaultQuery`.

- Results show name and email with an Invite button; already-invited people show "Invited".
- A full email that matches no one appears as its own row: "Invite sam@… · Not on return yet. We'll email them an invite."
- Invited people collect as removable chips under the search.
- Debounce `onQuery` (~250ms) and search by prefix on name and email. The backend sends the invite email; this component only collects people.
