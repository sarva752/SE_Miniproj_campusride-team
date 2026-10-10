from datetime import datetime, timedelta

import pytest

from campusride.notifications import NotificationService

NOW = datetime(2026, 10, 13, 8, 0)


def test_notification_created_for_every_listed_event():  # TC-Notif-01
    svc = NotificationService()
    for event in ["match_found", "join_request_received", "request_accepted", "request_rejected",
                  "booking_cancelled", "new_message", "rating_reminder"]:
        made = svc.notify("u1", event, {"id": 1}, NOW)
        assert {n.channel for n in made} == {"in_app", "email"}  # defaults: push is off
    assert len(svc.outbox) == 14


def test_unknown_event_rejected():
    with pytest.raises(ValueError):
        NotificationService().notify("u1", "bogus", {}, NOW)


def test_departure_reminder_timing():  # TC-Notif-02
    svc = NotificationService()
    ride = [(NOW + timedelta(minutes=30), ["d1", "r1"])]
    assert svc.due_departure_reminders(ride, NOW) == ["d1", "r1"]
    assert svc.due_departure_reminders(ride, NOW + timedelta(seconds=50)) == ["d1", "r1"]  # within +/- 1 min
    assert svc.due_departure_reminders(ride, NOW + timedelta(minutes=5)) == []
    assert svc.due_departure_reminders(ride, NOW - timedelta(minutes=5)) == []


def test_channel_and_category_preferences():  # TC-Notif-03
    svc = NotificationService()
    svc.set_channel("u1", "email", False)
    svc.set_channel("u1", "push", True)
    assert {n.channel for n in svc.notify("u1", "match_found", {}, NOW)} == {"in_app", "push"}
    svc.mute_event("u1", "new_message")
    assert svc.notify("u1", "new_message", {}, NOW) == []
    svc.mute_event("u1", "new_message", muted=False)
    assert svc.notify("u1", "new_message", {}, NOW)
    with pytest.raises(ValueError):
        svc.set_channel("u1", "sms", True)


def test_security_notices_ignore_preferences():  # TC-Notif-03
    svc = NotificationService()
    for c in ("in_app", "email", "push"):
        svc.set_channel("u1", c, False)
    svc.mute_event("u1", "account_locked")
    made = svc.notify("u1", "account_locked", {}, NOW)
    assert {n.channel for n in made} == {"in_app", "email"}
def test_reminders_handle_multiple_rides():
    svc = NotificationService()
    rides = [
        (NOW + timedelta(minutes=30), ["a"]),
        (NOW + timedelta(hours=2), ["b"]),
        (NOW + timedelta(minutes=30, seconds=20), ["c"]),
    ]
    assert svc.due_departure_reminders(rides, NOW) == ["a", "c"]
