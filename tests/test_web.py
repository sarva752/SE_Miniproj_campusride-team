"""Tests for the Flask web UI (they drive the pages with Flask's test client)."""
import re
from datetime import datetime, timedelta

import pytest

from campusride.web.app import ADMIN_EMAIL, ADMIN_PASSWORD, create_app

PASSWORD = "Ride#2026a"


@pytest.fixture
def app():
    return create_app({"TESTING": True, "SECRET_KEY": "test"})


def post(client, url, data=None, follow=True):
    """POST with the CSRF token the pages normally carry."""
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
    return client.post(url, data={**(data or {}), "csrf": "tok"}, follow_redirects=follow)


def signup(app, email, name):
    """Register, read the demo OTP from the page, verify and log in. Returns a logged-in client."""
    client = app.test_client()
    page = post(client, "/register", {"email": email, "name": name, "password": PASSWORD}).get_data(as_text=True)
    code = re.search(r"code is (\d{6})", page).group(1)
    post(client, "/verify", {"email": email, "code": code})
    post(client, "/login", {"email": email, "password": PASSWORD})
    return client


def admin_client(app):
    client = app.test_client()
    post(client, "/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    return client


def stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M")


def make_driver(app):
    """A verified user who applied and was approved by the admin."""
    driver = signup(app, "dev@example.edu", "Dev")
    post(driver, "/driver/apply", {"model": "Swift", "reg_no": "KA01", "capacity": "5", "licence_no": "L123"})
    state = app.config["STATE"]
    driver_id = state.auth._users["dev@example.edu"].id
    post(admin_client(app), f"/admin/applications/{driver_id}/review", {"decision": "approve"})
    return driver


def test_landing_page_and_login_wall(app):  # TC-Web-01
    client = app.test_client()
    assert client.get("/").status_code == 200
    for url in ("/rides", "/history", "/offers/new", "/requests/new", "/notifications", "/admin"):
        resp = client.get(url)
        assert resp.status_code == 302 and "/login" in resp.headers["Location"]


def test_register_verify_login_flow(app):  # TC-Web-02
    client = signup(app, "asha@example.edu", "Asha")
    page = client.get("/").get_data(as_text=True)
    assert "Hello, Asha" in page


def test_registration_rejects_non_institutional_email(app):  # TC-Web-02
    page = post(app.test_client(), "/register",
                {"email": "me@gmail.com", "name": "Me", "password": PASSWORD}).get_data(as_text=True)
    assert "institutional email" in page


def test_wrong_password_shows_generic_error(app):  # TC-Web-02
    signup(app, "asha@example.edu", "Asha")
    page = post(app.test_client(), "/login", {"email": "asha@example.edu", "password": "nope1234"}).get_data(as_text=True)
    assert "Invalid credentials" in page


def test_post_without_csrf_token_is_rejected(app):  # TC-Web-03, TC-Sec-06
    assert app.test_client().post("/login", data={"email": "a@example.edu", "password": "x"}).status_code == 400


def test_rider_cannot_open_admin_or_post_offers(app):  # TC-Web-04, TC-Sec-04
    rider = signup(app, "asha@example.edu", "Asha")
    assert rider.get("/admin").status_code == 403
    resp = rider.get("/offers/new")
    assert resp.status_code == 302 and "/driver/apply" in resp.headers["Location"]


def test_full_rider_and_driver_journey(app):  # TC-Web-05
    driver = make_driver(app)
    rider = signup(app, "asha@example.edu", "Asha")
    now = datetime.now()
    dep = (now + timedelta(hours=2)).replace(second=0, microsecond=0)

    page = post(driver, "/offers/new", {"origin": "Main Gate", "destination": "Tech Park", "departure": stamp(dep),
                                        "seats": "3", "tags": "ac"}).get_data(as_text=True)
    assert "Ride offer posted" in page

    resp = post(rider, "/requests/new", {"pickup": "Library", "drop": "Sports Complex",
                                         "earliest": stamp(dep - timedelta(minutes=20)),
                                         "latest": stamp(dep + timedelta(minutes=20)), "seats": "1"})
    page = resp.get_data(as_text=True)
    assert "Matches for your request" in page and "Dev" in page and "Request to join" in page

    page = post(rider, "/offers/o1/join", {"seats": "1"}).get_data(as_text=True)
    assert "Join request sent" in page
    assert "Booking confirmed" in post(driver, "/bookings/b1/accept").get_data(as_text=True)

    post(rider, "/bookings/b1/chat", {"action": "send", "content": "See you at the gate"})
    assert "See you at the gate" in driver.get("/bookings/b1/chat").get_data(as_text=True)

    assert "Ride started" in post(driver, "/offers/o1/start").get_data(as_text=True)
    assert "Ride completed" in post(driver, "/offers/o1/complete").get_data(as_text=True)

    assert "Thanks for your rating" in post(rider, "/bookings/b1/rate", {"stars": "5", "comment": "Smooth"}).get_data(as_text=True)
    state = app.config["STATE"]
    assert state.ratings.average(state.auth._users["dev@example.edu"].id) == (5.0, 1)
    assert "completed" in rider.get("/history").get_data(as_text=True).lower()
    assert "request accepted" in rider.get("/notifications").get_data(as_text=True)


def test_chat_escapes_html(app):  # TC-Web-06, TC-Sec-06
    driver = make_driver(app)
    rider = signup(app, "asha@example.edu", "Asha")
    dep = (datetime.now() + timedelta(hours=2)).replace(second=0, microsecond=0)
    post(driver, "/offers/new", {"origin": "Main Gate", "destination": "Tech Park", "departure": stamp(dep), "seats": "2"})
    post(rider, "/offers/o1/join", {"seats": "1"})
    post(rider, "/bookings/b1/chat", {"action": "send", "content": "<script>alert(1)</script>"})
    page = rider.get("/bookings/b1/chat").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_admin_dashboard_suspend_and_csv(app):  # TC-Web-07
    rider = signup(app, "asha@example.edu", "Asha")
    admin = admin_client(app)
    page = admin.get("/admin").get_data(as_text=True)
    assert "Audit log" in page and "Asha" in page
    uid = app.config["STATE"].auth._users["asha@example.edu"].id
    assert "User suspended" in post(admin, f"/admin/users/{uid}/suspend", {"reason": "spam"}).get_data(as_text=True)
    csv = admin.get("/admin/analytics.csv")
    assert csv.mimetype == "text/csv" and csv.get_data(as_text=True).startswith("metric,value")
    assert rider.get("/rides").status_code == 302  # suspended users are logged out
    assert "USER_SUSPENDED" in admin.get("/admin").get_data(as_text=True)


def test_admin_can_change_match_radius(app):  # TC-Web-08
    admin = admin_client(app)
    assert "Setting saved" in post(admin, "/admin/config", {"key": "match_radius_m", "value": "500"}).get_data(as_text=True)
    assert app.config["STATE"].admin.config["match_radius_m"] == 500
    assert "Invalid value" in post(admin, "/admin/config", {"key": "match_radius_m", "value": "5"}).get_data(as_text=True)


def test_every_page_renders_for_each_role(app):  # TC-Web-09
    driver = make_driver(app)
    rider = signup(app, "asha@example.edu", "Asha")
    admin = admin_client(app)
    for client, urls in (
        (rider, ("/", "/requests/new", "/rides", "/history", "/notifications", "/driver/apply", "/history?role=rider&status=COMPLETED")),
        (driver, ("/offers/new", "/rides", "/driver/apply")),
        (admin, ("/admin", "/admin/analytics.csv")),
    ):
        for url in urls:
            assert client.get(url).status_code == 200, url
    assert rider.get("/nope").status_code == 404


def test_any_edu_domain_is_accepted_but_other_domains_are_not():  # TC-Web-10
    strict = create_app({"TESTING": True, "SECRET_KEY": "t"})
    page = post(strict.test_client(), "/register",
                {"email": "me@pes.edu", "name": "Me", "password": PASSWORD}).get_data(as_text=True)
    assert "institutional email" in page  # default: only the configured domain

    relaxed = create_app({"TESTING": True, "SECRET_KEY": "t", "ANY_EDU_DOMAIN": True})
    for email in ("me@pes.edu", "me@student.iitm.edu"):
        page = post(relaxed.test_client(), "/register",
                    {"email": email, "name": "Me", "password": PASSWORD}).get_data(as_text=True)
        assert "verification code" in page, email
    for email in ("me@gmail.com", "me@college.edu.in", "not-an-email", "me@.edu"):
        page = post(relaxed.test_client(), "/register",
                    {"email": email, "name": "Me", "password": PASSWORD}).get_data(as_text=True)
        assert "institutional email" in page, email
