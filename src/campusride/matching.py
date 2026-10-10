"""Matching engine: filter, direction check, scoring and ranking.

Covers CRS-F-020, CRS-F-021, CRS-F-023 (see SAD section 4.1.2).

score = 0.40*(1 - detour/maxDetour) + 0.30*timeScore + 0.20*(rating/5) + 0.10*preferenceMatch
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .geo import project_on_route
from .models import OfferStatus, RideOffer, RideRequest

DEFAULT_RADIUS_M = 1000.0
NEW_DRIVER_RATING = 3.0  # neutral 0.6 after dividing by 5
WEIGHTS = (0.40, 0.30, 0.20, 0.10)


@dataclass
class Match:
    offer: RideOffer
    score: float
    detour_m: float
    pickup_distance_m: float
    drop_distance_m: float


def _evaluate(offer: RideOffer, req: RideRequest, radius_m: float, blocked: set):
    """Return (pickup_dist, drop_dist) if compatible else None."""
    if offer.status is not OfferStatus.OPEN:
        return None
    if offer.seats_available < req.seats_needed:
        return None
    if not (req.earliest <= offer.departure <= req.latest):
        return None
    if (req.rider_id, offer.driver_id) in blocked or (offer.driver_id, req.rider_id) in blocked:
        return None
    if offer.driver_id == req.rider_id:
        return None
    if not req.preferences <= offer.tags:  # hard preferences
        return None
    d_pick, pos_pick = project_on_route(req.pickup, offer.route)
    d_drop, pos_drop = project_on_route(req.drop, offer.route)
    if d_pick > radius_m or d_drop > radius_m:
        return None
    if pos_pick >= pos_drop:  # wrong direction: pickup must come before drop
        return None
    return d_pick, d_drop


def score_match(offer: RideOffer, req: RideRequest, detour_m: float, radius_m: float,
                driver_rating: Optional[float], weights=WEIGHTS) -> float:
    w_detour, w_time, w_rating, w_pref = weights
    detour_score = max(0.0, 1.0 - detour_m / (2 * radius_m))
    half_window = (req.latest - req.earliest).total_seconds() / 2
    if half_window <= 0:
        time_score = 1.0
    else:
        mid = req.earliest + (req.latest - req.earliest) / 2
        time_score = max(0.0, 1.0 - abs((offer.departure - mid).total_seconds()) / half_window)
    rating = NEW_DRIVER_RATING if driver_rating is None else driver_rating
    pref = 1.0 if not req.nice_to_have else len(req.nice_to_have & offer.tags) / len(req.nice_to_have)
    total = w_detour * detour_score + w_time * time_score + w_rating * (rating / 5.0) + w_pref * pref
    return round(max(0.0, min(1.0, total)), 4)


def find_matches(offers: Iterable[RideOffer], req: RideRequest, ratings: Optional[dict] = None,
                 radius_m: float = DEFAULT_RADIUS_M, blocked: Optional[set] = None) -> list:
    """Return compatible offers ranked by descending score (ties: earlier departure)."""
    ratings, blocked = ratings or {}, blocked or set()
    out = []
    for offer in offers:
        res = _evaluate(offer, req, radius_m, blocked)
        if res is None:
            continue
        d_pick, d_drop = res
        detour = d_pick + d_drop
        s = score_match(offer, req, detour, radius_m, ratings.get(offer.driver_id))
        out.append(Match(offer, s, detour, d_pick, d_drop))
    out.sort(key=lambda m: (-m.score, m.offer.departure))
    return out


def sort_matches(matches: list, key: str = "score") -> list:
    """CRS-F-023: sort by score, departure, detour or seats."""
    keys = {
        "score": lambda m: (-m.score, m.offer.departure),
        "departure": lambda m: m.offer.departure,
        "detour": lambda m: m.detour_m,
        "seats": lambda m: -m.offer.seats_available,
    }
    if key not in keys:
        raise ValueError(f"Unknown sort key: {key}")
    return sorted(matches, key=keys[key])


def filter_matches(matches: list, ratings: Optional[dict] = None, min_rating: Optional[float] = None,
                   max_detour_m: Optional[float] = None, min_seats: int = 1) -> list:
    ratings = ratings or {}
    out = []
    for m in matches:
        if m.offer.seats_available < min_seats:
            continue
        if max_detour_m is not None and m.detour_m > max_detour_m:
            continue
        if min_rating is not None and ratings.get(m.offer.driver_id, 0) < min_rating:
            continue
        out.append(m)
    return out
