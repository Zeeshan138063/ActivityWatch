#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("pcd_sync_client")

# ---------------------------------------------------------------------------
# Build-time configuration
# Set PCD_APP_SECRET before running pyinstaller — one value per environment.
# End users never see or configure this; it's compiled into the binary.
# ---------------------------------------------------------------------------
APP_SECRET = os.environ.get("PCD_APP_SECRET", "ACTIVITYWATCH_APP_SECRET")


# Known environments → base URLs (no trailing slash)
ENVIRONMENTS = {
    "local": "http://127.0.0.1:8005",
    "dev":   "https://api.dev.prescribingcaredirect.co.uk",
    "qa":    "https://api.qa.prescribingcaredirect.co.uk",
    "prod":  "https://api.qa.prescribingcaredirect.co.uk",
}
ACTIVITY_SYNC_PATH  = "/api/core/v1/activity-sync"
USER_VALIDATE_PATH  = "/api/users/verify-email"
ADMIN_VERIFY_PATH   = "/api/users/admin/verify"
UPDATE_EMAIL_PATH   = "/api/users/update-activity-email"
DEFAULT_ENV = "prod"

AW_SERVER_URL = "http://localhost:{port}/api/0"
STATE_FILE_PATH = os.path.join(os.path.expanduser("~"), ".pcd_sync_state.json")
USER_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".pcd_sync_config.json")

# Only these bucket prefixes are synced — pattern: <watcher-name>_<hostname>
WATCHED_BUCKET_PREFIXES = ("aw-watcher-window_", "aw-watcher-afk_")

# Backoff: doubles on each consecutive failure, capped at this many seconds
MAX_BACKOFF_SECS = 600  # 10 minutes


