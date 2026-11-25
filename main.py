#!/usr/bin/env python3
"""
KHAN AUTO REPLY - Telegram PERSONAL ACCOUNT auto reply (Telethon userbot).

This is NOT a Telegram Bot. It logs into your own account with a Telethon
StringSession and replies on your behalf in private chats.

Required environment variables:
    API_ID, API_HASH, SESSION
Optional environment variables:
    PAYMENT_NUMBER, PAYMENT_PROOF_LINK, DB_PATH, LOG_LEVEL
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import signal
import sqlite3
import sys
import threading
import time
import unicodedata
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from telethon import TelegramClient, errors, events
from telethon.sessions import StringSession

# ==========================================================
# CONFIGURATION (credentials only come from the environment)
# ==========================================================


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.stderr.write(f"FATAL: missing required environment variable {name}\n")
        sys.exit(2)
    return value


try:
    API_ID = int(require_env("API_ID"))
except ValueError:
    sys.stderr.write("FATAL: API_ID must be a number\n")
    sys.exit(2)

API_HASH = require_env("API_HASH")
SESSION = require_env("SESSION")

PAYMENT_PROOF_LINK = os.getenv("PAYMENT_PROOF_LINK", "").strip()
PAYMENT_NUMBER = os.getenv("PAYMENT_NUMBER", "").strip()

# Put this on a persistent disk/volume in production, e.g. /data/khan_auto_reply.db
DB_PATH = os.getenv("DB_PATH", "khan_auto_reply.db").strip() or "khan_auto_reply.db"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

WELCOME_COOLDOWN = timedelta(hours=24)
MANUAL_PAUSE = timedelta(hours=24)
AUTO_ID_TTL_SECONDS = 600          # how long we remember our own automatic message IDs
INVALID_REPLY_COOLDOWN = 60        # seconds between "invalid number" replies per user
TELEGRAM_SERVICE_ID = 777000

# ==========================================================
# PREMIUM GROUP LIST - change names and prices whenever you want
# (keys must stay "1" ... "9")
# ==========================================================

GROUPS = {
    "1": {"name": "Premium Group 01", "price": 0},
    "2": {"name": "Premium Group 02", "price": 0},
    "3": {"name": "Premium Group 03", "price": 0},
    "4": {"name": "Premium Group 04", "price": 0},
    "5": {"name": "Premium Group 05", "price": 0},
    "6": {"name": "Premium Group 06", "price": 0},
    "7": {"name": "Premium Group 07", "price": 0},
    "8": {"name": "Premium Group 08", "price": 0},
    "9": {"name": "Premium Group 09", "price": 0},
}

# ==========================================================
# LOGGING (never log secrets or message contents)
# ==========================================================

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.getLogger("telethon").setLevel(logging.WARNING)
logger = logging.getLogger("KHAN_AUTO_REPLY")

# ==========================================================
# TEXT HELPERS
# ==========================================================

_BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def normalize(text: Optional[str]) -> str:
    """Lower-case, convert Bengali digits to ASCII, collapse spaces, trim punctuation."""
    value = unicodedata.normalize("NFKC", text or "")
    value = value.translate(_BENGALI_DIGITS).lower()
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip(" .,!?।~-_:;\"'")


YES_WORDS = {
    normalize(word)
    for word in (
        "হ্যাঁ", "হ্যা", "হ্যাঁ ভাই", "হ্যাঁ জি", "হা", "হাঁ",
        "জি", "জি হ্যাঁ", "জি ভাই",
        "নিতে চাই", "কিনতে চাই", "কিনবো", "কিনব",
        "yes", "y", "yeah", "yep", "yup", "ok", "okay", "sure", "confirm",
    )
}

# ==========================================================
# MESSAGES
# ==========================================================


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def format_price(price: int) -> str:
    return f"{price} টাকা" if price > 0 else "দাম এখনো নির্ধারণ করা হয়নি"


def create_welcome() -> str:
    group_list = "\n".join(
        f"✦ <b>{esc(number)}. {esc(group['name'])}</b>"
        for number, group in GROUPS.items()
    )

    if PAYMENT_PROOF_LINK.startswith("https://"):
        safe_url = html.escape(PAYMENT_PROOF_LINK, quote=True)
        proof = f'<a href="{safe_url}">Payment Proof Group</a>'
    else:
        proof = "Payment Proof Link এখনো যুক্ত করা হয়নি।"

    return f"""
