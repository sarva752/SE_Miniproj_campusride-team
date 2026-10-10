"""Booking lifecycle: join request, accept/reject, cancel, expiry, start/complete.

Covers CRS-F-024, CRS-F-030..035. A lock makes seat allocation atomic (CRS-F-024); in the
production design this is the conditional SQL UPDATE described in SAD section 4.1.2.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Optional

from .errors import ConflictError, NotFound, PermissionDenied, ValidationError
from .models import Booking, BookingStatus, OfferStatus, RideOffer

REQUEST_TIMEOUT = timedelta(minutes=30)
LATE_CANCEL_WINDOW = timedelta(hours=1)
LATE_CANCEL_LIMIT = 3
LATE_CANCEL_PERIOD = timedelta(days=30)

ACTIVE = (BookingStatus.PENDING, BookingStatus.CONFIRMED)


class BookingService:
    def __init__(self):
        self.offers: dict[str, RideOffer] = {}
        self.bookings: dict[str, Booking] = {}
        self.late_cancellations: dict[str, list[datetime]] = {}
        self._lock = threading.Lock()
        self._seq = 0

    def add_offer(self, offer: RideOffer) -> None:
        self.offers[offer.id] = offer

    def _offer(self, offer_id: str) -> RideOffer:
        if offer_id not in self.offers:
            raise NotFound("Offer not found")
        return self.offers[offer_id]

    def _booking(self, booking_id: str) -> Booking:
        if booking_id not in self.bookings:
            raise NotFound("Booking not found")
        return self.bookings[booking_id]

    # CRS-F-030
    def send_join_request(self, offer_id: str, rider_id: str, seats: int, now: datetime) -> Booking:
        offer = self._offer(offer_id)
        if offer.driver_id == rider_id:
            raise PermissionDenied("Drivers cannot book their own offer")
        if offer.status is not OfferStatus.OPEN:
            raise ConflictError("Offer is not open")
        if seats < 1:
            raise ValidationError("Seats must be at least 1")
        with self._lock:
            if any(b.offer_id == offer_id and b.rider_id == rider_id and b.status in ACTIVE
                   for b in self.bookings.values()):
                raise ConflictError("You already have a request for this offer")
            self._seq += 1
            b = Booking(id=f"b{self._seq}", offer_id=offer_id, driver_id=offer.driver_id, rider_id=rider_id,
                        seats=seats, created_at=now, departure=offer.departure)
            self.bookings[b.id] = b
            return b

    # CRS-F-031 / CRS-F-032 / CRS-F-024
    def accept(self, booking_id: str, driver_id: str, now: datetime) -> Booking:
        b = self._booking(booking_id)
        if b.driver_id != driver_id:
            raise PermissionDenied("Only the offer owner can decide")
        with self._lock:  # atomic check-and-decrement
            if b.status is not BookingStatus.PENDING:
                raise ConflictError("Request already decided")
            if now - b.created_at > REQUEST_TIMEOUT or now >= b.departure:
                b.status = BookingStatus.EXPIRED
                raise ConflictError("Request expired")
            offer = self._offer(b.offer_id)
            if offer.seats_available < b.seats:
                raise ConflictError("Seats unavailable")
            offer.seats_available -= b.seats
            if offer.seats_available == 0:
                offer.status = OfferStatus.FULL
            b.status = BookingStatus.CONFIRMED
            return b

    def reject(self, booking_id: str, driver_id: str) -> Booking:
        b = self._booking(booking_id)
        if b.driver_id != driver_id:
            raise PermissionDenied("Only the offer owner can decide")
        with self._lock:
            if b.status is not BookingStatus.PENDING:
                raise ConflictError("Request already decided")
            b.status = BookingStatus.REJECTED
            return b

    # CRS-F-033
    def cancel(self, booking_id: str, user_id: str, reason: str, now: datetime) -> Booking:
        b = self._booking(booking_id)
        if user_id not in (b.rider_id, b.driver_id):
            raise PermissionDenied("Not your booking")
        if not (reason or "").strip():
            raise ValidationError("A reason is required")
        with self._lock:
            if b.status not in ACTIVE:
                raise ConflictError("Booking cannot be cancelled")
            if b.status is BookingStatus.CONFIRMED:
                offer = self._offer(b.offer_id)
                offer.seats_available += b.seats
                if offer.status is OfferStatus.FULL:
                    offer.status = OfferStatus.OPEN
                if b.departure - now < LATE_CANCEL_WINDOW:
                    self.late_cancellations.setdefault(user_id, []).append(now)
            b.status = BookingStatus.CANCELLED
            b.ended_at = now
            return b

    def is_flagged(self, user_id: str, now: datetime) -> bool:
        recent = [t for t in self.late_cancellations.get(user_id, []) if now - t <= LATE_CANCEL_PERIOD]
        return len(recent) >= LATE_CANCEL_LIMIT

    # CRS-F-035
    def expire_pending(self, now: datetime, timeout: timedelta = REQUEST_TIMEOUT) -> list:
        expired = []
        with self._lock:
            for b in self.bookings.values():
                if b.status is BookingStatus.PENDING and (now - b.created_at >= timeout or now >= b.departure):
                    b.status = BookingStatus.EXPIRED
                    expired.append(b)
        return expired

    # CRS-F-034
    def start_ride(self, offer_id: str, driver_id: str) -> RideOffer:
        offer = self._offer(offer_id)
        if offer.driver_id != driver_id:
            raise PermissionDenied("Only the driver can start the ride")
        if offer.status not in (OfferStatus.OPEN, OfferStatus.FULL):
            raise ConflictError("Ride cannot be started")
        if not any(b.offer_id == offer_id and b.status is BookingStatus.CONFIRMED for b in self.bookings.values()):
            raise ConflictError("No confirmed riders")
        offer.status = OfferStatus.STARTED
        for b in self.bookings.values():
            if b.offer_id == offer_id and b.status is BookingStatus.CONFIRMED:
                b.status = BookingStatus.STARTED
        return offer

    def complete_ride(self, offer_id: str, driver_id: str, now: datetime) -> RideOffer:
        offer = self._offer(offer_id)
        if offer.driver_id != driver_id:
            raise PermissionDenied("Only the driver can complete the ride")
        if offer.status is not OfferStatus.STARTED:
            raise ConflictError("Ride is not in progress")
        offer.status = OfferStatus.COMPLETED
        for b in self.bookings.values():
            if b.offer_id == offer_id and b.status is BookingStatus.STARTED:
                b.status = BookingStatus.COMPLETED
                b.ended_at = now
        return offer
