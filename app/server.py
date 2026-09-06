from __future__ import annotations
import html
import io
import json
import os
import socket
import threading
import uuid
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

from analyzer import analyze, generate_findings, generate_to_be
from models import Step
from report import export_csv, export_json, export_pdf
from store import Store

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = Path(os.getenv("PROCESSLENS_DATA_PATH", str(ROOT / "processlens_data.json")))
STORE = Store(DATA_PATH, legacy_path=ROOT / "app" / "processlens_data.json")
SESSION_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
SESSION_GROQ_KEY = os.getenv("GROQ_API_KEY", "").strip()
PUBLIC_MODE = os.getenv("PROCESSLENS_PUBLIC", "").strip().lower() in {"1", "true", "yes"} or bool(os.getenv("PORT"))
DEBUG_ERRORS = os.getenv("PROCESSLENS_DEBUG_ERRORS", "").strip().lower() in {"1", "true", "yes"}
HOST = os.getenv("HOST", "0.0.0.0" if PUBLIC_MODE else "127.0.0.1")
START_PORT = int(os.getenv("PORT", "8891"))
VERSION = "1.0.13"



def provider_label(mode: str) -> str:
    """Hide provider diagnostics from end users unless debug mode is enabled."""
    mode = str(mode or "")
    if DEBUG_ERRORS or " — " not in mode:
        return mode
    if mode.startswith("Local fallback"):
        return "Local fallback — online AI unavailable"
    return mode.split(" — ", 1)[0]


def user_error(exc: object, fallback: str = "Something went wrong. Please try again.") -> str:
    """Return technical diagnostics only in explicit debug mode."""
    if DEBUG_ERRORS:
        return str(exc)
    return fallback

