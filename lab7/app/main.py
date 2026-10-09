from __future__ import annotations

import csv
import heapq
import math
import os
from bisect import bisect_left
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile

MAX_LINK_BYTES = 64 * 1024 * 1024


class LocationStore:
    def __init__(self, filename: str):
        self.rows = []
        self.by_id = {}
        self.by_grid = {}
        self.lat_index = {}
        self.lon_index = {}
        self.buckets = defaultdict(list)
        self.latitudes = []
        self.longitudes = []
        self.step = 0.01
        self.grid_links = []
        self._load(filename)

    def _load(self, filename: str) -> None:
        with open(filename, newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            required = {"ID", "Latitude", "Longitude", "Category"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError("CSV must contain ID, Latitude, Longitude, and Category")
            for row in reader:
                item = (
                    row["ID"].strip(),
                    float(row["Latitude"]),
                    float(row["Longitude"]),
                    row["Category"].strip().casefold(),
                )
                self.by_id[item[0]] = len(self.rows)
                self.rows.append(item)
        self.latitudes = sorted({item[1] for item in self.rows})
        self.longitudes = sorted({item[2] for item in self.rows})
        self.lat_index = {value: position for position, value in enumerate(self.latitudes)}
        self.lon_index = {value: position for position, value in enumerate(self.longitudes)}
        if len(self.latitudes) > 1 and len(self.longitudes) > 1:
            self.step = max(
                min(
                    abs(self.latitudes[1] - self.latitudes[0]),
                    abs(self.longitudes[1] - self.longitudes[0]),
                ),
                1e-9,
            )
        for index, item in enumerate(self.rows):
            lat_pos = self.lat_index[item[1]]
            lon_pos = self.lon_index[item[2]]
            self.by_grid[(lat_pos, lon_pos)] = index
            self.buckets[self._bucket(item[1], item[2])].append(index)
        self.grid_links = [tuple(self._grid_neighbors(index)) for index in range(len(self.rows))]

    def _bucket_size(self) -> float:
        return self.step * 8

    def _bucket(self, latitude, longitude):
        size = self._bucket_size()
        return math.floor(latitude / size), math.floor(longitude / size)

    @staticmethod
    def _nearest(values, target):
        position = bisect_left(values, target)
        if position == 0:
            return 0
        if position == len(values):
            return position - 1
        before = position - 1
        return before if target - values[before] <= values[position] - target else position

    def candidates(self, latitude: float, longitude: float, radius: float, category: str):
        size = self._bucket_size()
        dataset_lat_min = math.floor(self.latitudes[0] / size)
        dataset_lat_max = math.floor(self.latitudes[-1] / size)
        dataset_lon_min = math.floor(self.longitudes[0] / size)
        dataset_lon_max = math.floor(self.longitudes[-1] / size)
        lat_min = max(dataset_lat_min, math.floor((latitude - radius) / size))
        lat_max = min(dataset_lat_max, math.floor((latitude + radius) / size))
        lon_min = max(dataset_lon_min, math.floor((longitude - radius) / size))
        lon_max = min(dataset_lon_max, math.floor((longitude + radius) / size))
        if lat_min > lat_max or lon_min > lon_max:
            return []
        wanted = category.casefold()
        found = []
        seen = set()
        for lat_bucket in range(lat_min, lat_max + 1):
            for lon_bucket in range(lon_min, lon_max + 1):
                for index in self.buckets.get((lat_bucket, lon_bucket), ()):
                    if index in seen:
                        continue
                    seen.add(index)
                    item = self.rows[index]
                    circular = math.hypot(item[1] - latitude, item[2] - longitude)
                    if item[3] == wanted and circular <= radius:
                        found.append(index)
        return found

    def start_node(self, latitude: float, longitude: float) -> int:
        lat_pos = self._nearest(self.latitudes, latitude)
        lon_pos = self._nearest(self.longitudes, longitude)
        return self.by_grid[(lat_pos, lon_pos)]

    def neighbors(self, index: int):
        yield from self.grid_links[index]

    def _grid_neighbors(self, index: int):
        item = self.rows[index]
        lat_pos = self.lat_index[item[1]]
        lon_pos = self.lon_index[item[2]]
        for point in ((lat_pos - 1, lon_pos), (lat_pos + 1, lon_pos), (lat_pos, lon_pos - 1), (lat_pos, lon_pos + 1)):
            neighbor = self.by_grid.get(point)
            if neighbor is not None:
                other = self.rows[neighbor]
                yield neighbor, math.hypot(item[1] - other[1], item[2] - other[2])

    @lru_cache(maxsize=2)
    def links(self, text: str):
        if text is None:
            return None
        graph = defaultdict(list)
        lines = []
        for line_number, line in enumerate(text.splitlines(), 1):
            values = line.split()
            if not values or values[0].startswith("#"):
                continue
            if len(values) != 2:
                raise ValueError(f"Invalid linkage at line {line_number}")
            lines.append((line_number, values[0], values[1]))
        use_indexes = any("0" in (first, second) for _, first, second in lines)
        for line_number, first_value, second_value in lines:
            first = self._link_index(first_value, use_indexes)
            second = self._link_index(second_value, use_indexes)
            if first == second:
                continue
            a = self.rows[first]
            b = self.rows[second]
            weight = math.hypot(a[1] - b[1], a[2] - b[2])
            graph[first].append((second, weight))
            graph[second].append((first, weight))
        return graph

    def _link_index(self, value: str, use_indexes: bool) -> int:
        if not use_indexes and value in self.by_id:
            return self.by_id[value]
        try:
            index = int(value)
        except ValueError as exc:
            raise ValueError(f"Unknown linkage node {value}") from exc
        if index < 0 or index >= len(self.rows):
            raise ValueError(f"Unknown linkage node {value}")
        return index

    def recommend(self, latitude, longitude, category, radius, link_text):
        eligible = set(self.candidates(latitude, longitude, radius, category))
        if not eligible:
            return []
        custom = self.links(link_text)
        start = self.start_node(latitude, longitude)
        distances = {start: 0.0}
        pending = [(0.0, start)]
        results = []
        best_limit = math.inf
        while pending:
            distance, current = heapq.heappop(pending)
            if distance != distances.get(current):
                continue
            if distance > best_limit:
                break
            if current in eligible:
                results.append((distance, self.rows[current][0]))
                eligible.remove(current)
                if len(results) == 10:
                    best_limit = distance
            for neighbor, weight in (custom.get(current, ()) if custom is not None else self.grid_links[current]):
                next_distance = distance + weight
                if next_distance < distances.get(neighbor, math.inf):
                    distances[neighbor] = next_distance
                    heapq.heappush(pending, (next_distance, neighbor))
        results.sort(key=lambda pair: (pair[0], pair[1]))
        return [location_id for _, location_id in results[:10]]


def dataset_name() -> str:
    configured = os.getenv("LOCATION_DATASET")
    if configured:
        return configured
    for name in ("locations.csv", "locations - locations.csv"):
        candidate = Path(__file__).resolve().parents[1] / name
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("Set LOCATION_DATASET to the supplied CSV file")


store = LocationStore(dataset_name())
app = FastAPI(title="Lab7 Location Recommendation API")


def search(latitude, longitude, category, radius, link_text):
    if not all(math.isfinite(value) for value in (latitude, longitude, radius)):
        raise HTTPException(status_code=422, detail="lat, long, and rad must be finite")
    if not category.strip():
        raise HTTPException(status_code=422, detail="cat must not be empty")
    try:
        return store.recommend(latitude, longitude, category, radius, link_text)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/health")
def health():
    return {"status": "ok", "service": "lab7-location-api"}


@app.get("/IP/search/", response_model=list[str])
def get_search(
    lat: float = Query(...),
    long: float = Query(...),
    cat: str = Query(...),
    rad: float = Query(..., ge=0),
):
    return search(lat, long, cat, rad, None)


@app.post("/IP/search/", response_model=list[str])
async def post_search(
    lat: float = Form(...),
    long: float = Form(...),
    cat: str = Form(...),
    rad: float = Form(..., ge=0),
    link: Optional[UploadFile] = File(None),
):
    text = None
    if link is not None:
        try:
            body = await link.read(MAX_LINK_BYTES + 1)
            if len(body) > MAX_LINK_BYTES:
                raise HTTPException(status_code=413, detail="link file exceeds 64 MiB")
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="link must be UTF-8 text") from exc
    return search(lat, long, cat, rad, text)
