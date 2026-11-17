<div align="center">

# ⚡ GDrive Folder Sync
### *Universal, Multi-Threaded Google Drive Synchronizer with Version Control*

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Google Drive](https://img.shields.io/badge/Google%20Drive-API%20v3-4285F4?style=for-the-badge&logo=googledrive&logoColor=white)](https://developers.google.com/drive)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=for-the-badge)](#)
[![Code Style](https://img.shields.io/badge/Design-Zero%20Bloat%20%E2%80%A2%20Portable-success?style=for-the-badge)](#)

<p align="center">
  <b>Drop this single script into ANY project folder on your machine and sync instantly to Google Drive.</b><br>
  <i>In-place file revisions, multi-threaded parallel uploads, automatic browser OAuth2 authentication, and incremental MD5 change detection.</i>
</p>

---

[Key Highlights](#-key-highlights) •
[Quick Start](#-quick-start) •
[Authentication Flow](#-one-time-authentication) •
[Usage & Commands](#-command-line-reference) •
[Ignore Rules](#-custom-ignore-rules) •
[Comparison](#-why-not-the-official-client)

---

</div>

<br>

## 🚀 Key Highlights

<table>
<tr>
<td width="50%">

### 📦 100% Portable & Self-Contained
Copy the script into **any** folder on your PC. Running it automatically syncs that exact directory tree to Google Drive. No complex installation or background daemons.

</td>
<td width="50%">

### 🔄 In-Place Version History
Modified files update directly on Google Drive as **new revisions** without generating messy duplicate copies (`file (1).txt`). Preserves original file IDs and sharing URLs.

</td>
</tr>
<tr>
<td width="50%">

### ⚡ Multi-Threaded Engine
Leverages concurrent worker threads (`ThreadPoolExecutor`) for lightning-fast uploads across directories with hundreds or thousands of files.

</td>
<td width="50%">

### 🔑 Frictionless OAuth 2.0
Prompts user once to connect their Gmail account via their default web browser. Tokens refresh automatically in the background without user intervention.

</td>
</tr>
<tr>
<td width="50%">

### 🛡️ Smart Ignore & Delta Hashing
Uses MD5 checksums and modification timestamps to upload only changed files. Respects `.gdrive_ignore` and built-in rules for caches, `.git`, `.venv`, and node modules.

</td>
<td width="50%">

### 🌐 Cross-Platform
Runs identically on **Windows**, **macOS**, and **Linux** with zero platform-specific dependencies beyond the lightweight `requests` library.

</td>
</tr>
</table>

---

## 🏗️ How It Works

```text
 ┌─────────────────────────────────────────────────────────┐
 │               Your Local Project Directory              │
 └────────────────────────────┬────────────────────────────┘
                              │
                    [1] Recursive Scan
                              │
                 ┌────────────▼────────────┐
                 │ .gdrive_ignore Check    │ ───► Skipped (.git, .venv, etc.)
                 └────────────┬────────────┘
                              │
                 ┌────────────▼────────────┐
                 │ MD5 & Timestamp Delta   │ ───► Unchanged Files Ignored
                 └────────────┬────────────┘
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
       [New Local Files]            [Modified Local Files]
               │                             │
    Multipart Upload (Drive v3)     PATCH /files/{id}?uploadType=media
               │                             │
               ▼                             ▼
        New Drive File               New Revision In-Place
               │                             │
               └──────────────┬──────────────┘
                              ▼
                 Update .gdrive_manifest.json
```

---

## ⚡ Quick Start

### 1. Clone or Download

Download `sync_to_gdrive.py` and place it in the folder you want to sync:

```bash
# Clone the repository
git clone https://github.com/passiontrader/gdrive-folder-sync.git
cd gdrive-folder-sync

# Install the single dependency
pip install -r requirements.txt
```

> **Requirements:** Python 3.8+ and `requests>=2.25.0`.

### 2. Run the Sync

```bash
python sync_to_gdrive.py
```

*That's it!* On the first run, the script opens your browser to link your Google account. Subsequent runs sync your files instantly.

---

## 🔐 One-Time Authentication

When you run the tool for the first time, it walks you through a clean 30-second setup:

```text
====================================================================
           GOOGLE DRIVE SYNCHRONIZER - ACCOUNT SETUP
====================================================================
To sync with your Google Drive, you need Google OAuth 2.0 credentials.

  [1] Provide path to a downloaded 'credentials.json' file
  [2] Enter OAuth Client ID and Client Secret manually
  [3] Show step-by-step instructions to get free Google credentials
  [Q] Quit

Select an option [1/2/3/Q]:
```

### 🎯 Getting Free Google Cloud Credentials (2 Minutes)

<details>
<summary><b>Click to expand step-by-step visual walkthrough</b></summary>

1. **Open Google Cloud Console:**
   Go to [console.cloud.google.com](https://console.cloud.google.com/) and create a project (e.g., `DriveSync`).
2. **Enable Google Drive API:**
   Navigate to **APIs & Services** $\rightarrow$ **Library** $\rightarrow$ Search for **Google Drive API** $\rightarrow$ Click **Enable**.
3. **Configure Consent Screen:**
   Go to **OAuth consent screen** $\rightarrow$ Select **External** $\rightarrow$ Fill in your app name and email $\rightarrow$ Under **Test Users**, add your Gmail address.
4. **Create Credentials:**
   Go to **Credentials** $\rightarrow$ **Create Credentials** $\rightarrow$ **OAuth client ID** $\rightarrow$ Application type: **Desktop app**.
5. **Done!** Download the `credentials.json` or paste your Client ID & Secret into the prompt.

</details>

Your token is safely stored in `~/.gdrive_sync/token.json`. You only authenticate **once** on your machine!

---

## 💻 Command-Line Reference

### 🛠️ Common Operations

```bash
# Sync the folder where the script is located
python sync_to_gdrive.py

# Sync a specific project folder
python sync_to_gdrive.py "C:\Projects\my-app"

# Preview planned actions without uploading anything
python sync_to_gdrive.py --dry-run

# Check status of local vs Google Drive files
python sync_to_gdrive.py --status

# Custom remote folder name on Google Drive
python sync_to_gdrive.py --name "Production_Backup_2026"
```

### 🎯 Selective Syncing

```bash
# Sync only specific subfolders
python sync_to_gdrive.py --include src assets config

# Exclude specific heavy subfolders
python sync_to_gdrive.py --exclude datasets logs temp
```

### 👤 Account Management

```bash
# View the currently authenticated Gmail user
python sync_to_gdrive.py --whoami

# Connect or switch to another Google / Gmail account
python sync_to_gdrive.py --login

# Disconnect and safely remove saved credentials
python sync_to_gdrive.py --logout
```

---

## 📋 Full Options Table

| Flag | Argument | Description |
| :--- | :--- | :--- |
| `path` | `[string]` *(optional)* | Folder to sync (defaults to script's current directory). |
| `--include` | `folder1 folder2 ...` | Only sync matching files or directories. |
| `--exclude` | `folder1 folder2 ...` | Exclude matching files or directories from sync. |
| `--name` | `folder_name` | Set custom root folder name in Google Drive. |
| `--status` | *None* | Audit sync status without uploading. |
| `--dry-run` | *None* | Simulate upload process and preview actions. |
| `--whoami` | *None* | Print connected Gmail username and email. |
| `--login` | *None* | Re-run OAuth setup to switch accounts. |
| `--logout` | *None* | Unlink account and wipe local tokens. |
| `--token-file` | `path/to/token.json` | Specify a custom token storage file path. |

---

## 🛡️ Custom Ignore Rules (`.gdrive_ignore`)

Just like `.gitignore`, you can place a `.gdrive_ignore` file in your root folder:

```gitignore
# Ignore heavy test outputs
test_output/
*.dump

# Ignore secrets & environment configs
*.env
secrets/

# Ignore media files
*.mp4
*.mkv
```

### Built-in Default Ignores:
The engine automatically skips build artifacts and sensitive credentials:
- **Directories:** `__pycache__`, `.git`, `.idea`, `.vscode`, `.gemini`, `.venv`, `venv`, `node_modules`
- **Extensions:** `.pyc`, `.tmp`, `.log.tmp`, `.swp`
- **Secrets:** `credentials.json`, `token.json`, `client_secret*.json`, `.gdrive_manifest.json`

---

## 🥊 Why Not the Official Google Drive Client?

| Feature | Official GDrive Client | ⚡ GDrive Folder Sync |
| :--- | :---: | :---: |
| **Zero Background Memory** | ❌ Always running in background | ✅ **Runs on-demand, exits when done** |
| **Single-Script Portability** | ❌ Full installer required | ✅ **Copy 1 file anywhere** |
| **In-Place File Revisions** | ⚠️ Can cause sync conflict copies | ✅ **Native Drive v3 revisions** |
| **Custom Filter Rules** | ❌ Limited folder exclusions | ✅ **Full `.gdrive_ignore` + CLI flags** |
| **Virtual Environments / Git** | ❌ Syncs garbage `.git` / `node_modules` | ✅ **Built-in developer ignores** |
| **Multi-Threaded Burst Upload** | ⚠️ Throttled background daemon | ✅ **6 Parallel worker threads** |

---

## 🔒 Security & Privacy

- **Direct Connection:** Communication happens strictly between your machine and official Google API servers (`googleapis.com`).
- **No Third-Party Relays:** Zero telemetry, zero intermediaries, zero analytics.
- **Local Credentials:** OAuth tokens and refresh keys are stored strictly on your local machine (`~/.gdrive_sync/token.json`).

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.

<div align="center">
  <sub>Built with ❤️ for developers and teams who want frictionless Google Drive synchronization.</sub>
</div>
