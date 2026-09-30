"""Resilient static SPA server and transparent API reverse proxy for sys1."""

import http.server
import logging
import os
from pathlib import Path
import socketserver
import urllib.error
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("serve_spa")

DIRECTORY = Path("/home/student/Jalasetu/frontend/dist")
PORT = int(os.getenv("PORT", "3000"))
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://172.17.0.5:3000").rstrip("/")

API_PREFIXES = ("/analyzeContour", "/findCatchment", "/v1/", "/health")

def _srv_health():
    """Minimal health endpoint served by sys1 itself (does NOT proxy)."""
    return True


class ResilientSPAHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

    def _is_api_request(self) -> bool:
        return any(self.path == prefix or self.path.startswith(prefix + "/") or self.path.startswith(prefix + "?") for prefix in API_PREFIXES)

    def _proxy_to_gateway(self):
        target_url = f"{GATEWAY_URL}{self.path}"
        logger.info(f"Proxying {self.command} {self.path} -> {target_url}")

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        forward_headers = {}
        for key, value in self.headers.items():
            if key.lower() not in ("host", "content-length", "connection"):
                forward_headers[key] = value
        forward_headers["X-Forwarded-For"] = self.client_address[0]

        req = urllib.request.Request(
            target_url,
            data=body,
            headers=forward_headers,
            method=self.command,
        )

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                self.send_response(resp.status)
                for header, val in resp.headers.items():
                    if header.lower() not in ("transfer-encoding", "content-encoding", "content-length"):
                        self.send_header(header, val)
                data = resp.read()
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as exc:
            self.send_response(exc.code)
            for header, val in exc.headers.items():
                if header.lower() not in ("transfer-encoding", "content-encoding", "content-length"):
                    self.send_header(header, val)
            err_data = exc.read()
            self.send_header("Content-Length", str(len(err_data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(err_data)
        except Exception as exc:
            logger.exception("Proxy forwarding error")
            err_msg = f'{{"error": "Gateway unavailable: {str(exc)}"}}'.encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_msg)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(err_msg)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        self._proxy_to_gateway()

    def do_GET(self):
        if self._is_api_request():
            return self._proxy_to_gateway()

        # Static SPA routing fallback
        clean_path = self.path.split("?")[0].lstrip("/")
        target_file = (DIRECTORY / clean_path).resolve()
        if not target_file.exists() or (target_file.is_dir() and not (target_file / "index.html").exists()):
            self.path = "/index.html"
        return super().do_GET()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with ThreadingTCPServer(("0.0.0.0", PORT), ResilientSPAHandler) as httpd:
        logger.info(f"Serving Resilient SPA + Reverse Proxy on port {PORT} -> Gateway at {GATEWAY_URL}")
        httpd.serve_forever()
