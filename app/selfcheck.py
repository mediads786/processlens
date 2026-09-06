from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def main() -> None:
    if sys.version_info < (3, 10):
        fail(f"Python 3.10+ required; found {sys.version.split()[0]}")
    print(f"[OK] Python {sys.version.split()[0]}")

    try:
        import analyzer, models, report, server, store  # noqa: F401
    except Exception as exc:
        fail(f"ProcessLens modules could not load: {exc}")
    print("[OK] ProcessLens modules load")

    try:
        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            test = Path(td) / "write_test.json"
            test.write_text(json.dumps({"ok": True}), encoding="utf-8")
            if json.loads(test.read_text(encoding="utf-8")) != {"ok": True}:
                fail("Local data write/read check failed")
    except Exception as exc:
        fail(f"Project data folder is not writable: {exc}")
    print("[OK] Local save folder is writable")
    print("[OK] Startup check passed")


if __name__ == "__main__":
    main()
