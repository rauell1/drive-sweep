# Testing updates on a real PC

Automated tests check the updater's logic on every pull request, but only a real Windows PC shows the whole path a user takes: the old version finds the new release, downloads it, closes, swaps itself and opens the new version. Run this checklist after each release, starting from the **previous** version (for example, update 0.7.1 to 0.7.2). It takes about 20 minutes.

The test exercises the updater of the version you start from, so it confirms that people who already have that version can upgrade.

## Before you start

- A Windows 10 or 11 PC (a spare PC or a virtual machine is best; Windows Sandbox works too).
- The new release is published on GitHub (the release workflow has finished and the assets are listed).
- Download the **previous** release's `DriveSweep.exe`, `DriveSweep-win64.zip` and `DriveSweep-Setup-X.Y.Z.exe` from its GitHub release page.
- Optional: note the contents of `%LOCALAPPDATA%\DriveSweep` (settings, history and the diagnostics log). They should survive every update.

Write down the result of each step as **pass** or **fail**. If something fails, open **Settings & Updates > Open Diagnostics Log** and attach the log to an issue.

## 1. Portable `DriveSweep.exe`

1. Make a test folder, for example `C:\DSTest\portable`, and put the previous `DriveSweep.exe` in it. Add a file named `my-notes.txt` next to it.
2. Start `DriveSweep.exe` (click **More info > Run anyway** if SmartScreen appears). Finish the first run notice.
3. Open **Settings & Updates**, click **Check for Updates**. **Expect:** the new version is offered, with a description saying it replaces this `DriveSweep.exe` in the same folder.
4. Click **Download & Update vX.Y.Z**. **Expect:** progress is shown, then DriveSweep closes by itself.
5. **Expect:** within about 10 seconds the new version opens on its own, and **Settings & Updates** shows the new version number.
6. In the test folder, **expect:** only `DriveSweep.exe` and `my-notes.txt`. No `DriveSweep.exe.old`, `.new` or `.part` files remain.
7. Right click `DriveSweep.exe` > **Properties > Details**. **Expect:** the new file version.
8. **Expect:** your language, theme and cleanup history are unchanged.

## 2. Zip folder version

1. Unzip the previous `DriveSweep-win64.zip` into `C:\DSTest\folder`. Add `my-notes.txt` to that folder.
2. Start `DriveSweep.exe` from the folder and repeat steps 3 to 5 of section 1. **Expect:** the description says it downloads `DriveSweep-win64.zip` and replaces the program files.
3. In the folder, **expect:** no `_update_old` or `_update_staging` folders and no `DriveSweep-win64.zip.download` file remain, and `my-notes.txt` is still there.
4. **Expect:** the new version number in **Settings & Updates**.

## 3. Installed copy (Setup)

1. Run the previous `DriveSweep-Setup-X.Y.Z.exe` and install with the defaults.
2. Start DriveSweep from the Start menu and repeat steps 3 and 4 of section 1. **Expect:** the description says it downloads the new Setup and updates the installed copy.
3. **Expect:** Windows asks for Administrator permission (UAC) once. Click **Yes**.
4. **Expect:** Setup runs silently and DriveSweep opens again showing the new version.
5. Open **Settings > Apps > Installed apps**. **Expect:** exactly one **DriveSweep** entry, showing the new version.
6. **Expect:** no leftover `.exe` files in `%TEMP%\DriveSweep-Updates`.

## 4. Rollback (portable version)

This checks that a new version which fails to open is replaced by the previous one again. It simulates the failure by closing the new version before its window appears.

1. Set up a fresh portable copy of the previous version as in section 1, steps 1 and 2.
2. Open **Windows PowerShell** and paste this. It waits for DriveSweep to close for the update, then stops the new version the moment it starts:
   ```powershell
   while (Get-Process DriveSweep -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 100 }; while (-not (Get-Process DriveSweep -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 50 }; Start-Sleep -Milliseconds 300; Stop-Process -Name DriveSweep -Force; "Stopped the new version"
   ```
3. In DriveSweep, check for updates and click **Download & Update vX.Y.Z**.
4. **Expect:** PowerShell prints `Stopped the new version`, and a few seconds later the **previous** version opens again by itself.
5. **Expect:** **Settings & Updates** shows the previous version number, and the folder contains `DriveSweep.exe` and `my-notes.txt` with no `DriveSweep.exe.old` left behind.
6. Check for updates again and update normally. **Expect:** it succeeds as in section 1.

If the new version's window was already open when PowerShell stopped it, the update counts as successful and no rollback happens. Run the test again; on a very fast PC, change `300` to `0`.

## 5. Undo, preview export and scheduled cleanup (0.8.0 and later)

These use the real Windows Recycle Bin. Automated tests on GitHub's Windows machines cover the basics on every pull request (`tests/test_recycle_bin_windows.py`); this checks the full app on your PC.

1. **Undo.** Note a few files in `%TEMP%`, run a Quick Clean with **Recycle Bin (Safe)**, then open **Cleanup Log** and click **Undo Last Cleanup**.
   - **Expect:** the confirmation shows a plausible item count and size, and after **Undo Cleanup** the files are back in `%TEMP%`.
   - **Expect:** a file the app recreated meanwhile is listed under **Left in the Recycle Bin** and the newer copy is untouched.
   - **Expect:** the Cleanup Log shows an **Undo Cleanup** entry, the lifetime total drops by the restored size, and **Undo Last Cleanup** no longer appears.
2. **Undo an earlier cleanup.** Run two small cleanups of different folders, then click **Undo** next to the older one in the Cleanup Log. **Expect:** only the older cleanup's files come back, and the newer one can still be undone.
3. **Undo after emptying.** Clean again, empty the Recycle Bin, then open the Cleanup Log. **Expect:** no **Undo Last Cleanup** button.
4. **Preview export.** Select items, click **Review Selected > Export List (CSV)**, and open the file in Excel. **Expect:** the same items and total as the bottom bar, headings in your chosen language, and nothing deleted.
5. **Scheduled cleanup.** In **Settings & Updates**, tick **Also clean Safe items automatically**, choose **Daily** and click **Save**. Then run the task now from **Task Scheduler > Task Scheduler Library > DriveSweepLowDiskReminder > Run**.
   - **Expect:** a "DriveSweep" notification in your chosen language about the space moved to the Recycle Bin, and a **Cleanup (Scheduled)** entry in the Cleanup Log that **Undo Last Cleanup** can reverse.
   - Untick the option and click **Save**. **Expect:** if the low-disk reminder is also off, the task disappears from Task Scheduler.

## 6. Things that must not happen

- No update starts without you clicking **Download & Update vX.Y.Z**.
- With **Check GitHub Releases on startup** turned off (the default), starting DriveSweep makes no request to GitHub.
- An update never offers an older version or a file from anywhere other than this repository's GitHub releases.
- The Recycle Bin is never emptied without the confirmation, and a scheduled run never cleans anything while **Also clean Safe items automatically** is off.

## After testing

- Uninstall the Setup copy and delete `C:\DSTest`.
- Note the results in the release's pull request or an issue, for example: "0.7.1 to 0.7.2: portable pass, folder pass, Setup pass, rollback pass (Windows 11 24H2)".
