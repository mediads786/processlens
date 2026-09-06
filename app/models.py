from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, List

@dataclass
class Step:
    id: int
    name: str
    type: str = "activity"
    actor: str = "Not specified"
    system: str = "Not specified"
    automation: str = "manual"
    next_step_ids: List[int] = field(default_factory=list)
    is_issue: bool = False
    issue_notes: str = ""
    next_step_labels: Dict[int, str] = field(default_factory=dict)

@dataclass
class Finding:
    title: str
    category: str
    severity: str
    description: str
    recommendation: str
    step_id: int | None = None
    accepted: bool = True

@dataclass
class ProcessAnalysis:
    id: str
    process_name: str
    description: str
    summary: str
    mode: str
    steps: List[Step]
    findings: List[Finding] = field(default_factory=list)
    to_be_steps: List[Step] = field(default_factory=list)
    findings_mode: str = "Not run"
    to_be_mode: str = "Not run"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def _step_from_dict(raw: dict) -> Step:
        data = dict(raw)
        labels = data.get("next_step_labels") or {}
        data["next_step_labels"] = {
            int(k): str(v) for k, v in labels.items()
            if str(k).lstrip("-").isdigit()
        }
        return Step(**data)

    @classmethod
    def from_dict(cls, data: dict) -> "ProcessAnalysis":
        return cls(
            id=data["id"],
            process_name=data["process_name"],
            description=data.get("description", ""),
            summary=data.get("summary", ""),
            mode=data.get("mode", "Local engine"),
            steps=[cls._step_from_dict(s) for s in data.get("steps", [])],
            findings=[Finding(**f) for f in data.get("findings", [])],
            to_be_steps=[cls._step_from_dict(s) for s in data.get("to_be_steps", [])],
            findings_mode=data.get("findings_mode", "Local engine" if data.get("findings") else "Not run"),
            to_be_mode=data.get("to_be_mode", "Local engine" if data.get("to_be_steps") else "Not run"),
        )