CSS = r'''
:root{
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  color:#2C2930;background:#F4F1EC;
  --ink:#2C2930;--ink-strong:#17161C;--muted:#756F78;--accent:#6A4F61;
  --accent-deep:#4E3948;--accent-soft:#EFE8ED;--line:#DDD7D1;--panel:#FCFBF8;
  --success:#657A66;--warning:#A17D4B;--danger:#9C5E5B;
}
*{box-sizing:border-box}
html{background:#F4F1EC}
body{margin:0;background:#F4F1EC;color:var(--ink);-webkit-font-smoothing:antialiased}
header{
  height:66px;background:rgba(252,251,248,.97);border-bottom:1px solid var(--line);
  display:flex;align-items:center;justify-content:space-between;padding:0 30px;
  position:sticky;top:0;z-index:4;backdrop-filter:saturate(150%) blur(10px)
}
header span{font-size:11px;color:#7A8591;letter-spacing:.02em}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;color:var(--ink-strong);text-decoration:none;letter-spacing:-.02em}
.brand:before{content:"P";display:grid;place-items:center;width:29px;height:29px;border-radius:8px;background:#2D2930;color:#fff;font-size:13px;font-weight:900;letter-spacing:0}
.layout{display:grid;grid-template-columns:205px minmax(0,1fr);max-width:1420px;margin:auto;min-height:calc(100vh - 66px)}
.nav{padding:30px 18px;border-right:1px solid #E1DBD5;background:#F0ECE7}
.nav a{display:block;text-decoration:none;color:#736972;padding:11px 13px;border-radius:5px;margin-bottom:6px;font-size:13.5px;font-weight:700;transition:.16s ease}
.nav a.active{background:#E6DDD8;color:#4B3744;box-shadow:inset 3px 0 0 #6A4F61}
@media(hover:hover){.nav a:hover{background:#EAE4DF;color:#4A3B45}}
main{padding:38px 34px 68px;min-width:0;max-width:1210px;width:100%;margin:0 auto}
.stages{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin-bottom:38px;border-bottom:1px solid #D8D1CB;background:transparent}
.stage{min-height:88px;border:0;border-bottom:4px solid transparent;background:transparent;color:#7B737A;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;padding:9px 10px 10px;font-size:15px;font-weight:760;letter-spacing:-.005em;transition:color .15s,background .15s,border-color .15s}
.stage-icon{font-size:29px;line-height:1;color:#8D858B}
.stage-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
.stage-hint{font-size:10.5px;font-weight:600;color:#9A9298;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
.stage.current{color:#442C3B;border-bottom-color:#5B3A50;background:linear-gradient(180deg,rgba(91,58,80,.08),rgba(91,58,80,.16))}
.stage.current .stage-icon{color:#5B3A50}
.stage.current .stage-label{color:#442C3B;font-weight:820}
.stage.current .stage-hint{color:#6A5261}
.stage.done{color:#5D6B5B;border-bottom-color:#B8C3B3}
.stage.done .stage-icon{color:#657A66}
@media(hover:hover){.stage:hover{background:#F8F4F0;color:#554B52}}
.hero,.pagehead{display:flex;justify-content:space-between;gap:34px;align-items:flex-start;margin-bottom:26px}
.hero>div:first-child,.pagehead>div:first-child{max-width:790px}
.eyebrow{color:#755E6D;font-size:10.5px;font-weight:800;letter-spacing:.16em;margin-bottom:9px;text-transform:uppercase}
h1{font-size:34px;line-height:1.14;margin:0 0 11px;color:var(--ink-strong);font-weight:760;letter-spacing:-.035em}
h2{font-size:17px;margin:0 0 16px;color:#24313E;font-weight:720;letter-spacing:-.015em}
h3{margin:11px 0 7px;color:#2B3742;font-size:15px}
p{color:var(--muted);line-height:1.62;margin-top:8px}
.scope{min-width:285px;background:#F6F2EE;border:1px solid #DED6CF;border-radius:7px;padding:16px 17px;display:flex;flex-direction:column;gap:6px;font-size:12.5px;color:#5F6B77}
.scope b{color:#293844;font-size:12px;letter-spacing:.02em}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:24px;margin-bottom:18px;box-shadow:0 1px 2px rgba(45,38,43,.025)}
.panel form{max-width:900px}
label{display:block;font-size:12.5px;font-weight:680;color:#465361;margin-bottom:18px}
input,textarea,select{display:block;width:100%;margin-top:7px;border:1px solid #CBD2D9;border-radius:5px;padding:11px 12px;font:inherit;color:var(--ink);background:#FCFDFD;transition:border-color .15s,box-shadow .15s,background .15s}
textarea{min-height:180px;resize:vertical}
input:focus,textarea:focus,select:focus{outline:none;border-color:#8D7484;box-shadow:0 0 0 3px rgba(106,79,97,.11);background:#fff}
button,.primary{border:1px solid var(--accent-deep);background:var(--accent-deep);color:#fff;border-radius:5px;padding:11px 16px;font-weight:720;cursor:pointer;text-decoration:none;font-size:12.5px;letter-spacing:.005em;transition:background .15s,border-color .15s,transform .05s,opacity .15s}
@media(hover:hover){button:hover,.primary:hover{background:#3F2E3A;border-color:#3F2E3A}}
button:active,.primary:active{transform:translateY(1px)}
button:disabled{opacity:.7;cursor:wait;transform:none}
button[aria-busy="true"]:before{content:"";display:inline-block;width:12px;height:12px;margin-right:8px;border:2px solid rgba(255,255,255,.45);border-top-color:#fff;border-radius:50%;vertical-align:-2px;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.secondary{background:#F1ECE8;color:#4B4148;border-color:#DCD3CC}
@media(hover:hover){.secondary:hover{background:#E9E1DB;border-color:#CFC3BA;color:#3D333A}}
.danger{background:#FFF7F5;color:#96594E;border-color:#ECD7D2}
@media(hover:hover){.danger:hover{background:#FBEFEB;border-color:#E6C8C1;color:#874D43}}
.link{display:inline-block;text-decoration:none;padding:10px 13px;border-radius:7px;font-weight:690}
.muted{font-weight:500;color:#8A949F}
.uploadrow{display:flex;align-items:center;gap:12px;margin:-4px 0 18px}
.filebtn{display:inline-block;margin:0;background:#F0F3F5;border:1px solid #DCE2E6;border-radius:7px;padding:9px 12px;cursor:pointer;color:#394B58}
.filebtn input{display:none}.uploadrow span{font-size:11.5px;color:var(--muted)}
.alert{padding:12px 14px;border-radius:8px;margin-bottom:17px;font-size:13px}
.alert.error{background:#FFF5F3;color:#8C493E;border:1px solid #EDD4CF}
.tablewrap{overflow:auto;border:1px solid #E7EAED;border-radius:8px}
table{width:100%;border-collapse:collapse;min-width:820px;font-size:12px;background:#fff}
th,td{padding:10px 11px;border-bottom:1px solid #ECEFF1;text-align:left;vertical-align:top}
th{font-size:9.5px;text-transform:uppercase;color:#7C8792;background:#FAFBFB;letter-spacing:.08em}
tbody tr:last-child td{border-bottom:0}
.mode{display:inline-block;background:#F0E9ED;border:1px solid #DED1D8;border-radius:999px;padding:5px 9px;font-size:10.5px;color:#644D5C;font-weight:700}
.toolbar{display:flex;justify-content:flex-end;gap:10px;margin-bottom:13px}
.editrow{display:grid;grid-template-columns:38px minmax(0,1fr) 75px;gap:13px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:15px;margin-bottom:10px}
.num{text-align:center;color:#87929C;padding-top:9px;font-size:12px}
.fieldgrid{display:grid;grid-template-columns:.65fr 1fr 1fr;gap:10px}.fields label{margin-bottom:10px;font-size:11px}.fields textarea{min-height:54px}
.check{display:flex;align-items:center;gap:8px}.check input{width:auto;margin:0}.rowbuttons{display:flex;flex-direction:column;gap:6px}.rowbuttons button{padding:8px}
.findings{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.finding{background:#fff;border:1px solid var(--line);border-left:3px solid #8EA3AF;border-radius:10px;padding:18px;transition:opacity .15s,border-color .15s}
.finding.high{border-left-color:#B66D61}.finding.medium{border-left-color:#B28B4A}
.pill,.severity{display:inline-block;font-size:9.5px;padding:4px 7px;border-radius:999px;background:#EEF2F4;color:#596873;margin-right:6px;font-weight:650}
.severity{background:#F6F0E4;color:#846A36}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:18px}
.metrics div{background:#fff;border:1px solid var(--line);border-radius:10px;padding:17px 18px}.metrics b{display:block;font-size:27px;color:#1E2B35;letter-spacing:-.03em}.metrics span{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.exports{display:flex;gap:7px}.done{margin-top:18px;padding:14px 16px;border:1px solid #D7DEE2;border-radius:9px;background:#F8FAFA;color:#5E6B76;font-size:12.5px}
.savedlist{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}.savedcard{background:#fff;border:1px solid var(--line);padding:16px 17px;border-radius:9px;text-decoration:none;color:#273844;transition:border-color .15s,transform .1s,box-shadow .15s}.savedcard b,.savedcard span{display:block}.savedcard span{font-size:10.5px;color:var(--muted);margin-top:5px}
@media(hover:hover){.savedcard:hover{border-color:#BAC7CD;box-shadow:0 5px 16px rgba(21,32,42,.045);transform:translateY(-1px)}}
.recommend-choice{margin-top:16px;display:flex;align-items:center;gap:10px;padding:11px 12px;border:1px solid #DCE3E7;border-radius:8px;background:#F8FAFB;font-weight:670;color:#364C59}.recommend-choice input{width:17px;height:17px}.sticky-action{display:flex;justify-content:flex-end;margin:18px 0 32px}.finding:has(.recommend-choice input:not(:checked)){opacity:.56;border-style:dashed}
.ai-status{padding:12px 14px;border:1px solid #DDE3E7;border-radius:8px;background:#F8FAFB;margin:4px 0 14px}.ai-status b{display:block;margin-bottom:5px;color:#31424F}.ai-status span{color:#65727D;font-size:.86rem}.provider-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.provider-grid label{margin-bottom:5px}.provider-note{font-size:11px;color:#77838E;margin:8px 0 16px}
.diagram-scroll{overflow:auto;border:1px solid #E1DAD4;border-radius:7px;background:#F8F5F1;padding:14px}.workflow-svg{display:block;margin:auto;min-width:680px}.compare{display:grid;grid-template-columns:1fr 1fr;gap:18px}.compare .panel{min-width:0}.compare .workflow-svg{min-width:620px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:10.5px;color:#776F76;margin:-6px 0 13px}.legend span:before{content:"";display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px;border:1px solid #8A7482;background:#F2EEF2}.legend .decision:before{background:#F4EBDD;border-color:#AA8956}.legend .auto:before{background:#EEF2EA;border-color:#7B9078}.legend .issue:before{background:#F5EAE7;border-color:#AA746B}

.landing{max-width:1080px;margin:0 auto;padding:18px 0 24px}
.landing-hero{padding:46px 0 34px;border-bottom:1px solid var(--line);display:grid;grid-template-columns:minmax(0,1.35fr) minmax(280px,.65fr);gap:54px;align-items:center}
.landing-hero h1{font-size:46px;max-width:760px;margin-bottom:16px}
.landing-hero p{font-size:17px;max-width:720px;color:#6D666C}
.landing-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:25px}
.landing-actions .primary,.landing-actions .secondary{padding:13px 19px;font-size:13.5px}
.landing-preview{background:#EEE7E3;border:1px solid #D9CFC8;border-radius:10px;padding:18px;box-shadow:0 12px 30px rgba(55,40,49,.06)}
.preview-kicker{font-size:10px;letter-spacing:.14em;text-transform:uppercase;font-weight:800;color:#765E6D;margin-bottom:12px}
.preview-tabs{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:14px;padding:4px;background:#E6DDD8;border-radius:8px}
.preview-tab{border:0;background:transparent;color:#746B71;padding:8px 7px;border-radius:6px;font-size:11px;font-weight:800;cursor:pointer;transition:.18s ease}
.preview-tab.active{background:#FCFBF8;color:#5C3F51;box-shadow:0 1px 5px rgba(60,42,53,.08)}
.preview-flow{display:flex;flex-direction:column;gap:9px;min-height:188px}
.preview-step{background:#FCFBF8;border:1px solid #D9D0CB;border-radius:7px;padding:11px 13px;font-size:12.5px;font-weight:700;color:#493E45;position:relative;transition:opacity .18s ease,transform .18s ease}
.preview-step:not(:last-child):after{content:"↓";position:absolute;left:50%;bottom:-16px;transform:translateX(-50%);color:#8B7F87;font-weight:800;z-index:2}
.preview-step.issue{border-color:#CDA79E;background:#F6ECE9}.preview-step.future{border-color:#A8B69F;background:#EEF2EA}
.preview-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:13px;padding-top:11px;border-top:1px solid #D8CEC8;color:#746B71;font-size:10.5px}
.preview-foot b{color:#5C3F51}.landing-actions .primary{box-shadow:0 8px 18px rgba(91,61,79,.12)}
@media(hover:hover){.landing-actions .primary:hover{transform:translateY(-1px)}.offer-card:hover{border-color:#CBBBC4;transform:translateY(-2px);box-shadow:0 8px 22px rgba(55,40,49,.05)}}
.offer-card{transition:.18s ease}
.landing-section{padding:34px 0}.landing-section h2{font-size:22px;margin-bottom:8px}.landing-section>p{max-width:720px;margin-bottom:22px}
.offer-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.offer-card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:20px}.offer-icon{font-size:24px;color:#65485B;margin-bottom:12px}.offer-card h3{font-size:15px;margin:0 0 7px}.offer-card p{font-size:12.5px;margin:0}
.how-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.how-step{padding:20px 14px;border-right:1px solid var(--line)}.how-step:last-child{border-right:0}.how-num{font-size:11px;font-weight:850;color:#765E6D;letter-spacing:.08em;margin-bottom:9px}.how-step b{display:block;font-size:13px;color:#352D32;margin-bottom:5px}.how-step span{font-size:11px;line-height:1.45;color:#847B82}
.landing-note{margin-top:24px;padding:16px 18px;background:#F0ECE7;border-left:3px solid #6A4F61;color:#625A60;font-size:12.5px;line-height:1.55}
@media(max-width:900px){.landing-hero{grid-template-columns:1fr;gap:26px;padding-top:24px}.landing-hero h1{font-size:36px}.offer-grid{grid-template-columns:1fr}.how-grid{grid-template-columns:1fr}.how-step{border-right:0;border-bottom:1px solid var(--line)}.how-step:last-child{border-bottom:0}.layout{grid-template-columns:1fr}.nav{display:flex;padding:10px 16px;border-right:0;border-bottom:1px solid var(--line);background:#F8F9FA;overflow:auto}.nav a{margin:0 5px 0 0;white-space:nowrap}.hero,.pagehead{display:block}.scope{margin-top:15px;min-width:0}.findings,.compare,.provider-grid{grid-template-columns:1fr}.fieldgrid{grid-template-columns:1fr}.savedlist{grid-template-columns:1fr}.pagehead .primary,.pagehead form,.exports{margin-top:14px}.metrics{grid-template-columns:1fr}main{padding:28px 17px 52px}h1{font-size:29px}}
@media(max-width:600px){header{padding:0 16px}header>span{display:none}.editrow{grid-template-columns:28px 1fr}.rowbuttons{grid-column:2;flex-direction:row}.toolbar{justify-content:stretch;flex-wrap:wrap}.toolbar button{flex:1}.panel{padding:18px}.stages{grid-template-columns:repeat(5,minmax(78px,1fr));overflow-x:auto}.stage{min-height:72px;padding:8px 6px}.stage-icon{font-size:24px}.stage-label{font-size:13px}.stage-hint{font-size:9px}}
'''



