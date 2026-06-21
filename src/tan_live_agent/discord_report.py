"""Discord alert sender for the watchdog.

Uses a webhook URL (preferred) or a bot token + channel id. If neither is set,
alerts degrade silently to stdout so the watchdog still runs.
"""
from __future__ import annotations

import os

import httpx


def send_alert(webhook_url: str, content: str, *, username: str = "TAN Watchdog") -> None:
    """POST a message to a Discord webhook. Raises on non-2xx."""
    if not webhook_url:
        print(content)
        return
    # Discord caps message length at 2000; chunk defensively.
    payload = {"username": username, "content": content[:1900]}
    r = httpx.post(webhook_url, json=payload, timeout=10)
    r.raise_for_status()


def send_via_bot(bot_token: str, channel_id: str, content: str) -> None:
    """Fallback: send via bot token + channel id."""
    if not bot_token or not channel_id:
        print(content)
        return
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    r = httpx.post(
        url,
        headers={"Authorization": f"Bot {bot_token}"},
        data={"content": content[:1900]},
        timeout=10,
    )
    r.raise_for_status()
