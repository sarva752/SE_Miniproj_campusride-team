"""Core domain model (see SAD Figure 2 - class diagram)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Role(str, Enum):
    RIDER = "RIDER"
    DRIVER = "DRIVER"
    ADMIN = "ADMIN"


class UserStatus(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OfferStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RequestStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lng: float


@dataclass
class User:
    id: str
    email: str
    name: str
    role: Role = Role.RIDER
    status: UserStatus = UserStatus.INACTIVE


@dataclass
class RideOffer:
    id: str
    driver_id: str
    origin: GeoPoint
    destination: GeoPoint
    route: list  # list[GeoPoint] polyline from origin to destination
    departure: datetime
    seats_total: int
    seats_available: int
    status: OfferStatus = OfferStatus.OPEN
    tags: set = field(default_factory=set)  # e.g. {"women_only", "no_smoking"}


@dataclass
class RideRequest:
    id: str
    rider_id: str
    pickup: GeoPoint
    drop: GeoPoint
    earliest: datetime
    latest: datetime
    seats_needed: int = 1
    preferences: set = field(default_factory=set)   # hard requirements (tags)
    nice_to_have: set = field(default_factory=set)  # soft preferences (tags)
    status: RequestStatus = RequestStatus.OPEN


@dataclass
class Booking:
    id: str
    offer_id: str
    driver_id: str
    rider_id: str
    seats: int
    status: BookingStatus = BookingStatus.PENDING
    created_at: Optional[datetime] = None
    departure: Optional[datetime] = None
    ended_at: Optional[datetime] = None
