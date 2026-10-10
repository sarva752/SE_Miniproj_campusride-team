from datetime import datetime, timedelta

import pytest

from campusride.errors import ValidationError
from campusride.models import GeoPoint
from campusride.rides import (ServiceArea, create_offer, create_request,
                              has_overlapping_ride, validate_location)

NOW = datetime(2026, 10, 12, 8, 0)
A = GeoPoint(13.00, 80.20)
B = GeoPoint(13.05, 80.25)


def offer(**kw):
    args = dict(offer_id="o1", driver_id="d1", vehicle_capacity=5, origin=A, destination=B, route=None,
                departure=NOW + timedelta(hours=2), seats=3, now=NOW)
    args.update(kw)
    return create_offer(**args)


def test_create_valid_offer():  # TC-Ride-01
    o = offer()
    assert o.seats_available == 3 and o.route == [A, B]


@pytest.mark.parametrize("kw", [
    dict(departure=NOW - timedelta(minutes=1)),
    dict(seats=0),
    dict(seats=5),  # capacity 5 -> max 4
])
def test_offer_rejects_invalid_input(kw):  # TC-Ride-02
    with pytest.raises(ValidationError):
        offer(**kw)


def test_offer_boundary_seats_capacity_minus_one():  # TC-Ride-02 boundary
    assert offer(seats=4).seats_total == 4


def test_create_valid_request():  # TC-Ride-04
    r = create_request("r1", "u1", A, B, NOW + timedelta(hours=1), NOW + timedelta(hours=2), 2, NOW)
    assert r.seats_needed == 2


@pytest.mark.parametrize("seats", [0, 5])
def test_request_seat_bounds(seats):
    with pytest.raises(ValidationError):
        create_request("r1", "u1", A, B, NOW, NOW + timedelta(hours=1), seats, NOW)


def test_request_rejects_bad_window_and_same_points():
    with pytest.raises(ValidationError):
        create_request("r1", "u1", A, B, NOW + timedelta(hours=2), NOW + timedelta(hours=1), 1, NOW)
    with pytest.raises(ValidationError):
        create_request("r1", "u1", A, A, NOW, NOW + timedelta(hours=1), 1, NOW)


def test_location_outside_service_area_rejected():  # TC-Ride-06
    with pytest.raises(ValidationError):
        validate_location(GeoPoint(28.6, 77.2))
    assert validate_location(A)
    tiny = ServiceArea(13.0, 13.01, 80.2, 80.21)
    with pytest.raises(ValidationError):
        validate_location(B, tiny)


def test_overlapping_rides_detected():  # TC-Ride-07
    d = NOW + timedelta(hours=3)
    assert has_overlapping_ride([d], d + timedelta(minutes=30))
    assert not has_overlapping_ride([d], d + timedelta(hours=1))  # back-to-back is fine
    assert not has_overlapping_ride([], d)

def test_offer_route_points_must_be_inside_service_area():
    with pytest.raises(ValidationError):
        offer(route=[A, GeoPoint(28.6, 77.2), B])


def test_request_with_window_starting_in_the_past_is_rejected():
    with pytest.raises(ValidationError):
        create_request("r1", "u1", A, B, NOW - timedelta(hours=1), NOW + timedelta(hours=1), 1, NOW)