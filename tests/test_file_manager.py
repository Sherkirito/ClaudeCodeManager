import os
import tempfile
import unittest

import app


class FileManagerTests(unittest.TestCase):
    def test_existing_directory_is_opened_with_normalized_path(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            ok, message, opened_path = app.open_directory_in_file_manager(
                os.path.join(directory, "."),
                opener=calls.append,
            )

        self.assertTrue(ok)
        self.assertIn("文件资源管理器", message)
        self.assertEqual(calls, [opened_path])
        self.assertEqual(opened_path, os.path.realpath(directory))

    def test_missing_directory_is_rejected_without_calling_opener(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "missing")
            ok, message, opened_path = app.open_directory_in_file_manager(
                missing,
                opener=calls.append,
            )

        self.assertFalse(ok)
        self.assertIn("目录不存在", message)
        self.assertEqual(calls, [])
        self.assertEqual(opened_path, os.path.realpath(missing))


if __name__ == "__main__":
    unittest.main()
