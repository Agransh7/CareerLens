"""Vercel endpoint that turns browser-extracted resume text into PDF or DOCX."""

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
    def do_POST(self) -> None:
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > careerlens.MAX_RESUME * 2:
                raise careerlens.RequestError(413, "Request is empty or too large.")
            data = json.loads(self.rfile.read(size).decode("utf-8"))
            file_format = str(data.get("format", ""))
            content = careerlens.export_resume(data, file_format)
            mime = "application/pdf" if file_format == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Disposition", f'attachment; filename="CareerLens-resume.{file_format}"')
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)
        except careerlens.RequestError as error:
            self._send_error(error.status, str(error))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            self._send_error(400, str(error) or "Request must contain valid JSON.")
        except Exception:
            self._send_error(500, "CareerLens could not create that resume file.")

    def _send_error(self, status: int, message: str) -> None:
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send_error(405, "Use POST to export a resume.")
