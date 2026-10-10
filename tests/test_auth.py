from datetime import datetime, timedelta

import pytest

from campusride.auth import (AuthService, OtpService, hash_password,
                             is_institutional_email, validate_password,
                             verify_password)
from campusride.errors import AuthenticationError, ConflictError, ValidationError
from campusride.models import UserStatus

NOW = datetime(2026, 10, 12, 9, 0)
PW = "Ride#2026a"


def make_verified(svc=None):
    svc = svc or AuthService()
    _, code = svc.register("asha@example.edu", "Asha K", PW, NOW)
    svc.verify_email("asha@example.edu", code, NOW)
    return svc


def test_institutional_email_rules():  # TC-Auth-02
    assert is_institutional_email("a@example.edu")
    assert is_institutional_email("A@EXAMPLE.EDU")
    assert not is_institutional_email("a@gmail.com")
    assert not is_institutional_email("not-an-email")


@pytest.mark.parametrize("pw", ["short1", "allletters", "12345678"])
def test_password_policy_rejects_weak(pw):  # CRS-SR-002
    with pytest.raises(ValidationError):
        validate_password(pw)


def test_password_hash_is_salted_and_verifiable():  # TC-Sec-03
    h1, h2 = hash_password(PW), hash_password(PW)
    assert h1 != h2 and PW not in h1
    assert verify_password(PW, h1) and not verify_password("wrong", h1)


def test_register_and_verify_flow():  # TC-Auth-01
    svc = AuthService()
    user, code = svc.register("asha@example.edu", "Asha K", PW, NOW)
    assert user.status is UserStatus.INACTIVE
    with pytest.raises(AuthenticationError):
        svc.login("asha@example.edu", PW, NOW)  # not yet verified
    svc.verify_email("asha@example.edu", code, NOW + timedelta(minutes=5))
    assert svc.login("asha@example.edu", PW, NOW).status is UserStatus.ACTIVE


def test_register_rejects_foreign_domain_and_duplicates():  # TC-Auth-02
    svc = AuthService()
    with pytest.raises(ValidationError):
        svc.register("x@gmail.com", "X", PW, NOW)
    svc.register("a@example.edu", "A", PW, NOW)
    with pytest.raises(ConflictError):
        svc.register("a@example.edu", "A", PW, NOW)


def test_otp_expiry_wrong_code_and_single_use():  # TC-Auth-02
    otp = OtpService()
    code = otp.issue("a@example.edu", NOW)
    assert not otp.verify("a@example.edu", "000000" if code != "000000" else "111111", NOW)
    assert not otp.verify("a@example.edu", code, NOW + timedelta(minutes=11))
    code = otp.issue("a@example.edu", NOW)
    assert otp.verify("a@example.edu", code, NOW + timedelta(minutes=9))
    assert not otp.verify("a@example.edu", code, NOW)  # already used


def test_login_valid_and_invalid_generic_error():  # TC-Auth-03
    svc = make_verified()
    assert svc.login("asha@example.edu", PW, NOW).name == "Asha K"
    with pytest.raises(AuthenticationError) as e1:
        svc.login("asha@example.edu", "wrongpass1", NOW)
    with pytest.raises(AuthenticationError) as e2:
        svc.login("nobody@example.edu", "wrongpass1", NOW)
    assert str(e1.value) == str(e2.value)  # no user enumeration


def test_lockout_after_five_failures_and_audit():  # TC-Auth-05
    svc = make_verified()
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            svc.login("asha@example.edu", "bad-pass-1", NOW)
    with pytest.raises(AuthenticationError, match="locked"):
        svc.login("asha@example.edu", PW, NOW + timedelta(minutes=5))
    assert svc.audit and svc.audit[0][1] == "ACCOUNT_LOCKED"
    # unlocked after 15 minutes
    assert svc.login("asha@example.edu", PW, NOW + timedelta(minutes=16))
def test_successful_login_resets_failure_counter():  # TC-Auth-05
    svc = make_verified()
    for _ in range(4):
        with pytest.raises(AuthenticationError):
            svc.login("asha@example.edu", "bad-pass-1", NOW)
    assert svc.login("asha@example.edu", PW, NOW)  # success clears the counter
    for _ in range(4):
        with pytest.raises(AuthenticationError):
            svc.login("asha@example.edu", "bad-pass-1", NOW)
    assert svc.login("asha@example.edu", PW, NOW)  # 4 + 4 failures, but never 5 in a row
    assert svc.audit == []  # no lockout was triggered
