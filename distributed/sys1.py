"""sys1 edge service: static frontend, climate API, and capacity reporting.

sys1 also hosts the OpenTelemetry backends, which use about half of its 500 MB,
and it has no virtualenv. This service therefore uses only the standard library
(about 35 MB resident). It takes the backend work that needs no geospatial
stack: the rainfall/climate API and the existing-infrastructure lookup
(OpenStreetMap), both of which the gateway calls for every analysis, and
serving the built SPA. Its ``/health`` reports memory and storage
use in the same shape as the stage workers, so the cluster view covers all four
nodes. It advertises no heavy stages, so the scheduler never places any here.

Run with ``python3 -m distributed.sys1``.
"""

from __future__ import annotations

import http.server
import ipaddress
import json
import logging
import os
import socketserver
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from app.services.infrastructure import fetch_infrastructure
from app.services.rainfall_service import RainfallService

from .capacity import CapacityGuard, StorageMonitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("jalasetu.sys1")

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = Path(os.getenv("JALASETU_FRONTEND_DIST", ROOT / "frontend" / "dist")).resolve()
PORT = int(os.getenv("PORT", os.getenv("JALASETU_PORT", "3000")))
GATEWAY_URL = os.getenv("GATEWAY_URL", "").rstrip("/")
NODE_NAME = os.getenv("JALASETU_NODE_NAME", "sys1")

# Only these paths are forwarded to the gateway, and Nginx routes every one of
# them to sys4 explicitly. Anything else is a static file, so a request can
# never bounce between Nginx and sys1.
GATEWAY_PREFIXES = ("/analyzeContour", "/findCatchment", "/v1/jobs", "/v1/cluster", "/IP/search")
RAINFALL_PATHS = ("/v1/rainfall", "/api/rainfall")
INFRASTRUCTURE_PATH = "/v1/infrastructure"
HOP_HEADER = "X-JalaSetu-Edge"

# The public entry point is the sys4 Nginx (load balancing, rate limits). The
# host also publishes sys1's port, which would otherwise serve a second copy of
# the site that bypasses Nginx; clients outside the trusted networks are sent
# to the public URL instead. Unset JALASETU_PUBLIC_URL to serve everyone.
PUBLIC_URL = os.getenv("JALASETU_PUBLIC_URL", "").rstrip("/")
TRUSTED_NETWORKS = tuple(
    ipaddress.ip_network(item.strip(), strict=False)
    for item in os.getenv("JALASETU_TRUSTED_NETWORKS", "127.0.0.0/8,::1/128").split(",")
    if item.strip()
)
MAX_PROXY_BODY = 50 * 1024 * 1024

guard = CapacityGuard()
storage = StorageMonitor()
rainfall = RainfallService()


def _matches(path: str, prefixes) -> bool:
    return any(path == p or path.startswith(p + "/") for p in prefixes)