<b>✦ WELCOME TO KHAN ✦</b>

আসসালামু আলাইকুম! ❤️

আমাদের সঙ্গে যোগাযোগ করার জন্য ধন্যবাদ।

আপনি কি আমাদের <b>PREMIUM GROUP</b>
কিনতে আগ্রহী?

আপনার সুবিধার জন্য নিচে আমাদের
Premium Group-এর তালিকা দেওয়া হলো।

<b>✦ PREMIUM GROUP LIST ✦</b>

{group_list}

গ্রুপের বিস্তারিত জানতে ১ থেকে ৯ এর মধ্যে
যেকোনো একটি নম্বর লিখে পাঠান।

<b>💳 PAYMENT PROOF</b>

পেমেন্ট সংক্রান্ত প্রমাণ দেখতে
আমাদের Payment Proof Group-এ ভিজিট করুন।

{proof}

কোনো কিছু জানার থাকলে মেসেজ করুন।
আমরা আপনাকে সহযোগিতা করব।

<b>THANK YOU ❤️</b>
""".strip()


def create_group_details(number: str, group: dict) -> str:
    return f"""
<b>✦ GROUP DETAILS ✦</b>

আপনি <b>{esc(number)} নম্বর</b> গ্রুপটি নির্বাচন করেছেন।

📌 গ্রুপের নাম: <b>{esc(group['name'])}</b>

💰 মূল্য: <b>{esc(format_price(group['price']))}</b>

আপনি কি এই গ্রুপটি কিনতে আগ্রহী?

কিনতে চাইলে <b>হ্যাঁ</b> লিখুন।
""".strip()


def create_order_info(group: dict) -> str:
    if group["price"] <= 0:
        return f"""
আপনি <b>{esc(group['name'])}</b> নির্বাচন করেছেন।

এই গ্রুপের মূল্য এখনো নির্ধারণ করা হয়নি।
মূল্য জানতে আমাদের সঙ্গে যোগাযোগ করুন।
""".strip()

    if PAYMENT_NUMBER:
        payment = f"\n💳 পেমেন্ট নম্বর: <b>{esc(PAYMENT_NUMBER)}</b>"
    else:
        payment = "\nপেমেন্ট নম্বর জানতে আমাদের সঙ্গে যোগাযোগ করুন।"

    return f"""
<b>✦ ORDER INFORMATION ✦</b>

আপনার নির্বাচিত গ্রুপ:
<b>{esc(group['name'])}</b>

💰 মূল্য: <b>{esc(group['price'])} টাকা</b>
{payment}

