"""Ride offers and requests: creation, validation and overlap checks.

Covers CRS-F-010, CRS-F-012, CRS-F-014, CRS-F-015.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from .errors import ValidationError
from .models import GeoPoint, RideOffer, RideRequest


@dataclass(frozen=True)
class ServiceArea:
    """Rectangular service area (configurable by admin, CRS-F-072)."""
    min_lat: float = 12.90
    max_lat: float = 13.20
    min_lng: float = 80.10
    max_lng: float = 80.35

    def contains(self, p: GeoPoint) -> bool:
        return self.min_lat <= p.lat <= self.max_lat and self.min_lng <= p.lng <= self.max_lng


DEFAULT_AREA = ServiceArea()
DEFAULT_RIDE_DURATION = timedelta(hours=1)


def validate_location(p: GeoPoint, area: ServiceArea = DEFAULT_AREA) -> GeoPoint:
    if not (-90 <= p.lat <= 90 and -180 <= p.lng <= 180):
        raise ValidationError("Invalid coordinates")
    if not area.contains(p):
        raise ValidationError("Location is outside the service area")
    return p


def create_offer(offer_id: str, driver_id: str, vehicle_capacity: int, origin: GeoPoint,
                 destination: GeoPoint, route: Optional[list], departure: datetime, seats: int,
                 now: datetime, area: ServiceArea = DEFAULT_AREA, tags: Optional[set] = None) -> RideOffer:
    """Seats must be 1..capacity-1 (driver occupies one seat); departure in the future."""
    validate_location(origin, area)
    validate_location(destination, area)
    if departure <= now:
        raise ValidationError("Departure time must be in the future")
    if not 1 <= seats <= max(vehicle_capacity - 1, 0):
        raise ValidationError("Seats must be between 1 and vehicle capacity minus 1")
    route = list(route) if route else [origin, destination]
    for p in route:
        validate_location(p, area)
    return RideOffer(id=offer_id, driver_id=driver_id, origin=origin, destination=destination,
                     route=route, departure=departure, seats_total=seats, seats_available=seats,
                     tags=set(tags or ()))


def create_request(request_id: str, rider_id: str, pickup: GeoPoint, drop: GeoPoint,
                   earliest: datetime, latest: datetime, seats_needed: int, now: datetime,
                   area: ServiceArea = DEFAULT_AREA, preferences: Optional[set] = None,
                   nice_to_have: Optional[set] = None) -> RideRequest:
    validate_location(pickup, area)
    validate_location(drop, area)
    if pickup == drop:
        raise ValidationError("Pickup and drop must differ")
    if earliest < now or latest < earliest:
        raise ValidationError("Invalid time window")
    if not 1 <= seats_needed <= 4:
        raise ValidationError("Seats needed must be between 1 and 4")
    return RideRequest(id=request_id, rider_id=rider_id, pickup=pickup, drop=drop, earliest=earliest,
                       latest=latest, seats_needed=seats_needed, preferences=set(preferences or ()),
                       nice_to_have=set(nice_to_have or ()))


def time_ranges_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def has_overlapping_ride(existing_departures: Iterable[datetime], new_departure: datetime,
                         duration: timedelta = DEFAULT_RIDE_DURATION) -> bool:
    """CRS-F-015: a user may not hold two confirmed rides that overlap in time."""
    new_end = new_departure + duration
    return any(time_ranges_overlap(d, d + duration, new_departure, new_end) for d in existing_departures)
