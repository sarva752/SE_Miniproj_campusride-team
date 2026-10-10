"""Registration, OTP verification, login and lockout (CRS-F-001..003, CRS-SR-002).

Time is passed in explicitly (``now``) so behaviour is deterministic in tests.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from .errors import AuthenticationError, ConflictError, ValidationError
from .models import Role, User, UserStatus

OTP_TTL = timedelta(minutes=10)
LOCK_AFTER_FAILURES = 5
LOCK_DURATION = timedelta(minutes=15)
DEFAULT_DOMAINS = frozenset({"example.edu"})

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})$")


def is_institutional_email(email: str, allowed_domains=DEFAULT_DOMAINS) -> bool:
    m = _EMAIL_RE.match(email or "")
    return bool(m) and m.group(1).lower() in {d.lower() for d in allowed_domains}


def validate_password(password: str) -> None:
    """Minimum 8 characters with letters and digits (CRS-SR-002)."""
    if len(password or "") < 8:
        raise ValidationError("Password must be at least 8 characters")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValidationError("Password must contain letters and digits")


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """Salted scrypt hash, stored as ``salt$hash`` (hex). Never store plain text."""
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    salt_hex, hash_hex = stored.split("$")
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1)
    return hmac.compare_digest(digest.hex(), hash_hex)


class OtpService:
    """Six-digit single-use OTP valid for 10 minutes."""

    def __init__(self):
        self._codes: dict[str, tuple[str, datetime]] = {}

    def issue(self, email: str, now: datetime) -> str:
        code = f"{secrets.randbelow(10 ** 6):06d}"
        self._codes[email.lower()] = (code, now + OTP_TTL)
        return code

    def verify(self, email: str, code: str, now: datetime) -> bool:
        entry = self._codes.get(email.lower())
        if not entry:
            return False
        stored, expires = entry
        if now > expires or not hmac.compare_digest(stored, str(code)):
            return False
        del self._codes[email.lower()]  # single use
        return True


class AuthService:
    def __init__(self, allowed_domains=DEFAULT_DOMAINS):
        self.allowed_domains = allowed_domains
        self.otp = OtpService()
        self._users: dict[str, User] = {}
        self._hashes: dict[str, str] = {}
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, datetime] = {}
        self.audit: list[tuple[datetime, str, str]] = []  # (time, event, email)

    # CRS-F-001
    def register(self, email: str, name: str, password: str, now: datetime):
        email = (email or "").strip().lower()
        if not is_institutional_email(email, self.allowed_domains):
            raise ValidationError("Use your institutional email address")
        if not (name or "").strip():
            raise ValidationError("Name is required")
        validate_password(password)
        if email in self._users:
            raise ConflictError("Email already registered")
        user = User(id=f"u{len(self._users) + 1}", email=email, name=name.strip(),
                    role=Role.RIDER, status=UserStatus.INACTIVE)
        self._users[email] = user
        self._hashes[email] = hash_password(password)
        return user, self.otp.issue(email, now)

    def verify_email(self, email: str, code: str, now: datetime) -> User:
        email = email.strip().lower()
        if email not in self._users or not self.otp.verify(email, code, now):
            raise ValidationError("Invalid or expired OTP")
        self._users[email].status = UserStatus.ACTIVE
        return self._users[email]

    # CRS-F-002 / CRS-F-003
    def login(self, email: str, password: str, now: datetime) -> User:
        email = (email or "").strip().lower()
        locked = self._locked_until.get(email)
        if locked and now < locked:
            raise AuthenticationError("Account locked, try again later")
        user = self._users.get(email)
        ok = bool(user) and verify_password(password, self._hashes[email])
        if not ok:
            self._record_failure(email, now)
            raise AuthenticationError("Invalid credentials")  # generic message
        if user.status is UserStatus.INACTIVE:
            raise AuthenticationError("Account not verified")
        if user.status is UserStatus.SUSPENDED:
            raise AuthenticationError("Account suspended")
        self._failures.pop(email, None)
        self._locked_until.pop(email, None)
        return user

    def _record_failure(self, email: str, now: datetime) -> None:
        self._failures[email] = self._failures.get(email, 0) + 1
        if self._failures[email] >= LOCK_AFTER_FAILURES:
            self._locked_until[email] = now + LOCK_DURATION
            self._failures[email] = 0
            self.audit.append((now, "ACCOUNT_LOCKED", email))
