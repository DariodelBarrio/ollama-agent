import gc
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


src_agent = load_module("src_agent", "src/agent.py")
mega_agent = load_module("mega_agent", "IA/MEGA/agent.py")


class SrcAgentSafetyTests(unittest.TestCase):
    def setUp(self):
        src_agent.ROOT_DIR = str(ROOT)
        src_agent.WORK_DIR = str(ROOT)

    def test_resolve_rejects_paths_outside_root(self):
        with self.assertRaises(ValueError):
            src_agent._resolve(str(ROOT.parent / "fuera.txt"))

    def test_run_command_blocks_dangerous_cmd(self):
        result = src_agent.run_command("cmd /c del archivo.txt", shell="cmd", timeout=5)
        self.assertIn("error", result)
        self.assertIn("bloqueado", result["error"].lower())

    def test_run_command_cmd_executes_safe_command(self):
        result = src_agent.run_command("echo codex_test", shell="cmd", timeout=5)
        self.assertEqual(result["returncode"], 0)
        self.assertIn("codex_test", result["stdout"].lower())


class MegaAgentSafetyTests(unittest.TestCase):
    def setUp(self):
        mega_agent.ROOT_DIR = str(ROOT)
        mega_agent.WORK_DIR = str(ROOT)

    def test_resolve_rejects_paths_outside_root(self):
        with self.assertRaises(ValueError):
            mega_agent._resolve(str(ROOT.parent / "fuera.txt"))

    def test_run_command_blocks_dangerous_cmd(self):
        result = mega_agent.run_command("cmd /c del archivo.txt", shell="cmd", timeout=5)
        self.assertIn("error", result)
        self.assertIn("bloqueado", result["error"].lower())

    def test_memory_db_sets_timestamps(self):
        temp_dir = tempfile.mkdtemp()
        db_path = Path(temp_dir) / "memory.db"
        db = mega_agent.MemoryDB(db_path)
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

    def test_validate_tool_args_rejects_missing_required_arg(self):
        agent = mega_agent.Agent.__new__(mega_agent.Agent)
        agent.logger = type("L", (), {"error": lambda *a, **k: None})()
        result = agent._validate_tool_args("read_file", {})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
