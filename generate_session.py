#!/usr/bin/env python3
"""Run this ON YOUR OWN COMPUTER once to create a SESSION string.

Usage:
    pip install telethon
    API_ID=123456 API_HASH=xxxx python generate_session.py

Treat the printed string like a password: anyone who has it can control
your Telegram account. Never share it or commit it to Git.
"""
import os

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(os.environ.get("API_ID") or input("API_ID: ").strip())
api_hash = os.environ.get("API_HASH") or input("API_HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as tg:
    print("\nYour SESSION string (keep it secret):\n")
    print(tg.session.save())
