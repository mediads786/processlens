# Deployment

## Vercel (recommended public deployment)

Vercel uses the root `app.py` FastAPI entrypoint. No custom start command is required.

Required setup:

- `GEMINI_API_KEY` — primary AI provider
- `GROQ_API_KEY` — optional backup
- Private Vercel Blob store — required for durable Saved Analyses on Vercel; connecting it supplies `BLOB_READ_WRITE_TOKEN`

See [VERCEL.md](VERCEL.md) for the exact steps.

## Local Windows development

Double-click `START_PROCESSLENS.bat`. It runs the existing standard-library local server and needs no web-host setup.

## Other Python hosts

The local server can also run with:

```text
python app/server.py
```

Useful environment variables:

- `GEMINI_API_KEY`
- `GROQ_API_KEY`
- `PROCESSLENS_PUBLIC=1`
- `PORT`
- `HOST`
- `PROCESSLENS_DATA_PATH` for a durable filesystem path

## Security

V1 has no account authentication or rate limiting. Public provider keys stay server-side, but visitors can consume the configured provider quota. Keep paid billing disabled if the deployment must remain free-only.