def validate_process_input(name: str, description: str) -> tuple[bool, str]:
    """Reject obviously non-process input before spending an AI request.

    This is intentionally conservative: it only blocks input that lacks enough
    process structure to analyze. The user can still describe processes in
    natural language without following a template.
    """
    import re

    name = (name or "").strip()
    description = " ".join((description or "").split())
    if len(name) < 3:
        return False, "Please give the process a short, meaningful name."
    if len(description) < 45:
        return False, "Please describe at least a few steps of the process before analyzing it."

    text = description.lower()
    non_process_phrases = (
        "i don't know", "i dont know", "i do not know", "what you can",
        "what can you", "who will explain", "can't understand", "cant understand",
        "cannot understand", "don't understand", "dont understand",
    )
    uncertainty_hits = sum(1 for phrase in non_process_phrases if phrase in text)

    action_verbs = {
        "receive", "receives", "received", "review", "reviews", "check", "checks",
        "verify", "verifies", "create", "creates", "send", "sends", "approve",
        "approves", "assign", "assigns", "contact", "contacts", "update", "updates",
        "record", "records", "enter", "enters", "collect", "collects", "process",
        "processes", "submit", "submits", "notify", "notifies", "route", "routes",
        "schedule", "schedules", "invoice", "invoices", "pay", "pays", "deliver",
        "delivers", "resolve", "resolves", "escalate", "escalates", "close", "closes",
        "open", "opens", "inspect", "inspects", "confirm", "confirms", "validate",
        "validates", "upload", "uploads", "download", "downloads", "handover",
        "hands", "forward", "forwards", "request", "requests", "generate", "generates",
        "compare", "compares", "match", "matches", "reconcile", "reconciles",
    }
    words = re.findall(r"[a-z]+", text)
    action_hits = sum(1 for word in words if word in action_verbs)

    sequence_markers = (
        " then ", " next ", " after ", " before ", " once ", " when ",
        " first ", " finally ", " followed by ", " if ", " until ", " while ",
    )
    padded = f" {text} "
    sequence_hits = sum(1 for marker in sequence_markers if marker in padded)
    sentence_like_steps = len([x for x in re.split(r"[\n.;]+", description) if len(x.strip()) >= 12])

    enough_structure = (action_hits >= 3) or (action_hits >= 2 and (sequence_hits >= 1 or sentence_like_steps >= 3))
    if uncertainty_hits >= 2 and not enough_structure:
        return False, (
            "This does not appear to describe a business process yet. "
            "Please describe what happens in order — for example: who starts the process, "
            "the main actions/decisions, and where it ends."
        )
    if not enough_structure:
        return False, (
            "ProcessLens needs a little more process detail before it can build a workflow. "
            "Include at least 2–3 actions in sequence, such as who receives something, "
            "what they check/do next, any decision, and the final outcome."
        )
    return True, ""

