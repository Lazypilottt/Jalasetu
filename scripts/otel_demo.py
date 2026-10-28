#!/usr/bin/env python3
"""
OpenTelemetry validation script for JalaSetu.

Sends:
1. 5 successful map-only POSTs to /analyzeContour:
   lat 21.2517, lon 81.2970, radius 250, dem_resolution_m in [5, 10, 15, 5, 10]
2. 1 invalid request: selected_radius_m=10000
3. 1 request outside the bundled extent: lat 21.30, lon 81.40
Prints HTTP status and duration for each request.
"""

import os
import sys
import time
import requests

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ENDPOINT = f"{BASE_URL}/analyzeContour"


def send_request(label: str, payload: dict):
    t0 = time.perf_counter()
    try:
        resp = requests.post(ENDPOINT, data=payload, timeout=120)
        dur = time.perf_counter() - t0
        print(f"[{label}] status={resp.status_code} duration={dur:.2f}s")
        return resp
    except Exception as exc:
        dur = time.perf_counter() - t0
        print(f"[{label}] FAILED: {exc} duration={dur:.2f}s")
        return None


def main():
    print(f"Target endpoint: {ENDPOINT}")
    resolutions = [5, 10, 15, 5, 10]

    # 1. Five successful map-only requests
    for idx, res in enumerate(resolutions, start=1):
        data = {
            "selected_latitude": 21.2517,
            "selected_longitude": 81.2970,
            "selected_radius_m": 250,
            "dem_resolution_m": res,
        }
        send_request(f"Success {idx}/5 (dem_resolution_m={res}m)", data)
        time.sleep(1)

    # 2. One invalid request (selected_radius_m=10000)
    invalid_data = {
        "selected_latitude": 21.2517,
        "selected_longitude": 81.2970,
        "selected_radius_m": 10000,
        "dem_resolution_m": 10,
    }
    send_request("Invalid request (selected_radius_m=10000)", invalid_data)
    time.sleep(1)

    # 3. One request outside the bundled extent (lat 21.30, lon 81.40)
    outside_data = {
        "selected_latitude": 21.30,
        "selected_longitude": 81.40,
        "selected_radius_m": 250,
        "dem_resolution_m": 10,
    }
    send_request("Outside extent (lat=21.30, lon=81.40)", outside_data)


if __name__ == "__main__":
    main()
