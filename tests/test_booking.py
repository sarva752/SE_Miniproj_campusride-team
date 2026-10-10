import threading
from datetime import datetime, timedelta

import pytest

from campusride.booking import BookingService
from campusride.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from campusride.models import BookingStatus, GeoPoint, OfferStatus, RideOffer

NOW = datetime(2026, 10, 13, 8, 0)
P = GeoPoint(13.0, 80.2)


def make(seats=3, departure=NOW + timedelta(hours=3)):
    svc = BookingService()
    svc.add_offer(RideOffer(id="o1", driver_id="d1", origin=P, destination=P, route=[P, P], departure=departure,
                            seats_total=seats, seats_available=seats))
    return svc


def test_join_request_and_duplicate_rejected():  # TC-Book-01
    svc = make()
    b = svc.send_join_request("o1", "r1", 1, NOW)
    assert b.status is BookingStatus.PENDING
    with pytest.raises(ConflictError):
        svc.send_join_request("o1", "r1", 1, NOW)
    with pytest.raises(PermissionDenied):
        svc.send_join_request("o1", "d1", 1, NOW)
    with pytest.raises(NotFound):
        svc.send_join_request("nope", "r1", 1, NOW)


def test_accept_reject_and_owner_check():  # TC-Book-02
    svc = make()
    b1 = svc.send_join_request("o1", "r1", 1, NOW)
    b2 = svc.send_join_request("o1", "r2", 1, NOW)
    with pytest.raises(PermissionDenied):
        svc.accept(b1.id, "intruder", NOW)
    assert svc.accept(b1.id, "d1", NOW).status is BookingStatus.CONFIRMED
    assert svc.reject(b2.id, "d1").status is BookingStatus.REJECTED
    with pytest.raises(ConflictError):
        svc.accept(b1.id, "d1", NOW)  # already decided


def test_acceptance_reduces_seats_and_marks_full():  # TC-Book-03
    svc = make(seats=2)
    b = svc.send_join_request("o1", "r1", 2, NOW)
    svc.accept(b.id, "d1", NOW)
    offer = svc.offers["o1"]
    assert offer.seats_available == 0 and offer.status is OfferStatus.FULL
    with pytest.raises(ConflictError):
        svc.send_join_request("o1", "r2", 1, NOW)  # full offers are closed


def test_cannot_accept_more_seats_than_available():
    svc = make(seats=2)
    b1 = svc.send_join_request("o1", "r1", 2, NOW)
    b2 = svc.send_join_request("o1", "r2", 1, NOW)
    svc.accept(b1.id, "d1", NOW)
    with pytest.raises(ConflictError, match="Seats unavailable"):
        svc.accept(b2.id, "d1", NOW)


def test_cancel_confirmed_restores_seats():  # TC-Book-04
    svc = make(seats=2)
    b = svc.send_join_request("o1", "r1", 2, NOW)
    svc.accept(b.id, "d1", NOW)
    svc.cancel(b.id, "r1", "plans changed", NOW)
    assert svc.offers["o1"].seats_available == 2 and svc.offers["o1"].status is OfferStatus.OPEN
    with pytest.raises(ValidationError):
        svc.cancel(svc.send_join_request("o1", "r1", 1, NOW).id, "r1", " ", NOW)
    with pytest.raises(PermissionDenied):
        svc.cancel(b.id, "stranger", "x", NOW)


def test_repeated_late_cancellations_are_flagged():  # TC-Book-05
    svc = BookingService()
    for i in range(3):
        dep = NOW + timedelta(days=i, minutes=30)
        svc.add_offer(RideOffer(id=f"o{i}", driver_id="d1", origin=P, destination=P, route=[P, P], departure=dep,
                                seats_total=1, seats_available=1))
        b = svc.send_join_request(f"o{i}", "r1", 1, dep - timedelta(hours=5))
        svc.accept(b.id, "d1", dep - timedelta(hours=5))
        assert not svc.is_flagged("r1", dep) if i < 2 else True
        svc.cancel(b.id, "r1", "late", dep - timedelta(minutes=30))  # < 1 h before departure
    assert svc.is_flagged("r1", NOW + timedelta(days=3))
    assert not svc.is_flagged("r1", NOW + timedelta(days=60))


def test_ride_lifecycle_transitions():  # TC-Book-06
    svc = make()
    b = svc.send_join_request("o1", "r1", 1, NOW)
    with pytest.raises(ConflictError):
        svc.start_ride("o1", "d1")  # no confirmed riders yet
    svc.accept(b.id, "d1", NOW)
    with pytest.raises(PermissionDenied):
        svc.start_ride("o1", "other")
    with pytest.raises(ConflictError):
        svc.complete_ride("o1", "d1", NOW)  # not started
    svc.start_ride("o1", "d1")
    assert b.status is BookingStatus.STARTED
    svc.complete_ride("o1", "d1", NOW + timedelta(hours=1))
    assert b.status is BookingStatus.COMPLETED and b.ended_at is not None
    with pytest.raises(ConflictError):
        svc.start_ride("o1", "d1")


def test_pending_requests_expire():  # TC-Book-07
    svc = make()
    b = svc.send_join_request("o1", "r1", 1, NOW)
    assert svc.expire_pending(NOW + timedelta(minutes=29)) == []
    assert svc.expire_pending(NOW + timedelta(minutes=30)) == [b]
    assert b.status is BookingStatus.EXPIRED
    b2 = svc.send_join_request("o1", "r2", 1, NOW)
    svc.expire_pending(NOW + timedelta(hours=3))  # departure reached
    assert b2.status is BookingStatus.EXPIRED


def test_accepting_expired_request_fails():
    svc = make()
    b = svc.send_join_request("o1", "r1", 1, NOW)
    with pytest.raises(ConflictError, match="expired"):
        svc.accept(b.id, "d1", NOW + timedelta(minutes=31))


def test_concurrent_acceptance_never_overbooks():  # TC-Match-06
    svc = make(seats=3)
    ids = [svc.send_join_request("o1", f"r{i}", 1, NOW).id for i in range(100)]
    results = []

    def worker(bid):
        try:
            svc.accept(bid, "d1", NOW)
            results.append("ok")
        except ConflictError:
            results.append("conflict")

    threads = [threading.Thread(target=worker, args=(i,)) for i in ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 3 and results.count("conflict") == 97
    assert svc.offers["o1"].seats_available == 0
    assert sum(b.status is BookingStatus.CONFIRMED for b in svc.bookings.values()) == 3
def test_full_offer_reopens_after_cancel():
    svc = make(seats=1)
    b = svc.send_join_request("o1", "r1", 1, NOW)
    svc.accept(b.id, "d1", NOW)
    assert svc.offers["o1"].status is OfferStatus.FULL
    svc.cancel(b.id, "r1", "plans changed", NOW)
    assert svc.offers["o1"].status is OfferStatus.OPEN
    assert svc.send_join_request("o1", "r2", 1, NOW)