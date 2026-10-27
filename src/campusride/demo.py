"""End-to-end walk-through of the CampusRide rider/driver journey (all modules working together)."""
from __future__ import annotations

from datetime import datetime, timedelta

from .auth import AuthService
from .booking import BookingService
from .matching import find_matches
from .messaging import ChatService
from .models import BookingStatus, GeoPoint
from .notifications import NotificationService
from .ratings import RatingService
from .rides import create_offer, create_request

NOW = datetime(2026, 10, 13, 7, 0)


def run_demo() -> list:
    log: list = []
    auth, bookings = AuthService(), BookingService()
    chat, ratings, notes = ChatService(), RatingService(), NotificationService()

    # 1. registration + verification for a driver and a rider
    users = {}
    for key, email in (("driver", "dev@example.edu"), ("rider", "asha@example.edu")):
        _, code = auth.register(email, key.title(), "Ride#2026a", NOW)
        users[key] = auth.verify_email(email, code, NOW)
    log.append("Registered and verified 2 users")

    # 2. driver posts an offer; rider posts a request
    a, b = GeoPoint(13.000, 80.200), GeoPoint(13.000, 80.290)
    dep = NOW + timedelta(hours=2)
    offer = create_offer("o1", users["driver"].id, 5, a, b, [a, GeoPoint(13.0, 80.245), b], dep, 3, NOW)
    bookings.add_offer(offer)
    req = create_request("r1", users["rider"].id, GeoPoint(13.002, 80.22), GeoPoint(13.002, 80.27),
                         dep - timedelta(minutes=20), dep + timedelta(minutes=20), 1, NOW)
    log.append("Offer and request created")

    # 3. matching
    matches = find_matches([offer], req)
    log.append(f"Matches found: {len(matches)} (best score {matches[0].score})")

    # 4. booking
    bk = bookings.send_join_request(offer.id, users["rider"].id, 1, NOW)
    notes.notify(users["driver"].id, "join_request_received", {"booking": bk.id}, NOW)
    bookings.accept(bk.id, users["driver"].id, NOW + timedelta(minutes=5))
    notes.notify(users["rider"].id, "request_accepted", {"booking": bk.id}, NOW)
    log.append(f"Booking {bk.id} confirmed, seats left: {offer.seats_available}")

    # 5. chat
    chat.send(bk, users["rider"].id, "See you at the main gate!", NOW + timedelta(minutes=10))
    log.append(f"Chat messages: {len(chat.history(bk, users['driver'].id))}")

    # 6. ride + ratings
    bookings.start_ride(offer.id, users["driver"].id)
    bookings.complete_ride(offer.id, users["driver"].id, dep + timedelta(hours=1))
    assert bk.status is BookingStatus.COMPLETED
    ratings.submit(bk, users["rider"].id, 5, "Smooth ride", dep + timedelta(hours=2))
    log.append(f"Driver rating: {ratings.average(users['driver'].id)}")
    log.append(f"Notifications sent: {len(notes.outbox)}")
    return log
