"""Tests for the local benchmark helper script."""
import importlib.util
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


benchmark = load_module("run_benchmark", "scripts/run_benchmark.py")


class BenchmarkScriptTests(unittest.TestCase):
    def setUp(self):
        self._tmp_root = ROOT / ".tmp-tests"
        self._tmp_root.mkdir(exist_ok=True)
        self.run_dir = self._tmp_root / f"benchmark-{uuid.uuid4().hex}"

    def tearDown(self):
        shutil.rmtree(self.run_dir, ignore_errors=True)
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_setup_writes_manifest_and_prompts(self):
        benchmark.cmd_setup(self.run_dir)

        manifest = self.run_dir / "manifest.json"
        prompts = self.run_dir / "prompts.txt"

        self.assertTrue(manifest.exists())
        self.assertTrue(prompts.exists())

        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["benchmark_version"], 1)
        self.assertIn("T1", payload["tasks"])
        self.assertGreater(payload["tasks"]["T1"]["expected_pattern_count"], 0)

    def test_check_passes_on_expected_fixture_outputs(self):
        benchmark.cmd_setup(self.run_dir)

        (self.run_dir / "T2" / benchmark.T2_FILE_NAME).write_text(
            "# Fixture T2 - benchmark Ollama Agent (do not remove this comment)\n"
            "MAX_RETRIES = 5\n"
            "TIMEOUT_SECONDS = 30\n",
            encoding="utf-8",
        )
        (self.run_dir / "T3" / benchmark.T3_FILE_NAME).write_text(
            "def add(a, b):\n    return a + b\n\n"
            "def multiply(a, b):\n    return a * b\n",
            encoding="utf-8",
        )

        results = benchmark.cmd_check(self.run_dir)
        self.assertIsNone(results["T1"]["pass"])
        self.assertTrue(results["T2"]["pass"])
        self.assertTrue(results["T3"]["pass"])

    def test_report_writes_env_and_metrics(self):
        benchmark.cmd_setup(self.run_dir)
        (self.run_dir / "T2" / benchmark.T2_FILE_NAME).write_text(
            "# Fixture T2 - benchmark Ollama Agent (do not remove this comment)\n"
            "MAX_RETRIES = 5\n"
            "TIMEOUT_SECONDS = 30\n",
            encoding="utf-8",
        )
        (self.run_dir / "T3" / benchmark.T3_FILE_NAME).write_text(
            "def add(a, b):\n    return a + b\n\n"
            "def multiply(a, b):\n    return a * b\n",
            encoding="utf-8",
        )

        out_file = self.run_dir / "result.json"
        benchmark.cmd_report(
            run_dir=self.run_dir,
            model="qwen2.5-coder:14b",
            backend="ollama",
            hardware="test cpu / test gpu / 32GB RAM",
            agent_entry="src/agent.py",
            api_base="http://localhost:11434/v1",
            out_file=out_file,
            t1_pass=True,
            t1_time_s=1.2,
            t2_time_s=2.3,
            t3_time_s=3.4,
            t1_tool_calls=4,
            t2_tool_calls=2,
            t3_tool_calls=1,
            notes="test run",
        )

        payload = json.loads(out_file.read_text(encoding="utf-8"))
        self.assertEqual(payload["env"]["backend"], "ollama")
        self.assertEqual(payload["env"]["hardware"], "test cpu / test gpu / 32GB RAM")
        self.assertTrue(payload["results"]["tasks"]["T1"]["pass"])
        self.assertEqual(payload["results"]["metrics"]["T2"]["tool_calls"], 2)


if __name__ == "__main__":
    unittest.main()
