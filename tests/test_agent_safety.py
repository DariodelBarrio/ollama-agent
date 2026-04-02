"""
Safety and correctness tests for ollama-agent.

After the BaseAgent refactoring, path-safety and command-blocking are tested
through base_agent directly (they live there now).  Hybrid-specific features
(MemoryDB, _validate_tool_args) are still tested by loading the hybrid module.
"""
import gc
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Ensure repo root and src/ are importable
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import base_agent


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hybrid_agent = load_module("hybrid_agent", "src/hybrid/agent.py")


# ── Path safety ───────────────────────────────────────────────────────────────
class PathSafetyTests(unittest.TestCase):
    def setUp(self):
        base_agent.sync_work_dir(str(ROOT))

    def test_resolve_rejects_paths_outside_root(self):
        with self.assertRaises(ValueError):
            base_agent.resolve_path(str(ROOT.parent / "fuera.txt"))

    def test_resolve_accepts_paths_inside_root(self):
        result = base_agent.resolve_path("requirements.txt")
        self.assertTrue(str(result).startswith(str(ROOT)))


# ── Command safety ────────────────────────────────────────────────────────────
class CommandSafetyTests(unittest.TestCase):
    def setUp(self):
        base_agent.sync_work_dir(str(ROOT))

    def test_run_command_blocks_dangerous_cmd(self):
        result = base_agent.run_command("cmd /c del archivo.txt", shell="cmd", timeout=5)
        self.assertIn("error", result)
        self.assertIn("bloqueado", result["error"].lower())

    def test_run_command_cmd_executes_safe_command(self):
        result = base_agent.run_command("echo codex_test", shell="cmd", timeout=5)
        self.assertEqual(result["returncode"], 0)
        self.assertIn("codex_test", result["stdout"].lower())


# ── edit_file fuzzy matching ──────────────────────────────────────────────────
class EditFileFuzzyTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        base_agent.sync_work_dir(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_exact_match_succeeds(self):
        path = Path(self._tmp.name) / "test.py"
        path.write_text("x = 1\ny = 2\n")
        result = base_agent.edit_file(str(path), "x = 1", "x = 99")
        self.assertIn("success", result)
        self.assertEqual(path.read_text(), "x = 99\ny = 2\n")

    def test_trailing_whitespace_normalized_match(self):
        # The file has no trailing spaces, but the LLM supplies old_text with them.
        # Exact match fails; normalized match should succeed.
        path = Path(self._tmp.name) / "test.py"
        path.write_text("x = 1\ny = 2\n")
        result = base_agent.edit_file(str(path), "x = 1   ", "x = 99")  # old_text has trailing spaces
        self.assertIn("success", result)
        self.assertIn("warning", result)          # fuzzy match applied

    def test_not_found_returns_helpful_error(self):
        path = Path(self._tmp.name) / "test.py"
        path.write_text("x = 1\ny = 2\n")
        result = base_agent.edit_file(str(path), "totally_different_text", "x = 99")
        self.assertIn("error", result)
        self.assertIn("read_file", result["error"])  # hint mentions read_file


# ── Output sanitization ───────────────────────────────────────────────────────
class OutputSanitizationTests(unittest.TestCase):
    def test_ansi_codes_stripped(self):
        from common_tools import _sanitize_output
        dirty = "\x1b[31mred text\x1b[0m normal"
        clean = _sanitize_output(dirty)
        self.assertNotIn("\x1b", clean)
        self.assertIn("red text", clean)

    def test_truncation_with_head_and_tail(self):
        from common_tools import _sanitize_output
        big = "A" * 30_000
        result = _sanitize_output(big, max_chars=1000)
        self.assertIn("omitidos", result)
        self.assertLessEqual(len(result), 2000)   # room for truncation message


# ── Hybrid: MemoryDB ──────────────────────────────────────────────────────────
class HybridMemoryTests(unittest.TestCase):
    def test_memory_db_sets_timestamps(self):
        temp_dir = tempfile.mkdtemp()
        db_path = Path(temp_dir) / "memory.db"
        db = hybrid_agent.MemoryDB(db_path)
        saved = db.save("k", "v", category="fact")
        self.assertTrue(saved.get("success"))
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT created_at, updated_at FROM memories WHERE key=? AND category=?",
                ("k", "fact"),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertGreater(row[0], 0)
        self.assertGreater(row[1], 0)
        del db
        gc.collect()


# ── Hybrid: _validate_tool_args ───────────────────────────────────────────────
class HybridValidationTests(unittest.TestCase):
    def setUp(self):
        base_agent.sync_work_dir(str(ROOT))

    def test_validate_tool_args_rejects_missing_required_arg(self):
        agent = hybrid_agent.Agent.__new__(hybrid_agent.Agent)
        agent.logger = type("L", (), {"error": lambda *a, **k: None, "warning": lambda *a, **k: None})()
        result = agent._validate_tool_args("read_file", {})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
