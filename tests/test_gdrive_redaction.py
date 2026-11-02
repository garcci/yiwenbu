"""Ensure upload errors never log resumable session material."""
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import requests

import gdrive


class UploadErrorRedactionTests(unittest.TestCase):
    def test_synthetic_http_error_is_redacted_on_each_retry_and_exit(self):
        secret = "synthetic-session-token-not-a-credential"
        message = f"https://example.invalid/upload?upload_id={secret}&session_crd={secret}"
        response = requests.Response()
        response.status_code = 500
        response._content = message.encode()
        error = requests.HTTPError(message, response=response)
        output = io.StringIO()
        with patch.object(gdrive, "_put_once", side_effect=error) as send, \
             patch("time.sleep") as sleep, contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exit_error:
                gdrive._put({}, Path(secret), "parent")

        self.assertEqual(send.call_count, 3)
        self.assertEqual(sleep.call_count, 3)
        self.assertEqual(str(exit_error.exception), "上传云盘失败")
        self.assertEqual(output.getvalue().count("服务端请求失败"), 3)
        for leaked in (secret, "upload_id", "session_crd", "example.invalid"):
            self.assertNotIn(leaked, output.getvalue() + str(exit_error.exception))

    def test_timeout_redacted_and_following_success_returned(self):
        secret = "synthetic-timeout-token"
        output = io.StringIO()
        with patch.object(gdrive, "_put_once", side_effect=[requests.Timeout(secret), "新建"]), \
             patch("time.sleep"), contextlib.redirect_stdout(output):
            result = gdrive._put({}, Path("sample.mp3"), "parent")
        self.assertEqual(result, "新建")
        self.assertIn("请求超时", output.getvalue())
        self.assertNotIn(secret, output.getvalue())


if __name__ == "__main__":
    unittest.main()
