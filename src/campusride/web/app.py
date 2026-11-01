"""Flask web UI for CampusRide.

The UI only calls the existing service classes (auth, rides, matching, booking, messaging,
ratings, notifications, admin); it holds no business rules of its own. All data lives in memory,
so it resets when the server restarts.
"""
from __future__ import annotations

import hmac
import os
import secrets
from datetime import datetime
from functools import wraps
from typing import Optional

from flask import Flask, Response, abort, flash, redirect, render_template, request, session, url_for

from ..admin import AdminService
from ..auth import AuthService
from ..booking import BookingService
from ..errors import CampusRideError, ConflictError, ValidationError
from ..matching import filter_matches, find_matches, sort_matches
from ..messaging import ChatService, RateLimited
from ..models import BookingStatus, GeoPoint, RideRequest, Role, User, UserStatus
from ..notifications import CHANNELS, NotificationService
from ..ratings import RatingService, ride_history
from ..rides import create_offer, create_request, has_overlapping_ride

# Named campus locations (all inside the default service area).
PLACES = {
    "Main Gate": GeoPoint(13.000, 80.200),
    "Library": GeoPoint(13.002, 80.220),
    "Hostel Block": GeoPoint(13.001, 80.245),
    "Sports Complex": GeoPoint(13.002, 80.270),
    "Tech Park": GeoPoint(13.000, 80.290),
}
PLACE_NAMES = {point: name for name, point in PLACES.items()}
TAGS = ("women_only", "no_smoking", "ac")
ADMIN_EMAIL, ADMIN_PASSWORD = "admin@example.edu", "Admin#2026a"  # demo admin account


class AppState:
    """One instance of every service, shared by all requests."""

    def __init__(self):
        self.auth = AuthService()
        self.bookings = BookingService()
        self.chat = ChatService()
        self.ratings = RatingService()
        self.notes = NotificationService()
        self.admin = AdminService()
        self.users: dict[str, User] = {}
        self.requests: dict[str, RideRequest] = {}
        self._seq = {"o": 0, "r": 0}

    def next_id(self, prefix: str) -> str:
        self._seq[prefix] += 1
        return f"{prefix}{self._seq[prefix]}"


def _seed_admin(state: AppState, now: datetime) -> None:
    _, code = state.auth.register(ADMIN_EMAIL, "Admin", ADMIN_PASSWORD, now)
    user = state.auth.verify_email(ADMIN_EMAIL, code, now)
    user.role = Role.ADMIN
    state.users[user.id] = user


# ---- small parsing helpers (they raise ValidationError, which the routes show as a message)
def place(name: Optional[str]) -> GeoPoint:
    if name not in PLACES:
        raise ValidationError("Choose a location from the list")
    return PLACES[name]


def to_int(value, label: str) -> int:
    try:
        return int(str(value).strip())
    except ValueError:
        raise ValidationError(f"{label} must be a whole number") from None


def parse_dt(value: Optional[str]) -> datetime:
    try:
        return datetime.fromisoformat((value or "").strip())
    except ValueError:
        raise ValidationError("Enter a valid date and time") from None


def optional_number(name: str, cast):
    raw = request.args.get(name, "").strip()
    try:
        return cast(raw) if raw else None
    except ValueError:
        return None


