# PCD Build

Build the PCD-customised ActivityWatch distribution for macOS or Windows, then reset the user config so the first run triggers the email setup dialog.

## Steps

1. Ask the user which environment to build for if not provided in the arguments: `local`, `dev`, `qa`, or `prod`. Default is `prod`.

2. Ask the user which platform to build for if not specified: `macos`, `windows`, or `both`.

3. Resolve `PCD_APP_SECRET` in this order:
   - Already set in the shell environment → use it.
   - A `.env` file exists in the project root → source it with `set -a; source .env; set +a` and use the value from there.
   - Neither → ask the user to enter it interactively. Warn them not to commit it to git.

   If `.env` does not exist yet and the user provides the secret interactively, offer to write it to `.env` for future builds. Make sure `.env` is in `.gitignore`.

4. Run `make build` to compile all Python submodules. If it fails, report the error and stop.

5. Run the PyInstaller bundle command with the chosen secret and environment:
   ```
   PCD_APP_SECRET=<secret> PCD_ENV=<env> venv/bin/pyinstaller --clean --noconfirm aw.spec
   ```

6. **macOS only:** Run `make dist/ActivityWatch.dmg` to produce the installer. Then rename the DMG to include the environment name:
   ```
   mv dist/ActivityWatch.dmg dist/ActivityWatch-<env>.dmg
   ```
   Report the final path.

7. **Windows only:** The EXE is already placed in `dist/` by PyInstaller. Rename it to include the environment:
   ```
   move dist\ActivityWatch\ActivityWatch.exe dist\ActivityWatch-<env>.exe
   ```
   (Run this via PowerShell or cmd — use the Bash tool with the appropriate shell.)

8. Remove the user config file to ensure the first run of the new build prompts for the PCD email:
   ```
   rm -f ~/.pcd_sync_config.json
   ```
   Also remove the sync state file so the first sync starts fresh:
   ```
   rm -f ~/.pcd_sync_state.json
   ```

9. Report a summary: environment, platform, output file path, and confirmation that the config was reset.

## Arguments

The user can pass arguments directly, e.g.:
- `/pcd-build dev macos` — build dev DMG for macOS
- `/pcd-build prod windows` — build prod EXE for Windows
- `/pcd-build qa both` — build QA for both platforms
- `/pcd-build` — interactive, prompt for all values