পেমেন্ট করার আগে তথ্য যাচাই করে নিন।
পেমেন্ট সম্পন্ন হলে জানাবেন।
""".strip()


INVALID_NUMBER_MESSAGE = (
    "দুঃখিত, এই নম্বরটি সঠিক নয়।\n"
    "অনুগ্রহ করে <b>১ থেকে ৯</b> এর মধ্যে একটি নম্বর লিখুন।"
)

# ==========================================================
# DATABASE (SQLite, WAL, explicit transactions, thread lock)
# ==========================================================


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass
class UserState:
    user_id: int
    last_welcome: Optional[datetime]
    paused_until: Optional[datetime]
    selected_group: Optional[str]
    awaiting_confirmation: bool


class Database:
    ALLOWED_FIELDS = (
        "last_welcome",
        "paused_until",
        "selected_group",
        "awaiting_confirmation",
    )

    def __init__(self, path: str):
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            path,
            timeout=30,
            isolation_level=None,        # we manage transactions explicitly
            check_same_thread=False,     # guarded by self._lock
        )
        self._conn.row_factory = sqlite3.Row

        mode = self._conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            logger.warning("SQLite WAL mode unavailable (journal_mode=%s)", mode)
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA busy_timeout=30000")

        with self._tx() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    last_welcome TEXT,
                    paused_until TEXT,
                    selected_group TEXT,
                    awaiting_confirmation INTEGER DEFAULT 0
                )
                """
            )
        logger.info("Database ready")

    @contextmanager
    def _tx(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def get_user(self, user_id: int) -> Optional[UserState]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT user_id, last_welcome, paused_until,
                       selected_group, awaiting_confirmation
                FROM users WHERE user_id=?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return UserState(
            user_id=row["user_id"],
            last_welcome=parse_dt(row["last_welcome"]),
            paused_until=parse_dt(row["paused_until"]),
            selected_group=row["selected_group"],
            awaiting_confirmation=bool(row["awaiting_confirmation"]),
        )

    def update_user(self, user_id: int, **values) -> None:
        """Create the row if needed and update the given fields atomically."""
        fields = {k: v for k, v in values.items() if k in self.ALLOWED_FIELDS}
        with self._tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)
            )
            if fields:
                # Column names come from the fixed whitelist above, never from input.
                assignments = ", ".join(f"{name}=?" for name in fields)
                conn.execute(
                    f"UPDATE users SET {assignments} WHERE user_id=?",
                    (*fields.values(), user_id),
                )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                logger.exception("Error closing database")


