from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs

# Vercel imports this module as an ASGI application. Keep the existing local
# server untouched and reuse its rendering/business functions here.
ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

os.environ.setdefault("PROCESSLENS_PUBLIC", "1")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

import server as core
from analyzer import analyze, generate_findings, generate_to_be
from report import export_csv, export_json, export_pdf
from vercel_store import BlobStore

app = FastAPI(title="ProcessLens", docs_url=None, redoc_url=None)

CLIENT_COOKIE = "processlens_client"
CLIENT_RE = re.compile(r"^[a-f0-9]{32}$")
ON_VERCEL = bool(os.getenv("VERCEL"))
HAS_BLOB = bool(os.getenv("BLOB_READ_WRITE_TOKEN"))


def _client_id(request: Request) -> str:
    value = request.cookies.get(CLIENT_COOKIE, "")
    return value if CLIENT_RE.fullmatch(value) else uuid.uuid4().hex


def _set_cookie(response: Response, client_id: str) -> Response:
    response.set_cookie(
            CLIENT_COOKIE,
            client_id,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            secure=ON_VERCEL,
        samesite="lax",
    )
    return response


def _store(request: Request):
    if HAS_BLOB:
        return BlobStore(_client_id(request))
    if ON_VERCEL:
        raise RuntimeError(
            "Persistent storage is not configured. Create a private Vercel Blob store "
            "for this project so BLOB_READ_WRITE_TOKEN is available."
        )
    return core.STORE


def _html(request: Request, content: str, status: int = 200) -> HTMLResponse:
    return _set_cookie(HTMLResponse(content, status_code=status), _client_id(request))


def _form_map(raw: bytes) -> dict[str, list[str]]:
    return parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)


def _analysis(store, request: Request):
    return store.get(request.query_params.get("id", ""))


@app.get("/")
def landing(request: Request):
    return _html(request, core.landing())


@app.get("/new")
def home(request: Request):
    error = ""
    if ON_VERCEL and not HAS_BLOB:
        error = "Deployment setup incomplete: private Vercel Blob storage is not configured."
    return _html(request, core.home(error))


@app.get("/health")
def health():
    return {
        "ok": True,
        "version": core.VERSION,
        "gemini_configured": bool(core.SESSION_GEMINI_KEY),
        "groq_configured": bool(core.SESSION_GROQ_KEY),
        "persistent_storage": "vercel-blob" if HAS_BLOB else ("local-file" if not ON_VERCEL else "missing"),
    }


@app.get("/saved")
def saved(request: Request):
    try:
        store = _store(request)
        return _html(request, core.saved(store.all()))
    except Exception as exc:
        return _html(request, core.home(core.user_error(exc, "Saved analyses are temporarily unavailable.")), 503)


@app.get("/asis")
def asis(request: Request):
    try:
        a = _analysis(_store(request), request)
        if not a:
            return _html(request, core.home("Analysis not found. Start a new one."), 404)
        return _html(request, core.asis(a))
    except Exception as exc:
        return _html(request, core.home(core.user_error(exc, "Saved analyses are temporarily unavailable.")), 503)


@app.get("/review")
def review(request: Request):
    try:
        a = _analysis(_store(request), request)
        if not a:
            return _html(request, core.home("Analysis not found. Start a new one."), 404)
        return _html(request, core.review(a))
    except Exception as exc:
        return _html(request, core.home(core.user_error(exc, "Saved analyses are temporarily unavailable.")), 503)


@app.get("/improvements")
def improvements(request: Request):
    try:
        store = _store(request)
        a = _analysis(store, request)
        if not a:
            return _html(request, core.home("Analysis not found. Start a new one."), 404)
        if not a.findings:
            a.findings, a.findings_mode = generate_findings(a, core.SESSION_GEMINI_KEY, core.SESSION_GROQ_KEY)
            store.put(a)
        return _html(request, core.improvements(a))
    except Exception as exc:
        return _html(request, core.home(core.user_error(exc, "Saved analyses are temporarily unavailable.")), 503)


