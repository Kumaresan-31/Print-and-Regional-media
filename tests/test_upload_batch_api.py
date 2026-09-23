import asyncio
import io
import unittest
from pathlib import Path
from fastapi import UploadFile, HTTPException

from harvester.api.app import serve_upload_page, upload_and_parse_newspaper_batch


class TestUploadBatchAPI(unittest.TestCase):

    def test_serve_upload_page(self):
        """Test serve_upload_page returns HTMLResponse containing expected page elements."""
        async def _run():
            res = await serve_upload_page()
            self.assertEqual(res.status_code, 200)
            body = res.body.decode("utf-8")
            self.assertIn("Hardcopy Broadsheet", body)
            self.assertIn("batchDropzone", body)

        asyncio.run(_run())

    def test_upload_batch_validation(self):
        """Test upload_and_parse_newspaper_batch rejects unsupported file extensions."""
        async def _run():
            fake_file = UploadFile(
                filename="test.exe",
                file=io.BytesIO(b"Hello world binary file")
            )
            with self.assertRaises(HTTPException) as cm:
                await upload_and_parse_newspaper_batch(files=[fake_file])
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("No supported document formats found", cm.exception.detail)

        asyncio.run(_run())

    def test_upload_batch_empty(self):
        """Test upload_and_parse_newspaper_batch rejects empty file list."""
        async def _run():
            with self.assertRaises(HTTPException) as cm:
                await upload_and_parse_newspaper_batch(files=[])
            self.assertEqual(cm.exception.status_code, 400)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
