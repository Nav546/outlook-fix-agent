# Outlook search returns nothing or is incomplete
keywords: search, cannot find email, search not working, no results, missing emails, index, indexing, find

## Questions
- Does search return no results or miss mail the user knows exists? [yes]
- Is the user using the cached copy of the mailbox (Cached Exchange Mode)? [yes]
- Did the problem begin after a profile change or migration? [yes]

## Warnings
- Rebuilding the index can take a long time and slow the PC while it runs.
- Do not do this during working hours if the user is busy.

## Steps
1. In Outlook, go to File, Options, Search, then Indexing Options.
2. Click Advanced, then Rebuild.
3. Leave Outlook open while it re-indexes. This may take hours for a big mailbox.
4. Meanwhile, check Outlook on the web to confirm the mail is still in the mailbox.
5. If search is still broken afterwards, create a new profile (see the profile fix note).
