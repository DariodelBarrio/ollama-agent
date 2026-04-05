"""CLI smoke tests for the canonical entry points."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliSmokeTests(unittest.TestCase):
    def _run_help(self, relative_path: str) -> str:
        proc = subprocess.run(
            [sys.executable, str(ROOT / relative_path), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(
            proc.returncode,
            0,
            msg=f"{relative_path} --help failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        output = f"{proc.stdout}\n{proc.stderr}"
        self.assertIn("usage", output.lower())
        return output

    def test_local_agent_help(self):
        output = self._run_help("src/agent.py")
        self.assertIn("--model", output)
        self.assertIn("--api-base", output)
        self.assertIn("--read-only", output)

    def test_hybrid_agent_help(self):
        output = self._run_help("src/hybrid/agent.py")
        self.assertIn("--backend", output)
        self.assertIn("--critic", output)
        self.assertIn("--remote-url", output)
        self.assertIn("--remote-model", output)
        self.assertIn("--read-only", output)

    def test_install_script_help(self):
        output = self._run_help("scripts/install.py")
        self.assertIn("--hybrid", output)
        self.assertNotIn("--mega", output)

    def test_benchmark_script_help(self):
        output = self._run_help("scripts/run_benchmark.py")
        self.assertIn("run-tests", output)
        self.assertIn("report", output)


if __name__ == "__main__":
    unittest.main()