def esc(v):
    return html.escape(str(v), quote=True)


def nav(active=""):
    items = [("New Analysis", "/new"), ("Saved Analyses", "/saved")]
    return '<nav class="nav">' + ''.join(
        f'<a class="{("active" if active == name else "")}" href="{href}">{name}</a>'
        for name, href in items
    ) + '</nav>'


def shell(title, body, active="", script=""):
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · ProcessLens</title><style>{CSS}</style></head><body><header><a class="brand" href="/">ProcessLens</a><span>{VERSION} · Gemini 3.5 Flash → Groq → Local</span></header><div class="layout">{nav(active)}<main>{body}</main></div>{('<script>'+script+'</script>') if script else ''}</body></html>'''


def stagebar(n):
    steps = [
        ("▤", "Input", "Describe process"),
        ("⌘", "AS-IS", "Current state"),
        ("◫", "Review", "Refine steps"),
        ("✦", "Improve", "AI suggestions"),
        ("◎", "TO-BE", "Future state"),
    ]
    items = []
    for i, (icon, name, hint) in enumerate(steps, 1):
        state = "done" if i < n else "current" if i == n else ""
        items.append(
            f'<div class="stage {state}" aria-current="{("step" if i == n else "false")}" title="Step {i}: {esc(hint)}">'
            f'<span class="stage-icon" aria-hidden="true">{icon}</span>'
            f'<span class="stage-label">{name}</span>'
            f'<span class="stage-hint">{hint}</span></div>'
        )
    return '<div class="stages" aria-label="Process progress">' + ''.join(items) + '</div>'


def _wrap(text: str, width: int = 27, max_lines: int = 3) -> list[str]:
    words = str(text).split()
    lines, line = [], ""
    for word in words:
        candidate = (line + " " + word).strip()
        if len(candidate) <= width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
        if len(lines) >= max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and words and len(" ".join(lines)) < len(str(text)):
        lines[-1] = lines[-1][:max(1, width - 1)].rstrip() + "…"
    return lines or [""]


def workflow_svg(steps: list[Step]) -> str:
    if not steps:
        return '<p class="muted">No workflow generated.</p>'
    by_id = {s.id: s for s in steps}
    start = next((s for s in steps if s.type == "start"), steps[0])
    levels = {start.id: 0}
    for _ in range(len(steps) + 2):
        changed = False
        for s in sorted(steps, key=lambda x: x.id):
            level = levels.get(s.id, 0)
            for target in s.next_step_ids:
                if target in by_id and target != s.id:
                    new_level = min(level + 1, len(steps) + 1)
                    if levels.get(target, -1) < new_level:
                        levels[target] = new_level
                        changed = True
        if not changed:
            break
    for i, s in enumerate(steps):
        levels.setdefault(s.id, i)
    groups: dict[int, list[Step]] = {}
    for s in steps:
        groups.setdefault(levels[s.id], []).append(s)
    max_cols = max(len(v) for v in groups.values())
    width = max(760, 120 + max_cols * 270)
    level_gap = 150
    height = 90 + (max(groups) + 1) * level_gap
    pos: dict[int, tuple[float, float]] = {}
    for level, nodes in groups.items():
        spacing = width / (len(nodes) + 1)
        for idx, node in enumerate(sorted(nodes, key=lambda x: x.id), 1):
            pos[node.id] = (spacing * idx, 55 + level * level_gap)
    marker = f"arr{abs(hash(tuple(sorted(by_id)))) % 100000}"
    parts = [f'<div class="diagram-scroll"><svg class="workflow-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Workflow diagram">',
             '<defs>',
             f'<marker id="{marker}" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#9A9096"/></marker>',
             '</defs>']
    for s in steps:
        if s.id not in pos:
            continue
        x1, y1 = pos[s.id]
        h1 = 54 if s.type in {"start", "end"} else 92
        for target in s.next_step_ids:
            if target not in pos:
                continue
            x2, y2 = pos[target]
            h2 = 54 if by_id[target].type in {"start", "end"} else 92
            sy = y1 + h1 / 2
            ty = y2 - h2 / 2
            mid = (sy + ty) / 2
            parts.append(f'<path d="M{x1:.1f},{sy:.1f} V{mid:.1f} H{x2:.1f} V{ty:.1f}" fill="none" stroke="#A79EA4" stroke-width="1.8" marker-end="url(#{marker})"/>')
            label = s.next_step_labels.get(target, "")
            if label:
                lx = (x1 + x2) / 2
                parts.append(f'<rect x="{lx-31:.1f}" y="{mid-17:.1f}" width="62" height="20" rx="10" fill="#FFFFFF" stroke="#DDD4CE"/>')
                parts.append(f'<text x="{lx:.1f}" y="{mid-3:.1f}" text-anchor="middle" font-size="10" font-weight="700" fill="#6E626A">{esc(label)}</text>')
    for s in steps:
        x, y = pos[s.id]
        automated = s.automation == "automated"
        issue = s.is_issue
        if s.type in {"start", "end"}:
            w, h = 170, 54
            parts.append(f'<rect x="{x-w/2:.1f}" y="{y-h/2:.1f}" width="{w}" height="{h}" rx="27" fill="#EEF2EA" stroke="#71816F" stroke-width="2"/>')
            parts.append(f'<text x="{x:.1f}" y="{y+5:.1f}" text-anchor="middle" font-size="13" font-weight="800" fill="#536451">{esc(s.name)}</text>')
            continue
        w, h = 230, 92
        fill = "#EEF2EA" if automated else "#F2EEF2"
        stroke = "#7B9078" if automated else "#8A7482"
        if s.type == "decision":
            fill, stroke = "#F4EBDD", "#AA8956"
            pts = f"{x:.1f},{y-h/2:.1f} {x+w/2:.1f},{y:.1f} {x:.1f},{y+h/2:.1f} {x-w/2:.1f},{y:.1f}"
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        else:
            parts.append(f'<rect x="{x-w/2:.1f}" y="{y-h/2:.1f}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        lines = _wrap(s.name, 28, 2 if s.type == "decision" else 3)
        start_y = y - 14 if len(lines) > 1 else y - 5
        for i, line in enumerate(lines):
            parts.append(f'<text x="{x:.1f}" y="{start_y + i*16:.1f}" text-anchor="middle" font-size="12" font-weight="800" fill="#3C343A">{esc(line)}</text>')
        meta = f"{s.actor} · {s.system}"
        parts.append(f'<text x="{x:.1f}" y="{y+32:.1f}" text-anchor="middle" font-size="9.5" fill="#7B7077">{esc(meta[:52])}</text>')
        if automated:
            parts.append(f'<rect x="{x-w/2+7:.1f}" y="{y-h/2+7:.1f}" width="42" height="17" rx="8" fill="#DDE7D8"/>')
            parts.append(f'<text x="{x-w/2+28:.1f}" y="{y-h/2+19:.1f}" text-anchor="middle" font-size="8" font-weight="800" fill="#596D56">AUTO</text>')
        if issue:
            parts.append(f'<circle cx="{x+w/2-12:.1f}" cy="{y-h/2+13:.1f}" r="9" fill="#F8EFEC" stroke="#B98370"/>')
            parts.append(f'<text x="{x+w/2-12:.1f}" y="{y-h/2+17:.1f}" text-anchor="middle" font-size="11" font-weight="900" fill="#8F5E4B">!</text>')
    parts.append('</svg></div>')
    return ''.join(parts)


def legend():
    return '<div class="legend"><span>Activity</span><span class="decision">Decision</span><span class="auto">Automated</span><span class="issue">Issue</span></div>'


def landing():
    return shell("AI workflow analysis", f'''
    <section class="landing">
      <section class="landing-hero">
        <div>
          <div class="eyebrow">PROCESS ANALYSIS · SIMPLIFIED</div>
          <h1>See how work happens today — and how it could work better.</h1>
          <p>ProcessLens turns a written business process into a visual AS-IS workflow, helps you review bottlenecks and automation opportunities, then produces an improved TO-BE workflow.</p>
          <div class="landing-actions">
            <a class="primary" href="/new">Start a new analysis →</a>
            <a class="secondary link" href="/saved">Open saved analyses</a>
          </div>
        </div>
        <div class="landing-preview" aria-label="Interactive ProcessLens example">
          <div class="preview-kicker">SEE A PROCESS CHANGE IN SECONDS</div>
          <div class="preview-tabs" role="tablist" aria-label="Example stages">
            <button class="preview-tab active" type="button" data-demo="asis">AS-IS</button>
            <button class="preview-tab" type="button" data-demo="findings">Findings</button>
            <button class="preview-tab" type="button" data-demo="tobe">TO-BE</button>
          </div>
          <div id="previewFlow" class="preview-flow" aria-live="polite"></div>
          <div class="preview-foot"><span>Example: customer complaint handling</span><b id="previewLabel">Current state</b></div>
        </div>
      </section>

      <section class="landing-section">
        <h2>What ProcessLens does</h2>
        <p>You do not need process-mapping expertise. Describe the work as it happens; ProcessLens structures it and keeps you in control of what changes.</p>
        <div class="offer-grid">
          <div class="offer-card"><div class="offer-icon">▤</div><h3>Map the current process</h3><p>Convert written steps into an editable AS-IS workflow with activities, decisions, actors and systems.</p></div>
          <div class="offer-card"><div class="offer-icon">✦</div><h3>Find friction</h3><p>Review bottlenecks, manual work, handoffs and automation opportunities instead of accepting AI blindly.</p></div>
          <div class="offer-card"><div class="offer-icon">◎</div><h3>Design the future state</h3><p>Accept or reject recommendations and generate a TO-BE workflow based on the improvements you approve.</p></div>
        </div>
      </section>

      <section class="landing-section">
        <h2>How it works</h2>
        <div class="how-grid">
          <div class="how-step"><div class="how-num">01</div><b>Input</b><span>Describe or upload the current process.</span></div>
          <div class="how-step"><div class="how-num">02</div><b>AS-IS</b><span>See the process as it works today.</span></div>
          <div class="how-step"><div class="how-num">03</div><b>Review</b><span>Correct steps, roles and decisions.</span></div>
          <div class="how-step"><div class="how-num">04</div><b>Improve</b><span>Review issues and recommendations.</span></div>
          <div class="how-step"><div class="how-num">05</div><b>TO-BE</b><span>Generate and export the improved process.</span></div>
        </div>
        <div class="landing-note"><b>AI assists; you decide.</b> ProcessLens keeps the workflow editable and requires human review before recommendations shape the future-state process.</div>
      </section>
    </section>
    ''' , "", '''