async def run_db(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


# ==========================================================
# GLOBAL RUNTIME STATE
# ==========================================================

client: Optional[TelegramClient] = None
db: Optional[Database] = None
my_id: Optional[int] = None

# One asyncio lock per chat: serialises all processing for the same person,
# which prevents duplicate welcome messages and manual/auto races.
_user_locks: "weakref.WeakValueDictionary[int, asyncio.Lock]" = (
    weakref.WeakValueDictionary()
)


def lock_for(chat_id: int) -> asyncio.Lock:
    lock = _user_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[chat_id] = lock
    return lock


class AutoMessageRegistry:
    """Remembers (chat_id, message_id) of messages WE sent automatically."""

    def __init__(self, ttl: float):
        self._ttl = ttl
        self._items: dict[tuple[int, int], float] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        for key in [k for k, exp in self._items.items() if exp < now]:
            self._items.pop(key, None)

    def add(self, chat_id: int, message_id: int) -> None:
        self._prune()
        self._items[(chat_id, message_id)] = time.monotonic() + self._ttl

    def contains(self, chat_id: int, message_id: int) -> bool:
        self._prune()
        return (chat_id, message_id) in self._items


auto_registry = AutoMessageRegistry(AUTO_ID_TTL_SECONDS)
_last_invalid_reply: dict[int, float] = {}


# ==========================================================
# SENDING
# ==========================================================


async def send_auto(chat_id: int, message: str) -> bool:
    """Send an automatic HTML message. Returns True on success, never raises."""
    assert client is not None
    for attempt in (1, 2):
        try:
            sent = await client.send_message(
                chat_id, message, parse_mode="html", link_preview=False
            )
            auto_registry.add(chat_id, sent.id)
            return True
        except errors.FloodWaitError as exc:
            wait = int(getattr(exc, "seconds", 30))
            logger.warning("FloodWait %ss while sending to %s", wait, chat_id)
            if attempt == 1 and wait <= 120:
                await asyncio.sleep(wait + 1)
                continue
            return False
        except errors.PeerFloodError:
            logger.error("PeerFloodError: Telegram is limiting this account's messaging")
            return False
        except (
            errors.UserIsBlockedError,
            errors.InputUserDeactivatedError,
            errors.UserPrivacyRestrictedError,
        ) as exc:
            logger.warning("Cannot message %s: %s", chat_id, type(exc).__name__)
            return False
        except (ConnectionError, asyncio.TimeoutError, errors.RPCError) as exc:
            logger.warning("Send to %s failed: %s", chat_id, type(exc).__name__)
            return False
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected error sending to %s", chat_id)
            return False
    return False


# ==========================================================
# CORE LOGIC (always called while holding lock_for(user_id))
# ==========================================================


async def send_welcome(user_id: int, previous: Optional[UserState], now: datetime) -> None:
    # Claim the welcome in the DB BEFORE sending so a crash/restart cannot duplicate it.
    await run_db(
        db.update_user,
        user_id,
        last_welcome=now.isoformat(),
        paused_until=None,
        selected_group=None,
        awaiting_confirmation=0,
    )
    if await send_auto(user_id, create_welcome()):
        logger.info("Welcome sent to user %s", user_id)
        return

    # Sending failed: roll the claim back so the next message retries.
    await run_db(
        db.update_user,
        user_id,
        last_welcome=previous.last_welcome.isoformat()
        if previous and previous.last_welcome
        else None,
    )


async def process_incoming(user_id: int, text: str) -> None:
    now = utcnow()
    state = await run_db(db.get_user, user_id)

    # 1) Manual-reply pause is checked FIRST, so a paused user never gets a welcome.
    if state and state.paused_until:
        if now < state.paused_until:
            logger.debug("User %s is paused, ignoring message", user_id)
            return
        await run_db(db.update_user, user_id, paused_until=None)
        state.paused_until = None

    # 2) First contact, or the 24-hour welcome cooldown has passed.
    if state is None or state.last_welcome is None or (
        now - state.last_welcome >= WELCOME_COOLDOWN
    ):
        await send_welcome(user_id, state, now)
        return

    # 3) Nothing to do for empty (media-only) messages.
    cleaned = normalize(text)
    if not cleaned:
        return

    # 4) Group number selection (ASCII or Bengali digits).
    if re.fullmatch(r"\d{1,6}", cleaned):
        key = str(int(cleaned))
        group = GROUPS.get(key)

        if group is None:
            mono = time.monotonic()
            last_invalid = _last_invalid_reply.get(user_id)
            if last_invalid is None or mono - last_invalid >= INVALID_REPLY_COOLDOWN:
                if len(_last_invalid_reply) > 2000:
                    _last_invalid_reply.clear()
                _last_invalid_reply[user_id] = mono
                await send_auto(user_id, INVALID_NUMBER_MESSAGE)
            return

        if await send_auto(user_id, create_group_details(key, group)):
            await run_db(
                db.update_user,
                user_id,
                selected_group=key,
                awaiting_confirmation=1,
            )
            logger.info("User %s selected group %s", user_id, key)
        return

    # 5) Purchase confirmation.
    if (
        state.awaiting_confirmation
        and state.selected_group
        and cleaned in YES_WORDS
    ):
        group = GROUPS.get(state.selected_group)
        if group is None:
            await run_db(db.update_user, user_id, selected_group=None, awaiting_confirmation=0)
            return

        if await send_auto(user_id, create_order_info(group)):
            await run_db(db.update_user, user_id, awaiting_confirmation=0)
            logger.info("Order info sent to user %s", user_id)
        return

    # 6) Anything else: stay silent (it is probably a normal conversation).
    logger.debug("Unmatched message from %s ignored", user_id)


# ==========================================================
# TELETHON EVENT HANDLERS
# ==========================================================


async def on_incoming(event) -> None:
    try:
        if not event.is_private:
            return
        if getattr(event.message, "action", None) is not None:
            return  # service message

        user_id = event.sender_id
        if user_id is None or user_id == my_id or user_id == TELEGRAM_SERVICE_ID:
            return

        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False) or getattr(sender, "deleted", False):
            return

        async with lock_for(user_id):
            await process_incoming(user_id, event.raw_text or "")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Error while handling incoming message")


