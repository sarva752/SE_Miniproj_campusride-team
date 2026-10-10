"""In-app chat between a rider and a driver who share a booking.

Covers CRS-F-040..044 and the chat rate limit of CRS-SR-006 (30 messages/minute/user).
"""
from __future__ import annotations

import html
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .errors import PermissionDenied, ValidationError
from .models import Booking, BookingStatus

MAX_LENGTH = 1000
READ_ONLY_AFTER = timedelta(hours=24)
RATE_LIMIT = 30
RATE_WINDOW = timedelta(minutes=1)


class RateLimited(Exception):
    """Too many messages (maps to HTTP 429)."""


@dataclass
class Message:
    id: int
    booking_id: str
    sender_id: str
    content: str
    sent_at: datetime
    read_at: Optional[datetime] = None


class ChatService:
    def __init__(self):
        self._messages: dict[str, list[Message]] = defaultdict(list)
        self._blocks: set[tuple[str, str]] = set()  # (blocker, blocked)
        self._recent: dict[str, deque] = defaultdict(deque)
        self.reports: list[tuple[str, str, str]] = []  # (reporter, target, reason)
        self._seq = 0

    # CRS-F-042
    def block(self, blocker: str, blocked: str) -> None:
        self._blocks.add((blocker, blocked))

    def is_blocked(self, a: str, b: str) -> bool:
        return (a, b) in self._blocks or (b, a) in self._blocks

    def blocked_pairs(self) -> set:
        """Pairs usable by the matching engine's ``blocked`` argument."""
        return set(self._blocks)

    def report(self, reporter: str, target: str, reason: str) -> None:
        if not (reason or "").strip():
            raise ValidationError("A reason is required")
        self.reports.append((reporter, target, reason.strip()))

    @staticmethod
    def _partner(booking: Booking, user_id: str) -> str:
        if user_id == booking.rider_id:
            return booking.driver_id
        if user_id == booking.driver_id:
            return booking.rider_id
        raise PermissionDenied("You are not part of this booking")  # CRS-F-040

    def _open_for_chat(self, booking: Booking, now: datetime) -> bool:
        if booking.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.STARTED):
            return True
        if booking.status in (BookingStatus.COMPLETED, BookingStatus.CANCELLED) and booking.ended_at:
            return now - booking.ended_at <= READ_ONLY_AFTER  # CRS-F-043
        return False

    def _check_rate(self, user_id: str, now: datetime) -> None:
        q = self._recent[user_id]
        while q and now - q[0] >= RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            raise RateLimited("Too many messages")
        q.append(now)

    # CRS-F-040, 041, 042, 044
    def send(self, booking: Booking, sender_id: str, content: str, now: datetime) -> Message:
        partner = self._partner(booking, sender_id)
        if self.is_blocked(sender_id, partner):
            raise PermissionDenied("Messaging is blocked between these users")
        if not self._open_for_chat(booking, now):
            raise PermissionDenied("This chat is read-only")
        text = (content or "").strip()
        if not text:
            raise ValidationError("Message cannot be empty")
        if len(text) > MAX_LENGTH:
            raise ValidationError(f"Message exceeds {MAX_LENGTH} characters")
        self._check_rate(sender_id, now)
        self._seq += 1
        msg = Message(self._seq, booking.id, sender_id, html.escape(text), now)  # sanitised before storage
        self._messages[booking.id].append(msg)
        return msg

    def history(self, booking: Booking, user_id: str) -> list:
        self._partner(booking, user_id)
        return list(self._messages[booking.id])

    def mark_read(self, booking: Booking, reader_id: str, now: datetime) -> int:
        self._partner(booking, reader_id)
        n = 0
        for m in self._messages[booking.id]:
            if m.sender_id != reader_id and m.read_at is None:
                m.read_at = now
                n += 1
        return n
