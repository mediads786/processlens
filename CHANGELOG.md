# Changelog

## 1.0.13 — Release candidate

- Added dedicated public landing page and interactive product preview.
- Added clearer five-stage icon navigation and distinct ProcessLens visual theme.
- Added semantic input-quality validation to reject non-process/nonsense input before AI analysis.
- Added loading states to every AI-triggering action.
- Kept Gemini as primary provider, Groq as optional backup, and the local engine as offline fallback.
- Workflow diagrams are rendered by ProcessLens from structured graph data rather than AI-generated images.
- Added public-mode error sanitization; provider diagnostics are hidden unless `PROCESSLENS_DEBUG_ERRORS=1`.
- Fixed Vercel routing so `/` shows the landing page and `/new` starts analysis.
- Fixed Vercel analysis route so the same input validation runs locally and in deployment.
- Retained PDF, CSV and JSON export, saved analyses, editable AS-IS workflow and human-approved TO-BE generation.

## 1.0.4

- Added Vercel/FastAPI entrypoint and deployment documentation.
- Added Vercel Blob persistence adapter.
- Added server-side provider environment variables and `/health` endpoint.
