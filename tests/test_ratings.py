from datetime import datetime, timedelta

import pytest

from campusride.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from campusride.models import Booking, BookingStatus
from campusride.ratings import RatingService, ride_history

END = datetime(2026, 10, 13, 10, 0)


def done(bid="b1", rider="r1", driver="d1", status=BookingStatus.COMPLETED, dep=None):
    dep = dep or END - timedelta(hours=1)
    return Booking(id=bid, offer_id="o1", driver_id=driver, rider_id=rider, seats=1, status=status,
                   created_at=dep - timedelta(days=1), departure=dep, ended_at=END)


def test_valid_rating_after_completion():  # TC-Rate-01
    svc = RatingService()
    r = svc.submit(done(), "r1", 5, "Great driver", END + timedelta(hours=1))
    assert (r.ratee_id, r.stars) == ("d1", 5)
    assert svc.submit(done(), "d1", 4, "", END).ratee_id == "r1"  # mutual rating


@pytest.mark.parametrize("stars", [0, 6, 4.5, "5", True])
def test_stars_must_be_whole_1_to_5(stars):  # TC-Rate-02
    with pytest.raises(ValidationError):
        RatingService().submit(done(), "r1", stars, "", END)


def test_duplicate_late_and_non_participant_rejected():  # TC-Rate-02
    svc = RatingService()
    svc.submit(done(), "r1", 5, "", END)
    with pytest.raises(ConflictError):
        svc.submit(done(), "r1", 4, "", END)
    with pytest.raises(ConflictError):
        RatingService().submit(done(), "r1", 4, "", END + timedelta(days=7, seconds=1))
    assert RatingService().submit(done(), "r1", 4, "", END + timedelta(days=7))  # boundary OK
    with pytest.raises(PermissionDenied):
        RatingService().submit(done(), "stranger", 4, "", END)
    with pytest.raises(ConflictError):
        RatingService().submit(done(status=BookingStatus.CONFIRMED), "r1", 4, "", END)
    with pytest.raises(ValidationError):
        RatingService().submit(done(), "r1", 4, "x" * 301, END)


def test_average_and_new_label():  # TC-Rate-03
    svc = RatingService()
    assert svc.average("d1") == (None, 0) and svc.display_label("d1") == "New"
    for i, stars in enumerate([5, 4, 3], start=1):
        svc.submit(done(bid=f"b{i}", rider=f"r{i}"), f"r{i}", stars, "", END)
        if i < 3:
            assert svc.display_label("d1") == "New"
    assert svc.average("d1") == (4.0, 3)
    assert svc.display_label("d1") == "4.0 (3)"
    assert svc.ratings_map() == {"d1": 4.0}


def test_ratings_immutable_and_flaggable():  # TC-Rate-04
    svc = RatingService()
    r = svc.submit(done(), "r1", 1, "rude", END)
    with pytest.raises(Exception):
        r.stars = 5  # type: ignore[misc]
    svc.flag_comment(r.id, "d1")
    assert svc.flagged == [(r.id, "d1")]
    with pytest.raises(NotFound):
        svc.flag_comment(99, "d1")


def test_history_shows_only_own_rides_with_filters():  # TC-Hist-01
    base = END
    bs = [
        done("b1", "r1", "d1", dep=base - timedelta(days=3)),
        done("b2", "r2", "r1", dep=base - timedelta(days=2)),                 # r1 drove this one
        done("b3", "r3", "d9", dep=base - timedelta(days=1)),                 # someone else's
        done("b4", "r1", "d1", BookingStatus.CANCELLED, base - timedelta(days=1)),
        done("b5", "r1", "d1", BookingStatus.CONFIRMED, base + timedelta(days=1)),  # upcoming, not history
    ]
    ids = lambda xs: [b.id for b in xs]
    assert ids(ride_history(bs, "r1")) == ["b4", "b2", "b1"]            # newest first, no strangers
    assert ids(ride_history(bs, "r1", role="driver")) == ["b2"]
    assert ids(ride_history(bs, "r1", role="rider")) == ["b4", "b1"]
    assert ids(ride_history(bs, "r1", status=BookingStatus.CANCELLED)) == ["b4"]
    assert ids(ride_history(bs, "r1", start=base - timedelta(days=2, hours=1))) == ["b4", "b2"]
    assert ride_history(bs, "nobody") == []



def test_comment_of_exactly_300_characters_is_accepted():
    assert RatingService().submit(done(), "r1", 5, "x" * 300, END)
