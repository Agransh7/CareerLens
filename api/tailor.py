"""Vercel serverless endpoint for resume tailoring."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as careerlens  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > careerlens.MAX_BODY:
                self._send_json(413, {"error": "Request is empty or too large."})
                return
            data = json.loads(self.rfile.read(size).decode("utf-8"))
            self._send_json(200, careerlens.tailor_resume(data))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            self._send_json(400, {"error": str(error) or "Request must contain valid JSON."})
        except careerlens.RequestError as error:
            self._send_json(error.status, {"error": str(error)})
        except RuntimeError as error:
            self._send_json(502, {"error": str(error)})
        except Exception:
            self._send_json(500, {"error": "CareerLens encountered an unexpected error. Please try again."})

    def do_GET(self) -> None:
        self._send_json(405, {"error": "Use POST to tailor a resume."})
