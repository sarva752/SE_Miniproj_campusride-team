from datetime import datetime, timedelta

import pytest

from campusride.admin import AdminService
from campusride.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from campusride.models import (Booking, BookingStatus, GeoPoint, OfferStatus, RequestStatus, RideOffer,
                               RideRequest, Role, User, UserStatus)

NOW = datetime(2026, 10, 13, 8, 0)
P = GeoPoint(13.0, 80.2)


def users():
    admin = User("a1", "admin@example.edu", "Admin", Role.ADMIN, UserStatus.ACTIVE)
    rider = User("u1", "asha@example.edu", "Asha", Role.RIDER, UserStatus.ACTIVE)
    return admin, rider


def apply(svc, rider):
    return svc.apply_as_driver(rider, "Swift", "TN01AB1234", 5, "DL-998877")


def test_driver_cannot_post_before_approval_then_can():  # TC-Prof-02 / TC-Admin-01
    svc = AdminService()
    admin, rider = users()
    apply(svc, rider)
    assert not svc.can_post_offers(rider)
    assert len(svc.pending_applications(admin)) == 1
    svc.review_application(admin, rider, True, "", NOW)
    assert svc.can_post_offers(rider) and rider.role is Role.DRIVER
    assert svc.pending_applications(admin) == []


def test_rejection_needs_reason_and_keeps_rider_role():  # TC-Admin-01
    svc = AdminService()
    admin, rider = users()
    apply(svc, rider)
    with pytest.raises(ValidationError):
        svc.review_application(admin, rider, False, " ", NOW)
    svc.review_application(admin, rider, False, "Licence unreadable", NOW)
    assert not svc.can_post_offers(rider) and rider.role is Role.RIDER
    apply(svc, rider)  # may re-apply after rejection


def test_application_validation_and_duplicates():  # TC-Prof-02
    svc = AdminService()
    _, rider = users()
    with pytest.raises(ValidationError):
        svc.apply_as_driver(rider, "", "TN01", 5, "DL")
    with pytest.raises(ValidationError):
        svc.apply_as_driver(rider, "Swift", "TN01", 1, "DL")
    apply(svc, rider)
    with pytest.raises(ConflictError):
        apply(svc, rider)


def test_admin_only_actions_are_enforced():  # CRS-SR-003
    svc = AdminService()
    _, rider = users()
    with pytest.raises(PermissionDenied):
        svc.pending_applications(rider)
    with pytest.raises(PermissionDenied):
        svc.update_config(rider, "match_radius_m", 500, NOW)
    with pytest.raises(PermissionDenied):
        svc.suspend_user(rider, rider, "x", [], [], NOW)
    with pytest.raises(NotFound):
        svc.review_application(users()[0], rider, True, "", NOW)


def test_suspension_removes_open_items_and_is_audited():  # TC-Admin-03
    svc = AdminService()
    admin, rider = users()
    offer = RideOffer("o1", "u1", P, P, [P, P], NOW + timedelta(hours=2), 2, 2)
    done = RideOffer("o2", "u1", P, P, [P, P], NOW, 2, 2, status=OfferStatus.COMPLETED)
    req = RideRequest("r1", "u1", P, P, NOW, NOW + timedelta(hours=1))
    svc.suspend_user(admin, rider, "harassment", [offer, done], [req], NOW)
    assert rider.status is UserStatus.SUSPENDED
    assert offer.status is OfferStatus.CANCELLED and done.status is OfferStatus.COMPLETED
    assert req.status is RequestStatus.CANCELLED
    assert svc.audit_log()[-1][2] == "USER_SUSPENDED"
    with pytest.raises(ValidationError):
        svc.suspend_user(admin, rider, "", [], [], NOW)


def test_configuration_changes_validated_and_audited():  # TC-Admin-04
    svc = AdminService()
    admin, _ = users()
    assert svc.update_config(admin, "match_radius_m", 1500, NOW)["match_radius_m"] == 1500
    for key, bad in [("match_radius_m", 50), ("match_radius_m", "big"), ("request_expiry_min", 0),
                     ("allowed_domains", []), ("nope", 1)]:
        with pytest.raises(ValidationError):
            svc.update_config(admin, key, bad, NOW)
    assert svc.config["match_radius_m"] == 1500
    assert "1000 -> 1500" in svc.audit_log()[-1][3]


def test_analytics_and_csv_export():  # TC-Admin-05
    admin, rider = users()
    bookings = [Booking("b1", "o1", "d1", "r1", 1, BookingStatus.CONFIRMED),
                Booking("b2", "o1", "d1", "r2", 1, BookingStatus.CANCELLED),
                Booking("b3", "o1", "d1", "r3", 1, BookingStatus.COMPLETED),
                Booking("b4", "o1", "d1", "r4", 1, BookingStatus.REJECTED)]
    stats = AdminService.analytics([admin, rider], [object()], bookings)
    assert stats["active_users"] == 2 and stats["rides_matched"] == 2 and stats["cancellations"] == 1
    assert stats["match_rate"] == 0.5
    csv = AdminService.analytics_csv(stats)
    assert csv.splitlines()[0] == "metric,value" and "match_rate,0.5" in csv
    assert AdminService.analytics([], [], [])["match_rate"] == 0.0


def test_audit_log_is_append_only_view():  # TC-Admin-06 / TC-Sec-10
    svc = AdminService()
    svc.log("a1", "TEST", "x", NOW)
    log = svc.audit_log()
    assert isinstance(log, tuple)
    assert not hasattr(svc, "delete_audit") and not hasattr(svc, "edit_audit")
    assert svc.audit_log() == log
