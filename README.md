# KHAN AUTO REPLY (Telethon personal-account auto reply)

This runs as **your Telegram user account**, not a bot. No BotFather token, no Bot API.

## 1. Environment variables
See `.env.example`. Required: `API_ID`, `API_HASH`, `SESSION`.
Optional: `PAYMENT_NUMBER`, `PAYMENT_PROOF_LINK`, `DB_PATH`, `LOG_LEVEL`.

## 2. Create the SESSION string (once, on your own computer)
    pip install telethon
    python generate_session.py
Log in with your phone number and code. Paste the printed string into the `SESSION` variable on your host.

## 3. Hosting as a persistent background worker
Deploy as a **worker / background process**, not a web service (there is no HTTP server).
- Start command: `python main.py` (the `Procfile` has `worker: python main.py`)
- Build command: `pip install -r requirements.txt`
- Python 3.9 or newer (3.11+ recommended)
- Set `DB_PATH` to a file on a **persistent volume**, e.g. mount a volume at `/data` and use `DB_PATH=/data/khan_auto_reply.db`.
  - Railway: add a Volume, mount path `/data`, service type with no public port.
  - Render: Background Worker + Persistent Disk (paid plan), mount path `/data`.
  - Fly.io: `fly volumes create` and mount at `/data`, run as a process without `[http_service]`.
  - VPS: any directory that survives reboots; run under systemd or Docker with restart policy `always`.

## 4. Storage requirements
The database stores per-user state (last welcome time, pause time, selected group). It is tiny (a few MB even for tens of thousands of users) but **must live on persistent storage**. If the disk is wiped on each deploy/restart, every customer will receive a new welcome message and manual-reply pauses are forgotten. Normal restarts do not lose data when `DB_PATH` is on a persistent volume. Back up the `.db` file occasionally (WAL mode also creates `-wal` and `-shm` files next to it; stop the app before copying, or copy all three).

## 5. Limitations (please read)
- **Run exactly one instance.** Using the same SESSION from two places (two containers, a deploy overlap, or your laptop) can cause Telegram to revoke the session (`AuthKeyDuplicatedError`). Configure your host for "stop old before starting new" and 1 replica.
- **Free tiers that sleep or have ephemeral disks are not suitable.**
- **Messages sent while the app is offline are not answered afterwards.** Telethon with a StringSession does not persist update state, so there is no catch-up on restart. Only messages received while connected are handled.
- **Manual-reply detection** treats any message you send in a private chat (from any device) that was not sent by this program as manual, and pauses that person for 24 hours. Service events (e.g. disappearing-message timer changes) are ignored. Replying in Saved Messages or to bots does nothing.
- **Telegram's rules.** Automating a personal account is a grey area. Telegram may limit or ban accounts that message many people who did not write first, so this program only replies to people who message you first. Avoid spam-like volumes.
- **Security.** The SESSION string gives full access to your account. Store it only in your host's secret/env settings and revoke it (Telegram > Settings > Devices) if it leaks.
- **Silent on unrelated text.** Only numbers, confirmation words (after selecting a group) and first contact / 24h cycle are answered. Invalid numbers (e.g. 0, 10) get a short reply at most once per minute per person.
- The Telegram connection auto-reconnects; if it fails repeatedly the app retries with backoff up to 5 minutes. Revoked/invalid sessions stop the app with a clear log line.
