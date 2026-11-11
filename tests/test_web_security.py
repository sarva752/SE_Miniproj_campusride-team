"""Web-layer guard, validation and error-path tests.

The happy paths of the Flask UI live in ``tests/test_web.py``. This file covers
the negative and guard paths that the Test Plan calls out, in particular the
access-control cases in Section 5.1 (Security Validation):

* TC-Sec-04  - RBAC and IDOR: a third user must not reach another pair's booking
               or another rider's match list.
* TC-Sec-05  - contact/location detail is only reachable by the two participants.
* TC-Book-04 - cancelling a confirmed booking restores seats and notifies.
* TC-Book-05 - rejecting a pending request notifies the rider.
* TC-Ride-07 - the UI refuses a second confirmed ride in the same time window.
* TC-Msg-03  - block and report a chat partner.
* TC-Notif-03- per-channel notification preferences.
* TC-Admin-01/03 - review and suspend guards, including "admins cannot be suspended".
"""
from datetime import datetime, timedelta

import pytest

from campusride.models import BookingStatus
from campusride.web.app import ADMIN_EMAIL, ADMIN_PASSWORD, create_app

from test_web import PASSWORD, admin_client, make_driver, post, signup, stamp


@pytest.fixture
def app():
    return create_app({"TESTING": True, "SECRET_KEY": "test"})


def confirmed_booking(app):
    """Driver offers a ride, rider joins, driver accepts. Returns both clients."""
    driver = make_driver(app)
    rider = signup(app, "asha@example.edu", "Asha")
    dep = (datetime.now() + timedelta(hours=2)).replace(second=0, microsecond=0)
    post(driver, "/offers/new", {"origin": "Main Gate", "destination": "Tech Park",
                                 "departure": stamp(dep), "seats": "3"})
    post(rider, "/offers/o1/join", {"seats": "1"})
    post(driver, "/bookings/b1/accept")
    return driver, rider, dep


# --------------------------------------------------------------- form validation
def test_unknown_location_is_rejected(app):  # TC-Web-12
    driver = make_driver(app)
    dep = (datetime.now() + timedelta(hours=2)).replace(second=0, microsecond=0)
    page = post(driver, "/offers/new", {"origin": "Mars Base", "destination": "Tech Park",
                                        "departure": stamp(dep), "seats": "2"}).get_data(as_text=True)
    assert "Choose a location from the list" in page


def test_origin_and_destination_must_differ(app):  # TC-Web-12
    driver = make_driver(app)
    dep = (datetime.now() + timedelta(hours=2)).replace(second=0, microsecond=0)
    page = post(driver, "/offers/new", {"origin": "Library", "destination": "Library",
                                        "departure": stamp(dep), "seats": "2"}).get_data(as_text=True)
    assert "must differ" in page


def test_non_numeric_seats_and_bad_datetime_are_reported(app):  # TC-Web-12
    driver = make_driver(app)
    dep = (datetime.now() + timedelta(hours=2)).replace(second=0, microsecond=0)

    page = post(driver, "/offers/new", {"origin": "Main Gate", "destination": "Tech Park",
                                        "departure": stamp(dep), "seats": "three"}).get_data(as_text=True)
    assert "whole number" in page

    page = post(driver, "/offers/new", {"origin": "Main Gate", "destination": "Tech Park",
                                        "departure": "not-a-date", "seats": "2"}).get_data(as_text=True)
    assert "valid date and time" in page


def test_driver_application_rejects_non_numeric_capacity(app):  # TC-Web-12
    user = signup(app, "new@example.edu", "New")
    page = post(user, "/driver/apply", {"model": "Swift", "reg_no": "KA01",
                                        "capacity": "many", "licence_no": "L1"}).get_data(as_text=True)
    assert "whole number" in page


# --------------------------------------------------------- TC-Sec-04: IDOR / RBAC
def test_booking_routes_reject_strangers_and_unknown_ids(app):  # TC-Web-11, TC-Sec-04
    driver, rider, _ = confirmed_booking(app)
    stranger = signup(app, "eve@example.edu", "Eve")

    # A user with no part in the booking may not read or act on it (IDOR).
    for url in ("/bookings/b1/chat",):
        assert stranger.get(url).status_code == 403, url
    for url in ("/bookings/b1/accept", "/bookings/b1/reject", "/bookings/b1/cancel", "/bookings/b1/rate"):
        assert post(stranger, url, {"reason": "x", "stars": "5"}, follow=False).status_code == 403, url

    # Unknown identifiers are 404 for everyone, including participants.
    assert driver.get("/bookings/nope/chat").status_code == 404
    assert post(rider, "/bookings/nope/cancel", {"reason": "x"}, follow=False).status_code == 404