const previewData={
  asis:{label:'Current state',steps:[
    ['Customer complaint arrives by email',''],
    ['Agent copies details into spreadsheet','issue'],
    ['Supervisor approval waits in inbox','issue']
  ]},
  findings:{label:'What ProcessLens finds',steps:[
    ['Duplicate data entry','issue'],
    ['Approval handoff creates delay','issue'],
    ['No single status view','issue']
  ]},
  tobe:{label:'Improved state',steps:[
    ['Complaint captured once','future'],
    ['Rules route the case automatically','future'],
    ['Supervisor reviews only exceptions','future']
  ]}
};
const flow=document.querySelector('#previewFlow'),label=document.querySelector('#previewLabel'),tabs=[...document.querySelectorAll('.preview-tab')];
function renderPreview(key){
  const d=previewData[key];
  flow.innerHTML=d.steps.map(([text,cls])=>`<div class="preview-step ${cls}">${text}</div>`).join('');
  label.textContent=d.label;
  tabs.forEach(t=>t.classList.toggle('active',t.dataset.demo===key));
}
tabs.forEach(t=>t.addEventListener('click',()=>renderPreview(t.dataset.demo)));
renderPreview('asis');
''')


def home(error="", name="", desc=""):
    err = f'<div class="alert error">{esc(error)}</div>' if error else ''
    g_status = "server configured" if PUBLIC_MODE and SESSION_GEMINI_KEY else "active" if SESSION_GEMINI_KEY else "not set"
    q_status = "server configured" if PUBLIC_MODE and SESSION_GROQ_KEY else "active" if SESSION_GROQ_KEY else "not set"
    g_placeholder = "Leave blank to reuse active Gemini key" if SESSION_GEMINI_KEY else "Gemini API key (optional)"
    q_placeholder = "Leave blank to reuse active Groq key" if SESSION_GROQ_KEY else "Groq API key (optional backup)"
    if PUBLIC_MODE:
        provider_inputs = '<div class="provider-note">API keys are configured on the server and are never sent to the browser.</div>'
    else:
        provider_inputs = f'<div class="provider-grid"><label>Gemini — primary<input type="password" name="gemini_key" autocomplete="off" placeholder="{esc(g_placeholder)}"></label><label>Groq — free-plan backup<input type="password" name="groq_key" autocomplete="off" placeholder="{esc(q_placeholder)}"></label></div><div class="provider-note">Keys remain in memory only until ProcessLens closes; they are not written to the saved-analysis file.</div>'
    return shell("New Analysis", f'''{stagebar(1)}<section class="hero"><div><div class="eyebrow">NEW ANALYSIS</div><h1>Turn a real process into an editable workflow.</h1><p>Online AI builds the workflow graph; ProcessLens renders it consistently. If online AI is unavailable, the local engine still works.</p></div><div class="scope"><b>Provider order</b><span>Gemini → Groq → Local engine</span><span>No paid fallback.</span></div></section>{err}<section class="panel"><form id="analyzeForm" method="post" action="/analyze"><label>Process name<input name="process_name" maxlength="120" required value="{esc(name)}" placeholder="e.g. Customer onboarding"></label><label>Process description<textarea id="description" name="description" minlength="30" maxlength="12000" required placeholder="Describe the process as it works today...">{esc(desc)}</textarea></label><div class="uploadrow"><label class="filebtn">Load text/DOCX<input id="file" type="file" accept=".txt,.md,.csv,.docx"></label><span id="uploadStatus">Optional</span></div><div class="ai-status"><b>AI providers</b><span>Gemini: {g_status} · Groq: {q_status} · Local engine: always available</span></div>{provider_inputs}<button id="analyzeBtn">Analyze process →</button></form></section>''', "New Analysis", '''const f=document.querySelector('#file'),t=document.querySelector('#description'),s=document.querySelector('#uploadStatus'),form=document.querySelector('#analyzeForm'),btn=document.querySelector('#analyzeBtn');f.addEventListener('change',async()=>{if(!f.files[0])return;s.textContent='Reading…';const b=await f.files[0].arrayBuffer();const r=await fetch('/extract-file',{method:'POST',headers:{'X-Filename':f.files[0].name},body:b});const d=await r.json();if(r.ok){t.value=d.text;s.textContent='Loaded '+f.files[0].name}else{s.textContent=d.error||'Could not read file'}});form.addEventListener('submit',()=>{btn.disabled=true;btn.setAttribute('aria-busy','true');btn.textContent='Working, please wait…';});''')


def asis(a):
    rows = ''.join(
        f'<tr><td>{s.id}</td><td>{esc(s.name)}</td><td>{esc(s.type)}</td><td>{esc(s.actor)}</td><td>{esc(s.system)}</td><td>{esc(", ".join(str(x) for x in s.next_step_ids))}</td><td>{"⚠" if s.is_issue else ""}</td></tr>'
        for s in a.steps
    )
    return shell("AS-IS Workflow", f'''{stagebar(2)}<div class="pagehead"><div><div class="eyebrow">AS-IS WORKFLOW</div><h1>{esc(a.process_name)}</h1><p>{esc(a.summary)}</p><span class="mode">AS-IS: {esc(provider_label(a.mode))}</span></div><a class="primary" href="/review?id={a.id}">Review & edit →</a></div><section class="panel"><h2>Workflow diagram</h2>{legend()}{workflow_svg(a.steps)}</section><section class="panel"><h2>Structured steps</h2><div class="tablewrap"><table><thead><tr><th>#</th><th>Step</th><th>Type</th><th>Actor</th><th>System</th><th>Next</th><th>Issue</th></tr></thead><tbody>{rows}</tbody></table></div></section>''')


