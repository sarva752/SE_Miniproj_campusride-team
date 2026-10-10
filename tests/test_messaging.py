from datetime import datetime, timedelta

import pytest

from campusride.errors import PermissionDenied, ValidationError
from campusride.messaging import ChatService, RateLimited
from campusride.models import Booking, BookingStatus

NOW = datetime(2026, 10, 13, 8, 0)


def booking(status=BookingStatus.CONFIRMED, ended_at=None):
    return Booking(id="b1", offer_id="o1", driver_id="d1", rider_id="r1", seats=1, status=status,
                   created_at=NOW, departure=NOW + timedelta(hours=1), ended_at=ended_at)


def test_only_booking_participants_can_chat():  # TC-Msg-01
    chat, b = ChatService(), booking()
    chat.send(b, "r1", "Hi", NOW)
    chat.send(b, "d1", "Hello", NOW)
    with pytest.raises(PermissionDenied):
        chat.send(b, "stranger", "hey", NOW)
    with pytest.raises(PermissionDenied):
        chat.history(b, "stranger")


def test_pending_booking_allows_chat_but_rejected_does_not():
    chat = ChatService()
    chat.send(booking(BookingStatus.PENDING), "r1", "Is the pickup at gate 2?", NOW)
    with pytest.raises(PermissionDenied):
        chat.send(booking(BookingStatus.REJECTED), "r1", "hi", NOW)


def test_messages_persist_with_read_status():  # TC-Msg-02
    chat, b = ChatService(), booking()
    chat.send(b, "r1", "On my way", NOW)
    assert len(chat.history(b, "d1")) == 1
    assert chat.mark_read(b, "d1", NOW + timedelta(seconds=2)) == 1
    assert chat.history(b, "r1")[0].read_at == NOW + timedelta(seconds=2)
    assert chat.mark_read(b, "d1", NOW) == 0  # already read


def test_block_and_report():  # TC-Msg-03
    chat, b = ChatService(), booking()
    chat.block("d1", "r1")
    for sender in ("r1", "d1"):  # blocked in both directions
        with pytest.raises(PermissionDenied):
            chat.send(b, sender, "hello", NOW)
    assert ("d1", "r1") in chat.blocked_pairs()
    chat.report("d1", "r1", "abusive language")
    assert chat.reports == [("d1", "r1", "abusive language")]
    with pytest.raises(ValidationError):
        chat.report("d1", "r1", "  ")


def test_chat_becomes_read_only_24h_after_ride_end():  # TC-Msg-04
    ended = NOW
    chat, b = ChatService(), booking(BookingStatus.COMPLETED, ended)
    chat.send(b, "r1", "thanks!", ended + timedelta(hours=23))
    with pytest.raises(PermissionDenied):
        chat.send(b, "r1", "one more", ended + timedelta(hours=25))
    assert len(chat.history(b, "r1")) == 1  # history stays readable


def test_length_limit_and_sanitisation():  # TC-Msg-05
    chat, b = ChatService(), booking()
    assert chat.send(b, "r1", "x" * 1000, NOW)  # boundary OK
    with pytest.raises(ValidationError):
        chat.send(b, "r1", "x" * 1001, NOW)
    with pytest.raises(ValidationError):
        chat.send(b, "r1", "   ", NOW)
    m = chat.send(b, "r1", "<script>alert(1)</script>", NOW)
    assert "<script>" not in m.content and "&lt;script&gt;" in m.content


def test_rate_limit_30_per_minute():  # TC-Sec-07
    chat, b = ChatService(), booking()
    for i in range(30):
        chat.send(b, "r1", f"m{i}", NOW)
    with pytest.raises(RateLimited):
        chat.send(b, "r1", "31st", NOW + timedelta(seconds=30))
    assert chat.send(b, "r1", "later", NOW + timedelta(seconds=61))
def test_block_does_not_affect_other_pairs():
    chat = ChatService()
    chat.block("d1", "r1")
    other = Booking(id="b2", offer_id="o2", driver_id="d2", rider_id="r1", seats=1,
                    status=BookingStatus.CONFIRMED, created_at=NOW,
                    departure=NOW + timedelta(hours=1))
    assert chat.send(other, "r1", "hi", NOW)