def parse_args():
    parser = argparse.ArgumentParser(
        description="Continuously sync ActivityWatch data to the PCD remote API."
    )
    # --env / --base-url / --aw-port / --interval are internal IT/build options,
    # not shown to end users. --setup is for first-time machine registration.
    parser.add_argument(
        "--env",
        choices=list(ENVIRONMENTS.keys()),  # local / dev / qa / prod
        default=os.environ.get("PCD_ENV", DEFAULT_ENV),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PCD_BASE_URL"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--aw-port",
        type=int,
        default=int(os.environ.get("AW_PORT", 5600)),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("PCD_SYNC_INTERVAL", 60)),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Re-run first-time setup (change your registered email).",
    )
    # aw-qt passes --testing when launched in test mode
    parser.add_argument("--testing", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


# ---------------------------------------------------------------------------
# User config  (~/.pcd_sync_config.json)
# Stores: pcd_user_email
# ---------------------------------------------------------------------------

def load_user_config() -> dict:
    if os.path.exists(USER_CONFIG_PATH):
        try:
            with open(USER_CONFIG_PATH) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read user config: {e}")
    return {}


def save_user_config(updates: dict) -> None:
    config = load_user_config()
    config.update(updates)
    try:
        with open(USER_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save user config: {e}")


# ---------------------------------------------------------------------------
# Email setup dialog
# ---------------------------------------------------------------------------

def validate_pcd_email(base_url: str, email: str) -> tuple[bool, str]:
    """
    Ask the PCD API whether this email belongs to a valid user.
    Returns (is_valid, error_message).
    On network / timeout errors we return (True, "") so startup is never blocked.
    """
    url = base_url + USER_VALIDATE_PATH
    try:
        res = requests.post(
            url,
            json={"email": email},
            headers=_auth_headers(),
            timeout=10,
        )
        if res.status_code == 200:
            return True, ""
        if res.status_code == 404:
            return False, f"No PCD account found for '{email}'. Please check and try again."
        try:
            detail = res.json().get("detail") or res.json().get("message") or ""
        except Exception:
            detail = ""
        return False, detail or f"Validation failed (HTTP {res.status_code}). Please try again."
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        logger.warning("PCD API unreachable during email validation — skipping check.")
        return True, ""
    except Exception as e:
        logger.warning(f"Email validation error: {e} — skipping check.")
        return True, ""


def verify_admin_credentials(base_url: str, username: str, password: str) -> tuple[bool, str]:
    """Authenticate an admin user against the PCD backend."""
    url = base_url + ADMIN_VERIFY_PATH
    try:
        res = requests.post(
            url,
            json={"username": username, "password": password},
            headers=_auth_headers(),
            timeout=10,
        )
        if res.status_code == 200:
            return True, ""
        if res.status_code in (401, 403):
            return False, "Invalid admin credentials."
        try:
            detail = res.json().get("detail") or res.json().get("message") or ""
        except Exception:
            detail = ""
        return False, detail or f"Admin verify failed (HTTP {res.status_code})."
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return False, "Cannot reach PCD API. Check your connection."
    except Exception as e:
        return False, f"Unexpected error: {e}"


def update_activity_email(base_url: str, existing_email: str, new_email: str) -> tuple[bool, str]:
    """Update the activity-sync email via the PCD backend, then update local config."""
    url = base_url + UPDATE_EMAIL_PATH
    try:
        res = requests.post(
            url,
            json={"existing_email": existing_email, "new_email": new_email},
            headers=_auth_headers(),
            timeout=10,
        )
        if res.status_code == 200:
            save_user_config({"pcd_user_email": new_email})
            logger.info(f"[admin] Activity email updated: {existing_email} → {new_email}")
            return True, ""
        if res.status_code == 404:
            return False, f"No PCD account found for '{existing_email}'."
        try:
            detail = res.json().get("detail") or res.json().get("message") or ""
        except Exception:
            detail = ""
        return False, detail or f"Update failed (HTTP {res.status_code})."
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return False, "Cannot reach PCD API. Check your connection."
    except Exception as e:
        return False, f"Unexpected error: {e}"


def _show_email_dialog(error_message: str | None = None) -> str | None:
    """
    Show a native email-input dialog.
    macOS  → osascript (works correctly in dark mode)
    Others → custom tkinter dialog with explicit light colours
    Falls back gracefully when no display is available.
    """
    if sys.platform == "darwin":
        return _show_email_dialog_macos(error_message)
    return _show_email_dialog_tkinter(error_message)


def _show_email_dialog_macos(error_message: str | None = None) -> str | None:
    """Native macOS dialog via osascript — renders correctly in light and dark mode."""
    prompt = (
        "Enter your PCD user email address.\\n\\n"
        "This links your computer to your PCD account.\\n"
        "You will only be asked once."
    )
    if error_message:
        prompt = f"{error_message}\\n\\n{prompt}"

    script = (
        f'display dialog "{prompt}" '
        f'default answer "" '
        f'with title "PCD Activity Sync — Setup" '
        f'buttons {{"Cancel", "OK"}} '
        f'default button "OK"'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return None  # user cancelled
        for part in result.stdout.strip().split(", "):
            if part.startswith("text returned:"):
                value = part[len("text returned:"):].strip()
                return value or None
        return None
    except Exception as e:
        logger.warning(f"osascript failed ({e}), falling back to tkinter.")
        return _show_email_dialog_tkinter(error_message)


def _show_email_dialog_tkinter(error_message: str | None = None) -> str | None:
    """Custom tkinter dialog with explicit colours — avoids dark-mode rendering issues."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        if error_message:
            messagebox.showerror(
                title="PCD Activity Sync",
                message=error_message,
                parent=root,
            )

        dialog = tk.Toplevel(root)
        dialog.title("PCD Activity Sync — Setup")
        dialog.configure(bg="#f0f0f0")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)

        tk.Label(
            dialog,
            text=(
                "Enter your PCD user email address.\n\n"
                "This links your computer's activity data\n"
                "to your PCD account. Asked only once."
            ),
            bg="#f0f0f0", fg="#000000",
            font=("Helvetica", 13),
            padx=20, pady=12,
        ).pack()

        entry_var = tk.StringVar()
        entry = tk.Entry(
            dialog, textvariable=entry_var, width=36,
            font=("Helvetica", 13), bg="white", fg="black",
            insertbackground="black",
        )
        entry.pack(padx=20, pady=(0, 10))
        entry.focus_set()

        result: list[str | None] = [None]

        def on_ok():
            result[0] = entry_var.get().strip() or None
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg="#f0f0f0")
        btn_frame.pack(pady=(0, 15))
        tk.Button(btn_frame, text="Cancel", command=on_cancel, width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="OK", command=on_ok, width=10, default=tk.ACTIVE).pack(side=tk.LEFT, padx=5)

        dialog.bind("<Return>", lambda _: on_ok())
        dialog.bind("<Escape>", lambda _: on_cancel())

        # centre on screen
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - dialog.winfo_reqwidth()) // 2
        y = (dialog.winfo_screenheight() - dialog.winfo_reqheight()) // 3
        dialog.geometry(f"+{x}+{y}")

        root.wait_window(dialog)
        root.destroy()
        return result[0]
    except Exception as e:
        logger.warning(f"GUI dialog unavailable ({e}). Run with --setup from a terminal.")
        return None


def prompt_and_save_email(base_url: str) -> str | None:
    """
    Dialog loop: show input → validate against PCD API → show error and retry.
    Saves to config on success. Returns the validated email or None if cancelled.
    """
    error_message = None
    while True:
        email = _show_email_dialog(error_message)
        if not email:
            logger.warning("No PCD email provided. Sync will run without user mapping.")
            return None

        if "@" not in email or "." not in email.split("@")[-1]:
            error_message = f"'{email}' is not a valid email address. Please try again."
            continue

        is_valid, api_error = validate_pcd_email(base_url, email)
        if is_valid:
            save_user_config({"pcd_user_email": email})
            logger.info(f"PCD user email saved: {email}")
            return email

        error_message = api_error


def resolve_pcd_email(base_url: str) -> str | None:
    """
    Resolve PCD email in priority order:
      1. Saved ~/.pcd_sync_config.json
      2. First-run GUI dialog → validates against PCD API → saves on success
    """
    saved = load_user_config().get("pcd_user_email")
    if saved:
        return saved
    logger.info("No PCD user email found. Showing setup dialog...")
    return prompt_and_save_email(base_url)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def _auth_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if APP_SECRET:
        headers["Authorization"] = f"Bearer {APP_SECRET}"
    return headers


def load_state() -> dict:
    if os.path.exists(STATE_FILE_PATH):
        try:
            with open(STATE_FILE_PATH) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read state file: {e}. Starting fresh.")
    return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE_PATH, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state file: {e}")


def fetch_buckets(aw_url: str) -> dict | None:
    try:
        res = requests.get(f"{aw_url}/buckets/", timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        logger.warning(f"Failed to connect to local aw-server: {e}")
        return None


def fetch_new_events(aw_url: str, bucket_id: str, start_time: str | None) -> list:
    params: dict = {"limit": -1}
    if start_time:
        params["start"] = start_time
    try:
        res = requests.get(
            f"{aw_url}/buckets/{bucket_id}/events", params=params, timeout=10
        )
        res.raise_for_status()
        return res.json()
    except Exception as e:
        logger.warning(f"Failed to fetch events for bucket {bucket_id}: {e}")
        return []


def sync_once(api_url: str, aw_url: str, pcd_user_email: str | None) -> bool:
    """Run one sync pass. Returns True if successful (or nothing to push)."""
    buckets = fetch_buckets(aw_url)
    if not buckets:
        logger.warning("aw-server unreachable, skipping this sync cycle.")
        return False

    hostname = socket.gethostname()
    os_username = getpass.getuser()
    state = load_state()

    sync_data = {
        "hostname": hostname,
        "os_username": os_username,
        "pcd_user_email": pcd_user_email,
        "sync_timestamp": datetime.now(timezone.utc).isoformat(),
        "buckets": {},
    }

    new_state = dict(state)
    has_new_events = False

    for bucket_id, bucket_info in buckets.items():
        if not any(bucket_id.startswith(p) for p in WATCHED_BUCKET_PREFIXES):
            continue

        b_type = bucket_info.get("type")
        last_sync = state.get(bucket_id)
        if not last_sync:
            last_sync = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        logger.debug(f"Fetching events for {bucket_id} since {last_sync}")
        events = fetch_new_events(aw_url, bucket_id, last_sync)

        if bucket_id.startswith("aw-watcher-afk_"):
            events = [e for e in events if e.get("data", {}).get("status") == "afk"]

        if events:
            events.sort(key=lambda x: x["timestamp"])
            sync_data["buckets"][bucket_id] = {
                "type": b_type,
                "client": bucket_info.get("client"),
                "events": events,
            }
            new_state[bucket_id] = events[-1]["timestamp"]
            has_new_events = True
            logger.info(f"Found {len(events)} new events for {bucket_id}")
        else:
            logger.debug(f"No new events for {bucket_id}")

    if not has_new_events:
        logger.debug("No new activity data this cycle.")
        return True

    logger.info(f"Posting payload to {api_url} ...")
    try:
        response = requests.post(api_url, json=sync_data, headers=_auth_headers(), timeout=30)
        response.raise_for_status()
        save_state(new_state)
        logger.info("Sync complete.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to post data to PCD API: {e}")
        return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    base_url = (args.base_url or ENVIRONMENTS[args.env]).rstrip("/")
    api_url = base_url + ACTIVITY_SYNC_PATH
    aw_url = AW_SERVER_URL.format(port=args.aw_port)

    if args.setup:
        prompt_and_save_email(base_url)
        sys.exit(0)

    pcd_user_email = resolve_pcd_email(base_url)

    if pcd_user_email:
        logger.info(f"PCD user email  : {pcd_user_email}")
    else:
        logger.warning("No PCD user email configured — syncing without user mapping.")

    logger.info(f"PCD sync started | env={args.base_url or args.env} | interval={args.interval}s")
    logger.info(f"PCD API URL : {api_url}")
    logger.info(f"AW server   : {aw_url}")

    shutdown_event = threading.Event()

    def _handle_signal(signum, _frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    consecutive_failures = 0

    while not shutdown_event.is_set():
        try:
            success = sync_once(api_url, aw_url, pcd_user_email)
        except Exception:
            logger.exception("Unexpected error during sync")
            success = False

        if success:
            consecutive_failures = 0
            wait_secs = args.interval
        else:
            consecutive_failures += 1
            wait_secs = min(args.interval * (2 ** (consecutive_failures - 1)), MAX_BACKOFF_SECS)
            logger.warning(
                f"Sync failed {consecutive_failures} time(s) in a row. "
                f"Retrying in {wait_secs}s."
            )

        shutdown_event.wait(wait_secs)

    logger.info("PCD sync stopped.")


if __name__ == "__main__":
    main()