def review(a, error=""):
    mids = [s for s in a.steps if s.type not in {"start", "end"}]
    rows = []
    for i, s in enumerate(mids):
        rows.append(f'''<div class="editrow" data-row><b class="num">{i+1}</b><div class="fields"><input type="hidden" name="orig_id" value="{s.id}"><label>Step<input name="name" value="{esc(s.name)}" required maxlength="140"></label><div class="fieldgrid"><label>Type<select name="type"><option value="activity" {'selected' if s.type=='activity' else ''}>Activity</option><option value="decision" {'selected' if s.type=='decision' else ''}>Decision</option></select></label><label>Actor<input name="actor" value="{esc(s.actor)}"></label><label>System<input name="system" value="{esc(s.system)}"></label></div><label class="check"><input type="checkbox" name="issue" {'checked' if s.is_issue else ''}> Bottleneck / issue</label><label>Issue notes<textarea name="issue_notes">{esc(s.issue_notes)}</textarea></label></div><div class="rowbuttons"><button type="button" class="secondary up">↑</button><button type="button" class="secondary down">↓</button><button type="button" class="danger del">Delete</button></div></div>''')
    err = f'<div class="alert error">{esc(error)}</div>' if error else ''
    script = '''(()=>{const list=document.querySelector('#steps');const ren=()=>[...list.children].forEach((r,i)=>r.querySelector('.num').textContent=i+1);const bind=r=>{r.querySelector('.up').onclick=()=>{const p=r.previousElementSibling;if(p){list.insertBefore(r,p);ren()}};r.querySelector('.down').onclick=()=>{const n=r.nextElementSibling;if(n){list.insertBefore(n,r);ren()}};r.querySelector('.del').onclick=()=>{if(list.children.length>1){r.remove();ren()}}};[...list.children].forEach(bind);document.querySelector('#add').onclick=()=>{const r=document.createElement('div');r.className='editrow';r.dataset.row='';r.innerHTML=`<b class="num"></b><div class="fields"><input type="hidden" name="orig_id" value="0"><label>Step<input name="name" required maxlength="140" placeholder="New step"></label><div class="fieldgrid"><label>Type<select name="type"><option value="activity">Activity</option><option value="decision">Decision</option></select></label><label>Actor<input name="actor" value="Not specified"></label><label>System<input name="system" value="Not specified"></label></div><label class="check"><input type="checkbox" name="issue"> Bottleneck / issue</label><label>Issue notes<textarea name="issue_notes"></textarea></label></div><div class="rowbuttons"><button type="button" class="secondary up">↑</button><button type="button" class="secondary down">↓</button><button type="button" class="danger del">Delete</button></div>`;list.appendChild(r);bind(r);ren()};document.querySelector('form').addEventListener('submit',()=>{[...list.children].forEach((r,i)=>r.querySelectorAll('input,select,textarea').forEach(el=>el.name=`step_${i}_${el.name}`));document.querySelector('#count').value=list.children.length;const b=document.querySelector('#saveReviewBtn');b.disabled=true;b.setAttribute('aria-busy','true');b.textContent='Working, please wait…'})})();'''
    return shell("Review & Edit", f'''{stagebar(3)}<div class="pagehead"><div><div class="eyebrow">PROCESS REVIEW</div><h1>Correct the AS-IS process</h1><p>Reorder/add/delete steps. Existing AI branch connections are preserved where still valid.</p></div></div>{err}<form method="post" action="/review/save"><input type="hidden" name="id" value="{a.id}"><input id="count" type="hidden" name="count" value="{len(mids)}"><div class="toolbar"><button type="button" class="secondary" id="add">+ Add step</button><button id="saveReviewBtn">Save & analyze improvements →</button></div><div id="steps">{''.join(rows)}</div></form>''', script=script)


