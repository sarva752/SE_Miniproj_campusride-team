"""Ratings and ride history (CRS-F-050..053)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .errors import ConflictError, NotFound, PermissionDenied, ValidationError
from .models import Booking, BookingStatus

RATING_WINDOW = timedelta(days=7)
MAX_COMMENT = 300
MIN_RATINGS_TO_SHOW = 3


@dataclass(frozen=True)  # frozen: ratings cannot be edited after submission (CRS-F-053)
class Rating:
    id: int
    booking_id: str
    rater_id: str
    ratee_id: str
    stars: int
    comment: str
    created_at: datetime


class RatingService:
    def __init__(self):
        self._ratings: list[Rating] = []
        self.flagged: list[tuple[int, str]] = []  # (rating_id, flagged_by)

    # CRS-F-051
    def submit(self, booking: Booking, rater_id: str, stars: int, comment: str, now: datetime) -> Rating:
        if rater_id not in (booking.rider_id, booking.driver_id):
            raise PermissionDenied("Only ride participants can rate")
        if booking.status is not BookingStatus.COMPLETED or booking.ended_at is None:
            raise ConflictError("The ride is not completed")
        if now - booking.ended_at > RATING_WINDOW:
            raise ConflictError("The 7-day rating window has closed")
        if isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= 5:
            raise ValidationError("Stars must be a whole number from 1 to 5")
        comment = (comment or "").strip()
        if len(comment) > MAX_COMMENT:
            raise ValidationError("Comment is too long (max 300 characters)")
        if any(r.booking_id == booking.id and r.rater_id == rater_id for r in self._ratings):
            raise ConflictError("You have already rated this ride")
        ratee = booking.driver_id if rater_id == booking.rider_id else booking.rider_id
        rating = Rating(len(self._ratings) + 1, booking.id, rater_id, ratee, stars, comment, now)
        self._ratings.append(rating)
        return rating

    # CRS-F-052
    def average(self, user_id: str) -> tuple:
        mine = [r.stars for r in self._ratings if r.ratee_id == user_id]
        if not mine:
            return None, 0
        return round(sum(mine) / len(mine), 2), len(mine)

    def display_label(self, user_id: str) -> str:
        avg, count = self.average(user_id)
        if count < MIN_RATINGS_TO_SHOW:
            return "New"
        return f"{avg:.1f} ({count})"

    def ratings_map(self) -> dict:
        """Average rating per user for the matching engine (only users with enough ratings)."""
        users = {r.ratee_id for r in self._ratings}
        out = {}
        for u in users:
            avg, count = self.average(u)
            if count >= MIN_RATINGS_TO_SHOW:
                out[u] = avg
        return out

    # CRS-F-053
    def flag_comment(self, rating_id: int, flagged_by: str) -> None:
        if not any(r.id == rating_id for r in self._ratings):
            raise NotFound("Rating not found")
        self.flagged.append((rating_id, flagged_by))


def ride_history(bookings, user_id: str, role: Optional[str] = None, status: Optional[BookingStatus] = None,
                 start: Optional[datetime] = None, end: Optional[datetime] = None) -> list:
    """CRS-F-050: only the user's own rides, newest first, filterable by role/status/date."""
    out = []
    for b in bookings:
        if user_id not in (b.rider_id, b.driver_id):
            continue
        if b.status not in (BookingStatus.COMPLETED, BookingStatus.CANCELLED, BookingStatus.REJECTED,
                            BookingStatus.EXPIRED):
            continue
        if role == "rider" and b.rider_id != user_id:
            continue
        if role == "driver" and b.driver_id != user_id:
            continue
        if status is not None and b.status is not status:
            continue
        when = b.departure
        if start and when < start:
            continue
        if end and when > end:
            continue
        out.append(b)
    return sorted(out, key=lambda b: b.departure, reverse=True)
