# Outlook is slow, freezes, or crashes on start (bad add-in)
keywords: slow, freezing, hangs, crash, crashes, not responding, add-in, addin, add in, plugin, safe mode, stops working

## Questions
- Does Outlook open normally in Safe Mode (Win+R, then outlook.exe /safe)? [yes]
- Did the problem start after a new add-in or update was installed? [yes]
- Does Outlook show "Outlook is not responding" or close by itself? [yes]

## Warnings
- If Safe Mode works, the cause is almost always an add-in, not the mailbox.
- Disable add-ins one at a time so you know which one is the cause.

## Steps
1. Close Outlook completely.
2. Open it in Safe Mode (Win+R, type outlook.exe /safe, press Enter).
3. In Outlook go to File, Options, Add-ins.
4. At the bottom, set Manage to "COM Add-ins" and click Go.
5. Untick all add-ins, click OK, then restart Outlook normally.
6. If it works, turn the add-ins back on one at a time, restarting each time, until the problem returns.
7. Leave the problem add-in off or update it.
