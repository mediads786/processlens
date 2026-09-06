from __future__ import annotations

import json
from typing import Iterable

from models import ProcessAnalysis


class BlobStore:
    """Per-browser durable ProcessLens storage using a private Vercel Blob store."""

    def __init__(self, namespace: str):
        if not namespace or len(namespace) > 64:
            raise ValueError("Invalid storage namespace.")
        self.namespace = namespace
        try:
            from vercel.blob import BlobClient, list_objects
        except ImportError as exc:  # pragma: no cover - Vercel installs this dependency
            raise RuntimeError("Vercel Blob SDK is not installed.") from exc
        self.client = BlobClient()
        self._list_objects = list_objects

    @property
    def prefix(self) -> str:
        return f"processlens/{self.namespace}/"

    def _path(self, analysis_id: str) -> str:
        safe = "".join(c for c in analysis_id if c.isalnum() or c in "-_")
        if not safe or safe != analysis_id:
            raise ValueError("Invalid analysis id.")
        return f"{self.prefix}{safe}.json"

    @staticmethod
    def _read_stream(stream) -> bytes:
        if stream is None:
            return b""
        if hasattr(stream, "read"):
            return stream.read()
        return b"".join(stream)

    def get(self, analysis_id: str):
        path = self._path(analysis_id)
        try:
            result = self.client.get(path, access="private")
        except Exception as exc:
            # The SDK raises a dedicated not-found exception, but keeping the
            # boundary generic prevents storage-library changes from crashing UI routes.
            if "not found" in str(exc).lower():
                return None
            raise RuntimeError(f"Persistent storage read failed: {exc}") from exc
        if result is None or getattr(result, "status_code", 200) != 200:
            return None
        raw = self._read_stream(getattr(result, "stream", None))
        if not raw:
            return None
        return ProcessAnalysis.from_dict(json.loads(raw.decode("utf-8")))

    def put(self, analysis: ProcessAnalysis):
        payload = json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
        try:
            self.client.put(
                self._path(analysis.id),
                payload,
                access="private",
                content_type="application/json",
                overwrite=True,
            )
        except Exception as exc:
            raise RuntimeError(f"Persistent storage write failed: {exc}") from exc

    def all(self):
        items: list[ProcessAnalysis] = []
        cursor = None
        try:
            while True:
                page = self._list_objects(prefix=self.prefix, limit=100, cursor=cursor)
                for blob in page.blobs:
                    analysis_id = blob.pathname.rsplit("/", 1)[-1].removesuffix(".json")
                    item = self.get(analysis_id)
                    if item:
                        items.append(item)
                if not page.has_more:
                    break
                cursor = page.cursor
        except Exception as exc:
            raise RuntimeError(f"Persistent storage list failed: {exc}") from exc
        return items