def test_match_list_belongs_to_its_owner_only(app):  # TC-Web-11, TC-Sec-04, TC-Sec-05
    rider = signup(app, "asha@example.edu", "Asha")
    stranger = signup(app, "eve@example.edu", "Eve")
    dep = (datetime.now() + timedelta(hours=2)).replace(second=0, microsecond=0)
    post(rider, "/requests/new", {"pickup": "Library", "drop": "Sports Complex",
                                  "earliest": stamp(dep - timedelta(minutes=20)),
                                  "latest": stamp(dep + timedelta(minutes=20)), "seats": "1"})

    assert rider.get("/requests/r1/matches").status_code == 200
    assert stranger.get("/requests/r1/matches").status_code == 403
    assert rider.get("/requests/r999/matches").status_code == 404


def test_join_on_unknown_offer_is_404(app):  # TC-Web-11
    rider = signup(app, "asha@example.edu", "Asha")
    assert post(rider, "/offers/o999/join", {"seats": "1"}, follow=False).status_code == 404


# ------------------------------------------------------- booking lifecycle paths
def test_driver_can_reject_a_pending_request(app):  # TC-Web-13
    driver = make_driver(app)
    rider = signup(app, "asha@example.edu", "Asha")
    dep = (datetime.now() + timedelta(hours=2)).replace(second=0, microsecond=0)
    post(driver, "/offers/new", {"origin": "Main Gate", "destination": "Tech Park",
                                 "departure": stamp(dep), "seats": "2"})
    post(rider, "/offers/o1/join", {"seats": "1"})

    assert "Request rejected" in post(driver, "/bookings/b1/reject").get_data(as_text=True)
    state = app.config["STATE"]
    assert state.bookings.bookings["b1"].status is BookingStatus.REJECTED
    assert "request rejected" in rider.get("/notifications").get_data(as_text=True).lower()


def test_cancelling_a_confirmed_booking_restores_seats_and_notifies(app):  # TC-Web-13
    driver, rider, _ = confirmed_booking(app)
    state = app.config["STATE"]
    assert state.bookings.offers["o1"].seats_available == 2

    page = post(rider, "/bookings/b1/cancel", {"reason": "Class moved"}).get_data(as_text=True)
    assert "Booking cancelled" in page
    assert state.bookings.offers["o1"].seats_available == 3
    assert "cancelled" in driver.get("/notifications").get_data(as_text=True).lower()


def test_cancel_without_a_reason_is_refused(app):  # TC-Web-13
    _driver, rider, _ = confirmed_booking(app)
    page = post(rider, "/bookings/b1/cancel", {"reason": "   "}).get_data(as_text=True)
    assert "reason is required" in page


def test_ui_blocks_a_second_overlapping_confirmed_ride(app):  # TC-Web-14
    """CRS-F-015 / TC-Ride-07 enforced at the web layer."""
    driver, rider, dep = confirmed_booking(app)
    # A second offer leaving at almost the same time as the rider's confirmed ride.
    post(driver, "/offers/new", {"origin": "Library", "destination": "Hostel Block",
                                 "departure": stamp(dep + timedelta(minutes=10)), "seats": "3"})
    page = post(rider, "/offers/o2/join", {"seats": "1"}).get_data(as_text=True)
    assert "already have a confirmed ride" in page


# ------------------------------------------------------------ TC-Msg-03: chat moderation
def test_block_and_report_from_the_chat_page(app):  # TC-Web-15
    driver, rider, _ = confirmed_booking(app)
    state = app.config["STATE"]

    assert "User blocked" in post(rider, "/bookings/b1/chat", {"action": "block"}).get_data(as_text=True)
    rider_id = state.auth._users["asha@example.edu"].id
    driver_id = state.auth._users["dev@example.edu"].id
    assert state.chat.is_blocked(rider_id, driver_id)

    page = post(rider, "/bookings/b1/chat", {"action": "report", "reason": "Rude language"}).get_data(as_text=True)
    assert "Report sent" in page
    assert state.chat.reports[-1] == (rider_id, driver_id, "Rude language")

    # A report with no reason is refused by the service and surfaced on the page.
    page = post(rider, "/bookings/b1/chat", {"action": "report", "reason": " "}).get_data(as_text=True)
    assert "reason is required" in page

    # The admin dashboard shows the report.
    assert "Rude language" in admin_client(app).get("/admin").get_data(as_text=True)


# -------------------------------------------------- TC-Notif-03: channel preferences
def test_notification_channel_preferences_are_saved(app):  # TC-Web-16
    rider = signup(app, "asha@example.edu", "Asha")
    state = app.config["STATE"]
    rider_id = state.auth._users["asha@example.edu"].id

    assert "settings saved" in post(rider, "/notifications", {"in_app": "on"}).get_data(as_text=True).lower()
    prefs = state.notes.prefs[rider_id]
    assert prefs.channels["in_app"] is True
    assert prefs.channels["email"] is False and prefs.channels["push"] is False


