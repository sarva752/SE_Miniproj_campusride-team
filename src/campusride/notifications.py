"""Event notifications, channel preferences and departure reminders (CRS-F-060..062)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

CHANNELS = ("in_app", "email", "push")
EVENTS = {
    "match_found", "join_request_received", "request_accepted", "request_rejected",
    "booking_cancelled", "new_message", "rating_reminder", "departure_reminder",
    "account_locked", "password_reset",
}
SECURITY_EVENTS = {"account_locked", "password_reset"}  # always sent (CRS-F-062)
REMINDER_LEAD = timedelta(minutes=30)
REMINDER_TOLERANCE = timedelta(minutes=1)


@dataclass
class Notification:
    user_id: str
    event: str
    channel: str
    payload: dict
    created_at: datetime


@dataclass
class Preferences:
    channels: dict = field(default_factory=lambda: {"in_app": True, "email": True, "push": False})
    muted_events: set = field(default_factory=set)


class NotificationService:
    def __init__(self):
        self.prefs: dict[str, Preferences] = {}
        self.outbox: list[Notification] = []

    def set_channel(self, user_id: str, channel: str, enabled: bool) -> None:
        if channel not in CHANNELS:
            raise ValueError(f"Unknown channel: {channel}")
        self.prefs.setdefault(user_id, Preferences()).channels[channel] = enabled

    def mute_event(self, user_id: str, event: str, muted: bool = True) -> None:
        p = self.prefs.setdefault(user_id, Preferences())
        (p.muted_events.add if muted else p.muted_events.discard)(event)

    def notify(self, user_id: str, event: str, payload: dict, now: datetime) -> list:
        """Create one notification per enabled channel; security notices ignore preferences."""
        if event not in EVENTS:
            raise ValueError(f"Unknown event: {event}")
        p = self.prefs.get(user_id, Preferences())
        critical = event in SECURITY_EVENTS
        if event in p.muted_events and not critical:
            return []
        channels = [c for c in CHANNELS if p.channels.get(c)] if not critical else ["in_app", "email"]
        made = [Notification(user_id, event, c, dict(payload), now) for c in channels]
        self.outbox.extend(made)
        return made

    def due_departure_reminders(self, rides: Iterable, now: datetime) -> list:
        """CRS-F-061: user ids for rides departing 30 minutes (+/- 1 minute) from ``now``.

        ``rides`` yields (departure, [user_ids]).
        """
        due = []
        for departure, users in rides:
            if abs((departure - now) - REMINDER_LEAD) <= REMINDER_TOLERANCE:
                due.extend(users)
        return due
