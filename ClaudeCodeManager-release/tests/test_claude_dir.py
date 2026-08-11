import os
import tempfile
import unittest

import app


class ClaudeDirectoryDiscoveryTests(unittest.TestCase):
    def test_defaults_to_current_user_home(self):
        with tempfile.TemporaryDirectory() as home:
            path, source = app.resolve_claude_dir(argv=[], environ={}, home=home)
            self.assertEqual(path, os.path.realpath(os.path.join(home, ".claude")))
            self.assertEqual(source, "user_home")

    def test_official_claude_config_dir_is_honored(self):
        with tempfile.TemporaryDirectory() as configured:
            path, source = app.resolve_claude_dir(argv=[], environ={"CLAUDE_CONFIG_DIR": configured})
            self.assertEqual(path, os.path.realpath(configured))
            self.assertEqual(source, "CLAUDE_CONFIG_DIR")

    def test_manager_override_precedes_official_environment(self):
        with tempfile.TemporaryDirectory() as manager_dir, tempfile.TemporaryDirectory() as claude_dir:
            path, source = app.resolve_claude_dir(
                argv=[],
                environ={"CCM_CLAUDE_DIR": manager_dir, "CLAUDE_CONFIG_DIR": claude_dir},
            )
            self.assertEqual(path, os.path.realpath(manager_dir))
            self.assertEqual(source, "CCM_CLAUDE_DIR")

    def test_cli_override_has_highest_priority(self):
        with tempfile.TemporaryDirectory() as cli_dir, tempfile.TemporaryDirectory() as env_dir:
            path, source = app.resolve_claude_dir(
                argv=["--claude-dir", cli_dir],
                environ={"CCM_CLAUDE_DIR": env_dir},
            )
            self.assertEqual(path, os.path.realpath(cli_dir))
            self.assertEqual(source, "cli")

    def test_missing_cli_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires a directory path"):
            app.resolve_claude_dir(argv=["--claude-dir"], environ={})


if __name__ == "__main__":
    unittest.main()
