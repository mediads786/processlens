from __future__ import annotations
import csv, io, json, textwrap
from models import ProcessAnalysis


def export_json(a: ProcessAnalysis) -> bytes:
    return json.dumps(a.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")


def export_csv(a: ProcessAnalysis) -> bytes:
    out = io.StringIO(newline="")
    w = csv.writer(out)
    w.writerow(["version", "step_id", "step", "type", "actor", "system", "automation", "next_step_ids", "branch_labels", "issue", "issue_notes"])
    for version, steps in (("AS-IS", a.steps), ("TO-BE", a.to_be_steps)):
        for s in steps:
            w.writerow([version, s.id, s.name, s.type, s.actor, s.system, s.automation, ";".join(map(str, s.next_step_ids)), json.dumps(s.next_step_labels, ensure_ascii=False), s.is_issue, s.issue_notes])
    return out.getvalue().encode("utf-8-sig")


def _report_lines(a: ProcessAnalysis) -> list[str]:
    lines = [
        "ProcessLens 1.0.3 Report",
        "",
        f"Process: {a.process_name}",
        f"AS-IS source: {a.mode}",
        f"Findings source: {a.findings_mode}",
        f"TO-BE source: {a.to_be_mode}",
        "",
        "Summary:",
    ]
    lines += textwrap.wrap(a.summary, 88) or [""]
    lines += ["", "AS-IS Steps:"]
    for s in a.steps:
        marker = " [ISSUE]" if s.is_issue else ""
        lines += textwrap.wrap(f"{s.id}. {s.name} [{s.type}] | {s.actor} | {s.system}{marker}", 88)
        if s.issue_notes:
            lines += textwrap.wrap(f"   Note: {s.issue_notes}", 84)
    lines += ["", "Improvement Findings:"]
    for i, f in enumerate(a.findings, 1):
        status = "ACCEPTED" if f.accepted else "EXCLUDED"
        lines += textwrap.wrap(f"{i}. {f.title} ({f.severity}; {status})", 88)
        lines += textwrap.wrap(f"   {f.description}", 84)
        lines += textwrap.wrap(f"   Recommendation: {f.recommendation}", 84)
    lines += ["", "TO-BE Steps:"]
    for s in a.to_be_steps:
        lines += textwrap.wrap(f"{s.id}. {s.name} [{s.type}; {s.automation}] | {s.actor} | {s.system}", 88)
    return lines


def _pdf_text_stream(lines: list[str], page_no: int, total_pages: int) -> bytes:
    def clean(t: str) -> str:
        return t.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    commands = ["BT /F1 10 Tf 45 805 Td"]
    for line in lines:
        commands.append(f"({clean(line)}) Tj 0 -14 Td")
    commands.append(f"0 -8 Td /F1 8 Tf (Page {page_no} of {total_pages}) Tj ET")
    return "\n".join(commands).encode("latin-1")


def export_pdf(a: ProcessAnalysis) -> bytes:
    lines = _report_lines(a)
    page_size = 49
    pages = [lines[i:i + page_size] for i in range(0, len(lines), page_size)] or [["ProcessLens 1.0.3 Report"]]
    total = len(pages)

    # Object layout: 1 catalog, 2 pages tree, then for each page: page object + content object, final font object.
    page_obj_nums = []
    content_obj_nums = []
    next_obj = 3
    for _ in pages:
        page_obj_nums.append(next_obj)
        content_obj_nums.append(next_obj + 1)
        next_obj += 2
    font_obj = next_obj

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())

    for idx, page_lines in enumerate(pages):
        content = _pdf_text_stream(page_lines, idx + 1, total)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 {font_obj} 0 R >> >> /Contents {content_obj_nums[idx]} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objects)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets[1:]:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(pdf)
