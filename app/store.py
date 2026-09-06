from __future__ import annotations
import json
from pathlib import Path
from threading import Lock
from models import ProcessAnalysis

class Store:
    def __init__(self, path: Path, legacy_path: Path | None = None):
        self.path = path
        self.legacy_path = legacy_path
        self.lock = Lock()
        self._items: dict[str, ProcessAnalysis] = {}
        self._load()

    def _load(self):
        source = self.path
        if not source.exists() and self.legacy_path and self.legacy_path.exists():
            source = self.legacy_path
        if not source.exists():
            return
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
            self._items = {k: ProcessAnalysis.from_dict(v) for k, v in raw.items()}
            if source != self.path:
                self._save()  # one-time migration out of the app/code folder
        except Exception:
            self._items = {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v.to_dict() for k, v in self._items.items()}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, analysis_id: str):
        return self._items.get(analysis_id)

    def put(self, analysis: ProcessAnalysis):
        with self.lock:
            self._items[analysis.id] = analysis
            self._save()

    def all(self):
        return list(self._items.values())