def improvements(a):
    cards = []
    for i, f in enumerate(a.findings):
        checked = 'checked' if f.accepted else ''
        cards.append(f'''<article class="finding {esc(f.severity.lower())}"><div><span class="pill">{esc(f.category)}</span><span class="severity">{esc(f.severity)}</span></div><h3>{esc(f.title)}</h3><p>{esc(f.description)}</p><b>Recommendation</b><p>{esc(f.recommendation)}</p><label class="recommend-choice"><input type="checkbox" name="finding_{i}" {checked}> Use this recommendation in TO-BE</label></article>''')
    return shell("Improvement Analysis", f'''{stagebar(4)}<div class="pagehead"><div><div class="eyebrow">IMPROVEMENT ANALYSIS</div><h1>{esc(a.process_name)}</h1><p>Select the recommendations you agree with. Excluded suggestions will not influence the TO-BE workflow.</p><span class="mode">Findings: {esc(provider_label(a.findings_mode))}</span></div></div><form id="tobeForm" method="post" action="/tobe/generate"><input type="hidden" name="id" value="{a.id}"><div class="findings">{"".join(cards)}</div><div class="sticky-action"><button id="tobeBtn">Generate TO-BE from selected recommendations →</button></div></form>''', script="const f=document.querySelector('#tobeForm'),b=document.querySelector('#tobeBtn');f.addEventListener('submit',()=>{b.disabled=true;b.setAttribute('aria-busy','true');b.textContent='Working, please wait…';});")


def tobe(a):
    asissues = sum(1 for s in a.steps if s.is_issue)
    automated = sum(1 for s in a.to_be_steps if s.automation == "automated")
    return shell("TO-BE Workflow", f'''{stagebar(5)}<div class="pagehead"><div><div class="eyebrow">TO-BE WORKFLOW</div><h1>{esc(a.process_name)}</h1><p>Proposed future-state graph based on the reviewed AS-IS workflow and accepted recommendations.</p><span class="mode">TO-BE: {esc(provider_label(a.to_be_mode))}</span></div><div class="exports"><a class="secondary link" href="/export/pdf?id={a.id}">PDF</a><a class="secondary link" href="/export/json?id={a.id}">JSON</a><a class="secondary link" href="/export/csv?id={a.id}">CSV</a></div></div><div class="metrics"><div><b>{asissues}</b><span>AS-IS flagged issues</span></div><div><b>{sum(1 for f in a.findings if f.accepted)}</b><span>Accepted improvements</span></div><div><b>{automated}</b><span>Automated TO-BE steps</span></div></div><div class="compare"><section class="panel"><h2>AS-IS</h2>{workflow_svg(a.steps)}</section><section class="panel"><h2>TO-BE</h2>{workflow_svg(a.to_be_steps)}</section></div><div class="done"><b>ProcessLens {VERSION} complete:</b> Input → AI/local graph → Review → Improvements → TO-BE graph → Export → Saved.</div>''')


def saved(items=None):
    items = STORE.all() if items is None else items
    items = sorted(items, key=lambda a: a.id, reverse=True)
    cards = ''.join(
        f'<a class="savedcard" href="/asis?id={a.id}"><b>{esc(a.process_name)}</b><span>{esc(provider_label(a.mode))} · {len(a.steps)} nodes</span></a>'
        for a in items
    ) or '<p class="muted">No saved analyses yet.</p>'
    return shell("Saved Analyses", f'<div class="eyebrow">SAVED ANALYSES</div><h1>Saved analyses</h1><div class="savedlist">{cards}</div>', "Saved Analyses")


def rebuild(form, a):
    count = int(form.get("count", ["0"])[0])
    old_by_id = {s.id: s for s in a.steps}
    old_end = next((s.id for s in a.steps if s.type == "end"), None)
    raw_rows = []
    for i in range(count):
        name = form.get(f"step_{i}_name", [""])[0].strip()
        if not name:
            continue
        try:
            orig_id = int(form.get(f"step_{i}_orig_id", ["0"])[0])
        except ValueError:
            orig_id = 0
        typ = form.get(f"step_{i}_type", ["activity"])[0]
        typ = typ if typ in {"activity", "decision"} else "activity"
        actor = form.get(f"step_{i}_actor", ["Not specified"])[0].strip() or "Not specified"
        system = form.get(f"step_{i}_system", ["Not specified"])[0].strip() or "Not specified"
        issue = f"step_{i}_issue" in form
        notes = form.get(f"step_{i}_issue_notes", [""])[0].strip()
        raw_rows.append((orig_id, name, typ, actor, system, issue, notes))
    if not raw_rows:
        raise ValueError("Keep at least one process step.")
    new_end = len(raw_rows) + 2
    old_to_new = {orig_id: idx + 2 for idx, (orig_id, *_rest) in enumerate(raw_rows) if orig_id > 0}
    if old_end:
        old_to_new[old_end] = new_end
    middle: list[Step] = []
    for idx, (orig_id, name, typ, actor, system, issue, notes) in enumerate(raw_rows):
        new_id = idx + 2
        old = old_by_id.get(orig_id)
        automation = old.automation if old else "manual"
        next_ids, labels = [], {}
        if old:
            for target in old.next_step_ids:
                mapped = old_to_new.get(target)
                if mapped and mapped > new_id and mapped not in next_ids:
                    next_ids.append(mapped)
                    label = old.next_step_labels.get(target, "")
                    if label:
                        labels[mapped] = label
        if not next_ids:
            next_ids = [new_id + 1 if idx + 1 < len(raw_rows) else new_end]
        middle.append(Step(new_id, name[:140], typ, actor[:80], system[:80], automation, next_ids, issue, notes[:400], labels))
    a.steps = [Step(1, "Process starts", "start", "Process owner", "—", "manual", [2]), *middle,
               Step(new_end, "Process ends", "end", "Process owner", "—", "manual", [])]
    a.findings = []
    a.to_be_steps = []
    a.findings_mode = "Not run"
    a.to_be_mode = "Not run"


