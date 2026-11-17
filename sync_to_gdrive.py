#!/usr/bin/env python3
"""
sync_to_gdrive_client.py
========================
Universal Google Drive Synchronizer with Version Control (Client Edition).

Highlights:
- 100% Portable: Copy this single file into ANY folder on your computer.
- One-Time Setup: Configures directly with your own Google / Gmail account via OAuth 2.0.
- Selective Sync: Choose exactly which folders/files to include or exclude.
- In-Place Versions: Edits to existing files create new revisions in Google Drive
  without creating duplicate files, preserving file IDs and share links.
- Multi-Threaded: Fast parallel uploads for projects with many files.

Usage:
    python sync_to_gdrive_client.py                         # Syncs current directory
    python sync_to_gdrive_client.py "D:\\another\\project"    # Syncs a specific directory
    python sync_to_gdrive_client.py --include folderA logs  # Syncs only chosen folders
    python sync_to_gdrive_client.py --exclude data cache    # Skips specified folders
    python sync_to_gdrive_client.py --status                 # Checks sync state without uploading
    python sync_to_gdrive_client.py --dry-run                # Preview what will be uploaded
    python sync_to_gdrive_client.py --whoami                 # View connected Gmail account
    python sync_to_gdrive_client.py --login                  # Connect or switch Google account
    python sync_to_gdrive_client.py --logout                 # Disconnect current Google account
"""

import os
import sys
import json
import time
import fnmatch
import hashlib
import argparse
import socket
import webbrowser
import urllib.parse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

# ---------------------------------------------------------------------------
# Optional: Pre-configured OAuth credentials
# If left empty (None), the script will prompt the user to provide their
# credentials.json or OAuth keys on first run.
# ---------------------------------------------------------------------------
DEFAULT_CLIENT_ID = None
DEFAULT_CLIENT_SECRET = None

# Global config and ignore definitions
CONFIG_DIR = Path.home() / ".gdrive_sync"
DEFAULT_TOKEN_FILE = CONFIG_DIR / "token.json"
OAUTH_SCOPE = "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/userinfo.email"

DEFAULT_IGNORE_DIRS = {
    "__pycache__", ".git", ".idea", ".vscode", ".gemini", ".venv", "venv", "node_modules"
}
DEFAULT_IGNORE_EXTS = {".pyc", ".tmp", ".log.tmp", ".swp"}
DEFAULT_IGNORE_FILES = {
    ".gdrive_manifest.json",
    ".gdrive_ignore",
    ".gdrive_token.json",
    "token.json",
    "credentials.json",
    "client_secret.json",
}


# ===========================================================================
# OAuth 2.0 Local Redirect Handler
# ===========================================================================

