"""Administration: driver verification, sanctions, configuration, analytics, audit log.

Covers CRS-F-006, CRS-F-070..074 and CRS-SR-003/009.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .errors import ConflictError, NotFound, PermissionDenied, ValidationError
from .models import OfferStatus, RequestStatus, Role, User, UserStatus

DEFAULT_CONFIG = {
    "match_radius_m": 1000,
    "request_expiry_min": 30,
    "rating_window_days": 7,
    "allowed_domains": ["example.edu"],
}
CONFIG_RULES = {
    "match_radius_m": lambda v: isinstance(v, int) and 100 <= v <= 10_000,
    "request_expiry_min": lambda v: isinstance(v, int) and 5 <= v <= 1440,
    "rating_window_days": lambda v: isinstance(v, int) and 1 <= v <= 30,
    "allowed_domains": lambda v: isinstance(v, list) and len(v) > 0 and all(isinstance(d, str) and "." in d for d in v),
}


@dataclass
class DriverApplication:
    user_id: str
    model: str
    reg_no: str
    capacity: int
    licence_no: str
    status: str = "PENDING"  # PENDING / APPROVED / REJECTED
    reason: str = ""


class AdminService:
    def __init__(self):
        self.applications: dict[str, DriverApplication] = {}
        self.config = dict(DEFAULT_CONFIG)
        self._audit: list[tuple[datetime, str, str, str]] = []  # append-only (time, actor, action, detail)
        self.users: dict[str, User] = {}

    # ---- audit log (CRS-F-074, CRS-SR-009): read access returns a copy, no edit/delete API
    def log(self, actor: str, action: str, detail: str, now: datetime) -> None:
        self._audit.append((now, actor, action, detail))

    def audit_log(self) -> tuple:
        return tuple(self._audit)

    @staticmethod
    def _require_admin(user: User) -> None:
        if user.role is not Role.ADMIN:
            raise PermissionDenied("Administrator role required")  # CRS-SR-003

    # ---- driver verification (CRS-F-006, CRS-F-070)
    def apply_as_driver(self, user: User, model: str, reg_no: str, capacity: int, licence_no: str) -> DriverApplication:
        if not (model or "").strip() or not (reg_no or "").strip() or not (licence_no or "").strip():
            raise ValidationError("Vehicle model, registration number and licence are required")
        if not 2 <= capacity <= 8:
            raise ValidationError("Seat capacity must be between 2 and 8")
        existing = self.applications.get(user.id)
        if existing and existing.status == "PENDING":
            raise ConflictError("Application already pending")
        app = DriverApplication(user.id, model.strip(), reg_no.strip(), capacity, licence_no.strip())
        self.applications[user.id] = app
        return app

    def pending_applications(self, admin: User) -> list:
        self._require_admin(admin)
        return [a for a in self.applications.values() if a.status == "PENDING"]

    def review_application(self, admin: User, user: User, approve: bool, reason: str, now: datetime) -> DriverApplication:
        self._require_admin(admin)
        app = self.applications.get(user.id)
        if not app:
            raise NotFound("No application for this user")
        if not approve and not (reason or "").strip():
            raise ValidationError("A reason is required when rejecting")
        app.status, app.reason = ("APPROVED", "") if approve else ("REJECTED", reason.strip())
        if approve:
            user.role = Role.DRIVER
        self.log(admin.id, "DRIVER_APPROVED" if approve else "DRIVER_REJECTED", user.id, now)
        return app

    def can_post_offers(self, user: User) -> bool:
        app = self.applications.get(user.id)
        return user.role is Role.DRIVER and bool(app) and app.status == "APPROVED"

    # ---- moderation (CRS-F-071)
    def suspend_user(self, admin: User, user: User, reason: str, offers: list, requests: list, now: datetime) -> User:
        self._require_admin(admin)
        if not (reason or "").strip():
            raise ValidationError("A reason is required")
        user.status = UserStatus.SUSPENDED
        for o in offers:
            if o.driver_id == user.id and o.status in (OfferStatus.OPEN, OfferStatus.FULL):
                o.status = OfferStatus.CANCELLED
        for r in requests:
            if r.rider_id == user.id and r.status is RequestStatus.OPEN:
                r.status = RequestStatus.CANCELLED
        self.log(admin.id, "USER_SUSPENDED", f"{user.id}: {reason.strip()}", now)
        return user

    # ---- configuration (CRS-F-072)
    def update_config(self, admin: User, key: str, value, now: datetime) -> dict:
        self._require_admin(admin)
        if key not in CONFIG_RULES:
            raise ValidationError(f"Unknown setting: {key}")
        if not CONFIG_RULES[key](value):
            raise ValidationError(f"Invalid value for {key}")
        old = self.config[key]
        self.config[key] = value
        self.log(admin.id, "CONFIG_CHANGED", f"{key}: {old} -> {value}", now)
        return dict(self.config)

    # ---- analytics (CRS-F-073)
    @staticmethod
    def analytics(users, offers, bookings) -> dict:
        from .models import BookingStatus
        total = len(bookings)
        matched = sum(b.status in (BookingStatus.CONFIRMED, BookingStatus.STARTED, BookingStatus.COMPLETED) for b in bookings)
        cancelled = sum(b.status is BookingStatus.CANCELLED for b in bookings)
        return {
            "active_users": sum(u.status is UserStatus.ACTIVE for u in users),
            "offers": len(offers),
            "bookings": total,
            "rides_matched": matched,
            "match_rate": round(matched / total, 4) if total else 0.0,
            "cancellations": cancelled,
        }

    @staticmethod
    def analytics_csv(stats: dict) -> str:
        return "metric,value\n" + "\n".join(f"{k},{v}" for k, v in stats.items()) + "\n"
