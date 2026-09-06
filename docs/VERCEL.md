# Deploy ProcessLens to Vercel

ProcessLens uses Vercel's Python/FastAPI runtime for the public web app. The Windows `.bat` launcher is only for local development.

## 1. Push the repository to GitHub

Do not commit real API keys or `processlens_data.json`.

## 2. Import the GitHub repository in Vercel

Import the repository as a new Vercel project. The root `app.py` exposes the FastAPI application.

## 3. Configure AI environment variables

In **Vercel → Project → Settings → Environment Variables** add:

- `GEMINI_API_KEY` — primary provider.
- `GROQ_API_KEY` — optional backup.

ProcessLens falls back to its local analysis engine if online providers are unavailable.

Do **not** set `PROCESSLENS_DEBUG_ERRORS=1` in production unless temporarily troubleshooting; public mode normally hides raw provider/API errors.

## 4. Add durable storage

Create/connect a **Private Vercel Blob** store. Vercel provides `BLOB_READ_WRITE_TOKEN` to the project.

The Saved Analyses screen is isolated by a random HttpOnly browser identifier. This is suitable for the V1 portfolio/demo; it is not account authentication.

## 5. Deploy and verify

Check:

- `/` shows the ProcessLens landing page.
- `/new` opens New Analysis.
- `/health` returns `"ok": true`.
- `persistent_storage` reports `vercel-blob`.
- `gemini_configured` reports `true` when Gemini is configured.
- A valid process reaches AS-IS, Improvements and TO-BE.
- PDF, CSV and JSON exports download successfully.
