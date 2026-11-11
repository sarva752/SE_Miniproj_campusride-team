"""Defensive and boundary paths of the service layer.

The feature test files cover each requirement's main flows. This file exercises
the guard clauses that those flows never reach - bad identifiers, wrong actor,
wrong state, out-of-range values - so that every decision in the service layer
is executed at least once in both directions (branch coverage, CRS-NF-010).
"""
from datetime import datetime, timedelta

import pytest

from campusride.auth import AuthService
from campusride.booking import BookingService
from campusride.errors import (
    AuthenticationError,
    ConflictError,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from campusride.geo import project_on_route
from campusride.matching import filter_matches, find_matches, score_match
from campusride.models import BookingStatus, GeoPoint, UserStatus
from campusride.ratings import ride_history
from campusride.rides import create_offer, create_request, validate_location

NOW = datetime(2026, 11, 3, 8, 0)
PASSWORD = "Ride#2026a"
A = GeoPoint(13.000, 80.200)
B = GeoPoint(13.000, 80.290)


# ------------------------------------------------------------------ auth guards
def test_registration_requires_a_name():  # TC-Auth-02
    auth = AuthService()
    with pytest.raises(ValidationError, match="Name is required"):
        auth.register("asha@example.edu", "   ", PASSWORD, NOW)


def test_verifying_an_unknown_email_is_rejected():  # TC-Auth-02
    auth = AuthService()
    with pytest.raises(ValidationError, match="Invalid or expired OTP"):
        auth.verify_email("nobody@example.edu", "123456", NOW)


def test_suspended_user_cannot_log_in():  # TC-Admin-03
    auth = AuthService()
    _user, code = auth.register("asha@example.edu", "Asha", PASSWORD, NOW)
    user = auth.verify_email("asha@example.edu", code, NOW)
    user.status = UserStatus.SUSPENDED
    with pytest.raises(AuthenticationError, match="suspended"):
        auth.login("asha@example.edu", PASSWORD, NOW)


# --------------------------------------------------------------- booking guards
@pytest.fixture
def service():
    svc = BookingService()
    svc.add_offer(create_offer("o1", "driver", 4, A, B, [A, B], NOW + timedelta(hours=2), 3, NOW))
    return svc


def test_unknown_booking_id_raises_not_found(service):  # TC-Book-02
    with pytest.raises(NotFound, match="Booking not found"):
        service.accept("b404", "driver", NOW)


def test_join_request_needs_at_least_one_seat(service):  # TC-Book-01
    with pytest.raises(ValidationError, match="at least 1"):
        service.send_join_request("o1", "rider", 0, NOW)


def test_only_the_offer_owner_can_reject(service):  # TC-Book-02
    service.send_join_request("o1", "rider", 1, NOW)
    with pytest.raises(PermissionDenied, match="Only the offer owner"):
        service.reject("b1", "someone-else")


def test_a_decided_request_cannot_be_rejected_again(service):  # TC-Book-02
    service.send_join_request("o1", "rider", 1, NOW)
    service.accept("b1", "driver", NOW)
    with pytest.raises(ConflictError, match="already decided"):
        service.reject("b1", "driver")


def test_a_cancelled_booking_cannot_be_cancelled_twice(service):  # TC-Book-04
    service.send_join_request("o1", "rider", 1, NOW)
    service.cancel("b1", "rider", "Plans changed", NOW)
    with pytest.raises(ConflictError, match="cannot be cancelled"):
        service.cancel("b1", "rider", "Plans changed again", NOW)


def test_cancelling_a_pending_request_leaves_seats_untouched(service):  # TC-Book-04
    """Only CONFIRMED bookings hold a seat, so cancelling a PENDING one frees nothing."""
    service.send_join_request("o1", "rider", 2, NOW)
    assert service.offers["o1"].seats_available == 3
    service.cancel("b1", "rider", "Plans changed", NOW)
    assert service.offers["o1"].seats_available == 3
    assert service.bookings["b1"].status is BookingStatus.CANCELLED


def test_only_the_driver_can_complete_a_ride(service):  # TC-Book-06
    service.send_join_request("o1", "rider", 1, NOW)
    service.accept("b1", "driver", NOW)
    service.start_ride("o1", "driver")
    with pytest.raises(PermissionDenied, match="Only the driver"):
        service.complete_ride("o1", "rider", NOW)


# ------------------------------------------------------------------ geo & rides
def test_projecting_on_a_route_needs_two_points():  # TC-Ride-06
    with pytest.raises(ValueError, match="at least two points"):
        project_on_route(A, [A])


def test_coordinates_outside_the_globe_are_rejected():  # TC-Ride-06
    with pytest.raises(ValidationError, match="Invalid coordinates"):
        validate_location(GeoPoint(120.0, 80.2))
    with pytest.raises(ValidationError, match="Invalid coordinates"):
        validate_location(GeoPoint(13.0, 200.0))


# --------------------------------------------------------------------- matching
def test_zero_length_time_window_scores_as_a_perfect_time_match():  # TC-Match-03
    """A request whose earliest equals its latest has no window to measure against."""
    instant = NOW + timedelta(hours=2)
    req = create_request("r1", "rider", A, B, instant, instant, 1, NOW)
    offer = create_offer("o1", "driver", 4, A, B, [A, B], instant, 3, NOW)
    perfect = score_match(offer, req, detour_m=0.0, radius_m=1000.0, driver_rating=5.0)

    late = create_offer("o2", "driver", 4, A, B, [A, B], instant + timedelta(minutes=45), 3, NOW)
    assert perfect == pytest.approx(score_match(late, req, 0.0, 1000.0, 5.0))


def test_max_detour_filter_drops_offers_that_are_too_far(service):  # TC-Match-05
    far = GeoPoint(13.030, 80.200)
    req = create_request("r1", "rider", far, B, NOW + timedelta(hours=1, minutes=30),
                         NOW + timedelta(hours=2, minutes=30), 1, NOW)
    found = find_matches(service.offers.values(), req, radius_m=5000)
    assert found, "the offer should match with a generous radius"

    assert filter_matches(found, max_detour_m=100_000) == found
    assert filter_matches(found, max_detour_m=1.0) == []


# ---------------------------------------------------------------------- history
def test_history_end_date_filter_excludes_later_rides(service):  # TC-Hist-01
    service.send_join_request("o1", "rider", 1, NOW)
    service.cancel("b1", "rider", "Plans changed", NOW)  # history only lists finished rides
    bookings = list(service.bookings.values())
    departure = bookings[0].departure

    assert ride_history(bookings, "rider", end=departure + timedelta(hours=1)) == bookings
    assert ride_history(bookings, "rider", end=departure - timedelta(hours=1)) == []
