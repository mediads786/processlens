from __future__ import annotations
import json
import re
import urllib.error
import urllib.request
from models import Finding, ProcessAnalysis, Step

# ProcessLens 1.0.3 multi-provider analyzer.
# Priority: Gemini -> Groq -> local engine. Online keys are session-only and never saved.

GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TRANSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "target_id": {"type": "integer"},
        "label": {"type": "string"},
    },
    "required": ["target_id", "label"],
    "additionalProperties": False,
}

GRAPH_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "node_id": {"type": "integer"},
        "name": {"type": "string"},
        "type": {"type": "string", "enum": ["activity", "decision"]},
        "actor": {"type": "string"},
        "system": {"type": "string"},
        "automation": {"type": "string", "enum": ["manual", "automated"]},
        "is_issue": {"type": "boolean"},
        "issue_notes": {"type": "string"},
        "transitions": {"type": "array", "items": TRANSITION_SCHEMA, "maxItems": 4},
    },
    "required": ["node_id", "name", "type", "actor", "system", "automation", "is_issue", "issue_notes", "transitions"],
    "additionalProperties": False,
}

ASIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "steps": {"type": "array", "items": GRAPH_STEP_SCHEMA, "maxItems": 18},
    },
    "required": ["summary", "steps"],
    "additionalProperties": False,
}

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "category": {"type": "string"},
                    "severity": {"type": "string", "enum": ["Low", "Medium", "High"]},
                    "description": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "step_id": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                },
                "required": ["title", "category", "severity", "description", "recommendation", "step_id"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

TOBE_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "node_id": {"type": "integer"},
        "name": {"type": "string"},
        "type": {"type": "string", "enum": ["activity", "decision"]},
        "actor": {"type": "string"},
        "system": {"type": "string"},
        "automation": {"type": "string", "enum": ["manual", "automated"]},
        "transitions": {"type": "array", "items": TRANSITION_SCHEMA, "maxItems": 4},
    },
    "required": ["node_id", "name", "type", "actor", "system", "automation", "transitions"],
    "additionalProperties": False,
}

TOBE_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {"type": "array", "maxItems": 18, "items": TOBE_STEP_SCHEMA}
    },
    "required": ["steps"],
    "additionalProperties": False,
}

SYSTEM_WORDS = {
    "excel": "Excel", "spreadsheet": "Spreadsheet", "google sheets": "Google Sheets",
    "email": "Email", "outlook": "Outlook", "gmail": "Gmail", "whatsapp": "WhatsApp",
    "crm": "CRM", "erp": "ERP", "sap": "SAP", "portal": "Portal", "website": "Website",
    "form": "Form", "database": "Database", "sql": "Database", "slack": "Slack",
    "teams": "Microsoft Teams", "api": "API", "n8n": "n8n", "system": "System",
}

ROLE_WORDS = [
    "customer", "client", "employee", "manager", "supervisor", "team lead", "team leader",
    "finance", "accounts", "accountant", "operations", "operator", "sales", "salesperson",
    "agent", "support", "procurement", "buyer", "vendor", "supplier", "warehouse",
    "technician", "engineer", "hr", "human resources", "director", "ceo", "admin",
    "administrator", "receptionist", "approver", "requester", "user", "staff",
]

DECISION_MARKERS = (
    " if ", " whether ", " unless ", " depending on ", " based on ", " check if ",
    " verify if ", " approve or reject", " accept or reject", " eligible", " exceeds ",
    " greater than ", " less than ", " over ", " under ",
)

AUTOMATION_MARKERS = (
    "automatically", "automatic", "auto-", "system sends", "system creates", "api",
    "workflow triggers", "bot ", "script ", "integration ", "scheduled",
)

