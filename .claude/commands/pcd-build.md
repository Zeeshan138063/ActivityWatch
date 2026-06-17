# PCD Build

Build the PCD-customised ActivityWatch distribution for macOS or Windows.

The build is environment-agnostic — no environment is baked in at compile time. The user configures the target environment (dev / qa / prod / local) after installation via the PCD Admin panel in the ActivityWatch UI.

## Steps

1. Ask the user which platform to build for if not specified: `macos`, `windows`, or `both`.

2. Resolve `PCD_APP_SECRET` in this order:
   - Already set in the shell environment → use it.
   - A `.env` file exists in the project root → source it with `set -a; source .env; set +a` and use the value from there.
   - Neither → ask the user to enter it interactively. Warn them not to commit it to git.

   If `.env` does not exist yet and the user provides the secret interactively, offer to write it to `.env` for future builds. Make sure `.env` is in `.gitignore`.

3. Run `make build` to compile all Python submodules. If it fails, report the error and stop.

4. Run the PyInstaller bundle command with only the secret (no `PCD_ENV`):
   ```
   PCD_APP_SECRET=<secret> venv/bin/pyinstaller --clean --noconfirm aw.spec
   ```

5. **macOS only:** Run `make dist/ActivityWatch.dmg` to produce the installer. Report the final path `dist/ActivityWatch.dmg`.

6. **Windows only:** PyInstaller cannot cross-compile — the Windows EXE must be built on a Windows machine. Print the following instructions clearly for the user and stop (do not attempt to run these locally):

   ```powershell
   # 1. Clone the repo (master already has all PCD changes)
   git clone https://github.com/Zeeshan138063/ActivityWatch.git
   cd ActivityWatch

   # 2. Pull all submodules (aw-server, aw-webui, aw-qt PCD forks)
   git submodule update --init --recursive

   # 3. Create and activate virtual environment
   python -m venv venv
   .\venv\Scripts\activate

   # 4. Build all submodules
   pip install setuptools
   make build

   # 5. Bundle with PyInstaller
   $env:PCD_APP_SECRET = "ACTIVITYWATCH_APP_SECRET"
   .\venv\Scripts\pyinstaller --clean --noconfirm aw.spec
   ```

   Output: `dist\ActivityWatch\ActivityWatch.exe`

7. Remove the user config file to ensure the first run prompts for the PCD email:
   ```
   rm -f ~/.pcd_sync_config.json
   ```
   Also remove the sync state file so the first sync starts fresh:
   ```
   rm -f ~/.pcd_sync_state.json
   ```

8. Report a summary: platform, output file path, and confirmation that the config was reset.
   Remind the user that the environment (dev / qa / prod) is configured post-install via the PCD Admin panel at `http://localhost:5600/#/pcd-admin`.

## Arguments

The user can pass arguments directly, e.g.:
- `/pcd-build macos` — build DMG for macOS
- `/pcd-build windows` — build EXE for Windows
- `/pcd-build both` — build for both platforms
- `/pcd-build` — interactive, prompt for platform
