import unittest
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


class BrowserStorageTests(unittest.TestCase):
    def test_dedicated_connection_takes_priority(self):
        env = dict(os.environ, PROCESSLENS_BLOB_READ_WRITE_TOKEN="test-new-token", BLOB_READ_WRITE_TOKEN="test-old-token")
        result = subprocess.run(
            [sys.executable, "-c", "import app, os; assert app.HAS_BLOB; assert os.environ['BLOB_READ_WRITE_TOKEN'] == 'test-new-token'"],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_first_request_storage_identity_matches_cookie(self):
        for cookie in (None, "invalid-cookie"):
            with self.subTest(cookie=cookie):
                namespaces = []
                records = {}

                class MemoryBlob:
                    def __init__(self, namespace):
                        self.namespace = namespace
                        namespaces.append(namespace)

                    def put(self, analysis):
                        records[self.namespace] = analysis

                    def all(self):
                        return [records[self.namespace]] if self.namespace in records else []

                analysis = SimpleNamespace(id="test-analysis")
                with (
                    patch.object(app, "HAS_BLOB", True),
                    patch.object(app, "BlobStore", MemoryBlob),
                    patch.object(app.core, "validate_process_input", return_value=(True, "")),
                    patch.object(app, "analyze", return_value=analysis),
                    patch.object(app.core, "asis", return_value="created"),
                    patch.object(app.core, "saved", side_effect=lambda items: str(len(items))),
                    TestClient(app.app, base_url="https://testserver") as client,
                ):
                    headers = {"Cookie": f"{app.CLIENT_COOKIE}={cookie}"} if cookie else {}
                    response = client.post("/analyze", data={"process_name": "Test", "description": "Test"}, headers=headers)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(client.cookies.get(app.CLIENT_COOKIE), namespaces[0])
                    self.assertEqual(client.get("/saved").text, "1")
                    self.assertEqual(namespaces[0], namespaces[1])
                    with TestClient(app.app, base_url="https://testserver") as other:
                        self.assertEqual(other.get("/saved").text, "0")
                        self.assertNotEqual(namespaces[0], namespaces[-1])


if __name__ == "__main__":
    unittest.main()
