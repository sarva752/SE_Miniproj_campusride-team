from campusride.models import (BookingStatus, GeoPoint, OfferStatus, Role,
                               User, UserStatus)


def test_geopoint_is_immutable_and_hashable():
    p = GeoPoint(13.0, 80.0)
    assert p in {p}
    try:
        p.lat = 1  # type: ignore[misc]
        assert False, "GeoPoint must be frozen"
    except Exception:
        pass


def test_user_defaults():
    u = User(id="u1", email="a@example.edu", name="Asha")
    assert u.role is Role.RIDER
    assert u.status is UserStatus.INACTIVE


def test_status_values_match_srs():
    assert {s.value for s in BookingStatus} >= {"PENDING", "CONFIRMED", "REJECTED", "CANCELLED", "EXPIRED"}
    assert OfferStatus.OPEN.value == "OPEN"