def extract_file(name: str, data: bytes) -> str:
    ext = Path(name).suffix.lower()
    if ext in {".txt", ".md", ".csv"}:
        return data.decode("utf-8", errors="replace")[:12000]
    if ext == ".docx":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
        root = ET.fromstring(xml)
        texts = []
        for el in root.iter():
            if el.tag.endswith('}t') and el.text:
                texts.append(el.text)
            elif el.tag.endswith('}p'):
                texts.append('\n')
        return ' '.join(''.join(texts).split())[:12000]
    raise ValueError("Supported files: TXT, MD, CSV, DOCX.")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("ProcessLens:", fmt % args)

    def send_html(self, s, status=200):
        b = s.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def send_bytes(self, b, ctype, name):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def form(self):
        n = int(self.headers.get("Content-Length", "0"))
        return parse_qs(self.rfile.read(n).decode("utf-8", errors="replace"))

    def analysis(self, q):
        return STORE.get(parse_qs(q).get("id", [""])[0])

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/":
            return self.send_html(landing())
        if p.path == "/new":
            return self.send_html(home())
        if p.path == "/saved":
            return self.send_html(saved())
        a = self.analysis(p.query)
        if p.path in {"/asis", "/review", "/improvements", "/tobe"} and not a:
            return self.send_html(home("Analysis not found. Start a new one."), 404)
        if p.path == "/asis":
            return self.send_html(asis(a))
        if p.path == "/review":
            return self.send_html(review(a))
        if p.path == "/improvements":
            if not a.findings:
                a.findings, a.findings_mode = generate_findings(a, SESSION_GEMINI_KEY, SESSION_GROQ_KEY)
                STORE.put(a)
            return self.send_html(improvements(a))
        if p.path == "/tobe":
            if not a.findings:
                a.findings, a.findings_mode = generate_findings(a, SESSION_GEMINI_KEY, SESSION_GROQ_KEY)
            if not a.to_be_steps:
                a.to_be_steps, a.to_be_mode = generate_to_be(a, SESSION_GEMINI_KEY, SESSION_GROQ_KEY)
                STORE.put(a)
            return self.send_html(tobe(a))
        if p.path.startswith("/export/") and a:
            safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in a.process_name)[:50] or 'process'
            if p.path == "/export/json":
                return self.send_bytes(export_json(a), "application/json", safe + ".json")
            if p.path == "/export/csv":
                return self.send_bytes(export_csv(a), "text/csv; charset=utf-8", safe + ".csv")
            if p.path == "/export/pdf":
                return self.send_bytes(export_pdf(a), "application/pdf", safe + ".pdf")
        self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path)
        if p.path == "/extract-file":
            n = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(n)
            name = self.headers.get("X-Filename", "file")
            try:
                payload = json.dumps({"text": extract_file(name, data)}).encode()
                status = 200
            except Exception as e:
                payload = json.dumps({"error": str(e)}).encode()
                status = 400
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        form = self.form()
        if p.path == "/analyze":
            global SESSION_GEMINI_KEY, SESSION_GROQ_KEY
            name = form.get("process_name", [""])[0]
            desc = form.get("description", [""])[0]
            entered_g = form.get("gemini_key", [""])[0].strip()
            entered_q = form.get("groq_key", [""])[0].strip()
            if entered_g:
                SESSION_GEMINI_KEY = entered_g
            if entered_q:
                SESSION_GROQ_KEY = entered_q
            valid, validation_error = validate_process_input(name, desc)
            if not valid:
                return self.send_html(home(validation_error, name, desc), 422)
            try:
                a = analyze(uuid.uuid4().hex[:12], name, desc, SESSION_GEMINI_KEY, SESSION_GROQ_KEY)
                STORE.put(a)
                return self.send_html(asis(a))
            except Exception as e:
                return self.send_html(home(str(e), name, desc), 400)
        if p.path == "/review/save":
            a = STORE.get(form.get("id", [""])[0])
            if not a:
                return self.send_html(home("Analysis not found."), 404)
            try:
                rebuild(form, a)
                a.findings, a.findings_mode = generate_findings(a, SESSION_GEMINI_KEY, SESSION_GROQ_KEY)
                STORE.put(a)
                return self.send_html(improvements(a))
            except Exception as e:
                return self.send_html(review(a, str(e)), 400)
        if p.path == "/tobe/generate":
            a = STORE.get(form.get("id", [""])[0])
            if not a:
                return self.send_html(home("Analysis not found."), 404)
            if not a.findings:
                a.findings, a.findings_mode = generate_findings(a, SESSION_GEMINI_KEY, SESSION_GROQ_KEY)
            for i, f in enumerate(a.findings):
                f.accepted = f"finding_{i}" in form
            a.to_be_steps, a.to_be_mode = generate_to_be(a, SESSION_GEMINI_KEY, SESSION_GROQ_KEY)
            STORE.put(a)
            return self.send_html(tobe(a))
        self.send_error(404)


def choose_port(start=START_PORT):
    if PUBLIC_MODE:
        return start
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                pass
    raise RuntimeError("No free local port found.")


def run():
    port = choose_port()
    display_host = "127.0.0.1" if HOST == "0.0.0.0" else HOST
    url = f"http://{display_host}:{port}"
    server = ThreadingHTTPServer((HOST, port), Handler)
    print(f"\nProcessLens {VERSION} is running")
    print("AI order: Gemini -> Groq -> Local engine")
    print(f"Listening on {HOST}:{port}")
    if not PUBLIC_MODE:
        print(url)
        print("Close this window or press Ctrl+C to stop.\n")
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    else:
        print("Public/server mode: browser auto-open disabled.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