# ------------------------------------------------------------------- history filters
def test_history_ignores_an_unknown_status_filter(app):  # TC-Web-09
    rider = signup(app, "asha@example.edu", "Asha")
    assert rider.get("/history?status=NOT_A_STATUS").status_code == 200


def test_match_list_ignores_a_bad_sort_key_and_bad_filters(app):  # TC-Web-09
    driver, rider, dep = confirmed_booking(app)
    post(rider, "/requests/new", {"pickup": "Library", "drop": "Sports Complex",
                                  "earliest": stamp(dep - timedelta(minutes=20)),
                                  "latest": stamp(dep + timedelta(minutes=20)), "seats": "1"})
    # Unknown sort key falls back to "score"; unparsable filters are ignored.
    resp = rider.get("/requests/r1/matches?sort=banana&min_rating=high&max_detour=far&min_seats=x")
    assert resp.status_code == 200


# ------------------------------------------------------------------ admin guards
def test_admin_actions_on_unknown_users_are_404(app):  # TC-Web-07
    admin = admin_client(app)
    assert post(admin, "/admin/applications/u999/review", {"decision": "approve"}, follow=False).status_code == 404
    assert post(admin, "/admin/users/u999/suspend", {"reason": "x"}, follow=False).status_code == 404


def test_an_admin_cannot_be_suspended(app):  # TC-Web-07
    admin = admin_client(app)
    admin_id = app.config["STATE"].auth._users[ADMIN_EMAIL].id
    page = post(admin, f"/admin/users/{admin_id}/suspend", {"reason": "oops"}).get_data(as_text=True)
    assert "Administrators cannot be suspended" in page


def test_rejecting_a_driver_application_needs_a_reason(app):  # TC-Web-07
    user = signup(app, "new@example.edu", "New")
    post(user, "/driver/apply", {"model": "Swift", "reg_no": "KA01", "capacity": "4", "licence_no": "L1"})
    uid = app.config["STATE"].auth._users["new@example.edu"].id
    admin = admin_client(app)
    page = post(admin, f"/admin/applications/{uid}/review", {"decision": "reject", "reason": ""}).get_data(as_text=True)
    assert "reason" in page.lower()


# ------------------------------------------------------- GET renders of the forms
def test_account_forms_render_on_a_plain_get(app):  # TC-Web-09
    client = app.test_client()
    for url in ("/register", "/verify?email=asha@example.edu", "/login"):
        assert client.get(url).status_code == 200, url


def test_a_wrong_code_keeps_the_user_on_the_verify_page(app):  # TC-Web-02
    client = app.test_client()
    post(client, "/register", {"email": "asha@example.edu", "name": "Asha", "password": PASSWORD})
    page = post(client, "/verify", {"email": "asha@example.edu", "code": "000000"}).get_data(as_text=True)
    assert "Invalid or expired OTP" in page
    assert "Email verified" not in page


def test_an_invalid_ride_request_redisplays_the_form(app):  # TC-Web-12
    rider = signup(app, "asha@example.edu", "Asha")
    dep = (datetime.now() + timedelta(hours=2)).replace(second=0, microsecond=0)
    # "latest" before "earliest" is not a usable time window.
    page = post(rider, "/requests/new", {"pickup": "Library", "drop": "Sports Complex",
                                         "earliest": stamp(dep),
                                         "latest": stamp(dep - timedelta(hours=1)),
                                         "seats": "1"}).get_data(as_text=True)
    assert "Matches for your request" not in page
    assert app.config["STATE"].requests == {}


def test_an_unknown_chat_action_changes_nothing(app):  # TC-Web-15
    _driver, rider, _ = confirmed_booking(app)
    state = app.config["STATE"]
    post(rider, "/bookings/b1/chat", {"action": "sabotage", "content": "hello"})
    assert state.chat.history(state.bookings.bookings["b1"], state.auth._users["asha@example.edu"].id) == []
    assert state.chat.reports == []


# --------------------------------------------------------------- session handling
def test_logout_clears_the_session(app):  # TC-Web-17, TC-Sec-08
    rider = signup(app, "asha@example.edu", "Asha")
    assert rider.get("/rides").status_code == 200
    post(rider, "/logout")
    assert rider.get("/rides").status_code == 302


# ------------------------------------------------------------------ app config
def test_app_can_start_without_the_demo_admin_and_without_showing_otps():  # TC-Web-18
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "SEED_ADMIN": False, "SHOW_OTP": False})
    assert app.config["STATE"].users == {}

    client = app.test_client()
    page = post(client, "/register", {"email": "asha@example.edu", "name": "Asha",
                                      "password": PASSWORD}).get_data(as_text=True)
    assert "verification code" not in page  # production mode sends the OTP by email instead

    # The seeded admin account does not exist, so its credentials do not work.
    page = post(client, "/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).get_data(as_text=True)
    assert "Welcome" not in page
