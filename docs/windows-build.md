# Windows Build Guide — PCD ActivityWatch

## Prerequisites (install once)

1. **Python 3.9** — https://www.python.org/downloads/release/python-3916/
   - During install: check **Add Python to PATH**

2. **Git** — https://git-scm.com/download/win

3. **Node.js 18+** — https://nodejs.org

4. **Make** — install via Chocolatey:
   ```bat
   choco install make
   ```
   Chocolatey installer: https://chocolatey.org/install

5. **Inno Setup 6** (optional — for producing a single `.exe` installer) — https://jrsoftware.org/isdl.php

---

## Step 1 — Get the code

### First build on this machine — clone fresh
```bat
git clone --recursive https://github.com/Zeeshan138063/ActivityWatch.git
cd ActivityWatch
git submodule update --init --recursive
```

### Already have the repo — pull the latest
```bat
cd ActivityWatch
git checkout master
git pull origin master
git submodule update --init --recursive
```

> ⚠️ The UI lives in nested submodules (`aw-server` → `aw-webui`). If you skip
> `git submodule update --init --recursive`, the build will use the OLD UI even
> though `master` is up to date.

---

## Step 2 — Create virtual environment

```bat
python -m venv venv
venv\Scripts\activate
pip install setuptools==69.0.0 poetry==1.4.2
```

---

## Step 3 — Build

```bat
set PCD_APP_SECRET=<secret>
make build
```

> Replace `<secret>` with the actual `PCD_APP_SECRET` value. Keep it secure — do not commit it.

---

## Step 4 — PyInstaller bundle

```bat
set PCD_APP_SECRET=<secret>
venv\Scripts\pyinstaller --clean --noconfirm aw.spec
```

Output: `dist\ActivityWatch\ActivityWatch.exe`

---

## Step 5 — Optional: Windows installer (.exe setup)

```bat
set AW_VERSION=v0.14.0b3
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" scripts\package\activitywatch-setup.iss
```

Output: `dist\ActivityWatch-Setup.exe`

---

## Step 6 — Reset config

```bat
del %USERPROFILE%\.pcd_sync_config.json
del %USERPROFILE%\.pcd_sync_state.json
```

---

## Step 7 — Upload to GitHub release

```bat
gh auth login
gh release upload v0.14.0b3 dist\ActivityWatch-Setup.exe --repo Zeeshan138063/ActivityWatch
```

---

## Step 8 — Verify the build

After launching `ActivityWatch.exe`, confirm the latest fixes are present:

- **UI:** open `http://localhost:5600` → **PCD Admin** is the first nav item, and
  the environment defaults to **Prod** (`https://api.prescribingcaredirect.co.uk`).
- **No console flashing:** the black PowerShell window must NOT pop up every ~30s
  (fixed via `CREATE_NO_WINDOW` on the VPN check).
- **VPN notifications:** toggle the VPN off/on → a Windows toast appears
  ("Tracking paused / resumed"). Allow notifications if Windows prompts on first launch.

If the UI still looks old, you almost certainly skipped
`git submodule update --init --recursive` in Step 1 — re-run it and rebuild.

---

## Notes

- The `PCD_APP_SECRET` must match the value used in the macOS build so users have the same admin password on both platforms.
- The app defaults to **Prod** (`https://api.prescribingcaredirect.co.uk`) on fresh install. Users can change the environment via PCD Admin after login.
- To upgrade: always quit ActivityWatch via the tray icon before installing a new build.
- Notification permission: on first launch Windows may prompt to allow notifications — click **Allow**.
