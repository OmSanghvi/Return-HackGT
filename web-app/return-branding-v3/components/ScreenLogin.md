# ScreenLogin

Route `/sign-in`. Clerk's `<SignIn />` (and `<SignUp />`) themed to return, centered on the cloud-field imagery. Auth itself is Clerk's; this screen only styles it.

- Pass `appearance` from `clerk/appearance.ts` (in the branding kit): colors, radius, Hanken Grotesk, pill buttons and inputs, glass-strong card.
- Copy: title "Welcome *back*" (sign-in) / "Start your first *room*" (sign-up). Keep Clerk's "Secured by Clerk" footer.
- After sign-in, redirect to `/rooms` (the dashboard), or back to the invite link if they arrived from one.