def is_trusted(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return any(ip in network for network in TRUSTED_NETWORKS)


def health_body() -> Dict[str, Any]:
    capacity = guard.report()
    capacity["accepting"] = False  # no heavy stages on the edge node
    return {
        "status": "ok",
        "service": NODE_NAME,
        "role": "edge",
        "stages": [],
        "affinity": [],
        "serves": ["frontend", "rainfall", "infrastructure"],
        "frontend_built": (DIST_DIR / "index.html").exists(),
        "capacity": capacity,
        "storage": storage.report(),
    }


def infrastructure_body(query: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
    try:
        lat = float((query.get("lat") or [None])[0])
        lon = float((query.get("lon") or [None])[0])
        radius = float((query.get("radius_m") or ["400"])[0])
    except (TypeError, ValueError):
        return 422, {"error": "lat, lon (and optional radius_m) must be numbers"}
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 50 <= radius <= 3000):
        return 422, {"error": "lat/lon out of range or radius_m outside 50-3000"}
    return 200, fetch_infrastructure(lat, lon, radius)


def rainfall_body(query: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
    lat_val = (query.get("lat") or query.get("latitude") or [None])[0]
    lon_val = (query.get("lon") or query.get("longitude") or [None])[0]
    if lat_val is None or lon_val is None:
        return 400, {"error": "lat and lon are required parameters"}
    try:
        lat, lon = float(lat_val), float(lon_val)
    except (TypeError, ValueError):
        return 422, {"error": "Invalid numerical coordinates"}
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return 422, {"error": "lat must be within ±90 and lon within ±180"}
    return 200, rainfall.get_rainfall_data(lat, lon)


class EdgeHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "JalaSetuEdge/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def log_message(self, fmt, *args):
        logger.info("%s %s", self.address_string(), fmt % args)

    def _send_json(self, status: int, body: Dict[str, Any], extra: Optional[Dict[str, str]] = None) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _redirect_external(self) -> bool:
        """Send direct outside visitors to the public entry point."""
        if not PUBLIC_URL or is_trusted(self.client_address[0]):
            return False
        target = PUBLIC_URL + (self.path if self.path.startswith("/") else "/" + self.path)
        self.send_response(308)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return True

    def _route(self) -> bool:
        """Handle API paths. Returns False when the path is a static file."""
        if self._redirect_external():
            return True
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/health":
            self._send_json(200, health_body())
            return True
        if parsed.path in RAINFALL_PATHS:
            query = urllib.parse.parse_qs(parsed.query)
            if self.command == "POST":
                query.update(self._read_form_or_json())
            status, body = rainfall_body(query)
            self._send_json(status, body)
            return True
        if parsed.path == INFRASTRUCTURE_PATH:
            status, body = infrastructure_body(urllib.parse.parse_qs(parsed.query))
            self._send_json(status, body)
            return True
        if _matches(parsed.path, GATEWAY_PREFIXES):
            self._proxy()
            return True
        return False

    def _read_form_or_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, 64 * 1024)) if length else b""
        try:
            values = json.loads(raw or b"{}")
            return {key: [value] for key, value in values.items()} if isinstance(values, dict) else {}
        except ValueError:
            return urllib.parse.parse_qs(raw.decode("utf-8", "replace"))

    def _proxy(self) -> None:
        if not GATEWAY_URL:
            self._send_json(404, {"error": "this edge node does not proxy API requests"})
            return
        if self.headers.get(HOP_HEADER):
            self._send_json(508, {"error": "request loop between edge and gateway"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_PROXY_BODY:
            self._send_json(413, {"error": "uploaded file exceeds the 50 MB limit"})
            return
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in ("host", "content-length", "connection", "accept-encoding")
        }
        headers[HOP_HEADER] = NODE_NAME
        headers["X-Forwarded-For"] = self.client_address[0]
        req = urllib.request.Request(f"{GATEWAY_URL}{self.path}", data=body, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=330) as resp:
                status, resp_headers, data = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            status, resp_headers, data = exc.code, exc.headers, exc.read()
        except Exception as exc:
            logger.warning("Gateway proxy failed: %s", exc)
            self._send_json(502, {"error": "Gateway unavailable"})
            return
        self.send_response(status)
        for key, value in resp_headers.items():
            if key.lower() not in ("transfer-encoding", "content-encoding", "content-length", "connection", "server", "date"):
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        # Vite fingerprints asset names, so they can be cached for a year;
        # index.html must revalidate so new builds are picked up.
        if self.path.startswith("/assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        super().end_headers()

    def do_GET(self):
        if self._route():
            return
        clean = urllib.parse.urlsplit(self.path).path.lstrip("/")
        target = (DIST_DIR / clean).resolve()
        inside = target == DIST_DIR or DIST_DIR in target.parents
        # Unknown paths are client-side routes: answer with the SPA shell.
        if not inside or not target.is_file() or clean in ("", "index.html"):
            index = DIST_DIR / "index.html"
            data = index.read_bytes() if index.exists() else b"frontend not built"
            self.send_response(200 if index.exists() else 503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def do_HEAD(self):
        if not self._route():
            super().do_HEAD()

    def do_POST(self):
        if not self._route():
            self._send_json(404, {"error": "not found"})


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    with ThreadingServer(("0.0.0.0", PORT), EdgeHandler) as httpd:
        logger.info("sys1 edge on :%d serving %s; gateway=%s", PORT, DIST_DIR, GATEWAY_URL or "none")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