class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Temporary local HTTP handler to capture Google's OAuth 2.0 redirect code."""

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logging to keep console clean

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        self.server.auth_code = params.get("code", [None])[0]
        self.server.auth_error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        if self.server.auth_code:
            html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Google Drive Sync - Connected</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
           background: #f1f5f9; color: #1e293b; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
    .card { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); text-align: center; max-width: 440px; }
    .badge { display: inline-block; background: #dcfce7; color: #16a34a; padding: 6px 16px; border-radius: 9999px; font-weight: 700; font-size: 14px; margin-bottom: 16px; }
    h2 { color: #0f172a; margin-top: 0; }
    p { color: #64748b; font-size: 15px; line-height: 1.5; }
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">&#10003; Connected</div>
    <h2>Authentication Successful!</h2>
    <p>Your Google Drive account has been connected successfully.</p>
    <p>You can close this browser tab and return to the terminal.</p>
  </div>
</body>
</html>"""
        else:
            err = self.server.auth_error or "Unknown error"
            html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Google Drive Sync - Authorization Failed</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
           background: #f1f5f9; color: #1e293b; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
    .card {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); text-align: center; max-width: 440px; }}
    h2 {{ color: #dc2626; margin-top: 0; }}
    p {{ color: #64748b; font-size: 15px; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>Authorization Failed</h2>
    <p>Error returned: <strong>{err}</strong></p>
    <p>Please return to your terminal to retry.</p>
  </div>
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))


def find_available_port(preferred_ports=(8085, 8080, 8888, 9090)):
    """Finds an open port on localhost for the OAuth callback."""
    for port in preferred_ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    # Pick any dynamic available port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def extract_auth_code_from_input(text):
    """Extracts authorization code from either raw code or redirected URL."""
    text = text.strip()
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urllib.parse.urlparse(text)
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("code", [None])[0]
        if code:
            return code
    return text


def parse_credentials_file(file_path):
    """Extracts client_id and client_secret from a Google Cloud credentials JSON."""
    file_path = Path(file_path).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Credentials file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "installed" in data:
        cid = data["installed"].get("client_id")
        sec = data["installed"].get("client_secret")
    elif "web" in data:
        cid = data["web"].get("client_id")
        sec = data["web"].get("client_secret")
    else:
        cid = data.get("client_id")
        sec = data.get("client_secret")

    if not cid or not sec:
        raise ValueError(
            "Could not find valid 'client_id' and 'client_secret' inside the JSON file.\n"
            "Ensure you downloaded an OAuth 2.0 Client ID (Application type: Desktop app)."
        )
    return cid, sec


def print_setup_guide():
    """Prints clear instructions on how to create free Google Cloud OAuth credentials."""
    print("""
----------------------------------------------------------------------
HOW TO GET FREE GOOGLE OAUTH CREDENTIALS (Takes ~2 minutes):
----------------------------------------------------------------------
1. Open Google Cloud Console:
   https://console.cloud.google.com/

2. Create a Project:
   - Click the project dropdown at the top -> 'New Project'
   - Enter a name (e.g. 'DriveSync') and click 'Create'.

3. Enable Google Drive API:
   - In the search bar or left menu, go to:
     'APIs & Services' > 'Enabled APIs & services'
   - Click '+ ENABLE APIS AND SERVICES'
   - Search for 'Google Drive API' and click 'Enable'.

4. Configure OAuth Consent Screen:
   - In the left menu, click 'OAuth consent screen'
   - Choose User Type: 'External' and click 'Create'.
   - Fill in App Name (e.g. 'DriveSync') and your User Support Email.
   - Click 'Save and Continue' through Scopes.
   - Under 'Test users', click '+ ADD USERS' and add your own Gmail address!
   - Click 'Save and Continue'.

5. Create Desktop Credentials:
   - In the left menu, click 'Credentials'
   - Click '+ CREATE CREDENTIALS' > 'OAuth client ID'.
   - Application type: Select 'Desktop app'.
   - Name: 'DriveSync Desktop' > Click 'Create'.

6. Download JSON:
   - Click the Download icon next to your client ID (save as credentials.json).
   - Or copy the Client ID and Client Secret.
----------------------------------------------------------------------
""")


def run_interactive_oauth_flow(client_id, client_secret, token_file):
    """Executes the OAuth 2.0 authorization code flow in the user's browser."""
    port = find_available_port()
    redirect_uri = f"http://localhost:{port}"

    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": OAUTH_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(auth_params)}"

    server = HTTPServer(("127.0.0.1", port), _OAuthCallbackHandler)
    server.auth_code = None
    server.auth_error = None
    server.timeout = 1.0

    print("\n" + "=" * 68)
    print("           GOOGLE DRIVE - GMAIL ACCOUNT AUTHORIZATION")
    print("=" * 68)
    print("[*] Opening your web browser to sign in with your Google / Gmail account...")
    print(f"[*] Redirect listener active on: {redirect_uri}")
    print("\nIf your browser does not open automatically, copy and visit this URL:\n")
    print(auth_url)
    print("\n" + "=" * 68)
    print("[*] Waiting for browser authorization (press Ctrl+C to enter code manually)...")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    auth_code = None
    timeout_seconds = 180
    start_time = time.time()

    try:
        while time.time() - start_time < timeout_seconds:
            server.handle_request()
            if server.auth_code or server.auth_error:
                break
        auth_code = server.auth_code
        if server.auth_error:
            raise RuntimeError(f"Google authorization failed: {server.auth_error}")
    except KeyboardInterrupt:
        print("\n[!] Browser wait cancelled.")
    finally:
        server.server_close()

    # Fallback to manual entry if browser callback was missed or blocked
    if not auth_code:
        print("\n[*] Manual Authorization Fallback:")
        print("  1. Visit the URL above and grant access with your Gmail.")
        print("  2. When redirected, copy the full redirected URL (or the 'code' parameter).")
        pasted = input("  Paste the redirect URL or code here: ").strip()
        auth_code = extract_auth_code_from_input(pasted)
        if not auth_code:
            raise ValueError("No authorization code provided. Configuration aborted.")

    print("\n[*] Exchanging authorization code for access tokens...")
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": auth_code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to exchange authorization code: {resp.text}")

    token_data = resp.json()
    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")

    if not refresh_token:
        raise RuntimeError(
            "Google did not return a refresh_token. Please re-run setup and ensure\n"
            "you approve permissions on the consent screen."
        )

    # Fetch user's Gmail address and name
    email = "Unknown"
    display_name = ""
    try:
        user_res = requests.get(
            "https://www.googleapis.com/drive/v3/about?fields=user",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if user_res.status_code == 200:
            u = user_res.json().get("user", {})
            email = u.get("emailAddress", "Unknown")
            display_name = u.get("displayName", "")
    except Exception:
        pass

    token_file = Path(token_file).expanduser().resolve()
    token_file.parent.mkdir(parents=True, exist_ok=True)

    config_record = {
        "email": email,
        "display_name": display_name,
        "client_id": client_id,
        "client_secret": client_secret,
        "token": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": token_data.get("expires_in", 3600),
            "token_type": token_data.get("token_type", "Bearer"),
            "scope": token_data.get("scope", ""),
        },
        "configured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(config_record, f, indent=2)

    print("\n" + "=" * 68)
    print(f"[✔] Successfully authenticated with Google Drive!")
    print(f"    Account:      {display_name} <{email}>")
    print(f"    Config File:  {token_file}")
    print("=" * 68 + "\n")
    return access_token


def configure_account(token_file=DEFAULT_TOKEN_FILE):
    """Guides the client through configuring their Gmail / Google Drive credentials."""
    print("=" * 68)
    print("           GOOGLE DRIVE SYNCHRONIZER - ACCOUNT SETUP")
    print("=" * 68)

    client_id = DEFAULT_CLIENT_ID
    client_secret = DEFAULT_CLIENT_SECRET

    if not client_id or not client_secret:
        # Check if local credentials.json is sitting in current directory
        local_creds = Path("credentials.json")
        if local_creds.exists():
            print(f"[*] Found local '{local_creds}'. Loading credentials...")
            try:
                client_id, client_secret = parse_credentials_file(local_creds)
            except Exception as e:
                print(f"[!] Warning reading local credentials.json: {e}")

    while not client_id or not client_secret:
        print("To sync with your Google Drive, you need Google OAuth 2.0 credentials.\n")
        print("  [1] Provide path to a downloaded 'credentials.json' file")
        print("  [2] Enter OAuth Client ID and Client Secret manually")
        print("  [3] Show step-by-step instructions to get free Google credentials")
        print("  [Q] Quit")

        choice = input("\nSelect an option [1/2/3/Q]: ").strip().lower()

        if choice == "1":
            path_input = input("Enter path to credentials.json: ").strip(' "\'')
            if not path_input:
                continue
            try:
                client_id, client_secret = parse_credentials_file(path_input)
                print("[✔] Successfully parsed credentials from JSON file.")
                break
            except Exception as e:
                print(f"[!] Error: {e}\n")
        elif choice == "2":
            cid = input("Enter Client ID: ").strip(' "\'')
            sec = input("Enter Client Secret: ").strip(' "\'')
            if cid and sec:
                client_id = cid
                client_secret = sec
                break
            print("[!] Both Client ID and Client Secret are required.\n")
        elif choice == "3":
            print_setup_guide()
        elif choice in ("q", "quit", "exit"):
            print("[*] Setup cancelled.")
            sys.exit(0)
        else:
            print("[!] Invalid selection. Please choose 1, 2, 3, or Q.\n")

    return run_interactive_oauth_flow(client_id, client_secret, token_file)


# ===========================================================================
# Token Resolution & Refresh
# ===========================================================================

def locate_token_file(custom_path=None):
    """Finds the active token file (custom path, local override, or global user config)."""
    if custom_path:
        return Path(custom_path).expanduser().resolve()
    # Check local folder overrides first
    for name in (".gdrive_token.json", "token.json"):
        local = Path(name)
        if local.exists():
            return local.resolve()
    # Global default in user profile
    return DEFAULT_TOKEN_FILE.resolve()


def get_access_token(token_file=DEFAULT_TOKEN_FILE):
    """Retrieves an active access token, refreshing or prompting configuration as needed."""
    token_file = locate_token_file(token_file)

    if not token_file.exists():
        print(f"[*] No Google Drive configuration found at:\n    {token_file}")
        return configure_account(token_file)

    try:
        with open(token_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        print("[!] Existing token file was corrupted. Re-configuring...")
        return configure_account(token_file)

    token = data.get("token", {}).get("access_token")

    # Probe token validity
    if token:
        try:
            r = requests.get(
                "https://www.googleapis.com/drive/v3/about?fields=user",
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            if r.status_code == 200:
                return token
        except Exception:
            pass

    # Token expired or invalid -> Refresh using refresh_token
    refresh_token = data.get("token", {}).get("refresh_token")
    client_id = data.get("client_id") or DEFAULT_CLIENT_ID
    client_secret = data.get("client_secret") or DEFAULT_CLIENT_SECRET

    if not refresh_token or not client_id or not client_secret:
        print("[!] Incomplete token credentials. Re-authenticating...")
        return configure_account(token_file)

    try:
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            new_info = resp.json()
            new_token = new_info["access_token"]
            data["token"]["access_token"] = new_token
            data["token"]["expires_in"] = new_info.get("expires_in", 3600)
            with open(token_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return new_token
        else:
            print(f"[!] Token refresh failed (HTTP {resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[!] Token refresh error: {e}")

    print("[*] Session expired or revoked. Please re-authenticate.")
    return configure_account(token_file)


def show_account_info(token_file=DEFAULT_TOKEN_FILE):
    """Displays information about the currently connected Google account."""
    token_file = locate_token_file(token_file)
    if not token_file.exists():
        print("[!] No Google Drive account configured yet.")
        print(f"    Run 'python {Path(__file__).name} --login' to configure your account.")
        return

    try:
        with open(token_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        email = data.get("email", "Unknown")
        name = data.get("display_name", "")
        configured = data.get("configured_at", "Unknown")
        print("=" * 55)
        print("         CONNECTED GOOGLE DRIVE ACCOUNT")
        print("=" * 55)
        if name:
            print(f"  Name:          {name}")
        print(f"  Email:         {email}")
        print(f"  Config File:   {token_file}")
        print(f"  Configured At: {configured}")
        print("=" * 55)
    except Exception as e:
        print(f"[!] Error reading config file: {e}")


def logout_account(token_file=DEFAULT_TOKEN_FILE):
    """Removes the stored token and logs out of Google Drive."""
    token_file = locate_token_file(token_file)
    if token_file.exists():
        try:
            token_file.unlink()
            print(f"[✔] Successfully logged out. Removed configuration at:\n    {token_file}")
        except Exception as e:
            print(f"[!] Error removing config file: {e}")
    else:
        print("[*] No active configuration file found.")


# ===========================================================================
# Project Sync Engine
# ===========================================================================

def load_ignore_file(project_dir):
    """Loads patterns from .gdrive_ignore if it exists in project folder."""
    ignore_file = project_dir / ".gdrive_ignore"
    patterns = []
    if ignore_file.exists():
        with open(ignore_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    return patterns


def should_skip(rel_path, is_dir, includes, excludes, custom_patterns):
    """Determines if a given path should be skipped based on filters and ignores."""
    rel_str = rel_path.as_posix()
    parts = rel_str.split("/")

    # Check default ignores
    for part in parts:
        if part in DEFAULT_IGNORE_DIRS:
            return True

    # If --include is set, only files matching include paths are allowed
    if includes:
        included = False
        for inc in includes:
            inc = inc.replace("\\", "/").strip("/")
            if rel_str == inc or rel_str.startswith(inc + "/") or (is_dir and inc.startswith(rel_str + "/")):
                included = True
                break
        if not included:
            return True

    # Check --exclude
    if excludes:
        for exc in excludes:
            exc = exc.replace("\\", "/").strip("/")
            if rel_str == exc or rel_str.startswith(exc + "/"):
                return True

    # Check custom .gdrive_ignore patterns
    for pat in custom_patterns:
        pat = pat.replace("\\", "/").rstrip("/")
        if fnmatch.fnmatch(rel_str, pat) or fnmatch.fnmatch(rel_path.name, pat):
            return True
        if any(fnmatch.fnmatch(part, pat) for part in parts):
            return True

    return False


def get_or_create_drive_folder(session, name, parent_id=None):
    """Finds an existing folder by name or creates it in Google Drive."""
    clean_name = name.replace("'", "\\'")
    q = f"name = '{clean_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    else:
        q += " and 'root' in parents"

    res = session.get(
        "https://www.googleapis.com/drive/v3/files",
        params={"q": q, "fields": "files(id, name)"},
        timeout=15,
    )
    res.raise_for_status()
    files = res.json().get("files", [])
    if files:
        return files[0]["id"]

    body = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        body["parents"] = [parent_id]
    create_res = session.post(
        "https://www.googleapis.com/drive/v3/files", json=body, timeout=15
    )
    create_res.raise_for_status()
    return create_res.json()["id"]


def get_file_md5(file_path):
    """Computes the MD5 checksum of a local file."""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_new_file(session, file_path, parent_id):
    """Performs multipart upload of a new file to Google Drive."""
    name = file_path.name
    metadata = {"name": name, "parents": [parent_id]}
    with open(file_path, "rb") as f:
        files = {
            "data": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
            "file": (name, f, "application/octet-stream"),
        }
        res = session.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            files=files,
            timeout=60,
        )
    res.raise_for_status()
    return res.json()["id"]


def update_existing_file(session, file_path, file_id):
    """Updates content in-place on Drive, pushing a new revision."""
    with open(file_path, "rb") as f:
        res = session.patch(
            f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media",
            data=f,
            headers={"Content-Type": "application/octet-stream"},
            timeout=60,
        )
    res.raise_for_status()
    return res.json()["id"]


def sync_project(
    project_dir,
    includes=None,
    excludes=None,
    drive_folder_name=None,
    dry_run=False,
    status_only=False,
    token_file=DEFAULT_TOKEN_FILE,
):
    """Core synchronization routine matching original sync behavior."""
    project_dir = Path(project_dir).resolve()
    if not project_dir.is_dir():
        print(f"[!] Target directory does not exist: {project_dir}")
        sys.exit(1)

    # Obtain or refresh token
    token = get_access_token(token_file)
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    # Fetch user email for display
    user_email = ""
    try:
        active_config = locate_token_file(token_file)
        if active_config.exists():
            with open(active_config, "r", encoding="utf-8") as f:
                user_email = json.load(f).get("email", "")
    except Exception:
        pass

    print("==================================================")
    print(f"[*] Google Drive Sync: {project_dir.name}")
    print(f"[*] Local Path:        {project_dir}")
    if user_email:
        print(f"[*] Connected Account: {user_email}")
    if includes:
        print(f"[*] Only Including:    {', '.join(includes)}")
    if excludes:
        print(f"[*] Excluding:         {', '.join(excludes)}")
    print("==================================================")

    manifest_path = project_dir / ".gdrive_manifest.json"
    manifest = {"folders": {}, "files": {}}
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {"folders": {}, "files": {}}

    # Determine Google Drive target root folder
    folder_name = drive_folder_name or manifest.get("drive_folder_name") or project_dir.name
    root_id = manifest.get("root_id")
    if not root_id:
        print(f"[*] Finding or creating Drive folder '{folder_name}'...")
        root_id = get_or_create_drive_folder(session, folder_name)
        manifest["root_id"] = root_id
        manifest["drive_folder_name"] = folder_name
    print(f"[*] Drive Root Folder: {folder_name} (ID: {root_id})")

    custom_patterns = load_ignore_file(project_dir)
    folder_map = manifest.setdefault("folders", {})
    file_map = manifest.setdefault("files", {})

    # 1. Discover local directories
    local_dirs = []
    for root, dirs, _ in os.walk(project_dir):
        dirs[:] = [
            d for d in dirs
            if not should_skip((Path(root) / d).relative_to(project_dir), True, includes, excludes, custom_patterns)
        ]
        for d in dirs:
            dir_full = Path(root) / d
            rel = dir_full.relative_to(project_dir)
            local_dirs.append(rel)

    local_dirs.sort(key=lambda p: len(p.parts))

    # Ensure folders exist in Drive
    if not dry_run and not status_only:
        for rel_dir in local_dirs:
            rel_str = rel_dir.as_posix()
            if rel_str in folder_map:
                continue
            parent_rel = rel_dir.parent.as_posix()
            parent_id = folder_map[parent_rel] if parent_rel != "." else root_id
            folder_id = get_or_create_drive_folder(session, rel_dir.name, parent_id)
            folder_map[rel_str] = folder_id

    # 2. Collect eligible files
    local_files = []
    for root, dirs, files in os.walk(project_dir):
        for f in files:
            p = Path(root) / f
            if p.suffix in DEFAULT_IGNORE_EXTS or p.name in DEFAULT_IGNORE_FILES:
                continue
            rel = p.relative_to(project_dir)
            if should_skip(rel, False, includes, excludes, custom_patterns):
                continue
            local_files.append((p, rel.as_posix()))

    # 3. Classify: upload vs update vs unchanged
    to_upload = []
    to_update = []
    unchanged = 0

    for file_path, rel_str in local_files:
        stat = file_path.stat()
        mtime = stat.st_mtime
        size = stat.st_size

        if rel_str not in file_map:
            parent_rel = Path(rel_str).parent.as_posix()
            parent_id = folder_map.get(parent_rel, root_id) if parent_rel != "." else root_id
            to_upload.append((file_path, rel_str, parent_id))
        else:
            rec = file_map[rel_str]
            if abs(rec.get("mtime", 0) - mtime) > 1.0 or rec.get("size") != size:
                md5 = get_file_md5(file_path)
                if md5 != rec.get("md5"):
                    to_update.append((file_path, rel_str, rec["id"]))
                else:
                    rec["mtime"] = mtime
                    unchanged += 1
            else:
                unchanged += 1

    print(f"\n[*] Status Summary:")
    print(f"    - Total eligible files: {len(local_files)}")
    print(f"    - New to upload:       {len(to_upload)}")
    print(f"    - Modified to update:  {len(to_update)} (will create new revision)")
    print(f"    - Already in sync:     {unchanged}")

    if status_only or dry_run:
        if to_upload:
            print("\n[+] Files to upload:")
            for _, r, _ in to_upload[:15]:
                print(f"    + {r}")
            if len(to_upload) > 15:
                print(f"    ... and {len(to_upload) - 15} more")
        if to_update:
            print("\n[*] Files to update (new revisions):")
            for _, r, _ in to_update[:15]:
                print(f"    ~ {r}")
            if len(to_update) > 15:
                print(f"    ... and {len(to_update) - 15} more")
        return

    if not to_upload and not to_update:
        print("\n[✔] Everything is up to date!")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        return

    # 4. Perform upload/update tasks
    def process_item(item, is_upload):
        fpath, rel, target_id = item
        if is_upload:
            fid = upload_new_file(session, fpath, target_id)
            op = "Uploaded"
        else:
            fid = update_existing_file(session, fpath, target_id)
            op = "Updated (Rev)"
        st = fpath.stat()
        return (op, rel, fid, st.st_mtime, st.st_size, get_file_md5(fpath))

    tasks = [(item, True) for item in to_upload] + [(item, False) for item in to_update]
    completed = 0
    total = len(tasks)

    print(f"\n[*] Syncing {total} items across worker threads...")
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(process_item, item, is_up): item[1] for item, is_up in tasks}
        for fut in as_completed(futures):
            rel_name = futures[fut]
            completed += 1
            try:
                op, rel, fid, mtime, size, md5 = fut.result()
                file_map[rel] = {
                    "id": fid,
                    "mtime": mtime,
                    "size": size,
                    "md5": md5,
                    "last_synced": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                print(f"  [{completed}/{total}] {op}: {rel_name}")
            except Exception as e:
                print(f"  [!] Failed: {rel_name} -> {e}")

            if completed % 20 == 0:
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n[✔] Sync completed successfully for '{project_dir.name}'!")


# ===========================================================================
# CLI Interface
# ===========================================================================

def main():
    script_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description="Universal Google Drive Project Synchronizer (Client Edition)"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=str(script_dir),
        help="Folder to sync (defaults to the folder where this script lives)",
    )
    parser.add_argument(
        "--include",
        nargs="+",
        help="Optional: Only sync specific subfolders (e.g. --include folderA)",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        help="Optional: Exclude specific subfolders (e.g. --exclude logs)",
    )
    parser.add_argument(
        "--name",
        help="Custom Google Drive folder name (defaults to folder name)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check sync status without uploading",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview sync actions without making changes",
    )
    parser.add_argument(
        "--whoami",
        "--account",
        action="store_true",
        help="Display the currently authenticated Google / Gmail account",
    )
    parser.add_argument(
        "--login",
        "--configure",
        action="store_true",
        help="Connect or switch Google / Gmail account",
    )
    parser.add_argument(
        "--logout",
        action="store_true",
        help="Disconnect and remove saved Google credentials",
    )
    parser.add_argument(
        "--token-file",
        help="Optional custom path to store/read the OAuth token JSON",
    )

    args = parser.parse_args()
    token_target = args.token_file or DEFAULT_TOKEN_FILE

    # Command shortcuts
    if args.whoami:
        show_account_info(token_target)
        return

    if args.logout:
        logout_account(token_target)
        return

    if args.login:
        configure_account(token_target)
        return

    # Normal sync execution
    sync_project(
        project_dir=args.path,
        includes=args.include,
        excludes=args.exclude,
        drive_folder_name=args.name,
        dry_run=args.dry_run,
        status_only=args.status,
        token_file=token_target,
    )


if __name__ == "__main__":
    main()