ISSUE_RULES = [
    ("waiting", "High", ("wait", "waiting", "pending", "delay", "overdue", "follow up", "follow-up"),
     "Waiting or delay is explicitly present in this step.",
     "Define an SLA, owner and escalation rule so overdue work is surfaced automatically."),
    ("approval", "Medium", ("approval", "approve", "authorized", "authorised"),
     "Approval can become a queue or bottleneck when ownership or timing is unclear.",
     "Keep the control, but define approval thresholds, owner and SLA; auto-route requests when possible."),
    ("manual work", "High", ("manual", "manually", "copy", "paste", "re-enter", "reenter", "type again", "data entry"),
     "The step contains avoidable manual handling or re-entry.",
     "Capture the data once in a structured form and reuse it downstream."),
    ("spreadsheet dependency", "Medium", ("excel", "spreadsheet", "google sheets"),
     "A spreadsheet is being used as an operational system of record or handoff point.",
     "Use controlled structured data with validation and ownership; keep spreadsheet export only where useful."),
    ("untracked communication", "Medium", ("email", "whatsapp", "message", "call", "phone"),
     "Important process state is moving through ad-hoc communication.",
     "Use a tracked workflow event or structured notification so status and ownership remain visible."),
    ("handoff", "Medium", ("send to", "forward to", "hand over", "handover", "pass to", "assign to"),
     "The step contains a handoff between people or teams.",
     "Standardize the handoff with required fields, owner, status and acknowledgement."),
    ("duplicate work", "High", ("duplicate", "again", "repeat", "same data"),
     "The wording indicates repeated or duplicated work.",
     "Remove the duplicate step or reuse the existing captured data."),
]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" \t\r\n-•")


def _split_process(description: str) -> list[str]:
    text = description.replace("→", "\n").replace("->", "\n")
    raw = re.split(r"(?:\r?\n)+|(?<=[.!?])\s+", text)
    parts: list[str] = []
    for piece in raw:
        piece = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", piece)
        piece = _clean(piece)
        if not piece:
            continue
        subs = re.split(r"\s*(?:;|\band then\b|\bthen\b|\bnext\b|\bafter that\b)\s*", piece, flags=re.I)
        parts.extend(_clean(x).rstrip(".!?") for x in subs if len(_clean(x)) >= 4)
    return parts[:18]


def _detect_system(text: str) -> str:
    low = text.lower()
    hits = [label for key, label in SYSTEM_WORDS.items() if key in low]
    if not hits:
        return "Not specified"
    out = []
    for h in hits:
        if h not in out:
            out.append(h)
    return " + ".join(out[:2])


def _detect_actor(text: str) -> str:
    low = text.lower()
    for role in sorted(ROLE_WORDS, key=len, reverse=True):
        if re.match(rf"^(?:the\s+)?{re.escape(role)}\b", low):
            return role.title()
    for role in sorted(ROLE_WORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(role)}\b", low):
            return role.title()
    return "Not specified"


def _step_type(text: str) -> str:
    low = f" {_clean(text).lower()} "
    return "decision" if any(m in low for m in DECISION_MARKERS) else "activity"


def _automation(text: str) -> str:
    low = text.lower()
    return "automated" if any(m in low for m in AUTOMATION_MARKERS) else "manual"


def _step_issue(text: str) -> tuple[bool, str]:
    low = text.lower()
    matches = []
    for category, _, words, description, _ in ISSUE_RULES:
        if any(w in low for w in words):
            matches.append((category, description))
    if not matches:
        return False, ""
    cats = ", ".join(x[0] for x in matches[:2])
    return True, f"Potential {cats}: {matches[0][1]}"


def _with_boundaries(middle: list[Step]) -> list[Step]:
    if not middle:
        middle = [Step(0, "Review the submitted process")]
    steps = [Step(1, "Process starts", "start", "Process owner", "—", "manual", [2])]
    for s in middle:
        s.id = len(steps) + 1
        s.next_step_ids = [s.id + 1]
        s.next_step_labels = {}
        steps.append(s)
    end_id = len(steps) + 1
    steps[-1].next_step_ids = [end_id]
    steps.append(Step(end_id, "Process ends", "end", "Process owner", "—", "manual", []))
    return steps


def _local_steps(description: str) -> list[Step]:
    middle: list[Step] = []
    for text in _split_process(description):
        issue, note = _step_issue(text)
        middle.append(Step(
            0, text[:140], _step_type(text), _detect_actor(text), _detect_system(text),
            _automation(text), [], issue, note[:400]
        ))
    return _with_boundaries(middle)


def _extract_gemini_text(response: dict) -> str:
    try:
        for part in (response.get("candidates") or [])[0]["content"]["parts"]:
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    except (IndexError, KeyError, TypeError):
        pass
    raise ValueError("Gemini returned no usable output.")


