"""Geometry helpers for route proximity (CRS-F-020).

Uses a local equirectangular projection, accurate to well under 1% at campus scale.
"""
from __future__ import annotations

import math
from typing import Sequence

from .models import GeoPoint

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(a: GeoPoint, b: GeoPoint) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi = p2 - p1
    dlmb = math.radians(b.lng - a.lng)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _to_xy(p: GeoPoint, ref_lat: float) -> tuple[float, float]:
    x = math.radians(p.lng) * EARTH_RADIUS_M * math.cos(math.radians(ref_lat))
    y = math.radians(p.lat) * EARTH_RADIUS_M
    return x, y


def project_on_route(point: GeoPoint, route: Sequence[GeoPoint]) -> tuple[float, float]:
    """Return (distance_m from point to the route, position_m of the nearest point along the route)."""
    if len(route) < 2:
        raise ValueError("A route needs at least two points")
    ref = route[0].lat
    px, py = _to_xy(point, ref)
    best_d, best_pos, travelled = float("inf"), 0.0, 0.0
    for a, b in zip(route[:-1], route[1:]):
        ax, ay = _to_xy(a, ref)
        bx, by = _to_xy(b, ref)
        dx, dy = bx - ax, by - ay
        seg_len = math.hypot(dx, dy)
        t = 0.0 if seg_len == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len ** 2))
        cx, cy = ax + t * dx, ay + t * dy
        d = math.hypot(px - cx, py - cy)
        if d < best_d:
            best_d, best_pos = d, travelled + t * seg_len
        travelled += seg_len
    return best_d, best_pos
