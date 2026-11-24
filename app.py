"""CareerLens local web app and Gemini model failover proxy."""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
MAX_BODY = 160_000
MAX_RESUME = 50_000


def load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip("\"'")
        if name:
            os.environ.setdefault(name, value)


def model_list() -> list[str]:
    configured = os.getenv("GEMINI_MODELS", "")
    if not configured.strip():
        configured = os.getenv("GEMINI_MODEL", "")
    if not configured.strip():
        configured = "gemini-3.8-flash,gemini-3.5-flash-lite,gemini-3.5-flash"
    models = list(dict.fromkeys(model.strip() for model in configured.split(",") if model.strip()))
    return models[:5]


def call_gemini(prompt: str) -> tuple[str, str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        raise RuntimeError("Gemini is not configured. Add your key to GEMINI_API_KEY in .env and restart CareerLens.")

    models = model_list()
    if not models:
        raise RuntimeError("No Gemini models are configured. Set GEMINI_MODELS in .env.")

    payload = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.35, "maxOutputTokens": 8192},
        }
    ).encode("utf-8")
    failures: list[str] = []

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        request = Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )

        # Retry brief service overloads before moving on to the next model.
        for attempt in range(3):
            try:
                with urlopen(request, timeout=35) as response:
                    data = json.loads(response.read().decode("utf-8"))
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
                if text.strip():
                    return text, model
                failures.append(f"{model}: Gemini returned no text")
                break
            except HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(detail)
                    detail = parsed.get("error", {}).get("message", detail)
                except (json.JSONDecodeError, AttributeError):
                    pass
                detail = " ".join(str(detail).split())[:400]
                if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                failures.append(f"{model} (HTTP {error.code}): {detail or error.reason}")
                break
            except (URLError, TimeoutError, OSError) as error:
                failures.append(f"{model}: connection failed: {error}")
                break
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
                failures.append(f"{model}: unexpected response: {error}")
                break

    summary = "\n".join(failures)
    raise RuntimeError(f"CareerLens tried all configured Gemini models but none succeeded:\n{summary}")


def make_prompt(data: dict) -> str:
    return (
        "You are an expert resume editor. Tailor this resume for the target company and role. "
        "Preserve truth; never invent employers, dates, degrees, skills, metrics, or achievements. "
        "Rephrase and reorganize only provided facts. Return a polished ATS-readable resume in Markdown, "
        "followed by a section titled 'Tailoring notes' with edits and details the candidate should verify. "
        "Do not claim access to private company hiring criteria.\n\n"
        f"Company: {data['company']}\n"
        f"Role: {data.get('role') or 'Not specified'}\n"
        f"Job description: {data.get('jobDescription') or 'Not provided'}\n\n"
        f"Resume:\n{data['resume']}"
    )


class CareerLensHandler(BaseHTTPRequestHandler):
    server_version = "CareerLens/1.0"

    def log_message(self, format: str, *args) -> None:
        # Do not log request bodies, which contain personal resume information.
        print(f"[{self.log_date_time_string()}] {args[0] if args else 'request'}")

    def send_json(self, status: int, data: dict) -> None:
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:
        if self.path != "/api/tailor":
            self.send_json(404, {"error": "API route not found."})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > MAX_BODY:
                self.send_json(413, {"error": "Request is empty or too large."})
                return
            data = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Request body must be a JSON object.")
            company = str(data.get("company", "")).strip()[:100]
            resume = str(data.get("resume", "")).strip()
            if not company or not resume:
                self.send_json(400, {"error": "Add a target company and resume text."})
                return
            if len(resume) > MAX_RESUME:
                self.send_json(413, {"error": "Resume text is too long. Keep it under 50,000 characters."})
                return
            normalized = {
                "company": company,
                "role": str(data.get("role", "")).strip()[:150],
                "jobDescription": str(data.get("jobDescription", "")).strip()[:6000],
                "resume": resume,
            }
            result, model = call_gemini(make_prompt(normalized))
            self.send_json(200, {"resume": result, "model": model})
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            self.send_json(400, {"error": str(error) or "Request must contain valid JSON."})
        except RuntimeError as error:
            self.send_json(502, {"error": str(error)})
        except Exception:
            self.send_json(500, {"error": "CareerLens encountered an unexpected error. Check the server terminal."})

    def do_GET(self) -> None:
        relative = "index.html" if self.path in ("/", "/index.html") else self.path.split("?", 1)[0].lstrip("/")
        target = (WEB_DIR / relative).resolve()
        if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
            self.send_error(404)
            return
        if not target.is_file():
            self.send_error(404)
            return
        content_type = "text/html; charset=utf-8" if target.suffix == ".html" else "text/css; charset=utf-8" if target.suffix == ".css" else "application/javascript; charset=utf-8" if target.suffix == ".js" else "application/octet-stream"
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    load_dotenv()
    try:
        port = int(os.getenv("PORT", "8080"))
    except ValueError as error:
        raise SystemExit("PORT must be a number.") from error
    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be between 1 and 65535.")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), CareerLensHandler)
    except OSError as error:
        if getattr(error, "winerror", None) == 10048 or getattr(error, "errno", None) in (48, 98, 10048):
            raise SystemExit(f"Port {port} is already in use. Stop the old CareerLens server with Ctrl+C, or set a different PORT in .env.") from error
        raise
    print(f"CareerLens is running at http://127.0.0.1:{port}", flush=True)
    print("Gemini fallback order: " + ", ".join(model_list()), flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCareerLens stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
