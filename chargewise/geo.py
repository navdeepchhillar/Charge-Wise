"""Geometry helpers: great-circle distance, bearings and positions along a polyline."""
from __future__ import annotations

import math
from bisect import bisect_right
from typing import List, Sequence, Tuple

LatLng = Tuple[float, float]
EARTH_KM = 6371.0088


def haversine_km(a: LatLng, b: LatLng) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: LatLng, b: LatLng) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlng = math.radians(b[1] - a[1])
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def offset(p: LatLng, km_north: float, km_east: float) -> LatLng:
    """Move a point by small north/east distances (good to well under 1% at these scales)."""
    return (p[0] + km_north / 110.574, p[1] + km_east / (111.320 * math.cos(math.radians(p[0]))))


class Polyline:
    """A route as a polyline with cumulative distances, for fast 'where am I after d km' lookups."""

    def __init__(self, points: Sequence[LatLng]):
        if len(points) < 2:
            raise ValueError("A route needs at least two points")
        self.points: List[LatLng] = [tuple(p) for p in points]
        self.cum: List[float] = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.cum.append(self.cum[-1] + haversine_km(a, b))
        self.length_km = self.cum[-1]

    def point_at(self, d_km: float) -> Tuple[LatLng, float]:
        """Position and heading after travelling d_km from the start (clamped to the route)."""
        d = min(max(d_km, 0.0), self.length_km)
        i = min(bisect_right(self.cum, d) - 1, len(self.points) - 2)
        seg = self.cum[i + 1] - self.cum[i]
        f = 0.0 if seg == 0 else (d - self.cum[i]) / seg
        a, b = self.points[i], self.points[i + 1]
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), bearing_deg(a, b)

    def project(self, p: LatLng) -> Tuple[float, float]:
        """(distance along the route of the closest point, lateral distance in km from the route)."""
        best = (0.0, float("inf"))
        for i, (a, b) in enumerate(zip(self.points, self.points[1:])):
            # local flat projection around a (fine for segments of a few km)
            kx = 111.320 * math.cos(math.radians(a[0]))
            ky = 110.574
            ax, ay = 0.0, 0.0
            bx, by = (b[1] - a[1]) * kx, (b[0] - a[0]) * ky
            px, py = (p[1] - a[1]) * kx, (p[0] - a[0]) * ky
            seg2 = bx * bx + by * by
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, (px * bx + py * by) / seg2))
            cx, cy = ax + t * bx, ay + t * by
            lateral = math.hypot(px - cx, py - cy)
            if lateral < best[1]:
                best = (self.cum[i] + t * (self.cum[i + 1] - self.cum[i]), lateral)
        return best

    def slice(self, d_from: float, d_to: float) -> List[LatLng]:
        """The polyline between two distances (for drawing the part already driven / still ahead)."""
        d_from, d_to = max(0.0, d_from), min(self.length_km, d_to)
        if d_to <= d_from:
            return [self.point_at(d_from)[0]]
        out = [self.point_at(d_from)[0]]
        out += [p for p, c in zip(self.points, self.cum) if d_from < c < d_to]
        out.append(self.point_at(d_to)[0])
        return out
