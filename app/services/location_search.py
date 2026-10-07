"""Indexed nearest-location search over the supplied grid dataset."""

from __future__ import annotations

import csv
import heapq
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional


DEFAULT_DATASET_NAMES = ("locations.csv", "locations - locations.csv")


@dataclass(frozen=True)
class Location:
    location_id: str
    latitude: float
    longitude: float
    category: str


def _dataset_path() -> Path:
    configured = os.getenv("LOCATION_DATASET")
    if configured:
        return Path(configured)
    root = Path(__file__).resolve().parents[2]
    for name in DEFAULT_DATASET_NAMES:
        candidate = root / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Location dataset not found; set LOCATION_DATASET to locations.csv")


@lru_cache(maxsize=2)
def load_locations(path: str, mtime_ns: int) -> tuple[Location, ...]:
    """Load and validate the CSV once per dataset revision."""
    locations: list[Location] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"ID", "Latitude", "Longitude", "Category"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Location CSV must contain ID, Latitude, Longitude, and Category columns")
        for row_number, row in enumerate(reader, start=2):
            try:
                locations.append(
                    Location(
                        location_id=row["ID"].strip(),
                        latitude=float(row["Latitude"]),
                        longitude=float(row["Longitude"]),
                        category=row["Category"].strip(),
                    )
                )
            except (AttributeError, TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"Invalid location row {row_number}") from exc
    if not locations:
        raise ValueError("Location CSV is empty")
    return tuple(locations)


def get_locations() -> tuple[Location, ...]:
    path = _dataset_path().resolve()
    return load_locations(str(path), path.stat().st_mtime_ns)


def _parse_links(lines: Iterable[str], locations: tuple[Location, ...]) -> dict[int, list[tuple[int, float]]]:
    by_id = {location.location_id: index for index, location in enumerate(locations)}
    adjacency: dict[int, list[tuple[int, float]]] = {index: [] for index in range(len(locations))}

    for line_number, line in enumerate(lines, start=1):
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        if len(fields) != 2:
            raise ValueError(f"Invalid linkage row {line_number}; expected two point IDs")
        left, right = fields
        if left not in by_id or right not in by_id:
            raise ValueError(f"Unknown point ID in linkage row {line_number}")
        source, target = by_id[left], by_id[right]
        if source == target:
            continue
        a, b = locations[source], locations[target]
        weight = math.hypot(a.latitude - b.latitude, a.longitude - b.longitude)
        adjacency[source].append((target, weight))
        adjacency[target].append((source, weight))
    return adjacency


def _default_grid_links(locations: tuple[Location, ...]) -> dict[int, list[tuple[int, float]]]:
    """Use four-neighbour links when no road file is supplied."""
    coordinate_index = {(location.latitude, location.longitude): index for index, location in enumerate(locations)}
    adjacency: dict[int, list[tuple[int, float]]] = {index: [] for index in range(len(locations))}
    latitudes = sorted({location.latitude for location in locations})
    longitudes = sorted({location.longitude for location in locations})
    lat_step = min((b - a for a, b in zip(latitudes, latitudes[1:]) if b > a), default=0.0)
    lon_step = min((b - a for a, b in zip(longitudes, longitudes[1:]) if b > a), default=0.0)
    for index, location in enumerate(locations):
        neighbours = ((location.latitude + lat_step, location.longitude),
                      (location.latitude - lat_step, location.longitude),
                      (location.latitude, location.longitude + lon_step),
                      (location.latitude, location.longitude - lon_step))
        for coordinate in neighbours:
            target = coordinate_index.get(coordinate)
            if target is not None:
                weight = math.hypot(location.latitude - locations[target].latitude,
                                    location.longitude - locations[target].longitude)
                adjacency[index].append((target, weight))
    return adjacency


def _nearest_grid_node(latitude: float, longitude: float, locations: tuple[Location, ...]) -> int:
    return min(
        range(len(locations)),
        key=lambda index: (math.hypot(locations[index].latitude - latitude,
                                      locations[index].longitude - longitude), index),
    )


def recommend_locations(
    latitude: float,
    longitude: float,
    category: str,
    radius: float,
    link_text: Optional[str],
) -> list[str]:
    locations = get_locations()
    adjacency = (
        _parse_links(link_text.splitlines(), locations)
        if link_text is not None
        else _default_grid_links(locations)
    )
    source = _nearest_grid_node(latitude, longitude, locations)
    eligible = {
        index
        for index, location in enumerate(locations)
        if location.category.casefold() == category.casefold()
        and math.hypot(location.latitude - latitude, location.longitude - longitude) <= radius
    }

    distances: dict[int, float] = {source: 0.0}
    queue: list[tuple[float, int]] = [(0.0, source)]
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != distances.get(node):
            continue
        for neighbour, weight in adjacency[node]:
            candidate_distance = distance + weight
            if candidate_distance < distances.get(neighbour, math.inf):
                distances[neighbour] = candidate_distance
                heapq.heappush(queue, (candidate_distance, neighbour))

    ranked = sorted(
        ((distances[index], locations[index].location_id, index) for index in eligible if index in distances),
        key=lambda item: (item[0], item[1], item[2]),
    )
    return [location_id for _, location_id, _ in ranked[:10]]
