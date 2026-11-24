"""CareerLens local web app and Gemini model failover proxy."""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from html.parser import HTMLParser
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
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 10000,
                "responseMimeType": "application/json",
            },
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


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if cleaned:
            self.parts.append(cleaned)


def _plain_text(html: str) -> str:
    parser = _VisibleText()
    parser.feed(html)
    return " ".join(parser.parts)


def _match_tokens(value: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()))
    return words - {"inc", "llc", "ltd", "limited", "corp", "corporation", "company", "co", "the", "and", "of"}


def find_public_job_listing(company: str, role: str) -> dict | None:
    """Find a company and role match in Arbeitnow's public, no-key job feed."""
    request = Request(
        "https://www.arbeitnow.com/api/job-board-api",
        headers={"User-Agent": "CareerLens/1.0 (student resume project)", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    jobs = data.get("data", []) if isinstance(data, dict) else []
    company_tokens = _match_tokens(company)
    role_tokens = _match_tokens(role)
    if not company_tokens or not role_tokens:
        return None
    matches: list[tuple[float, dict]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        posted_company = _match_tokens(str(job.get("company_name", "")))
        title = str(job.get("title", ""))
        posted_role = _match_tokens(title)
        company_score = len(company_tokens & posted_company) / len(company_tokens)
        role_score = len(role_tokens & posted_role) / len(role_tokens)
        if company_score >= 0.8 and role_score >= 0.35:
            matches.append((company_score + role_score, job))
    if not matches:
        return None
    _, job = max(matches, key=lambda item: item[0])
    url = str(job.get("url", ""))
    if not url.startswith("https://"):
        return None
    description = _plain_text(str(job.get("description", "")))[:6000]
    if len(description) < 80:
        return None
    return {
        "title": str(job.get("title", "Job posting"))[:200],
        "source_title": "Arbeitnow public job feed",
        "source_url": url,
        "job_description": description,
        "kind": "listing",
    }


def make_prompt(data: dict) -> str:
    job_description = data.get("jobDescription") or "Not provided"
    role = data.get("role") or "Not provided"
    return f"""You are CareerLens Evidence Mode, a careful resume editor. Analyze the candidate's resume against the supplied job description and role.

Return only a JSON object with exactly these top-level arrays:
{{
  "requirements": [
    {{"requirement": "short requirement", "status": "covered|partial|gap", "evidence_quote": "verbatim resume excerpt or empty string", "reason": "brief explanation"}}
  ],
  "suggestions": [
    {{"requirement": "one requirement above", "source_quote": "verbatim complete resume bullet or line", "rewrite": "revised bullet using only supported facts", "reason": "why this wording fits the requirement", "interview_question": "a question the candidate should be ready to answer", "needs_confirmation": false}}
  ],
  "experience_reviews": [
    {{"experience_type": "work|internship|project|research|volunteering|leadership|other", "source_quote": "verbatim complete resume entry or bullet", "effect_quote": "verbatim result/effect excerpt or empty string", "scale_quote": "verbatim measurement or scale excerpt, including a number only if stated, or empty string", "beneficiary_quote": "verbatim excerpt showing who benefited, or empty string", "impact_summary": "short summary supported by these excerpts, or empty string", "follow_up_question": "ask about the missing real outcome, scale, or beneficiary; never suggest a fabricated number"}}
  ],
  "technical_learning_notes": [
    {{"skill": "technical skill/tool required by the posting", "job_quote": "verbatim excerpt from the job description", "why_it_matters": "brief reason this skill is relevant", "practice_step": "a small project or study task to build it"}}
  ]
}}

Rules:
- Never invent employers, dates, degrees, skills, metrics, or accomplishments.
- Every non-gap requirement must cite an exact, contiguous excerpt from the resume in evidence_quote. If there is no evidence, use status "gap" and an empty evidence_quote.
- Every suggestion must cite one exact, contiguous, complete bullet or line from the resume in source_quote. Do not cite a paraphrase. If no existing line can support a rewrite, do not create a suggestion for it.
- Keep each rewrite truthful and directly traceable to its source_quote. Do not add claims that cannot be defended from that quote.
- Set needs_confirmation to true when a rewrite depends on an ambiguous detail or would benefit from the candidate checking accuracy.
- Review every work experience, internship, project, research role, volunteer role, and leadership activity in the resume. Include each relevant entry in experience_reviews, quoting its source exactly.
- Evaluate each experience in three separate dimensions: (1) the effect/result, (2) scale or how much it changed (use a number only if the resume already states one), and (3) who benefited (users, customers, team, community, or society where relevant).
- Each effect_quote, scale_quote, and beneficiary_quote must be an exact excerpt from source_quote for that dimension. Leave a field empty when the resume does not state it. Never invent a number, result, or social benefit.
- Do not force a social-impact claim into ordinary work. Mention community or societal benefit only when the resume itself supports it.
- Return at most 20 experience_reviews. If the resume contains no identifiable experience entries, use an empty array.
- Make 3 to 8 concise requirements when a job description is supplied. If no job description is supplied, label requirements as role-based in their wording and do not imply access to private company criteria.
- Return at most 8 suggestions. Use an empty suggestions array when the resume contains no supporting evidence.
- technical_learning_notes must list only explicit technical skills, tools, frameworks, or platforms in the supplied job description that are not evidenced anywhere in the resume. Do not infer that the candidate lacks a skill merely because the resume omits it; describe these as "not shown in this resume" study candidates.
- Each technical learning note must include a verbatim job_quote from the supplied job description. Do not include guessed company requirements, generic soft skills, or requirements already clearly evidenced in the resume.
- If no job description was supplied, return an empty technical_learning_notes array.

Company: {data['company']}
Target role: {role}
Selected job posting: {data.get('jobTitle') or 'Provided by user'}
Posting URL: {data.get('jobSourceURL') or 'Not provided'}
Job description and verified requirement excerpts: {job_description}

Resume text:
{data['resume']}"""


def normalized_evidence(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(value.split())


def parse_evidence_response(response_text: str, resume: str, job_description: str = "") -> dict:
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise RuntimeError("Gemini did not return the evidence data in the expected JSON format. Please try again.") from error
    if not isinstance(result, dict):
        raise RuntimeError("Gemini returned evidence data in an unexpected format. Please try again.")

    source = normalized_evidence(resume)
    job_source = normalized_evidence(job_description)
    requirements = []
    for item in result.get("requirements", [])[:12]:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("evidence_quote", "")).strip()[:1500]
        stated_status = str(item.get("status", "gap")).lower()
        grounded = bool(quote) and normalized_evidence(quote) in source
        status = stated_status if stated_status in {"covered", "partial", "gap"} else "gap"
        if status != "gap" and not grounded:
            status = "unverified"
        requirements.append({
            "requirement": str(item.get("requirement", "Role requirement"))[:300],
            "status": status,
            "evidence_quote": quote,
            "reason": str(item.get("reason", ""))[:500],
            "grounded": grounded,
        })

    suggestions = []
    for item in result.get("suggestions", [])[:8]:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("source_quote", "")).strip()[:1500]
        grounded = bool(quote) and normalized_evidence(quote) in source
        rewrite = str(item.get("rewrite", "")).strip()[:1500]
        if not rewrite:
            continue
        suggestions.append({
            "requirement": str(item.get("requirement", "Role requirement"))[:300],
            "source_quote": quote,
            "rewrite": rewrite,
            "reason": str(item.get("reason", ""))[:500],
            "interview_question": str(item.get("interview_question", "How would you explain this experience in an interview?"))[:500],
            "needs_confirmation": bool(item.get("needs_confirmation", False)),
            "grounded": grounded,
        })

    experience_reviews = []
    for item in result.get("experience_reviews", [])[:20]:
        if not isinstance(item, dict):
            continue
        source_quote = str(item.get("source_quote", "")).strip()[:2000]
        source_grounded = bool(source_quote) and normalized_evidence(source_quote) in source
        if not source_grounded:
            continue
        source_entry = normalized_evidence(source_quote)
        impact_dimensions = {}
        for key in ("effect_quote", "scale_quote", "beneficiary_quote"):
            quote = str(item.get(key, "")).strip()[:800]
            grounded = bool(quote) and normalized_evidence(quote) in source_entry
            impact_dimensions[key.removesuffix("_quote")] = {
                "quote": quote if grounded else "",
                "grounded": grounded,
            }
        has_impact_evidence = any(value["grounded"] for value in impact_dimensions.values())
        experience_reviews.append({
            "experience_type": str(item.get("experience_type", "experience"))[:80],
            "source_quote": source_quote,
            "impact_dimensions": impact_dimensions,
            "impact_summary": str(item.get("impact_summary", ""))[:400] if has_impact_evidence else "",
            "follow_up_question": str(item.get("follow_up_question", "What changed because of this work, by how much, and who benefited?"))[:500],
            "has_impact_evidence": has_impact_evidence,
        })

    technical_learning_notes = []
    for item in result.get("technical_learning_notes", [])[:10]:
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill", "")).strip()[:200]
        job_quote = str(item.get("job_quote", "")).strip()[:1200]
        if not skill or not job_quote or normalized_evidence(job_quote) not in job_source:
            continue
        technical_learning_notes.append({
            "skill": skill,
            "job_quote": job_quote,
            "why_it_matters": str(item.get("why_it_matters", ""))[:400],
            "practice_step": str(item.get("practice_step", ""))[:500],
        })
    return {
        "requirements": requirements,
        "suggestions": suggestions,
        "experience_reviews": experience_reviews,
        "technical_learning_notes": technical_learning_notes,
    }


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
            role = str(data.get("role", "")).strip()[:150]
            job_description = str(data.get("jobDescription", "")).strip()[:6000]
            if not company or not resume:
                self.send_json(400, {"error": "Add a target company and resume text."})
                return
            if not role and not job_description:
                self.send_json(400, {"error": "Add a target role or job description so CareerLens can build a meaningful evidence map."})
                return
            if len(resume) > MAX_RESUME:
                self.send_json(413, {"error": "Resume text is too long. Keep it under 50,000 characters."})
                return
            normalized = {
                "company": company,
                "role": role,
                "jobDescription": job_description,
                "resume": resume,
            }
            job_posting = None
            job_context = None
            if not job_description:
                job_posting = find_public_job_listing(company, role)
                if job_posting:
                    normalized["jobDescription"] = job_posting["job_description"]
                    normalized["jobSourceURL"] = job_posting["source_url"]
                    normalized["jobTitle"] = job_posting["title"]
                else:
                    job_context = {
                        "kind": "benchmark",
                        "title": f"{role} role benchmark",
                        "source_title": "No exact public listing found. Requirements are role-based, not company-specific.",
                    }
            response_text, model = call_gemini(make_prompt(normalized))
            result = parse_evidence_response(response_text, resume, normalized["jobDescription"])
            self.send_json(200, {**result, "model": model, "job_posting": job_posting, "job_context": job_context})
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
