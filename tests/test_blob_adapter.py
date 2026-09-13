import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import app
from vercel.blob.types import GetBlobResult, ListBlobResult, ListBlobItem
from vercel_store import BlobStore


class BlobAdapterTests(unittest.TestCase):
    def test_saved_list_reads_sdk_content(self):
        now = datetime.now(timezone.utc)
        path = "processlens/browser/analysis.json"
        result = GetBlobResult(
            url="https://example.invalid/analysis.json", download_url="", pathname=path,
            content_type="application/json", size=2, content_disposition="", cache_control="",
            uploaded_at=now, etag="test", content=b'{"id":"analysis"}', status_code=200,
        )
        store = BlobStore.__new__(BlobStore)
        store.namespace = "browser"
        store.client = Mock()
        store.client.get.return_value = result
        store._list_objects = Mock(return_value=ListBlobResult(
            blobs=[ListBlobItem(url=result.url, download_url="", pathname=path, size=17, uploaded_at=now)],
            cursor=None, has_more=False,
        ))
        with patch("vercel_store.ProcessAnalysis.from_dict", return_value="restored") as restore:
            self.assertEqual(store.all(), ["restored"])
            restore.assert_called_once_with({"id": "analysis"})
        store.client.get.assert_called_once_with(path, access="private", use_cache=False)


if __name__ == "__main__":
    unittest.main()
