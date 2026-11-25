# CareerLens

CareerLens is a local resume tailoring website. The frontend uses HTML, CSS, and JavaScript. A small Python server serves the site and calls Gemini, keeping the API key out of browser code. It uses only Python's standard library; no CMake, vcpkg, compiler, or pip packages are needed.

## Start CareerLens

1. Install Python 3.10 or newer and the VS Code Python extension.
2. Open this folder in VS Code.
3. Check that `.env` contains your Gemini API key and a comma-separated `GEMINI_MODELS` list.
4. Press **Ctrl+Shift+P**, choose **Tasks: Run Task**, then choose **CareerLens: run server**. Or open Terminal and run `python app.py`.
5. Open <http://127.0.0.1:8080>.

Stop the server with **Ctrl+C** in its terminal. Change the port with `PORT` in `.env` if 8080 is already in use.

## Public deployment on Vercel

This repository includes a Vercel static frontend and a Python serverless endpoint. Import `Agransh7/CareerLens` into Vercel, set `GEMINI_API_KEY` in the project's Environment Variables, and deploy. Keep the key out of Git and do not upload `.env`. Set `GEMINI_MODELS` there too if the defaults are not enabled for your project.

Before sharing a public URL, configure a Vercel Firewall rate limit for `POST /api/tailor` (for example, 3 requests per minute per IP). Each successful request uses your Gemini API key and may create usage charges. CareerLens does not store resume text, but sends it to Gemini when submitted. Treat the deployment as public: anyone with the URL can use it.

## Gemini fallback

CareerLens tries the comma-separated models in `GEMINI_MODELS` in order. The default list is `gemini-3.8-flash,gemini-3.5-flash-lite,gemini-3.5-flash`. For temporary 429 or 5xx responses, it retries a model up to three times with short delays, then moves to the next model. Errors show which models were attempted. Adjust the list in `.env` if your Gemini project has different model access.

## GitHub pushes

In VS Code, run **Ctrl+Shift+P → Tasks: Run Task → CareerLens: commit and push**. Enter a commit message (or press Enter to use an automatic one). The task stages project changes, creates a commit, and pushes the current branch to the Git remote named `origin`. It refuses to push if `.env` is tracked or is not ignored. Git Credential Manager handles GitHub sign-in; no GitHub token belongs in project files. The first run requires a GitHub repository URL configured as `origin`.

## Features and limits

- Upload a PDF, DOCX, or TXT resume; browser-side text extraction keeps files local.
- Optionally enter a target role and job description.
- If the job description is left blank, CareerLens checks the free, no-key Arbeitnow public job feed for a company and role match. When it finds one, the site shows the listing source and reviews its description. The feed focuses mainly on European jobs, so if no exact match appears, CareerLens uses general role-based expectations and labels them as not company-specific. For the most accurate review, paste the specific job description.
- Evidence Mode maps role requirements to exact resume excerpts and proposes edits that preserve their source quote.
- An experience review scans jobs, internships, projects, research, volunteering, and leadership for outcomes, measurable scale, and beneficiaries. It flags missing impact and asks the candidate for real results rather than making up numbers.
- A technical learning panel lists required job-posting skills not mentioned in the resume as learning requirements. When there is no exact posting, it uses common role-based technical expectations and labels them accordingly.
- Review, edit, add, or remove suggestions; unverified quotes cannot be applied to the preview.
- Each suggestion includes an interview question. Suggestions flagged for confirmation must be cleared before copying or downloading.
- Copy or download the updated resume preview as Markdown.
- Open a prefilled Gmail draft addressed to the recruiter or company email you enter, with the generated resume in the email body. Review and send it from Gmail. Direct automatic sending requires a Google OAuth setup, which this project does not include.
- Resume text is sent to Gemini only when you submit. CareerLens does not save the file or request.
- PDF reading uses PDF.js from a CDN. Scanned PDFs need OCR, which this starter does not include.

Always review generated content for accuracy before applying.

## Interview notes

This project uses Python's `ThreadingHTTPServer` and `urllib` to create a small local API proxy. The model fallback loop handles transient upstream failures, while `.env` keeps the API key server-side. A production service should use a mature web framework, structured retries with jitter, request authentication and rate limits, and a robust resume parser.
