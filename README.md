# iina-mal-scrobbler

[![CI](https://github.com/Abdulaziz-kiran/iina-mal-scrobbler/actions/workflows/ci.yml/badge.svg)](https://github.com/Abdulaziz-kiran/iina-mal-scrobbler/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey.svg)](https://apple.com/macos)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://python.org)

An ultra-lightweight, zero-daemon, open-source MyAnimeList (MAL) scrobbler for **IINA** and **mpv** on macOS.

---

## Highlights

- **Zero Background Daemon:** No 24/7 background agents, menu-bar apps, or launchd processes. It runs only when IINA/mpv opens a video and terminates when playback ends.
- **Zero External Runtime Dependencies:** Powered entirely by standard macOS tools (`urllib`, `sqlite3`, `security` Keychain, `re`).
- **Asynchronous & Non-Blocking:** Video playback never freezes during network requests or authentication checks.
- **Deterministic Filename Parser:** Robust layered parsing for standard fansub releases (`[SubsPlease]`, `[Erai-raws]`, SxxExx, absolute numbering). Never invents episode numbers.
- **Ambiguity Guard:** Prevents accidentally updating the wrong anime when multiple titles are close matches.
- **Monotonic Progress Protection:** Never downgrades watched progress if an older episode is replayed.
- **macOS Keychain Security:** Access and refresh tokens are securely stored in the macOS Keychain—never in plaintext files.
- **Offline Resilient:** Network failures are automatically queued in SQLite and retried opportunistically.
- **Built-in Diagnostic Tool:** Run `mal-scrobbler doctor` anytime to verify your system setup.

---

## Architecture

```text
IINA / mpv
    ↓ (file-loaded, percent-pos >= 80%)
Lua Script (scripts/mal_scrobbler.lua)
    ↓ (asynchronous subprocess)
mal-scrobbler CLI
    ├── 1. Filename Parser (deterministic layered stripping)
    ├── 2. Title Cache & Idempotency Check (SQLite)
    ├── 3. MAL Search & Ambiguity Resolver
    ├── 4. Token Refresh & Keychain Integration (OAuth 2.0 PKCE)
    └── 5. Update Status (PUT /v2/anime/{id}/my_list_status)
    ↓ (JSON result)
Lua OSD Notification (e.g. "✓ MAL: Frieren (Ep. 5) updated!")
```

---

## Installation

### 1. Clone & Run the Installer

Open your terminal and run:

```bash
git clone https://github.com/Abdulaziz-kiran/iina-mal-scrobbler.git
cd iina-mal-scrobbler
./install.sh
```

The installer will:
1. Verify macOS and Python 3.9+.
2. Install core application files to `~/.local/share/mal-scrobbler`.
3. Create the `mal-scrobbler` CLI launcher in `~/.local/bin`.
4. Install the Lua script to `~/.config/mpv/scripts/mal_scrobbler.lua`.
5. Run the diagnostic `doctor` command.

*Note: If `~/.local/bin` is not in your PATH, add it by adding `export PATH="$HOME/.local/bin:$PATH"` to your `~/.zshrc`.*

---

### 2. Configure IINA

To allow IINA to load custom mpv scripts:

1. Open **IINA** and navigate to **Preferences** (`Cmd + ,`).
2. Select the **Advanced** tab.
3. Check the box for **"Use config directory"**.
4. Set the path to `~/.config/mpv`.

![IINA Config Directory](https://raw.githubusercontent.com/iina/iina/master/iina/Assets.xcassets/AppIcon.appiconset/icon_128x128.png)

---

### 3. Connect Your MyAnimeList Account

#### Step A: Obtain a Free MAL API Client ID
1. Log in to [MyAnimeList](https://myanimelist.net/).
2. Go to **Settings** &rarr; **API** (or visit [myanimelist.net/apiconfig](https://myanimelist.net/apiconfig)).
3. Click **Create ID** and fill out the details:
   - **App Name:** `iina-mal-scrobbler`
   - **App Type:** `web`
   - **App Redirect URL:** `http://localhost:8484/callback`
   - **Description:** `Personal media player scrobbler`
4. Copy your generated **Client ID**.

#### Step B: Configure and Log In
In your terminal, set your Client ID and log in:

```bash
# 1. Set your Client ID
mal-scrobbler config set-client-id <YOUR_CLIENT_ID>

# 2. Log in (opens your browser for OAuth 2.0 PKCE authentication)
mal-scrobbler auth login
```

Tokens are automatically saved into your encrypted macOS Keychain.

---

## Usage

Just watch your anime!

When you reach **80%** of an episode in IINA or mpv, an On-Screen Display (OSD) notification will appear in the player:

- `✓ MAL: Sousou no Frieren (Ep. 5) updated!`
- `✓ MAL: Sousou no Frieren (Ep. 5 already synced)`
- `⏳ MAL offline: Progress queued for sync`
- `⚠ MAL: Ambiguous anime title match`

---

## CLI Reference

You can also use the `mal-scrobbler` CLI directly:

```bash
# Run diagnostics
mal-scrobbler doctor

# Test filename parsing without modifying MAL
mal-scrobbler parse --file "[SubsPlease] Sousou no Frieren - 05 (1080p).mkv"

# Manually scrobble a file
mal-scrobbler scrobble --file "/path/to/video.mkv"

# Retry any pending offline scrobbles
mal-scrobbler retry-pending

# Check authentication status
mal-scrobbler auth status

# Refresh access token
mal-scrobbler auth refresh

# Log out and remove Keychain credentials
mal-scrobbler auth logout
```

---

## Uninstallation

To cleanly remove `iina-mal-scrobbler`:

```bash
./uninstall.sh
```

To also remove configuration files, database history, and logs:

```bash
./uninstall.sh --purge
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