@app.get("/tobe")
def tobe(request: Request):
    try:
        store = _store(request)
        a = _analysis(store, request)
        if not a:
            return _html(request, core.home("Analysis not found. Start a new one."), 404)
        if not a.findings:
            a.findings, a.findings_mode = generate_findings(a, core.SESSION_GEMINI_KEY, core.SESSION_GROQ_KEY)
        if not a.to_be_steps:
            a.to_be_steps, a.to_be_mode = generate_to_be(a, core.SESSION_GEMINI_KEY, core.SESSION_GROQ_KEY)
            store.put(a)
        return _html(request, core.tobe(a))
    except Exception as exc:
        return _html(request, core.home(core.user_error(exc, "Saved analyses are temporarily unavailable.")), 503)


@app.get("/export/{kind}")
def export(kind: str, request: Request):
    try:
        a = _analysis(_store(request), request)
        if not a:
            return _html(request, core.home("Analysis not found."), 404)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in a.process_name)[:50] or "process"
        if kind == "json":
            data, media, suffix = export_json(a), "application/json", ".json"
        elif kind == "csv":
            data, media, suffix = export_csv(a), "text/csv; charset=utf-8", ".csv"
        elif kind == "pdf":
            data, media, suffix = export_pdf(a), "application/pdf", ".pdf"
        else:
            return Response("Not found", status_code=404)
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{safe}{suffix}"'})
    except Exception as exc:
        return _html(request, core.home(core.user_error(exc, "Saved analyses are temporarily unavailable.")), 503)


@app.post("/extract-file")
async def extract_file(request: Request):
    try:
        data = await request.body()
        if len(data) > 4_000_000:
            return JSONResponse({"error": "File is too large. Maximum supported upload is 4 MB."}, status_code=413)
        name = request.headers.get("X-Filename", "file")
        return JSONResponse({"text": core.extract_file(name, data)})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Could not read the uploaded file."}, status_code=500)


@app.post("/analyze")
async def analyze_route(request: Request):
    form = _form_map(await request.body())
    name = form.get("process_name", [""])[0].strip()
    desc = form.get("description", [""])[0].strip()
    valid, validation_error = core.validate_process_input(name, desc)
    if not valid:
        return _html(request, core.home(validation_error, name, desc), 422)
    try:
        store = _store(request)
        a = analyze(uuid.uuid4().hex[:12], name, desc, core.SESSION_GEMINI_KEY, core.SESSION_GROQ_KEY)
        store.put(a)
        return _html(request, core.asis(a))
    except ValueError as exc:
        return _html(request, core.home(str(exc), name, desc), 400)
    except Exception as exc:
        return _html(request, core.home(core.user_error(exc, "Analysis could not be completed. Please try again."), name, desc), 503)


@app.post("/review/save")
async def save_review(request: Request):
    form = _form_map(await request.body())
    try:
        store = _store(request)
        a = store.get(form.get("id", [""])[0])
        if not a:
            return _html(request, core.home("Analysis not found."), 404)
        core.rebuild(form, a)
        a.findings, a.findings_mode = generate_findings(a, core.SESSION_GEMINI_KEY, core.SESSION_GROQ_KEY)
        store.put(a)
        return _html(request, core.improvements(a))
    except ValueError as exc:
        if "a" in locals() and a:
            return _html(request, core.review(a, str(exc)), 400)
        return _html(request, core.home(str(exc)), 400)
    except Exception as exc:
        return _html(request, core.home(core.user_error(exc, "Saved analyses are temporarily unavailable.")), 503)


@app.post("/tobe/generate")
async def generate_tobe(request: Request):
    form = _form_map(await request.body())
    try:
        store = _store(request)
        a = store.get(form.get("id", [""])[0])
        if not a:
            return _html(request, core.home("Analysis not found."), 404)
        if not a.findings:
            a.findings, a.findings_mode = generate_findings(a, core.SESSION_GEMINI_KEY, core.SESSION_GROQ_KEY)
        for i, finding in enumerate(a.findings):
            finding.accepted = f"finding_{i}" in form
        a.to_be_steps, a.to_be_mode = generate_to_be(a, core.SESSION_GEMINI_KEY, core.SESSION_GROQ_KEY)
        store.put(a)
        return _html(request, core.tobe(a))
    except Exception as exc:
        return _html(request, core.home(core.user_error(exc, "Saved analyses are temporarily unavailable.")), 503)
