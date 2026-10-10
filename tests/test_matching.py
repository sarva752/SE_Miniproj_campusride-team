from datetime import datetime, timedelta

import pytest

from campusride.geo import haversine_m, project_on_route
from campusride.matching import (filter_matches, find_matches, score_match,
                                 sort_matches)
from campusride.models import GeoPoint, OfferStatus, RideOffer, RideRequest

T0 = datetime(2026, 10, 13, 8, 0)
# Straight west->east route along latitude 13.00, roughly 10 km long
START, END = GeoPoint(13.00, 80.20), GeoPoint(13.00, 80.29)
ROUTE = [START, GeoPoint(13.00, 80.245), END]
PICK = GeoPoint(13.002, 80.22)   # ~220 m north of the route
DROP = GeoPoint(13.002, 80.27)


def offer(oid="o1", driver="d1", seats=3, dep=T0 + timedelta(minutes=15), route=ROUTE, **kw):
    return RideOffer(id=oid, driver_id=driver, origin=route[0], destination=route[-1], route=route,
                     departure=dep, seats_total=seats, seats_available=seats, **kw)


def request(**kw):
    args = dict(id="r1", rider_id="u1", pickup=PICK, drop=DROP, earliest=T0, latest=T0 + timedelta(minutes=30),
                seats_needed=1)
    args.update(kw)
    return RideRequest(**args)


def test_geo_distance_and_projection():
    assert haversine_m(START, END) == pytest.approx(9_850, rel=0.02)
    d, pos = project_on_route(GeoPoint(13.002, 80.245), ROUTE)
    assert d == pytest.approx(221, rel=0.03)
    assert pos == pytest.approx(haversine_m(START, GeoPoint(13.0, 80.245)), rel=0.02)


def test_compatible_offer_is_returned():  # TC-Match-01
    ms = find_matches([offer()], request())
    assert len(ms) == 1 and 0 < ms[0].score <= 1
    assert ms[0].detour_m == pytest.approx(442, rel=0.05)


@pytest.mark.parametrize("name,offers,req", [
    ("no seats", [offer(seats=1)], request(seats_needed=2)),
    ("out of window", [offer(dep=T0 + timedelta(hours=2))], request()),
    ("wrong direction", [offer(route=ROUTE[::-1])], request()),
    ("too far", [offer()], request(pickup=GeoPoint(13.05, 80.22))),
    ("not open", [offer(status=OfferStatus.FULL)], request()),
    ("own offer", [offer(driver="u1")], request()),
    ("missing hard preference", [offer()], request(preferences={"women_only"})),
])
def test_incompatible_offers_are_excluded(name, offers, req):  # TC-Match-02
    assert find_matches(offers, req) == [], name


def test_blocked_users_are_never_matched():  # CRS-F-042 link
    assert find_matches([offer()], request(), blocked={("u1", "d1")}) == []
    assert find_matches([offer()], request(), blocked={("d1", "u1")}) == []


def test_ranking_is_deterministic_and_prefers_better_offers():  # TC-Match-03
    near = offer("near", "d1", dep=T0 + timedelta(minutes=15))
    late = offer("late", "d2", dep=T0 + timedelta(minutes=29))
    ratings = {"d1": 4.9, "d2": 3.0}
    first = [m.offer.id for m in find_matches([late, near], request(), ratings)]
    second = [m.offer.id for m in find_matches([near, late], request(), ratings)]
    assert first == second == ["near", "late"]


def test_score_formula_with_fixed_inputs():  # TC-Match-03
    o, r = offer(dep=T0 + timedelta(minutes=15)), request()  # departure at window midpoint
    # detour 0 -> 0.4, time 1.0 -> 0.3, rating 5 -> 0.2, no nice_to_have -> 0.1
    assert score_match(o, r, 0.0, 1000.0, 5.0) == 1.0
    # new driver neutral rating 3/5 = 0.6 -> 0.12 instead of 0.2
    assert score_match(o, r, 0.0, 1000.0, None) == pytest.approx(0.92)


def test_soft_preferences_raise_score():
    base = find_matches([offer(tags={"no_smoking"})], request(nice_to_have={"no_smoking"}))[0].score
    low = find_matches([offer()], request(nice_to_have={"no_smoking"}))[0].score
    assert base > low


def test_sort_and_filter_results():  # TC-Match-05
    a = offer("a", "d1", dep=T0 + timedelta(minutes=25), seats=1)
    b = offer("b", "d2", dep=T0 + timedelta(minutes=5), seats=3)
    ms = find_matches([a, b], request(), {"d1": 5.0, "d2": 2.0})
    assert [m.offer.id for m in sort_matches(ms, "departure")] == ["b", "a"]
    assert [m.offer.id for m in sort_matches(ms, "seats")] == ["b", "a"]
    assert [m.offer.id for m in filter_matches(ms, {"d1": 5.0, "d2": 2.0}, min_rating=4)] == ["a"]
    assert [m.offer.id for m in filter_matches(ms, min_seats=2)] == ["b"]
    with pytest.raises(ValueError):
        sort_matches(ms, "bogus")

def test_custom_radius_controls_which_offers_match():
    # PICK and DROP are about 220 m from the route
    assert find_matches([offer()], request(), radius_m=150) == []
    assert len(find_matches([offer()], request(), radius_m=300)) == 1


def test_closer_pickup_ranks_higher_when_everything_else_is_equal():
    near = request(pickup=GeoPoint(13.0005, 80.22), drop=GeoPoint(13.0005, 80.27))
    far = request(pickup=PICK, drop=DROP)
    assert find_matches([offer()], near)[0].score > find_matches([offer()], far)[0].score
