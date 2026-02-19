#!/usr/bin/env python3
"""
serve_ical.py
-------------
Serves the .ics files in ~/NotionCalendars/ over http://localhost:8080
so Apple Calendar can subscribe to them.

This is intentionally minimal — it only serves .ics files,
refuses directory listings, and only accepts connections from localhost.
"""

import os
import sys
import logging
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", str(Path.home() / "NotionCalendars"))
PORT       = int(os.getenv("SERVER_PORT", "8080"))
HOST       = "127.0.0.1"  # localhost only — not accessible from other devices

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)


class ICalHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Route access logs through our logger instead of stderr
        log.info("Request: %s", format % args)

    def do_GET(self):
        # Strip leading slash and decode URL encoding (e.g. %20 → space)
        requested = unquote(self.path.lstrip("/"))

        # Security: reject any path traversal attempts (e.g. ../../etc/passwd)
        if ".." in requested or requested.startswith("/"):
            self.send_error(400, "Bad request")
            return

        # Only serve .ics files — nothing else
        if not requested.endswith(".ics"):
            self.send_error(403, "Only .ics files are served")
            return

        ics_path = Path(OUTPUT_DIR).expanduser() / requested

        if not ics_path.exists():
            self.send_error(404, f"Calendar not found: {requested}")
            return

        content = ics_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/calendar; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main():
    output_dir = Path(OUTPUT_DIR).expanduser()
    if not output_dir.exists():
        log.warning("Output directory does not exist yet: %s", output_dir)
        log.warning("Run notion_to_ical.py first to generate .ics files.")

    server = HTTPServer((HOST, PORT), ICalHandler)
    log.info("Serving .ics files from %s", output_dir)
    log.info("Listening on http://%s:%d/", HOST, PORT)
    log.info("Example URL: http://%s:%d/My%%20Calendar.ics", HOST, PORT)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Server stopped.")


if __name__ == "__main__":
    main()
