# Outlook won't open after mailbox migration (profile problem)
keywords: outlook won't open, cannot start outlook, profile, migration, migrated, cloud, stuck on loading profile, can't open outlook

## Questions
- Was the user's mailbox recently moved to the cloud (migration)? [yes]
- Does Outlook fail to open, or hang on "Loading profile"? [yes]
- Does Outlook ALSO fail in Safe Mode (Win+R, then outlook.exe /safe)? [yes]

## Warnings
- Check the user can sign in to Outlook on the web first, so you know the mailbox itself is healthy.
- Add the NEW profile first. Only remove the old profile once the new one works.
- The new profile rebuilds the local mail cache, so mail may take a while to fill in.

## Steps
1. Close Outlook completely (check Task Manager for outlook.exe).
2. Open Control Panel, then Mail (Microsoft Outlook) (32-bit), then Show Profiles.
3. Click Add, give it a new name, and let it set up the account automatically with the user's email address.
4. Under "When starting Microsoft Outlook, use this profile", choose "Always use this profile" and pick the new one.
5. Open Outlook and confirm the mailbox loads.
6. Once it works, go back to Show Profiles and remove the old profile.