async def on_outgoing(event) -> None:
    try:
        if not event.is_private:
            return
        if getattr(event.message, "action", None) is not None:
            return  # service message, not a manual reply

        chat_id = event.chat_id
        if chat_id is None or chat_id == my_id or chat_id == TELEGRAM_SERVICE_ID:
            return

        # Waiting for the per-chat lock guarantees that if our own automatic
        # send is still in flight, its message ID is registered before we look.
        async with lock_for(chat_id):
            if auto_registry.contains(chat_id, event.id):
                return  # our own automatic message

            try:
                chat = await event.get_chat()
            except Exception:
                chat = None
            if chat is None or getattr(chat, "bot", False) or getattr(chat, "is_self", False):
                return

            pause_until = utcnow() + MANUAL_PAUSE
            await run_db(
                db.update_user,
                chat_id,
                paused_until=pause_until.isoformat(),
                selected_group=None,
                awaiting_confirmation=0,
            )
            logger.info("Manual reply detected: paused user %s for 24 hours", chat_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Error while handling outgoing message")


# ==========================================================
# APPLICATION LIFECYCLE
# ==========================================================

FATAL_ERROR_NAMES = (
    "AuthKeyDuplicatedError",
    "AuthKeyUnregisteredError",
    "SessionRevokedError",
    "SessionExpiredError",
    "UserDeactivatedError",
    "UserDeactivatedBanError",
)
FATAL_ERRORS = tuple(
    getattr(errors, name) for name in FATAL_ERROR_NAMES if hasattr(errors, name)
)


async def run() -> int:
    global client, db, my_id

    db = Database(DB_PATH)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # not supported on this platform

    client = TelegramClient(
        StringSession(SESSION),
        API_ID,
        API_HASH,
        connection_retries=10,
        retry_delay=3,
        auto_reconnect=True,
        request_retries=5,
        flood_sleep_threshold=60,
    )
    client.add_event_handler(on_outgoing, events.NewMessage(outgoing=True))
    client.add_event_handler(on_incoming, events.NewMessage(incoming=True))

    logger.info("KHAN AUTO REPLY STARTING")
    exit_code = 0
    delay = 5

    try:
        while not stop.is_set():
            try:
                await client.connect()

                if not await client.is_user_authorized():
                    logger.critical(
                        "SESSION is not authorized. Generate a new session string "
                        "(see generate_session.py) and update the SESSION variable."
                    )
                    exit_code = 2
                    break

                me = await client.get_me()
                my_id = me.id
                logger.info("Connected. Account ID: %s", my_id)
                logger.info("KHAN AUTO REPLY IS RUNNING")
                delay = 5

                disconnected = asyncio.ensure_future(client.run_until_disconnected())
                stopper = asyncio.ensure_future(stop.wait())
                done, _ = await asyncio.wait(
                    {disconnected, stopper}, return_when=asyncio.FIRST_COMPLETED
                )

                if stopper in done:
                    logger.info("Shutdown requested")
                    await client.disconnect()
                    try:
                        await asyncio.wait_for(disconnected, timeout=10)
                    except Exception:
                        pass
                    break

                stopper.cancel()
                disconnected.result()  # re-raises if the connection task failed
                logger.warning("Disconnected from Telegram, reconnecting")

            except asyncio.CancelledError:
                raise
            except FATAL_ERRORS as exc:
                logger.critical(
                    "Fatal session error (%s). Do not run the same session in two "
                    "places at once; create a new SESSION if it was revoked.",
                    type(exc).__name__,
                )
                exit_code = 3
                break
            except Exception as exc:
                logger.error("Connection error (%s). Retrying in %ss", type(exc).__name__, delay)
                logger.debug("Connection error details", exc_info=True)

            if stop.is_set():
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, 300)
    finally:
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:
            logger.debug("Error during disconnect", exc_info=True)
        db.close()
        logger.info("KHAN AUTO REPLY STOPPED")

    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