def _call_gemini_json(system_prompt: str, user_prompt: str, schema: dict, api_key: str) -> dict:
    prompt = (
        user_prompt
        + "\n\nReturn ONLY one JSON object matching this JSON schema exactly:\n"
        + json.dumps(schema, ensure_ascii=False)
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }
    req = urllib.request.Request(
        GEMINI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise ValueError(f"Gemini HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise ValueError(f"Gemini unavailable: {exc}") from exc
    return json.loads(_extract_gemini_text(body))


def _call_groq_json(system_prompt: str, user_prompt: str, schema: dict, api_key: str) -> dict:
    prompt = (
        user_prompt
        + "\n\nReturn ONLY one JSON object matching this JSON schema exactly:\n"
        + json.dumps(schema, ensure_ascii=False)
    )
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise ValueError(f"Groq HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise ValueError(f"Groq unavailable: {exc}") from exc
    try:
        text = body["choices"][0]["message"]["content"]
        return json.loads(text)
    except Exception as exc:
        raise ValueError("Groq returned invalid JSON.") from exc


def _call_online_json(system_prompt: str, user_prompt: str, schema: dict,
                      gemini_key: str = "", groq_key: str = "") -> tuple[dict, str]:
    errors: list[str] = []
    if (gemini_key or "").strip():
        try:
            return _call_gemini_json(system_prompt, user_prompt, schema, gemini_key.strip()), f"Gemini ({GEMINI_MODEL})"
        except Exception as exc:
            errors.append(str(exc))
    if (groq_key or "").strip():
        try:
            return _call_groq_json(system_prompt, user_prompt, schema, groq_key.strip()), f"Groq ({GROQ_MODEL})"
        except Exception as exc:
            errors.append(str(exc))
    raise ValueError("; ".join(errors) or "No online AI key is active.")


def _graph_from_ai(raw_steps: list[dict], include_issues: bool = True) -> list[Step]:
    valid_raw: list[dict] = []
    seen: set[int] = set()
    for raw in raw_steps[:18]:
        try:
            local_id = int(raw.get("node_id"))
        except Exception:
            continue
        name = str(raw.get("name", "")).strip()
        if local_id < 1 or local_id > 99 or local_id in seen or not name:
            continue
        seen.add(local_id)
        valid_raw.append(raw)
    if not valid_raw:
        raise ValueError("AI returned no usable workflow nodes.")

    local_to_actual = {int(raw["node_id"]): idx + 2 for idx, raw in enumerate(valid_raw)}
    middle: list[Step] = []
    for idx, raw in enumerate(valid_raw):
        actual_id = idx + 2
        typ = str(raw.get("type", "activity"))
        if typ not in {"activity", "decision"}:
            typ = "activity"
        automation = str(raw.get("automation", "manual"))
        if automation not in {"manual", "automated"}:
            automation = "manual"
        step = Step(
            actual_id,
            str(raw.get("name", ""))[:140],
            typ,
            str(raw.get("actor") or "Not specified")[:80],
            str(raw.get("system") or "Not specified")[:80],
            automation,
            [],
            bool(raw.get("is_issue", False)) if include_issues else False,
            str(raw.get("issue_notes") or "")[:400] if include_issues else "",
            {},
        )
        transitions = raw.get("transitions") or []
        for tr in transitions[:4]:
            try:
                target_local = int(tr.get("target_id"))
            except Exception:
                continue
            target_actual = local_to_actual.get(target_local)
            if target_actual is None or target_actual <= actual_id:
                continue
            if target_actual not in step.next_step_ids:
                step.next_step_ids.append(target_actual)
                label = str(tr.get("label") or "").strip()[:40]
                if label:
                    step.next_step_labels[target_actual] = label
        middle.append(step)

    end_id = len(middle) + 2
    for i, step in enumerate(middle):
        if not step.next_step_ids:
            step.next_step_ids = [middle[i + 1].id if i + 1 < len(middle) else end_id]
    start = Step(1, "Process starts", "start", "Process owner", "—", "manual", [middle[0].id])
    end = Step(end_id, "Process ends", "end", "Process owner", "—", "manual", [])
    return [start, *middle, end]


def analyze(process_id: str, process_name: str, description: str,
            gemini_key: str = "", groq_key: str = "") -> ProcessAnalysis:
    process_name = (process_name or "").strip()
    description = (description or "").strip()
    if len(process_name) < 2:
        raise ValueError("Process name must contain at least 2 characters.")
    if len(description) < 30:
        raise ValueError("Describe the process in at least 30 characters.")
    if len(description) > 12000:
        raise ValueError("Process description is too long (12,000 characters max).")

    online_attempted = bool((gemini_key or "").strip() or (groq_key or "").strip())
    online_error = ""
    if online_attempted:
        try:
            data, provider = _call_online_json(
                "You are a business-process analyst. Extract only the AS-IS process actually described. Return an editable directed workflow graph. Use compact node IDs 1..N. Decisions should have explicit forward transitions such as Yes/No when the source text supports them. Keep the graph acyclic: do not point to an earlier node. Identify actors and systems only when supported. Flag obvious operational friction. Do not invent quantified facts.",
                f"Process name: {process_name}\n\nAS-IS description:\n{description}",
                ASIS_SCHEMA,
                gemini_key,
                groq_key,
            )
            steps = _graph_from_ai(data.get("steps", []), include_issues=True)
            summary = str(data.get("summary") or f"AS-IS workflow generated by {provider}.")[:500]
            return ProcessAnalysis(process_id, process_name, description, summary, provider, steps)
        except Exception as exc:
            online_error = str(exc)

    steps = _local_steps(description)
    middle = [st for st in steps if st.type not in {"start", "end"}]
    decisions = sum(st.type == "decision" for st in middle)
    issues = sum(st.is_issue for st in middle)
    actors = len({st.actor for st in middle if st.actor != "Not specified"})
    systems = len({st.system for st in middle if st.system != "Not specified"})
    summary = (
        f"Local analysis detected {len(middle)} operational steps, {decisions} decision(s), "
        f"{issues} potential issue(s), {actors} named actor(s) and {systems} system reference(s)."
    )
    mode = (f"Local fallback — {online_error[:220]}" if online_attempted and online_error else "Local fallback") if online_attempted else "Local engine"
    return ProcessAnalysis(process_id, process_name, description, summary, mode, steps)


def _find_rule_matches(step: Step) -> list[Finding]:
    low = f"{step.name} {step.issue_notes}".lower()
    findings: list[Finding] = []
    for category, severity, words, description, recommendation in ISSUE_RULES:
        if any(w in low for w in words):
            findings.append(Finding(
                f"{category.title()} at step {step.id}", category, severity,
                description, recommendation, step.id,
            ))
    if step.actor == "Not specified" and step.type not in {"start", "end"}:
        findings.append(Finding(
            f"Ownership unclear at step {step.id}", "ownership", "Low",
            "No responsible actor was detected for this step.",
            "Assign a clear accountable role to this step before automating it.", step.id,
        ))
    return findings


def _local_generate_findings(analysis: ProcessAnalysis) -> tuple[list[Finding], str]:
    findings: list[Finding] = []
    seen: set[tuple[str, int | None]] = set()
    for step in analysis.steps:
        if step.type in {"start", "end"}:
            continue
        for finding in _find_rule_matches(step):
            key = (finding.category, finding.step_id)
            if key not in seen:
                findings.append(finding)
                seen.add(key)
    if not findings:
        findings.append(Finding(
            "No obvious control issue detected", "review", "Low",
            "The supplied wording does not expose a clear bottleneck or control weakness.",
            "Add timings, volumes, rework, exception rates and ownership details for a deeper review.", None,
        ))
    return findings[:12], "Local engine"


def generate_findings(analysis: ProcessAnalysis, gemini_key: str = "", groq_key: str = "") -> tuple[list[Finding], str]:
    online_attempted = bool((gemini_key or "").strip() or (groq_key or "").strip())
    online_error = ""
    if online_attempted:
        try:
            reviewed = [
                {
                    "id": st.id, "name": st.name, "type": st.type, "actor": st.actor,
                    "system": st.system, "automation": st.automation,
                    "next_step_ids": st.next_step_ids, "next_step_labels": st.next_step_labels,
                    "is_issue": st.is_issue, "issue_notes": st.issue_notes,
                }
                for st in analysis.steps if st.type not in {"start", "end"}
            ]
            data, provider = _call_online_json(
                "You are a senior operations and process-improvement analyst. Analyze the reviewed AS-IS process. Identify concrete bottlenecks, delays, duplicate work, uncontrolled handoffs, re-entry, avoidable manual work, weak ownership, and sensible automation opportunities. Do not invent quantified savings. Recommendations must be specific and implementable.",
                f"Process: {analysis.process_name}\n\nReviewed AS-IS graph:\n{json.dumps(reviewed, ensure_ascii=False)}",
                FINDINGS_SCHEMA,
                gemini_key,
                groq_key,
            )
            valid_ids = {st.id for st in analysis.steps}
            findings: list[Finding] = []
            for raw in data.get("findings", [])[:12]:
                sid = raw.get("step_id")
                if sid not in valid_ids:
                    sid = None
                severity = str(raw.get("severity", "Medium"))
                if severity not in {"Low", "Medium", "High"}:
                    severity = "Medium"
                findings.append(Finding(
                    str(raw.get("title", "Finding"))[:160],
                    str(raw.get("category", "process issue"))[:80],
                    severity,
                    str(raw.get("description", ""))[:700],
                    str(raw.get("recommendation", ""))[:700],
                    sid,
                ))
            if findings:
                return findings, provider
        except Exception as exc:
            online_error = str(exc)
    findings, _ = _local_generate_findings(analysis)
    mode = (f"Local fallback — {online_error[:220]}" if online_error else "Local fallback") if online_attempted else "Local engine"
    return findings, mode


def _accepted_categories(analysis: ProcessAnalysis, step_id: int) -> set[str]:
    return {f.category for f in analysis.findings if f.accepted and f.step_id == step_id}


def _rewrite_step(step: Step, categories: set[str]) -> Step:
    name = step.name
    actor = step.actor
    system = step.system
    automation = step.automation
    if "manual work" in categories or "duplicate work" in categories:
        name = f"Capture once and reuse: {name}"
        system = "Workflow data"
        automation = "automated"
    elif "spreadsheet dependency" in categories:
        name = f"Use validated structured record: {name}"
        system = "Workflow data"
        automation = "automated"
    elif "untracked communication" in categories:
        name = f"Track workflow event: {name}"
        system = "Workflow"
        automation = "automated"
    elif "handoff" in categories:
        name = f"Structured handoff: {name}"
        system = "Workflow"
    elif "waiting" in categories:
        name = f"SLA-controlled: {name}"
        system = "Workflow" if system == "Not specified" else system
    elif "approval" in categories:
        name = f"Rule-based approval routing: {name}"
        system = "Workflow" if system == "Not specified" else system
    elif "ownership" in categories:
        name = f"Assign owner: {name}"
        actor = "Process owner"
    return Step(
        step.id, name[:140], step.type, actor, system, automation,
        list(step.next_step_ids), False, "", dict(step.next_step_labels)
    )


def _local_generate_to_be(analysis: ProcessAnalysis) -> tuple[list[Step], str]:
    out: list[Step] = []
    for step in analysis.steps:
        if step.type in {"start", "end"}:
            out.append(Step(
                step.id, step.name, step.type, step.actor, step.system, step.automation,
                list(step.next_step_ids), False, "", dict(step.next_step_labels)
            ))
        else:
            out.append(_rewrite_step(step, _accepted_categories(analysis, step.id)))
    return out, "Local engine"


def generate_to_be(analysis: ProcessAnalysis, gemini_key: str = "", groq_key: str = "") -> tuple[list[Step], str]:
    online_attempted = bool((gemini_key or "").strip() or (groq_key or "").strip())
    online_error = ""
    if online_attempted:
        try:
            reviewed = [
                {
                    "id": st.id, "name": st.name, "type": st.type, "actor": st.actor,
                    "system": st.system, "automation": st.automation,
                    "next_step_ids": st.next_step_ids, "next_step_labels": st.next_step_labels,
                }
                for st in analysis.steps if st.type not in {"start", "end"}
            ]
            accepted = [
                {
                    "title": f.title, "severity": f.severity, "description": f.description,
                    "recommendation": f.recommendation, "step_id": f.step_id,
                }
                for f in analysis.findings if f.accepted
            ]
            data, provider = _call_online_json(
                "You are a senior business-process designer. Produce a concise directed TO-BE workflow graph from the reviewed AS-IS graph and ONLY the accepted findings. Use compact node IDs 1..N and explicit forward transitions. Decisions should use branch labels such as Yes/No where meaningful. Keep the graph acyclic. Do not apply rejected findings. Preserve necessary controls and human approvals. Mark automation only when plausible. Do not invent quantified savings.",
                f"Process: {analysis.process_name}\n\nAS-IS:\n{json.dumps(reviewed, ensure_ascii=False)}\n\nAccepted findings:\n{json.dumps(accepted, ensure_ascii=False)}",
                TOBE_SCHEMA,
                gemini_key,
                groq_key,
            )
            steps = _graph_from_ai(data.get("steps", []), include_issues=False)
            return steps, provider
        except Exception as exc:
            online_error = str(exc)
    steps, _ = _local_generate_to_be(analysis)
    mode = (f"Local fallback — {online_error[:220]}" if online_error else "Local fallback") if online_attempted else "Local engine"
    return steps, mode
