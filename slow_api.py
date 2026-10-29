"""Fake external payment API for the load test: answers every request after DELAY seconds.

    python slow_api.py 9100 5
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        time.sleep(DELAY)
        body = json.dumps({"status": "paid"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    port, DELAY = int(sys.argv[1]), float(sys.argv[2])
    ThreadingHTTPServer.request_queue_size = 128  # the load test opens many connections at once
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
