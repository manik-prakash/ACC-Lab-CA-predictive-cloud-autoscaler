"""Minimal CPU-bound service used by the autoscaler experiment."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import json
import math
import os
import time


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path)
        if path.path == "/health":
            self._send(200, {"status": "ok"})
            return
        if path.path != "/work":
            self._send(404, {"error": "use /health or /work?units=200000"})
            return

        try:
            units = int(parse_qs(path.query).get("units", ["200000"])[0])
        except ValueError:
            self._send(400, {"error": "units must be an integer"})
            return
        units = max(1_000, min(units, 5_000_000))
        started = time.perf_counter()
        value = 0.0
        for index in range(units):
            value += math.sqrt((index % 997) + 1)
        self._send(200, {"units": units, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2), "checksum": round(value, 2)})

    def _send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