def create_app(config: Optional[dict] = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("CAMPUSRIDE_SECRET", "dev-only-change-me"),
        CLOCK=datetime.now,   # tests replace this
        SHOW_OTP=True,        # demo mode: no email server, so show the OTP on screen
        SEED_ADMIN=True,
        ANY_EDU_DOMAIN=False,  # accept any institution whose email domain ends in .edu (see register())
    )
    app.config.update(config or {})
    state = AppState()
    app.config["STATE"] = state

    def now() -> datetime:
        return app.config["CLOCK"]().replace(microsecond=0)

    if app.config["SEED_ADMIN"]:
        _seed_admin(state, now())

    def me() -> Optional[User]:
        return state.users.get(session.get("uid"))

    def csrf() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    def attempt(fn, ok_msg: Optional[str] = None):
        """Run a service call; show its error as a message instead of crashing."""
        try:
            result = fn()
        except (CampusRideError, RateLimited, ValueError) as exc:
            flash(str(exc), "error")
            return None, False
        if ok_msg:
            flash(ok_msg, "ok")
        return result, True

    def login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if me() is None:
                flash("Please log in first.", "error")
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapper

    def admin_required(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if me().role is not Role.ADMIN:
                abort(403)
            return view(*args, **kwargs)
        return wrapper

    def booking_for(booking_id: str):
        booking = state.bookings.bookings.get(booking_id)
        if booking is None:
            abort(404)
        if me().id not in (booking.rider_id, booking.driver_id):
            abort(403)
        return booking

    def notify(user_id: str, event: str, **payload) -> None:
        state.notes.notify(user_id, event, payload, now())

    # ------------------------------------------------------------------ hooks
    @app.before_request
    def guard():
        if request.method == "POST":  # CSRF token check on every form post
            sent, good = request.form.get("csrf", ""), session.get("csrf", "")
            if not good or not hmac.compare_digest(sent.encode(), good.encode()):
                abort(400)
        user = me()
        if user and user.status is UserStatus.SUSPENDED:
            session.clear()

    @app.context_processor
    def inject():
        user = me()
        count = 0
        if user:
            count = sum(1 for n in state.notes.outbox if n.user_id == user.id and n.channel == "in_app")
        return dict(
            csrf=csrf, me=user, note_count=count, Role=Role, BookingStatus=BookingStatus,
            places=list(PLACES), tags=TAGS,
            name_of=lambda uid: state.users[uid].name if uid in state.users else uid,
            label_of=state.ratings.display_label,
            pname=lambda p: PLACE_NAMES.get(p, f"{p.lat:.3f}, {p.lng:.3f}"),
        )

    @app.template_filter("dt")
    def fmt_dt(value):
        return value.strftime("%d %b %Y, %H:%M") if value else "-"

    for code, text in ((400, "Bad request (missing or invalid form token)"), (403, "You are not allowed to do that"),
                       (404, "Page not found")):
        app.register_error_handler(code, lambda e, code=code, text=text: (render_template("error.html", code=code, text=text), code))

    # ------------------------------------------------------------------ accounts
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            f = request.form
            email = f.get("email", "").strip().lower()
            domain = email.rsplit("@", 1)[-1] if "@" in email else ""
            if app.config["ANY_EDU_DOMAIN"] and domain.endswith(".edu"):
                # Any .edu institution is accepted; AuthService still checks the address format.
                state.auth.allowed_domains = frozenset(state.auth.allowed_domains) | {domain}
            res, ok = attempt(lambda: state.auth.register(email, f.get("name", ""), f.get("password", ""), now()))
            if ok:
                user, code = res
                state.users[user.id] = user
                if app.config["SHOW_OTP"]:
                    flash(f"Demo mode: no email is sent. Your verification code is {code}.", "info")
                return redirect(url_for("verify", email=user.email))
        return render_template("register.html")

    @app.route("/verify", methods=["GET", "POST"])
    def verify():
        email = request.values.get("email", "")
        if request.method == "POST":
            _, ok = attempt(lambda: state.auth.verify_email(email, request.form.get("code", "").strip(), now()),
                            "Email verified. You can log in now.")
            if ok:
                return redirect(url_for("login"))
        return render_template("verify.html", email=email)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            f = request.form
            user, ok = attempt(lambda: state.auth.login(f.get("email", ""), f.get("password", ""), now()))
            if ok:
                session.clear()
                session["uid"] = user.id
                flash(f"Welcome, {user.name}.", "ok")
                return redirect(url_for("index"))
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/driver/apply", methods=["GET", "POST"])
    @login_required
    def driver_apply():
        user = me()
        if request.method == "POST":
            f = request.form
            _, ok = attempt(lambda: state.admin.apply_as_driver(
                user, f.get("model", ""), f.get("reg_no", ""), to_int(f.get("capacity", ""), "Seat capacity"),
                f.get("licence_no", "")), "Application submitted. An admin will review it.")
            if ok:
                return redirect(url_for("driver_apply"))
        return render_template("driver_apply.html", application=state.admin.applications.get(user.id))

    # ------------------------------------------------------------------ offers, requests, matching
    @app.route("/offers/new", methods=["GET", "POST"])
    @login_required
    def offer_new():
        user = me()
        if not state.admin.can_post_offers(user):
            flash("You need an approved driver application before offering rides.", "error")
            return redirect(url_for("driver_apply"))
        capacity = state.admin.applications[user.id].capacity
        if request.method == "POST":
            f = request.form

            def build():
                origin, dest = place(f.get("origin")), place(f.get("destination"))
                if origin == dest:
                    raise ValidationError("Origin and destination must differ")
                offer = create_offer(state.next_id("o"), user.id, capacity, origin, dest, [origin, dest],
                                     parse_dt(f.get("departure")), to_int(f.get("seats", ""), "Seats"), now(),
                                     tags=set(f.getlist("tags")) & set(TAGS))
                state.bookings.add_offer(offer)
                return offer

            _, ok = attempt(build, "Ride offer posted.")
            if ok:
                return redirect(url_for("rides"))
        return render_template("offer_new.html", capacity=capacity)

    @app.route("/requests/new", methods=["GET", "POST"])
    @login_required
    def request_new():
        user = me()
        if request.method == "POST":
            f = request.form

            def build():
                req = create_request(state.next_id("r"), user.id, place(f.get("pickup")), place(f.get("drop")),
                                     parse_dt(f.get("earliest")), parse_dt(f.get("latest")),
                                     to_int(f.get("seats", ""), "Seats"), now(),
                                     preferences=set(f.getlist("required")) & set(TAGS),
                                     nice_to_have=set(f.getlist("preferred")) & set(TAGS))
                state.requests[req.id] = req
                return req

            req, ok = attempt(build, "Ride request created.")
            if ok:
                return redirect(url_for("matches", request_id=req.id))
        return render_template("request_new.html")

    @app.get("/requests/<request_id>/matches")
    @login_required
    def matches(request_id):
        req = state.requests.get(request_id)
        if req is None:
            abort(404)
        if req.rider_id != me().id:
            abort(403)
        ratings = state.ratings.ratings_map()
        found = find_matches(state.bookings.offers.values(), req, ratings=ratings,
                             radius_m=state.admin.config["match_radius_m"], blocked=state.chat.blocked_pairs())
        found = filter_matches(found, ratings, min_rating=optional_number("min_rating", float),
                               max_detour_m=optional_number("max_detour", float),
                               min_seats=optional_number("min_seats", int) or 1)
        sort_key = request.args.get("sort", "score")
        try:
            found = sort_matches(found, sort_key)
        except ValueError:
            sort_key = "score"
            found = sort_matches(found, sort_key)
        return render_template("matches.html", req=req, found=found, sort_key=sort_key, args=request.args)

    # ------------------------------------------------------------------ bookings
    @app.get("/rides")
    @login_required
    def rides():
        user = me()
        offers = state.bookings.offers
        all_bookings = list(state.bookings.bookings.values())
        offer_rows = [(o, [b for b in all_bookings if b.offer_id == o.id])
                      for o in offers.values() if o.driver_id == user.id]
        return render_template(
            "rides.html", offers=offers, offer_rows=offer_rows,
            as_rider=[b for b in all_bookings if b.rider_id == user.id],
            my_requests=[r for r in state.requests.values() if r.rider_id == user.id])

    @app.post("/offers/<offer_id>/join")
    @login_required
    def join(offer_id):
        user = me()
        offer = state.bookings.offers.get(offer_id)
        if offer is None:
            abort(404)

        def go():
            seats = to_int(request.form.get("seats", "1"), "Seats")
            confirmed = [b.departure for b in state.bookings.bookings.values()
                         if b.rider_id == user.id and b.status in (BookingStatus.CONFIRMED, BookingStatus.STARTED)]
            if has_overlapping_ride(confirmed, offer.departure):  # CRS-F-015
                raise ConflictError("You already have a confirmed ride at that time")
            booking = state.bookings.send_join_request(offer_id, user.id, seats, now())
            notify(offer.driver_id, "join_request_received", booking=booking.id)
            return booking

        attempt(go, "Join request sent. The driver has 30 minutes to respond.")
        return redirect(url_for("rides"))

    @app.post("/bookings/<booking_id>/accept")
    @login_required
    def accept(booking_id):
        booking = booking_for(booking_id)

        def go():
            result = state.bookings.accept(booking_id, me().id, now())
            notify(booking.rider_id, "request_accepted", booking=booking_id)
            return result

        attempt(go, "Booking confirmed.")
        return redirect(url_for("rides"))

    @app.post("/bookings/<booking_id>/reject")
    @login_required
    def reject(booking_id):
        booking = booking_for(booking_id)

        def go():
            result = state.bookings.reject(booking_id, me().id)
            notify(booking.rider_id, "request_rejected", booking=booking_id)
            return result

        attempt(go, "Request rejected.")
        return redirect(url_for("rides"))

    @app.post("/bookings/<booking_id>/cancel")
    @login_required
    def cancel(booking_id):
        booking = booking_for(booking_id)
        user = me()

        def go():
            result = state.bookings.cancel(booking_id, user.id, request.form.get("reason", ""), now())
            other = booking.driver_id if user.id == booking.rider_id else booking.rider_id
            notify(other, "booking_cancelled", booking=booking_id)
            return result

        attempt(go, "Booking cancelled.")
        return redirect(url_for("rides"))

    @app.post("/offers/<offer_id>/start")
    @login_required
    def start(offer_id):
        attempt(lambda: state.bookings.start_ride(offer_id, me().id), "Ride started.")
        return redirect(url_for("rides"))

    @app.post("/offers/<offer_id>/complete")
    @login_required
    def complete(offer_id):
        attempt(lambda: state.bookings.complete_ride(offer_id, me().id, now()),
                "Ride completed. You can now rate each other under History.")
        return redirect(url_for("rides"))

    # ------------------------------------------------------------------ chat, ratings, history
    @app.route("/bookings/<booking_id>/chat", methods=["GET", "POST"])
    @login_required
    def chat_view(booking_id):
        booking, user = booking_for(booking_id), me()
        partner = booking.driver_id if user.id == booking.rider_id else booking.rider_id
        if request.method == "POST":
            action = request.form.get("action", "send")
            if action == "send":
                def go():
                    msg = state.chat.send(booking, user.id, request.form.get("content", ""), now())
                    notify(partner, "new_message", booking=booking_id)
                    return msg
                attempt(go)
            elif action == "block":
                attempt(lambda: state.chat.block(user.id, partner), "User blocked.")
            elif action == "report":
                attempt(lambda: state.chat.report(user.id, partner, request.form.get("reason", "")),
                        "Report sent to the admins.")
            return redirect(url_for("chat_view", booking_id=booking_id))
        state.chat.mark_read(booking, user.id, now())
        return render_template("chat.html", booking=booking, partner=partner,
                               messages=state.chat.history(booking, user.id),
                               blocked=state.chat.is_blocked(user.id, partner))

    @app.post("/bookings/<booking_id>/rate")
    @login_required
    def rate(booking_id):
        booking = booking_for(booking_id)
        attempt(lambda: state.ratings.submit(booking, me().id, to_int(request.form.get("stars", ""), "Stars"),
                                             request.form.get("comment", ""), now()), "Thanks for your rating.")
        return redirect(url_for("history"))

    @app.get("/history")
    @login_required
    def history():
        user = me()
        role = request.args.get("role")
        role = role if role in ("rider", "driver") else None
        try:
            status = BookingStatus(request.args["status"]) if request.args.get("status") else None
        except ValueError:
            status = None
        rows = ride_history(state.bookings.bookings.values(), user.id, role=role, status=status)
        average, count = state.ratings.average(user.id)
        return render_template("history.html", rows=rows, offers=state.bookings.offers, role=role, status=status,
                               average=average, count=count,
                               statuses=[BookingStatus.COMPLETED, BookingStatus.CANCELLED, BookingStatus.REJECTED,
                                         BookingStatus.EXPIRED])

    # ------------------------------------------------------------------ notifications
    @app.route("/notifications", methods=["GET", "POST"])
    @login_required
    def notifications():
        user = me()
        if request.method == "POST":
            for channel in CHANNELS:
                state.notes.set_channel(user.id, channel, channel in request.form)
            flash("Notification settings saved.", "ok")
            return redirect(url_for("notifications"))
        mine = [n for n in state.notes.outbox if n.user_id == user.id and n.channel == "in_app"]
        prefs = state.notes.prefs.get(user.id)
        enabled = prefs.channels if prefs else {"in_app": True, "email": True, "push": False}
        return render_template("notifications.html", items=list(reversed(mine)), channels=CHANNELS, enabled=enabled)

    # ------------------------------------------------------------------ admin
    @app.get("/admin")
    @admin_required
    def admin_home():
        stats = AdminService.analytics(state.users.values(), state.bookings.offers.values(),
                                       state.bookings.bookings.values())
        return render_template(
            "admin.html", stats=stats, pending=state.admin.pending_applications(me()),
            users=list(state.users.values()), config=state.admin.config,
            audit=list(reversed(state.admin.audit_log())), reports=state.chat.reports,
            flagged=state.ratings.flagged)

    @app.get("/admin/analytics.csv")
    @admin_required
    def admin_csv():
        stats = AdminService.analytics(state.users.values(), state.bookings.offers.values(),
                                       state.bookings.bookings.values())
        return Response(AdminService.analytics_csv(stats), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=analytics.csv"})

    @app.post("/admin/applications/<user_id>/review")
    @admin_required
    def admin_review(user_id):
        target = state.users.get(user_id)
        if target is None:
            abort(404)
        approve = request.form.get("decision") == "approve"
        attempt(lambda: state.admin.review_application(me(), target, approve, request.form.get("reason", ""), now()),
                "Application approved." if approve else "Application rejected.")
        return redirect(url_for("admin_home"))

    @app.post("/admin/users/<user_id>/suspend")
    @admin_required
    def admin_suspend(user_id):
        target = state.users.get(user_id)
        if target is None:
            abort(404)
        if target.role is Role.ADMIN:
            flash("Administrators cannot be suspended here.", "error")
        else:
            attempt(lambda: state.admin.suspend_user(me(), target, request.form.get("reason", ""),
                                                     list(state.bookings.offers.values()),
                                                     list(state.requests.values()), now()), "User suspended.")
        return redirect(url_for("admin_home"))

    @app.post("/admin/config")
    @admin_required
    def admin_config():
        key = request.form.get("key", "")
        attempt(lambda: state.admin.update_config(me(), key, to_int(request.form.get("value", ""), "Value"), now()),
                "Setting saved.")
        return redirect(url_for("admin_home"))

    return app
