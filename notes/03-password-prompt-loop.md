# Outlook keeps asking for a password
keywords: password, prompt, keeps asking, credentials, sign in, login, authentication, credential manager, loop, repeated

## Questions
- Does the password prompt come back even after entering the right password? [yes]
- Was the password changed recently, or the mailbox recently migrated? [yes]
- Can the user sign in to Outlook on the web with the same password? [yes]

## Warnings
- If web sign-in also fails, this is an account or password problem, not an Outlook problem. Escalate to whoever manages accounts.
- Only remove saved credentials that relate to Office or Outlook.

## Steps
1. Close Outlook completely.
2. Open Control Panel, then Credential Manager, then Windows Credentials.
3. Remove saved entries that mention MicrosoftOffice or outlook.
4. Restart Outlook and sign in again when prompted.
5. If the prompt still loops, create a new profile (see the profile fix note).
