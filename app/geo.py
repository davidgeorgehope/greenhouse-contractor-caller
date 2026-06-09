from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass

GASPORT_COORDS = (43.2091, -78.6453)
USER_AGENT = "greenhouse-contractor-caller/0.1"


@dataclass(frozen=True)
class Coordinates:
    lat: float
    lng: float


def haversine_miles(origin: Coordinates, destination: Coordinates) -> float:
    radius_miles = 3958.7613
    lat1 = math.radians(origin.lat)
    lat2 = math.radians(destination.lat)
    dlat = lat2 - lat1
    dlng = math.radians(destination.lng - origin.lng)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * radius_miles * math.asin(math.sqrt(a))


def geocode_nominatim(query: str) -> Coordinates | None:
    params = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 1})
    request = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/search?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        results = json.loads(response.read().decode("utf-8"))
    if not results:
        return None
    return Coordinates(lat=float(results[0]["lat"]), lng=float(results[0]["lon"]))


def osrm_drive_minutes(origin: Coordinates, destination: Coordinates) -> int | None:
    coords = f"{origin.lng},{origin.lat};{destination.lng},{destination.lat}"
    request = urllib.request.Request(
        f"https://router.project-osrm.org/route/v1/driving/{coords}?overview=false",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    routes = payload.get("routes") or []
    if not routes:
        return None
    return round(float(routes[0]["duration"]) / 60)


def travel_from_gasport(address: str) -> tuple[Coordinates, float, int | None] | None:
    destination = geocode_nominatim(address)
    if destination is None:
        return None
    origin = Coordinates(*GASPORT_COORDS)
    return destination, round(haversine_miles(origin, destination), 1), osrm_drive_minutes(origin, destination)
